from pathlib import Path
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
import typer
import yaml
from pydantic import ValidationError

from slop_code.entrypoints.commands import common
from slop_code.execution import docker_runtime
from slop_code.execution import local_runtime


def test_validate_rubric_options_success():
    """Test validate_rubric_options with valid inputs."""
    # Both None - valid
    common.validate_rubric_options(None, None)

    # Both provided - valid
    common.validate_rubric_options(
        Path("rubric.jsonl"), "claude-3-opus-20240229"
    )


def test_validate_rubric_options_failure():
    """Test validate_rubric_options with invalid inputs."""
    # Path provided but no model
    with pytest.raises(typer.Exit) as excinfo:
        common.validate_rubric_options(Path("rubric.jsonl"), None)
    assert excinfo.value.exit_code == 1

    # Model provided but no path
    with pytest.raises(typer.Exit) as excinfo:
        common.validate_rubric_options(None, "claude-3-opus-20240229")
    assert excinfo.value.exit_code == 1


@patch("slop_code.entrypoints.commands.common.ProblemConfig.from_yaml")
def test_load_problem_config_or_exit_success(mock_from_yaml):
    """Test successful problem config loading."""
    mock_config = MagicMock()
    mock_from_yaml.return_value = mock_config

    result = common.load_problem_config_or_exit(Path("problem.yaml"))

    assert result == mock_config
    mock_from_yaml.assert_called_once_with(Path("problem.yaml"))


@patch("slop_code.entrypoints.commands.common.ProblemConfig.from_yaml")
def test_load_problem_config_or_exit_file_not_found(mock_from_yaml):
    """Test problem config loading when file not found."""
    mock_from_yaml.side_effect = FileNotFoundError()

    with pytest.raises(typer.Exit) as excinfo:
        common.load_problem_config_or_exit(Path("problem.yaml"))
    assert excinfo.value.exit_code == 1


@patch("slop_code.entrypoints.commands.common.ProblemConfig.from_yaml")
def test_load_problem_config_or_exit_yaml_error(mock_from_yaml):
    """Test problem config loading with YAML error."""
    mock_from_yaml.side_effect = yaml.YAMLError("parsing error")

    with pytest.raises(typer.Exit) as excinfo:
        common.load_problem_config_or_exit(Path("problem.yaml"))
    assert excinfo.value.exit_code == 1


@patch("slop_code.entrypoints.commands.common.ProblemConfig.from_yaml")
def test_load_problem_config_or_exit_validation_error(mock_from_yaml):
    """Test problem config loading with validation error."""
    mock_from_yaml.side_effect = ValidationError.from_exception_data(
        "Validation failed", []
    )

    with pytest.raises(typer.Exit) as excinfo:
        common.load_problem_config_or_exit(Path("problem.yaml"))
    assert excinfo.value.exit_code == 1


@patch("slop_code.execution.docker_runtime.build_base_image")
@patch("docker.from_env")
def test_ensure_docker_ready_docker_env(mock_docker_client, mock_build):
    """Test ensure_docker_ready with Docker environment."""
    env = MagicMock(spec=docker_runtime.DockerEnvironmentSpec)

    common.ensure_docker_ready(env)

    mock_docker_client.assert_called_once()
    mock_build.assert_called_once_with(
        client=mock_docker_client.return_value,
        environment_spec=env,
        force_build=False,
    )


@patch("slop_code.execution.docker_runtime.build_base_image")
def test_ensure_docker_ready_non_docker_env(mock_build):
    """Test ensure_docker_ready with non-Docker environment."""
    env = MagicMock(spec=local_runtime.LocalEnvironmentSpec)

    common.ensure_docker_ready(env)

    mock_build.assert_not_called()


@patch("slop_code.entrypoints.commands.common.setup_logging")
def test_setup_command_logging(mock_setup_logging):
    """Test setup_command_logging."""
    log_dir = Path("logs")
    verbosity = 1
    console = MagicMock()

    common.setup_command_logging(
        log_dir=log_dir,
        verbosity=verbosity,
        console=console,
        add_multiproc_info=True,
    )

    mock_setup_logging.assert_called_once_with(
        log_dir=log_dir,
        verbosity=verbosity,
        log_file_name="evaluation.log",
        console=console,
        add_multiproc_info=True,
    )


# Tests for new unified config_loader.resolve_environment()
# Note: These test the new unified function in config/loader.py


@patch("slop_code.entrypoints.config.loader._resolve_environment_config")
def test_resolve_environment_success_docker(mock_resolve):
    """Test successful Docker environment resolution."""
    from slop_code.entrypoints.config import loader as config_loader

    mock_resolve.return_value = (
        None,
        {
            "type": "docker",
            "name": "test-docker",
            "docker": {"image": "python:3.12", "workdir": "/workspace"},
        },
    )

    result = config_loader.resolve_environment(Path("env.yaml"))

    assert isinstance(result, docker_runtime.DockerEnvironmentSpec)
    assert result.name == "test-docker"


@patch("slop_code.entrypoints.config.loader._resolve_environment_config")
def test_resolve_environment_success_local(mock_resolve):
    """Test successful local environment resolution."""
    from slop_code.entrypoints.config import loader as config_loader

    mock_resolve.return_value = (None, {"type": "local", "name": "test-local"})

    result = config_loader.resolve_environment(Path("env.yaml"))

    assert isinstance(result, local_runtime.LocalEnvironmentSpec)
    assert result.name == "test-local"


@patch("slop_code.entrypoints.config.loader._resolve_environment_config")
def test_resolve_environment_file_not_found(mock_resolve):
    """Test environment resolution when file not found."""
    from slop_code.entrypoints.config import loader as config_loader

    mock_resolve.side_effect = FileNotFoundError("Config not found")

    with pytest.raises(typer.Exit) as excinfo:
        config_loader.resolve_environment(Path("env.yaml"))
    assert excinfo.value.exit_code == 1


@patch("slop_code.entrypoints.config.loader._resolve_environment_config")
def test_resolve_environment_yaml_error(mock_resolve):
    """Test environment resolution with YAML error."""
    from slop_code.entrypoints.config import loader as config_loader

    mock_resolve.side_effect = yaml.YAMLError("parsing error")

    with pytest.raises(typer.Exit) as excinfo:
        config_loader.resolve_environment(Path("env.yaml"))
    assert excinfo.value.exit_code == 1


@patch("slop_code.entrypoints.config.loader._resolve_environment_config")
def test_resolve_environment_validation_error(mock_resolve):
    """Test environment resolution with validation error."""
    from slop_code.entrypoints.config import loader as config_loader

    mock_resolve.return_value = (None, {"type": "docker", "name": "test"})
    # Missing required 'docker' field will cause ValidationError

    with pytest.raises(typer.Exit) as excinfo:
        config_loader.resolve_environment(Path("env.yaml"))
    assert excinfo.value.exit_code == 1


@patch("slop_code.entrypoints.config.loader._resolve_environment_config")
def test_resolve_environment_invalid_type(mock_resolve):
    """Test environment resolution with invalid type."""
    from slop_code.entrypoints.config import loader as config_loader

    mock_resolve.return_value = (None, {"type": "invalid", "name": "test"})

    with pytest.raises(typer.Exit) as excinfo:
        config_loader.resolve_environment(Path("env.yaml"))
    assert excinfo.value.exit_code == 1


@patch("slop_code.entrypoints.config.loader._resolve_environment_config")
def test_resolve_environment_accepts_dict(mock_resolve):
    """Test that resolve_environment accepts dict input."""
    from slop_code.entrypoints.config import loader as config_loader

    env_dict = {"type": "local", "name": "test-local"}
    mock_resolve.return_value = (None, env_dict)

    result = config_loader.resolve_environment(env_dict)

    assert isinstance(result, local_runtime.LocalEnvironmentSpec)
    mock_resolve.assert_called_once_with(env_dict)
