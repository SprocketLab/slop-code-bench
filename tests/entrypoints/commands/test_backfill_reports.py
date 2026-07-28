from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock

from slop_code.entrypoints.commands import (
    backfill_reports as backfill_reports_module,
)
from slop_code.entrypoints.commands.backfill_reports import (
    _recategorize_evaluation_tests,
)


def test_recategorize_evaluation_tests_dict_format_excludes_skipped_from_counts(
    tmp_path: Path,
) -> None:
    eval_path = tmp_path / "evaluation.json"
    eval_path.write_text(
        json.dumps(
            {
                "checkpoint_name": "checkpoint_1",
                "pass_counts": {"Core": 1},
                "total_counts": {"Core": 3},
                "tests": {
                    "checkpoint_1-Core": {
                        "passed": ["test_pass"],
                        "failed": ["test_fail"],
                        "skipped": ["test_skip"],
                    }
                },
            }
        )
    )

    updated = _recategorize_evaluation_tests(eval_path, MagicMock())

    data = json.loads(eval_path.read_text())
    assert updated is True
    assert data["pass_counts"] == {"Core": 1}
    assert data["total_counts"] == {"Core": 2}


def test_backfill_reports_preserves_costs_for_all_agents(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "config.yaml").write_text(
        json.dumps(
            {
                "agent": {"type": "codex"},
                "model": {
                    "name": "priced-model",
                    "pricing": {
                        "input": 10.0,
                        "output": 0.0,
                        "cache_read": 0.0,
                        "cache_write": 0.0,
                    },
                },
            }
        )
    )

    reports = [
        {
            "problem": "example",
            "checkpoint": "checkpoint_1",
            "input": 1_000_000,
            "output": 0,
            "cache_read": 0,
            "cache_write": 0,
            "cost": 0.25,
        }
    ]
    written_reports: list[dict] = []

    monkeypatch.setattr(
        backfill_reports_module,
        "_process_single_run_backfill",
        lambda problem_root, results_dir, logger: (reports, [], 1),
    )
    monkeypatch.setattr(
        backfill_reports_module,
        "update_results_jsonl",
        lambda report_file, new_reports: written_reports.extend(new_reports),
    )
    monkeypatch.setattr(
        backfill_reports_module,
        "display_and_save_summary",
        lambda report_file,
        results_dir,
        config,
        console,
        expected_checkpoints: None,
    )
    monkeypatch.setattr(
        backfill_reports_module,
        "count_expected_checkpoints",
        lambda config, problems_dir: 0,
    )
    monkeypatch.setattr(
        backfill_reports_module.common,
        "resolve_problem_catalog_root",
        lambda _ctx: run_dir.parent,
    )
    ctx = cast(
        "Any",
        SimpleNamespace(
            obj=SimpleNamespace(
                verbosity=0,
                scbench_home=run_dir.parent / ".scbench-home",
            )
        ),
    )

    backfill_reports_module.backfill_reports(ctx, run_dir)

    assert written_reports[0]["cost"] == 0.25
