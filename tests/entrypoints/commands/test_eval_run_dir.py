"""Tests for evaluate_agent_run command behavior."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast
from unittest.mock import MagicMock

import yaml

from slop_code.common import CHECKPOINT_RESULTS_FILENAME
from slop_code.common import CONFIG_FILENAME
from slop_code.common import PROBLEM_CONFIG_NAME
from slop_code.entrypoints.commands import eval_run_dir
from slop_code.entrypoints.commands.eval_run_dir import (
    _is_evaluation_schema_current,
)
from slop_code.entrypoints.commands.eval_run_dir import (
    _is_problem_fully_evaluated,
)
from slop_code.evaluation import EVALUATION_SCHEMA_VERSION
from slop_code.evaluation import PassPolicy
from slop_code.evaluation import ProblemConfig

if TYPE_CHECKING:
    import typer


REQUIRED_EVAL_FIELDS = {
    "problem_name": "test_problem",
    "problem_version": 1,
    "checkpoint_name": "checkpoint_1",
    "checkpoint_version": 1,
    "duration": 1.0,
    "entrypoint": "python main.py",
    "tests": {},
    "pass_counts": {},
    "total_counts": {},
    "pytest_exit_code": 0,
    "pytest_collected": 0,
    "infrastructure_failure": False,
}


def _create_run_dir(tmp_path: Path) -> Path:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "environment.yaml").write_text("type: fake\n")
    (run_dir / CONFIG_FILENAME).write_text("name: test-run\n")
    return run_dir


def _create_checkpoint(
    problem_dir: Path,
    checkpoint_name: str,
    *,
    schema_current: bool,
) -> None:
    checkpoint_dir = problem_dir / checkpoint_name
    checkpoint_dir.mkdir(parents=True)

    data = dict(REQUIRED_EVAL_FIELDS)
    data["checkpoint_name"] = checkpoint_name
    if schema_current:
        data["schema_version"] = EVALUATION_SCHEMA_VERSION

    (checkpoint_dir / "evaluation.json").write_text(json.dumps(data))

    eval_dir = checkpoint_dir / "evaluation"
    eval_dir.mkdir()
    (eval_dir / "stdout.txt").write_text("")
    (eval_dir / "stderr.txt").write_text("")
    (eval_dir / "report.json").write_text("{}")


def _mock_source_problem(name: str) -> MagicMock:
    source_problem = MagicMock(spec=ProblemConfig)
    source_problem.name = name
    source_problem.model_dump.return_value = {
        "name": name,
        "version": 1,
        "adapter": "python",
        "static_assets": None,
        "checkpoints": {
            "checkpoint_1": {
                "name": "checkpoint_1",
                "version": 1,
                "order": 1,
                "groups": {},
            }
        },
    }
    source_problem.iterate_checkpoint_items.return_value = []
    return source_problem


def _eval_summary() -> SimpleNamespace:
    return SimpleNamespace(
        successful=1,
        failed=0,
        total_checkpoints=1,
        format_summary=lambda: "summary",
    )


def _ctx(tmp_path: Path) -> typer.Context:
    return cast(
        "typer.Context",
        SimpleNamespace(
            obj=SimpleNamespace(
                verbosity=0,
                scbench_home=tmp_path / "scbench-home",
            )
        ),
    )


def _stub_eval_dependencies(
    monkeypatch,
    tmp_path: Path,
    available_problems: dict[str, MagicMock],
    *,
    evaluate_result: tuple[object | None, SimpleNamespace] | None = None,
) -> MagicMock:
    evaluate_mock = MagicMock(
        return_value=evaluate_result or (None, _eval_summary())
    )

    monkeypatch.setattr(
        eval_run_dir.config_loader,
        "resolve_environment",
        lambda _path: object(),
    )
    monkeypatch.setattr(
        eval_run_dir.common,
        "ensure_docker_ready",
        lambda _environment: None,
    )
    monkeypatch.setattr(
        eval_run_dir.common,
        "setup_command_logging",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        eval_run_dir.common,
        "resolve_problem_catalog_root",
        lambda _ctx: tmp_path / "problems",
    )
    monkeypatch.setattr(
        eval_run_dir,
        "get_available_problems",
        lambda _problem_path: available_problems,
    )
    monkeypatch.setattr(
        eval_run_dir,
        "_write_problem_and_checkpoint_configs",
        lambda _problem_dir, _source_problem: None,
    )
    monkeypatch.setattr(
        eval_run_dir.ProblemConfig,
        "from_yaml",
        lambda _path: MagicMock(spec=ProblemConfig),
    )
    monkeypatch.setattr(
        eval_run_dir.evaluation_entry,
        "create_problem_reports",
        lambda _problem_dir, _problem: ([], []),
    )
    monkeypatch.setattr(
        eval_run_dir,
        "update_results_jsonl",
        lambda _report_file, _reports: None,
    )
    monkeypatch.setattr(
        eval_run_dir,
        "display_and_save_summary",
        lambda _report_file, _agent_run_dir, _config, _console, _expected: None,
    )
    monkeypatch.setattr(
        eval_run_dir,
        "count_expected_checkpoints",
        lambda _config, _problems_dir: 0,
    )
    monkeypatch.setattr(
        eval_run_dir.evaluation_entry,
        "evaluate",
        evaluate_mock,
    )

    return evaluate_mock


class TestEvaluationSchemaHelpers:
    def test_schema_current_requires_version(self, tmp_path: Path) -> None:
        _create_checkpoint(tmp_path, "checkpoint_1", schema_current=False)
        checkpoint_dir = tmp_path / "checkpoint_1"

        assert _is_evaluation_schema_current(checkpoint_dir) is False

    def test_problem_fully_evaluated_requires_current_schema(
        self, tmp_path: Path
    ) -> None:
        problem_dir = tmp_path / "problem"
        problem_dir.mkdir()
        _create_checkpoint(problem_dir, "checkpoint_1", schema_current=False)

        assert _is_problem_fully_evaluated(problem_dir) is False


class TestEvaluateSelectionBehavior:
    def test_default_skips_current_and_evaluates_missing_or_outdated(
        self,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        agent_run_dir = _create_run_dir(tmp_path)

        complete_problem_dir = agent_run_dir / "complete_problem"
        complete_problem_dir.mkdir()
        _create_checkpoint(
            complete_problem_dir, "checkpoint_1", schema_current=True
        )

        missing_problem_dir = agent_run_dir / "missing_problem"
        missing_problem_dir.mkdir()
        (missing_problem_dir / "checkpoint_1").mkdir()

        outdated_problem_dir = agent_run_dir / "outdated_problem"
        outdated_problem_dir.mkdir()
        _create_checkpoint(
            outdated_problem_dir, "checkpoint_1", schema_current=False
        )

        available_problems = {
            "complete_problem": _mock_source_problem("complete_problem"),
            "missing_problem": _mock_source_problem("missing_problem"),
            "outdated_problem": _mock_source_problem("outdated_problem"),
        }

        evaluate_mock = _stub_eval_dependencies(
            monkeypatch,
            tmp_path,
            available_problems,
        )

        eval_run_dir.evaluate_agent_run(
            ctx=_ctx(tmp_path),
            agent_run_dir=agent_run_dir,
            problem_names=[],
            pass_policy=PassPolicy.ALL_CASES,
            env_config=None,
            live_progress=False,
            num_workers=1,
            overwrite=False,
        )

        evaluated = {
            problem_dir.name
            for _, problem_dir in evaluate_mock.call_args.kwargs["problems"]
        }
        assert evaluated == {"missing_problem", "outdated_problem"}

    def test_overwrite_evaluates_all_selected_problems(
        self,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        agent_run_dir = _create_run_dir(tmp_path)

        for problem_name in ["datagate", "other_problem"]:
            problem_dir = agent_run_dir / problem_name
            problem_dir.mkdir()
            _create_checkpoint(problem_dir, "checkpoint_1", schema_current=True)

        available_problems = {
            "datagate": _mock_source_problem("datagate"),
            "other_problem": _mock_source_problem("other_problem"),
        }

        evaluate_mock = _stub_eval_dependencies(
            monkeypatch,
            tmp_path,
            available_problems,
        )

        eval_run_dir.evaluate_agent_run(
            ctx=_ctx(tmp_path),
            agent_run_dir=agent_run_dir,
            problem_names=[],
            pass_policy=PassPolicy.ALL_CASES,
            env_config=None,
            live_progress=False,
            num_workers=1,
            overwrite=True,
        )

        evaluated = {
            problem_dir.name
            for _, problem_dir in evaluate_mock.call_args.kwargs["problems"]
        }
        assert evaluated == {"datagate", "other_problem"}

    def test_problem_and_overwrite_only_evaluates_selected_problem(
        self,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        agent_run_dir = _create_run_dir(tmp_path)

        for problem_name in ["datagate", "other_problem"]:
            problem_dir = agent_run_dir / problem_name
            problem_dir.mkdir()
            _create_checkpoint(problem_dir, "checkpoint_1", schema_current=True)

        available_problems = {
            "datagate": _mock_source_problem("datagate"),
            "other_problem": _mock_source_problem("other_problem"),
        }

        evaluate_mock = _stub_eval_dependencies(
            monkeypatch,
            tmp_path,
            available_problems,
        )

        eval_run_dir.evaluate_agent_run(
            ctx=_ctx(tmp_path),
            agent_run_dir=agent_run_dir,
            problem_names=["datagate"],
            pass_policy=PassPolicy.ALL_CASES,
            env_config=None,
            live_progress=False,
            num_workers=1,
            overwrite=True,
        )

        evaluated = [
            problem_dir.name
            for _, problem_dir in evaluate_mock.call_args.kwargs["problems"]
        ]
        assert evaluated == ["datagate"]

    def test_report_regeneration_uses_all_problem_directories_after_partial_overwrite(
        self,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        agent_run_dir = _create_run_dir(tmp_path)

        for problem_name in ["datagate", "other_problem"]:
            problem_dir = agent_run_dir / problem_name
            problem_dir.mkdir()
            (problem_dir / "checkpoint_1").mkdir()

        available_problems = {
            "datagate": _mock_source_problem("datagate"),
            "other_problem": _mock_source_problem("other_problem"),
        }

        evaluate_mock = MagicMock(return_value=(None, _eval_summary()))
        update_results_mock = MagicMock()

        monkeypatch.setattr(
            eval_run_dir.config_loader,
            "resolve_environment",
            lambda _path: object(),
        )
        monkeypatch.setattr(
            eval_run_dir.common,
            "ensure_docker_ready",
            lambda _environment: None,
        )
        monkeypatch.setattr(
            eval_run_dir.common,
            "setup_command_logging",
            lambda **_kwargs: None,
        )
        monkeypatch.setattr(
            eval_run_dir.common,
            "resolve_problem_catalog_root",
            lambda _ctx: tmp_path / "problems",
        )
        monkeypatch.setattr(
            eval_run_dir,
            "get_available_problems",
            lambda _problem_path: available_problems,
        )
        monkeypatch.setattr(
            eval_run_dir,
            "_write_problem_and_checkpoint_configs",
            lambda _problem_dir, _source_problem: None,
        )
        monkeypatch.setattr(
            eval_run_dir.ProblemConfig,
            "from_yaml",
            lambda _path: MagicMock(spec=ProblemConfig),
        )
        monkeypatch.setattr(
            eval_run_dir.evaluation_entry,
            "create_problem_reports",
            lambda problem_dir, _problem: (
                [
                    {
                        "problem_name": problem_dir.name,
                        "checkpoint_name": "checkpoint_1",
                    }
                ],
                [],
            ),
        )
        monkeypatch.setattr(
            eval_run_dir,
            "update_results_jsonl",
            update_results_mock,
        )
        monkeypatch.setattr(
            eval_run_dir,
            "display_and_save_summary",
            lambda _report_file,
            _agent_run_dir,
            _config,
            _console,
            _expected: None,
        )
        monkeypatch.setattr(
            eval_run_dir,
            "count_expected_checkpoints",
            lambda _config, _problems_dir: 0,
        )
        monkeypatch.setattr(
            eval_run_dir.evaluation_entry,
            "evaluate",
            evaluate_mock,
        )

        eval_run_dir.evaluate_agent_run(
            ctx=_ctx(tmp_path),
            agent_run_dir=agent_run_dir,
            problem_names=["datagate"],
            pass_policy=PassPolicy.ALL_CASES,
            env_config=None,
            live_progress=False,
            num_workers=1,
            overwrite=True,
        )

        evaluated = [
            problem_dir.name
            for _, problem_dir in evaluate_mock.call_args.kwargs["problems"]
        ]
        assert evaluated == ["datagate"]

        report_file, all_reports = update_results_mock.call_args.args
        assert report_file == agent_run_dir / CHECKPOINT_RESULTS_FILENAME
        assert {report["problem_name"] for report in all_reports} == {
            "datagate",
            "other_problem",
        }

    def test_planning_does_not_call_collection_preflight(
        self,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        agent_run_dir = _create_run_dir(tmp_path)

        current_problem_dir = agent_run_dir / "already_evaluated"
        current_problem_dir.mkdir()
        _create_checkpoint(
            current_problem_dir, "checkpoint_1", schema_current=True
        )

        to_eval_problem_dir = agent_run_dir / "needs_eval"
        to_eval_problem_dir.mkdir()
        (to_eval_problem_dir / "checkpoint_1").mkdir()

        source_problem = _mock_source_problem("already_evaluated")
        with (current_problem_dir / PROBLEM_CONFIG_NAME).open("w") as f:
            yaml.safe_dump(
                source_problem.model_dump.return_value, f, sort_keys=True
            )

        available_problems = {
            "already_evaluated": source_problem,
            "needs_eval": _mock_source_problem("needs_eval"),
        }

        evaluate_mock = _stub_eval_dependencies(
            monkeypatch,
            tmp_path,
            available_problems,
        )

        def _should_not_be_called(**_kwargs: object) -> tuple[bool, bool]:
            raise AssertionError("collection preflight should not run")

        monkeypatch.setattr(
            eval_run_dir,
            "check_problem_needs_reevaluation",
            _should_not_be_called,
            raising=False,
        )

        eval_run_dir.evaluate_agent_run(
            ctx=_ctx(tmp_path),
            agent_run_dir=agent_run_dir,
            problem_names=[],
            pass_policy=PassPolicy.ALL_CASES,
            env_config=None,
            live_progress=False,
            num_workers=1,
            overwrite=False,
        )

        evaluated = [
            problem_dir.name
            for _, problem_dir in evaluate_mock.call_args.kwargs["problems"]
        ]
        assert evaluated == ["needs_eval"]
