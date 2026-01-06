"""Tests for run summary computation."""

from __future__ import annotations

import pytest

from slop_code.metrics.summary import compute_run_summary


@pytest.fixture
def mock_config() -> dict:
    """Return a minimal config dict for compute_run_summary."""
    return {
        "model": {"name": "test-model"},
        "thinking": "none",
        "prompt_path": "test.jinja",
        "agent": {"type": "test-agent", "version": "1.0"},
    }


class TestRunSummaryDeltaExtraction:
    """Tests for delta extraction in compute_run_summary."""

    def test_extracts_deltas_from_checkpoints(self, mock_config):
        """Test that summary reads delta.* keys from checkpoints."""
        checkpoints = [
            {
                "problem": "test",
                "idx": 1,
                "pass_rate": 0.8,
                "total_tests": 10,
                "passed_tests": 8,
            },
            {
                "problem": "test",
                "idx": 2,
                "pass_rate": 1.0,
                "total_tests": 10,
                "passed_tests": 10,
                "delta.lint_errors": 50.0,
                "delta.ast_grep_violations": -20.0,
                "delta.cc_high_count": 25.0,
                "delta.comparisons": 15.0,
                "delta.new_violations_per_loc": 0.05,
            },
        ]
        summary = compute_run_summary(mock_config, checkpoints)

        # Should have extracted the delta values
        assert summary.delta.lint.mean == 50.0
        assert summary.delta.ast_grep.mean == -20.0
        assert summary.delta.complex.mean == 25.0
        assert summary.delta.comparisons.mean == 15.0
        assert summary.delta.rubric_non_carryover.mean == 0.05

    def test_skips_inf_deltas(self, mock_config):
        """Test that inf values are skipped in delta extraction."""
        checkpoints = [
            {"problem": "test", "idx": 1, "pass_rate": 0.8},
            {
                "problem": "test",
                "idx": 2,
                "pass_rate": 1.0,
                "delta.lint_errors": float("inf"),
            },
            {
                "problem": "test",
                "idx": 3,
                "pass_rate": 1.0,
                "delta.lint_errors": 50.0,
            },
        ]
        summary = compute_run_summary(mock_config, checkpoints)

        # Should only include the non-inf value
        assert summary.delta.lint.mean == 50.0
        assert summary.delta.lint.count == 1

    def test_empty_deltas_when_no_delta_keys(self, mock_config):
        """Test that summary handles checkpoints without delta keys."""
        checkpoints = [
            {"problem": "test", "idx": 1, "pass_rate": 0.8},
            {"problem": "test", "idx": 2, "pass_rate": 1.0},
        ]
        summary = compute_run_summary(mock_config, checkpoints)

        # Should have empty stats (count=0)
        assert summary.delta.lint.count == 0
        assert summary.delta.lint.mean is None


class TestRunSummaryCounts:
    """Tests for count aggregation in compute_run_summary."""

    def test_counts_problems_and_checkpoints(self, mock_config):
        """Test that summary counts problems and checkpoints correctly."""
        checkpoints = [
            {"problem": "prob1", "idx": 1, "pass_rate": 0.8},
            {"problem": "prob1", "idx": 2, "pass_rate": 1.0},
            {"problem": "prob2", "idx": 1, "pass_rate": 0.5},
        ]
        summary = compute_run_summary(mock_config, checkpoints)

        assert summary.num_problems == 2
        assert summary.num_checkpoints == 3

    def test_empty_checkpoints_returns_empty_summary(self, mock_config):
        """Test that empty checkpoints returns empty summary."""
        summary = compute_run_summary(mock_config, [])

        assert summary.num_problems == 0
        assert summary.num_checkpoints == 0


class TestRunSummaryCosts:
    """Tests for cost aggregation in compute_run_summary."""

    def test_aggregates_costs(self, mock_config):
        """Test that summary aggregates costs correctly."""
        checkpoints = [
            {"problem": "prob1", "idx": 1, "cost": 0.10, "pass_rate": 1.0},
            {"problem": "prob1", "idx": 2, "cost": 0.20, "pass_rate": 1.0},
            {"problem": "prob2", "idx": 1, "cost": 0.15, "pass_rate": 1.0},
        ]
        summary = compute_run_summary(mock_config, checkpoints)

        assert abs(summary.costs.total - 0.45) < 0.001
        assert abs(summary.costs.checkpoint.mean - 0.15) < 0.001
        # Problem costs: prob1=0.30, prob2=0.15
        assert abs(summary.costs.problem.mean - 0.225) < 0.001


class TestRunSummarySolveRates:
    """Tests for solve rate computation in compute_run_summary."""

    def test_computes_checkpoint_solve_rate(self, mock_config):
        """Test that summary computes checkpoint solve rate correctly."""
        checkpoints = [
            {"problem": "prob1", "idx": 1, "pass_rate": 1.0, "checkpoint_pass_rate": 1.0},
            {"problem": "prob1", "idx": 2, "pass_rate": 0.8, "checkpoint_pass_rate": 0.8},
            {"problem": "prob2", "idx": 1, "pass_rate": 1.0, "checkpoint_pass_rate": 1.0},
            {"problem": "prob2", "idx": 2, "pass_rate": 1.0, "checkpoint_pass_rate": 1.0},
        ]
        summary = compute_run_summary(mock_config, checkpoints)

        # 3 out of 4 checkpoints have pass_rate == 1.0
        assert summary.pct_checkpoints_solved == 75.0

    def test_computes_problem_solve_rate(self, mock_config):
        """Test that summary computes problem solve rate correctly."""
        checkpoints = [
            {"problem": "prob1", "idx": 1, "pass_rate": 1.0, "checkpoint_pass_rate": 1.0},
            {"problem": "prob1", "idx": 2, "pass_rate": 1.0, "checkpoint_pass_rate": 1.0},  # fully solved
            {"problem": "prob2", "idx": 1, "pass_rate": 0.8, "checkpoint_pass_rate": 0.8},
            {
                "problem": "prob2",
                "idx": 2,
                "pass_rate": 0.9,
                "checkpoint_pass_rate": 0.9,
            },  # not fully solved
        ]
        summary = compute_run_summary(mock_config, checkpoints)

        # Only 1 problem fully solved
        assert summary.pct_problems_solved == 50.0

    def test_computes_partial_solve_rate(self, mock_config):
        """Test that summary computes partial solve rate correctly."""
        checkpoints = [
            {"problem": "prob1", "idx": 1, "pass_rate": 1.0, "checkpoint_pass_rate": 1.0},
            {
                "problem": "prob1",
                "idx": 2,
                "pass_rate": 0.5,
                "checkpoint_pass_rate": 0.5,
            },  # has at least one 1.0
            {"problem": "prob2", "idx": 1, "pass_rate": 0.8, "checkpoint_pass_rate": 0.8},
            {"problem": "prob2", "idx": 2, "pass_rate": 0.9, "checkpoint_pass_rate": 0.9},  # no 1.0
        ]
        summary = compute_run_summary(mock_config, checkpoints)

        # Only prob1 has at least one pass_rate == 1.0
        assert summary.pct_problems_partial == 50.0


class TestRunSummaryPassRates:
    """Tests for pass rate aggregation in compute_run_summary."""

    def test_computes_pass_rates_by_type(self, mock_config):
        """Test that summary computes pass rates by test type."""
        checkpoints = [
            {
                "problem": "prob1",
                "idx": 1,
                "pass_rate": 0.8,
                "total_tests": 10,
                "passed_tests": 8,
                "core_total": 5,
                "core_passed": 5,
                "functionality_total": 3,
                "functionality_passed": 2,
                "error_total": 2,
                "error_passed": 1,
                "regression_total": 0,
                "regression_passed": 0,
            },
        ]
        summary = compute_run_summary(mock_config, checkpoints)

        assert summary.pass_rates.checkpoint.total == 0.8
        assert summary.pass_rates.checkpoint.core == 1.0
        assert abs(summary.pass_rates.checkpoint.functionality - 2 / 3) < 0.01
        assert summary.pass_rates.checkpoint.error == 0.5

    def test_pass_rates_exclude_zero_total_checkpoints(self, mock_config):
        """Test that checkpoints with 0 tests for a type are excluded from averages.

        Regression test: Previously, checkpoints with regression_total=0 would
        contribute 0.0 to the mean, dragging down the average incorrectly.
        """
        checkpoints = [
            {
                "problem": "prob1",
                "idx": 1,
                "pass_rate": 1.0,
                "total_tests": 10,
                "passed_tests": 10,
                "core_total": 5,
                "core_passed": 5,
                "functionality_total": 5,
                "functionality_passed": 5,
                "error_total": 0,  # No error tests
                "error_passed": 0,
                "regression_total": 0,  # No regression tests (first checkpoint)
                "regression_passed": 0,
            },
            {
                "problem": "prob1",
                "idx": 2,
                "pass_rate": 0.9,
                "total_tests": 20,
                "passed_tests": 18,
                "core_total": 5,
                "core_passed": 4,
                "functionality_total": 5,
                "functionality_passed": 4,
                "error_total": 5,
                "error_passed": 5,  # 100% error rate
                "regression_total": 5,
                "regression_passed": 5,  # 100% regression rate
            },
        ]
        summary = compute_run_summary(mock_config, checkpoints)

        # Core: mean of (5/5, 4/5) = (1.0 + 0.8) / 2 = 0.9
        assert abs(summary.pass_rates.checkpoint.core - 0.9) < 0.01

        # Error: only checkpoint 2 has error tests (5/5 = 1.0)
        # checkpoint 1 should be EXCLUDED, not counted as 0.0
        assert summary.pass_rates.checkpoint.error == 1.0

        # Regression: only checkpoint 2 has regression tests (5/5 = 1.0)
        # checkpoint 1 should be EXCLUDED, not counted as 0.0
        assert summary.pass_rates.checkpoint.regression == 1.0

    def test_pass_rates_multiple_checkpoints_with_zero_tests(self, mock_config):
        """Test pass rate averaging with multiple checkpoints having no tests."""
        checkpoints = [
            {
                "problem": "prob1",
                "idx": 1,
                "pass_rate": 1.0,
                "total_tests": 10,
                "passed_tests": 10,
                "core_total": 10,
                "core_passed": 10,
                "error_total": 0,
                "error_passed": 0,
                "regression_total": 0,
                "regression_passed": 0,
            },
            {
                "problem": "prob2",
                "idx": 1,
                "pass_rate": 1.0,
                "total_tests": 10,
                "passed_tests": 10,
                "core_total": 10,
                "core_passed": 10,
                "error_total": 0,
                "error_passed": 0,
                "regression_total": 0,
                "regression_passed": 0,
            },
            {
                "problem": "prob1",
                "idx": 2,
                "pass_rate": 0.8,
                "total_tests": 20,
                "passed_tests": 16,
                "core_total": 10,
                "core_passed": 8,
                "error_total": 5,
                "error_passed": 4,  # 80% error rate
                "regression_total": 5,
                "regression_passed": 4,  # 80% regression rate
            },
        ]
        summary = compute_run_summary(mock_config, checkpoints)

        # Error: only 1 checkpoint has error tests (4/5 = 0.8)
        # The 2 checkpoints with error_total=0 should be EXCLUDED
        assert summary.pass_rates.checkpoint.error == 0.8

        # Regression: only 1 checkpoint has regression tests (4/5 = 0.8)
        assert summary.pass_rates.checkpoint.regression == 0.8

    def test_pass_rates_all_checkpoints_have_zero_tests_returns_zero(self, mock_config):
        """Test that pass rate is 0.0 when ALL checkpoints have 0 tests for a type."""
        checkpoints = [
            {
                "problem": "prob1",
                "idx": 1,
                "pass_rate": 1.0,
                "total_tests": 10,
                "passed_tests": 10,
                "core_total": 10,
                "core_passed": 10,
                "error_total": 0,  # No error tests
                "error_passed": 0,
            },
            {
                "problem": "prob1",
                "idx": 2,
                "pass_rate": 1.0,
                "total_tests": 10,
                "passed_tests": 10,
                "core_total": 10,
                "core_passed": 10,
                "error_total": 0,  # No error tests
                "error_passed": 0,
            },
        ]
        summary = compute_run_summary(mock_config, checkpoints)

        # When no checkpoints have error tests, the rate should be 0.0
        # (not NaN or an error)
        assert summary.pass_rates.checkpoint.error == 0.0


class TestRunSummaryCcMetrics:
    """Tests for cyclomatic complexity aggregation in compute_run_summary."""

    def test_computes_cc_stats(self, mock_config):
        """Test that summary aggregates CC metrics across checkpoints."""
        checkpoints = [
            {
                "problem": "prob1",
                "idx": 1,
                "pass_rate": 1.0,
                "cc_high_count": 5,
                "high_cc_mean": 12.0,
                "cc_max": 30,
            },
            {
                "problem": "prob2",
                "idx": 1,
                "pass_rate": 0.8,
                "cc_high_count": 3,
                "high_cc_mean": 18.0,
                "cc_max": 24,
            },
        ]
        summary = compute_run_summary(mock_config, checkpoints)

        assert summary.cc.high_count.mean == 4.0
        assert summary.cc.high_count.count == 2
        assert summary.cc.high_mean.mean == 15.0
        assert summary.cc.max.max == 30
        assert summary.cc.max.min == 24
