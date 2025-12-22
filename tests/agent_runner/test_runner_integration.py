from __future__ import annotations

import queue
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

from slop_code.agent_runner import runner
from slop_code.agent_runner.agent import Agent
from slop_code.agent_runner.agent import AgentConfigBase
from slop_code.agent_runner.models import AgentCostLimits
from slop_code.agent_runner.models import AgentRunSpec
from slop_code.agent_runner.state import AgentStateEnum
from slop_code.common import AGENT_DIR_NAME
from slop_code.common import PROMPT_FILENAME
from slop_code.evaluation import GroupType
from slop_code.evaluation import PassPolicy


class FakeDiff:
    def model_dump_json(self) -> str:  # pragma: no cover - trivial wrapper
        return "{}"


class FakeSession:
    def __init__(self, working_dir: Path) -> None:
        self.working_dir = working_dir
        self.working_dir.mkdir(parents=True, exist_ok=True)
        self.closed = False
        self.finished_snapshots: list[Path] = []

    def __enter__(self) -> FakeSession:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.closed = True

    def finish_checkpoint(self, snapshot_dir: Path) -> FakeDiff:
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        self.finished_snapshots.append(snapshot_dir)
        return FakeDiff()


@dataclass
class StubCheckpoint:
    name: str
    spec_text: str

    def get_spec_text(self) -> str:
        return self.spec_text


class StubEnvironment:
    def format_entry_file(self, entry_file: str) -> str:
        return f"formatted/{entry_file}"

    def get_command(self, entry_file: str, *, is_agent_run: bool) -> str:
        suffix = "agent" if is_agent_run else "eval"
        return f"run-{suffix} {entry_file}"


class FailingAgent(Agent):
    def __init__(self) -> None:
        super().__init__(
            agent_name="failing",
            problem_name="stub",
            cost_limits=AgentCostLimits(
                step_limit=10,
                cost_limit=100.0,
                net_cost_limit=200.0,
            ),
            pricing=None,
            verbose=False,
        )
        self._failures = 0
        self.saved_paths: list[Path] = []

    def setup(self, session: FakeSession) -> None:
        self.session = session

    def run(self, task: str) -> None:
        self.usage.steps += 1
        self.usage.cost += 1.0
        self.usage.current_tokens.input += 10
        self.usage.net_tokens.input += 10
        if self._failures == 0:
            self._failures += 1
            raise RuntimeError("boom")

    def reset(self) -> None:
        pass

    def save_artifacts(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        self.saved_paths.append(path)
        (path / "artifact.txt").write_text("artifact", encoding="utf-8")

    def cleanup(self) -> None:
        pass

    @classmethod
    def _from_config(
        cls,
        config: AgentConfigBase,
        problem_name: str,
        verbose: bool,
        image: str | None,
    ) -> Agent:
        raise NotImplementedError("FailingAgent is for testing only")


def fake_quality_metrics():
    """Create a fake SnapshotQualityReport for testing."""
    from slop_code.metrics import LineCountMetrics
    from slop_code.metrics import SnapshotQualityReport

    return SnapshotQualityReport(
        files=0,
        source_files=0,
        overall_lines=LineCountMetrics(
            total_lines=0,
            loc=0,
            comments=0,
            multi_comment=0,
            single_comment=0,
        ),
        lint_errors=0,
        lint_fixable=0,
        cc_counts={},
        mi={},
    )


class FakeReport:
    def __init__(self, *, passed: bool) -> None:
        self.passed = passed
        self.pass_counts = {
            GroupType.FUNCTIONALITY: int(passed),
            GroupType.ERROR: 0,
        }
        self.total_counts = {GroupType.FUNCTIONALITY: 1, GroupType.ERROR: 0}
        score = 1.0 if passed else 0.0

        class _FakeGroupReport:
            def __init__(
                self, group_type: GroupType, results: dict[str, float]
            ):
                self.type = group_type
                self.results = results

        self.group_outcomes = {
            GroupType.FUNCTIONALITY.value: _FakeGroupReport(
                GroupType.FUNCTIONALITY,
                {"case": score},
            ),
            GroupType.ERROR.value: _FakeGroupReport(
                GroupType.ERROR,
                {},
            ),
        }

    def save(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)


class StubProblem:
    def __init__(self, checkpoints: list[str]) -> None:
        self.name = "stub_problem"
        self.version = 1
        self.entry_file = "main.py"
        self.checkpoints = checkpoints


def _make_run_spec(
    problem: StubProblem,
    environment: StubEnvironment,
    *,
    compress_artifacts: bool = False,
) -> AgentRunSpec:
    return AgentRunSpec.model_construct(
        seed=123,
        template="{{ spec }}",
        problem=problem,
        environment=environment,
        pass_policy=PassPolicy.ANY,
        skip_evaluation=False,
        verbose=False,
        compress_artifacts=compress_artifacts,
    )


def test_agent_runner_stops_after_failed_checkpoint(tmp_path: Path) -> None:
    problem = StubProblem(["first", "second"])
    environment = StubEnvironment()
    run_spec = _make_run_spec(problem, environment)
    agent = FailingAgent()

    progress_queue: queue.Queue = queue.Queue()
    output_path = tmp_path / "outputs"
    output_path.mkdir(parents=True, exist_ok=True)

    workspace = tmp_path / "workspace"
    fake_session = FakeSession(workspace)
    checkpoints = [
        StubCheckpoint(name="first", spec_text="Spec for first"),
        StubCheckpoint(name="second", spec_text="Spec for second"),
    ]
    checkpoint_dirs = []
    for checkpoint in checkpoints:
        ckpt_dir = output_path / checkpoint.name
        ckpt_dir.mkdir(parents=True, exist_ok=True)
        checkpoint_dirs.append((checkpoint, ckpt_dir))

    saved_results: dict | None = None

    def _save_results(results, metrics, _run_spec, _output_dir):
        nonlocal saved_results
        # Build checkpoint state dict
        checkpoints_state = {}
        for summary in results:
            if summary.had_error:
                checkpoints_state[summary.checkpoint_name] = "error"
            else:
                checkpoints_state[summary.checkpoint_name] = "ran"
        saved_results = {
            "summary": {
                "state": metrics.state.value,
                "checkpoints": checkpoints_state,
                "passed": False,
                "passed_policy": False,
                "total_cost": metrics.usage.cost,
            },
        }
        return saved_results

    with (
        patch(
            "slop_code.agent_runner.runner.create_agent_session",
            return_value=fake_session,
        ),
        patch(
            "slop_code.agent_runner.runner.reporting.setup_run_output_directory",
            return_value=None,
        ),
        patch(
            "slop_code.agent_runner.runner.get_checkpoints",
            side_effect=lambda *_args, **_kwargs: iter(checkpoint_dirs),
        ),
        patch(
            "slop_code.agent_runner.runner.evaluate_agent_snapshot",
            side_effect=[(FakeReport(passed=False), fake_quality_metrics())],
        ) as evaluate,
        patch(
            "slop_code.agent_runner.runner.reporting.save_results",
            side_effect=_save_results,
        ),
    ):
        runner_instance = runner.AgentRunner(
            run_spec=run_spec,
            agent=agent,
            output_path=output_path,
            progress_queue=progress_queue,
        )

        result = runner_instance.run()

    assert saved_results == result
    assert saved_results == {
        "summary": {
            "state": AgentStateEnum.ERROR.value,
            "checkpoints": {"first": "error"},
            "passed": False,
            "passed_policy": False,
            "total_cost": agent.usage.cost,
        },
    }
    assert evaluate.call_count == 1
    assert fake_session.closed is True

    assert (output_path / "first" / PROMPT_FILENAME).exists()
    artifacts_dir = output_path / "first" / AGENT_DIR_NAME
    assert artifacts_dir.exists()

    assert agent.usage.steps == 1
    assert not progress_queue.empty()

    assert runner_instance.metrics_tracker.state is AgentStateEnum.ERROR
    assert (
        runner_instance.results
        and runner_instance.results[0].checkpoint_name == "first"
    )
    assert list(fake_session.finished_snapshots)

    if runner_instance.progress_thread:
        runner_instance.progress_thread.join(timeout=1)
