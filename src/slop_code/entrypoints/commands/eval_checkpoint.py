from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from slop_code.entrypoints import utils
from slop_code.entrypoints.commands import common
from slop_code.entrypoints.config import loader as config_loader
from slop_code.entrypoints.evaluation.driver import evaluate_checkpoint
from slop_code.evaluation import GroupType
from slop_code.logging import get_logger
from slop_code.metrics import RubricProvider

logger = get_logger(__name__)

EXIT_CODE_MEANINGS = {
    0: "all tests passed",
    1: "tests failed",
    2: "pytest interrupted",
    3: "pytest internal error",
    4: "pytest usage error",
    5: "no tests collected",
}


def render_pytest_results(
    console: Console,
    results,
    verbosity: int,
) -> None:
    summary = Table(title="Execution Summary")
    summary.add_column("Field", width=22)
    summary.add_column("Value", overflow="fold")
    summary.add_row("Problem", results.problem_name)
    summary.add_row("Checkpoint", results.checkpoint_name)
    summary.add_row("Duration (s)", f"{results.duration:.2f}")
    summary.add_row("Entrypoint", results.entrypoint)
    summary.add_row("Pytest Exit Code", str(results.pytest_exit_code))
    summary.add_row(
        "Exit Meaning",
        EXIT_CODE_MEANINGS.get(results.pytest_exit_code, "unknown"),
    )
    summary.add_row("Tests Collected", str(results.pytest_collected))
    summary.add_row(
        "Infrastructure Failure",
        "yes" if results.infrastructure_failure else "no",
    )
    console.print(summary)

    status_counts = Counter(test.status for test in results.tests)
    status_table = Table(title="Status Summary")
    status_table.add_column("Status")
    status_table.add_column("Count", justify="right")
    for status in ["passed", "failed", "error", "skipped"]:
        status_table.add_row(status, str(status_counts.get(status, 0)))
    console.print(status_table)

    group_table = Table(title="Group Summary")
    group_table.add_column("Group")
    group_table.add_column("Num Passed", justify="right")
    group_table.add_column("Num Tests", justify="right")
    group_table.add_column("Pass Rate", justify="right")
    total_passed = 0
    total_tests = 0
    for group_type in GroupType:
        passed = results.pass_counts.get(group_type, 0)
        total = results.total_counts.get(group_type, 0)
        total_passed += passed
        total_tests += total
        pass_rate = f"{(passed / total):.2%}" if total else "n/a"
        group_table.add_row(
            group_type.value,
            str(passed),
            str(total),
            pass_rate,
        )
    group_table.add_section()
    total_rate = f"{(total_passed / total_tests):.2%}" if total_tests else "n/a"
    group_table.add_row(
        "Total",
        str(total_passed),
        str(total_tests),
        total_rate,
    )
    console.print(group_table)

    failed_tests = [
        test
        for test in results.tests
        if test.status in {"failed", "error"}
    ]
    show_tests = verbosity > 0 or failed_tests or results.infrastructure_failure

    if show_tests:
        tests_table = Table(title="Test Results", show_lines=True)
        tests_table.add_column("Test", width=40, overflow="fold")
        tests_table.add_column("Status", width=10)
        tests_table.add_column("Group", width=14)
        tests_table.add_column("Duration(ms)", width=12, justify="right")
        tests_table.add_column("Failure", overflow="fold")
        for test_result in sorted(
            results.tests, key=lambda x: (x.group_type.value, x.status, x.id)
        ):
            test_label = test_result.id
            if test_result.file_path and test_result.file_path not in test_label:
                test_label = f"{test_result.file_path}::{test_label}"
            tests_table.add_row(
                test_label,
                test_result.status,
                test_result.group_type.value,
                f"{test_result.duration_ms:.2f}",
                test_result.failure_message or "",
            )
        console.print(tests_table)

    if failed_tests:
        failure_table = Table(title="Failure Details", show_lines=True)
        failure_table.add_column("Test", width=40, overflow="fold")
        failure_table.add_column("Group", width=14)
        failure_table.add_column("Status", width=10)
        failure_table.add_column("Message", overflow="fold")
        for test_result in failed_tests:
            test_label = test_result.id
            if test_result.file_path and test_result.file_path not in test_label:
                test_label = f"{test_result.file_path}::{test_label}"
            failure_table.add_row(
                test_label,
                test_result.group_type.value,
                test_result.status,
                test_result.failure_message or "",
            )
        console.print(failure_table)


def register(app: typer.Typer, name: str) -> None:
    app.command(
        name,
        help="Evaluate a single snapshot directory. The only assumption we make is that the specified directory IS the snapshot of code.",
    )(evaluate_snapshot)


def evaluate_snapshot(
    ctx: typer.Context,
    snapshot_dir: Annotated[
        Path,
        typer.Argument(
            exists=True,
            dir_okay=True,
            file_okay=False,
        ),
    ],
    save_dir: Annotated[
        Path,
        typer.Option(
            "-o",
            "--save-dir",
            help="Path to save the evaluation results",
        ),
    ],
    problem_name: Annotated[
        str,
        typer.Option(
            "-p",
            "--problem-name",
            help="Name of the problem. If not provided, the name of the snapshot directory will be used. It must have a problem configuration file.",
        ),
    ],
    checkpoint_num: Annotated[
        int,
        typer.Option(
            "-c",
            "--checkpoint-num",
            help="Number of the checkpoint.",
        ),
    ],
    env_config: Annotated[
        Path,
        typer.Option(
            "-e",
            "--env-config",
            help="Path to environment specification configuration",
            exists=True,
            dir_okay=False,
            file_okay=True,
        ),
    ],
    rubric_path: Path | None = typer.Option(
        None,
        "--rubric",
        help="Path to rubric JSONL file for code quality grading.",
    ),
    rubric_model: str | None = typer.Option(
        None,
        "--rubric-model",
        help="Model ID for rubric grading (required if --rubric is set).",
    ),
    rubric_temperature: float = typer.Option(
        0.0,
        "--rubric-temperature",
        help="Sampling temperature for rubric grading (default: 0).",
    ),
    rubric_provider: RubricProvider = typer.Option(
        RubricProvider.OPENROUTER,
        "--rubric-provider",
        help="LLM provider for rubric grading",
        case_sensitive=False,
    ),
) -> None:
    # Validate rubric options
    common.validate_rubric_options(rubric_path, rubric_model)

    problem_path = ctx.obj.problem_path / problem_name
    problem = common.load_problem_config_or_exit(problem_path)

    environment = config_loader.resolve_environment(env_config)

    if save_dir == snapshot_dir:
        typer.echo(
            typer.style(
                "Save directory cannot be the same as the snapshot directory.",
                fg=typer.colors.RED,
                bold=True,
            )
        )
        raise typer.Exit(1)

    ordered_checkpoints = list(problem.iterate_checkpoint_items())
    if checkpoint_num < 1 or checkpoint_num > len(ordered_checkpoints):
        typer.echo(
            typer.style(
                f"Checkpoint number {checkpoint_num} is out of range for problem {problem_name}. Must be between 1 and {len(ordered_checkpoints)}.",
                fg=typer.colors.RED,
                bold=True,
            )
        )
        raise typer.Exit(1)

    checkpoint_name, checkpoint = ordered_checkpoints[checkpoint_num - 1]

    save_dir = utils.ensure_dir_exists(save_dir, create=True)
    logger = common.setup_command_logging(
        log_dir=save_dir,
        verbosity=ctx.obj.verbosity,
        log_file_name="evaluation.log",
    )
    logger.info(
        "Evaluating a single snapshot",
        snapshot_dir=str(snapshot_dir),
        save_dir=str(save_dir),
        problem_name=problem_name,
        checkpoint_num=checkpoint_num,
        env_config=str(env_config),
    )

    common.ensure_docker_ready(environment)

    report = evaluate_checkpoint(
        snapshot=snapshot_dir,
        save_dir=save_dir,
        checkpoint=checkpoint,
        problem=problem,
        environment=environment,
        rubric_path=rubric_path,
        rubric_model=rubric_model,
        rubric_temperature=rubric_temperature,
        rubric_provider=rubric_provider,
    )
    console = Console()
    render_pytest_results(console, report.report, ctx.obj.verbosity)
