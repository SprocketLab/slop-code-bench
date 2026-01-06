"""Delta computation between consecutive checkpoints.

This module provides functions to compute percentage changes in metrics
between consecutive checkpoints.
"""

from __future__ import annotations

from typing import Any

# Metric keys for which to compute percentage deltas between checkpoints.
# Each key will be prefixed with "delta." in the output.
# Only keys that are actually consumed by dashboard/summary/variance.
DELTA_METRIC_KEYS: tuple[str, ...] = (
    "loc",
    "lint_errors",
    "ast_grep_violations",
    "cc_high_count",
    "comparisons",
)


def safe_ratio(numerator: float | None, denominator: float | None) -> float:
    """Compute numerator / denominator with zero handling.

    Args:
        numerator: Value to divide.
        denominator: Value to divide by.

    Returns:
        Ratio, 0 if both are 0, inf if denominator is 0 but numerator isn't.
    """
    numer = numerator or 0
    denom = denominator or 0

    if denom == 0:
        return 0.0 if numer == 0 else float("inf")

    return numer / denom


def safe_delta_pct(prev_val: float | None, curr_val: float | None) -> float:
    """Compute (curr - prev) / prev * 100 with zero handling.

    Args:
        prev_val: Previous checkpoint value.
        curr_val: Current checkpoint value.

    Returns:
        Percentage change, 0 if both are 0, inf if prev is 0 but curr isn't.
    """
    prev = prev_val or 0
    curr = curr_val or 0
    return safe_ratio(curr - prev, prev) * 100


def compute_checkpoint_delta(
    prev_metrics: dict[str, Any] | None,
    curr_metrics: dict[str, Any],
) -> dict[str, float | None]:
    """Compute percentage delta metrics between two consecutive checkpoints.

    All deltas are percentage changes: ((curr - prev) / prev) * 100.
    When prev == 0, returns float('inf') if curr > 0, else 0.

    Args:
        prev_metrics: Metrics from checkpoint N (from get_checkpoint_metrics).
                      Pass None for first checkpoint.
        curr_metrics: Metrics from checkpoint N+1.

    Returns:
        Dict with delta.* keys containing percentage changes.
        Returns empty dict if prev_metrics is None (first checkpoint).
    """
    if prev_metrics is None:
        return {}

    result: dict[str, float | None] = {}

    # Compute percentage deltas for all standard metrics
    for key in DELTA_METRIC_KEYS:
        result[f"delta.{key}"] = safe_delta_pct(
            prev_metrics.get(key), curr_metrics.get(key)
        )

    # Compute churn ratio: (lines_added + lines_removed) / prev_total_lines
    churn = curr_metrics["lines_added"] + curr_metrics["lines_removed"]
    prev_total_lines = prev_metrics["total_lines"]
    result["delta.churn_ratio"] = safe_ratio(churn, prev_total_lines)

    # Compute new violations per LOC if rubric metrics exist
    if "rubric_total_flags" in curr_metrics:
        new_flags = (
            curr_metrics["rubric_total_flags"]
            - curr_metrics["rubric_carried_over"]
        )
        result["delta.new_violations_per_loc"] = safe_ratio(
            new_flags, curr_metrics["loc"]
        )

    return result
