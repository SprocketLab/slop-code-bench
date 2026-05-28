from __future__ import annotations

import json
import queue
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import Mock
from unittest.mock import patch
from unittest.mock import sentinel

import pytest

from slop_code.agent_runner import runner
from slop_code.agent_runner.agent import RETRY_PROMPT
from slop_code.agent_runner.agent import Agent
from slop_code.agent_runner.models import AgentCostLimits
from slop_code.agent_runner.models import AgentError
from slop_code.agent_runner.models import UsageTracker
from slop_code.agent_runner.resume import ResumeInfo
from slop_code.common import INFERENCE_RESULT_FILENAME
from slop_code.common import PROMPT_FILENAME
from slop_code.common.llms import TokenUsage
from slop_code.evaluation.report import PassPolicy


class StubCheckpoint:
    def __init__(self, name: str, spec_text: str) -> None:
        self.name = name
        self._spec_text = spec_text

    def get_spec_text(self) -> str:
        return self._spec_text


@dataclass(frozen=True)
class ReplayCase:
    path_exists: bool
    is_file: bool
    supports: bool
    expected: bool


def _usage(cost: float = 0.0, steps: int = 0) -> UsageTracker:
    return UsageTracker(
        cost=cost,
        steps=steps,
        net_tokens=TokenUsage(),
        current_tokens=TokenUsage(),
    )


class RetryProbeAgent(Agent):
    def __init__(
        self,
        *,
        max_retries: int,
        errors: list[Exception],
    ) -> None:
        super().__init__(
            agent_name="retry_probe",
            problem_name="prob",
            cost_limits=AgentCostLimits(
                step_limit=0,
                cost_limit=0.0,
                net_cost_limit=0.0,
                max_retries=max_retries,
            ),
            pricing=None,
            verbose=False,
        )
        self.errors = errors
        self.run_tasks: list[str] = []
        self.retry_count = 0

    @classmethod
    def _from_config(cls, *args: object, **kwargs: object) -> Agent:
        raise NotImplementedError

    def setup(self, session: object) -> None:
        _ = session

    def run(self, task: str) -> None:
        self.run_tasks.append(task)
        if self.errors:
            raise self.errors.pop(0)

    def retry(self) -> None:
        self.retry_count += 1
        self.run(RETRY_PROMPT)

    def reset(self) -> None:
        pass

    def save_artifacts(self, path: Path) -> None:
        _ = path

    def cleanup(self) -> None:
        pass


class CapturingLogger:
    def __init__(self) -> None:
        self.errors: list[tuple[str, dict[str, object]]] = []

    def error(self, event: str, **kwargs: object) -> None:
        self.errors.append((event, kwargs))


def test_run_checkpoint_retries_agent_errors_with_continue_prompt() -> None:
    agent = RetryProbeAgent(
        max_retries=1,
        errors=[AgentError("transient")],
    )

    result = agent.run_checkpoint("full checkpoint prompt")

    assert result.had_error is False
    assert agent.retry_count == 1
    assert agent.run_tasks == ["full checkpoint prompt", RETRY_PROMPT]


def test_run_checkpoint_stops_after_retry_budget() -> None:
    agent = RetryProbeAgent(
        max_retries=1,
        errors=[AgentError("first"), AgentError("second")],
    )

    result = agent.run_checkpoint("full checkpoint prompt")

    assert result.had_error is True
    assert "second" in (result.error_message or "")
    assert agent.retry_count == 1
    assert agent.run_tasks == ["full checkpoint prompt", RETRY_PROMPT]


def test_run_checkpoint_does_not_retry_non_agent_errors() -> None:
    agent = RetryProbeAgent(
        max_retries=3,
        errors=[RuntimeError("programming error")],
    )

    result = agent.run_checkpoint("full checkpoint prompt")

    assert result.had_error is True
    assert "programming error" in (result.error_message or "")
    assert agent.retry_count == 0
    assert agent.run_tasks == ["full checkpoint prompt"]


def test_run_checkpoint_logs_exact_agent_error_message() -> None:
    agent = RetryProbeAgent(
        max_retries=0,
        errors=[AgentError("provider said: rate limit exceeded")],
    )
    logger = CapturingLogger()
    agent.log = logger  # type: ignore[assignment]

    agent.run_checkpoint("full checkpoint prompt")

    assert logger.errors
    _, kwargs = logger.errors[0]
    assert kwargs["error_message"] == "provider said: rate limit exceeded"


def test_agent_cost_limits_default_to_two_retries() -> None:
    limits = AgentCostLimits(
        step_limit=0,
        cost_limit=0.0,
        net_cost_limit=0.0,
    )

    assert limits.max_retries == 2


@pytest.mark.parametrize(
    "case",
    [
        ReplayCase(
            path_exists=False, is_file=False, supports=True, expected=False
        ),
        ReplayCase(
            path_exists=True, is_file=False, supports=True, expected=False
        ),
        ReplayCase(
            path_exists=True, is_file=True, supports=False, expected=False
        ),
        ReplayCase(
            path_exists=True, is_file=True, supports=True, expected=True
        ),
    ],
)
def test_should_run_replay(
    tmp_path: Path,
    case: ReplayCase,
) -> None:
    agent = Mock(spec=Agent)
    agent.supports_replay.return_value = case.supports

    replay_path = tmp_path / "replay.json"
    if case.path_exists:
        replay_path.write_text("{}")
        if not case.is_file:
            replay_path.unlink()
            replay_path.mkdir()

    assert (
        runner._should_run_replay(
            replay_path if case.path_exists else None, agent
        )
        is case.expected
    )

    if case.path_exists:
        assert agent.supports_replay.call_count >= 1
    else:
        assert agent.supports_replay.call_count == 0


def test_run_checkpoint_task_uses_replay_when_available(
    tmp_path: Path,
) -> None:
    agent = Mock(spec=Agent)
    replay_result = sentinel.replay_result
    agent.run_replay.return_value = replay_result
    replay_path = tmp_path / "replay.json"

    with patch(
        "slop_code.agent_runner.runner._should_run_replay",
        return_value=True,
    ):
        result = runner._run_checkpoint_task(
            agent=agent,
            task="ignored",
            checkpoint_name="ckpt",
            replay_path=replay_path,
        )

    assert result is replay_result
    agent.run_replay.assert_called_once()
    agent.run_checkpoint.assert_not_called()


def test_run_checkpoint_task_runs_inference_when_no_replay() -> None:
    agent = Mock(spec=Agent)
    inference_result = sentinel.inference_result
    agent.run_checkpoint.return_value = inference_result

    with patch(
        "slop_code.agent_runner.runner._should_run_replay",
        return_value=False,
    ):
        result = runner._run_checkpoint_task(
            agent=agent,
            task="solve this",
            checkpoint_name="ckpt",
            replay_path=None,
        )

    assert result is inference_result
    agent.run_checkpoint.assert_called_once_with("solve this")
    agent.run_replay.assert_not_called()


def test_get_task_for_checkpoint_renders_prompt_and_writes_file(
    tmp_path: Path,
) -> None:
    spec_text = "Start with %%%ENTRYPOINT:entry_file%%% and run %%%ENTRYPOINT:entry_command%%%"
    environment = Mock()
    environment.format_entry_file.return_value = "formatted/main.py"
    environment.get_command.return_value = "uv run formatted/main.py"

    prompt = runner.get_task_for_checkpoint(
        checkpoint_name="checkpoint_1",
        spec_text=spec_text,
        template="{{ 'CONT' if is_continuation else 'START' }} :: {{ spec }}",
        entry_file="main.py",
        environment=environment,
        is_first_checkpoint=True,
        output_path=tmp_path,
    )

    expected_text = (
        "START :: Start with formatted/main.py and run uv run formatted/main.py"
    )
    assert prompt == expected_text

    written = (tmp_path / PROMPT_FILENAME).read_text()
    assert written == expected_text

    environment.format_entry_file.assert_called_once_with("main.py")
    environment.get_command.assert_called_once_with(
        "main.py", is_agent_run=True
    )


def test_get_task_for_checkpoint_includes_agent_info_in_context(
    tmp_path: Path,
) -> None:
    """Test that agent_type, agent_version, and model_name are available in templates."""
    spec_text = "Test spec"
    environment = Mock()
    environment.format_entry_file.return_value = "main.py"
    environment.get_command.return_value = "python main.py"

    template = (
        "Agent: {{ agent_type }} v{{ agent_version }} | "
        "Model: {{ model_name }} | "
        "{{ spec }}"
    )

    prompt = runner.get_task_for_checkpoint(
        checkpoint_name="checkpoint_1",
        spec_text=spec_text,
        template=template,
        entry_file="main.py",
        environment=environment,
        is_first_checkpoint=True,
        output_path=tmp_path,
        agent_type="claude_code",
        agent_version="2.0.51",
        model_name="opus-4.5",
    )

    expected = "Agent: claude_code v2.0.51 | Model: opus-4.5 | Test spec"
    assert prompt == expected


def test_get_task_for_checkpoint_handles_none_agent_version(
    tmp_path: Path,
) -> None:
    """Test that None agent_version renders as empty string."""
    environment = Mock()
    environment.format_entry_file.return_value = "main.py"
    environment.get_command.return_value = "python main.py"

    template = "Agent: {{ agent_type }}{% if agent_version %}-{{ agent_version }}{% endif %}"

    prompt = runner.get_task_for_checkpoint(
        checkpoint_name="checkpoint_1",
        spec_text="spec",
        template=template,
        entry_file="main.py",
        environment=environment,
        is_first_checkpoint=True,
        output_path=tmp_path,
        agent_type="gemini",
        agent_version=None,
        model_name="gemini-2.0",
    )

    # agent_version is converted to "" when None, so conditional is false
    assert prompt == "Agent: gemini"


def test_create_agent_session_uses_static_assets_and_environment() -> None:
    problem_config = Mock()
    problem_config.path = Path("/problem")
    problem_config.static_assets = {"foo": "bar"}
    environment_spec = Mock()

    resolved_assets = {"foo": sentinel.asset}
    with (
        patch(
            "slop_code.agent_runner.runner.resolve_static_assets",
            return_value=resolved_assets,
        ) as resolve_assets,
        patch(
            "slop_code.agent_runner.runner.Session.from_environment_spec",
            return_value=sentinel.session,
        ) as from_env_spec,
    ):
        session = runner.create_agent_session(problem_config, environment_spec)

    assert session is sentinel.session
    resolve_assets.assert_called_once_with(
        base_path=problem_config.path,
        assets=problem_config.static_assets,
    )
    from_env_spec.assert_called_once_with(
        spec=environment_spec,
        base_dir=None,
        static_assets=resolved_assets,
        is_agent_infer=True,
    )


def test_run_problem_resume_does_not_treat_first_executed_as_checkpoint_1(
    tmp_path: Path,
) -> None:
    """When resuming and skipping early checkpoints, continuation must be true.

    This ensures `_run_problem()` only treats the real `checkpoint_1` as the
    first checkpoint for prompt rendering purposes.
    """

    agent = Mock(spec=Agent)
    agent.usage = _usage()

    run_spec = Mock()
    run_spec.problem = Mock()
    run_spec.problem.name = "prob"
    run_spec.problem.checkpoints = {
        "checkpoint_1": Mock(),
        "checkpoint_2": Mock(),
        "checkpoint_3": Mock(),
    }
    run_spec.skip_evaluation = True
    run_spec.concurrent_evaluation = False
    run_spec.pass_policy = Mock()

    resume_info = ResumeInfo(
        resume_from_checkpoint="checkpoint_3",
        completed_checkpoints=["checkpoint_1", "checkpoint_2"],
        last_snapshot_dir=None,
        prior_usage=_usage(),
    )

    ar = runner.AgentRunner(
        run_spec=run_spec,
        agent=agent,
        output_path=tmp_path,
        progress_queue=queue.Queue(),
        resume_info=resume_info,
    )

    checkpoints = [
        (StubCheckpoint("checkpoint_1", ""), tmp_path / "checkpoint_1"),
        (StubCheckpoint("checkpoint_2", ""), tmp_path / "checkpoint_2"),
        (StubCheckpoint("checkpoint_3", ""), tmp_path / "checkpoint_3"),
    ]

    existing_summary = Mock()
    existing_summary.usage = _usage()

    summary = Mock()
    summary.passed = True
    summary.passed_policy = True
    summary.had_error = False
    summary.checkpoint_name = "checkpoint_3"
    summary.usage = _usage()

    with (
        patch(
            "slop_code.agent_runner.runner.get_checkpoints",
            return_value=iter(checkpoints),
        ),
        patch.object(
            runner.AgentRunner,
            "_load_checkpoint_summary",
            return_value=existing_summary,
        ),
        patch.object(
            runner.AgentRunner,
            "_run_checkpoint",
            return_value=summary,
        ) as run_ckpt,
    ):
        ar._run_problem()

    # Only checkpoint_3 should be executed, and it must not be treated as
    # "first" just because it's the first executed after resume.
    run_ckpt.assert_called_once()
    _, _, is_first_checkpoint = run_ckpt.call_args.args
    assert is_first_checkpoint is False


def test_run_problem_resume_does_not_double_count_prior_usage(
    tmp_path: Path,
) -> None:
    """Skipped checkpoints are already included in resume_info.prior_usage."""

    agent = Mock(spec=Agent)
    agent.usage = _usage(cost=4.0, steps=40)

    run_spec = Mock()
    run_spec.problem = Mock()
    run_spec.problem.name = "prob"
    run_spec.problem.checkpoints = {
        "checkpoint_1": Mock(),
        "checkpoint_2": Mock(),
        "checkpoint_3": Mock(),
    }
    run_spec.skip_evaluation = True
    run_spec.concurrent_evaluation = False
    run_spec.pass_policy = Mock()

    resume_info = ResumeInfo(
        resume_from_checkpoint="checkpoint_3",
        completed_checkpoints=["checkpoint_1", "checkpoint_2"],
        last_snapshot_dir=None,
        prior_usage=_usage(cost=3.0, steps=30),
    )

    ar = runner.AgentRunner(
        run_spec=run_spec,
        agent=agent,
        output_path=tmp_path,
        progress_queue=queue.Queue(),
        resume_info=resume_info,
    )
    ar.metrics_tracker.usage = resume_info.prior_usage.model_copy(deep=True)

    checkpoints = [
        (StubCheckpoint("checkpoint_1", ""), tmp_path / "checkpoint_1"),
        (StubCheckpoint("checkpoint_2", ""), tmp_path / "checkpoint_2"),
        (StubCheckpoint("checkpoint_3", ""), tmp_path / "checkpoint_3"),
    ]

    skipped_summaries = [
        Mock(usage=_usage(cost=1.0, steps=10)),
        Mock(usage=_usage(cost=2.0, steps=20)),
    ]

    summary = Mock()
    summary.passed_policy = True
    summary.had_error = False
    summary.checkpoint_name = "checkpoint_3"
    summary.usage = agent.usage

    with (
        patch(
            "slop_code.agent_runner.runner.get_checkpoints",
            return_value=iter(checkpoints),
        ),
        patch.object(
            runner.AgentRunner,
            "_load_checkpoint_summary",
            side_effect=skipped_summaries,
        ),
        patch.object(
            runner.AgentRunner,
            "_run_checkpoint",
            return_value=summary,
        ),
    ):
        ar._run_problem()

    assert ar.metrics_tracker.usage.cost == 7.0
    assert ar.metrics_tracker.usage.steps == 70


def test_run_problem_resume_does_not_duplicate_preloaded_checkpoint_results(
    tmp_path: Path,
) -> None:
    """Resume should keep one checkpoint result entry per checkpoint."""

    agent = Mock(spec=Agent)
    agent.usage = _usage(cost=4.0, steps=40)

    run_spec = Mock()
    run_spec.problem = Mock()
    run_spec.problem.name = "prob"
    run_spec.problem.checkpoints = {
        "checkpoint_1": Mock(),
        "checkpoint_2": Mock(),
        "checkpoint_3": Mock(),
    }
    run_spec.compress_artifacts = False
    run_spec.skip_evaluation = True
    run_spec.concurrent_evaluation = False
    run_spec.pass_policy = Mock()

    resume_info = ResumeInfo(
        resume_from_checkpoint="checkpoint_3",
        completed_checkpoints=["checkpoint_1", "checkpoint_2"],
        last_snapshot_dir=None,
        prior_usage=_usage(cost=3.0, steps=30),
    )

    ar = runner.AgentRunner(
        run_spec=run_spec,
        agent=agent,
        output_path=tmp_path,
        progress_queue=queue.Queue(),
        resume_info=resume_info,
    )
    ar.metrics_tracker.usage = resume_info.prior_usage.model_copy(deep=True)
    # Mimic setup() preloading completed checkpoint results.
    ar.metrics_tracker.record_checkpoint_result("checkpoint_1", None)
    ar.metrics_tracker.record_checkpoint_result("checkpoint_2", None)

    for checkpoint_name, usage in (
        ("checkpoint_1", {"cost": 1.0, "steps": 10}),
        ("checkpoint_2", {"cost": 2.0, "steps": 20}),
    ):
        checkpoint_dir = tmp_path / checkpoint_name
        checkpoint_dir.mkdir()
        with (checkpoint_dir / INFERENCE_RESULT_FILENAME).open("w") as f:
            json.dump({"usage": usage, "had_error": False}, f)

    checkpoints = [
        (StubCheckpoint("checkpoint_1", ""), tmp_path / "checkpoint_1"),
        (StubCheckpoint("checkpoint_2", ""), tmp_path / "checkpoint_2"),
        (StubCheckpoint("checkpoint_3", ""), tmp_path / "checkpoint_3"),
    ]

    summary = Mock()
    summary.passed_policy = True
    summary.had_error = False
    summary.checkpoint_name = "checkpoint_3"
    summary.usage = agent.usage

    def _run_checkpoint_side_effect(*args: object, **kwargs: object) -> Mock:
        ar.metrics_tracker.record_checkpoint_result("checkpoint_3", None)
        return summary

    with (
        patch(
            "slop_code.agent_runner.runner.get_checkpoints",
            return_value=iter(checkpoints),
        ),
        patch.object(
            runner.AgentRunner,
            "_run_checkpoint",
            side_effect=_run_checkpoint_side_effect,
        ),
    ):
        ar._run_problem()

    assert [r.name for r in ar.metrics_tracker.checkpoint_results] == [
        "checkpoint_1",
        "checkpoint_2",
        "checkpoint_3",
    ]


def test_run_problem_concurrent_eval_bounds_inflight(tmp_path):
    """Concurrent eval runs in a rolling background thread.

    Verifies: every checkpoint is evaluated, AT MOST ONE eval is in flight at
    a time (so in-flight containers stay bounded to 1 solve + 1 eval), reports
    are merged back into the summaries, and the run does not deadlock.
    """
    agent = Mock(spec=Agent)
    agent.usage = _usage()

    run_spec = Mock()
    run_spec.problem = Mock()
    run_spec.problem.name = "prob"
    run_spec.problem.checkpoints = {
        f"checkpoint_{i}": Mock() for i in range(1, 5)
    }
    run_spec.skip_evaluation = False
    run_spec.concurrent_evaluation = True
    run_spec.environment = Mock()
    run_spec.pass_policy = Mock()
    run_spec.pass_policy.check.return_value = True

    ar = runner.AgentRunner(
        run_spec=run_spec,
        agent=agent,
        output_path=tmp_path,
        progress_queue=queue.Queue(),
    )

    names = [f"checkpoint_{i}" for i in range(1, 5)]
    checkpoints = [(StubCheckpoint(n, ""), tmp_path / n) for n in names]

    def make_summary(name: str) -> Mock:
        s = Mock()
        s.checkpoint_name = name
        s.had_error = False
        s.passed_policy = None
        s.snapshot_dir = tmp_path / name / "snapshot"
        s.path = tmp_path / name
        s.artifacts = tmp_path / name / "artifacts"
        s.usage = _usage()
        return s

    solved: list[str] = []

    def fake_run_checkpoint(checkpoint, save_dir, is_first):  # noqa: ANN001
        solved.append(checkpoint.name)
        time.sleep(0.02)  # let an eval overlap the next solve
        return make_summary(checkpoint.name)

    inflight = {"cur": 0, "max": 0}
    lock = threading.Lock()
    evaluated: list[str] = []

    def fake_eval(*, checkpoint, save_dir, snapshot_dir, problem, environment):  # noqa: ANN001
        with lock:
            inflight["cur"] += 1
            inflight["max"] = max(inflight["max"], inflight["cur"])
        time.sleep(0.05)
        with lock:
            inflight["cur"] -= 1
            evaluated.append(checkpoint.name)
        return (Mock(), None)

    with (
        patch(
            "slop_code.agent_runner.runner.get_checkpoints",
            return_value=iter(checkpoints),
        ),
        patch.object(
            runner.AgentRunner,
            "_run_checkpoint",
            side_effect=fake_run_checkpoint,
        ),
        patch(
            "slop_code.agent_runner.runner.evaluate_agent_snapshot",
            side_effect=fake_eval,
        ),
        patch.object(runner.MetricsTracker, "record_checkpoint_result"),
        patch.object(runner.MetricsTracker, "finish_checkpoint"),
    ):
        results = ar._run_problem()

    assert solved == names
    assert sorted(evaluated) == sorted(names)
    # The core guarantee: never more than one eval running at once.
    assert inflight["max"] == 1
    # Reports folded back; one summary per checkpoint.
    assert len(results) == 4
    assert all(n in ar._eval_reports for n in names)


def test_run_problem_concurrent_eval_records_failure_and_continues(
    tmp_path: Path,
) -> None:
    """Concurrent eval that raises must record into `_failed_evals`, warn at
    the next cp boundary + at end-of-run, and let subsequent cps proceed.
    """
    agent = Mock(spec=Agent)
    agent.usage = _usage()

    run_spec = Mock()
    run_spec.problem = Mock()
    run_spec.problem.name = "prob"
    run_spec.problem.checkpoints = {
        "checkpoint_1": Mock(),
        "checkpoint_2": Mock(),
        "checkpoint_3": Mock(),
    }
    run_spec.skip_evaluation = False
    run_spec.concurrent_evaluation = True
    # Use a real PassPolicy so _merge_eval_reports can rebuild summaries via
    # AgentCheckpointSummary.from_results (which validates with pydantic).
    run_spec.pass_policy = PassPolicy.ANY_CASE

    ar = runner.AgentRunner(
        run_spec=run_spec,
        agent=agent,
        output_path=tmp_path,
        progress_queue=queue.Queue(),
        resume_info=None,
    )

    checkpoints = [
        (StubCheckpoint(f"checkpoint_{i}", ""), tmp_path / f"checkpoint_{i}")
        for i in (1, 2, 3)
    ]

    def make_summary(cp_name: str) -> Mock:
        s = Mock()
        s.passed_policy = True  # so _should_early_stop doesn't fire
        s.had_error = False
        s.checkpoint_name = cp_name
        s.snapshot_dir = tmp_path / f"{cp_name}_snap"  # truthy => eval queued
        s.path = tmp_path / cp_name
        s.artifacts = []
        s.usage = _usage()
        return s

    summaries = {f"checkpoint_{i}": make_summary(f"checkpoint_{i}") for i in (1, 2, 3)}
    eval_calls: list[str] = []

    def make_report() -> Mock:
        """Minimal mock report that record_checkpoint_result can sum over."""
        r = Mock()
        r.pass_counts = {"Core": 1}
        r.total_counts = {"Core": 1}
        return r

    def eval_snapshot_side_effect(*, checkpoint, **_kwargs):
        eval_calls.append(checkpoint.name)
        if checkpoint.name == "checkpoint_1":
            raise RuntimeError("boom: simulated eval failure")
        return (make_report(), Mock())

    with (
        patch(
            "slop_code.agent_runner.runner.get_checkpoints",
            return_value=iter(checkpoints),
        ),
        patch.object(
            runner.AgentRunner,
            "_run_checkpoint",
            side_effect=lambda ckpt, *_a, **_kw: summaries[ckpt.name],
        ),
        patch(
            "slop_code.agent_runner.runner.evaluate_agent_snapshot",
            side_effect=eval_snapshot_side_effect,
        ),
        # Bypass _merge_eval_reports — it rebuilds pydantic-validated
        # summaries which is orthogonal to what we're testing.
        patch.object(
            runner.AgentRunner,
            "_merge_eval_reports",
            side_effect=lambda r: r,
        ),
        patch.object(runner.logger, "warning") as mock_warning,
    ):
        ar._run_problem()

    # 1. cp1's failure is recorded with the exception text; cp2/cp3 are not.
    assert "checkpoint_1" in ar._failed_evals
    assert "boom" in ar._failed_evals["checkpoint_1"]
    assert "checkpoint_2" not in ar._failed_evals
    assert "checkpoint_3" not in ar._failed_evals

    # 2. Subsequent cps still ran — all 3 evals were attempted in order.
    assert eval_calls == ["checkpoint_1", "checkpoint_2", "checkpoint_3"]

    # 3. Boundary warning fired exactly once for cp1 (at cp2's boundary).
    boundary_warnings = [
        call for call in mock_warning.call_args_list
        if call.args
        and "Concurrent eval failed for earlier checkpoint" in call.args[0]
        and call.kwargs.get("checkpoint") == "checkpoint_1"
    ]
    assert len(boundary_warnings) == 1, (
        f"expected 1 boundary warning for cp1, got "
        f"{len(boundary_warnings)}: {boundary_warnings}"
    )

    # 4. End-of-run summary warning lists cp1 as a failed eval.
    summary_warnings = [
        call for call in mock_warning.call_args_list
        if call.args and "Run completed with concurrent eval failures" in call.args[0]
    ]
    assert len(summary_warnings) == 1
    assert summary_warnings[0].kwargs.get("failed_checkpoints") == ["checkpoint_1"]
    assert summary_warnings[0].kwargs.get("count") == 1
