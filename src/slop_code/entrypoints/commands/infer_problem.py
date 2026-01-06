from __future__ import annotations

import shutil
from pathlib import Path
from queue import Queue
from typing import Annotated

import typer

from slop_code import evaluation
from slop_code.agent_runner import Agent
from slop_code.agent_runner import AgentRunSpec
from slop_code.agent_runner import runner
from slop_code.agent_runner.credentials import API_KEY_STORE
from slop_code.agent_runner.credentials import CredentialNotFoundError
from slop_code.agent_runner.registry import build_agent_config
from slop_code.common.llms import ModelCatalog
from slop_code.entrypoints import utils
from slop_code.entrypoints.commands import common
from slop_code.entrypoints.config import loader as config_loader
from slop_code.evaluation import ProblemConfig
from slop_code.execution import docker_runtime
from slop_code.logging import get_logger
from slop_code.logging import setup_logging


def register(app: typer.Typer, name: str) -> None:
    app.command(
        name,
        help="Run inference on a single problem.",
    )(infer_problem)


def infer_problem(
    ctx: typer.Context,
    problem_name: Annotated[
        str,
        typer.Argument(
            help="Name of the problem. It must exist in the problem directory.",
            exists=True,
            dir_okay=True,
            file_okay=False,
        ),
    ],
    agent_config_path: Annotated[
        Path,
        typer.Option(
            "-a",
            "--agent",
            help="Path to agent-runner configuration YAML",
        ),
    ],
    environment_config_path: Annotated[
        Path,
        typer.Option(
            "-e",
            "--environment-config-path",
            help="Path to environment-runner configuration YAML",
        ),
    ],
    output_path: Annotated[
        Path,
        typer.Option(
            "-o",
            "--output-path",
            help="Path to output directory.",
        ),
    ],
    prompt_template_path: Annotated[
        Path,
        typer.Option(
            "-prompt",
            "--prompt-template",
            help="Path to prompt template YAML",
            exists=True,
            dir_okay=False,
            file_okay=True,
        ),
    ],
    model_override: str = typer.Option(
        ...,
        "--model",
        "-m",
        help="Model in the form '{provider}/{model}'. Both provider and model are required.",
    ),
    provider_api_key_env: str | None = typer.Option(
        None,
        "--provider-api-key-env",
        help="Override the environment variable used to resolve the provider API key.",
    ),
    thinking: str | None = typer.Option(
        None,
        "--thinking",
        help="Thinking budget preset: none, low, medium, or high",
    ),
    max_thinking_tokens: int | None = typer.Option(
        None,
        "--max-thinking-tokens",
        help="Maximum thinking tokens (mutually exclusive with --thinking)",
    ),
    pass_policy: evaluation.PassPolicy = typer.Option(
        evaluation.PassPolicy.ANY,
        "--pass-policy",
        "-pass",
        help="Policy to determine if the checkpoint passed",
    ),
    evaluate: bool = typer.Option(
        True,
        "--evaluate/--no-evaluate",
        help="Whether to run evaluation",
    ),
) -> None:
    """Run inference on a single problem."""
    # Validate mutual exclusion of thinking options
    if thinking is not None and max_thinking_tokens is not None:
        typer.echo(
            typer.style(
                "Cannot specify both --thinking and --max-thinking-tokens",
                fg=typer.colors.RED,
                bold=True,
            )
        )
        raise typer.Exit(1)

    # Validate thinking preset value
    valid_presets = ("none", "low", "medium", "high")
    if thinking is not None and thinking not in valid_presets:
        typer.echo(
            typer.style(
                f"Invalid --thinking value '{thinking}'. "
                f"Must be one of: {', '.join(valid_presets)}",
                fg=typer.colors.RED,
                bold=True,
            )
        )
        raise typer.Exit(1)

    typer.echo(f"Running inference on problem: {problem_name}")

    # Parse model override to get provider and model name
    try:
        parsed_model_override = utils.parse_model_override(model_override)
    except ValueError as exc:
        typer.echo(typer.style(str(exc), fg=typer.colors.RED, bold=True))
        raise typer.Exit(1) from exc

    # Look up ModelDefinition from catalog
    model_def = ModelCatalog.get(parsed_model_override.name)
    if model_def is None:
        typer.echo(
            typer.style(
                f"Model '{parsed_model_override.name}' not found in catalog",
                fg=typer.colors.RED,
                bold=True,
            )
        )
        raise typer.Exit(1)

    # Resolve credential for the provider
    try:
        credential = API_KEY_STORE.resolve(
            parsed_model_override.provider,
            env_var_override=provider_api_key_env,
        )
    except CredentialNotFoundError as e:
        typer.echo(
            typer.style(
                f"Credential error: {e}", fg=typer.colors.RED, bold=True
            )
        )
        raise typer.Exit(1) from e

    # Load agent config (no model injection)
    _, agent_data = config_loader.load_agent_config(agent_config_path)
    agent_config = build_agent_config(agent_data)
    if provider_api_key_env:
        typer.echo(
            f"Using provider API key env override: {provider_api_key_env}"
        )
    env_spec = config_loader.resolve_environment(environment_config_path)
    prompt_template = prompt_template_path.read_text(encoding="utf-8")
    save_dir = output_path / problem_name
    if save_dir.exists():
        if ctx.obj.overwrite:
            typer.echo(
                typer.style(
                    f"Overwriting output path '{save_dir}'.",
                    fg=typer.colors.YELLOW,
                    bold=True,
                )
            )
            shutil.rmtree(save_dir)
            save_dir.mkdir(parents=True, exist_ok=True)
        else:
            typer.echo(
                typer.style(
                    f"Output path '{save_dir}' already exists. Use --overwrite to overwrite.",
                    fg=typer.colors.RED,
                    bold=True,
                )
            )
            raise typer.Exit(1)
    else:
        save_dir.mkdir(parents=True, exist_ok=True)
    setup_logging(save_dir, ctx.obj.verbosity, "infer.log")
    logger = get_logger()
    logger.info(
        "Running inference on problem",
        problem_name=problem_name,
        save_dir=save_dir,
    )
    logger.info(
        "Using configs",
        agent_type=agent_config.type,
        problem_path=str(ctx.obj.problem_path / problem_name),
        prompt_template_path=str(prompt_template_path),
    )
    problem = ProblemConfig.from_yaml(ctx.obj.problem_path / problem_name)
    if isinstance(env_spec, docker_runtime.DockerEnvironmentSpec):
        if agent_config.docker_template is not None:
            image_name = common.build_agent_docker(
                agent_config=agent_config,
                environment=env_spec,
                force_build=False,
                force_build_base=False,
            )
        else:
            # Agent doesn't have custom Dockerfile, use environment base image
            image_name = env_spec.get_base_image()
    else:
        image_name = None

    run_spec = AgentRunSpec(
        seed=ctx.obj.seed,
        template=prompt_template,
        problem=problem,
        environment=env_spec,
        pass_policy=pass_policy,
        skip_evaluation=not evaluate,
        verbose=ctx.obj.verbosity > 0,
        image=image_name,  # type: ignore[arg-type]
    )
    agent = Agent.from_config(
        agent_config,
        model=model_def,
        credential=credential,
        problem_name=problem_name,
        verbose=run_spec.verbose,
        image=run_spec.image,
        thinking_preset=thinking,  # type: ignore[arg-type]
        thinking_max_tokens=max_thinking_tokens,
    )

    progress_queue = Queue()
    runner.run_agent(
        run_spec=run_spec,
        agent=agent,
        output_path=save_dir,
        progress_queue=progress_queue,
    )
