from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated, Any

import typer
import yaml

from slop_code.common import CHECKPOINT_RESULTS_FILENAME
from slop_code.common import CONFIG_FILENAME
from slop_code.entrypoints.utils import discover_run_directories
from slop_code.logging import get_logger
from slop_code.logging import setup_logging

logger = get_logger(__name__)


def register(app: typer.Typer, name: str) -> None:
    app.command(
        name,
        help=(
            "Combine checkpoint_results.jsonl from a set of runs into one JSONL "
            "with run metadata attached to each row."
        ),
    )(combine_results)


def combine_results(
    ctx: typer.Context,
    runs_dir: Annotated[
        Path,
        typer.Argument(
            help="Path to a run directory or a directory containing run outputs",
            exists=True,
            file_okay=False,
            dir_okay=True,
        ),
    ],
    output_file: Annotated[
        Path | None,
        typer.Option(
            "--output",
            "-o",
            help=(
                "Where to write the merged JSONL (defaults to "
                "<runs_dir>/combined_checkpoint_results.jsonl)"
            ),
            file_okay=True,
            dir_okay=False,
        ),
    ] = None,
    overwrite: Annotated[
        bool,
        typer.Option(
            "--overwrite",
            "-w",
            help="Overwrite the output file if it already exists",
        ),
    ] = False,
) -> None:
    """Merge checkpoint results across multiple runs with run-level metadata."""
    setup_logging(log_dir=None, verbosity=ctx.obj.verbosity)
    output_path = output_file or runs_dir / "combined_checkpoint_results.jsonl"

    run_dirs = discover_run_directories(runs_dir)
    if not run_dirs:
        typer.echo(
            typer.style(
                f"No run directories found under {runs_dir}",
                fg=typer.colors.RED,
                bold=True,
            )
        )
        raise typer.Exit(1)

    if output_path.exists() and not overwrite:
        typer.echo(
            typer.style(
                f"Output file already exists: {output_path} "
                "(use --overwrite to replace)",
                fg=typer.colors.RED,
                bold=True,
            )
        )
        raise typer.Exit(1)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    typer.echo(f"Found {len(run_dirs)} run(s); collecting results...")
    total_records = 0
    runs_with_results = 0

    with output_path.open("w", encoding="utf-8") as merged_file:
        for run_dir in run_dirs:
            run_meta = _load_run_metadata(run_dir, runs_dir)
            results_path = run_dir / CHECKPOINT_RESULTS_FILENAME
            if not results_path.exists():
                logger.warning(
                    "Skipping run with no checkpoint results",
                    run=str(run_dir),
                    results_path=str(results_path),
                )
                continue

            records_written = 0
            for record in _load_checkpoint_results(results_path):
                merged_record = {**record, **run_meta}
                merged_file.write(json.dumps(merged_record))
                merged_file.write("\n")
                records_written += 1

            if records_written:
                runs_with_results += 1
                total_records += records_written
                typer.echo(
                    f"  {run_dir}: wrote {records_written} checkpoint record(s)"
                )

    typer.echo(
        typer.style(
            f"\nMerged {total_records} checkpoint(s) from "
            f"{runs_with_results} run(s) into {output_path}",
            fg=typer.colors.GREEN,
            bold=True,
        )
    )


def _load_checkpoint_results(results_path: Path) -> Iterator[dict[str, Any]]:
    """Stream a checkpoint_results.jsonl file as dicts."""
    try:
        with results_path.open(encoding="utf-8") as f:
            for idx, line in enumerate(f, start=1):
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    yield json.loads(stripped)
                except json.JSONDecodeError as exc:
                    logger.warning(
                        "Skipping malformed JSONL line",
                        path=str(results_path),
                        line_number=idx,
                        error=str(exc),
                    )
    except OSError as exc:
        logger.warning(
            "Failed to read checkpoint results",
            path=str(results_path),
            error=str(exc),
        )


def _load_run_metadata(run_dir: Path, base_dir: Path) -> dict[str, Any]:
    """Extract run-level metadata useful for grouping."""
    meta: dict[str, Any] = {
        "run_name": run_dir.name,
        "run_dir": str(run_dir),
    }

    try:
        relative_path = run_dir.relative_to(base_dir)
        meta["run_relative_path"] = (
            run_dir.name if str(relative_path) == "." else str(relative_path)
        )
    except ValueError:
        meta["run_relative_path"] = run_dir.name

    relative_parts = Path(meta["run_relative_path"]).parts
    if len(relative_parts) > 1:
        meta["run_group"] = relative_parts[0]

    config_path = run_dir / CONFIG_FILENAME
    if not config_path.exists():
        logger.warning(
            "Run config not found; metadata will be partial",
            run=str(run_dir),
            config_path=str(config_path),
        )
        return meta

    try:
        with config_path.open(encoding="utf-8") as f:
            config_data = yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError) as exc:
        logger.warning(
            "Failed to load run config; metadata will be partial",
            run=str(run_dir),
            config_path=str(config_path),
            error=str(exc),
        )
        return meta

    if not isinstance(config_data, dict):
        logger.warning(
            "Unexpected run config format; metadata will be partial",
            run=str(run_dir),
            config_path=str(config_path),
        )
        return meta

    model = config_data.get("model", {}) or {}
    agent = config_data.get("agent", {}) or {}
    environment = config_data.get("environment", {}) or {}

    meta["model_name"] = model.get("name")
    meta["model_provider"] = model.get("provider")

    meta["prompt_path"] = config_data.get("prompt_path")
    if meta["prompt_path"]:
        meta["prompt_name"] = Path(meta["prompt_path"]).stem
    else:
        meta["prompt_name"] = None

    meta["thinking_level"] = config_data.get("thinking")
    meta["thinking_max_tokens"] = config_data.get("thinking_max_tokens")
    meta["pass_policy"] = config_data.get("pass_policy")

    meta["agent_type"] = agent.get("type")
    meta["agent_version"] = agent.get("version")
    meta["agent_binary"] = agent.get("binary")
    meta["agent_timeout"] = agent.get("timeout")
    meta["agent_config_path"] = config_data.get("agent_config_path")

    meta["environment_name"] = environment.get("name")
    meta["environment_type"] = environment.get("type")
    meta["environment_config_path"] = config_data.get("environment_config_path")

    meta["output_path"] = config_data.get("output_path")

    return meta
