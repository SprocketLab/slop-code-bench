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
    return MetricStats(
        mean=statistics.mean(values),
        stddev=statistics.stdev(values) if count >= 2 else None,
        min=min(values),
        max=max(values),
        median=statistics.median(values),
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
    ratios = []
    for chkpt in checkpoints:
        num = chkpt.get(numerator_key)
        denom = chkpt.get(denominator_key)
        if num is not None and denom and denom > 0:
            ratios.append(num / denom)
    return ratios


def compute_pass_rate(passed: float | None, total: float | None) -> float | None:
    """Compute pass rate safely.

    Returns:
        Pass rate as a float, or None if there are no tests (total=0 or missing).
    """
    if not total or passed is None:
        return None
    return passed / total


def group_by_problem(
    checkpoints: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Group checkpoints by problem name."""
    problems = defaultdict(list)
    for chkpt in checkpoints:
        problems[chkpt.get("problem", "unknown")].append(chkpt)
    return problems
