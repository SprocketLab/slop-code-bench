"""Tests for decomposing Regression failures across checkpoints."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from slop_code.entrypoints.evaluation import metrics as eval_metrics
from slop_code.evaluation.report import CorrectnessResults
from slop_code.evaluation.report import GroupType
from slop_code.evaluation.report import TestResult as EvalTestResult
from slop_code.metrics.checkpoint.extractors import get_evaluation_metrics
from slop_code.metrics.checkpoint.regression import REGRESSION_BREAKDOWN_KEYS
from slop_code.metrics.checkpoint.regression import RegressionHistory
from slop_code.metrics.summary import compute_run_summary

BREAKDOWN_OUTPUT_KEYS = (*REGRESSION_BREAKDOWN_KEYS, "true_regression_hazard")


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

    def test_missing_file_suppresses_later_checkpoints(self, tmp_path: Path):
        history = RegressionHistory()
        for name, tests in [
            ("checkpoint_1", {"checkpoint_1-Core": _group(passed=["a"])}),
            ("checkpoint_2", None),
            (
                "checkpoint_3",
                {"checkpoint_1-Regression": _group(passed=["a"], failed=["b"])},
            ),
        ]:
            checkpoint_dir = tmp_path / name
            checkpoint_dir.mkdir()
            if tests is not None:
                (checkpoint_dir / "evaluation.json").write_text(
                    json.dumps({"tests": tests})
                )

        assert _breakdown(history.observe_dir(tmp_path / "checkpoint_1")) == (
            0,
            0,
            0,
            0,
        )
        assert history.observe_dir(tmp_path / "checkpoint_2") == {}
        assert history.observe_dir(tmp_path / "checkpoint_3") == {}

    def test_legacy_tests_gap_suppresses_later_checkpoints(
        self, tmp_path: Path
    ):
        history = RegressionHistory()
        (tmp_path / "checkpoint_1").mkdir()
        (tmp_path / "checkpoint_1" / "evaluation.json").write_text(
            json.dumps({"tests": []})
        )
        (tmp_path / "checkpoint_2").mkdir()
        (tmp_path / "checkpoint_2" / "evaluation.json").write_text(
            json.dumps(
                {"tests": {"checkpoint_1-Regression": _group(failed=["a"])}}
            )
        )

        assert history.observe_dir(tmp_path / "checkpoint_1") == {}
        assert history.observe_dir(tmp_path / "checkpoint_2") == {}

    def test_mark_gap_suppresses_observe(self):
        history = RegressionHistory()
        history.observe({"checkpoint_1-Core": _group(passed=["a"])})
        history.mark_gap()

        assert (
            history.observe({"checkpoint_1-Regression": _group(failed=["a"])})
            == {}
        )

    def test_breakdown_equals_regression_non_pass_count(self, tmp_path: Path):
        cp1_results = CorrectnessResults(
            problem_name="prob",
            problem_version=1,
            checkpoint_name="checkpoint_1",
            checkpoint_version=1,
            duration=1.0,
            entrypoint="python main.py",
            pytest_exit_code=0,
            pytest_collected=5,
        )
        for test_id, group_type, status in [
            ("p1", GroupType.CORE, "passed"),
            ("p2", GroupType.CORE, "passed"),
            ("f1", GroupType.ERROR, "failed"),
            ("e1", GroupType.ERROR, "error"),
            ("s1", GroupType.FUNCTIONALITY, "skipped"),
        ]:
            cp1_results.add_test_result(
                EvalTestResult(
                    id=test_id,
                    checkpoint="checkpoint_1",
                    group_type=group_type,
                    status=status,
                    duration_ms=1.0,
                    file_path="tests/test_cp1.py",
                )
            )

        cp2_results = CorrectnessResults(
            problem_name="prob",
            problem_version=1,
            checkpoint_name="checkpoint_2",
            checkpoint_version=1,
            duration=1.0,
            entrypoint="python main.py",
            pytest_exit_code=1,
            pytest_collected=8,
        )
        for test_id, checkpoint, group_type, status in [
            ("p1", "checkpoint_1", GroupType.REGRESSION, "passed"),
            ("p2", "checkpoint_1", GroupType.REGRESSION, "failed"),
            ("f1", "checkpoint_1", GroupType.REGRESSION, "failed"),
            ("e1", "checkpoint_1", GroupType.REGRESSION, "error"),
            ("s1", "checkpoint_1", GroupType.REGRESSION, "failed"),
            ("new_fail", "checkpoint_1", GroupType.REGRESSION, "failed"),
            ("skip_reg", "checkpoint_1", GroupType.REGRESSION, "skipped"),
            ("cp2_core", "checkpoint_2", GroupType.CORE, "passed"),
        ]:
            cp2_results.add_test_result(
                EvalTestResult(
                    id=test_id,
                    checkpoint=checkpoint,
                    group_type=group_type,
                    status=status,
                    duration_ms=1.0,
                    file_path=f"tests/test_{checkpoint}.py",
                )
            )

        cp1_dir = tmp_path / "checkpoint_1"
        cp2_dir = tmp_path / "checkpoint_2"
        cp1_results.save(cp1_dir)
        cp2_results.save(cp2_dir)

        history = RegressionHistory()
        history.observe_dir(cp1_dir)
        breakdown = history.observe_dir(cp2_dir)

        assert _breakdown(breakdown) == (1, 2, 2, 2)

        eval_data = json.loads((cp2_dir / "evaluation.json").read_text())
        regression_non_pass = (
            eval_data["total_counts"]["Regression"]
            - eval_data["pass_counts"]["Regression"]
        )
        assert (
            breakdown["true_regressions"]
            + breakdown["carryover_failures"]
            + breakdown["newly_active_failures"]
            == regression_non_pass
        )

        extracted = get_evaluation_metrics(cp2_dir)
        assert (
            breakdown["true_regressions"]
            + breakdown["carryover_failures"]
            + breakdown["newly_active_failures"]
            == extracted["regression_total"] - extracted["regression_passed"]
        )


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

    def test_missing_evaluation_json_suppresses_later_breakdowns(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(
            eval_metrics, "get_checkpoint_metrics", lambda *_a, **_k: {}
        )
        (tmp_path / "problem.yaml").write_text("version: 1\n")
        (tmp_path / "checkpoint_1").mkdir()
        (tmp_path / "checkpoint_1" / "evaluation.json").write_text(
            json.dumps({"tests": {"checkpoint_1-Core": _group(passed=["a"])}})
        )
        # checkpoint_2 exists on disk but has no evaluation.json.
        (tmp_path / "checkpoint_2").mkdir()
        (tmp_path / "checkpoint_3").mkdir()
        (tmp_path / "checkpoint_3" / "evaluation.json").write_text(
            json.dumps(
                {
                    "tests": {
                        "checkpoint_1-Regression": _group(
                            passed=["a"], failed=["b"]
                        )
                    }
                }
            )
        )
        problem = SimpleNamespace(
            name="prob",
            checkpoints={
                "checkpoint_1": SimpleNamespace(order=1),
                "checkpoint_2": SimpleNamespace(order=2),
                "checkpoint_3": SimpleNamespace(order=3),
            },
        )

        reports, errors = eval_metrics.create_problem_reports(tmp_path, problem)

        assert errors == []
        assert [r["checkpoint"] for r in reports] == [
            "checkpoint_1",
            "checkpoint_2",
            "checkpoint_3",
        ]
        assert _breakdown(reports[0]) == (0, 0, 0, 0)
        for key in BREAKDOWN_OUTPUT_KEYS:
            assert key not in reports[1]
            assert key not in reports[2]

    def test_missing_checkpoint_dir_suppresses_later_breakdowns(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(
            eval_metrics, "get_checkpoint_metrics", lambda *_a, **_k: {}
        )
        (tmp_path / "problem.yaml").write_text("version: 1\n")
        (tmp_path / "checkpoint_1").mkdir()
        (tmp_path / "checkpoint_1" / "evaluation.json").write_text(
            json.dumps({"tests": {"checkpoint_1-Core": _group(passed=["a"])}})
        )
        # checkpoint_2 directory is completely absent.
        (tmp_path / "checkpoint_3").mkdir()
        (tmp_path / "checkpoint_3" / "evaluation.json").write_text(
            json.dumps(
                {"tests": {"checkpoint_1-Regression": _group(failed=["a"])}}
            )
        )
        problem = SimpleNamespace(
            name="prob",
            checkpoints={
                "checkpoint_1": SimpleNamespace(order=1),
                "checkpoint_2": SimpleNamespace(order=2),
                "checkpoint_3": SimpleNamespace(order=3),
            },
        )

        reports, errors = eval_metrics.create_problem_reports(tmp_path, problem)

        assert len(errors) == 1
        assert errors[0][0] == "checkpoint_2"
        assert [r["checkpoint"] for r in reports] == [
            "checkpoint_1",
            "checkpoint_3",
        ]
        assert _breakdown(reports[0]) == (0, 0, 0, 0)
        for key in BREAKDOWN_OUTPUT_KEYS:
            assert key not in reports[1]


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
