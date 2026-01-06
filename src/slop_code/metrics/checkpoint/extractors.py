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


def _load_json_file(file_path: Path, checkpoint_dir: Path, file_type: str) -> dict:
    """Load and parse a JSON file with standardized error handling.

    Args:
        file_path: Path to the JSON file to load.
        checkpoint_dir: Parent checkpoint directory for error context.
        file_type: Description of file type for error messages.

    Returns:
        Parsed JSON data as a dictionary.

    Raises:
        MetricsError: If file cannot be parsed or read.
    """
    try:
        with file_path.open("r") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        logger.error(
            f"Failed to parse {file_type} JSON",
            checkpoint_dir=str(checkpoint_dir),
            file_path=str(file_path),
            error=str(e),
        )
        raise MetricsError(
            f"Failed to parse {file_type} file '{file_path}': {e}",
            context={"checkpoint_dir": str(checkpoint_dir)},
        ) from e


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
    if diff is not None:
        file_diffs = diff["file_diffs"]
        for fm in file_metrics_iter:
            if (file_path := fm["file_path"]) in file_diffs:
                file_diff = file_diffs[file_path]
                lines_added += file_diff["lines_added"]
                lines_removed += file_diff["lines_removed"]
    else:
        # Consume iterator even if diff is None
        list(file_metrics_iter)

    # Extract function metrics from symbols
    func_lines = []
    func_comparisons = []
    func_try_counts = []

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


def _extract_ast_grep_categories(ast_grep: dict) -> dict[str, int]:
    """Extract AST-grep violation counts by category.

    Args:
        ast_grep: AST-grep metrics dictionary.

    Returns:
        Dictionary of category violation counts with sg_ prefix.
    """
    categories = [
        "verbosity",
        "naming",
        "performance",
        "types",
        "safety",
        "style",
        "complexity",
    ]
    category_counts = ast_grep.get("category_counts", {})
    return {f"sg_{cat}_violations": category_counts.get(cat, 0) for cat in categories}


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
    # Extract nested structures
    file_count = snapshot["file_count"]
    lines = snapshot["lines"]
    lint = snapshot["lint"]
    symbols = snapshot["symbols"]
    functions = snapshot["functions"]
    waste = snapshot["waste"]
    redundancy = snapshot["redundancy"]
    ast_grep = snapshot["ast_grep"]
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
        # Waste
        "single_use_functions": waste["single_use_functions"],
        "trivial_wrappers": waste["trivial_wrappers"],
        "single_method_classes": waste["single_method_classes"],
        # Redundancy
        "clone_instances": redundancy["clone_instances"],
        "clone_lines": redundancy["clone_lines"],
        # Function distribution stats
        "nesting_mean": functions["nesting_mean"],
        "nesting_concentration": functions["nesting_concentration"],
        "comparisons_mean": functions["comparisons_mean"],
        "comparisons_concentration": functions["comparisons_concentration"],
        "branches_mean": functions["branches_mean"],
        "branches_concentration": functions["branches_concentration"],
        "control_mean": functions["control_mean"],
        "control_concentration": functions["control_concentration"],
        # AST-grep
        "ast_grep_violations": ast_grep["violations"],
        # Source file tracking
        "source_file_count": snapshot.get("source_file_count", file_count),
    }

    # Add AST-grep category counts
    result.update(_extract_ast_grep_categories(ast_grep))

    # Per-LOC normalized metrics
    if total_loc > 0:
        result["ast_grep_per_loc"] = ast_grep["violations"] / total_loc
        result["lint_per_loc"] = lint["errors"] / total_loc

    # Graph metrics (optional, may be None for non-Python)
    if graph := snapshot.get("graph"):
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

    metrics = _load_json_file(eval_file, checkpoint_dir, "evaluation")

    total_counts = metrics["total_counts"]
    pass_counts = metrics["pass_counts"]
    total_passed = sum(pass_counts.values())
    total_total = sum(total_counts.values())
    checkpoint_passed = total_passed - pass_counts.get("Regression", 0)
    checkpoint_total = total_total - total_counts.get("Regression", 0)

    if "Core" not in total_counts:
        print(checkpoint_dir)

    return {
        "pass_rate": total_passed / total_total,
        "core_pass_rate": pass_counts.get("Core", 0) / total_counts["Core"],
        "checkpoint_pass_rate": checkpoint_passed / checkpoint_total,
        "duration": metrics["duration"],
        # Flattened tests
        "total_tests": total_total,
        "passed_tests": total_passed,
        "core_total": total_counts["Core"],
        "core_passed": pass_counts.get("Core", 0),
        "functionality_total": total_counts.get("Functionality", 0),
        "functionality_passed": pass_counts.get("Functionality", 0),
        "error_total": total_counts.get("Error", 0),
        "error_passed": pass_counts.get("Error", 0),
        "regression_total": total_counts.get("Regression", 0),
        "regression_passed": pass_counts.get("Regression", 0),
    }


def get_inference_metrics(
    checkpoint_dir: Path, inference_file_name: str = INFERENCE_RESULT_FILENAME
) -> dict:
    """Extract inference metrics from inference_result.json."""
    inference_file = checkpoint_dir / inference_file_name
    if not inference_file.exists():
        return {}

    metrics = _load_json_file(inference_file, checkpoint_dir, "inference")

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


def _load_jsonl_file(file_path: Path, checkpoint_dir: Path) -> list[dict]:
    """Load and parse a JSONL file with error handling.

    Args:
        file_path: Path to the JSONL file to load.
        checkpoint_dir: Parent checkpoint directory for error context.

    Returns:
        List of parsed JSON objects from the file.

    Raises:
        MetricsError: If file cannot be read.
    """
    records = []
    try:
        with file_path.open("r") as f:
            for line_num, line in enumerate(f, 1):
                if line := line.strip():
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError as e:
                        logger.warning(
                            "Skipping malformed JSON line in JSONL file",
                            checkpoint_dir=str(checkpoint_dir),
                            file_path=str(file_path),
                            line_num=line_num,
                            error=str(e),
                        )
    except OSError as e:
        logger.error(
            "Failed to read JSONL file",
            checkpoint_dir=str(checkpoint_dir),
            file_path=str(file_path),
            error=str(e),
        )
        raise MetricsError(
            f"Failed to read JSONL file '{file_path}': {e}",
            context={"checkpoint_dir": str(checkpoint_dir)},
        ) from e
    return records


def get_rubric_metrics(
    checkpoint_dir: Path, rubric_file_name: str = "rubric.jsonl"
) -> dict:
    """Extract rubric metrics with flattened criteria counts.

    Returns a flat dict with keys:
    - rubric_total_flags: Total number of rubric violations
    - rubric_carried_over: Number of grades carried over from previous checkpoint
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

    grades = _load_jsonl_file(rubric_file, checkpoint_dir)

    # Count metrics using comprehensions
    carried_over_count = sum(1 for g in grades if "carried_over" in g)
    verbosity_count = sum(1 for g in grades if g.get("type") == "verbosity")
    erosion_count = sum(1 for g in grades if g.get("type") == "erosion")

    return {
        "rubric_total_flags": len(grades),
        "rubric_carried_over": carried_over_count,
        "rubric_verbosity_flags": verbosity_count,
        "rubric_erosion_flags": erosion_count,
    }
