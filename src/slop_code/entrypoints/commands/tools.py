from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from slop_code.entrypoints.commands import common
from slop_code.entrypoints.config import loader as config_loader
from slop_code.evaluation.pytest_runner import run_checkpoint_pytest
from slop_code.logging import get_logger

logger = get_logger(__name__)

app = typer.Typer(
    help="Utilities for launching interactive tools (Streamlit apps).",
)


@app.command(
    "run-case",
    help="Run pytest tests for a snapshot and output raw stdout.",
)
def run_case(
    ctx: typer.Context,
    snapshot_dir: Annotated[
        Path,
        typer.Option(
            "-s",
            "--snapshot-dir",
            exists=True,
            dir_okay=True,
            file_okay=False,
            help="Path to snapshot directory.",
        ),
    ],
    problem_name: Annotated[
        str,
        typer.Option(
            "-p",
            "--problem",
            help="Name of the problem.",
        ),
    ],
    checkpoint_num: Annotated[
        int,
        typer.Option(
            "-c",
            "--checkpoint",
            help="Checkpoint number to evaluate.",
        ),
    ],
    env_config: Annotated[
        Path,
        typer.Option(
            "-e",
            "--env-config",
            help="Path to environment specification configuration.",
            exists=True,
            dir_okay=False,
            file_okay=True,
        ),
    ],
    tests: Annotated[
        list[str] | None,
        typer.Option(
            "-t",
            "--test",
            help="Pytest test file or nodeid to run (repeatable).",
        ),
    ] = None,
    case: Annotated[
        str | None,
        typer.Option(
            "--case",
            help="Pytest -k expression to select tests.",
        ),
    ] = None,
    pytest_args: Annotated[
        list[str] | None,
        typer.Option(
            "--pytest-arg",
            help="Extra args to pass to pytest (repeatable).",
        ),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Output JSON report instead of raw pytest stdout.",
        ),
    ] = False,
    full: Annotated[
        bool,
        typer.Option(
            "--full",
            help="Include the full pytest report payload (JSON only).",
        ),
    ] = False,
) -> None:
    problem_path = ctx.obj.problem_path / problem_name
    problem = common.load_problem_config_or_exit(
        problem_path,
        problem_name,
    )

    ordered_checkpoints = list(problem.iterate_checkpoint_items())
    if checkpoint_num < 1 or checkpoint_num > len(ordered_checkpoints):
        typer.echo(
            typer.style(
                f"Checkpoint number {checkpoint_num} is out of range for "
                f"problem {problem_name}. Must be between 1 and "
                f"{len(ordered_checkpoints)}.",
                fg=typer.colors.RED,
                bold=True,
            )
        )
        raise typer.Exit(1)

    checkpoint_name, checkpoint = ordered_checkpoints[checkpoint_num - 1]
    logger.info(
        "Running pytest case selection",
        snapshot_dir=str(snapshot_dir),
        problem_name=problem_name,
        checkpoint_name=checkpoint_name,
    )

    environment = config_loader.resolve_environment(env_config)
    common.ensure_docker_ready(environment)

    selected_tests = [test for test in (tests or []) if test.strip()]
    test_files = selected_tests or None

    extra_pytest_args = [arg for arg in (pytest_args or []) if arg.strip()]
    if case is not None and case.strip():
        extra_pytest_args.extend(["-k", case.strip()])
    if not extra_pytest_args:
        extra_pytest_args = None

    results = run_checkpoint_pytest(
        submission_path=snapshot_dir,
        problem=problem,
        checkpoint=checkpoint,
        env_spec=environment,
        test_files=test_files,
        pytest_args=extra_pytest_args,
    )

    if full or json_output:
        payload = (
            results.model_dump(mode="json")
            if full
            else [test.model_dump(mode="json") for test in results.tests]
        )
        typer.echo(json.dumps(payload, indent=2))
        return

    typer.echo(results.pytest_stdout or "", nl=False)
