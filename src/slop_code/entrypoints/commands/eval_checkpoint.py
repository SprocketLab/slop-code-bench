from __future__ import annotations

import json
import re
from collections import Counter
from collections import defaultdict
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


def parse_test_id(test_id: str) -> tuple[str, str | None]:
    """Extract base name and param from test_id like 'test_foo[bar]'."""
    name = test_id.split("::")[-1] if "::" in test_id else test_id
    match = re.match(r"^(.+?)\[(.+)\]$", name)
    if match:
        return match.group(1), match.group(2)
    return name, None


def _status_icon(status: str) -> str:
    """Return colored status icon for test status."""
    if status == "passed":
        return "[green]✓[/green]"
    if status == "skipped":
        return "[yellow]○[/yellow]"
    return "[red]✗[/red]"


def _render_tests_tree(
    console: Console, tests: list, indent: str = "  "
) -> None:
    """Render tests in tree-style hierarchy, grouping parametrized tests."""
    # Group tests by base name, preserving order
    grouped: dict[str, list[tuple[str | None, object]]] = defaultdict(list)
    order: list[str] = []
    for test in tests:
        base, param = parse_test_id(test.id)
        if base not in grouped:
            order.append(base)
        grouped[base].append((param, test))

    for base_name in order:
        items = grouped[base_name]
        # Get group type from first test
        group_type = items[0][1].group_type.value

        if len(items) == 1 and items[0][0] is None:
            # Single non-parametrized test
            _, test = items[0]
            icon = _status_icon(test.status)
            console.print(f"{indent}{base_name} ({group_type}) {icon}")
        else:
            # Parametrized tests - render as tree
            console.print(f"{indent}{base_name} ({group_type})")
            for i, (param, test) in enumerate(items):
                is_last = i == len(items) - 1
                connector = "└──" if is_last else "├──"
                icon = _status_icon(test.status)
                param_display = param if param else "(no param)"
                console.print(f"{indent}{connector} {param_display} {icon}")


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

    console.print("\n[bold]Execution Summary[/bold]")
    console.print(
        f"{results.problem_name} / {results.checkpoint_name} "
        f"({results.duration:.1f}s)"
    )
    console.print("[bold]Status Summary[/bold]")
    if status_parts:
        console.print(", ".join(status_parts))
    else:
        console.print("[dim]No tests executed[/dim]")

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
        console.print("\n[bold]Group Summary[/bold]")
        console.print(group_table)

    # Show failed tests only (unless verbose)
    failed_tests = [
        test for test in results.tests if test.status in {"failed", "error"}
    ]

    if verbosity <= 1 and failed_tests:
        console.print("\n[bold]Test Results[/bold]")
        console.print(
            f"[red bold]Failed Tests ({len(failed_tests)}):[/red bold]"
        )
        _render_tests_tree(console, failed_tests)
    elif verbosity > 1:
        console.print("\n[bold]Test Results[/bold]")
        console.print(f"[bold]All Tests ({total}):[/bold]")
        sorted_tests = sorted(
            results.tests, key=lambda x: (x.group_type.value, x.status, x.id)
        )
        _render_tests_tree(console, sorted_tests)


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
    checkpoint: Annotated[
        str,
        typer.Option(
            "-c",
            "--checkpoint",
            help="Checkpoint index (e.g., '1') or name (e.g., 'checkpoint_1').",
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
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Output correctness results as JSON.",
    ),
) -> None:
    if isinstance(json_output, typer.models.OptionInfo):
        json_output = bool(json_output.default)

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
    checkpoint_names = [name for name, _ in ordered_checkpoints]

    # Resolve checkpoint: accept either index (e.g., "1") or name (e.g., "checkpoint_1")
    if checkpoint.isdigit():
        checkpoint_num = int(checkpoint)
        if checkpoint_num < 1 or checkpoint_num > len(ordered_checkpoints):
            typer.echo(
                typer.style(
                    f"Checkpoint index {checkpoint_num} is out of range for problem {problem_name}. "
                    f"Must be between 1 and {len(ordered_checkpoints)}.",
                    fg=typer.colors.RED,
                    bold=True,
                )
            )
            raise typer.Exit(1)
        checkpoint_name, checkpoint_config = ordered_checkpoints[
            checkpoint_num - 1
        ]
    elif checkpoint in checkpoint_names:
        checkpoint_idx = checkpoint_names.index(checkpoint)
        checkpoint_num = checkpoint_idx + 1
        checkpoint_name, checkpoint_config = ordered_checkpoints[checkpoint_idx]
    else:
        typer.echo(
            typer.style(
                f"Invalid checkpoint '{checkpoint}' for problem {problem_name}. "
                f"Must be an index (1-{len(ordered_checkpoints)}) or name ({', '.join(checkpoint_names)}).",
                fg=typer.colors.RED,
                bold=True,
            )
        )
        raise typer.Exit(1)

    save_dir = utils.ensure_dir_exists(save_dir, create=True)
    quiet = getattr(ctx.obj, "quiet", False)
    logger = common.setup_command_logging(
        log_dir=save_dir,
        verbosity=ctx.obj.verbosity,
        log_file_name="evaluation.log",
        quiet=quiet,
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
        checkpoint=checkpoint_config,
        problem=problem,
        environment=environment,
        rubric_path=rubric_path,
        rubric_model=rubric_model,
        rubric_temperature=rubric_temperature,
        rubric_provider=rubric_provider,
    )
    if json_output:
        typer.echo(json.dumps(report.report.to_output_dict(), indent=2))
    else:
        console = Console()
        render_pytest_results(console, report.report, ctx.obj.verbosity)
