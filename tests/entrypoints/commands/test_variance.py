from pathlib import Path

import pytest
from rich.console import Console

from slop_code.common import CHECKPOINT_RESULTS_FILENAME
from slop_code.entrypoints.commands.variance import ConfidenceIntervalEntry
from slop_code.entrypoints.commands.variance import RunGroupKey
from slop_code.entrypoints.commands.variance import _collect_ci_entries
from slop_code.entrypoints.commands.variance import _discover_run_dirs
from slop_code.entrypoints.commands.variance import _metric_value
from slop_code.entrypoints.commands.variance import (
    _render_confidence_interval_table,
)
from slop_code.entrypoints.commands.variance import _render_problem_cv_summary


def _write_checkpoint_results_file(run_dir: Path) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / CHECKPOINT_RESULTS_FILENAME).write_text("{}\n")


def test_discovers_runs_nested_under_model_dirs(tmp_path: Path) -> None:
    outputs_dir = tmp_path / "outputs"
    outputs_dir.mkdir()

    model_a = outputs_dir / "model_a"
    model_b = outputs_dir / "model_b"
    model_a.mkdir()
    model_b.mkdir()

    run_a = model_a / "run_a"
    run_b = model_b / "run_b"
    _write_checkpoint_results_file(run_a)
    _write_checkpoint_results_file(run_b)

    unrelated_dir = outputs_dir / "not_a_run"
    unrelated_dir.mkdir()

    discovered = _discover_run_dirs(outputs_dir)

    assert discovered == sorted([run_a, run_b])


def test_metric_value_combines_lint_and_slop() -> None:
    row = {
        "lint_per_loc": 0.2,
        "ast_grep_per_loc": 0.3,
    }

    value = _metric_value(row, "normalized.lint_slop_per_loc")

    assert value == 0.5


def test_metric_value_combines_lint_and_slop_missing_returns_none() -> None:
    row = {"lint_per_loc": 0.2}

    value = _metric_value(row, "normalized.lint_slop_per_loc")

    assert value is None


def test_render_problem_cv_summary_splits_tables() -> None:
    console = Console(record=True, width=120)
    problem_cv_summary = {
        "sample": {
            "Pass rate": [0.3],
            "Lint": [0.1],
            "Slop": [0.2],
            "Lint+Slop": [0.4],
            "LOC": [0.5],
        }
    }
    problem_first_cv_summary = {
        "sample": {
            "Pass rate": [0.05],
            "Lint": [0.01],
            "Slop": [0.02],
            "Lint+Slop": [0.04],
            "LOC": [0.05],
        }
    }
    problem_final_cv_summary = problem_first_cv_summary

    _render_problem_cv_summary(
        console,
        problem_cv_summary,
        problem_first_cv_summary,
        problem_final_cv_summary,
    )

    output = console.export_text()
    assert "overall CV" in output
    assert "first vs final checkpoints" in output
    assert "High CC count" in output
    assert "Average CV by problem (overall across checkpoints)" in output
    assert "Average CV by problem (first vs final checkpoints)" in output


def test_collect_ci_entries_filters_by_width() -> None:
    record = {
        "problem": "prob",
        "run_count": 3,
        "final.delta.loc.mean": 1.0,
        "final.delta.loc.ci95_low": 0.4,
        "final.delta.loc.ci95_high": 1.6,
    }
    key = RunGroupKey(
        model="m",
        prompt_path="p",
        thinking="t",
        agent_type="a",
        agent_version="v",
    )

    entries = _collect_ci_entries(record, key, min_width=0.5)

    assert len(entries) == 1
    assert entries[0].width == pytest.approx(1.2)


def test_collect_ci_entries_filters_to_allowed_delta_metrics() -> None:
    record = {
        "problem": "prob",
        "run_count": 2,
        "unrelated.mean": 0.1,
        "unrelated.ci95_low": 0.0,
        "unrelated.ci95_high": 1.0,
    }
    key = RunGroupKey(
        model="m",
        prompt_path="p",
        thinking="t",
        agent_type="a",
        agent_version="v",
    )

    entries = _collect_ci_entries(record, key, min_width=0.0)

    assert entries == []


def test_collect_ci_entries_canonicalizes_metric_names() -> None:
    record = {
        "problem": "prob",
        "run_count": 2,
        "final.delta.ast_grep_violations.ci95_low": 0.4,
        "final.delta.ast_grep_violations.ci95_high": 0.6,
        "delta.ast_grep_violations.final.ci95_low": 0.5,
        "delta.ast_grep_violations.final.ci95_high": 0.7,
    }
    key = RunGroupKey(
        model="m",
        prompt_path="p",
        thinking="t",
        agent_type="a",
        agent_version="v",
    )

    entries = _collect_ci_entries(record, key, min_width=0.0)

    assert len(entries) == 1


def test_collect_ci_entries_allows_checkpoint_deltas() -> None:
    record = {
        "problem": "prob",
        "run_count": 2,
        "delta.loc.ci95_low": 0.4,
        "delta.loc.ci95_high": 0.6,
    }
    key = RunGroupKey(
        model="m",
        prompt_path="p",
        thinking="t",
        agent_type="a",
        agent_version="v",
    )

    entries = _collect_ci_entries(
        record,
        key,
        min_width=0.0,
        allowed_metrics={"delta.loc"},
    )

    assert len(entries) == 1
    assert entries[0].metric == "LOC delta"


def test_render_confidence_interval_table_outputs_ci_block() -> None:
    console = Console(record=True, width=120)
    entries = [
        ConfidenceIntervalEntry(
            problem="prob",
            metric="metric",
            mean=1.0,
            ci95_low=0.4,
            ci95_high=1.6,
            width=1.2,
            runs=3,
            group=RunGroupKey(
                model="m",
                prompt_path="p",
                thinking="t",
                agent_type="a",
                agent_version="v",
            ),
        )
    ]

    _render_confidence_interval_table(
        console=console, entries=entries, min_width=0.1, top_n=5
    )

    output = console.export_text()
    assert "Confidence intervals (95%) averaged across problems" in output
    assert "[0.40, 1.60]" in output
    assert "Width (avg)" in output
    assert "Problems" in output


def test_render_confidence_interval_table_aggregates_multiple_problems() -> (
    None
):
    console = Console(record=True, width=120)
    entries = [
        ConfidenceIntervalEntry(
            problem="prob1",
            metric="metric",
            mean=1.0,
            ci95_low=0.0,
            ci95_high=1.0,
            width=1.0,
            runs=2,
            group=RunGroupKey(
                model="m",
                prompt_path="p",
                thinking="t",
                agent_type="a",
                agent_version="v",
            ),
        ),
        ConfidenceIntervalEntry(
            problem="prob2",
            metric="metric",
            mean=3.0,
            ci95_low=2.0,
            ci95_high=4.0,
            width=2.0,
            runs=4,
            group=RunGroupKey(
                model="m",
                prompt_path="p",
                thinking="t",
                agent_type="a",
                agent_version="v",
            ),
        ),
    ]

    _render_confidence_interval_table(
        console=console, entries=entries, min_width=0.1, top_n=5
    )

    output = console.export_text()
    assert "metric" in output
    # Mean should be averaged: (1 + 3) / 2 = 2
    assert "2.00" in output
    # Width averaged: (1 + 2) / 2 = 1.50
    assert "1.50" in output


def test_render_confidence_interval_table_no_threshold_filtering() -> None:
    console = Console(record=True, width=120)
    entries = [
        ConfidenceIntervalEntry(
            problem="prob",
            metric="metric",
            mean=1.0,
            ci95_low=0.9,
            ci95_high=1.1,
            width=0.2,
            runs=3,
            group=RunGroupKey(
                model="m",
                prompt_path="p",
                thinking="t",
                agent_type="a",
                agent_version="v",
            ),
        )
    ]

    _render_confidence_interval_table(
        console=console, entries=entries, min_width=0.1, top_n=5
    )

    output = console.export_text()
    assert "metric" in output
