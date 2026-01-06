"""Data models for code quality and rubric metrics.

This module contains all Pydantic models for representing code quality metrics
including line counts, lint results, symbol complexity, and file-level metrics.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Literal

from pydantic import BaseModel
from pydantic import Field
from pydantic import computed_field

from slop_code.logging import get_logger

logger = get_logger(__name__)


class MetricsThresholds(BaseModel):
    """Configurable thresholds for distribution buckets in quality metrics.

    CC (cyclomatic complexity) thresholds follow the radon standard and are not
    configurable here - they use the standard A-F rating scale.

    Attributes:
        shallow_nesting_max: Max depth considered "shallow" nesting (inclusive).
        deep_nesting_min: Min depth considered "deep" nesting (inclusive).
        short_symbol_max: Max lines for a "short" symbol (inclusive).
        medium_symbol_max: Max lines for a "medium" symbol (inclusive).
        long_symbol_max: Max lines for a "long" symbol (inclusive).
        few_expr_max: Max expressions for "few expressions" bucket (inclusive).
        many_expr_min: Min expressions for "many expressions" bucket (inclusive).
        many_control_blocks_min: Min control blocks for "many" bucket (inclusive).
        complex_cc_threshold: CC value above which a symbol is "complex".
    """

    shallow_nesting_max: int = 1
    deep_nesting_min: int = 4
    short_symbol_max: int = 10
    medium_symbol_max: int = 30
    long_symbol_max: int = 75
    few_expr_max: int = 5
    many_expr_min: int = 20
    many_control_blocks_min: int = 5
    complex_cc_threshold: int = 10


class LineCountMetrics(BaseModel):
    """Metrics for line count statistics.

    Attributes:
        total_lines (int): total lines of code.
        loc (int): Number of SOURCE code.
        comments: Number of lines of comments.
        multi_comment: Number of lines of multiline comments.
        single_comment: Number of lines of single line comments.

    """

    total_lines: int
    loc: int
    comments: int
    multi_comment: int
    single_comment: int


class LintMetrics(BaseModel):
    """Metrics for a lint report.

    Attributes:
        errors: Number of flagged items by the linter.
        fixable: Number of fixable errors.
        counts: Counts of flagged items by the code.
    """

    errors: int
    fixable: int
    counts: dict[str, int]


def _compute_rating(complexity: int) -> Literal["A", "B", "C", "D", "E", "F"]:
    """Compute complexity rating from cyclomatic complexity value.

    Ratings per radon:
    - A: 1-5
    - B: 6-10
    - C: 11-20
    - D: 21-30
    - E: 31-40
    - F: 41+
    """
    if complexity <= 5:
        return "A"
    if complexity <= 10:
        return "B"
    if complexity <= 20:
        return "C"
    if complexity <= 30:
        return "D"
    if complexity <= 40:
        return "E"
    return "F"


class SymbolMetrics(BaseModel):
    """Metrics for a symbol extracted from source code.

    Attributes:
        name: The name of the symbol.
        type: The type of symbol (function, class, method, variable, type_alias).
        start: Starting line number (1-indexed).
        start_col: Starting column number (0-indexed).
        end: Ending line number (1-indexed).
        end_col: Ending column number (0-indexed).
        complexity: Cyclomatic complexity score.
        branches: Number of branch points (decision points).
        statements: Number of statements in the symbol.
        rating: Complexity rating (A-F) computed from complexity.
        imports: Number of imports in the symbol.
        globals: Number of globals in the symbol.
        statements_total: Total number of statements in the symbol.
        expressions_total: Total number of expressions in the symbol.
        control_blocks: Number of control blocks in the symbol.
        control_flow: Number of if/elif/match/case occurrences in the symbol.
        exception_scaffold: Number of try/except/finally occurrences.
        comparisons: Number of comparison operators.
        max_nesting_depth: Maximum nesting depth of the symbol.
        lines: Number of lines in the symbol.
        method_count: Number of methods in the symbol.
        attribute_count: Number of attributes in the symbol.
        file_path: Path to the file containing this symbol.
        parent_class: Name of parent class if this is a method.
        base_classes: List of base class names for class definitions.
        body_hash: Hash of normalized body (identifiers replaced with placeholders).
        structure_hash: Hash of AST structure only (node types, no content).
        signature: Dict mapping parameter names to type annotations (or None).
        return_type: Return type annotation as string.
        signature_hash: Hash of normalized signature for move detection.
        variables_defined: Number of variable definitions in the symbol.
        variables_used: Number of variable usages in the symbol.
        return_count: Number of return statements.
        raise_count: Number of raise statements.
    """

    name: str
    type: str
    start: int
    start_col: int
    end: int
    end_col: int
    complexity: int
    branches: int
    statements: int
    expressions_top_level: int = 0
    expressions_total: int = 0
    control_blocks: int = 0
    control_flow: int = 0
    exception_scaffold: int = 0
    comparisons: int = 0
    max_nesting_depth: int = 0
    lines: int = 0
    method_count: int | None = None
    attribute_count: int | None = None
    # Location info
    file_path: str = ""
    parent_class: str | None = None
    base_classes: list[str] | None = None
    # Signature info (functions/methods only)
    body_hash: str | None = None
    structure_hash: str | None = None
    signature: dict[str, str | None] | None = None
    return_type: str | None = None
    signature_hash: str | None = None
    # Flow metrics (functions/methods only)
    variables_defined: int = 0
    variables_used: int = 0
    return_count: int = 0
    raise_count: int = 0

    @computed_field
    @property
    def rating(self) -> Literal["A", "B", "C", "D", "E", "F"]:
        """Compute rating from complexity for backwards compatibility."""
        return _compute_rating(self.complexity)


class ImportInfo(BaseModel):
    """Information about a single import statement.

    Attributes:
        module_path: The dotted module path (e.g., "scheduler.parser").
            None for "from . import X" style imports.
        is_relative: Whether this is a relative import.
        relative_level: Number of dots for relative imports (0 for absolute).
        imported_names: Names imported (for "from X import a, b" style).
            Empty for "import X" style.
        line: Line number of the import.
    """

    module_path: str | None
    is_relative: bool
    relative_level: int
    imported_names: list[str]
    line: int


class FileMetrics(BaseModel):
    """Metrics for a file.

    Attributes:
        file_path: Relative path to the file (populated when saving to JSONL).
        symbols: Symbols found in this file.
        lines: The line metrics for this file.
        lint: The lint metrics for this file.
        mi: Maintainability index score of this file
        depth: Depth of the file in the directory tree
        is_entry_language: Whether this file matches the entrypoint language
    """

    file_path: str = ""
    symbols: list[SymbolMetrics]
    lines: LineCountMetrics
    lint: LintMetrics
    mi: float
    depth: int
    is_entry_language: bool = False
    import_count: int = 0
    global_count: int = 0
    redundancy: RedundancyMetrics | None = None
    waste: WasteMetrics | None = None
    ast_grep_violations: list[AstGrepViolation] = []
    ast_grep_rules_checked: int = 0


class CodeClone(BaseModel):
    """A group of duplicate code blocks with identical AST structure."""

    ast_hash: str
    locations: list[tuple[int, int]]
    node_type: str
    line_count: int


class RedundancyMetrics(BaseModel):
    """Per-file redundancy analysis results."""

    clones: list[CodeClone]
    total_clone_instances: int
    clone_lines: int
    clone_ratio: float


class SingleUseFunction(BaseModel):
    """A function that is only called once."""

    name: str
    line: int
    called_from_line: int | None


class TrivialWrapper(BaseModel):
    """A function that just delegates to another function."""

    name: str
    line: int
    wraps: str


class WasteMetrics(BaseModel):
    """Per-file abstraction waste analysis."""

    single_use_functions: list[SingleUseFunction]
    trivial_wrappers: list[TrivialWrapper]
    single_method_classes: list[str]
    single_use_count: int
    trivial_wrapper_count: int
    single_method_class_count: int


class AstGrepViolation(BaseModel):
    """A single AST-grep pattern violation.

    Attributes:
        rule_id: The rule identifier (e.g., "bare-except-pass").
        severity: Severity level (warning, error, info, hint).
        category: Overall category from rule filename (e.g., "verbosity", "safety").
        subcategory: Sub-category from rule metadata.category field.
        weight: Rule weight from metadata (1-4, higher = more important).
        line: Starting line number (1-indexed).
        column: Starting column number (0-indexed).
        end_line: Ending line number (1-indexed).
        end_column: Ending column number (0-indexed).
    """

    rule_id: str
    severity: str
    category: str = ""
    subcategory: str = "unknown"
    weight: int = 1
    line: int
    column: int
    end_line: int
    end_column: int


class AstGrepMetrics(BaseModel):
    """AST-grep pattern detection results.

    Attributes:
        violations: List of individual violations found.
        total_violations: Total number of violations.
        counts: Mapping of rule_id to violation count.
        rules_checked: Number of rules that were applied.
    """

    violations: list[AstGrepViolation]
    total_violations: int
    counts: dict[str, int]
    rules_checked: int


class FunctionStats(BaseModel):
    """Pre-computed statistics for functions and methods across all files.

    All stats are computed during aggregation in driver.py.
    """

    count: int = 0
    # Complexity stats
    cc_sum: int = 0
    cc_max: int = 0
    cc_mean: float = 0.0
    cc_std: float = 0.0
    cc_high_count: int = 0  # count > 10
    cc_extreme_count: int = 0  # count > 30
    high_cc_mean: float = 0.0
    extreme_cc_mean: float = 0.0
    cc_normalized: float = 0.0
    cc_concentration: float = 0.0
    # Depth stats
    depth_max: int = 0
    # Lines stats
    lines_sum: int = 0
    lines_mean: float = 0.0
    # Control blocks
    control_blocks_sum: int = 0

    # Distribution stats (mean, concentration, high_count)
    # Nesting (threshold > 3)
    nesting_mean: float = 0.0
    nesting_concentration: float = 0.0
    nesting_high_count: int = 0

    # Comparisons (threshold > 5)
    comparisons_mean: float = 0.0
    comparisons_concentration: float = 0.0
    comparisons_high_count: int = 0

    # Branches (threshold > 5)
    branches_mean: float = 0.0
    branches_concentration: float = 0.0
    branches_high_count: int = 0

    # Control blocks (threshold > 5)
    control_mean: float = 0.0
    control_concentration: float = 0.0
    control_high_count: int = 0


class ClassStats(BaseModel):
    """Pre-computed statistics for classes across all files.

    All stats are computed during aggregation in driver.py.
    """

    count: int = 0
    method_counts_sum: int = 0
    method_counts_mean: float = 0.0
    attribute_counts_sum: int = 0
    attribute_counts_mean: float = 0.0


class SymbolAggregates(BaseModel):
    """Aggregate counts for symbols across all files."""

    total: int
    functions: int
    methods: int
    classes: int
    variables: int
    type_aliases: int
    statements: int
    expressions_top_level: int
    expressions: int
    imports: int
    max_imports: int
    globals: int

    def update(self, fm: FileMetrics) -> None:
        """Update aggregates from a FileMetrics instance."""
        self.imports += fm.import_count
        self.max_imports = max(self.max_imports, fm.import_count)
        self.globals += fm.global_count

        for sym in fm.symbols:
            self.total += 1
            self.statements += sym.statements
            self.expressions_top_level += sym.expressions_top_level
            self.expressions += sym.expressions_total

            if sym.type == "function":
                self.functions += 1
            elif sym.type == "method":
                self.methods += 1
            elif sym.type == "class":
                self.classes += 1
            elif sym.type == "variable":
                self.variables += 1
            elif sym.type == "type_alias":
                self.type_aliases += 1


class ComplexityAggregates(BaseModel):
    """Aggregate complexity metrics (CC and MI)."""

    cc_ratings: dict[Literal["A", "B", "C", "D", "E", "F"], int]
    mi_ratings: dict[Literal["A", "B", "C"], int]
    cc_sum: int
    cc_max: int
    num_complex: int
    mi_sum: float
    mi_min: float

    def update(
        self, fm: FileMetrics, thresholds: MetricsThresholds | None = None
    ) -> None:
        """Update aggregates from a FileMetrics instance."""
        if thresholds is None:
            thresholds = MetricsThresholds()

        # MI rating and stats
        self.mi_sum += fm.mi
        self.mi_min = min(self.mi_min, fm.mi)
        if fm.mi >= 19:
            self.mi_ratings["A"] += 1
        elif fm.mi > 9:
            self.mi_ratings["B"] += 1
        else:
            self.mi_ratings["C"] += 1

        # CC stats from symbols
        for sym in fm.symbols:
            self.cc_ratings[_compute_rating(sym.complexity)] += 1
            self.cc_sum += sym.complexity
            self.cc_max = max(self.cc_max, sym.complexity)
            if sym.complexity > thresholds.complex_cc_threshold:
                self.num_complex += 1


class WasteAggregates(BaseModel):
    """Aggregate waste detection metrics."""

    single_use_functions: int
    trivial_wrappers: int
    single_method_classes: int

    def update(self, fm: FileMetrics) -> None:
        """Update aggregates from a FileMetrics instance."""
        if fm.waste:
            self.single_use_functions += fm.waste.single_use_count
            self.trivial_wrappers += fm.waste.trivial_wrapper_count
            self.single_method_classes += fm.waste.single_method_class_count


class RedundancyAggregates(BaseModel):
    """Aggregate redundancy/clone detection metrics."""

    clone_instances: int
    clone_lines: int
    clone_ratio_sum: float
    files_with_clones: int

    def update(self, fm: FileMetrics) -> None:
        """Update aggregates from a FileMetrics instance."""
        if fm.redundancy:
            self.clone_instances += fm.redundancy.total_clone_instances
            self.clone_lines += fm.redundancy.clone_lines
            self.clone_ratio_sum += fm.redundancy.clone_ratio
            self.files_with_clones += 1


class AstGrepAggregates(BaseModel):
    """Aggregate AST-grep pattern violation metrics."""

    violations: int
    rules_checked: int
    counts: dict[str, int] = {}
    weighted: int = 0
    category_counts: dict[str, int] = {}
    category_weighted: dict[str, int] = {}

    def update(self, fm: FileMetrics) -> None:
        """Update aggregates from a FileMetrics instance."""
        if fm.ast_grep_violations:
            self.violations += len(fm.ast_grep_violations)
            for v in fm.ast_grep_violations:
                self.counts[v.rule_id] = self.counts.get(v.rule_id, 0) + 1
                self.weighted += v.weight
                self.category_counts[v.category] = (
                    self.category_counts.get(v.category, 0) + 1
                )
                self.category_weighted[v.category] = (
                    self.category_weighted.get(v.category, 0) + v.weight
                )
        self.rules_checked = max(self.rules_checked, fm.ast_grep_rules_checked)


class GraphMetrics(BaseModel):
    """Program dependency graph metrics.

    Metrics computed from the dependency graph built from import statements.
    Nodes represent architectural units (files/modules) and edges represent
    import/reference relationships.

    Attributes:
        node_count: Number of nodes (files/modules) in the graph.
        edge_count: Number of directed edges (import relationships).
        cyclic_dependency_mass: Ratio of edge weight in SCCs to total edge weight.
        propagation_cost: Average reachability (transitive closure metric).
        dependency_entropy: Normalized Shannon entropy of dependency distribution.
    """

    node_count: int
    edge_count: int
    cyclic_dependency_mass: float
    propagation_cost: float
    dependency_entropy: float


class SnapshotMetrics(BaseModel):
    """Metrics for the overall snapshot.

    Individual file metrics are saved separately to files.jsonl.
    This model contains aggregate metrics organized by category.

    Attributes:
        file_count: Total number of files measured.
        source_file_count: Files traced from entrypoint (or file_count if None).
        lines: Aggregated line metrics across all files.
        lint: Aggregated lint metrics across all files.
        symbols: Symbol counts and totals across all files.
        functions: Pre-computed statistics for functions and methods.
        classes: Pre-computed statistics for classes.
        complexity: CC and MI rating distributions and stats.
        waste: Waste detection totals.
        redundancy: Clone detection totals.
        ast_grep: AST-grep pattern violation totals.
        graph: Dependency graph metrics (None if not computed).
        source_files: Relative paths of files traced from the entrypoint.
    """

    file_count: int
    source_file_count: int
    lines: LineCountMetrics
    lint: LintMetrics
    symbols: SymbolAggregates
    functions: FunctionStats
    classes: ClassStats
    complexity: ComplexityAggregates
    waste: WasteAggregates
    redundancy: RedundancyAggregates
    ast_grep: AstGrepAggregates
    graph: GraphMetrics | None = None
    source_files: set[str] | None = None


class SnapshotQualityReport(BaseModel):
    """Summary of quality metrics for a snapshot."""

    files: int
    source_files: int
    overall_lines: LineCountMetrics
    lint_errors: int
    lint_fixable: int
    cc_counts: dict[Literal["A", "B", "C", "D", "E", "F"], int]
    mi: dict[Literal["A", "B", "C"], int]
    ast_grep_violations: int = 0
    ast_grep_rules_checked: int = 0
    graph: GraphMetrics | None = None

    @classmethod
    def from_snapshot_metrics(
        cls, snapshot_metrics: SnapshotMetrics
    ) -> SnapshotQualityReport:
        """Create a report from snapshot metrics."""
        return cls(
            files=snapshot_metrics.file_count,
            source_files=snapshot_metrics.source_file_count,
            overall_lines=snapshot_metrics.lines,
            lint_errors=snapshot_metrics.lint.errors,
            lint_fixable=snapshot_metrics.lint.fixable,
            cc_counts=snapshot_metrics.complexity.cc_ratings,
            mi=snapshot_metrics.complexity.mi_ratings,
            ast_grep_violations=snapshot_metrics.ast_grep.violations,
            ast_grep_rules_checked=snapshot_metrics.ast_grep.rules_checked,
            graph=snapshot_metrics.graph,
        )


class LanguageSpec(BaseModel):
    """Specification for a language.

    Attributes:
        extensions: The extensions of the language.
        line: The function to calculate the line metrics.
        lint: The function to calculate the lint metrics.
        symbol: The function to calculate the symbol metrics.
        mi: The function to calculate the maintainability index.
    """

    extensions: set[str]
    line: Callable[[Path], LineCountMetrics]
    lint: Callable[[Path], LintMetrics]
    symbol: Callable[[Path], list[SymbolMetrics]]
    mi: Callable[[Path], float]
    redundancy: Callable[[Path], RedundancyMetrics] | None = None
    waste: Callable[[Path, list[SymbolMetrics]], WasteMetrics] | None = None
    ast_grep: Callable[[Path], AstGrepMetrics] | None = None


# -----------------------------------------------------------------------------
# Run Summary Models
# -----------------------------------------------------------------------------


class MetricStats(BaseModel):
    """Statistics for a single metric across checkpoints."""

    mean: float | None = None
    stddev: float | None = None
    min: float | None = None
    max: float | None = None
    median: float | None = None
    count: int = 0

    def format_display(self, precision: int = 4, suffix: str = "") -> str:
        """Format as 'mean +/- stddev' for console display.

        Args:
            precision: Number of decimal places.
            suffix: Optional suffix to append (e.g., 's' for seconds).

        Returns:
            Formatted string like '0.82 +/- 0.21s' or 'N/A'.
        """
        if self.mean is None:
            return "N/A"
        if self.stddev is None or self.stddev == 0:
            return f"{self.mean:.{precision}f}{suffix}"
        return (
            f"{self.mean:.{precision}f} +/- {self.stddev:.{precision}f}{suffix}"
        )


class CostsStats(BaseModel):
    """Cost statistics at different aggregation levels."""

    checkpoint: MetricStats = Field(default_factory=MetricStats)
    problem: MetricStats = Field(default_factory=MetricStats)
    total: float = 0.0


class TimeStats(BaseModel):
    """Time statistics at different aggregation levels."""

    checkpoint: MetricStats = Field(default_factory=MetricStats)
    problem: MetricStats = Field(default_factory=MetricStats)


class TokenMeans(BaseModel):
    """Mean token counts by type."""

    input: float = 0.0
    output: float = 0.0
    cache_read: float = 0.0
    cache_write: float = 0.0
    reasoning: float = 0.0


class TokenStats(BaseModel):
    """Token statistics: totals and per-level means."""

    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_write: int = 0
    reasoning: int = 0
    problem: TokenMeans = Field(default_factory=TokenMeans)
    checkpoint: TokenMeans = Field(default_factory=TokenMeans)


class StepsStats(BaseModel):
    """Step statistics at different aggregation levels."""

    checkpoint: MetricStats = Field(default_factory=MetricStats)
    problem: MetricStats = Field(default_factory=MetricStats)


class CyclomaticComplexityStats(BaseModel):
    """Cyclomatic complexity aggregates across checkpoints."""

    high_count: MetricStats = Field(default_factory=MetricStats)
    high_mean: MetricStats = Field(default_factory=MetricStats)
    max: MetricStats = Field(default_factory=MetricStats)


class PassRatesByType(BaseModel):
    """Pass rates by test type (means)."""

    core: float = 0.0
    total: float = 0.0
    error: float = 0.0
    functionality: float = 0.0
    regression: float = 0.0


class PassRatesStats(BaseModel):
    """Pass rate statistics at different aggregation levels."""

    problem: PassRatesByType = Field(default_factory=PassRatesByType)
    checkpoint: PassRatesByType = Field(default_factory=PassRatesByType)


class RatiosStats(BaseModel):
    """Quality ratio statistics (per LOC)."""

    rubric: MetricStats = Field(default_factory=MetricStats)
    lint: MetricStats = Field(default_factory=MetricStats)
    ast_grep: MetricStats = Field(default_factory=MetricStats)


class DeltaStats(BaseModel):
    """Delta statistics between consecutive checkpoints."""

    lint: MetricStats = Field(default_factory=MetricStats)
    complex: MetricStats = Field(default_factory=MetricStats)
    ast_grep: MetricStats = Field(default_factory=MetricStats)
    comparisons: MetricStats = Field(default_factory=MetricStats)
    rubric_non_carryover: MetricStats = Field(default_factory=MetricStats)


class RunSummary(BaseModel):
    """Complete summary statistics for a run."""

    model: str
    thinking: str
    prompt: str
    agent_type: str
    agent_version: str | None

    # Counts
    num_problems: int
    num_checkpoints: int

    # Costs: {checkpoint, problem, total}
    costs: CostsStats = Field(default_factory=CostsStats)

    # Time: {checkpoint, problem}
    time: TimeStats = Field(default_factory=TimeStats)

    # Tokens: totals + per-level means
    tokens: TokenStats = Field(default_factory=TokenStats)

    # Steps: {checkpoint, problem}
    steps: StepsStats = Field(default_factory=StepsStats)

    # Solve rates
    checkpoints_solved: int = 0
    checkpoints_iso_solved: int = 0
    checkpoints_core_solved: int = 0
    problem_solved: float = 0.0
    problem_partial: float = 0.0
    pct_checkpoints_solved: float = 0.0
    pct_checkpoints_iso_solved: float = 0.0
    pct_problems_solved: float = 0.0
    pct_problems_partial: float = 0.0
    pct_checkpoints_core_solved: float = 0.0

    # Pass rates by test type: {problem, checkpoint} x {core, total, error, ...}
    pass_rates: PassRatesStats = Field(default_factory=PassRatesStats)

    # Cyclomatic complexity
    cc: CyclomaticComplexityStats = Field(
        default_factory=CyclomaticComplexityStats
    )

    # Quality ratios (per LOC): {rubric, lint, ast_grep}
    ratios: RatiosStats = Field(default_factory=RatiosStats)

    # Delta stats between consecutive checkpoints
    delta: DeltaStats = Field(default_factory=DeltaStats)

    # Composite quality scores
    verbosity: MetricStats = Field(default_factory=MetricStats)
    erosion: MetricStats = Field(default_factory=MetricStats)
