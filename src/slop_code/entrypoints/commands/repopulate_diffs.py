"""Repopulate diff.json files for checkpoint snapshots."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from slop_code.common import DIFF_FILENAME
from slop_code.common import SNAPSHOT_DIR_NAME
from slop_code.entrypoints.utils import discover_checkpoints
from slop_code.entrypoints.utils import discover_problems
from slop_code.execution.snapshot import create_diff_from_directories
from slop_code.logging import get_logger

logger = get_logger(__name__)


def register(app: typer.Typer, name: str):
    app.command(
        name,
        help="Repopulate diff.json files for checkpoint snapshots.",
    )(repopulate_diffs)


def _process_problem(
    problem_dir: Path,
) -> dict[str, dict[str, int]]:
    """Process a single problem, regenerating diff.json for each checkpoint.

    Args:
        problem_dir: Path to the problem directory.

    Returns:
        Dictionary mapping checkpoint names to their diff stats.
    """
    checkpoints = discover_checkpoints(problem_dir)
    results: dict[str, dict[str, int]] = {}

    prev_snapshot_dir: Path | None = None

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

        # Create diff comparing to previous checkpoint (or empty for first)
        diff = create_diff_from_directories(
            from_dir=prev_snapshot_dir,
            to_dir=snapshot_dir,
        )

        # Write diff.json
        diff_path = checkpoint_dir / DIFF_FILENAME
        with diff_path.open("w") as f:
            f.write(diff.model_dump_json(indent=2))

        logger.info(
            "Wrote diff.json",
            checkpoint=checkpoint_name,
            problem=problem_dir.name,
            changed_files=len(diff.file_diffs),
        )

        results[checkpoint_name] = diff.get_stats()

        # Update previous snapshot for next iteration
        prev_snapshot_dir = snapshot_dir

    return results


def repopulate_diffs(
    run_dir: Annotated[
        Path,
        typer.Argument(
            help="Path to the run directory",
            exists=True,
            dir_okay=True,
            file_okay=False,
        ),
    ],
    problem_name: Annotated[
        str | None,
        typer.Option(
            "-p",
            "--problem-name",
            help="Filter to a specific problem name.",
        ),
    ] = None,
) -> None:
    """Regenerate diff.json files for all checkpoints in a run.

    For each checkpoint, generates a diff comparing to the previous checkpoint's
    snapshot directory. The first checkpoint is compared against an empty
    snapshot (all files marked as created).
    """
    console = Console()

    # Discover problems
    problems = discover_problems(run_dir)

    if not problems:
        console.print(
            f"[red]No problems found in {run_dir}[/red]",
        )
        sys.exit(1)

    # Filter by problem name if specified
    if problem_name is not None:
        problems = [p for p in problems if p.name == problem_name]
        if not problems:
            console.print(
                f"[red]Problem '{problem_name}' not found in {run_dir}[/red]",
            )
            sys.exit(1)

    console.print(
        f"[green]Found {len(problems)} problem(s) in {run_dir}[/green]",
    )

    # Process each problem
    all_results: dict[str, dict[str, dict[str, int]]] = {}

    for problem_dir in problems:
        console.print(f"\n[bold]Processing: {problem_dir.name}[/bold]")
        results = _process_problem(problem_dir)
        all_results[problem_dir.name] = results

    # Display summary table
    console.print("\n[bold]Summary[/bold]")

    table = Table(show_header=True, show_lines=True)
    table.add_column("Problem")
    table.add_column("Checkpoint")
    table.add_column("Created")
    table.add_column("Modified")
    table.add_column("Deleted")
    table.add_column("Lines +")
    table.add_column("Lines -")

    for problem_name, checkpoints in all_results.items():
        for i, (checkpoint_name, stats) in enumerate(checkpoints.items()):
            # Only show problem name on first row
            display_problem = problem_name if i == 0 else ""
            table.add_row(
                display_problem,
                checkpoint_name,
                str(stats.get("created", 0)),
                str(stats.get("modified", 0)),
                str(stats.get("deleted", 0)),
                str(stats.get("lines_added", 0)),
                str(stats.get("lines_removed", 0)),
            )

    console.print(table)
