from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

import typer
import yaml
from rich.console import Console

from slop_code import evaluation
from slop_code.common import CHECKPOINT_CONFIG_NAME
from slop_code.common import CHECKPOINT_RESULTS_FILENAME
from slop_code.common import CONFIG_FILENAME
from slop_code.common import PROBLEM_CONFIG_NAME
from slop_code.common import SNAPSHOT_DIR_NAME
from slop_code.common import serialize_path_dict
from slop_code.entrypoints import evaluation as evaluation_entry
from slop_code.entrypoints.commands import common
from slop_code.entrypoints.config import loader as config_loader
from slop_code.entrypoints.evaluation.metrics import update_results_jsonl
from slop_code.entrypoints.utils import display_and_save_summary
from slop_code.evaluation import ProblemConfig
from slop_code.evaluation import get_available_problems
from slop_code.logging import get_logger

logger = get_logger(__name__)


def _is_problem_fully_evaluated(problem_dir: Path) -> bool:
    """Check if all checkpoints in a problem directory have evaluation.json."""
    checkpoint_dirs = sorted(
        d
        for d in problem_dir.iterdir()
        if d.is_dir() and d.name.startswith("checkpoint_")
    )
    if not checkpoint_dirs:
        return False
    return all((d / "evaluation.json").exists() for d in checkpoint_dirs)


def _write_problem_and_checkpoint_configs(
    problem_dir: Path, source_config: ProblemConfig
) -> None:
    """Write evaluation configs into the run directory.

    This makes re-evaluation/resume self-contained and ensures future config
    comparisons and report generation reflect the most recent source configs.
    """
    try:
        problem_payload = serialize_path_dict(
            source_config.model_dump(mode="json")
        )
        with (problem_dir / PROBLEM_CONFIG_NAME).open("w") as f:
            yaml.dump(problem_payload, f, indent=2, sort_keys=True)
    except OSError:
        logger.warning(
            "Failed to write problem.yaml into run directory",
            problem_dir=str(problem_dir),
        )

    for checkpoint_name, checkpoint in source_config.iterate_checkpoint_items():
        checkpoint_dir = problem_dir / checkpoint_name
        if not checkpoint_dir.exists() or not checkpoint_dir.is_dir():
            continue
        try:
            checkpoint_payload = serialize_path_dict(
                checkpoint.model_dump(mode="json")
            )
            with (checkpoint_dir / CHECKPOINT_CONFIG_NAME).open("w") as f:
                yaml.dump(checkpoint_payload, f, indent=2, sort_keys=True)
        except OSError:
            logger.warning(
                "Failed to write checkpoint.yaml into run directory",
                problem_dir=str(problem_dir),
                checkpoint_name=checkpoint_name,
            )


def _extract_eval_relevant_fields(config: dict[str, Any]) -> dict[str, Any]:
    """Extract fields from a problem config that affect evaluation."""
    checkpoints_summary = {}
    for name, chkpt in config.get("checkpoints", {}).items():
        if isinstance(chkpt, dict):
            checkpoints_summary[name] = {
                "version": chkpt.get("version"),
                "groups": sorted(chkpt.get("groups", {}).keys()),
            }
    return {
        "version": config.get("version"),
        "adapter": config.get("adapter"),
        "static_assets": config.get("static_assets"),
        "checkpoints": checkpoints_summary,
    }


def _has_evaluation_config_changed(
    problem_dir: Path,
    source_config: ProblemConfig,
) -> bool:
    """Check if evaluation-relevant config fields have changed.

    Compares the saved problem.yaml in the agent run directory against
    the current source problem config. Returns True if fields that affect
    evaluation (adapter, static_assets, version, checkpoint groups) differ.
    """
    saved_config_path = problem_dir / PROBLEM_CONFIG_NAME
    if not saved_config_path.exists():
        # No saved config means we can't compare - treat as changed
        return True

    try:
        with saved_config_path.open("r") as f:
            saved_config = yaml.safe_load(f)
    except (OSError, yaml.YAMLError):
        # If we can't load the saved config, treat as changed
        return True

    saved_fields = _extract_eval_relevant_fields(saved_config)
    source_fields = _extract_eval_relevant_fields(
        source_config.model_dump(mode="json")
    )

    return saved_fields != source_fields


def register(app: typer.Typer, name: str) -> None:
    app.command(
        name,
        help=(
            "Evaluate a directory of agent inference results. Must be in the "
            "format <agent_dir>/<problem>/<checkpoint>/<snapshot>."
        ),
    )(evaluate_agent_run)


def evaluate_agent_run(
    ctx: typer.Context,
    agent_run_dir: Annotated[
        Path,
        typer.Argument(
            help="Path to the inference directory",
            exists=True,
            dir_okay=True,
            file_okay=False,
        ),
    ],
    problem_names: list[str] = typer.Option(
        [],
        "--problem",
        help="Name of the specific problems to run",
    ),
    pass_policy: evaluation.PassPolicy = typer.Option(
        evaluation.PassPolicy.ALL_CASES,
        "--pass-policy",
        help="Policy to determine if the checkpoint passed",
    ),
    env_config: Path | None = typer.Option(
        None,
        "-e",
        "--env-config",
        help="Path to environment specification configuration",
    ),
    live_progress: bool = typer.Option(
        False,
        "--live-progress/--no-live-progress",
        help="Enable live progress display",
    ),
    num_workers: int = typer.Option(
        1,
        "--num-workers",
        "-proc",
        help="Number of parallel evaluation workers (1 for sequential)",
    ),
    overwrite: bool = typer.Option(
        False,
        "--overwrite",
        help="Re-evaluate problems even if they already have evaluation results",
    ),
) -> None:
    """Evaluate a directory of attempts against a problem specification."""

    if not agent_run_dir.exists():
        typer.echo(
            typer.style(
                f"Submission path '{agent_run_dir}' does not exist.",
                fg=typer.colors.RED,
                bold=True,
            )
        )
        raise typer.Exit(1)

    if not (agent_run_dir / "environment.yaml").exists() and env_config is None:
        typer.echo(
            typer.style(
                f"Environment configuration file '{agent_run_dir / 'environment.yaml'}' does not exist.",
                fg=typer.colors.RED,
                bold=True,
            )
        )
        raise typer.Exit(1)
    env_path = env_config or (agent_run_dir / "environment.yaml")

    environment = config_loader.resolve_environment(env_path)

    console = Console()
    common.setup_command_logging(
        log_dir=agent_run_dir,
        verbosity=ctx.obj.verbosity,
        log_file_name="evaluation.log",
        add_multiproc_info=num_workers > 1,
        console=console,
    )
    logger = get_logger(__name__)
    logger.info(
        "Evaluating a directory of submissions",
        submission_path=str(agent_run_dir),
        problem_names=problem_names,
        env_config=str(env_path),
        pass_policy=pass_policy.value,
    )

    common.ensure_docker_ready(environment)

    valid_problems = get_available_problems(ctx.obj.problem_path)
    problems_to_eval = []
    # Only auto-skip when no explicit problems specified and overwrite=False
    auto_skip_evaluated = not problem_names and not overwrite
    skipped_count = 0
    for problem_name in problem_names or valid_problems.keys():
        if problem_name not in valid_problems:
            logger.warning(
                "Problem not found in available problems",
                problem_name=problem_name,
            )
            continue
        problem_dir = agent_run_dir / problem_name
        if not problem_dir.exists():
            logger.debug(
                "Problem directory does not exist",
                problem_dir=str(problem_dir),
            )
            continue
        if auto_skip_evaluated and _is_problem_fully_evaluated(problem_dir):
            source_config = valid_problems[problem_name]
            if _has_evaluation_config_changed(problem_dir, source_config):
                logger.info(
                    "Re-evaluating due to config change",
                    problem_name=problem_name,
                )
            else:
                logger.info(
                    "Skipping already-evaluated problem",
                    problem_name=problem_name,
                )
                skipped_count += 1
                continue
        logger.info(
            "Adding problem to evaluation",
            problem_name=problem_name,
            problem_dir=str(problem_dir),
        )
        source_problem = valid_problems[problem_name]
        _write_problem_and_checkpoint_configs(problem_dir, source_problem)
        problems_to_eval.append((source_problem, problem_dir))

    if not problems_to_eval:
        if skipped_count > 0:
            logger.info(
                f"No problems to evaluate ({skipped_count} already evaluated, "
                "use --overwrite to re-evaluate)"
            )
        else:
            logger.error("No problems to evaluate")
        raise typer.Exit(1)
    if skipped_count > 0:
        logger.info(
            f"Evaluating {len(problems_to_eval):,} problems "
            f"({skipped_count} skipped as already evaluated)"
        )
    else:
        logger.info(f"Evaluating {len(problems_to_eval):,} problems")

    _, eval_summary = evaluation_entry.evaluate(
        problems=problems_to_eval,
        environment=environment,
        snapshot_dir_name=SNAPSHOT_DIR_NAME,
        live_progress=live_progress,
        console=console,
        num_workers=num_workers,
    )
    logger.info(
        "Evaluation complete",
        successful=eval_summary.successful,
        failed=eval_summary.failed,
    )

    report_file = agent_run_dir / CHECKPOINT_RESULTS_FILENAME
    report_errors: list[tuple[str, str]] = []
    all_reports: list[dict] = []
    for p_dir in agent_run_dir.iterdir():
        if not p_dir.is_dir():
            continue
        typer.echo(f"Processing problem {p_dir}")
        problem_name = p_dir.name
        try:
            problem = ProblemConfig.from_yaml(
                ctx.obj.problem_path / problem_name
            )
        except FileNotFoundError:
            logger.error(
                "Problem configuration not found during report generation",
                problem_name=problem_name,
            )
            report_errors.append((problem_name, "Problem config not found"))
            continue
        except Exception as e:
            logger.error(
                "Error loading problem configuration",
                problem_name=problem_name,
                error=str(e),
            )
            report_errors.append((problem_name, str(e)))
            continue

        reports, errors = evaluation_entry.create_problem_reports(
            p_dir, problem
        )
        all_reports.extend(reports)
        for checkpoint_name, error_msg in errors:
            report_errors.append(
                (f"{problem_name}/{checkpoint_name}", error_msg)
            )

    update_results_jsonl(report_file, all_reports)

    typer.echo(f"Reports written to {report_file}")

    # Display evaluation summary at end
    if eval_summary.failed > 0:
        typer.echo(
            typer.style(
                f"\n{eval_summary.format_summary()}",
                fg=typer.colors.YELLOW,
                bold=True,
            )
        )
    else:
        typer.echo(
            typer.style(
                f"\nAll {eval_summary.total_checkpoints} checkpoints evaluated successfully!",
                fg=typer.colors.GREEN,
                bold=True,
            )
        )

    typer.echo(
        typer.style(
            f"\n{len(report_errors)} error(s) during report generation:",
            fg=typer.colors.YELLOW,
            bold=True,
        )
    )
    for identifier, error_msg in report_errors:
        typer.echo(
            typer.style(f"  - {identifier}: {error_msg}", fg=typer.colors.RED)
        )
    with (agent_run_dir / CONFIG_FILENAME).open("r") as f:
        config = yaml.safe_load(f)
    # Display and save summary statistics
    display_and_save_summary(report_file, agent_run_dir, config, console)
