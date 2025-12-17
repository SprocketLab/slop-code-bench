from __future__ import annotations

import queue
from pathlib import Path
from unittest.mock import Mock
from unittest.mock import patch
from unittest.mock import sentinel

import pytest

from slop_code.agent_runner import runner
from slop_code.agent_runner.agent import Agent
from slop_code.agent_runner.models import UsageTracker
from slop_code.agent_runner.resume import ResumeInfo
from slop_code.common import PROMPT_FILENAME


class StubCheckpoint:
    def __init__(self, name: str, spec_text: str) -> None:
        self.name = name
        self._spec_text = spec_text

    def get_spec_text(self) -> str:
        return self._spec_text


@pytest.mark.parametrize(
    ("path_exists", "is_file", "supports", "expected"),
    [
        (False, False, True, False),
        (True, False, True, False),
        (True, True, False, False),
        (True, True, True, True),
    ],
)
def test_should_run_replay(
    tmp_path: Path,
    path_exists: bool,
    is_file: bool,
    supports: bool,
    expected: bool,
) -> None:
    agent = Mock(spec=Agent)
    agent.supports_replay.return_value = supports

    replay_path = tmp_path / "replay.json"
    if path_exists:
        replay_path.write_text("{}")
        if not is_file:
            replay_path.unlink()
            replay_path.mkdir()

    assert (
        runner._should_run_replay(replay_path if path_exists else None, agent)
        is expected
    )

    if path_exists:
        assert agent.supports_replay.call_count >= 1
    else:
        assert agent.supports_replay.call_count == 0


def test_run_checkpoint_task_uses_replay_when_available() -> None:
    agent = Mock(spec=Agent)
    replay_result = sentinel.replay_result
    agent.run_replay.return_value = replay_result

    with patch(
        "slop_code.agent_runner.runner._should_run_replay",
        return_value=True,
    ):
        result = runner._run_checkpoint_task(
            agent=agent,
            task="ignored",
            checkpoint_name="ckpt",
            replay_path=Path("/tmp/replay.json"),
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
    checkpoint = StubCheckpoint(
        name="checkpoint_one",
        spec_text=(
            "Start with %%%ENTRYPOINT:entry_file%%% and run %%%ENTRYPOINT:entry_command%%%"
        ),
    )
    environment = Mock()
    environment.format_entry_file.return_value = "formatted/main.py"
    environment.get_command.return_value = "uv run formatted/main.py"

    prompt = runner.get_task_for_checkpoint(
        checkpoint=checkpoint,
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
    agent.usage = UsageTracker()

    run_spec = Mock()
    run_spec.problem = Mock()
    run_spec.problem.name = "prob"
    run_spec.problem.checkpoints = {
        "checkpoint_1": Mock(),
        "checkpoint_2": Mock(),
        "checkpoint_3": Mock(),
    }
    run_spec.skip_evaluation = True
    run_spec.pass_policy = Mock()

    resume_info = ResumeInfo(
        resume_from_checkpoint="checkpoint_3",
        completed_checkpoints=["checkpoint_1", "checkpoint_2"],
        last_snapshot_dir=None,
        prior_usage=UsageTracker(),
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
    existing_summary.usage = UsageTracker()

    summary = Mock()
    summary.passed = True
    summary.passed_policy = True
    summary.had_error = False
    summary.checkpoint_name = "checkpoint_3"
    summary.usage = UsageTracker()

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
