"""Tests for DockerStreamingRuntime."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from slop_code.execution.docker_runtime.models import DockerConfig
from slop_code.execution.docker_runtime.models import DockerEnvironmentSpec
from slop_code.execution.docker_runtime.streaming import DockerStreamingRuntime
from slop_code.execution.models import CommandConfig
from slop_code.execution.runtime import RuntimeEvent
from slop_code.execution.runtime import RuntimeResult
from slop_code.execution.runtime import SolutionRuntimeError
from slop_code.execution.shared import HANDLE_ENTRY_NAME

from .conftest import docker_available
from .conftest import test_image_available


class TestDockerStreamingRuntimeInit:
    """Tests for DockerStreamingRuntime initialization."""

    def test_init_stores_working_dir(
        self, docker_spec: DockerEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Working directory is stored."""
        with patch("slop_code.execution.docker_runtime.streaming.docker"):
            runtime = DockerStreamingRuntime(
                spec=docker_spec,
                working_dir=tmp_path,
                static_assets={},
                is_evaluation=False,
                ports={},
                mounts={},
                env_vars={},
                setup_command=None,
            )
            assert runtime.cwd == tmp_path

    def test_init_stores_spec(
        self, docker_spec: DockerEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Environment spec is stored."""
        with patch("slop_code.execution.docker_runtime.streaming.docker"):
            runtime = DockerStreamingRuntime(
                spec=docker_spec,
                working_dir=tmp_path,
                static_assets={},
                is_evaluation=False,
                ports={},
                mounts={},
                env_vars={},
                setup_command=None,
            )
            assert runtime.spec == docker_spec

    def test_init_container_is_none(
        self, docker_spec: DockerEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Container is None initially."""
        with patch("slop_code.execution.docker_runtime.streaming.docker"):
            runtime = DockerStreamingRuntime(
                spec=docker_spec,
                working_dir=tmp_path,
                static_assets={},
                is_evaluation=False,
                ports={},
                mounts={},
                env_vars={},
                setup_command=None,
            )
            assert runtime._container is None


class TestDockerStreamingRuntimeSpawn:
    """Tests for DockerStreamingRuntime.spawn()."""

    def test_spawn_creates_runtime(
        self, docker_spec: DockerEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Spawn creates a DockerStreamingRuntime instance."""
        with patch("slop_code.execution.docker_runtime.streaming.docker"):
            runtime = DockerStreamingRuntime.spawn(
                environment=docker_spec,
                working_dir=tmp_path,
            )
            assert isinstance(runtime, DockerStreamingRuntime)

    def test_spawn_rejects_wrong_environment_type(self, tmp_path: Path) -> None:
        """Spawn raises ValueError for wrong environment type."""
        mock_spec = MagicMock()
        mock_spec.type = "local"

        with pytest.raises(ValueError, match="Invalid environment spec"):
            DockerStreamingRuntime.spawn(
                environment=mock_spec,
                working_dir=tmp_path,
            )

    def test_spawn_passes_ports(
        self, docker_spec: DockerEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Spawn passes port mappings to runtime."""
        with patch("slop_code.execution.docker_runtime.streaming.docker"):
            runtime = DockerStreamingRuntime.spawn(
                environment=docker_spec,
                working_dir=tmp_path,
                ports={8080: 80, 3000: 3000},
            )
            assert runtime._ports == {8080: 80, 3000: 3000}

    def test_spawn_passes_mounts(
        self, docker_spec: DockerEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Spawn passes mount mappings to runtime."""
        with patch("slop_code.execution.docker_runtime.streaming.docker"):
            runtime = DockerStreamingRuntime.spawn(
                environment=docker_spec,
                working_dir=tmp_path,
                mounts={"/host/path": "/container/path"},
            )
            assert runtime._mounts == {"/host/path": "/container/path"}


class TestDockerStreamingRuntimeBuildVolumes:
    """Tests for _build_volumes method."""

    def test_mounts_workspace(
        self, docker_spec: DockerEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Workspace is mounted to container workdir."""
        with patch("slop_code.execution.docker_runtime.streaming.docker"):
            runtime = DockerStreamingRuntime(
                spec=docker_spec,
                working_dir=tmp_path,
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


class TestDockerStreamingRuntimeUser:
    """Tests for user property."""

    def test_user_from_constructor(
        self, docker_spec: DockerEnvironmentSpec, tmp_path: Path
    ) -> None:
        """User from constructor takes precedence."""
        with patch("slop_code.execution.docker_runtime.streaming.docker"):
            runtime = DockerStreamingRuntime(
                spec=docker_spec,
                working_dir=tmp_path,
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
        with patch("slop_code.execution.docker_runtime.streaming.docker"):
            runtime = DockerStreamingRuntime(
                spec=docker_spec,
                working_dir=tmp_path,
                static_assets={},
                is_evaluation=True,
                ports={},
                mounts={},
                env_vars={},
                setup_command=None,
            )
            assert runtime.user == "1000:1000"


class TestDockerStreamingRuntimeContainer:
    """Tests for container property."""

    def test_container_raises_when_not_created(
        self, docker_spec: DockerEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Container property raises when no container exists."""
        with patch("slop_code.execution.docker_runtime.streaming.docker"):
            runtime = DockerStreamingRuntime(
                spec=docker_spec,
                working_dir=tmp_path,
                static_assets={},
                is_evaluation=False,
                ports={},
                mounts={},
                env_vars={},
                setup_command=None,
            )
            with pytest.raises(
                SolutionRuntimeError, match="Container not created"
            ):
                _ = runtime.container


class TestDockerStreamingRuntimeEnsureContainerRunning:
    """Tests for _ensure_container_running method."""

    def test_creates_container_when_none(
        self,
        docker_spec: DockerEnvironmentSpec,
        tmp_path: Path,
        mock_docker_client_with_container: MagicMock,
    ) -> None:
        """Creates container when none exists."""
        with patch(
            "slop_code.execution.docker_runtime.streaming.docker.from_env",
            return_value=mock_docker_client_with_container,
        ):
            runtime = DockerStreamingRuntime(
                spec=docker_spec,
                working_dir=tmp_path,
                static_assets={},
                is_evaluation=False,
                ports={},
                mounts={},
                env_vars={},
                setup_command=None,
            )
            container = runtime._ensure_container_running()
            assert container is not None
            mock_docker_client_with_container.containers.create.assert_called_once()


class TestDockerStreamingRuntimePrepareCommand:
    """Tests for _prepare_command method."""

    def test_writes_entry_script(
        self, docker_spec: DockerEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Writes entry script when setup not disabled."""
        with patch("slop_code.execution.docker_runtime.streaming.docker"):
            runtime = DockerStreamingRuntime(
                spec=docker_spec,
                working_dir=tmp_path,
                static_assets={},
                is_evaluation=False,
                ports={},
                mounts={},
                env_vars={},
                setup_command=None,
            )
            command = runtime._prepare_command("echo test")
            assert (tmp_path / HANDLE_ENTRY_NAME).exists()
            assert HANDLE_ENTRY_NAME in command

    def test_returns_command_directly_when_disabled(
        self, docker_spec: DockerEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Returns command directly when disable_setup=True."""
        with patch("slop_code.execution.docker_runtime.streaming.docker"):
            runtime = DockerStreamingRuntime(
                spec=docker_spec,
                working_dir=tmp_path,
                static_assets={},
                is_evaluation=False,
                ports={},
                mounts={},
                env_vars={},
                setup_command=None,
                disable_setup=True,
            )
            command = runtime._prepare_command("echo test")
            assert command == "echo test"
            assert not (tmp_path / HANDLE_ENTRY_NAME).exists()


class TestDockerStreamingRuntimePoll:
    """Tests for DockerStreamingRuntime.poll()."""

    def test_poll_returns_none_when_no_exec(
        self, docker_spec: DockerEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Poll returns None when no exec process is running."""
        with patch("slop_code.execution.docker_runtime.streaming.docker"):
            runtime = DockerStreamingRuntime(
                spec=docker_spec,
                working_dir=tmp_path,
                static_assets={},
                is_evaluation=False,
                ports={},
                mounts={},
                env_vars={},
                setup_command=None,
            )
            assert runtime.poll() is None


class TestDockerStreamingRuntimeKill:
    """Tests for DockerStreamingRuntime.kill()."""

    def test_kill_is_safe_when_no_container(
        self, docker_spec: DockerEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Kill is safe to call when no container exists."""
        with patch("slop_code.execution.docker_runtime.streaming.docker"):
            runtime = DockerStreamingRuntime(
                spec=docker_spec,
                working_dir=tmp_path,
                static_assets={},
                is_evaluation=False,
                ports={},
                mounts={},
                env_vars={},
                setup_command=None,
            )
            # Should not raise
            runtime.kill()


class TestDockerStreamingRuntimeCleanup:
    """Tests for DockerStreamingRuntime.cleanup()."""

    def test_cleanup_is_idempotent(
        self, docker_spec: DockerEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Cleanup can be called multiple times safely."""
        with patch("slop_code.execution.docker_runtime.streaming.docker"):
            runtime = DockerStreamingRuntime(
                spec=docker_spec,
                working_dir=tmp_path,
                static_assets={},
                is_evaluation=False,
                ports={},
                mounts={},
                env_vars={},
                setup_command=None,
            )
            # Should not raise on multiple calls
            runtime.cleanup()
            runtime.cleanup()
            runtime.cleanup()


# Integration tests - require real Docker
@docker_available
@test_image_available
class TestDockerStreamingRuntimeIntegration:
    """Integration tests for DockerStreamingRuntime (require Docker)."""

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

    def test_stream_yields_events(
        self, integration_spec: DockerEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Stream yields RuntimeEvent objects."""
        runtime = DockerStreamingRuntime.spawn(
            environment=integration_spec,
            working_dir=tmp_path,
            disable_setup=True,
        )
        try:
            events = list(runtime.stream("echo hello", env={}, timeout=30))
            assert len(events) > 0
            assert all(isinstance(e, RuntimeEvent) for e in events)
        finally:
            runtime.cleanup()

    def test_stream_captures_stdout(
        self, integration_spec: DockerEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Stream captures stdout in events."""
        runtime = DockerStreamingRuntime.spawn(
            environment=integration_spec,
            working_dir=tmp_path,
            disable_setup=True,
        )
        try:
            events = list(
                runtime.stream("echo hello_docker", env={}, timeout=30)
            )
            stdout_events = [e for e in events if e.kind == "stdout"]
            stdout_text = "".join(e.text for e in stdout_events if e.text)
            assert "hello_docker" in stdout_text
        finally:
            runtime.cleanup()

    def test_stream_captures_stderr(
        self, integration_spec: DockerEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Stream captures stderr in events."""
        runtime = DockerStreamingRuntime.spawn(
            environment=integration_spec,
            working_dir=tmp_path,
            disable_setup=True,
        )
        try:
            events = list(
                runtime.stream("echo error_msg >&2", env={}, timeout=30)
            )
            stderr_events = [e for e in events if e.kind == "stderr"]
            stderr_text = "".join(e.text for e in stderr_events if e.text)
            assert "error_msg" in stderr_text
        finally:
            runtime.cleanup()

    def test_stream_ends_with_finished(
        self, integration_spec: DockerEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Stream ends with a finished event."""
        runtime = DockerStreamingRuntime.spawn(
            environment=integration_spec,
            working_dir=tmp_path,
            disable_setup=True,
        )
        try:
            events = list(runtime.stream("echo test", env={}, timeout=30))
            assert events[-1].kind == "finished"
        finally:
            runtime.cleanup()

    def test_stream_finished_has_result(
        self, integration_spec: DockerEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Finished event contains RuntimeResult."""
        runtime = DockerStreamingRuntime.spawn(
            environment=integration_spec,
            working_dir=tmp_path,
            disable_setup=True,
        )
        try:
            events = list(runtime.stream("echo test", env={}, timeout=30))
            finished = events[-1]
            assert finished.result is not None
            assert isinstance(finished.result, RuntimeResult)
        finally:
            runtime.cleanup()

    def test_stream_exit_code(
        self, integration_spec: DockerEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Finished event has correct exit code."""
        runtime = DockerStreamingRuntime.spawn(
            environment=integration_spec,
            working_dir=tmp_path,
            disable_setup=True,
        )
        try:
            events = list(runtime.stream("exit 42", env={}, timeout=30))
            finished = events[-1]
            assert finished.result.exit_code == 42
        finally:
            runtime.cleanup()

    def test_stream_with_environment_variables(
        self, integration_spec: DockerEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Stream passes environment variables to container."""
        runtime = DockerStreamingRuntime.spawn(
            environment=integration_spec,
            working_dir=tmp_path,
            disable_setup=True,
        )
        try:
            events = list(
                runtime.stream(
                    'echo "$TEST_VAR"',
                    env={"TEST_VAR": "docker_streaming_value"},
                    timeout=30,
                )
            )
            stdout_events = [e for e in events if e.kind == "stdout"]
            stdout_text = "".join(e.text for e in stdout_events if e.text)
            assert "docker_streaming_value" in stdout_text
        finally:
            runtime.cleanup()

    def test_stream_multiple_commands(
        self, integration_spec: DockerEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Multiple stream calls work on same container."""
        runtime = DockerStreamingRuntime.spawn(
            environment=integration_spec,
            working_dir=tmp_path,
            disable_setup=True,
        )
        try:
            # First command
            events1 = list(runtime.stream("echo first", env={}, timeout=30))
            assert events1[-1].kind == "finished"

            # Second command
            events2 = list(runtime.stream("echo second", env={}, timeout=30))
            assert events2[-1].kind == "finished"

            # Both should have output
            stdout1 = "".join(
                e.text for e in events1 if e.kind == "stdout" and e.text
            )
            stdout2 = "".join(
                e.text for e in events2 if e.kind == "stdout" and e.text
            )
            assert "first" in stdout1
            assert "second" in stdout2
        finally:
            runtime.cleanup()

    def test_stream_file_io(
        self, integration_spec: DockerEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Stream can read/write files in workspace."""
        test_file = tmp_path / "input.txt"
        test_file.write_text("docker streaming content")

        runtime = DockerStreamingRuntime.spawn(
            environment=integration_spec,
            working_dir=tmp_path,
            disable_setup=True,
        )
        try:
            events = list(runtime.stream("cat input.txt", env={}, timeout=30))
            stdout_text = "".join(
                e.text for e in events if e.kind == "stdout" and e.text
            )
            assert "docker streaming content" in stdout_text
        finally:
            runtime.cleanup()

    def test_stream_timeout(
        self, integration_spec: DockerEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Stream handles timeout correctly."""
        runtime = DockerStreamingRuntime.spawn(
            environment=integration_spec,
            working_dir=tmp_path,
            disable_setup=True,
        )
        try:
            events = list(runtime.stream("sleep 60", env={}, timeout=1))
            finished = events[-1]
            assert finished.result.timed_out is True
        finally:
            runtime.cleanup()

    def test_container_persists_between_commands(
        self, integration_spec: DockerEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Container state persists between stream calls."""
        runtime = DockerStreamingRuntime.spawn(
            environment=integration_spec,
            working_dir=tmp_path,
            disable_setup=True,
        )
        try:
            # Create a file
            list(runtime.stream("touch /tmp/test_file", env={}, timeout=30))

            # Verify it exists
            events = list(
                runtime.stream("ls -la /tmp/test_file", env={}, timeout=30)
            )
            stdout_text = "".join(
                e.text for e in events if e.kind == "stdout" and e.text
            )
            assert "test_file" in stdout_text
        finally:
            runtime.cleanup()

    def test_workspace_persists_between_commands(
        self, integration_spec: DockerEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Workspace changes persist between stream calls."""
        runtime = DockerStreamingRuntime.spawn(
            environment=integration_spec,
            working_dir=tmp_path,
            disable_setup=True,
        )
        try:
            # Create a file in workspace
            list(
                runtime.stream(
                    "echo 'streaming test' > test.txt", env={}, timeout=30
                )
            )

            # Verify it exists
            events = list(runtime.stream("cat test.txt", env={}, timeout=30))
            stdout_text = "".join(
                e.text for e in events if e.kind == "stdout" and e.text
            )
            assert "streaming test" in stdout_text
        finally:
            runtime.cleanup()
