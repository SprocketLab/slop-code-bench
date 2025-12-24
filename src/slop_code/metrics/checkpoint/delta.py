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


def safe_delta_pct(prev_val: float | None, curr_val: float | None) -> float:
    """Compute (curr - prev) / prev * 100 with zero handling.

    Args:
        prev_val: Previous checkpoint value.
        curr_val: Current checkpoint value.

    Returns:
        Percentage change, 0 if both are 0, inf if prev is 0 but curr isn't.
    """
    prev_val = prev_val or 0
    curr_val = curr_val or 0
    if prev_val > 0:
        return ((curr_val - prev_val) / prev_val) * 100
    return 0 if curr_val == 0 else float("inf")


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

    # churn_ratio: curr.lines.churn / prev.lines.total
    churn = curr_metrics["lines_added"] + curr_metrics["lines_removed"]
    result["delta.churn_ratio"] = (
        churn / prev_metrics["total_lines"]
        if prev_metrics["total_lines"] > 0
        else (0 if churn == 0 else float("inf"))
    )
    if "rubric_total_flags" in curr_metrics:
        # new_violations_per_loc: (rubric_total_flags - rubric.carried_over) / curr.lines.loc
        curr_total_flags = curr_metrics["rubric_total_flags"]
        curr_carried_over = curr_metrics["rubric_carried_over"]
        curr_lines_loc = curr_metrics["loc"]
        new_flags = curr_total_flags - curr_carried_over
        result["delta.new_violations_per_loc"] = new_flags / curr_lines_loc

    return result
