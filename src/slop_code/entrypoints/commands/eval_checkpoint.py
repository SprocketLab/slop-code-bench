from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.json import JSON
from rich.table import Table

from slop_code.entrypoints import utils
from slop_code.entrypoints.commands import common
from slop_code.entrypoints.config import loader as config_loader
from slop_code.entrypoints.evaluation.driver import evaluate_checkpoint
from slop_code.logging import get_logger
from slop_code.metrics import RubricProvider

logger = get_logger(__name__)


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
    group_scores = defaultdict(list)
    rows = []
    overview_rows = []
    for case_report in report.report.reports:
        group_name = case_report.group
        group_scores[group_name].append(case_report.calculate_score())

        diff = {}
        stderr = case_report.results.get("stderr", None)
        if stderr is not None:
            stderr = stderr.actual
        for attr_result in case_report.get_verified_attributes():
            pretty_actual = attr_result.actual
            if not isinstance(pretty_actual, str):
                pretty_actual = str(pretty_actual)

            pretty_expected = attr_result.expected

            if not isinstance(pretty_expected, str):
                pretty_expected = str(pretty_expected)
            diff_str = attr_result.diff

            if not isinstance(diff_str, str):
                diff_str = str(diff_str)

            diff[attr_result.attribute] = {
                "correct": attr_result.is_correct,
                "actual": pretty_actual[:256],
                "expected": pretty_expected[:256],
                "diff": diff_str,
                "weight": attr_result.weight,
            }
        if "stderr" not in diff:
            diff["stderr"] = str(stderr)[:256]

        case_name = f"{case_report.group}/{case_report.id}"
        overview_rows.append(
            (
                case_name,
                f"{case_report.calculate_score():.2f}",
                JSON(json.dumps(diff)),
            )
        )

    console = Console()
    table = Table(title="Case Results", show_lines=True, show_header=True)

    table.add_column("Case", width=32)
    table.add_column("Score", width=8)
    table.add_column("diff", overflow="fold", no_wrap=False)
    for row in sorted(overview_rows, key=lambda x: (x[0], x[2])):
        table.add_row(*row)
    console.print(table)

    key_types = defaultdict(set)
    for row in rows:
        for k, v in row.items():
            if k in ["results"]:
                for sub_v in v:
                    for kk, vv in sub_v.items():
                        key_types[f"{k}-{kk}"].add(type(vv).__name__)
            else:
                key_types[k].add(type(v).__name__)

    table = Table(title="Group Scores")
    table.add_column("Group")
    table.add_column("Num Passed")
    table.add_column("Num Cases")
    table.add_column("Score")
    total_score = []
    for group, score in group_scores.items():
        mean_score = sum(score) / len(score)
        total_score.extend(score)
        num_passed = sum(1 for score in score if math.isclose(score, 1.0))
        table.add_row(
            group,
            f"{num_passed}",
            f"{len(score)}",
            f"{mean_score:.2%}",
        )
    table.add_section()
    table.add_row(
        "Total",
        f"{sum(1 for score in total_score if math.isclose(score, 1.0))}",
        f"{len(total_score)}",
        f"{sum(total_score) / len(total_score):.2%}",
    )
    console.print(table)
