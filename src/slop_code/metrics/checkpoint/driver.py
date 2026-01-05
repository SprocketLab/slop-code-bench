"""Main entry point for checkpoint metric extraction.

This module provides the orchestrating function that combines all metric
extractors to produce a complete checkpoint metrics dictionary.
"""

from __future__ import annotations

from pathlib import Path

from slop_code.common import QUALITY_DIR
from slop_code.common import SYMBOLS_QUALITY_SAVENAME
from slop_code.metrics.checkpoint.delta import compute_checkpoint_delta
from slop_code.metrics.checkpoint.extractors import get_evaluation_metrics
from slop_code.metrics.checkpoint.extractors import get_inference_metrics
from slop_code.metrics.checkpoint.extractors import get_quality_metrics
from slop_code.metrics.checkpoint.extractors import get_rubric_metrics
from slop_code.metrics.checkpoint.mass import compute_mass_delta


def get_checkpoint_metrics(
    checkpoint_dir: Path,
    prior_metrics: dict | None = None,
    prior_checkpoint_dir: Path | None = None,
    is_first: bool = False,
    is_last: bool = False,
) -> dict:
    """Extract all metrics for a checkpoint directory.

    Combines evaluation, inference, quality, and rubric metrics into a single dict.

    Args:
        checkpoint_dir: Path to the checkpoint directory.
        prior_metrics: Metrics from previous checkpoint (for percentage deltas).
        prior_checkpoint_dir: Path to previous checkpoint directory (for mass deltas).
        is_first: Whether this is the first checkpoint.
        is_last: Whether this is the last checkpoint.
    Returns:
        Dictionary with all metrics combined. Keys use dot-notation for namespacing.

    Raises:
        MetricsError: If any metric extraction fails.
    """
    metrics = {
        **get_evaluation_metrics(checkpoint_dir),
        **get_inference_metrics(checkpoint_dir),
        **get_quality_metrics(checkpoint_dir),
        **get_rubric_metrics(checkpoint_dir),
    }

    # Add rubric density metric if applicable
    if "rubric_total_flags" in metrics and metrics.get("loc", 0) > 0:
        metrics["rubric_per_loc"] = metrics["rubric_total_flags"] / metrics["loc"]

    # Compute deltas from prior checkpoint
    delta = compute_checkpoint_delta(prior_metrics, metrics)

    # Add mass deltas if prior checkpoint exists
    if prior_checkpoint_dir is not None:
        prior_symbols = prior_checkpoint_dir / QUALITY_DIR / SYMBOLS_QUALITY_SAVENAME
        curr_symbols = checkpoint_dir / QUALITY_DIR / SYMBOLS_QUALITY_SAVENAME
        delta.update(compute_mass_delta(prior_symbols, curr_symbols))

    return {
        "is_first": is_first,
        "is_last": is_last,
        **metrics,
        **delta,
    }
