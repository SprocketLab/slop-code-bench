"""Tests for decomposing Regression failures across checkpoints."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from slop_code.entrypoints.evaluation import metrics as eval_metrics
from slop_code.metrics.checkpoint.regression import RegressionHistory
from slop_code.metrics.summary import compute_run_summary


def _group(passed=(), failed=(), skipped=()) -> dict[str, list[str]]:
    return {
        "passed": list(passed),
        "failed": list(failed),
        "skipped": list(skipped),
    }


def _breakdown(result: dict) -> tuple[int, int, int, int]:
    return (
        result["true_regressions"],
        result["carryover_failures"],
        result["newly_active_failures"],
        result["regression_previously_passed"],
    )


class TestRegressionHistory:
    def test_first_checkpoint_has_no_regressions(self):
        history = RegressionHistory()
        result = history.observe(
            {"checkpoint_1-Core": _group(passed=["a"], failed=["b"])}
        )

        assert _breakdown(result) == (0, 0, 0, 0)
        assert result["true_regression_hazard"] == 0.0

    def test_passed_then_failed_is_true_regression(self):
        history = RegressionHistory()
        history.observe({"checkpoint_1-Core": _group(passed=["a", "b"])})

        result = history.observe(
            {
                "checkpoint_1-Regression": _group(passed=["a"], failed=["b"]),
                "checkpoint_2-Core": _group(passed=["c"]),
            }
        )

        assert _breakdown(result) == (1, 0, 0, 2)
        assert result["true_regression_hazard"] == pytest.approx(0.5)

    def test_failed_at_origin_is_carryover(self):
        history = RegressionHistory()
        history.observe(
            {
                "checkpoint_1-Core": _group(passed=["a"]),
                "checkpoint_1-Error": _group(failed=["edge"]),
            }
        )

        result = history.observe(
            {"checkpoint_1-Regression": _group(passed=["a"], failed=["edge"])}
        )

        assert _breakdown(result) == (0, 1, 0, 1)
        assert result["true_regression_hazard"] == 0.0

    @pytest.mark.parametrize(
        "first_checkpoint",
        [
            {"checkpoint_1-Core": _group(skipped=["a"])},
            {"checkpoint_1-Core": _group()},
        ],
        ids=["skipped", "absent"],
    )
    def test_never_ran_is_newly_active(self, first_checkpoint):
        history = RegressionHistory()
        history.observe(first_checkpoint)

        result = history.observe(
            {"checkpoint_1-Regression": _group(failed=["a"])}
        )

        assert _breakdown(result) == (0, 0, 1, 0)

    def test_pass_at_any_earlier_checkpoint_counts(self):
        history = RegressionHistory()
        history.observe({"checkpoint_1-Core": _group(failed=["a"])})
        history.observe({"checkpoint_1-Regression": _group(passed=["a"])})
        history.observe({"checkpoint_1-Regression": _group(failed=["a"])})

        result = history.observe(
            {"checkpoint_1-Regression": _group(failed=["a"])}
        )

        assert _breakdown(result) == (1, 0, 0, 1)

    def test_skipped_regression_tests_are_ignored(self):
        history = RegressionHistory()
        history.observe({"checkpoint_1-Core": _group(passed=["a"])})

        result = history.observe(
            {"checkpoint_1-Regression": _group(skipped=["a"])}
        )

        assert _breakdown(result) == (0, 0, 0, 0)

    def test_same_test_id_in_different_checkpoints_is_distinct(self):
        history = RegressionHistory()
        history.observe({"checkpoint_1-Core": _group(passed=["test_x"])})
        history.observe(
            {
                "checkpoint_1-Regression": _group(passed=["test_x"]),
                "checkpoint_2-Core": _group(failed=["test_x"]),
            }
        )

        result = history.observe(
            {
                "checkpoint_1-Regression": _group(passed=["test_x"]),
                "checkpoint_2-Regression": _group(failed=["test_x"]),
            }
        )

        assert _breakdown(result) == (0, 1, 0, 1)

    def test_checkpoint_names_with_delimiter(self):
        history = RegressionHistory()
        history.observe({"part-1-Core": _group(passed=["a"])})

        result = history.observe({"part-1-Regression": _group(failed=["a"])})

        assert _breakdown(result) == (1, 0, 0, 1)

    def test_categories_partition_regression_failures(self):
        history = RegressionHistory()
        history.observe(
            {
                "checkpoint_1-Core": _group(passed=["p1", "p2"], failed=["f"]),
                "checkpoint_1-Functionality": _group(skipped=["s"]),
            }
        )

        result = history.observe(
            {
                "checkpoint_1-Regression": _group(
                    passed=["p1"], failed=["p2", "f", "s", "new"]
                ),
            }
        )

        true, carryover, newly_active, _ = _breakdown(result)
        assert (true, carryover, newly_active) == (1, 1, 2)


class TestObserveDir:
    def test_reads_evaluation_json(self, tmp_path: Path):
        history = RegressionHistory()
        for name, tests in [
            ("checkpoint_1", {"checkpoint_1-Core": _group(passed=["a"])}),
            (
                "checkpoint_2",
                {"checkpoint_1-Regression": _group(failed=["a"])},
            ),
        ]:
            (tmp_path / name).mkdir()
            (tmp_path / name / "evaluation.json").write_text(
                json.dumps({"tests": tests})
            )

        history.observe_dir(tmp_path / "checkpoint_1")
        result = history.observe_dir(tmp_path / "checkpoint_2")

        assert _breakdown(result) == (1, 0, 0, 1)

    def test_missing_file_returns_empty(self, tmp_path: Path):
        assert RegressionHistory().observe_dir(tmp_path) == {}

    def test_legacy_list_tests_returns_empty(self, tmp_path: Path):
        (tmp_path / "evaluation.json").write_text(json.dumps({"tests": []}))

        assert RegressionHistory().observe_dir(tmp_path) == {}


class TestCreateProblemReports:
    def test_adds_breakdown_to_checkpoint_reports(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(
            eval_metrics, "get_checkpoint_metrics", lambda *_a, **_k: {}
        )
        (tmp_path / "problem.yaml").write_text("version: 1\n")
        checkpoint_tests = {
            "checkpoint_1": {"checkpoint_1-Core": _group(passed=["a", "b"])},
            "checkpoint_2": {
                "checkpoint_1-Regression": _group(passed=["a"], failed=["b"])
            },
        }
        for name, tests in checkpoint_tests.items():
            (tmp_path / name).mkdir()
            (tmp_path / name / "evaluation.json").write_text(
                json.dumps({"tests": tests})
            )
        problem = SimpleNamespace(
            name="prob",
            checkpoints={
                "checkpoint_2": SimpleNamespace(order=2),
                "checkpoint_1": SimpleNamespace(order=1),
            },
        )

        reports, errors = eval_metrics.create_problem_reports(tmp_path, problem)

        assert errors == []
        assert [r["checkpoint"] for r in reports] == [
            "checkpoint_1",
            "checkpoint_2",
        ]
        assert _breakdown(reports[0]) == (0, 0, 0, 0)
        assert _breakdown(reports[1]) == (1, 0, 0, 2)
        assert reports[1]["true_regression_hazard"] == pytest.approx(0.5)


class TestRunSummaryRegressionBreakdown:
    def test_sums_counts_and_pools_hazard(self):
        config = {
            "model": {"name": "test-model"},
            "thinking": "none",
            "prompt_path": "test.jinja",
            "agent": {"type": "test-agent", "version": "1.0"},
        }
        checkpoints = [
            {"problem": "p1", "idx": 1},
            {
                "problem": "p1",
                "idx": 2,
                "true_regressions": 1,
                "carryover_failures": 3,
                "newly_active_failures": 0,
                "regression_previously_passed": 10,
                "true_regression_hazard": 0.1,
            },
            {
                "problem": "p2",
                "idx": 2,
                "true_regressions": 0,
                "carryover_failures": 2,
                "newly_active_failures": 1,
                "regression_previously_passed": 30,
                "true_regression_hazard": 0.0,
            },
        ]

        summary = compute_run_summary(
            config, checkpoints, expected_checkpoints=len(checkpoints)
        )

        breakdown = summary.regression_breakdown
        assert breakdown.true_regressions == 1
        assert breakdown.carryover_failures == 5
        assert breakdown.newly_active_failures == 1
        assert breakdown.regression_previously_passed == 40
        assert breakdown.true_regression_hazard == pytest.approx(1 / 40)

    def test_defaults_to_zero_without_breakdown_keys(self):
        config = {
            "model": {"name": "test-model"},
            "thinking": "none",
            "prompt_path": "test.jinja",
            "agent": {"type": "test-agent", "version": "1.0"},
        }

        summary = compute_run_summary(
            config,
            [{"problem": "p1", "idx": 1, "strict_pass_rate": 1.0}],
            expected_checkpoints=1,
        )

        assert summary.regression_breakdown.true_regression_hazard == 0.0
        assert summary.regression_breakdown.carryover_failures == 0
