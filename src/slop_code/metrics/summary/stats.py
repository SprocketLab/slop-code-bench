"""Statistical computation helpers for summary generation.

This module provides reusable functions for computing statistics
from checkpoint data.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from typing import Any

from slop_code.metrics.models import MetricStats


def compute_metric_stats(values: list[float]) -> MetricStats:
    """Compute mean, stddev, min, max, median for a list of values.

    Args:
        values: List of numeric values (may be empty).

    Returns:
        MetricStats with computed statistics, or None values if empty.
    """
    if not values:
        return MetricStats(count=0)

    count = len(values)
    mean_val = statistics.mean(values)
    median_val = statistics.median(values)
    min_val = min(values)
    max_val = max(values)

    # stddev requires at least 2 values
    stddev_val = statistics.stdev(values) if count >= 2 else None

    return MetricStats(
        mean=mean_val,
        stddev=stddev_val,
        min=min_val,
        max=max_val,
        median=median_val,
        count=count,
    )


def extract_metric_values(
    checkpoints: list[dict[str, Any]],
    key: str,
) -> list[float]:
    """Extract values for a metric from checkpoints."""
    return [chkpt[key] for chkpt in checkpoints if key in chkpt]


def compute_ratio_values(
    checkpoints: list[dict[str, Any]],
    numerator_key: str,
    denominator_key: str,
) -> list[float]:
    """Compute ratio values for each checkpoint.

    Args:
        checkpoints: List of checkpoint dictionaries.
        numerator_key: Key for numerator value.
        denominator_key: Key for denominator value.

    Returns:
        List of ratios (excluding cases where denominator is 0 or missing).
    """
    values: list[float] = []
    for chkpt in checkpoints:
        num = chkpt.get(numerator_key)
        denom = chkpt.get(denominator_key)
        if num is not None and denom is not None and denom > 0:
            values.append(num / denom)
    return values


def compute_pass_rate(passed: float | None, total: float | None) -> float:
    """Compute pass rate safely, returning 0.0 if total is 0 or missing."""
    if total is None or total == 0:
        return 0.0
    if passed is None:
        return 0.0
    return passed / total


def group_by_problem(
    checkpoints: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Group checkpoints by problem name."""
    problems: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for chkpt in checkpoints:
        problem_name = chkpt.get("problem", "unknown")
        problems[problem_name].append(chkpt)
    return problems
