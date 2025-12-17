"""Run summary statistics computation.

This module aggregates checkpoint metrics into run-level statistics,
computing means, stddevs, and other aggregate metrics across checkpoints.
"""

from __future__ import annotations

import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from pydantic import Field

from slop_code.common import SUMMARY_FILENAME
from slop_code.logging import get_logger

logger = get_logger(__name__)


# -----------------------------------------------------------------------------
# Pydantic Models
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

    # Solve rates (keep names)
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


# -----------------------------------------------------------------------------
# Helper Functions
# -----------------------------------------------------------------------------


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


def load_checkpoint_data(results_file: Path) -> list[dict[str, Any]]:
    """Load checkpoint data from checkpoint_results.jsonl.

    Args:
        results_file: Path to checkpoint_results.jsonl file.

    Returns:
        List of checkpoint dictionaries.

    Raises:
        FileNotFoundError: If checkpoint_results file doesn't exist.
    """
    if not results_file.exists():
        raise FileNotFoundError(
            f"Checkpoint results file not found: {results_file}"
        )

    checkpoints: list[dict[str, Any]] = []
    with results_file.open("r") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                checkpoints.append(entry)
            except json.JSONDecodeError as e:
                logger.warning(
                    "Skipping malformed JSON line",
                    file=str(results_file),
                    line_num=line_num,
                    error=str(e),
                )

    return checkpoints


def _extract_metric_values(
    checkpoints: list[dict[str, Any]],
    key: str,
) -> list[float]:
    """Extract values for a metric from checkpoints."""
    return [chkpt[key] for chkpt in checkpoints if key in chkpt]


def _compute_ratio_values(
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


def _compute_pass_rate(passed: float | None, total: float | None) -> float:
    """Compute pass rate safely, returning 0.0 if total is 0 or missing."""
    if total is None or total == 0:
        return 0.0
    if passed is None:
        return 0.0
    return passed / total


# -----------------------------------------------------------------------------
# Summary Component Computations
# -----------------------------------------------------------------------------


def _group_by_problem(
    checkpoints: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Group checkpoints by problem name."""
    problems: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for chkpt in checkpoints:
        problem_name = chkpt.get("problem", "unknown")
        problems[problem_name].append(chkpt)
    return problems


def _compute_costs_stats(
    checkpoints: list[dict[str, Any]],
    problems: dict[str, list[dict[str, Any]]],
) -> CostsStats:
    """Compute cost statistics at checkpoint and problem levels."""
    checkpoint_costs = _extract_metric_values(checkpoints, "cost")
    total_cost = sum(checkpoint_costs) if checkpoint_costs else 0.0

    problem_costs: list[float] = []
    for problem_chkpts in problems.values():
        problem_cost = sum(c.get("cost", 0) for c in problem_chkpts)
        problem_costs.append(problem_cost)

    return CostsStats(
        checkpoint=compute_metric_stats(checkpoint_costs),
        problem=compute_metric_stats(problem_costs),
        total=total_cost,
    )


def _compute_time_stats(
    checkpoints: list[dict[str, Any]],
    problems: dict[str, list[dict[str, Any]]],
) -> TimeStats:
    """Compute time statistics at checkpoint and problem levels."""
    checkpoint_times = _extract_metric_values(checkpoints, "elapsed")

    problem_times: list[float] = []
    for problem_chkpts in problems.values():
        problem_time = sum(c.get("elapsed", 0) for c in problem_chkpts)
        problem_times.append(problem_time)

    return TimeStats(
        checkpoint=compute_metric_stats(checkpoint_times),
        problem=compute_metric_stats(problem_times),
    )


def _compute_tokens_stats(
    checkpoints: list[dict[str, Any]],
    problems: dict[str, list[dict[str, Any]]],
) -> TokenStats:
    """Compute token statistics: totals and per-level means."""
    input_values = _extract_metric_values(checkpoints, "input")
    output_values = _extract_metric_values(checkpoints, "output")
    cache_read_values = _extract_metric_values(checkpoints, "cache_read")
    cache_write_values = _extract_metric_values(checkpoints, "cache_write")
    reasoning_values = _extract_metric_values(checkpoints, "reasoning")

    # Per-checkpoint means
    checkpoint_token_means = TokenMeans(
        input=statistics.mean(input_values) if input_values else 0.0,
        output=statistics.mean(output_values) if output_values else 0.0,
        cache_read=statistics.mean(cache_read_values)
        if cache_read_values
        else 0.0,
        cache_write=statistics.mean(cache_write_values)
        if cache_write_values
        else 0.0,
        reasoning=statistics.mean(reasoning_values)
        if reasoning_values
        else 0.0,
    )

    # Per-problem token totals, then compute means
    problem_input: list[float] = []
    problem_output: list[float] = []
    problem_cache_read: list[float] = []
    problem_cache_write: list[float] = []
    problem_reasoning: list[float] = []

    for problem_chkpts in problems.values():
        problem_input.append(sum(c.get("input", 0) for c in problem_chkpts))
        problem_output.append(sum(c.get("output", 0) for c in problem_chkpts))
        problem_cache_read.append(
            sum(c.get("cache_read", 0) for c in problem_chkpts)
        )
        problem_cache_write.append(
            sum(c.get("cache_write", 0) for c in problem_chkpts)
        )
        problem_reasoning.append(
            sum(c.get("reasoning", 0) for c in problem_chkpts)
        )

    problem_token_means = TokenMeans(
        input=statistics.mean(problem_input) if problem_input else 0.0,
        output=statistics.mean(problem_output) if problem_output else 0.0,
        cache_read=statistics.mean(problem_cache_read)
        if problem_cache_read
        else 0.0,
        cache_write=statistics.mean(problem_cache_write)
        if problem_cache_write
        else 0.0,
        reasoning=statistics.mean(problem_reasoning)
        if problem_reasoning
        else 0.0,
    )

    return TokenStats(
        input=int(sum(input_values)) if input_values else 0,
        output=int(sum(output_values)) if output_values else 0,
        cache_read=int(sum(cache_read_values)) if cache_read_values else 0,
        cache_write=int(sum(cache_write_values)) if cache_write_values else 0,
        reasoning=int(sum(reasoning_values)) if reasoning_values else 0,
        checkpoint=checkpoint_token_means,
        problem=problem_token_means,
    )


def _compute_steps_stats(
    checkpoints: list[dict[str, Any]],
    problems: dict[str, list[dict[str, Any]]],
) -> StepsStats:
    """Compute step statistics at checkpoint and problem levels."""
    checkpoint_steps = _extract_metric_values(checkpoints, "steps")

    problem_steps: list[float] = []
    for problem_chkpts in problems.values():
        problem_step = sum(c.get("steps", 0) for c in problem_chkpts)
        problem_steps.append(problem_step)

    return StepsStats(
        checkpoint=compute_metric_stats(checkpoint_steps),
        problem=compute_metric_stats(problem_steps),
    )


def _compute_solve_rates(
    checkpoints: list[dict[str, Any]],
    problems: dict[str, list[dict[str, Any]]],
) -> dict[str, float | None]:
    """Compute solve rate percentages.

    Returns:
        Dict with pct_checkpoints_solved, pct_problems_solved, pct_problems_partial.
    """
    pass_rates_list = _extract_metric_values(checkpoints, "pass_rate")
    iso_pass_rates_list = _extract_metric_values(
        checkpoints, "checkpoint_pass_rate"
    )
    core_pass_rates_list = _extract_metric_values(checkpoints, "core_pass_rate")
    num_problems = len(problems)
    if not pass_rates_list or not iso_pass_rates_list:
        return {}

    checkpoints_solved = sum(
        1 for pr in pass_rates_list if math.isclose(pr, 1.0)
    )
    iso_solved = sum(1 for pr in iso_pass_rates_list if math.isclose(pr, 1.0))
    core_solved = sum(1 for pr in core_pass_rates_list if math.isclose(pr, 1.0))
    pct_problems_solved: float | None = None
    pct_problems_partial: float | None = None

    fully_solved = 0
    partially_solved = 0
    for problem_chkpts in problems.values():
        problem_pass_rates = [c.get("pass_rate", 0.0) for c in problem_chkpts]
        if problem_pass_rates:
            if all(pr == 1.0 for pr in problem_pass_rates):
                fully_solved += 1
            if any(pr == 1.0 for pr in problem_pass_rates):
                partially_solved += 1
    pct_problems_solved = (fully_solved / num_problems) * 100
    pct_problems_partial = (partially_solved / num_problems) * 100

    return {
        "pct_checkpoints_solved": checkpoints_solved / len(checkpoints) * 100,
        "pct_checkpoints_iso_solved": iso_solved / len(checkpoints) * 100,
        "pct_problems_solved": pct_problems_solved,
        "pct_problems_partial": pct_problems_partial,
        "pct_checkpoints_core_solved": core_solved / len(checkpoints) * 100,
        "problem_solved": fully_solved,
        "problem_partial": partially_solved,
        "checkpoints_solved": checkpoints_solved,
        "checkpoints_iso_solved": iso_solved,
        "checkpoints_core_solved": core_solved,
    }


def _compute_pass_rates_stats(
    checkpoints: list[dict[str, Any]],
    problems: dict[str, list[dict[str, Any]]],
) -> PassRatesStats:
    """Compute pass rate statistics by test type at checkpoint and problem levels."""
    test_types = ["core", "total", "error", "functionality", "regression"]

    # Per-checkpoint pass rates by type
    checkpoint_pass_rates: dict[str, list[float]] = {t: [] for t in test_types}
    for chkpt in checkpoints:
        checkpoint_pass_rates["total"].append(
            _compute_pass_rate(
                chkpt.get("passed_tests"), chkpt.get("total_tests")
            )
        )
        for test_type in ["core", "error", "functionality", "regression"]:
            checkpoint_pass_rates[test_type].append(
                _compute_pass_rate(
                    chkpt.get(f"{test_type}_passed"),
                    chkpt.get(f"{test_type}_total"),
                )
            )

    # Per-problem pass rates by type (mean of checkpoint pass rates per problem)
    problem_pass_rates: dict[str, list[float]] = {t: [] for t in test_types}
    for problem_chkpts in problems.values():
        for test_type in test_types:
            if test_type == "total":
                rates = [
                    _compute_pass_rate(
                        c.get("passed_tests"), c.get("total_tests")
                    )
                    for c in problem_chkpts
                ]
            else:
                rates = [
                    _compute_pass_rate(
                        c.get(f"{test_type}_passed"),
                        c.get(f"{test_type}_total"),
                    )
                    for c in problem_chkpts
                ]
            problem_pass_rates[test_type].append(
                statistics.mean(rates) if rates else 0.0
            )

    def safe_mean(values: list[float]) -> float:
        return statistics.mean(values) if values else 0.0

    return PassRatesStats(
        checkpoint=PassRatesByType(
            core=safe_mean(checkpoint_pass_rates["core"]),
            total=safe_mean(checkpoint_pass_rates["total"]),
            error=safe_mean(checkpoint_pass_rates["error"]),
            functionality=safe_mean(checkpoint_pass_rates["functionality"]),
            regression=safe_mean(checkpoint_pass_rates["regression"]),
        ),
        problem=PassRatesByType(
            core=safe_mean(problem_pass_rates["core"]),
            total=safe_mean(problem_pass_rates["total"]),
            error=safe_mean(problem_pass_rates["error"]),
            functionality=safe_mean(problem_pass_rates["functionality"]),
            regression=safe_mean(problem_pass_rates["regression"]),
        ),
    )


def _compute_cc_stats(
    checkpoints: list[dict[str, Any]],
) -> CyclomaticComplexityStats:
    """Compute CC (cyclomatic complexity) statistics."""
    high_counts = _extract_metric_values(checkpoints, "cc_high_count")
    high_means = _extract_metric_values(checkpoints, "high_cc_mean")
    max_values = _extract_metric_values(checkpoints, "cc_max")

    return CyclomaticComplexityStats(
        high_count=compute_metric_stats(high_counts),
        high_mean=compute_metric_stats(high_means),
        max=compute_metric_stats(max_values),
    )


def _compute_ratios_stats(checkpoints: list[dict[str, Any]]) -> RatiosStats:
    """Compute quality ratio statistics (per LOC)."""
    rubric_ratios = _compute_ratio_values(
        checkpoints, "rubric_total_flags", "loc"
    )
    lint_ratios = _compute_ratio_values(checkpoints, "lint_errors", "loc")
    ast_grep_ratios = _compute_ratio_values(
        checkpoints, "ast_grep_violations", "loc"
    )

    return RatiosStats(
        rubric=compute_metric_stats(rubric_ratios),
        lint=compute_metric_stats(lint_ratios),
        ast_grep=compute_metric_stats(ast_grep_ratios),
    )


def _compute_delta_stats(checkpoints: list[dict[str, Any]]) -> DeltaStats:
    """Compute delta statistics between consecutive checkpoints."""

    def extract_delta_values(key: str) -> list[float]:
        """Extract delta.{key} values from checkpoints (skipping None/inf)."""
        values: list[float] = []
        for chkpt in checkpoints:
            val = chkpt.get(f"delta.{key}")
            if val is not None and val != float("inf"):
                values.append(val)
        return values

    return DeltaStats(
        lint=compute_metric_stats(extract_delta_values("lint_errors")),
        complex=compute_metric_stats(extract_delta_values("cc_high_count")),
        comparisons=compute_metric_stats(extract_delta_values("comparisons")),
        ast_grep=compute_metric_stats(
            extract_delta_values("ast_grep_violations")
        ),
        rubric_non_carryover=compute_metric_stats(
            extract_delta_values("new_violations_per_loc")
        ),
    )


def _compute_composite_scores(
    checkpoints: list[dict[str, Any]],
) -> dict[str, MetricStats]:
    """Compute verbosity and erosion composite scores.

    Verbosity measures code bloat: flags per LOC + wrapper/single-use ratios.
    Erosion measures code degradation: high complexity ratio + lint density.
    """
    verbosity_values: list[float] = []
    erosion_values: list[float] = []

    for chkpt in checkpoints:
        loc = chkpt.get("loc", 0)
        funcs = chkpt.get("functions", 0)
        methods = chkpt.get("methods", 0)
        total_callables = funcs + methods

        # Verbosity: (ast_grep + rubric) / loc + wrapper_ratios
        if loc > 0 and total_callables > 0:
            flags_per_loc = (
                chkpt.get("ast_grep_violations", 0)
                + chkpt.get("rubric_total_flags", 0)
            ) / loc
            wrapper_ratio = chkpt.get("trivial_wrappers", 0) / total_callables
            single_use_ratio = (
                chkpt.get("single_use_functions", 0) / total_callables
            )
            verbosity_values.append(
                flags_per_loc + wrapper_ratio + single_use_ratio
            )

        # Erosion: high complexity ratio + lint per LOC
        lint_per_loc = chkpt.get("lint_per_loc", 0.0) or 0.0
        if total_callables > 0:
            high_complex = (
                chkpt.get("cc_high_count", 0) + chkpt.get("cc_extreme_count", 0)
            ) / total_callables
            erosion_values.append(high_complex + lint_per_loc)

    return {
        "verbosity": compute_metric_stats(verbosity_values),
        "erosion": compute_metric_stats(erosion_values),
    }


# -----------------------------------------------------------------------------
# Main Summary Computation
# -----------------------------------------------------------------------------


def compute_run_summary(
    config: dict, checkpoints: list[dict[str, Any]]
) -> RunSummary:
    """Compute complete summary statistics from checkpoint data.

    Args:
        checkpoints: List of checkpoint data dictionaries.

    Returns:
        RunSummary with all computed statistics.
    """

    problems = _group_by_problem(checkpoints)
    solve_rates = _compute_solve_rates(checkpoints, problems)
    composite = _compute_composite_scores(checkpoints)

    return RunSummary(
        model=config["model"]["name"],
        thinking=config["thinking"],
        prompt=Path(config["prompt_path"]).stem,
        agent_type=config["agent"]["type"],
        agent_version=config["agent"].get("version"),
        num_problems=len(problems),
        num_checkpoints=len(checkpoints),
        costs=_compute_costs_stats(checkpoints, problems),
        time=_compute_time_stats(checkpoints, problems),
        tokens=_compute_tokens_stats(checkpoints, problems),
        steps=_compute_steps_stats(checkpoints, problems),
        **solve_rates,
        pass_rates=_compute_pass_rates_stats(checkpoints, problems),
        cc=_compute_cc_stats(checkpoints),
        ratios=_compute_ratios_stats(checkpoints),
        delta=_compute_delta_stats(checkpoints),
        **composite,
    )


# -----------------------------------------------------------------------------
# Persistence
# -----------------------------------------------------------------------------


def save_summary_json(
    summary: RunSummary,
    run_dir: Path,
    filename: str = SUMMARY_FILENAME,
) -> Path:
    """Save full summary statistics to JSON file.

    Args:
        summary: Computed summary statistics.
        run_dir: Directory to save results to.
        filename: Output filename.

    Returns:
        Path to saved file.
    """
    output_path = run_dir / filename
    with output_path.open("w") as f:
        json.dump(summary.model_dump(), f, indent=2)

    logger.info("Saved run summary", path=str(output_path))
    return output_path
