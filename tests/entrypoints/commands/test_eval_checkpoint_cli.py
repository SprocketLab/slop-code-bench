from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from unittest.mock import patch

from rich.console import Console as RichConsole

from slop_code.evaluation.config import CheckpointConfig
from slop_code.evaluation.report import CorrectnessResults
from slop_code.evaluation.report import GroupType
from slop_code.evaluation.report import TestResult as EvalTestResult
from slop_code.entrypoints.commands.eval_checkpoint import evaluate_snapshot


def test_eval_snapshot_renders_pytest_results(tmp_path: Path) -> None:
    snapshot_dir = tmp_path / "snapshot"
    snapshot_dir.mkdir()
    save_dir = tmp_path / "output"

    checkpoint = CheckpointConfig(
        name="checkpoint_1",
        version=1,
        order=1,
        timeout=10,
        env={},
    )

    problem = MagicMock()
    problem.iterate_checkpoint_items.return_value = [("checkpoint_1", checkpoint)]

    results = CorrectnessResults(
        problem_name="problem",
        problem_version=1,
        checkpoint_name="checkpoint_1",
        checkpoint_version=1,
        duration=1.0,
        entrypoint="python main.py",
        pytest_exit_code=0,
        pytest_collected=2,
    )
    results.add_test_result(
        EvalTestResult(
            id="test_core",
            checkpoint="checkpoint_1",
            group_type=GroupType.CORE,
            status="passed",
            duration_ms=12.5,
            file_path="tests/test_checkpoint_1.py",
        )
    )
    results.add_test_result(
        EvalTestResult(
            id="test_optional",
            checkpoint="checkpoint_1",
            group_type=GroupType.FUNCTIONALITY,
            status="failed",
            duration_ms=7.5,
            file_path="tests/test_checkpoint_1.py",
            failure_message="boom",
        )
    )

    stub_report = MagicMock()
    stub_report.report = results

    ctx = SimpleNamespace(
        obj=SimpleNamespace(problem_path=tmp_path, verbosity=1)
    )

    recorded_console: dict[str, RichConsole] = {}

    def _console_factory(*args: object, **kwargs: object) -> RichConsole:
        console = RichConsole(record=True, width=120)
        recorded_console["console"] = console
        return console

    with (
        patch(
            "slop_code.entrypoints.commands.eval_checkpoint.common.load_problem_config_or_exit",
            return_value=problem,
        ),
        patch(
            "slop_code.entrypoints.commands.eval_checkpoint.config_loader.resolve_environment",
            return_value=MagicMock(),
        ),
        patch(
            "slop_code.entrypoints.commands.eval_checkpoint.common.ensure_docker_ready",
            return_value=None,
        ),
        patch(
            "slop_code.entrypoints.commands.eval_checkpoint.common.setup_command_logging",
            return_value=MagicMock(),
        ),
        patch(
            "slop_code.entrypoints.commands.eval_checkpoint.evaluate_checkpoint",
            return_value=stub_report,
        ),
        patch(
            "slop_code.entrypoints.commands.eval_checkpoint.Console",
            side_effect=_console_factory,
        ),
    ):
        evaluate_snapshot(
            ctx=ctx,
            snapshot_dir=snapshot_dir,
            save_dir=save_dir,
            problem_name="problem",
            checkpoint_num=1,
            env_config=tmp_path / "env.yaml",
            rubric_path=None,
            rubric_model=None,
            rubric_temperature=0.0,
            rubric_provider=MagicMock(),
        )

    output = recorded_console["console"].export_text()
    assert "Execution Summary" in output
    assert "Status Summary" in output
    assert "Test Results" in output
    assert "Group Summary" in output
    assert GroupType.CORE.value in output
    assert GroupType.FUNCTIONALITY.value in output
    assert "failed" in output
