"""Main entry point for checkpoint metric extraction.

This module provides the orchestrating function that combines all metric
extractors to produce a complete checkpoint metrics dictionary.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from slop_code.common import SNAPSHOT_DIR_NAME
from slop_code.logging import get_logger
from slop_code.metrics.checkpoint.delta import compute_checkpoint_delta
from slop_code.metrics.checkpoint.extractors import get_evaluation_metrics
from slop_code.metrics.checkpoint.extractors import get_inference_metrics
from slop_code.metrics.checkpoint.extractors import get_quality_metrics
from slop_code.metrics.checkpoint.extractors import get_rubric_metrics

logger = get_logger(__name__)

# `scb-check` owns the composite quality scores, and its rule set changes
# between releases, so an unpinned `uvx` invocation makes verbosity
# incomparable across runs. Bump this deliberately; the value is recorded
# with every checkpoint so past results stay interpretable.
SCB_CHECK_VERSION = "0.1.3"


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


def _scb_check_metrics_from_report(report: dict[str, Any]) -> dict[str, Any]:
    """Extract checkpoint metrics owned by scb-check's report."""
    metrics: dict[str, Any] = {}

    verbosity = _number(report.get("verbosity"))
    if verbosity is not None:
        metrics["verbosity"] = verbosity

    erosion = _number(report.get("erosion"))
    if erosion is not None:
        metrics["erosion"] = erosion

    clone_loc = _number(report.get("clone_loc"))
    if clone_loc is not None:
        metrics["cloned_sloc_lines"] = int(clone_loc)

    verbosity_flagged_loc = _number(report.get("verbosity_flagged_loc"))
    if verbosity_flagged_loc is not None:
        metrics["verbosity_flagged_sloc_lines"] = int(verbosity_flagged_loc)

    total_loc = _number(report.get("total_loc"))
    if total_loc is None or total_loc <= 0:
        return metrics

    if clone_loc is not None:
        metrics["cloned_pct"] = clone_loc / total_loc
    if verbosity_flagged_loc is not None:
        metrics["verbosity_flagged_pct"] = verbosity_flagged_loc / total_loc

    return metrics


def _get_scb_check_metrics(checkpoint_dir: Path) -> dict[str, Any]:
    """Run scb-check for composite quality metrics for a checkpoint."""
    snapshot_dir = checkpoint_dir / SNAPSHOT_DIR_NAME
    if not snapshot_dir.exists():
        return {}

    command = [
        "uvx",
        f"scb-check=={SCB_CHECK_VERSION}",
        "check",
        "--report",
        "--include-all",
        str(snapshot_dir),
    ]
    try:
        completed = subprocess.run(  # noqa: S603 - command is fixed above.
            command,  # noqa: S607 - uvx must resolve from the active PATH.
            check=True,
            capture_output=True,
            text=True,
        )
        report = json.loads(completed.stdout)
    except subprocess.CalledProcessError as e:
        logger.warning(
            "scb-check failed",
            checkpoint_dir=str(checkpoint_dir),
            snapshot_dir=str(snapshot_dir),
            returncode=e.returncode,
            stderr=e.stderr,
        )
        return {}
    except (OSError, json.JSONDecodeError) as e:
        logger.warning(
            "Failed to load scb-check report",
            checkpoint_dir=str(checkpoint_dir),
            snapshot_dir=str(snapshot_dir),
            error=str(e),
        )
        return {}

    metrics = _scb_check_metrics_from_report(report)
    metrics["scb_check_version"] = SCB_CHECK_VERSION
    return metrics


def get_checkpoint_metrics(
    checkpoint_dir: Path,
    prior_metrics: dict | None = None,
    prior_checkpoint_dir: Path | None = None,
    is_first: bool = False,  # noqa: FBT001,FBT002
    is_last: bool = False,  # noqa: FBT001,FBT002
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
        metrics["rubric_per_loc"] = (
            metrics["rubric_total_flags"] / metrics["loc"]
        )

    metrics.update(_get_scb_check_metrics(checkpoint_dir))

    # Compute deltas from prior checkpoint
    delta = compute_checkpoint_delta(prior_metrics, metrics)

    return {
        "is_first": is_first,
        "is_last": is_last,
        **metrics,
        **delta,
    }
