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


def compute_costs_stats(
    checkpoints: list[dict[str, Any]],
    problems: dict[str, list[dict[str, Any]]],
) -> CostsStats:
    """Compute cost statistics at checkpoint and problem levels."""
    checkpoint_costs = extract_metric_values(checkpoints, "cost")
    total_cost = sum(checkpoint_costs) if checkpoint_costs else 0.0

    problem_costs: list[float] = []
    for problem_chkpts in problems.values():
        problem_cost = sum(c.get("cost", 0) for c in problem_chkpts)
        problem_costs.append(problem_cost)

    return CostsStats(
        checkpoint=compute_metric_stats(checkpoint_costs),
        problem=compute_metric_stats(problem_costs),
        total=total_cost,
    )


def compute_time_stats(
    checkpoints: list[dict[str, Any]],
    problems: dict[str, list[dict[str, Any]]],
) -> TimeStats:
    """Compute time statistics at checkpoint and problem levels."""
    checkpoint_times = extract_metric_values(checkpoints, "elapsed")

    problem_times: list[float] = []
    for problem_chkpts in problems.values():
        problem_time = sum(c.get("elapsed", 0) for c in problem_chkpts)
        problem_times.append(problem_time)

    return TimeStats(
        checkpoint=compute_metric_stats(checkpoint_times),
        problem=compute_metric_stats(problem_times),
    )


def compute_tokens_stats(
    checkpoints: list[dict[str, Any]],
    problems: dict[str, list[dict[str, Any]]],
) -> TokenStats:
    """Compute token statistics: totals and per-level means."""
    input_values = extract_metric_values(checkpoints, "input")
    output_values = extract_metric_values(checkpoints, "output")
    cache_read_values = extract_metric_values(checkpoints, "cache_read")
    cache_write_values = extract_metric_values(checkpoints, "cache_write")
    reasoning_values = extract_metric_values(checkpoints, "reasoning")

    # Per-checkpoint means
    checkpoint_token_means = TokenMeans(
        input=statistics.mean(input_values) if input_values else 0.0,
        output=statistics.mean(output_values) if output_values else 0.0,
        cache_read=statistics.mean(cache_read_values) if cache_read_values else 0.0,
        cache_write=statistics.mean(cache_write_values) if cache_write_values else 0.0,
        reasoning=statistics.mean(reasoning_values) if reasoning_values else 0.0,
    )

    # Per-problem token totals, then compute means
    problem_input: list[float] = []
    problem_output: list[float] = []
    problem_cache_read: list[float] = []
    problem_cache_write: list[float] = []
    problem_reasoning: list[float] = []

    for problem_chkpts in problems.values():
        problem_input.append(sum(c.get("input", 0) for c in problem_chkpts))
        problem_output.append(sum(c.get("output", 0) for c in problem_chkpts))
        problem_cache_read.append(sum(c.get("cache_read", 0) for c in problem_chkpts))
        problem_cache_write.append(sum(c.get("cache_write", 0) for c in problem_chkpts))
        problem_reasoning.append(sum(c.get("reasoning", 0) for c in problem_chkpts))

    problem_token_means = TokenMeans(
        input=statistics.mean(problem_input) if problem_input else 0.0,
        output=statistics.mean(problem_output) if problem_output else 0.0,
        cache_read=statistics.mean(problem_cache_read) if problem_cache_read else 0.0,
        cache_write=statistics.mean(problem_cache_write)
        if problem_cache_write
        else 0.0,
        reasoning=statistics.mean(problem_reasoning) if problem_reasoning else 0.0,
    )

    return TokenStats(
        input=int(sum(input_values)) if input_values else 0,
        output=int(sum(output_values)) if output_values else 0,
        cache_read=int(sum(cache_read_values)) if cache_read_values else 0,
        cache_write=int(sum(cache_write_values)) if cache_write_values else 0,
        reasoning=int(sum(reasoning_values)) if reasoning_values else 0,
        checkpoint=checkpoint_token_means,
        problem=problem_token_means,
    )


def compute_steps_stats(
    checkpoints: list[dict[str, Any]],
    problems: dict[str, list[dict[str, Any]]],
) -> StepsStats:
    """Compute step statistics at checkpoint and problem levels."""
    checkpoint_steps = extract_metric_values(checkpoints, "steps")

    problem_steps: list[float] = []
    for problem_chkpts in problems.values():
        problem_step = sum(c.get("steps", 0) for c in problem_chkpts)
        problem_steps.append(problem_step)

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
    iso_pass_rates_list = extract_metric_values(checkpoints, "checkpoint_pass_rate")
    core_pass_rates_list = extract_metric_values(checkpoints, "core_pass_rate")
    num_problems = len(problems)
    if not pass_rates_list or not iso_pass_rates_list:
        return {}

    checkpoints_solved = sum(1 for pr in pass_rates_list if math.isclose(pr, 1.0))
    iso_solved = sum(1 for pr in iso_pass_rates_list if math.isclose(pr, 1.0))
    core_solved = sum(1 for pr in core_pass_rates_list if math.isclose(pr, 1.0))
    pct_problems_solved: float | None = None
    pct_problems_partial: float | None = None

    fully_solved = 0
    partially_solved = 0
    for problem_chkpts in problems.values():
        problem_pass_rates = [c.get("pass_rate", 0.0) for c in problem_chkpts]
        if problem_pass_rates:
            if all(pr == 1.0 for pr in problem_pass_rates):
                fully_solved += 1
            if any(pr == 1.0 for pr in problem_pass_rates):
                partially_solved += 1
    pct_problems_solved = (fully_solved / num_problems) * 100
    pct_problems_partial = (partially_solved / num_problems) * 100

    return {
        "pct_checkpoints_solved": checkpoints_solved / len(checkpoints) * 100,
        "pct_checkpoints_iso_solved": iso_solved / len(checkpoints) * 100,
        "pct_problems_solved": pct_problems_solved,
        "pct_problems_partial": pct_problems_partial,
        "pct_checkpoints_core_solved": core_solved / len(checkpoints) * 100,
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
    """Compute pass rate statistics by test type at checkpoint and problem levels."""
    test_types = ["core", "total", "error", "functionality", "regression"]

    # Per-checkpoint pass rates by type
    checkpoint_pass_rates: dict[str, list[float]] = {t: [] for t in test_types}
    for chkpt in checkpoints:
        checkpoint_pass_rates["total"].append(
            compute_pass_rate(chkpt.get("passed_tests"), chkpt.get("total_tests"))
        )
        for test_type in ["core", "error", "functionality", "regression"]:
            checkpoint_pass_rates[test_type].append(
                compute_pass_rate(
                    chkpt.get(f"{test_type}_passed"),
                    chkpt.get(f"{test_type}_total"),
                )
            )

    # Per-problem pass rates by type (mean of checkpoint pass rates per problem)
    problem_pass_rates: dict[str, list[float]] = {t: [] for t in test_types}
    for problem_chkpts in problems.values():
        for test_type in test_types:
            if test_type == "total":
                rates = [
                    compute_pass_rate(c.get("passed_tests"), c.get("total_tests"))
                    for c in problem_chkpts
                ]
            else:
                rates = [
                    compute_pass_rate(
                        c.get(f"{test_type}_passed"),
                        c.get(f"{test_type}_total"),
                    )
                    for c in problem_chkpts
                ]
            problem_pass_rates[test_type].append(
                statistics.mean(rates) if rates else 0.0
            )

    def safe_mean(values: list[float]) -> float:
        return statistics.mean(values) if values else 0.0

    return PassRatesStats(
        checkpoint=PassRatesByType(
            core=safe_mean(checkpoint_pass_rates["core"]),
            total=safe_mean(checkpoint_pass_rates["total"]),
            error=safe_mean(checkpoint_pass_rates["error"]),
            functionality=safe_mean(checkpoint_pass_rates["functionality"]),
            regression=safe_mean(checkpoint_pass_rates["regression"]),
        ),
        problem=PassRatesByType(
            core=safe_mean(problem_pass_rates["core"]),
            total=safe_mean(problem_pass_rates["total"]),
            error=safe_mean(problem_pass_rates["error"]),
            functionality=safe_mean(problem_pass_rates["functionality"]),
            regression=safe_mean(problem_pass_rates["regression"]),
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
    rubric_ratios = compute_ratio_values(checkpoints, "rubric_total_flags", "loc")
    lint_ratios = compute_ratio_values(checkpoints, "lint_errors", "loc")
    ast_grep_ratios = compute_ratio_values(checkpoints, "ast_grep_violations", "loc")

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
        ast_grep=compute_metric_stats(extract_delta_values("ast_grep_violations")),
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
                chkpt.get("ast_grep_violations", 0) + chkpt.get("rubric_total_flags", 0)
            ) / loc
            wrapper_ratio = chkpt.get("trivial_wrappers", 0) / total_callables
            single_use_ratio = chkpt.get("single_use_functions", 0) / total_callables
            verbosity_values.append(flags_per_loc + wrapper_ratio + single_use_ratio)

        # Erosion: high complexity ratio + lint per LOC
        lint_per_loc = chkpt.get("lint_per_loc", 0.0) or 0.0
        if total_callables > 0:
            high_complex = (
                chkpt.get("cc_high_count", 0) + chkpt.get("cc_extreme_count", 0)
            ) / total_callables
            erosion_values.append(high_complex + lint_per_loc)

    return {
        "verbosity": compute_metric_stats(verbosity_values),
        "erosion": compute_metric_stats(erosion_values),
    }
