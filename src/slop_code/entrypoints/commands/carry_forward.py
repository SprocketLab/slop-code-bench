"""Carry forward rubric grades from previous checkpoints."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from slop_code.entrypoints.utils import discover_checkpoints
from slop_code.entrypoints.utils import discover_problems
from slop_code.logging import get_logger
from slop_code.metrics import process_problem_carry_forward

logger = get_logger(__name__)


def register(app: typer.Typer, name: str):
    app.command(
        name,
        help="Carry forward rubric grades from previous checkpoints.",
    )(carry_forward_grades)


def carry_forward_grades(
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
            "--problem",
            help="Filter to a specific problem name.",
        ),
    ] = None,
) -> None:
    """Carry forward unchanged rubric grades from previous checkpoints.

    For each checkpoint N > 1, loads the previous checkpoint's rubric.jsonl
    and diff.json, identifies grades that should be carried forward (unchanged
    code regions not re-flagged), and augments the current rubric.jsonl.
    """
    console = Console()

    # Discover problems
    problems = discover_problems(run_dir)

    if not problems:
        console.print(f"[red]No problems found in {run_dir}[/red]")
        sys.exit(1)

    # Filter by problem name if specified
    if problem_name is not None:
        problems = [p for p in problems if p.name == problem_name]
        if not problems:
            console.print(
                f"[red]Problem '{problem_name}' not found in {run_dir}[/red]"
            )
            sys.exit(1)

    console.print(
        f"[green]Found {len(problems)} problem(s) in {run_dir}[/green]"
    )

    # Process each problem
    all_results: dict[str, dict[str, dict[str, int]]] = {}

    for problem_dir in problems:
        console.print(f"\n[bold]Processing: {problem_dir.name}[/bold]")
        results = process_problem_carry_forward(
            problem_dir, discover_checkpoints
        )
        all_results[problem_dir.name] = results

    # Display summary table
    console.print("\n[bold]Summary[/bold]")

    table = Table(show_header=True, show_lines=True)
    table.add_column("Problem")
    table.add_column("Checkpoint")
    table.add_column("Original Total")
    table.add_column("Carried")
    table.add_column("Total Grades")

    total_carried = 0
    for prob_name, checkpoints in all_results.items():
        for i, (checkpoint_name, stats) in enumerate(checkpoints.items()):
            display_problem = prob_name if i == 0 else ""
            original_total = stats.get("original_total", 0)
            carried = stats.get("carried", 0)
            total = stats.get("total", 0)
            total_carried += carried
            table.add_row(
                display_problem,
                checkpoint_name,
                str(original_total),
                str(carried),
                str(total),
            )

    console.print(table)
    console.print(
        f"\n[green]Total grades carried forward: {total_carried}[/green]"
    )
