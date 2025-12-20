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
    # Compact header
    status_counts = Counter(test.status for test in results.tests)
    passed = status_counts.get("passed", 0)
    failed = status_counts.get("failed", 0) + status_counts.get("error", 0)
    skipped = status_counts.get("skipped", 0)
    total = len(results.tests)

    # One-line status
    status_parts = []
    if passed:
        status_parts.append(f"[green]{passed} passed[/green]")
    if failed:
        status_parts.append(f"[red]{failed} failed[/red]")
    if skipped:
        status_parts.append(f"[yellow]{skipped} skipped[/yellow]")

    console.print(
        f"\n[bold]{results.problem_name}[/bold] / {results.checkpoint_name} "
        f"— {', '.join(status_parts)} ({results.duration:.1f}s)"
    )

    if results.infrastructure_failure:
        console.print("[red bold]⚠ Infrastructure failure detected[/red bold]")

    # Group summary table (compact)
    group_table = Table(show_header=True, box=None, padding=(0, 2))
    group_table.add_column("Group", style="dim")
    group_table.add_column("Result", justify="right")

    total_passed = 0
    total_tests = 0
    for group_type in GroupType:
        group_passed = results.pass_counts.get(group_type, 0)
        group_total = results.total_counts.get(group_type, 0)
        if group_total == 0:
            continue
        total_passed += group_passed
        total_tests += group_total
        if group_passed == group_total:
            result_str = f"[green]{group_passed}/{group_total}[/green]"
        else:
            result_str = f"[red]{group_passed}/{group_total}[/red]"
        group_table.add_row(group_type.value, result_str)

    if total_tests > 0:
        console.print(group_table)

    # Show failed tests only (unless verbose)
    failed_tests = [
        test
        for test in results.tests
        if test.status in {"failed", "error"}
    ]

    if failed_tests:
        console.print(f"\n[red bold]Failed Tests ({len(failed_tests)}):[/red bold]")
        for test_result in failed_tests:
            # Extract just the test name from nodeid (includes param like [case1])
            test_name = test_result.id.split("::")[-1] if "::" in test_result.id else test_result.id
            console.print(f"  [red]✗[/red] {test_name}")

    # Verbose mode: show all tests
    if verbosity > 1:
        console.print(f"\n[bold]All Tests ({total}):[/bold]")
        for test_result in sorted(
            results.tests, key=lambda x: (x.group_type.value, x.status, x.id)
        ):
            test_name = test_result.id.split("::")[-1] if "::" in test_result.id else test_result.id
            if test_result.status == "passed":
                console.print(f"  [green]✓[/green] {test_name}")
            elif test_result.status == "skipped":
                console.print(f"  [yellow]○[/yellow] {test_name}")
            else:
                console.print(f"  [red]✗[/red] {test_name}")


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
