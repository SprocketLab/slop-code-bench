from pathlib import Path

import pytest
import yaml

from slop_code.execution import DockerEnvironmentSpec
from slop_code.execution import LocalEnvironmentSpec


@pytest.fixture()
def local_environment_spec() -> LocalEnvironmentSpec:
    with (Path(__file__).parents[2] / "configs/environments/local-py.yaml").open(
        "r"
    ) as f:
        environment_config = yaml.safe_load(f)
    return LocalEnvironmentSpec.model_validate(environment_config)


@pytest.fixture()
def docker_environment_spec() -> DockerEnvironmentSpec:
    with (
        Path(__file__).parents[2] / "configs/environments/docker-python3.12-uv.yaml"
    ).open("r") as f:
        environment_config = yaml.safe_load(f)
    return DockerEnvironmentSpec.model_validate(environment_config)
