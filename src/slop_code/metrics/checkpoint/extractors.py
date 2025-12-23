"""Metric extractors for checkpoint directories.

This module provides functions to extract specific metric categories from
checkpoint directories by reading and processing various JSON/JSONL files.
"""

from __future__ import annotations

import json
import statistics
from collections.abc import Generator
from datetime import datetime
from pathlib import Path
from typing import Any

from slop_code.common import EVALUATION_FILENAME
from slop_code.common import INFERENCE_RESULT_FILENAME
from slop_code.common import QUALITY_METRIC_SAVENAME
from slop_code.logging import get_logger
from slop_code.metrics.checkpoint.loaders import load_diff_metrics
from slop_code.metrics.checkpoint.loaders import load_file_metrics
from slop_code.metrics.checkpoint.loaders import load_snapshot_metrics
from slop_code.metrics.checkpoint.loaders import load_symbol_metrics
from slop_code.metrics.checkpoint.mass import compute_mass_metrics
from slop_code.metrics.models import MetricsThresholds
from slop_code.metrics.utils import MetricsError

logger = get_logger(__name__)


def _compute_distributions(
    file_metrics_iter: Generator[dict, None, None],
    symbol_metrics_iter: Generator[dict, None, None],
    diff: dict | None,
) -> dict[str, Any]:
    """Compute distribution metrics from file-level and symbol-level data.

    This computes metrics that require iterating through individual files/symbols:
    - Lines added/removed (for churn calculation)
    - Function aggregates (LOC, comparisons, try/except scaffolds)

    Args:
        file_metrics_iter: Iterator over flat file metrics from files.jsonl.
        symbol_metrics_iter: Iterator over flat symbol metrics from symbols.jsonl.
        diff: Parsed diff.json or None.
    """
    lines_added = 0
    lines_removed = 0

    # Process file metrics for diff tracking
    for fm in file_metrics_iter:
        file_path = fm["file_path"]
        if diff is not None and file_path in diff["file_diffs"]:
            file_diff = diff["file_diffs"][file_path]
            lines_added += file_diff["lines_added"]
            lines_removed += file_diff["lines_removed"]

    # Function-specific aggregates
    func_lines: list[int] = []
    func_comparisons: list[int] = []
    func_try_counts: list[int] = []

    # Process symbol metrics for function aggregates
    for s in symbol_metrics_iter:
        if s.get("type") in {"function", "method"}:
            func_lines.append(s["lines"])
            func_comparisons.append(s["comparisons"])
            func_try_counts.append(s["exception_scaffold"])

    return {
        "lines_added": lines_added,
        "lines_removed": lines_removed,
        "mean_func_loc": statistics.mean(func_lines) if func_lines else 0.0,
        "comparisons": sum(func_comparisons),
        "try_scaffold": sum(func_try_counts),
    }


def _build_metrics_from_snapshot(
    snapshot: dict, distributions: dict[str, Any]
) -> dict[str, Any]:
    """Build flat metrics dict from SnapshotMetrics structure.

    Args:
        snapshot: Dict from SnapshotMetrics.model_dump() with nested fields:
            - lines, lint, symbols, functions, classes, waste, redundancy, etc.
        distributions: Pre-computed distribution metrics from file iteration.

    Returns:
        Flat dict with keys for metrics.
    """
    file_count = snapshot["file_count"]

    # Extract nested objects
    lines = snapshot["lines"]
    lint = snapshot["lint"]
    symbols = snapshot["symbols"]
    functions = snapshot["functions"]
    waste = snapshot["waste"]
    redundancy = snapshot["redundancy"]
    # Backwards compatibility with old metrics
    ast_grep = snapshot.get("ast_grep") or snapshot.get("slop", {})

    total_loc = lines["loc"]

    result: dict[str, Any] = {
        # Lines
        "loc": total_loc,
        "total_lines": lines["total_lines"],
        "single_comments": lines["single_comment"],
        # Lint
        "lint_errors": lint["errors"],
        "lint_fixable": lint["fixable"],
        "files": file_count,
        # Symbols
        "functions": symbols["functions"],
        "methods": symbols["methods"],
        "classes": symbols["classes"],
        "statements": symbols["statements"],
        "symbols_total": symbols["total"],
        # Function stats (pre-computed from FunctionStats)
        "cc_max": functions["cc_max"],
        "cc_mean": functions["cc_mean"],
        "cc_std": functions["cc_std"],
        "cc_high_count": functions["cc_high_count"],
        "cc_extreme_count": functions["cc_extreme_count"],
        "high_cc_mean": functions["high_cc_mean"],
        "cc_normalized": functions["cc_normalized"],
        "cc_concentration": functions["cc_concentration"],
        "max_nesting_depth": functions["depth_max"],
        "lines_per_symbol": functions["lines_mean"],
        # Distribution stats (mean, concentration)
        # Use .get() for backwards compatibility with old data
        "nesting_mean": functions.get("nesting_mean", 0.0),
        "nesting_concentration": functions.get("nesting_concentration", 0.0),
        "comparisons_mean": functions.get("comparisons_mean", 0.0),
        "comparisons_concentration": functions.get("comparisons_concentration", 0.0),
        "branches_mean": functions.get("branches_mean", 0.0),
        "branches_concentration": functions.get("branches_concentration", 0.0),
        "control_mean": functions.get("control_mean", 0.0),
        "control_concentration": functions.get("control_concentration", 0.0),
        # Waste
        "single_use_functions": waste["single_use_functions"],
        "trivial_wrappers": waste["trivial_wrappers"],
        "single_method_classes": waste["single_method_classes"],
        # Redundancy (raw counts only)
        "clone_instances": redundancy["clone_instances"],
        "clone_lines": redundancy["clone_lines"],
        # AST-grep
        "ast_grep_violations": ast_grep.get("violations", 0),
        # Source file tracking
        "source_file_count": snapshot.get("source_file_count", file_count),
    }

    # Add per-category AST-grep violation counts (not weighted)
    category_counts = ast_grep.get("category_counts", {})
    for cat in [
        "verbosity",
        "naming",
        "performance",
        "types",
        "safety",
        "style",
        "complexity",
    ]:
        result[f"sg_{cat}_violations"] = category_counts.get(cat, 0)

    # Per-LOC normalized metrics (only those actually used)
    if total_loc > 0:
        result["ast_grep_per_loc"] = ast_grep.get("violations", 0) / total_loc
        result["lint_per_loc"] = lint["errors"] / total_loc

    # Graph metrics (optional, may be None for non-Python or old data)
    # Only keep the metrics that are actually used in dashboard
    graph = snapshot.get("graph")
    if graph:
        result.update(
            {
                "graph_cyclic_dependency_mass": graph["cyclic_dependency_mass"],
                "graph_propagation_cost": graph["propagation_cost"],
                "graph_dependency_entropy": graph["dependency_entropy"],
            }
        )

    # Merge distribution metrics from file/symbol iteration
    result.update(distributions)
    return result


def get_evaluation_metrics(
    checkpoint_dir: Path, eval_file_name: str = EVALUATION_FILENAME
) -> dict:
    """Extract evaluation metrics with flattened test results.

    Returns a flat dict with dot-notation keys for tests:
    - total_tests, passed_tests: Overall counts
    - core_total, core_passed: Core test counts
    - functionality_total, functionality_passed: Functionality counts
    - error_total, error_passed: Error handling test counts
    - regression_total, regression_passed: Regression test counts
    """
    eval_file = checkpoint_dir / eval_file_name
    if not eval_file.exists():
        logger.warning(
            "Evaluation file not found",
            checkpoint_dir=str(checkpoint_dir),
            eval_file=str(eval_file),
        )
        return {}

    try:
        with eval_file.open("r") as f:
            metrics = json.load(f)
    except json.JSONDecodeError as e:
        logger.error(
            "Failed to parse evaluation JSON",
            checkpoint_dir=str(checkpoint_dir),
            eval_file=str(eval_file),
            error=str(e),
        )
        raise MetricsError(
            f"Failed to parse evaluation file '{eval_file}': {e}",
            context={"checkpoint_dir": str(checkpoint_dir)},
        ) from e

    # Initialize counters for each test type
    tests_by_type: dict[str, dict[str, int]] = {
        "core": {"passed": 0, "total": 0},
        "functionality": {"passed": 0, "total": 0},
        "error": {"passed": 0, "total": 0},
        "regression": {"passed": 0, "total": 0},
    }

    checkpoint_passed = checkpoint_total = 0
    total_passed = total_total = 0
    core_passed = core_total = 0

    for c_type, c_total in metrics["total_counts"].items():
        c_passed = metrics["pass_counts"].get(c_type, 0)

        # Map to lowercase key
        type_key = c_type.lower()
        if type_key in tests_by_type:
            tests_by_type[type_key]["passed"] = c_passed
            tests_by_type[type_key]["total"] = c_total

        if c_type == "Core":
            core_passed += c_passed
            core_total += c_total
        if c_type != "Regression":
            checkpoint_passed += c_passed
            checkpoint_total += c_total
        total_passed += c_passed
        total_total += c_total

    return {
        "pass_rate": total_passed / total_total if total_total > 0 else 0,
        "core_pass_rate": core_passed / core_total if core_total > 0 else 0,
        "checkpoint_pass_rate": (
            checkpoint_passed / checkpoint_total if checkpoint_total > 0 else 0
        ),
        "duration": metrics["duration"],
        # Flattened tests
        "total_tests": total_total,
        "passed_tests": total_passed,
        "core_total": tests_by_type["core"]["total"],
        "core_passed": tests_by_type["core"]["passed"],
        "functionality_total": tests_by_type["functionality"]["total"],
        "functionality_passed": tests_by_type["functionality"]["passed"],
        "error_total": tests_by_type["error"]["total"],
        "error_passed": tests_by_type["error"]["passed"],
        "regression_total": tests_by_type["regression"]["total"],
        "regression_passed": tests_by_type["regression"]["passed"],
    }


def get_inference_metrics(
    checkpoint_dir: Path, inference_file_name: str = INFERENCE_RESULT_FILENAME
) -> dict:
    """Extract inference metrics from inference_result.json."""
    inference_file = checkpoint_dir / inference_file_name
    if not inference_file.exists():
        return {}

    try:
        with inference_file.open("r") as f:
            metrics = json.load(f)
    except json.JSONDecodeError as e:
        logger.error(
            "Failed to parse inference JSON",
            checkpoint_dir=str(checkpoint_dir),
            inference_file=str(inference_file),
            error=str(e),
        )
        raise MetricsError(
            f"Failed to parse inference file '{inference_file}': {e}",
            context={"checkpoint_dir": str(checkpoint_dir)},
        ) from e

    try:
        started = datetime.fromisoformat(metrics["started"])
        ended = datetime.fromisoformat(metrics["completed"])
        elapsed = (ended - started).total_seconds()
        return {
            "started": started.isoformat(),
            "ended": ended.isoformat(),
            "elapsed": elapsed,
            "cost": metrics["usage"]["cost"],
            "steps": metrics["usage"]["steps"],
            **metrics["usage"]["net_tokens"],
        }
    except (KeyError, ValueError) as e:
        logger.error(
            "Invalid inference metrics structure",
            checkpoint_dir=str(checkpoint_dir),
            error=str(e),
        )
        raise MetricsError(
            f"Invalid inference metrics in '{inference_file}': {e}",
            context={"checkpoint_dir": str(checkpoint_dir)},
        ) from e


def get_quality_metrics(
    checkpoint_dir: Path,
    quality_file_name: str = QUALITY_METRIC_SAVENAME,
    thresholds: MetricsThresholds | None = None,
) -> dict:
    """Extract and aggregate quality metrics into a flat structure.

    This function reads SnapshotMetrics from overall_quality.json and
    computes distribution metrics from file_quality.jsonl.

    Args:
        checkpoint_dir: Path to the checkpoint directory.
        quality_file_name: Name of the quality metrics file.
        thresholds: Configurable thresholds for distribution buckets.

    Returns:
        A flat dict with dot-notation keys for namespacing:
        - lines.*: Line count aggregations
        - quality.*: Code quality aggregations
        - files.*: File change counts
        - symbols.*: Symbol type counts and complexity ratings
        - waste.*: Abstraction waste metrics
        - redundancy.*: Code clone metrics
        - ast_grep.*: AST-grep violation metrics
    """
    if thresholds is None:
        thresholds = MetricsThresholds()

    snapshot_data = load_snapshot_metrics(checkpoint_dir, quality_file_name)
    if snapshot_data is None:
        return {}

    # Compute distributions from file-level and symbol-level data
    diff = load_diff_metrics(checkpoint_dir)
    file_metrics_iter = load_file_metrics(checkpoint_dir)
    symbol_metrics_iter = load_symbol_metrics(checkpoint_dir)
    distributions = _compute_distributions(
        file_metrics_iter,
        symbol_metrics_iter,
        diff,
    )

    # Compute mass metrics (needs separate iterator since we consume it)
    mass_symbol_iter = load_symbol_metrics(checkpoint_dir)
    mass_metrics = compute_mass_metrics(mass_symbol_iter)

    # Build flat metrics from SnapshotMetrics structure (data is at root level)
    result = _build_metrics_from_snapshot(snapshot_data, distributions)
    result.update(mass_metrics)
    return result


def get_rubric_metrics(
    checkpoint_dir: Path, rubric_file_name: str = "rubric.jsonl"
) -> dict:
    """Extract rubric metrics with flattened criteria counts.

    Returns a flat dict with dot-notation keys:
    - rubric_total_flags: Total number of rubric violations
    - rubric.files_flagged: Number of unique files with violations
    - rubric.carried_over: Number of grades carried over from previous checkpoint
    - rubric_verbosity_flags: Count of verbosity-type violations
    - rubric_erosion_flags: Count of erosion-type violations

    Args:
        checkpoint_dir: Path to the checkpoint directory.
        rubric_file_name: Name of the rubric grades file (JSONL format).

    Returns:
        Dictionary with rubric metrics, or empty dict if file doesn't exist.
    """
    rubric_file = checkpoint_dir / rubric_file_name
    if not rubric_file.exists():
        return {}

    grades = []
    try:
        with rubric_file.open("r") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    grades.append(json.loads(line))
                except json.JSONDecodeError as e:
                    logger.warning(
                        "Skipping malformed JSON line in rubric.jsonl",
                        checkpoint_dir=str(checkpoint_dir),
                        line_num=line_num,
                        error=str(e),
                    )
    except OSError as e:
        logger.error(
            "Failed to read rubric file",
            checkpoint_dir=str(checkpoint_dir),
            rubric_file=str(rubric_file),
            error=str(e),
        )
        raise MetricsError(
            f"Failed to read rubric file '{rubric_file}': {e}",
            context={"checkpoint_dir": str(checkpoint_dir)},
        ) from e

    # Count carried-over grades
    carried_over_count = sum(1 for g in grades if "carried_over" in g)

    # Count by type
    verbosity_count = sum(1 for g in grades if g.get("type") == "verbosity")
    erosion_count = sum(1 for g in grades if g.get("type") == "erosion")

    return {
        "rubric_total_flags": len(grades),
        "rubric_carried_over": carried_over_count,
        # Dot-notation alias for dashboard compatibility
        "rubric.carried_over": carried_over_count,
        "rubric_verbosity_flags": verbosity_count,
        "rubric_erosion_flags": erosion_count,
    }
