"""CLI commands for inspecting problems and checkpoints."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from slop_code.evaluation import CheckpointConfig
from slop_code.evaluation import GroupType
from slop_code.evaluation import ProblemConfig
from slop_code.evaluation import get_available_problems
from slop_code.evaluation import initialize_loader
from slop_code.evaluation.loaders import NoOpStore
from slop_code.logging import get_logger

logger = get_logger(__name__)
app = typer.Typer(help="Commands for inspecting problems and checkpoints")


def _count_cases_by_type(
    problem: ProblemConfig, checkpoint: CheckpointConfig
) -> dict[str, int]:
    loader = initialize_loader(problem, checkpoint, use_placeholders=True)
    store = loader.initialize_store()
    counts: Counter[str] = Counter(
        {group_type.value: 0 for group_type in GroupType}
    )

    for group_config in checkpoint.groups.values():
        group_type = (
            group_config.type.value
            if isinstance(group_config.type, GroupType)
            else str(group_config.type)
        )
        for case, _ in loader(group_config, store):
            counts[group_type] += 1
    return dict(counts)


def _build_checkpoint_entry(
    problem: ProblemConfig,
    checkpoint_name: str,
    checkpoint: CheckpointConfig,
) -> dict[str, object]:
    return {
        "checkpoint_name": checkpoint_name,
        "spec": checkpoint.get_spec_text(),
        "version": checkpoint.version,
        "state": checkpoint.state,
        "tests_by_type": _count_cases_by_type(problem, checkpoint),
    }


def _build_problem_entry(problem: ProblemConfig) -> dict[str, object]:
    checkpoints = [
        _build_checkpoint_entry(problem, name, checkpoint)
        for name, checkpoint in problem.iterate_checkpoint_items()
    ]
    return {
        "problem_name": problem.name,
        "tags": problem.tags,
        "version": problem.version,
        "author": problem.author,
        "category": problem.category,
        "entry_point": problem.entry_file,
        "adapter_type": problem.adapter.type,
        "difficulty": problem.difficulty,
        "description": problem.description,
        "checkpoints": checkpoints,
    }


def _has_non_draft_checkpoint(problem: ProblemConfig) -> bool:
    return any(cp.state != "Draft" for cp in problem.iterate_checkpoints())


@app.command("make-registry")
def make_registry(
    ctx: typer.Context,
    output: Annotated[
        Path | None,
        typer.Option(
            "--output",
            "-o",
            exists=False,
            file_okay=True,
            dir_okay=False,
            resolve_path=True,
            help="Path to write the registry JSONL (default: problems/registry.jsonl)",
        ),
    ] = None,
) -> None:
    """Generate a registry.jsonl file describing all non-draft problems."""
    output_path = output or ctx.obj.problem_path / "registry.jsonl"
    problems = get_available_problems(ctx.obj.problem_path)

    registry_rows = []
    skipped_draft = 0
    for problem_name in sorted(problems.keys()):
        problem = problems[problem_name]
        if not _has_non_draft_checkpoint(problem):
            skipped_draft += 1
            continue
        registry_rows.append(_build_problem_entry(problem))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        for row in registry_rows:
            f.write(json.dumps(row))
            f.write("\n")

    typer.echo(
        f"Wrote registry with {len(registry_rows)} "
        f"problem{'s' if len(registry_rows) != 1 else ''} to {output_path}"
        + (f" (skipped {skipped_draft} draft)" if skipped_draft else "")
    )


@app.command("ls")
def list_problems(
    ctx: typer.Context,
    include_draft: bool = typer.Option(
        False,
        "--include-draft",
        help="Include problems with only draft checkpoints",
    ),
) -> None:
    """List all problems with their metadata.

    Displays a table with problem name, version, adapter type, category,
    and checkpoint count. By default, excludes problems that only have
    draft checkpoints.
    """
    problems = get_available_problems(ctx.obj.problem_path)

    table = Table(title="Available Problems")
    table.add_column("Problem", style="cyan")
    table.add_column("Version", justify="center")
    table.add_column("Adapter Type", justify="center")
    table.add_column("Category", style="green")
    table.add_column("# Checkpoints", justify="right")

    problem_rows = []
    for problem_name in sorted(problems.keys()):
        problem = problems[problem_name]

        # Get all checkpoints and filter by draft status
        all_checkpoints = list(problem.iterate_checkpoints())
        non_draft_checkpoints = [
            cp for cp in all_checkpoints if cp.state != "Draft"
        ]

        # Skip problems with only draft checkpoints unless flag is set
        if not include_draft and not non_draft_checkpoints:
            continue

        # Get adapter type
        adapter_type = problem.adapter.type

        problem_rows.append(
            (
                problem.name,
                str(problem.version),
                adapter_type,
                problem.category,
                str(len(all_checkpoints)),
            )
        )

    # Add rows to table
    for row in problem_rows:
        table.add_row(*row)

    console = Console()
    console.print(table)
    console.print(
        f"\n[dim]Total: {len(problem_rows)} "
        f"problem{'s' if len(problem_rows) != 1 else ''}[/dim]"
    )


@app.command("chkpt")
def checkpoint_details(
    ctx: typer.Context,
    problem_name: Annotated[
        str,
        typer.Argument(help="Name of the problem"),
    ],
    checkpoint_num: Annotated[
        int,
        typer.Argument(help="Checkpoint number (1-based)"),
    ],
    jsonl: bool = typer.Option(
        False,
        "--jsonl",
        help="Output in JSONL format instead of rich table",
    ),
    regressions: bool = typer.Option(
        False,
        "--regressions",
        help="Show regression information (original checkpoint and group)",
    ),
) -> None:
    """List groups, cases, and types for a checkpoint of a problem.

    Displays information about all groups in the specified checkpoint,
    including group type and number of test cases. Can optionally show
    regression information and output in JSONL format.
    """
    # Load the problem
    try:
        problem = ProblemConfig.from_yaml(ctx.obj.problem_path / problem_name)
    except FileNotFoundError:
        console = Console()
        console.print(
            f"[red]Error:[/red] Problem '{problem_name}' not found "
            f"at {ctx.obj.problem_path / problem_name}"
        )
        sys.exit(1)
    except Exception as e:
        console = Console()
        console.print(f"[red]Error loading problem:[/red] {e}")
        sys.exit(1)

    # Get the requested checkpoint
    checkpoints = list(problem.iterate_checkpoint_items())
    if checkpoint_num < 1 or checkpoint_num > len(checkpoints):
        console = Console()
        console.print(
            f"[red]Error:[/red] Invalid checkpoint number. "
            f"Must be between 1 and {len(checkpoints)}"
        )
        sys.exit(1)

    checkpoint_name, checkpoint = checkpoints[checkpoint_num - 1]

    # Initialize loader to discover cases
    loader = initialize_loader(problem, checkpoint, use_placeholders=True)
    store = NoOpStore()

    # Collect data for each group
    rows = []
    for group_name, group_config in checkpoint.groups.items():
        # Count cases by iterating through loader
        case_count = 0
        for case, expected in loader(group_config, store):
            case_count += 1

        # Handle type as either enum or string
        group_type = (
            group_config.type.value
            if isinstance(group_config.type, GroupType)
            else group_config.type
        )

        row_data = {
            "group": group_name,
            "type": group_type,
            "cases": case_count,
        }

        # Add regression info if requested
        if regressions:
            is_regression = (
                group_config.type == GroupType.REGRESSION
                if isinstance(group_config.type, GroupType)
                else group_config.type == "Regression"
            )
            if is_regression:
                row_data["original_checkpoint"] = (
                    group_config.original_checkpoint or ""
                )
                row_data["original_group"] = group_config.original_group or ""
            else:
                row_data["original_checkpoint"] = ""
                row_data["original_group"] = ""

        rows.append(row_data)

    # Output results
    if jsonl:
        # Output as JSONL
        for row in rows:
            print(json.dumps(row))
    else:
        # Output as rich table
        console = Console()
        table = Table(
            title=f"{problem.name} - {checkpoint_name}",
            show_header=True,
        )
        table.add_column("Group", style="cyan")
        table.add_column("Type", style="yellow")
        table.add_column("# Cases", justify="right")

        if regressions:
            table.add_column("Original Checkpoint", style="dim")
            table.add_column("Original Group", style="dim")

        # Add rows to table
        for row in rows:
            if regressions:
                table.add_row(
                    row["group"],
                    row["type"],
                    str(row["cases"]),
                    row["original_checkpoint"],
                    row["original_group"],
                )
            else:
                table.add_row(
                    row["group"],
                    row["type"],
                    str(row["cases"]),
                )

        console.print(table)

        # Print summary
        total_cases = sum(r["cases"] for r in rows)
        console.print(
            f"\n[dim]Total: {len(rows)} group"
            f"{'s' if len(rows) != 1 else ''}, "
            f"{total_cases} case{'s' if total_cases != 1 else ''}[/dim]"
        )
