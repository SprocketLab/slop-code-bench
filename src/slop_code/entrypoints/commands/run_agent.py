from __future__ import annotations

import shutil
from pathlib import Path
from typing import cast

import typer
import yaml
from rich.console import Console

from slop_code.agent_runner.agent import AgentConfigBase
from slop_code.agent_runner.credentials import API_KEY_STORE
from slop_code.agent_runner.credentials import CredentialNotFoundError
from slop_code.agent_runner.credentials import ProviderCredential
from slop_code.agent_runner.registry import build_agent_config
from slop_code.agent_runner.resume import detect_resume_point
from slop_code.common import CHECKPOINT_RESULTS_FILENAME
from slop_code.common import CONFIG_FILENAME
from slop_code.common import ENV_CONFIG_NAME
from slop_code.common import serialize_path_dict
from slop_code.common.llms import ModelCatalog
from slop_code.common.llms import ModelDefinition
from slop_code.entrypoints import evaluation as evaluation_entry
from slop_code.entrypoints import problem_runner
from slop_code.entrypoints import utils
from slop_code.entrypoints.commands import common
from slop_code.entrypoints.config import ResolvedRunConfig
from slop_code.entrypoints.config import load_run_config
from slop_code.entrypoints.config import loader as config_loader
from slop_code.entrypoints.evaluation.metrics import update_results_jsonl
from slop_code.entrypoints.utils import display_and_save_summary
from slop_code.evaluation import ProblemConfig
from slop_code.execution import EnvironmentSpecType
from slop_code.execution import docker_runtime
from slop_code.logging import get_logger

logger = get_logger(__name__)


def _clear_problem_outputs(run_dir: Path, problem_name: str) -> None:
    """Remove any prior outputs for a problem (but keep the run dir)."""
    shutil.rmtree(run_dir / problem_name, ignore_errors=True)


def _check_problem_needs_rerun(
    run_dir: Path,
    problem_name: str,
    problem_path: Path,
    prompt_template: str,
    environment: EnvironmentSpecType,
) -> tuple[bool, str | None]:
    """Check if a problem needs to be run based on checkpoint state.

    Uses detect_resume_point() which handles both:
    1. Structured detection from run_info.yaml if present
    2. Artifact-based fallback (inference_result.json + snapshot) if missing
    3. Prompt validation to detect spec changes

    Args:
        run_dir: The run output directory
        problem_name: Name of the problem
        problem_path: Path to the problem definition
        prompt_template: Current prompt template content
        environment: Current environment spec

    Returns:
        (needs_rerun, reason) - reason is None if doesn't need rerun,
        otherwise a human-readable explanation
    """
    output_path = run_dir / problem_name

    # If output directory doesn't exist, need to run
    if not output_path.exists():
        return True, "no output directory"

    # Load problem config for checkpoint validation
    try:
        problem_config = ProblemConfig.from_yaml(problem_path)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Failed to load problem config",
            problem=problem_name,
            error=str(exc),
        )
        return True, "invalid problem config"

    checkpoint_items = list(problem_config.iterate_checkpoint_items())
    checkpoint_names = [name for name, _ in checkpoint_items]
    checkpoints = [cp for _, cp in checkpoint_items]

    # Use detect_resume_point for both run_info.yaml and artifact-based detection
    resume_info = detect_resume_point(
        output_path,
        checkpoint_names,
        problem_config=problem_config,
        prompt_template=prompt_template,
        environment=environment,
        entry_file=problem_config.entry_file,
        checkpoints=checkpoints,
    )

    # No valid state found at all
    if resume_info is None:
        return True, "no valid checkpoint state"

    # All checkpoints completed and valid
    if not resume_info.resume_from_checkpoint:
        return False, None

    # Some checkpoints need to be re-run
    reasons = []
    for status in resume_info.checkpoint_statuses:
        if not status.is_valid and status.reason:
            reasons.append(f"{status.name}: {status.reason.value}")
    reason_str = "; ".join(reasons) if reasons else "incomplete checkpoints"
    return True, reason_str


def _filter_problems_for_execution(
    run_dir: Path,
    problem_names: list[str],
    problem_path: Path,
    prompt_template: str,
    environment: EnvironmentSpecType,
    *,
    overwrite: bool,
    resume: bool,
) -> tuple[list[str], list[str], dict[str, str]]:
    """Filter problems based on completion status and prompt changes.

    Determines which problems need to be run based on their completion state
    and whether prompts have changed since the last run.

    Args:
        run_dir: The run output directory
        problem_names: List of requested problem names
        problem_path: Base path to problem definitions
        prompt_template: Current prompt template content
        environment: Current environment spec
        overwrite: If True, rerun all problems regardless of state
        resume: If True, preserve partial checkpoint outputs

    Returns:
        Tuple of (problems_to_run, skipped_problems, rerun_reasons)
        where rerun_reasons maps problem name to why it needs rerun
    """
    if overwrite:
        # Clear all outputs and rerun everything
        for p in problem_names:
            _clear_problem_outputs(run_dir, p)
        return list(problem_names), [], {}

    to_run: list[str] = []
    skipped: list[str] = []
    rerun_reasons: dict[str, str] = {}

    for p in problem_names:
        needs_rerun, reason = _check_problem_needs_rerun(
            run_dir,
            p,
            problem_path / p,
            prompt_template,
            environment,
        )
        if needs_rerun:
            to_run.append(p)
            if reason:
                rerun_reasons[p] = reason
            if not resume:
                _clear_problem_outputs(run_dir, p)
        else:
            skipped.append(p)

    return to_run, skipped, rerun_reasons


def _build_cli_flags(
    agent_config_path: str | None,
    environment_config_path: str | None,
    prompt_template_path: str | None,
    model_override: str | None,
) -> dict[str, object]:
    """Build CLI flags dict for config loading.

    Args:
        agent_config_path: Agent config override
        environment_config_path: Environment config override
        prompt_template_path: Prompt template override
        model_override: Model override in "provider/name" format

    Returns:
        Dictionary of CLI flags for config loading

    Raises:
        ValueError: If model_override format is invalid
    """
    cli_flags: dict[str, object] = {}

    if agent_config_path is not None:
        cli_flags["agent"] = agent_config_path

    if environment_config_path is not None:
        cli_flags["environment"] = environment_config_path

    if prompt_template_path is not None:
        cli_flags["prompt"] = prompt_template_path

    if model_override is not None:
        parsed = utils.parse_model_override(model_override)
        cli_flags["model"] = {
            "provider": parsed.provider,
            "name": parsed.name,
        }

    return cli_flags


def _resolve_environment_and_credentials(
    run_cfg: ResolvedRunConfig,
    provider_api_key_env: str | None,
) -> tuple[EnvironmentSpecType, ModelDefinition, ProviderCredential]:
    """Resolve environment spec, model definition, and credentials.

    Args:
        run_cfg: The resolved run configuration
        provider_api_key_env: Optional override for API key environment variable

    Returns:
        Tuple of (environment_spec, model_definition, credential)

    Raises:
        typer.Exit: If model not found in catalog or credentials unavailable
    """
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

    return env_spec_typed, model_def, credential


def _build_agent_config(run_cfg: ResolvedRunConfig) -> AgentConfigBase:
    """Build agent configuration from resolved run config.

    Args:
        run_cfg: The resolved run configuration

    Returns:
        Built agent configuration
    """
    if run_cfg.agent_config_path is not None:
        _, agent_data = config_loader.load_agent_config(
            run_cfg.agent_config_path
        )
        return build_agent_config(agent_data)
    return build_agent_config(run_cfg.agent)


def _discover_problems(problem_path: Path) -> list[str]:
    """Auto-discover problems from the problem directory.

    Args:
        problem_path: Base path containing problem directories

    Returns:
        List of valid problem names found
    """
    problem_names: list[str] = []
    for problem in sorted(problem_path.iterdir(), key=lambda x: x.name):
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

    return problem_names


def _validate_problem_paths(problem_names: list[str], problem_path: Path) -> None:
    """Validate that all problem paths exist.

    Args:
        problem_names: List of problem names to validate
        problem_path: Base path containing problem directories

    Raises:
        typer.Exit: If any problem path does not exist
    """
    for problem in problem_names:
        full_path = problem_path / problem
        if not full_path.exists():
            typer.echo(
                typer.style(
                    f"Problem path '{full_path}' does not exist.",
                    fg=typer.colors.RED,
                    bold=True,
                )
            )
            raise typer.Exit(1)


def _preview_dry_run(
    problem_names: list[str],
    run_dir: Path,
    problem_path: Path,
    prompt_template: str,
    env_spec: EnvironmentSpecType,
) -> None:
    """Preview what would be executed without making changes.

    Args:
        problem_names: List of problem names to preview
        run_dir: The run output directory
        problem_path: Base path to problem definitions
        prompt_template: Current prompt template content
        env_spec: Current environment spec
    """
    typer.echo(
        typer.style(
            "\nDRY RUN - Resume Preview:",
            fg=typer.colors.CYAN,
            bold=True,
        )
    )
    for problem_name in problem_names:
        full_problem_path = problem_path / problem_name
        try:
            problem_config = ProblemConfig.from_yaml(full_problem_path)
        except Exception as exc:  # noqa: BLE001
            typer.echo(
                typer.style(
                    f"\n{problem_name}: Failed to load config - {exc}",
                    fg=typer.colors.RED,
                )
            )
            continue

        output_path = run_dir / problem_name
        checkpoint_items = list(problem_config.iterate_checkpoint_items())
        checkpoint_names = [name for name, _ in checkpoint_items]
        checkpoints = [cp for _, cp in checkpoint_items]

        resume_info = detect_resume_point(
            output_path,
            checkpoint_names,
            problem_config=problem_config,
            prompt_template=prompt_template,
            environment=env_spec,
            entry_file=problem_config.entry_file,
            checkpoints=checkpoints,
        )

        # Skip fully completed problems (silently)
        if resume_info and not resume_info.resume_from_checkpoint:
            continue

        typer.echo(
            typer.style(
                f"\n{problem_name}:",
                fg=typer.colors.CYAN,
                bold=True,
            )
        )

        if resume_info:
            typer.echo(
                f"  Resume from: {resume_info.resume_from_checkpoint}"
            )
            typer.echo(
                f"  Completed: {', '.join(resume_info.completed_checkpoints)}"
            )
            if resume_info.invalidated_checkpoints:
                typer.echo("  Would delete and re-run:")
                for status in resume_info.checkpoint_statuses:
                    if not status.is_valid and status.reason:
                        typer.echo(
                            f"    - {status.name} ({status.reason.value})"
                        )
                # Show directories that would be deleted
                typer.echo("  Directories to delete:")
                for cp_name in resume_info.invalidated_checkpoints:
                    cp_dir = output_path / cp_name
                    if cp_dir.exists():
                        typer.echo(f"    - {cp_dir}")
        else:
            if output_path.exists():
                typer.echo(
                    "  Would start fresh (no valid completed checkpoints)"
                )
            else:
                typer.echo("  Would start fresh (no existing run)")

    typer.echo(
        typer.style(
            "\nNo changes made (dry run).",
            fg=typer.colors.CYAN,
            bold=True,
        )
    )


def _prepare_run_artifacts(
    run_dir: Path,
    env_spec: EnvironmentSpecType,
    agent_config: AgentConfigBase,
    run_cfg: ResolvedRunConfig,
) -> str:
    """Save configuration artifacts and build Docker image if needed.

    Args:
        run_dir: The run output directory
        env_spec: Environment specification
        agent_config: Agent configuration
        run_cfg: Resolved run configuration

    Returns:
        Docker image name (empty string if not using Docker)
    """
    # Save environment and config to run directory
    with (run_dir / ENV_CONFIG_NAME).open("w") as f:
        yaml.dump(serialize_path_dict(env_spec.model_dump(mode="json")), f)

    with (run_dir / CONFIG_FILENAME).open("w") as f:
        yaml.dump(
            serialize_path_dict(run_cfg.model_dump(mode="json")),
            f,
        )

    # Build docker image if needed
    if isinstance(env_spec, docker_runtime.DockerEnvironmentSpec):
        if agent_config.docker_template is not None:
            return common.build_agent_docker(
                agent_config=agent_config,
                environment=env_spec,
                force_build=False,
                force_build_base=False,
            )
        # Agent doesn't have custom Dockerfile, use environment base image
        return env_spec.get_base_image()
    return ""


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
        True,  # noqa: FBT003
        "--evaluate/--no-evaluate",
        help="Whether to run evaluation",
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
    dry_run: bool = typer.Option(  # noqa: FBT001, FBT002
        False,  # noqa: FBT003
        "--dry-run",
        help="Preview what would be done without making changes (use with --resume)",
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
    _validate_problem_paths(problem_names, ctx.obj.problem_path)

    # If the run directory already exists, filter based on completion and prompt changes
    requested = list(problem_names)
    if run_dir_preexisted:
        if ctx.obj.overwrite:
            typer.echo(
                typer.style(
                    f"--overwrite set: rerunning all {len(requested):,} problem(s) in-place (run directory not deleted).",
                    fg=typer.colors.YELLOW,
                    bold=True,
                )
            )

        to_run, skipped, rerun_reasons = _filter_problems_for_execution(
            run_dir,
            problem_names,
            ctx.obj.problem_path,
            run_cfg.prompt_content,
            env_spec,
            overwrite=ctx.obj.overwrite,
            resume=resume,
        )

        if not ctx.obj.overwrite:
            # Log why problems are being rerun
            spec_changed = [p for p, r in rerun_reasons.items() if "spec_changed" in r]

            if spec_changed:
                typer.echo(
                    typer.style(
                        f"Spec changed for {len(spec_changed)} problem(s): {', '.join(spec_changed[:3])}{'...' if len(spec_changed) > 3 else ''}",
                        fg=typer.colors.YELLOW,
                        bold=True,
                    )
                )

            typer.echo(
                typer.style(
                    f"Output directory exists: {len(skipped):,} done, {len(to_run):,} to run.",
                    fg=typer.colors.YELLOW,
                    bold=True,
                )
            )

        problem_names = to_run

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

    # Handle dry-run mode
    if dry_run:
        _preview_dry_run(
            problem_names,
            run_dir,
            ctx.obj.problem_path,
            run_cfg.prompt_content,
            env_spec,
        )
        return

    # Save environment and config to run directory, build docker image if needed
    image_name = _prepare_run_artifacts(run_dir, env_spec_typed, agent_config, run_cfg)
    logger.info(
        "Starting agent runs",
        num_problems=len(problem_names),
        num_workers=num_workers,
    )

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
