from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from pydantic import BaseModel
from rich import box
from rich.table import Table

from slop_code import common
from slop_code.agent_runner import ProviderCatalog
from slop_code.common.llms import ModelCatalog
from slop_code.common.llms import ModelDefinition
from slop_code.evaluation import CheckpointConfig
from slop_code.evaluation import ProblemConfig
from slop_code.logging import get_logger
from slop_code.metrics import RunSummary
from slop_code.metrics import compute_run_summary
from slop_code.metrics import load_checkpoint_data
from slop_code.metrics import save_summary_json

if TYPE_CHECKING:
    from rich.console import Console

logger = get_logger(__name__)


class CLIContext(BaseModel):
    verbosity: int
    seed: int
    problem_path: Path
    overwrite: bool
    debug: bool
    snapshot_dir_name: str
    quiet: bool = False


class CLIError(Exception):
    """Exception raised by the CLI."""


@dataclass(frozen=True)
class ModelOverride:
    """Parsed model specification from CLI in {provider}/{model} format.

    Attributes:
        model_def: The ModelDefinition from the catalog
        provider: The credential provider (e.g., "anthropic")
    """

    model_def: ModelDefinition
    provider: str

    @property
    def name(self) -> str:
        """Registered model name (config filename)."""
        return self.model_def.name

    @property
    def internal_name(self) -> str:
        """API model identifier."""
        return self.model_def.internal_name


def ensure_dir_exists(path: Path, *, create: bool = False) -> Path:
    logger.debug(
        "Ensuring directory exists", path=path, create=create, verbose=True
    )
    if not path.exists():
        if create:
            path.mkdir(parents=True, exist_ok=True)
            return path
        raise FileNotFoundError(f"{path} does not exist")

    if not path.is_dir():
        raise FileNotFoundError(f"Path {path} is not a directory")
    return path


def ensure_file_exists(path: Path) -> Path:
    logger.debug("Ensuring file exists", path=path, verbose=True)
    if not path.exists():
        raise FileNotFoundError(f"{path} does not exist")
    if not path.is_file():
        raise FileNotFoundError(f"Path {path} is not a file")
    return path


def ensure_at_least_one_file_exists(*paths: Path) -> Path:
    logger.debug("Ensuring at least one file exists", paths=paths, verbose=True)
    for path in paths:
        if path.exists():
            return path
    raise FileNotFoundError(f"No files exist in {paths}")


def parse_model_override(raw_value: str) -> ModelOverride:
    """Parse a CLI model specification of the form '{provider}/{model}'.

    Both provider and model are required.

    Args:
        raw_value: The raw CLI value in '{provider}/{model}' format.

    Returns:
        ModelOverride with provider and model.

    Raises:
        ValueError: If the format is invalid or provider is unknown.
    """
    value = raw_value.strip()
    if not value:
        raise ValueError("Model specification cannot be empty")

    if "/" not in value:
        raise ValueError(
            f"Model must be in '{{provider}}/{{model}}' format. Got: '{value}'"
        )

    provider, model = value.split("/", 1)
    provider = provider.strip()
    model = model.strip()

    if not provider:
        raise ValueError(
            "Provider cannot be empty. Use '{provider}/{model}' format."
        )
    if not model:
        raise ValueError(
            "Model name cannot be empty. Use '{provider}/{model}' format."
        )

    # Validate provider exists
    ProviderCatalog.ensure_loaded()
    if ProviderCatalog.get(provider) is None:
        available = ", ".join(ProviderCatalog.list_providers())
        raise ValueError(
            f"Unknown provider '{provider}'. "
            f"Known providers: {available or 'none'}."
        )

    canonical_model = ModelCatalog.resolve_canonical(model)

    # Validate model exists in catalog
    model_def = ModelCatalog.get(canonical_model)
    if model_def is None:
        available = ModelCatalog.list_models()
        if len(available) > 10:
            models_str = ", ".join(available[:10]) + "..."
        else:
            models_str = ", ".join(available) if available else "none"
        raise ValueError(f"Unknown model '{model}'. Known models: {models_str}")

    return ModelOverride(model_def=model_def, provider=provider)


def load_problem_from_snapshot_dir(
    snapshot_dir: Path,
) -> tuple[Path, ProblemConfig, CheckpointConfig] | None:
    logger.info(
        "Loading problem from snapshot directory", snapshot_dir=snapshot_dir
    )
    chkpt_dir = snapshot_dir.parent.name
    problem_dir = snapshot_dir.parents[1]
    logger.debug(
        "Checkpoint directory", chkpt_dir=chkpt_dir, problem_dir=problem_dir
    )
    if not (problem_dir / "problem.yaml").exists():
        logger.info("Problem directory not found", problem_dir=problem_dir)
        return None
    with (problem_dir / "problem.yaml").open() as f:
        problem_config = ProblemConfig.model_validate(yaml.safe_load(f))
    checkpoint_config = problem_config.checkpoints[chkpt_dir]
    return problem_dir, problem_config, checkpoint_config


def discover_problems(run_dir: Path) -> list[Path]:
    """Discover problem directories in a run directory.

    A problem directory is identified by containing checkpoint_* subdirectories.

    Args:
        run_dir: Path to the run directory.

    Returns:
        List of paths to problem directories, sorted by name.
    """
    problems: list[Path] = []

    for child in run_dir.iterdir():
        if not child.is_dir():
            continue

        # Check if this directory contains checkpoint_* subdirectories
        has_checkpoints = any(
            subdir.is_dir() and subdir.name.startswith("checkpoint_")
            for subdir in child.iterdir()
        )
        if has_checkpoints:
            problems.append(child)

    return sorted(problems)


def discover_run_directories(collection_dir: Path) -> list[Path]:
    """Discover run directories by finding config.yaml files with 'agent' field.

    A run directory is identified by containing a config.yaml file that has
    an 'agent' key at the top level.

    Args:
        collection_dir: Path to search for run directories.

    Returns:
        Sorted list of valid run directory paths.
    """
    run_dirs: list[Path] = []

    for config_file in collection_dir.rglob(common.CONFIG_FILENAME):
        # Skip snapshot directories (problem test data)
        if "snapshot" in config_file.parts:
            continue

        try:
            with config_file.open() as f:
                config_data = yaml.safe_load(f)

            if isinstance(config_data, dict) and "agent" in config_data:
                run_dirs.append(config_file.parent)
        except (yaml.YAMLError, OSError):
            continue

    return sorted(run_dirs)


def discover_checkpoints(problem_dir: Path) -> list[Path]:
    """Discover checkpoint directories in a problem directory.

    Args:
        problem_dir: Path to the problem directory.

    Returns:
        List of paths to checkpoint directories, sorted by checkpoint number.
    """
    checkpoint_pattern = re.compile(r"^checkpoint_(\d+)$")
    checkpoints: list[tuple[int, Path]] = []

    for child in problem_dir.iterdir():
        if not child.is_dir():
            continue

        match = checkpoint_pattern.match(child.name)
        if match:
            checkpoint_num = int(match.group(1))
            checkpoints.append((checkpoint_num, child))

    # Sort by checkpoint number
    checkpoints.sort(key=lambda x: x[0])
    return [path for _, path in checkpoints]


def render_summary_table(summary: RunSummary, console: Console) -> None:
    """Render summary statistics as a Rich table to console.

    Args:
        summary: Computed summary statistics.
        console: Rich console for output.
    """
    table = Table(
        title="Run Summary",
        show_header=True,
        header_style="bold cyan",
        box=box.ROUNDED,
    )
    table.add_column("Metric", style="cyan", width=28)
    table.add_column("Value", justify="right", width=22)

    # Counts
    table.add_row("Problems ran", str(summary.num_problems))
    table.add_row("Checkpoints", str(summary.num_checkpoints))

    # Costs
    table.add_row("Total cost", f"${summary.costs.total:.4f}")
    table.add_row(
        "Mean cost / chkpt",
        f"${summary.costs.checkpoint.format_display(4)}",
    )

    # Time
    table.add_row(
        "Mean time / chkpt",
        summary.time.checkpoint.format_display(1, "s"),
    )

    # Tokens (now means, not MetricStats)
    table.add_row(
        "Mean input tokens / chkpt",
        f"{summary.tokens.checkpoint.input:,.0f}",
    )
    table.add_row(
        "Mean output tokens / chkpt",
        f"{summary.tokens.checkpoint.output:,.0f}",
    )

    # Steps
    table.add_row(
        "Mean steps / chkpt",
        summary.steps.checkpoint.format_display(1),
    )

    # Separator for pass rate section
    table.add_section()

    # Pass rates (only show if available)
    table.add_row(
        "% checkpoints solved",
        f"{summary.pct_checkpoints_solved:.1f}%",
    )
    table.add_row(
        "% checkpoints iso solved",
        f"{summary.pct_checkpoints_iso_solved:.1f}%",
    )
    table.add_row(
        "% checkpoints core solved",
        f"{summary.pct_checkpoints_core_solved:.1f}%",
    )
    table.add_row(
        "% problems solved",
        f"{summary.pct_problems_solved:.1f}%",
    )
    table.add_row(
        "% problems partial",
        f"{summary.pct_problems_partial:.1f}%",
    )
    table.add_row(
        "Mean test pass rate",
        f"{summary.pass_rates.checkpoint.total:.3f}",
    )

    # Separator for quality section
    table.add_section()

    # Quality ratios (only show if data available)
    if summary.ratios.rubric.count > 0:
        table.add_row(
            "Mean rubric:loc",
            summary.ratios.rubric.format_display(4),
        )
    if summary.ratios.lint.count > 0:
        table.add_row(
            "Mean lint:loc",
            summary.ratios.lint.format_display(4),
        )
    if summary.ratios.ast_grep.count > 0:
        table.add_row(
            "Mean ast_grep:loc",
            summary.ratios.ast_grep.format_display(4),
        )
    if summary.verbosity.count > 0:
        table.add_row(
            "Mean verbosity",
            summary.verbosity.format_display(4),
        )
    if summary.erosion.count > 0:
        table.add_row(
            "Mean erosion",
            summary.erosion.format_display(4),
        )

    console.print()
    console.print(table)


def display_and_save_summary(
    results_file: Path,
    run_dir: Path,
    config: dict,
    console: Console,
) -> RunSummary | None:
    """Convenience function to load, compute, display, and save summary.

    Args:
        results_file: Path to checkpoint_results.jsonl file.
        run_dir: Directory to save result.json to.
        console: Rich console for display.

    Returns:
        RunSummary if successful, None if no data available.
    """
    if not results_file.exists():
        logger.debug(
            "Checkpoint results file not found, skipping summary",
            path=str(results_file),
        )
        return None

    try:
        checkpoint_data = load_checkpoint_data(results_file)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning(
            "Failed to load checkpoint results data",
            path=str(results_file),
            error=str(e),
        )
        return None

    if not checkpoint_data:
        logger.debug(
            "No checkpoint data found, skipping summary",
            path=str(results_file),
        )
        return None

    summary = compute_run_summary(config, checkpoint_data)
    render_summary_table(summary, console)
    save_summary_json(summary, run_dir)

    return summary
