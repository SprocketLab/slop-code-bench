"""Integration tests for checkpoint resume functionality.

These tests verify that resume commands work correctly in a real Docker
environment with proper user permissions.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

from slop_code.execution.docker_runtime import DockerEnvironmentSpec
from slop_code.execution.docker_runtime import DockerExecRuntime
from slop_code.execution.runtime import RuntimeResult


def run_docker_command(
    env: DockerEnvironmentSpec,
    working_dir: Path,
    command: str,
    timeout: int = 120,
) -> RuntimeResult:
    """Run a single command in Docker and return the result."""
    runtime = DockerExecRuntime.spawn(
        environment=env,
        working_dir=working_dir,
        command=command,
        static_assets=None,
        ports={},
        mounts={},
        env_vars={},
        setup_command=None,
        is_evaluation=False,
        disable_setup=True,
    )
    try:
        return runtime.execute(env={}, stdin=None, timeout=timeout)
    finally:
        runtime.cleanup()


@pytest.fixture
def docker_python_env() -> DockerEnvironmentSpec:
    """Load the docker-python3.12-uv environment spec."""
    config_path = (
        Path(__file__).parent.parent.parent
        / "configs"
        / "environments"
        / "docker-python3.12-uv.yaml"
    )
    with config_path.open() as f:
        config = yaml.safe_load(f)
    return DockerEnvironmentSpec(**config)


def cleanup_as_root(path: Path) -> None:
    """Clean up a directory that may have root-owned files using docker."""
    if not path.exists():
        return
    # Use docker to remove files as root
    subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{path}:/cleanup",
            "alpine:latest",
            "rm",
            "-rf",
            "/cleanup",
        ],
        capture_output=True,
        check=False,
    )
    # Remove the now-empty directory
    if path.exists():
        path.rmdir()


@pytest.fixture
def workspace_dir(tmp_path: Path):
    """Create a workspace directory that gets properly cleaned up."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    yield workspace
    # Clean up any root-owned files created by docker
    cleanup_as_root(workspace)


@pytest.mark.integration
class TestResumeCommandsIntegration:
    """Integration tests for resume commands in Docker."""

    def test_resume_commands_create_venv(
        self,
        docker_python_env: DockerEnvironmentSpec,
        workspace_dir: Path,
        tmp_path: Path,
    ) -> None:
        """Test that resume commands create a working venv."""
        # Create a minimal snapshot with a requirements.txt
        snapshot_dir = tmp_path / "snapshot"
        snapshot_dir.mkdir()
        (snapshot_dir / "requirements.txt").write_text("requests==2.31.0\n")
        (snapshot_dir / "main.py").write_text("print('hello')\n")

        # Copy snapshot to workspace
        import shutil

        for item in snapshot_dir.iterdir():
            if item.is_dir():
                shutil.copytree(item, workspace_dir / item.name)
            else:
                shutil.copy2(item, workspace_dir / item.name)

        # Run resume commands
        resume_commands = docker_python_env.get_resume_commands()
        assert len(resume_commands) >= 2, "Expected at least 2 resume commands"

        for cmd in resume_commands:
            result = run_docker_command(
                docker_python_env, workspace_dir, cmd, timeout=120
            )
            # Commands use || true so should always succeed
            assert result.exit_code == 0, (
                f"Resume command failed: {cmd}\n"
                f"stdout: {result.stdout}\n"
                f"stderr: {result.stderr}"
            )

        # Verify venv was created
        result = run_docker_command(
            docker_python_env,
            workspace_dir,
            "test -d .venv && echo 'venv exists'",
            timeout=10,
        )
        assert "venv exists" in result.stdout, "venv directory not created"

        # Verify pip works in the venv
        result = run_docker_command(
            docker_python_env,
            workspace_dir,
            ".venv/bin/pip --version",
            timeout=30,
        )
        assert result.exit_code == 0, (
            f"pip not working in venv: {result.stderr}"
        )
        assert "pip" in result.stdout

        # Verify requests was installed
        result = run_docker_command(
            docker_python_env,
            workspace_dir,
            ".venv/bin/pip show requests",
            timeout=30,
        )
        assert result.exit_code == 0, f"requests not installed: {result.stderr}"
        assert "requests" in result.stdout.lower()

    def test_resume_commands_handle_missing_requirements(
        self,
        docker_python_env: DockerEnvironmentSpec,
        workspace_dir: Path,
        tmp_path: Path,
    ) -> None:
        """Test that resume commands don't fail when requirements.txt is missing."""
        # No requirements.txt - simulates a problem that doesn't need deps
        (workspace_dir / "main.py").write_text("print('no deps')\n")

        # All resume commands should succeed (they use || true)
        for cmd in docker_python_env.get_resume_commands():
            result = run_docker_command(
                docker_python_env, workspace_dir, cmd, timeout=120
            )
            assert result.exit_code == 0, (
                f"Resume command should not fail even without "
                f"requirements.txt: {cmd}\nstderr: {result.stderr}"
            )
