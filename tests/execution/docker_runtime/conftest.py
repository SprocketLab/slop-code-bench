"""Fixtures for Docker runtime tests."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from slop_code.execution.docker_runtime.models import DockerConfig
from slop_code.execution.docker_runtime.models import DockerEnvironmentSpec
from slop_code.execution.models import CommandConfig
from slop_code.execution.models import SetupConfig


def _docker_available() -> bool:
    """Check if Docker is available on the system."""
    if not shutil.which("docker"):
        return False
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def _test_image_available() -> bool:
    """Check if the test Docker image is available."""
    if not _docker_available():
        return False
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", "slop-code:python3.12"],
            capture_output=True,
            timeout=10,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


# Skip markers
docker_available = pytest.mark.skipif(
    not _docker_available(),
    reason="Docker is not available",
)

test_image_available = pytest.mark.skipif(
    not _test_image_available(),
    reason="Test Docker image (slop-code:python3.12) not available",
)


@pytest.fixture
def docker_spec() -> DockerEnvironmentSpec:
    """Create a DockerEnvironmentSpec for testing."""
    return DockerEnvironmentSpec(
        type="docker",
        name="test-docker",
        commands=CommandConfig(command="python"),
        docker=DockerConfig(
            image="python:3.12-slim",
            workdir="/workspace",
        ),
    )


@pytest.fixture
def docker_spec_with_setup() -> DockerEnvironmentSpec:
    """Create a DockerEnvironmentSpec with setup commands."""
    return DockerEnvironmentSpec(
        type="docker",
        name="test-docker-setup",
        commands=CommandConfig(command="python"),
        setup=SetupConfig(
            commands=["echo 'setup command 1'"],
            eval_commands=["echo 'eval setup'"],
        ),
        docker=DockerConfig(
            image="python:3.12-slim",
            workdir="/workspace",
        ),
    )


@pytest.fixture
def docker_spec_with_mounts(tmp_path: Path) -> DockerEnvironmentSpec:
    """Create a DockerEnvironmentSpec with extra mounts."""
    mount_dir = tmp_path / "extra_mount"
    mount_dir.mkdir()
    (mount_dir / "mounted_file.txt").write_text("mounted content")

    return DockerEnvironmentSpec(
        type="docker",
        name="test-docker-mounts",
        commands=CommandConfig(command="python"),
        docker=DockerConfig(
            image="python:3.12-slim",
            workdir="/workspace",
            extra_mounts={str(mount_dir): "/extra"},
        ),
    )


@pytest.fixture
def docker_spec_host_network() -> DockerEnvironmentSpec:
    """Create a DockerEnvironmentSpec with host networking."""
    return DockerEnvironmentSpec(
        type="docker",
        name="test-docker-host",
        commands=CommandConfig(command="python"),
        docker=DockerConfig(
            image="python:3.12-slim",
            workdir="/workspace",
            network="host",
        ),
    )


@pytest.fixture
def mock_docker_client() -> MagicMock:
    """Create a mock Docker client."""
    client = MagicMock(spec=["containers", "close"])
    client.containers = MagicMock()
    return client


@pytest.fixture
def mock_container() -> MagicMock:
    """Create a mock Docker container."""
    container = MagicMock()
    container.id = "abc123def456"
    container.attrs = {"State": {"Status": "running"}}
    container.reload = MagicMock()
    container.start = MagicMock()
    container.stop = MagicMock()
    container.kill = MagicMock()
    container.remove = MagicMock()
    return container


@pytest.fixture
def mock_docker_client_with_container(
    mock_docker_client: MagicMock,
    mock_container: MagicMock,
) -> MagicMock:
    """Create a mock Docker client that returns a container."""
    mock_docker_client.containers.create.return_value = mock_container
    return mock_docker_client
