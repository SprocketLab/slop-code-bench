"""Tests for DockerExecRuntime."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from slop_code.execution.docker_runtime.exec import DockerExecRuntime
from slop_code.execution.docker_runtime.models import DockerConfig
from slop_code.execution.docker_runtime.models import DockerEnvironmentSpec
from slop_code.execution.models import CommandConfig
from slop_code.execution.models import SetupConfig
from slop_code.execution.runtime import RuntimeResult
from slop_code.execution.shared import HANDLE_ENTRY_NAME

from .conftest import docker_available
from .conftest import test_image_available


class TestDockerExecRuntimeInit:
    """Tests for DockerExecRuntime initialization."""

    def test_init_stores_command(
        self, docker_spec: DockerEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Command is stored on the runtime."""
        with patch("slop_code.execution.docker_runtime.exec.docker"):
            runtime = DockerExecRuntime(
                spec=docker_spec,
                working_dir=tmp_path,
                command="echo hello",
                static_assets={},
                is_evaluation=False,
                ports={},
                mounts={},
                env_vars={},
                setup_command=None,
            )
            assert runtime._command == "echo hello"

    def test_init_stores_working_dir(
        self, docker_spec: DockerEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Working directory is stored."""
        with patch("slop_code.execution.docker_runtime.exec.docker"):
            runtime = DockerExecRuntime(
                spec=docker_spec,
                working_dir=tmp_path,
                command="echo test",
                static_assets={},
                is_evaluation=False,
                ports={},
                mounts={},
                env_vars={},
                setup_command=None,
            )
            assert runtime.cwd == tmp_path

    def test_init_stores_env_vars(
        self, docker_spec: DockerEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Environment variables are stored."""
        with patch("slop_code.execution.docker_runtime.exec.docker"):
            runtime = DockerExecRuntime(
                spec=docker_spec,
                working_dir=tmp_path,
                command="echo test",
                static_assets={},
                is_evaluation=False,
                ports={},
                mounts={},
                env_vars={"MY_VAR": "my_value"},
                setup_command=None,
            )
            assert runtime._env_vars == {"MY_VAR": "my_value"}


class TestDockerExecRuntimeSpawn:
    """Tests for DockerExecRuntime.spawn()."""

    def test_spawn_creates_runtime(
        self, docker_spec: DockerEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Spawn creates a DockerExecRuntime instance."""
        with patch("slop_code.execution.docker_runtime.exec.docker"):
            runtime = DockerExecRuntime.spawn(
                environment=docker_spec,
                working_dir=tmp_path,
                command="echo test",
            )
            assert isinstance(runtime, DockerExecRuntime)

    def test_spawn_rejects_wrong_environment_type(self, tmp_path: Path) -> None:
        """Spawn raises ValueError for wrong environment type."""
        mock_spec = MagicMock()
        mock_spec.type = "local"

        with pytest.raises(ValueError, match="Invalid environment spec"):
            DockerExecRuntime.spawn(
                environment=mock_spec,
                working_dir=tmp_path,
                command="echo test",
            )

    def test_spawn_passes_ports(
        self, docker_spec: DockerEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Spawn passes port mappings to runtime."""
        with patch("slop_code.execution.docker_runtime.exec.docker"):
            runtime = DockerExecRuntime.spawn(
                environment=docker_spec,
                working_dir=tmp_path,
                command="echo test",
                ports={8080: 80, 3000: 3000},
            )
            assert runtime._ports == {8080: 80, 3000: 3000}


class TestDockerExecRuntimeBuildVolumes:
    """Tests for _build_volumes method."""

    def test_mounts_workspace(
        self, docker_spec: DockerEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Workspace is mounted to container workdir."""
        with patch("slop_code.execution.docker_runtime.exec.docker"):
            runtime = DockerExecRuntime(
                spec=docker_spec,
                working_dir=tmp_path,
                command="echo test",
                static_assets={},
                is_evaluation=False,
                ports={},
                mounts={},
                env_vars={},
                setup_command=None,
            )
            volumes = runtime._build_volumes()
            assert str(tmp_path) in volumes
            assert volumes[str(tmp_path)]["bind"] == "/workspace"
            assert volumes[str(tmp_path)]["mode"] == "rw"

    def test_mounts_extra_mounts(
        self, docker_spec_with_mounts: DockerEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Extra mounts from spec are included."""
        with patch("slop_code.execution.docker_runtime.exec.docker"):
            runtime = DockerExecRuntime(
                spec=docker_spec_with_mounts,
                working_dir=tmp_path,
                command="echo test",
                static_assets={},
                is_evaluation=False,
                ports={},
                mounts={},
                env_vars={},
                setup_command=None,
            )
            volumes = runtime._build_volumes()
            # Should have workspace + extra mount
            assert len(volumes) >= 2

    def test_mounts_runtime_mounts(
        self, docker_spec: DockerEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Runtime-specified mounts are included."""
        extra_mount = tmp_path / "runtime_mount"
        extra_mount.mkdir()

        with patch("slop_code.execution.docker_runtime.exec.docker"):
            runtime = DockerExecRuntime(
                spec=docker_spec,
                working_dir=tmp_path,
                command="echo test",
                static_assets={},
                is_evaluation=False,
                ports={},
                mounts={str(extra_mount): "/runtime_mount"},
                env_vars={},
                setup_command=None,
            )
            volumes = runtime._build_volumes()
            assert str(extra_mount) in volumes


class TestDockerExecRuntimeBuildDockerRunCommand:
    """Tests for _build_docker_run_command method."""

    def test_includes_image(
        self, docker_spec: DockerEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Docker run command includes the image."""
        with patch("slop_code.execution.docker_runtime.exec.docker"):
            runtime = DockerExecRuntime(
                spec=docker_spec,
                working_dir=tmp_path,
                command="echo test",
                static_assets={},
                is_evaluation=False,
                ports={},
                mounts={},
                env_vars={},
                setup_command=None,
            )
            args = runtime._build_docker_run_command({})
            # Image should be in args
            assert any("slop-code:" in arg for arg in args)

    def test_includes_rm_flag(
        self, docker_spec: DockerEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Docker run command includes --rm flag."""
        with patch("slop_code.execution.docker_runtime.exec.docker"):
            runtime = DockerExecRuntime(
                spec=docker_spec,
                working_dir=tmp_path,
                command="echo test",
                static_assets={},
                is_evaluation=False,
                ports={},
                mounts={},
                env_vars={},
                setup_command=None,
            )
            args = runtime._build_docker_run_command({})
            assert "--rm" in args

    def test_includes_workdir(
        self, docker_spec: DockerEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Docker run command includes workdir."""
        with patch("slop_code.execution.docker_runtime.exec.docker"):
            runtime = DockerExecRuntime(
                spec=docker_spec,
                working_dir=tmp_path,
                command="echo test",
                static_assets={},
                is_evaluation=False,
                ports={},
                mounts={},
                env_vars={},
                setup_command=None,
            )
            args = runtime._build_docker_run_command({})
            assert "--workdir" in args
            workdir_idx = args.index("--workdir")
            assert args[workdir_idx + 1] == "/workspace"

    def test_includes_network_mode(
        self, docker_spec: DockerEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Docker run command includes network mode."""
        with patch("slop_code.execution.docker_runtime.exec.docker"):
            runtime = DockerExecRuntime(
                spec=docker_spec,
                working_dir=tmp_path,
                command="echo test",
                static_assets={},
                is_evaluation=False,
                ports={},
                mounts={},
                env_vars={},
                setup_command=None,
            )
            args = runtime._build_docker_run_command({})
            assert "--network" in args

    def test_includes_environment_variables(
        self, docker_spec: DockerEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Docker run command includes environment variables."""
        with patch("slop_code.execution.docker_runtime.exec.docker"):
            runtime = DockerExecRuntime(
                spec=docker_spec,
                working_dir=tmp_path,
                command="echo test",
                static_assets={},
                is_evaluation=False,
                ports={},
                mounts={},
                env_vars={"TEST_VAR": "test_value"},
                setup_command=None,
            )
            args = runtime._build_docker_run_command({})
            # Should have -e flag with variable
            assert "-e" in args

    def test_includes_user_when_set(
        self, docker_spec: DockerEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Docker run command includes user when specified."""
        with patch("slop_code.execution.docker_runtime.exec.docker"):
            runtime = DockerExecRuntime(
                spec=docker_spec,
                working_dir=tmp_path,
                command="echo test",
                static_assets={},
                is_evaluation=True,  # Evaluation uses user
                ports={},
                mounts={},
                env_vars={},
                setup_command=None,
            )
            args = runtime._build_docker_run_command({})
            assert "--user" in args

    def test_writes_entry_script(
        self, docker_spec: DockerEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Docker run command writes entry script when setup not disabled."""
        with patch("slop_code.execution.docker_runtime.exec.docker"):
            runtime = DockerExecRuntime(
                spec=docker_spec,
                working_dir=tmp_path,
                command="echo test",
                static_assets={},
                is_evaluation=False,
                ports={},
                mounts={},
                env_vars={},
                setup_command=None,
            )
            runtime._build_docker_run_command({})
            # Entry script should be written
            assert (tmp_path / HANDLE_ENTRY_NAME).exists()

    def test_skips_entry_script_when_disabled(
        self, docker_spec: DockerEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Docker run command skips entry script when disable_setup=True."""
        with patch("slop_code.execution.docker_runtime.exec.docker"):
            runtime = DockerExecRuntime(
                spec=docker_spec,
                working_dir=tmp_path,
                command="echo test",
                static_assets={},
                is_evaluation=False,
                ports={},
                mounts={},
                env_vars={},
                setup_command=None,
                disable_setup=True,
            )
            runtime._build_docker_run_command({})
            # Entry script should NOT be written
            assert not (tmp_path / HANDLE_ENTRY_NAME).exists()


class TestDockerExecRuntimeUser:
    """Tests for user property."""

    def test_user_from_constructor(
        self, docker_spec: DockerEnvironmentSpec, tmp_path: Path
    ) -> None:
        """User from constructor takes precedence."""
        with patch("slop_code.execution.docker_runtime.exec.docker"):
            runtime = DockerExecRuntime(
                spec=docker_spec,
                working_dir=tmp_path,
                command="echo test",
                static_assets={},
                is_evaluation=False,
                ports={},
                mounts={},
                env_vars={},
                setup_command=None,
                user="custom:user",
            )
            assert runtime.user == "custom:user"

    def test_user_for_evaluation(
        self, docker_spec: DockerEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Evaluation context uses eval user."""
        with patch("slop_code.execution.docker_runtime.exec.docker"):
            runtime = DockerExecRuntime(
                spec=docker_spec,
                working_dir=tmp_path,
                command="echo test",
                static_assets={},
                is_evaluation=True,
                ports={},
                mounts={},
                env_vars={},
                setup_command=None,
            )
            assert runtime.user == "1000:1000"


class TestDockerExecRuntimeResolvePorts:
    """Tests for _resolve_ports method."""

    def test_returns_ports_for_bridge(
        self, docker_spec: DockerEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Returns ports for bridge networking."""
        with patch("slop_code.execution.docker_runtime.exec.docker"):
            runtime = DockerExecRuntime(
                spec=docker_spec,
                working_dir=tmp_path,
                command="echo test",
                static_assets={},
                is_evaluation=False,
                ports={8080: 80},
                mounts={},
                env_vars={},
                setup_command=None,
            )
            ports = runtime._resolve_ports()
            assert ports == {8080: 80}

    def test_returns_none_for_host_network(
        self, docker_spec_host_network: DockerEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Returns None for host networking (ports not needed)."""
        with patch("slop_code.execution.docker_runtime.exec.docker"):
            with patch("platform.system", return_value="Linux"):
                runtime = DockerExecRuntime(
                    spec=docker_spec_host_network,
                    working_dir=tmp_path,
                    command="echo test",
                    static_assets={},
                    is_evaluation=False,
                    ports={8080: 80},
                    mounts={},
                    env_vars={},
                    setup_command=None,
                )
                ports = runtime._resolve_ports()
                assert ports is None


class TestDockerExecRuntimePoll:
    """Tests for DockerExecRuntime.poll()."""

    def test_poll_returns_none_before_execute(
        self, docker_spec: DockerEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Poll returns None before execute is called."""
        with patch("slop_code.execution.docker_runtime.exec.docker"):
            runtime = DockerExecRuntime.spawn(
                environment=docker_spec,
                working_dir=tmp_path,
                command="echo test",
            )
            assert runtime.poll() is None


class TestDockerExecRuntimeKill:
    """Tests for DockerExecRuntime.kill()."""

    def test_kill_is_safe_when_no_process(
        self, docker_spec: DockerEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Kill is safe to call when no process is running."""
        with patch("slop_code.execution.docker_runtime.exec.docker"):
            runtime = DockerExecRuntime.spawn(
                environment=docker_spec,
                working_dir=tmp_path,
                command="echo test",
            )
            # Should not raise
            runtime.kill()


class TestDockerExecRuntimeCleanup:
    """Tests for DockerExecRuntime.cleanup()."""

    def test_cleanup_is_idempotent(
        self, docker_spec: DockerEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Cleanup can be called multiple times safely."""
        with patch("slop_code.execution.docker_runtime.exec.docker"):
            runtime = DockerExecRuntime.spawn(
                environment=docker_spec,
                working_dir=tmp_path,
                command="echo test",
            )
            # Should not raise on multiple calls
            runtime.cleanup()
            runtime.cleanup()
            runtime.cleanup()


# Integration tests - require real Docker
@docker_available
@test_image_available
class TestDockerExecRuntimeIntegration:
    """Integration tests for DockerExecRuntime (require Docker)."""

    @pytest.fixture
    def integration_spec(self) -> DockerEnvironmentSpec:
        """Create a spec that uses an actual Docker image."""
        return DockerEnvironmentSpec(
            type="docker",
            name="python3.12",
            commands=CommandConfig(command="python"),
            docker=DockerConfig(
                image="slop-code:python3.12",
                workdir="/workspace",
            ),
        )

    def test_execute_returns_runtime_result(
        self, integration_spec: DockerEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Execute returns a RuntimeResult."""
        runtime = DockerExecRuntime.spawn(
            environment=integration_spec,
            working_dir=tmp_path,
            command="echo hello",
            disable_setup=True,
        )
        try:
            result = runtime.execute(env={}, stdin=None, timeout=30)
            assert isinstance(result, RuntimeResult)
        finally:
            runtime.cleanup()

    def test_execute_captures_stdout(
        self, integration_spec: DockerEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Execute captures stdout."""
        runtime = DockerExecRuntime.spawn(
            environment=integration_spec,
            working_dir=tmp_path,
            command="echo hello_docker",
            disable_setup=True,
        )
        try:
            result = runtime.execute(env={}, stdin=None, timeout=30)
            assert "hello_docker" in result.stdout
        finally:
            runtime.cleanup()

    def test_execute_captures_stderr(
        self, integration_spec: DockerEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Execute captures stderr."""
        runtime = DockerExecRuntime.spawn(
            environment=integration_spec,
            working_dir=tmp_path,
            command="sh -c 'echo error_msg >&2'",
            disable_setup=True,
        )
        try:
            result = runtime.execute(env={}, stdin=None, timeout=30)
            assert "error_msg" in result.stderr
        finally:
            runtime.cleanup()

    def test_execute_returns_exit_code(
        self, integration_spec: DockerEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Execute returns correct exit code."""
        runtime = DockerExecRuntime.spawn(
            environment=integration_spec,
            working_dir=tmp_path,
            command="sh -c 'exit 42'",
            disable_setup=True,
        )
        try:
            result = runtime.execute(env={}, stdin=None, timeout=30)
            assert result.exit_code == 42
        finally:
            runtime.cleanup()

    def test_execute_with_stdin(
        self, integration_spec: DockerEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Execute passes stdin to container."""
        runtime = DockerExecRuntime.spawn(
            environment=integration_spec,
            working_dir=tmp_path,
            command="cat",
            disable_setup=True,
        )
        try:
            result = runtime.execute(
                env={}, stdin="hello from stdin", timeout=30
            )
            assert "hello from stdin" in result.stdout
        finally:
            runtime.cleanup()

    def test_execute_with_environment_variables(
        self, integration_spec: DockerEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Execute passes environment variables to container."""
        runtime = DockerExecRuntime.spawn(
            environment=integration_spec,
            working_dir=tmp_path,
            command="sh -c 'echo $TEST_VAR'",
            disable_setup=True,
        )
        try:
            result = runtime.execute(
                env={"TEST_VAR": "docker_test_value"}, stdin=None, timeout=30
            )
            assert "docker_test_value" in result.stdout
        finally:
            runtime.cleanup()

    def test_execute_timeout(
        self, integration_spec: DockerEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Execute handles timeout correctly."""
        runtime = DockerExecRuntime.spawn(
            environment=integration_spec,
            working_dir=tmp_path,
            command="sleep 60",
            disable_setup=True,
        )
        try:
            result = runtime.execute(env={}, stdin=None, timeout=1)
            assert result.timed_out is True
        finally:
            runtime.cleanup()

    def test_execute_file_io(
        self, integration_spec: DockerEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Execute can read/write files in workspace."""
        test_file = tmp_path / "input.txt"
        test_file.write_text("docker file content")

        runtime = DockerExecRuntime.spawn(
            environment=integration_spec,
            working_dir=tmp_path,
            command="cat input.txt",
            disable_setup=True,
        )
        try:
            result = runtime.execute(env={}, stdin=None, timeout=30)
            assert "docker file content" in result.stdout
        finally:
            runtime.cleanup()

    def test_execute_with_setup_commands(
        self, integration_spec: DockerEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Execute runs setup commands and separates output."""
        spec = DockerEnvironmentSpec(
            type="docker",
            name="python3.12",
            commands=CommandConfig(command="python"),
            setup=SetupConfig(
                commands=["echo setup_output"],
            ),
            docker=DockerConfig(
                image="slop-code:python3.12",
                workdir="/workspace",
            ),
        )

        runtime = DockerExecRuntime.spawn(
            environment=spec,
            working_dir=tmp_path,
            command="echo main_output",
        )
        try:
            result = runtime.execute(env={}, stdin=None, timeout=30)
            assert "setup_output" in result.setup_stdout
            assert "main_output" in result.stdout
        finally:
            runtime.cleanup()
