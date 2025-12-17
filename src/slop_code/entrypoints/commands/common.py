"""Common utilities for CLI commands."""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any

import docker
import typer
import yaml
from pydantic import ValidationError
from rich.console import Console

from slop_code.agent_runner.agent import AgentConfigBase
from slop_code.evaluation import ProblemConfig
from slop_code.execution import docker_runtime
from slop_code.logging import get_logger
from slop_code.logging import setup_logging


class PathType(str, Enum):
    """Type of path being processed by commands."""

    RUN = "run"
    COLLECTION = "collection"


def build_agent_docker(
    agent_config: AgentConfigBase,
    environment: docker_runtime.DockerEnvironmentSpec,
    force_build: bool = False,
    force_build_base: bool = False,
) -> str:
    agent_image_name = f"{docker_runtime.IMAGE_NAME_PREFIX}:{agent_config.get_image(environment.name)}"
    client = docker.from_env()
    docker_runtime.build_base_image(
        client=client,
        environment_spec=environment,
        force_build=force_build_base,
    )
    docker_file = agent_config.get_docker_file(environment.get_base_image())
    if docker_file is None:
        raise ValueError("Docker file is None")
    client = docker.from_env()
    _ = docker_runtime.build_image_from_str(
        client=client,
        image_name=agent_image_name,
        dockerfile=docker_file,
        force_build=force_build,
    )
    client.close()
    return agent_image_name


def validate_rubric_options(
    rubric_path: Path | None, rubric_model: str | None
) -> None:
    """Validate that both rubric path and model are provided together."""
    if (rubric_path is not None) != (rubric_model is not None):
        typer.echo(
            typer.style(
                "Both --rubric and --rubric-model must be provided together.",
                fg=typer.colors.RED,
                bold=True,
            )
        )
        raise typer.Exit(1)


def load_problem_config(problem_path: Path) -> ProblemConfig:
    """Load problem configuration.

    Args:
        problem_path: Path to problem directory or config.yaml file.

    Returns:
        Loaded problem configuration.

    Raises:
        FileNotFoundError: If config file not found.
        yaml.YAMLError: If YAML is malformed.
        ValidationError: If config validation fails.
    """
    return ProblemConfig.from_yaml(problem_path)


def load_problem_config_or_exit(
    problem_path: Path, problem_name: str | None = None
) -> ProblemConfig:
    """Load problem configuration or exit with error."""
    log = get_logger(__name__)
    display_name = problem_name or problem_path.name

    try:
        return load_problem_config(problem_path)
    except FileNotFoundError:
        log.error(
            "Problem configuration file not found",
            problem_name=display_name,
            path=str(problem_path),
        )
        typer.echo(
            typer.style(
                f"Problem configuration not found at '{problem_path}'",
                fg=typer.colors.RED,
                bold=True,
            )
        )
        raise typer.Exit(1)
    except yaml.YAMLError as e:
        log.error(
            "YAML parsing error in problem configuration",
            problem_name=display_name,
            error=str(e),
        )
        typer.echo(
            typer.style(
                f"YAML parsing error in problem configuration for '{display_name}': {e}",
                fg=typer.colors.RED,
                bold=True,
            )
        )
        raise typer.Exit(1)
    except ValidationError as e:
        log.error(
            "Problem configuration validation failed",
            problem_name=display_name,
            error=str(e),
        )
        typer.echo(
            typer.style(
                f"Problem configuration validation failed for '{display_name}':\n{e}",
                fg=typer.colors.RED,
                bold=True,
            )
        )
        raise typer.Exit(1)


def ensure_docker_ready(environment: Any, force_build: bool = False) -> None:
    """Ensure docker base image is built if environment is docker-based."""
    if isinstance(environment, docker_runtime.DockerEnvironmentSpec):
        import docker

        _ = docker_runtime.build_base_image(
            client=docker.from_env(),
            environment_spec=environment,
            force_build=force_build,
        )


def setup_command_logging(
    log_dir: Path,
    verbosity: int,
    log_file_name: str = "evaluation.log",
    console: Console | None = None,
    add_multiproc_info: bool = False,
) -> Any:
    """Setup logging for commands."""
    return setup_logging(
        log_dir=log_dir,
        verbosity=verbosity,
        log_file_name=log_file_name,
        console=console,
        add_multiproc_info=add_multiproc_info,
    )
