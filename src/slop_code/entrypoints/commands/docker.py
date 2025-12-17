from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

import docker
import typer

from slop_code.agent_runner.registry import build_agent_config
from slop_code.entrypoints.commands import common
from slop_code.entrypoints.config import loader as config_loader
from slop_code.evaluation import ProblemConfig
from slop_code.execution import docker_runtime
from slop_code.execution.assets import resolve_static_assets

app = typer.Typer(
    help="Utility tools for working with docker.",
)


@app.command(
    "make-dockerfile",
    help="Make the Dockerfile for a docker environment.",
)
def make_dockerfile(
    ctx: typer.Context,
    dockerfile: Literal["base", "agent"],
    environment_config_path: Annotated[
        Path, typer.Argument(exists=True, dir_okay=False)
    ],
) -> None:
    environment_config = config_loader.resolve_environment(environment_config_path)
    if not isinstance(environment_config, docker_runtime.DockerEnvironmentSpec):
        raise typer.BadParameter(
            "Environment config must be a DockerEnvironmentSpec"
        )

    if dockerfile == "base":
        dockerfile = docker_runtime.make_base_image(environment_config)
    else:
        raise typer.BadParameter("Invalid dockerfile type")
    print(dockerfile)


@app.command(
    "build-base",
    help="Build the base image for a docker environment.",
)
def build_base_image(
    ctx: typer.Context,
    environment_config_path: Annotated[
        Path, typer.Argument(exists=True, dir_okay=False)
    ],
    force_build: bool = False,
) -> None:
    client = docker.from_env()
    environment_config = config_loader.resolve_environment(environment_config_path)

    docker_runtime.build_base_image(
        client,
        environment_spec=environment_config,
        force_build=force_build,
    )
    client.close()


@app.command(
    "build-submission",
    help="Build a docker image for a submission.",
)
def build_submission_image(
    ctx: typer.Context,
    name: str,
    submission_path: Annotated[
        Path, typer.Argument(exists=True, dir_okay=True, file_okay=False)
    ],
    environment_config_path: Annotated[
        Path, typer.Argument(exists=True, dir_okay=False)
    ],
    problem_name: Annotated[str, typer.Argument()],
    force_build: bool = False,
    build_base: bool = False,
) -> None:
    client = docker.from_env()
    environment_config = config_loader.resolve_environment(environment_config_path)
    problem = ProblemConfig.from_yaml(ctx.obj.problem_path / problem_name)

    static_assets = resolve_static_assets(problem.path, problem.static_assets)
    docker_runtime.build_submission_image(
        client,
        environment_config_path.stem,
        submission_path,
        environment_spec=environment_config,
        static_assets=static_assets,
        force_build=force_build,
        build_base=build_base,
        use_name=name,
    )
    client.close()


@app.command(
    "build-agent",
    help="Build a docker image for an agent.",
)
def build_agent_image(
    ctx: typer.Context,
    agent_config_path: Annotated[
        Path, typer.Argument(exists=True, dir_okay=False)
    ],
    environment_config_path: Annotated[
        Path, typer.Argument(exists=True, dir_okay=False)
    ],
    force_build: bool = False,
    force_build_base: bool = False,
) -> None:
    _, agent_data = config_loader.load_agent_config(agent_config_path)
    agent_config = build_agent_config(agent_data)
    environment_config = config_loader.resolve_environment(environment_config_path)
    common.build_agent_docker(
        agent_config=agent_config,
        environment=environment_config,
        force_build=force_build,
        force_build_base=force_build_base,
    )
