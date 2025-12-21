from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from slop_code.common import PROBLEM_CONFIG_NAME
from slop_code.common import SNAPSHOT_DIR_NAME
from slop_code.entrypoints.commands import common
from slop_code.entrypoints.commands.eval_checkpoint import render_pytest_results
from slop_code.entrypoints.config import loader as config_loader
from slop_code.entrypoints.evaluation.driver import evaluate_checkpoint
from slop_code.entrypoints.evaluation.utils import gather_checkpoint_directories
from slop_code.entrypoints.evaluation.utils import maybe_update_problem_report
from slop_code.entrypoints.evaluation.utils import resolve_problem
from slop_code.logging import get_logger
from slop_code.metrics import RubricProvider

logger = get_logger(__name__)


def register(app: typer.Typer, name: str) -> None:
    app.command(
        name,
        help="Evaluate a single problem directory. Must be in the format `<submission dir>/<checkpoint_name>/<snapshot_dir_name>`.",
    )(evaluate_problem_dir)


def evaluate_problem_dir(
    ctx: typer.Context,
    submission_path: Annotated[
        Path,
        typer.Argument(
            help="Path to the problem directory",
            exists=True,
            dir_okay=True,
            file_okay=False,
        ),
    ],
    problem_name: str | None = typer.Option(
        None,
        "-p",
        "--problem-name",
        help=(
            "Name of the problem. If not provided, the name of the submission "
            "directory will be used. It must have a problem configuration "
            f"file called `{PROBLEM_CONFIG_NAME}`."
        ),
    ),
    env_config: Path | None = typer.Option(
        None,
        "-e",
        "--env-config",
        help=(
            "Path to environment specification configuration. If not provided, "
            "the environment specification configuration will be loaded from "
            "the parent directory."
        ),
    ),
    snapshot_dir: str = typer.Option(
        SNAPSHOT_DIR_NAME,
        "--snapshot-dir",
        help="Name of the directory for snapshots in checkpoints.",
    ),
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
    """Evaluate a single checkpoint for a specific problem."""
    # Validate rubric options
    common.validate_rubric_options(rubric_path, rubric_model)

    if not submission_path.exists():
        typer.echo(
            typer.style(
                f"Submission path '{submission_path}' does not exist.",
                fg=typer.colors.RED,
                bold=True,
            )
        )
        raise typer.Exit(1)
    if env_config is None:
        env_config = submission_path.parent / "environment.yaml"

    # Resolve environment using common utility
    # Note: The original code manually checked existence before calling resolve_environment_spec
    # The common utility handles FileNotFoundError, so we can rely on that.
    environment = config_loader.resolve_environment(env_config)

    logger = common.setup_command_logging(
        log_dir=submission_path,
        verbosity=ctx.obj.verbosity,
        log_file_name="evaluation.log",
    )
    logger = get_logger(__name__)
    logger.info(
        "Evaluating a single problem",
        submission_path=str(submission_path),
        problem_name=problem_name,
        seed=ctx.obj.seed,
        verbose=ctx.obj.verbosity,
    )

    console = Console()
    common.ensure_docker_ready(environment)

    problem = resolve_problem(
        submission_dir=submission_path,
        problem_path=ctx.obj.problem_path,
    )

    results = {}
    for name, submission, snapshot in gather_checkpoint_directories(
        problem=problem,
        submission_dir=submission_path,
        snapshot_dir_name=snapshot_dir,
    ):
        logger.info(
            f"Starting checkpoint '{name}'",
            submission=str(submission),
            snapshot=str(snapshot),
        )
        result = evaluate_checkpoint(
            snapshot=snapshot,
            save_dir=submission,
            checkpoint=problem.checkpoints[name],
            problem=problem,
            environment=environment,
            rubric_path=rubric_path,
            rubric_model=rubric_model,
            rubric_temperature=rubric_temperature,
            rubric_provider=rubric_provider,
        )
        console.rule(f"{problem.name} / {name}")
        render_pytest_results(console, result.report, ctx.obj.verbosity)
        results[name] = (result.report, result.quality)
    maybe_update_problem_report(
        submission_dir=submission_path, summaries=results
    )
