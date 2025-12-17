from __future__ import annotations

import shutil
from pathlib import Path
from typing import cast

import typer
import yaml
from rich.console import Console

from slop_code.agent_runner.credentials import API_KEY_STORE
from slop_code.agent_runner.credentials import CredentialNotFoundError
from slop_code.agent_runner.registry import build_agent_config
from slop_code.common import CHECKPOINT_RESULTS_FILENAME
from slop_code.common import CONFIG_FILENAME
from slop_code.common import ENV_CONFIG_NAME
from slop_code.common import RUN_INFO_FILENAME
from slop_code.common import serialize_path_dict
from slop_code.common.llms import ModelCatalog
from slop_code.entrypoints import evaluation as evaluation_entry
from slop_code.entrypoints import problem_runner
from slop_code.entrypoints import utils
from slop_code.entrypoints.commands import common
from slop_code.entrypoints.config import load_run_config
from slop_code.entrypoints.config import loader as config_loader
from slop_code.entrypoints.evaluation.metrics import update_results_jsonl
from slop_code.entrypoints.utils import display_and_save_summary
from slop_code.evaluation import ProblemConfig
from slop_code.execution import EnvironmentSpecType
from slop_code.execution import docker_runtime
from slop_code.logging import get_logger

logger = get_logger(__name__)


def _problem_is_done(run_dir: Path, problem_name: str) -> bool:
    """Return True if the problem appears completed in the run directory.

    We consider a problem "done" if it has a run_info.yaml and its summary
    state is "completed".
    """
    run_info_path = run_dir / problem_name / RUN_INFO_FILENAME
    if not run_info_path.exists():
        return False
    try:
        with run_info_path.open("r") as f:
            data = yaml.safe_load(f)
    except OSError:
        return False
    if not isinstance(data, dict):
        return False
    summary = data.get("summary")
    if not isinstance(summary, dict):
        return False
    state = summary.get("state")
    if state is None:
        return False
    return str(state).strip().lower() == "completed"


def _clear_problem_outputs(run_dir: Path, problem_name: str) -> None:
    """Remove any prior outputs for a problem (but keep the run dir)."""
    shutil.rmtree(run_dir / problem_name, ignore_errors=True)


def register(app: typer.Typer, name: str) -> None:
    app.command(
        name,
        help="Runs a model with an agent on the benchmark. Uses unified config system with hydra-style overrides.",
    )(run_agent)


def _report_results(results: list[problem_runner.TaskResult]) -> None:
    """Report the results of running problems.

    Args:
        results: List of TaskResult objects
    """
    logger = get_logger(__name__)
    successful = sum(1 for r in results if r.success)
    failed = len(results) - successful

    logger.info(
        "Agent runs completed",
        total=len(results),
        successful=successful,
        failed=failed,
    )

    if failed > 0:
        typer.echo(
            typer.style(
                f"\nCompleted with {failed} failure(s) out of "
                f"{len(results)} problems.",
                fg=typer.colors.YELLOW,
                bold=True,
            )
        )
        for result in results:
            if not result.success:
                summary = result.error_message or "Unknown error"
                if result.error_type:
                    summary = f"{result.error_type}: {summary}"
                typer.echo(
                    typer.style(
                        f"  - {result.problem_name}: {summary}",
                        fg=typer.colors.RED,
                    )
                )
                if result.error_traceback:
                    typer.echo(
                        typer.style(result.error_traceback, fg=typer.colors.RED)
                    )
    else:
        typer.echo(
            typer.style(
                f"\nAll {len(results)} problems completed successfully!",
                fg=typer.colors.GREEN,
                bold=True,
            )
        )


def _create_checkpoint_results_and_summary(
    run_dir: Path,
    problems_base_path: Path,
    problem_names: list[str],
    console: Console,
) -> None:
    """Generate checkpoint_results.jsonl and a run summary."""
    problems_to_process = {
        name for name in problem_names if (run_dir / name).exists()
    }
    for entry in run_dir.iterdir():
        if entry.is_dir() and (problems_base_path / entry.name).exists():
            problems_to_process.add(entry.name)

    if not problems_to_process:
        logger.info(
            "No problems found for checkpoint result generation",
            run_directory=str(run_dir),
        )
        return

    results_file = run_dir / CHECKPOINT_RESULTS_FILENAME
    all_reports: list[dict[str, object]] = []

    for problem_name in sorted(problems_to_process):
        problem_dir = run_dir / problem_name
        try:
            problem = ProblemConfig.from_yaml(problems_base_path / problem_name)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Skipping checkpoint report generation for problem",
                problem=problem_name,
                error=str(exc),
            )
            continue

        try:
            reports, _ = evaluation_entry.create_problem_reports(
                problem_dir, problem
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed to create checkpoint reports",
                problem=problem_name,
                error=str(exc),
            )
            continue

        all_reports.extend(reports)

    if all_reports:
        update_results_jsonl(results_file, all_reports)
        logger.info(
            "Updated checkpoint results",
            path=str(results_file),
            report_count=len(all_reports),
        )
    else:
        logger.info(
            "No checkpoint reports generated",
            run_directory=str(run_dir),
        )

    with (run_dir / CONFIG_FILENAME).open("r") as f:
        config = yaml.safe_load(f)
    display_and_save_summary(results_file, run_dir, config, console)


def run_agent(
    ctx: typer.Context,
    # Config file (optional)
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to run configuration YAML file",
    ),
    # Override flags (all optional, override config file values)
    agent_config_path: str | None = typer.Option(
        None,
        "--agent",
        "-a",
        help="Override agent config (bare name or path)",
    ),
    environment_config_path: str | None = typer.Option(
        None,
        "--environment",
        "-e",
        help="Override environment config (bare name or path)",
    ),
    prompt_template_path: str | None = typer.Option(
        None,
        "--prompt",
        "-p",
        help="Override prompt template (bare name or path)",
    ),
    model_override: str | None = typer.Option(
        None,
        "--model",
        "-m",
        help="Override model: '{provider}/{model}'",
    ),
    # CLI-only flags (not in config)
    provider_api_key_env: str | None = typer.Option(
        None,
        "--provider-api-key-env",
        "-key",
        help="Override the environment variable used to resolve the provider API key.",
    ),
    problem_names: list[str] = typer.Option(
        [],
        "--problem",
        help="Name of the specific problems to run",
    ),
    num_workers: int = typer.Option(
        1,
        "--num-workers",
        "-n",
        help="Number of parallel workers for running problems",
    ),
    evaluate: bool = typer.Option(  # noqa: FBT001, FBT002
        True,
        "--evaluate/--no-evaluate",
        help="Whether to run evaluation",  # noqa: FBT003
    ),
    live_progress: bool = typer.Option(  # noqa: FBT001, FBT002
        True,  # noqa: FBT003
        "--live-progress/--no-live-progress",
        help="Whether to show live progress",
    ),
    resume: bool = typer.Option(  # noqa: FBT001, FBT002
        False,  # noqa: FBT003
        "--resume",
        help="Resume from the first incomplete checkpoint of an existing run",
    ),
    output_path: str | None = typer.Option(
        None,
        "--output-path",
        "-o",
        help="Override output path from config",
    ),
    # Config overrides via positional arguments
    overrides: list[str] | None = typer.Argument(
        None,
        help="Config overrides in key=value format (e.g., thinking=medium model.name=opus-4)",
    ),
) -> None:
    """Run the agent with unified config system.

    Examples:
        # Using a config file
        slop-code run --config my_run.yaml

        # Override values from config
        slop-code run --config my_run.yaml model.name=opus-4 thinking=high

        # Using flags only (defaults apply for unspecified values)
        slop-code run --agent claude_code --model anthropic/sonnet-4.5

        # Mix of flags and overrides
        slop-code run --model anthropic/sonnet-4.5 thinking=medium pass_policy=ALL_CASES
    """
    # Build CLI flags dict for config loading
    cli_flags: dict[str, object] = {}

    if agent_config_path is not None:
        cli_flags["agent"] = agent_config_path

    if environment_config_path is not None:
        cli_flags["environment"] = environment_config_path

    if prompt_template_path is not None:
        cli_flags["prompt"] = prompt_template_path

    # Parse model override into config format if provided
    if model_override is not None:
        try:
            parsed = utils.parse_model_override(model_override)
            cli_flags["model"] = {
                "provider": parsed.provider,
                "name": parsed.name,
            }
        except ValueError as exc:
            typer.echo(typer.style(str(exc), fg=typer.colors.RED, bold=True))
            raise typer.Exit(1) from exc

    # Load unified config with priority merging
    try:
        run_cfg = load_run_config(
            config_path=config,
            cli_flags=cli_flags,
            cli_overrides=overrides or [],
        )
    except FileNotFoundError as exc:
        typer.echo(typer.style(str(exc), fg=typer.colors.RED, bold=True))
        raise typer.Exit(1) from exc
    except ValueError as exc:
        typer.echo(
            typer.style(f"Config error: {exc}", fg=typer.colors.RED, bold=True)
        )
        raise typer.Exit(1) from exc

    # Resolve environment spec from loaded config
    env_spec = config_loader.resolve_environment(
        run_cfg.environment_config_path or run_cfg.environment
    )
    env_spec_typed = cast("EnvironmentSpecType", env_spec)

    # Look up ModelDefinition from catalog
    model_def = ModelCatalog.get(run_cfg.model.name)
    if model_def is None:
        typer.echo(
            typer.style(
                f"Model '{run_cfg.model.name}' not found in catalog",
                fg=typer.colors.RED,
                bold=True,
            )
        )
        raise typer.Exit(1)

    # Resolve credential for the provider
    try:
        credential = API_KEY_STORE.resolve(
            run_cfg.model.provider,
            env_var_override=provider_api_key_env,
        )
    except CredentialNotFoundError as e:
        typer.echo(
            typer.style(
                f"Credential error: {e}", fg=typer.colors.RED, bold=True
            )
        )
        raise typer.Exit(1) from e

    # Build agent config (no model injection - model passed separately)
    if run_cfg.agent_config_path is not None:
        _, agent_data = config_loader.load_agent_config(
            run_cfg.agent_config_path
        )
        agent_config = build_agent_config(agent_data)
    else:
        # Inline agent config
        agent_config = build_agent_config(run_cfg.agent)

    typer.echo(f"Using model: {run_cfg.model.provider}/{run_cfg.model.name}")
    if provider_api_key_env:
        typer.echo(
            f"Using provider API key env override: {provider_api_key_env}"
        )

    cli_problem_names = list(problem_names)
    problem_names = cli_problem_names or list(run_cfg.problems)
    if run_cfg.problems and not cli_problem_names:
        typer.echo(
            typer.style(
                f"Using problems from config: {', '.join(run_cfg.problems)}",
                fg=typer.colors.CYAN,
            )
        )

    # Determine output directory
    output_path_str = (
        output_path if output_path is not None else run_cfg.output_path
    )
    if ctx.obj.debug:
        # Prepend DEBUG_ to the last path component
        parts = output_path_str.rsplit("/", 1)
        if len(parts) == 2:
            output_path_str = f"{parts[0]}/DEBUG_{parts[1]}"
        else:
            output_path_str = f"DEBUG_{output_path_str}"

    run_dir = Path(output_path_str)
    run_dir_preexisted = run_dir.exists()
    typer.echo(
        typer.style(
            f"Output directory: {run_dir}", fg=typer.colors.GREEN, bold=True
        )
    )
    run_dir = utils.ensure_dir_exists(run_dir, create=True)

    console = Console()
    common.setup_command_logging(
        log_dir=run_dir,
        verbosity=ctx.obj.verbosity,
        log_file_name="run_agent.log",
        console=console,
        add_multiproc_info=num_workers > 1,
    )
    logger = get_logger(__name__)
    logger.info(
        "Starting agent run",
        agent_config=str(run_cfg.agent_config_path or "inline"),
        environment_config=str(run_cfg.environment_config_path or "inline"),
        prompt_path=str(run_cfg.prompt_path),
        model=f"{run_cfg.model.provider}/{run_cfg.model.name}",
        thinking=run_cfg.thinking,
        pass_policy=run_cfg.pass_policy.value,
        problem_names=problem_names,
        one_shot=run_cfg.one_shot.enabled,
    )

    # Discover problems if not specified
    if not problem_names:
        for problem in sorted(
            ctx.obj.problem_path.iterdir(), key=lambda x: x.name
        ):
            if not problem.exists():
                continue
            try:
                cfg = ProblemConfig.from_yaml(problem)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "Problem config not valid",
                    problem=problem.name,
                    error=str(exc),
                )
                continue

            if cfg.category == "NOT_SET":
                continue

            checkpoints = [cp for _, cp in cfg.iterate_checkpoint_items()]
            if not checkpoints:
                typer.echo(
                    typer.style(
                        f"Problem '{problem}' has no checkpoints",
                        fg=typer.colors.RED,
                        bold=True,
                    )
                )
                continue
            problem_names.append(problem.name)
        typer.echo(
            typer.style(
                f"Found {len(problem_names):,} problems",
                fg=typer.colors.GREEN,
                bold=True,
            )
        )

    # Validate problem paths exist
    for problem in problem_names:
        problem_path = ctx.obj.problem_path / problem
        if not problem_path.exists():
            typer.echo(
                typer.style(
                    f"Problem path '{problem_path}' does not exist.",
                    fg=typer.colors.RED,
                    bold=True,
                )
            )
            raise typer.Exit(1)

    # If the run directory already exists, support "resume" behavior:
    # - default: only run problems that are missing / not completed
    # - --overwrite: rerun all requested problems (without deleting run_dir)
    if run_dir_preexisted:
        requested = list(problem_names)
        if ctx.obj.overwrite:
            typer.echo(
                typer.style(
                    f"--overwrite set: rerunning all {len(requested):,} problem(s) in-place (run directory not deleted).",
                    fg=typer.colors.YELLOW,
                    bold=True,
                )
            )
            for p in requested:
                _clear_problem_outputs(run_dir, p)
        else:
            done = [p for p in requested if _problem_is_done(run_dir, p)]
            done_set = set(done)
            missing = [p for p in requested if p not in done_set]
            typer.echo(
                typer.style(
                    f"Output directory exists: {len(done):,} done, {len(missing):,} missing. Running missing only.",
                    fg=typer.colors.YELLOW,
                    bold=True,
                )
            )
            if not resume:
                for p in missing:
                    _clear_problem_outputs(run_dir, p)
            problem_names = missing

            if not problem_names:
                typer.echo(
                    typer.style(
                        "Nothing to do: all requested problems are already completed.",
                        fg=typer.colors.GREEN,
                        bold=True,
                    )
                )
                if evaluate:
                    _create_checkpoint_results_and_summary(
                        run_dir=run_dir,
                        problems_base_path=ctx.obj.problem_path,
                        problem_names=requested,
                        console=console,
                    )
                return

    # Save environment and config to run directory
    with (run_dir / ENV_CONFIG_NAME).open("w") as f:
        yaml.dump(serialize_path_dict(env_spec.model_dump(mode="json")), f)

    with (run_dir / CONFIG_FILENAME).open("w") as f:
        yaml.dump(
            serialize_path_dict(run_cfg.model_dump(mode="json")),
            f,
        )
    logger.info(
        "Starting agent runs",
        num_problems=len(problem_names),
        num_workers=num_workers,
    )

    # Build docker image if needed
    if isinstance(env_spec_typed, docker_runtime.DockerEnvironmentSpec):
        if agent_config.docker_template is not None:
            image_name = common.build_agent_docker(
                agent_config=agent_config,
                environment=env_spec_typed,
                force_build=False,
                force_build_base=False,
            )
        else:
            # Agent doesn't have custom Dockerfile, use environment base image
            image_name = env_spec_typed.get_base_image()
    else:
        image_name = ""

    task_config = problem_runner.RunTaskConfig(
        problem_base_path=ctx.obj.problem_path,
        run_dir=run_dir,
        env_spec=env_spec_typed,
        agent_config=agent_config,
        model_def=model_def,
        credential=credential,
        thinking_preset=run_cfg.thinking,
        thinking_max_tokens=run_cfg.thinking_max_tokens,
        prompt_template=run_cfg.prompt_content,
        pass_policy=run_cfg.pass_policy,
        seed=ctx.obj.seed,
        verbosity=ctx.obj.verbosity,
        debug=ctx.obj.debug,
        disable_evaluation=not evaluate,
        live_progress=live_progress,
        image=image_name,
        resume=resume,
        one_shot=run_cfg.one_shot,
    )

    # Run problems using the run_task module
    results = problem_runner.run_problems(
        problem_names=problem_names,
        config=task_config,
        num_workers=num_workers,
        console=console,
    )

    # Report results
    _report_results(results)

    if evaluate:
        _create_checkpoint_results_and_summary(
            run_dir=run_dir,
            problems_base_path=ctx.obj.problem_path,
            problem_names=problem_names,
            console=console,
        )
    else:
        logger.info(
            "Evaluation disabled; skipping checkpoint result generation",
            run_directory=str(run_dir),
        )
