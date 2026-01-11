"""Per-category aggregation functions for run summary computation.

This module provides functions that compute specific categories of
aggregate statistics from checkpoint data.
"""

from __future__ import annotations

import math
import statistics
from typing import Any

from slop_code.metrics.models import CostsStats
from slop_code.metrics.models import CyclomaticComplexityStats
from slop_code.metrics.models import DeltaStats
from slop_code.metrics.models import MetricStats
from slop_code.metrics.models import PassRatesByType
from slop_code.metrics.models import PassRatesStats
from slop_code.metrics.models import RatiosStats
from slop_code.metrics.models import StepsStats
from slop_code.metrics.models import TimeStats
from slop_code.metrics.models import TokenMeans
from slop_code.metrics.models import TokenStats
from slop_code.metrics.summary.stats import compute_metric_stats
from slop_code.metrics.summary.stats import compute_pass_rate
from slop_code.metrics.summary.stats import compute_ratio_values
from slop_code.metrics.summary.stats import extract_metric_values


def safe_mean(values: list[float]) -> float:
    """Compute mean of values, returning 0.0 for empty lists."""
    return statistics.mean(values) if values else 0.0


def aggregate_per_problem(
    problems: dict[str, list[dict[str, Any]]],
    key: str,
    default: float = 0,
) -> list[float]:
    """Sum values for a given key across all checkpoints within each problem."""
    return [
        sum(c.get(key, default) for c in chkpts) for chkpts in problems.values()
    ]


def compute_costs_stats(
    checkpoints: list[dict[str, Any]],
    problems: dict[str, list[dict[str, Any]]],
) -> CostsStats:
    """Compute cost statistics at checkpoint and problem levels."""
    checkpoint_costs = extract_metric_values(checkpoints, "cost")
    problem_costs = aggregate_per_problem(problems, "cost")

    return CostsStats(
        checkpoint=compute_metric_stats(checkpoint_costs),
        problem=compute_metric_stats(problem_costs),
        total=sum(checkpoint_costs) if checkpoint_costs else 0.0,
    )


def compute_time_stats(
    checkpoints: list[dict[str, Any]],
    problems: dict[str, list[dict[str, Any]]],
) -> TimeStats:
    """Compute time statistics at checkpoint and problem levels."""
    checkpoint_times = extract_metric_values(checkpoints, "elapsed")
    problem_times = aggregate_per_problem(problems, "elapsed")

    return TimeStats(
        checkpoint=compute_metric_stats(checkpoint_times),
        problem=compute_metric_stats(problem_times),
    )


def compute_tokens_stats(
    checkpoints: list[dict[str, Any]],
    problems: dict[str, list[dict[str, Any]]],
) -> TokenStats:
    """Compute token statistics: totals and per-level means."""
    token_types = ["input", "output", "cache_read", "cache_write", "reasoning"]

    # Extract checkpoint-level values and compute means
    checkpoint_values = {
        t: extract_metric_values(checkpoints, t) for t in token_types
    }
    checkpoint_means = TokenMeans(
        **{t: safe_mean(checkpoint_values[t]) for t in token_types}
    )

    # Aggregate per-problem totals and compute means
    problem_totals = {
        t: aggregate_per_problem(problems, t) for t in token_types
    }
    problem_means = TokenMeans(
        **{t: safe_mean(problem_totals[t]) for t in token_types}
    )

    return TokenStats(
        **{
            t: int(sum(checkpoint_values[t])) if checkpoint_values[t] else 0
            for t in token_types
        },
        checkpoint=checkpoint_means,
        problem=problem_means,
    )


def compute_steps_stats(
    checkpoints: list[dict[str, Any]],
    problems: dict[str, list[dict[str, Any]]],
) -> StepsStats:
    """Compute step statistics at checkpoint and problem levels."""
    checkpoint_steps = extract_metric_values(checkpoints, "steps")
    problem_steps = aggregate_per_problem(problems, "steps")

    return StepsStats(
        checkpoint=compute_metric_stats(checkpoint_steps),
        problem=compute_metric_stats(problem_steps),
    )


def compute_solve_rates(
    checkpoints: list[dict[str, Any]],
    problems: dict[str, list[dict[str, Any]]],
) -> dict[str, float | None]:
    """Compute solve rate percentages.

    Returns:
        Dict with pct_checkpoints_solved, pct_problems_solved, pct_problems_partial.
    """
    pass_rates_list = extract_metric_values(checkpoints, "pass_rate")
    iso_pass_rates_list = extract_metric_values(
        checkpoints, "checkpoint_pass_rate"
    )
    core_pass_rates_list = extract_metric_values(checkpoints, "core_pass_rate")

    if not pass_rates_list or not iso_pass_rates_list:
        return {}

    # Count checkpoints that fully pass (rate = 1.0)
    checkpoints_solved = sum(
        1 for pr in pass_rates_list if math.isclose(pr, 1.0)
    )
    iso_solved = sum(1 for pr in iso_pass_rates_list if math.isclose(pr, 1.0))
    core_solved = sum(1 for pr in core_pass_rates_list if math.isclose(pr, 1.0))

    # Count problems fully vs partially solved
    fully_solved = sum(
        1
        for chkpts in problems.values()
        if (rates := [c.get("pass_rate", 0.0) for c in chkpts])
        and all(pr == 1.0 for pr in rates)
    )
    partially_solved = sum(
        1
        for chkpts in problems.values()
        if (rates := [c.get("pass_rate", 0.0) for c in chkpts])
        and any(pr == 1.0 for pr in rates)
    )

    num_problems = len(problems)
    num_checkpoints = len(checkpoints)

    return {
        "pct_checkpoints_solved": (checkpoints_solved / num_checkpoints) * 100,
        "pct_checkpoints_iso_solved": (iso_solved / num_checkpoints) * 100,
        "pct_checkpoints_core_solved": (core_solved / num_checkpoints) * 100,
        "pct_problems_solved": (fully_solved / num_problems) * 100,
        "pct_problems_partial": (partially_solved / num_problems) * 100,
        "problem_solved": fully_solved,
        "problem_partial": partially_solved,
        "checkpoints_solved": checkpoints_solved,
        "checkpoints_iso_solved": iso_solved,
        "checkpoints_core_solved": core_solved,
    }


def compute_pass_rates_stats(
    checkpoints: list[dict[str, Any]],
    problems: dict[str, list[dict[str, Any]]],
) -> PassRatesStats:
    """Compute pass rate statistics by test type at checkpoint and problem levels.

    Note: Checkpoints with no tests for a given type (e.g., no error tests) are
    excluded from the average for that type.
    """
    test_types = ["core", "total", "error", "functionality", "regression"]

    def compute_pass_rates_by_type(
        chkpt: dict[str, Any],
    ) -> dict[str, float | None]:
        """Extract pass rates for all test types from a single checkpoint."""
        return {
            "total": compute_pass_rate(
                chkpt.get("passed_tests"), chkpt.get("total_tests")
            ),
            **{
                t: compute_pass_rate(
                    chkpt.get(f"{t}_passed"), chkpt.get(f"{t}_total")
                )
                for t in ["core", "error", "functionality", "regression"]
            },
        }

    def mean_excluding_none(values: list[float | None]) -> float:
        """Compute mean of non-None values, returning 0.0 if all are None."""
        valid = [v for v in values if v is not None]
        return statistics.mean(valid) if valid else 0.0

    # Collect checkpoint-level pass rates (excluding None for checkpoints with 0 tests)
    checkpoint_pass_rates: dict[str, list[float | None]] = {
        t: [] for t in test_types
    }
    for chkpt in checkpoints:
        rates = compute_pass_rates_by_type(chkpt)
        for test_type in test_types:
            checkpoint_pass_rates[test_type].append(rates[test_type])

    # Collect problem-level pass rates (mean across checkpoints per problem, excluding None)
    problem_pass_rates: dict[str, list[float]] = {t: [] for t in test_types}
    for problem_chkpts in problems.values():
        for test_type in test_types:
            rates = [
                compute_pass_rates_by_type(c)[test_type] for c in problem_chkpts
            ]
            problem_pass_rates[test_type].append(mean_excluding_none(rates))

    return PassRatesStats(
        checkpoint=PassRatesByType(
            **{
                t: mean_excluding_none(checkpoint_pass_rates[t])
                for t in test_types
            }
        ),
        problem=PassRatesByType(
            **{t: safe_mean(problem_pass_rates[t]) for t in test_types}
        ),
    )


def compute_cc_stats(
    checkpoints: list[dict[str, Any]],
) -> CyclomaticComplexityStats:
    """Compute CC (cyclomatic complexity) statistics."""
    high_counts = extract_metric_values(checkpoints, "cc_high_count")
    high_means = extract_metric_values(checkpoints, "high_cc_mean")
    max_values = extract_metric_values(checkpoints, "cc_max")

    return CyclomaticComplexityStats(
        high_count=compute_metric_stats(high_counts),
        high_mean=compute_metric_stats(high_means),
        max=compute_metric_stats(max_values),
    )


def compute_ratios_stats(checkpoints: list[dict[str, Any]]) -> RatiosStats:
    """Compute quality ratio statistics (per LOC)."""
    rubric_ratios = compute_ratio_values(
        checkpoints, "rubric_total_flags", "loc"
    )
    lint_ratios = compute_ratio_values(checkpoints, "lint_errors", "loc")
    ast_grep_ratios = compute_ratio_values(
        checkpoints, "ast_grep_violations", "loc"
    )

    return RatiosStats(
        rubric=compute_metric_stats(rubric_ratios),
        lint=compute_metric_stats(lint_ratios),
        ast_grep=compute_metric_stats(ast_grep_ratios),
    )


def compute_delta_stats(checkpoints: list[dict[str, Any]]) -> DeltaStats:
    """Compute delta statistics between consecutive checkpoints."""

    def extract_delta_values(key: str) -> list[float]:
        """Extract delta.{key} values from checkpoints (skipping None/inf)."""
        values: list[float] = []
        for chkpt in checkpoints:
            val = chkpt.get(f"delta.{key}")
            if val is not None and val != float("inf"):
                values.append(val)
        return values

    return DeltaStats(
        lint=compute_metric_stats(extract_delta_values("lint_errors")),
        complex=compute_metric_stats(extract_delta_values("cc_high_count")),
        comparisons=compute_metric_stats(extract_delta_values("comparisons")),
        ast_grep=compute_metric_stats(
            extract_delta_values("ast_grep_violations")
        ),
        rubric_non_carryover=compute_metric_stats(
            extract_delta_values("new_violations_per_loc")
        ),
    )


def compute_composite_scores(
    checkpoints: list[dict[str, Any]],
) -> dict[str, MetricStats]:
    """Compute verbosity and erosion composite scores.

    Verbosity measures code bloat: flags per LOC + wrapper/single-use ratios.
    Erosion measures code degradation: high complexity ratio + lint density.
    """
    verbosity_values: list[float] = []
    erosion_values: list[float] = []

    for chkpt in checkpoints:
        loc = chkpt.get("loc", 0)
        funcs = chkpt.get("functions", 0)
        methods = chkpt.get("methods", 0)
        total_callables = funcs + methods

        # Verbosity: (ast_grep + rubric) / loc + wrapper_ratios
        if loc > 0 and total_callables > 0:
            flags_per_loc = (
                chkpt.get("ast_grep_violations", 0)
                + chkpt.get("rubric_total_flags", 0)
            ) / loc
            wrapper_ratio = chkpt.get("trivial_wrappers", 0) / total_callables
            single_use_ratio = (
                chkpt.get("single_use_functions", 0) / total_callables
            )
            verbosity_values.append(
                flags_per_loc + wrapper_ratio + single_use_ratio
            )

        # Erosion: high complexity ratio + lint per LOC
        lint_per_loc = chkpt.get("lint_per_loc", 0.0) or 0.0
        if total_callables > 0:
            high_complex = (
                chkpt.get("cc_high_count", 0)
                + chkpt.get("cc_extreme_count", 0) * 2
            ) / total_callables
            erosion_values.append(high_complex + lint_per_loc)

    return {
        "verbosity": compute_metric_stats(verbosity_values),
        "erosion": compute_metric_stats(erosion_values),
    }
