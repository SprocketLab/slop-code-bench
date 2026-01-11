"""Driver module for orchestrating code quality and rubric metrics collection.

This module provides high-level functions for measuring code quality metrics
across a codebase snapshot, including line counts, linting, complexity analysis,
and file-level metrics aggregation.
"""

from __future__ import annotations

import fnmatch
import json
from collections import Counter
from collections.abc import Callable
from collections.abc import Generator
from pathlib import Path

from slop_code.common import RUBRIC_FILENAME
from slop_code.logging import get_logger
from slop_code.metrics.languages import get_language_by_extension
from slop_code.metrics.languages.python import extract_imports
from slop_code.metrics.models import AstGrepAggregates
from slop_code.metrics.models import ClassStats
from slop_code.metrics.models import ComplexityAggregates
from slop_code.metrics.models import FileMetrics
from slop_code.metrics.models import FunctionStats
from slop_code.metrics.models import GraphMetrics
from slop_code.metrics.models import LineCountMetrics
from slop_code.metrics.models import LintMetrics
from slop_code.metrics.models import MetricsThresholds
from slop_code.metrics.models import RedundancyAggregates
from slop_code.metrics.models import SnapshotMetrics
from slop_code.metrics.models import SymbolAggregates
from slop_code.metrics.models import WasteAggregates
from slop_code.metrics.quality_io import save_quality_metrics

logger = get_logger(__name__)


def _calculate_file_metrics(
    file_path: Path, depth: int, *, is_entry_language: bool = False
) -> FileMetrics | None:
    """Calculate quality metrics for a single Python file.

    Args:
        file_path: Path to the Python file.

    Returns:
        FileMetrics object, or None if file has syntax errors or cannot be read.
    """

    language = get_language_by_extension(file_path.suffix)
    if language is None:
        logger.debug(
            "Unsupported file extension",
            file_path=str(file_path),
            extension=file_path.suffix,
        )
        return None
    line_metrics = language.line(file_path)
    lint_metrics = language.lint(file_path)
    symbols = language.symbol(file_path)
    mi = language.mi(file_path)
    imports = extract_imports(file_path) if file_path.suffix == ".py" else []
    import_count = len(imports)
    global_count = sum(1 for symbol in symbols if symbol.type == "variable")
    redundancy = language.redundancy(file_path) if language.redundancy else None
    waste = language.waste(file_path, symbols) if language.waste else None
    ast_grep = language.ast_grep(file_path) if language.ast_grep else None
    return FileMetrics(
        symbols=symbols,
        lines=line_metrics,
        lint=lint_metrics,
        mi=mi,
        depth=depth,
        is_entry_language=is_entry_language,
        import_count=import_count,
        global_count=global_count,
        redundancy=redundancy,
        waste=waste,
        ast_grep_violations=ast_grep.violations if ast_grep else [],
        ast_grep_rules_checked=ast_grep.rules_checked if ast_grep else 0,
    )


def measure_files(
    dir_path: Path,
    exclude_patterns: set[str],
    entry_extensions: set[str] | None = None,
) -> Generator[tuple[Path, FileMetrics], None, None]:
    for file_path in dir_path.rglob("*"):
        if file_path.is_dir():
            continue
        rel_parts = file_path.relative_to(dir_path).parts
        matched = [
            pattern
            for pattern in exclude_patterns
            if any(fnmatch.fnmatch(part, pattern) for part in rel_parts)
        ]
        if matched:
            logger.debug(
                "Skipping file",
                file_path=str(file_path),
                matched=matched,
            )
            continue
        depth = len(file_path.relative_to(dir_path).parts)
        is_entry_language = (
            entry_extensions is not None
            and file_path.suffix in entry_extensions
        )
        try:
            result = _calculate_file_metrics(
                file_path, depth, is_entry_language=is_entry_language
            )
        except (UnicodeDecodeError, SyntaxError):
            logger.debug(
                "Skipping file",
                file_path=str(file_path),
                error="UnicodeDecodeError",
            )
            continue
        if result is not None:
            yield file_path, result


class _AggregateResult:
    """Internal container for compute_aggregates results."""

    def __init__(
        self,
        file_count: int,
        source_file_count: int,
        symbols: SymbolAggregates,
        functions: FunctionStats,
        classes: ClassStats,
        complexity: ComplexityAggregates,
        waste: WasteAggregates,
        redundancy: RedundancyAggregates,
        ast_grep: AstGrepAggregates,
    ):
        self.file_count = file_count
        self.source_file_count = source_file_count
        self.symbols = symbols
        self.functions = functions
        self.classes = classes
        self.complexity = complexity
        self.waste = waste
        self.redundancy = redundancy
        self.ast_grep = ast_grep


HIGH_CC_THRESHOLD = 10
EXTREME_CC_THRESHOLD = 30


def _normalized_complexity(cc_values: list[int], max_cc: int = 50) -> float:
    """Compute normalized complexity score (0 = ideal, 1 = worst case)."""
    if not cc_values:
        return 0.0

    total = sum(cc_values)
    n = len(cc_values)

    # Actual sum of squares
    sum_sq = sum(cc**2 for cc in cc_values)

    # Best case: uniform distribution
    best_sum_sq = n * (total / n) ** 2 if n > 0 else 0

    # Worst case: all in one function, capped at max_cc
    worst_sum_sq = max(total, max_cc) ** 2

    if worst_sum_sq <= best_sum_sq:
        return 0.0
    return (sum_sq - best_sum_sq) / (worst_sum_sq - best_sum_sq)


def _concentration_score(values: list[int]) -> float:
    """Compute Gini coefficient for value distribution.

    Measures inequality in distribution:
    - 0 = perfectly uniform (all functions have equal value)
    - 1 = maximum concentration (all value in one function)

    Args:
        values: List of metric values (e.g., complexity, nesting depth).

    Returns:
        Gini coefficient in [0, 1].
    """
    non_zero = [v for v in values if v > 0]

    if len(non_zero) <= 1:
        return 0.0

    sorted_vals = sorted(non_zero)
    n = len(sorted_vals)
    total = sum(sorted_vals)

    if total < 1e-9:
        return 0.0

    # Gini formula: (2 * sum(i * val[i]) - (n+1) * total) / (n * total)
    weighted_sum = sum((i + 1) * val for i, val in enumerate(sorted_vals))
    return (2 * weighted_sum - (n + 1) * total) / (n * total)


def _compute_function_stats(
    cc_values: list[int],
    depth_values: list[int],
    lines_values: list[int],
    control_blocks_values: list[int],
    branches_values: list[int],
    comparisons_values: list[int],
) -> FunctionStats:
    """Compute pre-aggregated stats for functions/methods."""
    import statistics

    count = len(cc_values)
    if count == 0:
        return FunctionStats()

    # CC stats
    cc_sum = sum(cc_values)
    cc_max = max(cc_values)
    cc_mean = statistics.mean(cc_values)
    cc_std = statistics.stdev(cc_values) if count > 1 else 0.0

    # Threshold counts
    high_cc = [c for c in cc_values if c > HIGH_CC_THRESHOLD]
    extreme_cc = [c for c in cc_values if c > EXTREME_CC_THRESHOLD]
    cc_high_count = len(high_cc)
    cc_extreme_count = len(extreme_cc)
    high_cc_mean = statistics.mean(high_cc) if high_cc else 0.0
    extreme_cc_mean = statistics.mean(extreme_cc) if extreme_cc else 0.0

    # Derived metrics
    cc_normalized = _normalized_complexity(cc_values)
    cc_concentration = _concentration_score(cc_values)

    # Depth stats
    depth_max = max(depth_values) if depth_values else 0

    # Lines stats
    lines_sum = sum(lines_values)
    lines_mean = statistics.mean(lines_values) if lines_values else 0.0

    # Control blocks
    control_blocks_sum = sum(control_blocks_values)

    # Helper for distribution stats
    def _dist_stats(
        values: list[int], threshold: int
    ) -> tuple[float, float, int]:
        if not values:
            return 0.0, 0.0, 0
        mean = statistics.mean(values)
        conc = _concentration_score(values)
        high = sum(1 for v in values if v > threshold)
        return mean, conc, high

    # Compute distribution stats for each family
    nesting_mean, nesting_conc, nesting_high = _dist_stats(depth_values, 3)
    comp_mean, comp_conc, comp_high = _dist_stats(comparisons_values, 5)
    branch_mean, branch_conc, branch_high = _dist_stats(branches_values, 5)
    ctrl_mean, ctrl_conc, ctrl_high = _dist_stats(control_blocks_values, 5)

    return FunctionStats(
        count=count,
        cc_sum=cc_sum,
        cc_max=cc_max,
        cc_mean=cc_mean,
        cc_std=cc_std,
        cc_high_count=cc_high_count,
        cc_extreme_count=cc_extreme_count,
        high_cc_mean=high_cc_mean,
        extreme_cc_mean=extreme_cc_mean,
        cc_normalized=cc_normalized,
        cc_concentration=cc_concentration,
        depth_max=depth_max,
        lines_sum=lines_sum,
        lines_mean=lines_mean,
        control_blocks_sum=control_blocks_sum,
        # Distribution stats
        nesting_mean=nesting_mean,
        nesting_concentration=nesting_conc,
        nesting_high_count=nesting_high,
        comparisons_mean=comp_mean,
        comparisons_concentration=comp_conc,
        comparisons_high_count=comp_high,
        branches_mean=branch_mean,
        branches_concentration=branch_conc,
        branches_high_count=branch_high,
        control_mean=ctrl_mean,
        control_concentration=ctrl_conc,
        control_high_count=ctrl_high,
    )


def _compute_class_stats(
    method_counts: list[int],
    attribute_counts: list[int],
) -> ClassStats:
    """Compute pre-aggregated stats for classes."""
    import statistics

    count = len(method_counts)
    if count == 0:
        return ClassStats()

    method_counts_sum = sum(method_counts)
    method_counts_mean = (
        statistics.mean(method_counts) if method_counts else 0.0
    )
    attribute_counts_sum = sum(attribute_counts)
    attribute_counts_mean = (
        statistics.mean(attribute_counts) if attribute_counts else 0.0
    )

    return ClassStats(
        count=count,
        method_counts_sum=method_counts_sum,
        method_counts_mean=method_counts_mean,
        attribute_counts_sum=attribute_counts_sum,
        attribute_counts_mean=attribute_counts_mean,
    )


def compute_aggregates(
    file_metrics: dict[str, FileMetrics],
    source_files: set[str] | None,
    thresholds: MetricsThresholds | None = None,
) -> _AggregateResult:
    """Compute aggregate metrics from file metrics in a single pass.

    Args:
        file_metrics: Dictionary mapping file paths to their metrics.
        source_files: Set of source file paths traced from entrypoint, or None.
        thresholds: Configurable thresholds for metrics (uses defaults if None).

    Returns:
        _AggregateResult with sectioned aggregate models.
    """
    if thresholds is None:
        thresholds = MetricsThresholds()

    file_count = len(file_metrics)
    source_file_count = len(source_files) if source_files else file_count

    # Initialize aggregates with zero values
    symbols = SymbolAggregates(
        total=0,
        functions=0,
        methods=0,
        classes=0,
        variables=0,
        type_aliases=0,
        statements=0,
        expressions_top_level=0,
        expressions=0,
        imports=0,
        max_imports=0,
        globals=0,
    )
    complexity = ComplexityAggregates(
        cc_ratings={"A": 0, "B": 0, "C": 0, "D": 0, "E": 0, "F": 0},
        mi_ratings={"A": 0, "B": 0, "C": 0},
        cc_sum=0,
        cc_max=0,
        num_complex=0,
        mi_sum=0.0,
        mi_min=float("inf"),
    )
    waste = WasteAggregates(
        single_use_functions=0,
        trivial_wrappers=0,
        single_method_classes=0,
    )
    redundancy = RedundancyAggregates(
        clone_instances=0,
        clone_lines=0,
        clone_ratio_sum=0.0,
        files_with_clones=0,
    )
    ast_grep = AstGrepAggregates(
        violations=0,
        rules_checked=0,
        counts={},
    )

    # Collect raw values for function/class stats computation
    func_cc: list[int] = []
    func_depth: list[int] = []
    func_lines: list[int] = []
    func_control_blocks: list[int] = []
    func_branches: list[int] = []
    func_comparisons: list[int] = []
    class_method_counts: list[int] = []
    class_attribute_counts: list[int] = []

    # Single pass through all files
    for fm in file_metrics.values():
        symbols.update(fm)
        complexity.update(fm, thresholds)
        waste.update(fm)
        redundancy.update(fm)
        ast_grep.update(fm)

        # Collect function/method metrics
        for sym in fm.symbols:
            if sym.type in ("function", "method"):
                func_cc.append(sym.complexity)
                func_depth.append(sym.max_nesting_depth)
                func_lines.append(sym.lines)
                func_control_blocks.append(sym.control_blocks)
                func_branches.append(sym.branches)
                func_comparisons.append(sym.comparisons)
            elif sym.type == "class":
                if sym.method_count is not None:
                    class_method_counts.append(sym.method_count)
                if sym.attribute_count is not None:
                    class_attribute_counts.append(sym.attribute_count)

    # Compute stats from collected values
    functions = _compute_function_stats(
        func_cc,
        func_depth,
        func_lines,
        func_control_blocks,
        func_branches,
        func_comparisons,
    )
    classes = _compute_class_stats(class_method_counts, class_attribute_counts)

    # Handle edge case of no files
    if complexity.mi_min == float("inf"):
        complexity.mi_min = 0.0

    return _AggregateResult(
        file_count=file_count,
        source_file_count=source_file_count,
        symbols=symbols,
        functions=functions,
        classes=classes,
        complexity=complexity,
        waste=waste,
        redundancy=redundancy,
        ast_grep=ast_grep,
    )


def measure_snapshot_quality(
    entry_file: str | Path, snapshot_dir: Path
) -> tuple[SnapshotMetrics, list[FileMetrics]]:
    """Measure code quality metrics for a codebase snapshot.

    Overall metrics are determined by the provided entry file while per-file
    metrics are still collected for every supported source file.

    Returns:
        Tuple of (SnapshotMetrics with aggregates, list of FileMetrics for JSONL).
    """
    # Import here to avoid circular import
    from slop_code.metrics.languages.python import trace_source_files

    files_metrics: dict[str, FileMetrics] = {}

    exclude_patterns = {
        "__pycache__",
        "*.pyc",
        "venv",
        ".venv",
        "virtualenv",
        ".virtualenv",
        ".git",
        "node_modules",
        ".tox",
        ".nox",
    }

    # Track totals in case the entry file is missing
    total_lines = 0
    total_loc = 0
    total_comments = 0
    total_multi_comment = 0
    total_single_comment = 0

    lint_count = Counter()
    lint_fixable = lint_errors = 0

    entry_path = Path(entry_file)
    # Normalize entry path relative to the snapshot root for comparison
    target_entry_path = (
        entry_path if entry_path.is_absolute() else (snapshot_dir / entry_path)
    ).resolve()

    entry_language = (
        get_language_by_extension(target_entry_path.suffix)
        if target_entry_path.suffix
        else None
    )
    entry_extensions = entry_language.extensions if entry_language else None

    for file_path, file_metric in measure_files(
        snapshot_dir, exclude_patterns, entry_extensions=entry_extensions
    ):
        relative_path = file_path.relative_to(snapshot_dir)
        path_str = relative_path.as_posix()

        # Set file_path on the metric for JSONL output
        file_metric.file_path = path_str
        files_metrics[path_str] = file_metric

        total_lines += file_metric.lines.total_lines
        total_loc += file_metric.lines.loc
        total_comments += file_metric.lines.comments
        total_multi_comment += file_metric.lines.multi_comment
        total_single_comment += file_metric.lines.single_comment
        lint_count += file_metric.lint.counts
        lint_fixable += file_metric.lint.fixable
        lint_errors += file_metric.lint.errors

        if file_path.resolve() == target_entry_path or (
            not entry_path.is_absolute()
            and relative_path.with_suffix("").as_posix()
            == entry_path.as_posix()
        ):
            # Update target_entry_path to the actual file path found
            target_entry_path = file_path.resolve()

    snapshot_line_metrics = LineCountMetrics(
        total_lines=total_lines,
        loc=total_loc,
        comments=total_comments,
        multi_comment=total_multi_comment,
        single_comment=total_single_comment,
    )

    snapshot_lint_metrics = LintMetrics(
        errors=lint_errors, fixable=lint_fixable, counts=lint_count
    )

    # Trace source files from entrypoint for Python files
    traced_source_files: set[str] | None = None
    if target_entry_path.suffix == ".py" and target_entry_path.exists():
        try:
            traced_paths = trace_source_files(target_entry_path, snapshot_dir)
            traced_source_files = {p.as_posix() for p in traced_paths}
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "Failed to trace source files",
                entry_file=str(entry_file),
                error=str(e),
            )

    # Build dependency graph and compute graph metrics for Python files
    from slop_code.metrics.languages.python.graph import build_dependency_graph
    from slop_code.metrics.languages.python.graph import compute_graph_metrics

    if target_entry_path.suffix != ".py" or not target_entry_path.exists():
        # Log and use empty graph metrics for non-Python or missing entrypoints
        logger.warning(
            "Skipping graph construction",
            entry_file=str(target_entry_path),
            reason="not a Python file"
            if target_entry_path.suffix != ".py"
            else "file not found",
        )
        graph_metrics = GraphMetrics(
            node_count=0,
            edge_count=0,
            cyclic_dependency_mass=0.0,
            propagation_cost=0.0,
            dependency_entropy=0.0,
        )
    else:
        dependency_graph = build_dependency_graph(
            snapshot_dir, target_entry_path
        )
        graph_metrics = compute_graph_metrics(dependency_graph)

    # Compute aggregates using the dedicated function
    agg = compute_aggregates(files_metrics, traced_source_files)

    # Build file list for JSONL output
    file_metrics_list = list(files_metrics.values())

    snapshot = SnapshotMetrics(
        file_count=agg.file_count,
        source_file_count=agg.source_file_count,
        lines=snapshot_line_metrics,
        lint=snapshot_lint_metrics,
        symbols=agg.symbols,
        functions=agg.functions,
        classes=agg.classes,
        complexity=agg.complexity,
        waste=agg.waste,
        redundancy=agg.redundancy,
        ast_grep=agg.ast_grep,
        graph=graph_metrics,
        source_files=traced_source_files,
    )

    return snapshot, file_metrics_list


# =============================================================================
# Rubric Utilities
# =============================================================================


def load_rubric(rubric_path: Path) -> list[dict]:
    """Load grades from a rubric.jsonl file.

    Args:
        rubric_path: Path to the rubric.jsonl file.

    Returns:
        List of grade dictionaries. Empty list if file doesn't exist.
    """
    if not rubric_path.exists():
        return []

    grades = []
    for line in rubric_path.read_text().splitlines():
        if line.strip():
            grades.append(json.loads(line))
    return grades


def save_rubric_results(
    checkpoint_dir: Path, grades: list[dict], raw: dict
) -> None:
    """Save rubric results to checkpoint directory."""
    rubric_path = checkpoint_dir / RUBRIC_FILENAME
    raw_path = checkpoint_dir / "raw_rubric.json"

    with rubric_path.open("w") as f:
        for g in grades:
            f.write(json.dumps(g) + "\n")
    with raw_path.open("w") as f:
        json.dump(raw, f, indent=2)

    logger.info(
        "Saved rubric results",
        grade_count=len(grades),
        rubric_file=rubric_path.name,
        checkpoint_dir=checkpoint_dir.name,
    )


def build_category_map(rubric_items: list[dict]) -> dict[str, str]:
    """Build mapping from criteria name to category.

    Args:
        rubric_items: List of rubric item dictionaries with 'name' and
            'category' fields.

    Returns:
        Dict mapping criteria name to category string.
    """
    return {item["name"]: item.get("category", "") for item in rubric_items}


def build_type_map(rubric_items: list[dict]) -> dict[str, str]:
    """Build mapping from criteria name to type.

    Args:
        rubric_items: List of rubric item dictionaries with 'name' and
            'type' fields.

    Returns:
        Dict mapping criteria name to type string (verbosity or erosion).
    """
    return {item["name"]: item.get("type", "") for item in rubric_items}


def annotate_grades_with_category(
    grades: list[dict],
    category_map: dict[str, str],
    type_map: dict[str, str] | None = None,
) -> list[dict]:
    """Add category and type fields to each grade based on criteria name.

    Args:
        grades: List of grade dictionaries with 'criteria' field.
        category_map: Dict mapping criteria name to category.
        type_map: Optional dict mapping criteria name to type
            (verbosity or erosion).

    Returns:
        Same list of grades with 'category' and 'type' fields added
        where applicable.
    """
    for grade in grades:
        criteria = grade.get("criteria", "")
        if "category" not in grade and criteria in category_map:
            grade["category"] = category_map[criteria]
        if type_map and "type" not in grade and criteria in type_map:
            grade["type"] = type_map[criteria]
    return grades


def count_file_lines(file_path: Path) -> int:
    """Count lines in a file."""
    try:
        return len(file_path.read_text().splitlines())
    except (OSError, UnicodeDecodeError):
        return 0


# File batching defaults
DEFAULT_MAX_BATCH_LINES = 1000
DEFAULT_MAX_BATCH_FILES = 5
DEFAULT_LARGE_FILE_THRESHOLD = 500


def batch_files_by_size(
    files: list[Path],
    max_batch_lines: int = DEFAULT_MAX_BATCH_LINES,
    max_batch_files: int = DEFAULT_MAX_BATCH_FILES,
    large_file_threshold: int = DEFAULT_LARGE_FILE_THRESHOLD,
) -> list[list[Path]]:
    """Batch files by combined line count for multi-file grading.

    Args:
        files: List of file paths to batch.
        max_batch_lines: Maximum combined lines per batch.
        max_batch_files: Maximum files per batch.
        large_file_threshold: Files above this line count stay separate.

    Returns:
        List of file batches (each batch is a list of Paths).
    """
    if not files:
        return []

    # Calculate line counts
    file_lines = [(f, count_file_lines(f)) for f in files]

    # Separate large files (they get their own batch)
    large_files = [(f, n) for f, n in file_lines if n > large_file_threshold]
    small_files = [(f, n) for f, n in file_lines if n <= large_file_threshold]

    batches: list[list[Path]] = []

    # Large files get individual batches
    for f, _ in large_files:
        batches.append([f])

    # Batch small files together
    current_batch: list[Path] = []
    current_lines = 0

    for f, n in small_files:
        if (
            current_lines + n > max_batch_lines
            or len(current_batch) >= max_batch_files
        ):
            if current_batch:
                batches.append(current_batch)
            current_batch = [f]
            current_lines = n
        else:
            current_batch.append(f)
            current_lines += n

    if current_batch:
        batches.append(current_batch)

    return batches


def aggregate_usage(raw_data: dict[str, list]) -> dict[str, int]:
    """Aggregate token usage from raw API responses.

    Args:
        raw_data: Dict mapping file paths to lists of raw API responses.

    Returns:
        Dict with prompt_tokens, completion_tokens, total_tokens,
        cache_read_tokens, cache_write_tokens sums.
    """
    totals = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "cost": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
    }
    for responses in raw_data.values():
        for resp in responses:
            usage = resp.get("usage", {})
            totals["prompt_tokens"] += usage.get("prompt_tokens", 0)
            totals["completion_tokens"] += usage.get("completion_tokens", 0)
            totals["total_tokens"] += usage.get("total_tokens", 0)
            totals["cost"] += usage.get("cost", 0)
            totals["cache_read_tokens"] += usage.get(
                "cache_read_input_tokens", 0
            )
            totals["cache_write_tokens"] += usage.get(
                "cache_creation_input_tokens", 0
            )
    return totals


# =============================================================================
# Problem Processing
# =============================================================================

# Constant for snapshot directory name - imported from agent_runner at runtime
# to avoid circular imports
SNAPSHOT_DIR_NAME = "snapshot"


def process_problem_quality(
    problem_dir: Path,
    entry_file: str,
    discover_checkpoints: Callable[[Path], list[Path]],
) -> tuple[dict[str, SnapshotMetrics], int]:
    """Process a single problem, calculating and saving quality metrics.

    Args:
        problem_dir: Path to the problem directory.
        entry_file: The entry file name to use for language detection.
        discover_checkpoints: Function to discover checkpoint directories.

    Returns:
        Tuple of (dictionary mapping checkpoint names to metrics, files saved
        count).
    """
    checkpoints = discover_checkpoints(problem_dir)
    results: dict[str, SnapshotMetrics] = {}
    files_saved = 0

    for checkpoint_dir in checkpoints:
        checkpoint_name = checkpoint_dir.name
        snapshot_dir = checkpoint_dir / SNAPSHOT_DIR_NAME

        if not snapshot_dir.exists():
            logger.warning(
                "Snapshot directory not found, skipping checkpoint",
                checkpoint=checkpoint_name,
                problem=problem_dir.name,
            )
            continue

        quality_result, file_metrics_list = measure_snapshot_quality(
            entry_file,
            snapshot_dir,
        )
        results[checkpoint_name] = quality_result

        # Save quality metrics to flat files
        files_saved += save_quality_metrics(
            checkpoint_dir, quality_result, file_metrics_list
        )

        logger.debug(
            "Calculated and saved quality metrics",
            checkpoint=checkpoint_name,
            problem=problem_dir.name,
            files=quality_result.file_count,
        )

    return results, files_saved
