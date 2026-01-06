"""Command to generate a registry JSONL file for all problems."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from slop_code.evaluation.config import get_available_problems
from slop_code.logging import setup_logging


def register(app: typer.Typer, name: str):
    """Register the make-registry command."""
    app.command(
        name,
        help="Generate a registry.jsonl file with problem metadata",
    )(make_registry)


def make_registry(
    ctx: typer.Context,
    output: Annotated[
        Path,
        typer.Option(
            "-o",
            "--output",
            help="Output JSONL file path",
        ),
    ],
    problem: Annotated[
        list[str] | None,
        typer.Option(
            "--problem",
            help="Filter to specific problem name(s) (repeatable)",
        ),
    ] = None,
) -> None:
    """Generate a registry JSONL file containing metadata for all problems.

    Each line in the output file is a JSON object with problem metadata including
    name, tags, checkpoints with their specs, etc. This format is used by the
    slopcodebench.github.io website.

    Examples:

        # Generate registry for all problems

        slop-code utils make-registry -o registry.jsonl

        # Generate registry for specific problems only

        slop-code utils make-registry -o registry.jsonl --problem file_backup --problem code_search
    """
    logger = setup_logging(
        log_dir=None,
        verbosity=ctx.obj.verbosity,
    )

    problem_path: Path = ctx.obj.problem_path
    problems = get_available_problems(problem_path)

    if problem:
        problems = {k: v for k, v in problems.items() if k in problem}

    if not problems:
        typer.echo(typer.style("No problems found", fg=typer.colors.YELLOW))
        raise typer.Exit(0)

    typer.echo(f"Generating registry for {len(problems)} problem(s)")

    entries = []
    for problem_name, config in sorted(problems.items()):
        logger.debug("Processing problem", problem=problem_name)

        checkpoints = []
        for (
            checkpoint_name,
            checkpoint_config,
        ) in config.iterate_checkpoint_items():
            try:
                spec = config.get_checkpoint_spec(checkpoint_name)
            except FileNotFoundError:
                logger.warning(
                    "Checkpoint spec not found",
                    problem=problem_name,
                    checkpoint=checkpoint_name,
                )
                spec = ""

            checkpoints.append(
                {
                    "checkpoint_name": checkpoint_name,
                    "spec": spec,
                    "version": checkpoint_config.version,
                    "state": checkpoint_config.state,
                }
            )

        entry = {
            "problem_name": config.name,
            "tags": config.tags,
            "version": config.version,
            "author": config.author,
            "category": config.category,
            "entry_point": config.entry_file,
            "adapter_type": "cli",
            "difficulty": config.difficulty,
            "description": config.description,
            "checkpoints": checkpoints,
        }
        entries.append(entry)

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")

    typer.echo(
        typer.style(
            f"Wrote {len(entries)} entries to {output}", fg=typer.colors.GREEN
        )
    )
