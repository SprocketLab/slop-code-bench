"""Tests for LocalExecRuntime."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from slop_code.execution.local_exec import LocalExecRuntime
from slop_code.execution.local_streaming import LocalEnvironmentSpec
from slop_code.execution.models import CommandConfig
from slop_code.execution.models import SetupConfig
from slop_code.execution.runtime import RuntimeResult


@pytest.fixture
def local_spec() -> LocalEnvironmentSpec:
    """Create a LocalEnvironmentSpec for testing."""
    return LocalEnvironmentSpec(
        type="local",
        name="test-local",
        commands=CommandConfig(command="python"),
    )


@pytest.fixture
def local_spec_with_setup() -> LocalEnvironmentSpec:
    """Create a LocalEnvironmentSpec with setup commands."""
    return LocalEnvironmentSpec(
        type="local",
        name="test-local-setup",
        commands=CommandConfig(command="python"),
        setup=SetupConfig(
            commands=["echo 'setup command 1'"],
            eval_commands=["echo 'eval setup'"],
        ),
    )


class TestLocalExecRuntimeInit:
    """Tests for LocalExecRuntime initialization."""

    def test_init_stores_command(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Command is stored on the runtime."""
        runtime = LocalExecRuntime(
            environment=local_spec,
            working_dir=tmp_path,
            command="echo hello",
        )
        assert runtime._command == "echo hello"

    def test_init_stores_working_dir(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Working directory is stored."""
        runtime = LocalExecRuntime(
            environment=local_spec,
            working_dir=tmp_path,
            command="echo test",
        )
        assert runtime.cwd == tmp_path

    def test_init_stores_env_vars(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Environment variables are stored."""
        runtime = LocalExecRuntime(
            environment=local_spec,
            working_dir=tmp_path,
            command="echo test",
            env_vars={"MY_VAR": "my_value"},
        )
        assert runtime._env_vars == {"MY_VAR": "my_value"}


class TestLocalExecRuntimeSpawn:
    """Tests for LocalExecRuntime.spawn()."""

    def test_spawn_creates_runtime(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Spawn creates a LocalExecRuntime instance."""
        runtime = LocalExecRuntime.spawn(
            environment=local_spec,
            working_dir=tmp_path,
            command="echo test",
        )
        assert isinstance(runtime, LocalExecRuntime)

    def test_spawn_rejects_wrong_environment_type(self, tmp_path: Path) -> None:
        """Spawn raises ValueError for wrong environment type."""
        # Create a mock environment spec that isn't LocalEnvironmentSpec
        mock_spec = MagicMock()
        mock_spec.type = "docker"

        with pytest.raises(ValueError, match="Invalid environment spec"):
            LocalExecRuntime.spawn(
                environment=mock_spec,
                working_dir=tmp_path,
                command="echo test",
            )

    def test_spawn_runs_setup_commands(
        self, local_spec_with_setup: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Spawn runs setup commands during creation."""
        marker_file = tmp_path / "setup_ran"

        spec = LocalEnvironmentSpec(
            type="local",
            name="test",
            commands=CommandConfig(command="python"),
            setup=SetupConfig(
                commands=[f"touch {marker_file}"],
            ),
        )

        LocalExecRuntime.spawn(
            environment=spec,
            working_dir=tmp_path,
            command="echo test",
        )

        assert marker_file.exists()

    def test_spawn_with_disable_setup(
        self, local_spec_with_setup: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Spawn skips setup commands when disable_setup=True."""
        marker_file = tmp_path / "should_not_exist"

        spec = LocalEnvironmentSpec(
            type="local",
            name="test",
            commands=CommandConfig(command="python"),
            setup=SetupConfig(
                commands=[f"touch {marker_file}"],
            ),
        )

        LocalExecRuntime.spawn(
            environment=spec,
            working_dir=tmp_path,
            command="echo test",
            disable_setup=True,
        )

        assert not marker_file.exists()

    def test_spawn_passes_env_vars_to_setup(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Setup commands receive environment variables."""
        output_file = tmp_path / "env_output"

        spec = LocalEnvironmentSpec(
            type="local",
            name="test",
            commands=CommandConfig(command="python"),
            setup=SetupConfig(
                commands=[f'sh -c \'echo "$TEST_VAR" > {output_file}\''],
            ),
        )

        LocalExecRuntime.spawn(
            environment=spec,
            working_dir=tmp_path,
            command="echo test",
            env_vars={"TEST_VAR": "hello_from_env"},
        )

        assert "hello_from_env" in output_file.read_text()


class TestLocalExecRuntimeExecute:
    """Tests for LocalExecRuntime.execute()."""

    def test_execute_returns_runtime_result(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Execute returns a RuntimeResult."""
        runtime = LocalExecRuntime.spawn(
            environment=local_spec,
            working_dir=tmp_path,
            command="echo hello",
        )
        result = runtime.execute(env={}, stdin=None, timeout=10)
        assert isinstance(result, RuntimeResult)

    def test_execute_captures_stdout(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Execute captures stdout."""
        runtime = LocalExecRuntime.spawn(
            environment=local_spec,
            working_dir=tmp_path,
            command="echo hello_world",
        )
        result = runtime.execute(env={}, stdin=None, timeout=10)
        assert "hello_world" in result.stdout

    def test_execute_captures_stderr(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Execute captures stderr."""
        runtime = LocalExecRuntime.spawn(
            environment=local_spec,
            working_dir=tmp_path,
            command="sh -c 'echo error_msg >&2'",
        )
        result = runtime.execute(env={}, stdin=None, timeout=10)
        assert "error_msg" in result.stderr

    def test_execute_returns_exit_code(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Execute returns correct exit code."""
        runtime = LocalExecRuntime.spawn(
            environment=local_spec,
            working_dir=tmp_path,
            command="sh -c 'exit 42'",
        )
        result = runtime.execute(env={}, stdin=None, timeout=10)
        assert result.exit_code == 42

    def test_execute_success_exit_code(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Successful command returns exit code 0."""
        runtime = LocalExecRuntime.spawn(
            environment=local_spec,
            working_dir=tmp_path,
            command="echo success",
        )
        result = runtime.execute(env={}, stdin=None, timeout=10)
        assert result.exit_code == 0

    def test_execute_with_stdin_string(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Execute passes stdin string to process."""
        runtime = LocalExecRuntime.spawn(
            environment=local_spec,
            working_dir=tmp_path,
            command="cat",
        )
        result = runtime.execute(env={}, stdin="hello from stdin", timeout=10)
        assert "hello from stdin" in result.stdout

    def test_execute_with_stdin_list(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Execute passes stdin list to process."""
        runtime = LocalExecRuntime.spawn(
            environment=local_spec,
            working_dir=tmp_path,
            command="cat",
        )
        result = runtime.execute(
            env={}, stdin=["line1\n", "line2\n", "line3\n"], timeout=10
        )
        assert "line1" in result.stdout
        assert "line2" in result.stdout
        assert "line3" in result.stdout

    def test_execute_with_environment_variables(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Execute passes environment variables."""
        runtime = LocalExecRuntime.spawn(
            environment=local_spec,
            working_dir=tmp_path,
            command="sh -c 'echo $MY_VAR'",
        )
        result = runtime.execute(env={"MY_VAR": "test_value"}, stdin=None, timeout=10)
        assert "test_value" in result.stdout

    def test_execute_measures_elapsed_time(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Execute measures elapsed time."""
        runtime = LocalExecRuntime.spawn(
            environment=local_spec,
            working_dir=tmp_path,
            command="sleep 0.1",
        )
        result = runtime.execute(env={}, stdin=None, timeout=10)
        assert result.elapsed >= 0.1

    def test_execute_timeout_sets_flag(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Execute sets timed_out flag when command times out."""
        runtime = LocalExecRuntime.spawn(
            environment=local_spec,
            working_dir=tmp_path,
            command="sleep 10",
        )
        result = runtime.execute(env={}, stdin=None, timeout=0.1)
        assert result.timed_out is True

    def test_execute_timeout_kills_process(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Execute kills process on timeout."""
        runtime = LocalExecRuntime.spawn(
            environment=local_spec,
            working_dir=tmp_path,
            command="sleep 10",
        )
        result = runtime.execute(env={}, stdin=None, timeout=0.1)
        # Process should be killed, so elapsed should be close to timeout
        assert result.elapsed < 1.0

    def test_execute_uses_working_directory(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Execute runs in the specified working directory."""
        runtime = LocalExecRuntime.spawn(
            environment=local_spec,
            working_dir=tmp_path,
            command="pwd",
        )
        result = runtime.execute(env={}, stdin=None, timeout=10)
        assert str(tmp_path) in result.stdout


class TestLocalExecRuntimePoll:
    """Tests for LocalExecRuntime.poll()."""

    def test_poll_returns_none_before_execute(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Poll returns None before execute is called."""
        runtime = LocalExecRuntime.spawn(
            environment=local_spec,
            working_dir=tmp_path,
            command="echo test",
        )
        assert runtime.poll() is None

    def test_poll_returns_exit_code_after_execute(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Poll returns exit code after execute completes."""
        runtime = LocalExecRuntime.spawn(
            environment=local_spec,
            working_dir=tmp_path,
            command="sh -c 'exit 5'",
        )
        runtime.execute(env={}, stdin=None, timeout=10)
        assert runtime.poll() == 5


class TestLocalExecRuntimeKill:
    """Tests for LocalExecRuntime.kill()."""

    def test_kill_is_safe_when_no_process(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Kill is safe to call when no process is running."""
        runtime = LocalExecRuntime.spawn(
            environment=local_spec,
            working_dir=tmp_path,
            command="echo test",
        )
        # Should not raise
        runtime.kill()


class TestLocalExecRuntimeCleanup:
    """Tests for LocalExecRuntime.cleanup()."""

    def test_cleanup_is_idempotent(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Cleanup can be called multiple times safely."""
        runtime = LocalExecRuntime.spawn(
            environment=local_spec,
            working_dir=tmp_path,
            command="echo test",
        )
        runtime.execute(env={}, stdin=None, timeout=10)
        # Should not raise on multiple calls
        runtime.cleanup()
        runtime.cleanup()
        runtime.cleanup()


class TestLocalExecRuntimeIntegration:
    """Integration tests for LocalExecRuntime."""

    def test_full_lifecycle(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Test complete spawn -> execute -> cleanup lifecycle."""
        runtime = LocalExecRuntime.spawn(
            environment=local_spec,
            working_dir=tmp_path,
            command="echo integration_test",
        )
        try:
            result = runtime.execute(env={}, stdin=None, timeout=10)
            assert "integration_test" in result.stdout
            assert result.exit_code == 0
        finally:
            runtime.cleanup()

    def test_file_io_in_working_directory(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Test file I/O operations in working directory."""
        # Create a file
        test_file = tmp_path / "test_input.txt"
        test_file.write_text("input content")

        runtime = LocalExecRuntime.spawn(
            environment=local_spec,
            working_dir=tmp_path,
            command="cat test_input.txt",
        )
        result = runtime.execute(env={}, stdin=None, timeout=10)
        assert "input content" in result.stdout
        runtime.cleanup()

    def test_large_output_handling(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Test handling of large output."""
        # Generate 1000 lines of output
        runtime = LocalExecRuntime.spawn(
            environment=local_spec,
            working_dir=tmp_path,
            command="seq 1 1000",
        )
        result = runtime.execute(env={}, stdin=None, timeout=10)
        lines = result.stdout.strip().split("\n")
        assert len(lines) == 1000
        assert "1" in lines[0]
        assert "1000" in lines[-1]
        runtime.cleanup()

    def test_concurrent_stdout_stderr(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Test capturing concurrent stdout and stderr."""
        script = tmp_path / "mixed_output.sh"
        script.write_text(
            """#!/bin/sh
echo "stdout line 1"
echo "stderr line 1" >&2
echo "stdout line 2"
echo "stderr line 2" >&2
"""
        )
        script.chmod(0o755)

        runtime = LocalExecRuntime.spawn(
            environment=local_spec,
            working_dir=tmp_path,
            command=f"sh {script}",
        )
        result = runtime.execute(env={}, stdin=None, timeout=10)
        assert "stdout line 1" in result.stdout
        assert "stdout line 2" in result.stdout
        assert "stderr line 1" in result.stderr
        assert "stderr line 2" in result.stderr
        runtime.cleanup()

    def test_special_characters_in_output(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Test handling of special characters in output."""
        runtime = LocalExecRuntime.spawn(
            environment=local_spec,
            working_dir=tmp_path,
            command='echo "special: $HOME \\"quotes\\" <brackets> & ampersand"',
        )
        result = runtime.execute(env={}, stdin=None, timeout=10)
        assert "special:" in result.stdout
        assert '"quotes"' in result.stdout
        assert "<brackets>" in result.stdout
        assert "ampersand" in result.stdout
        runtime.cleanup()

    def test_env_var_merging(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Test that spawn env_vars and execute env are merged."""
        runtime = LocalExecRuntime.spawn(
            environment=local_spec,
            working_dir=tmp_path,
            command="sh -c 'echo spawn=$SPAWN_VAR exec=$EXEC_VAR'",
            env_vars={"SPAWN_VAR": "from_spawn"},
        )
        result = runtime.execute(
            env={"EXEC_VAR": "from_exec"}, stdin=None, timeout=10
        )
        assert "spawn=from_spawn" in result.stdout
        assert "exec=from_exec" in result.stdout
        runtime.cleanup()


class TestLocalExecRuntimePrepareStdin:
    """Tests for stdin preparation."""

    def test_prepare_stdin_none(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """None stdin returns None."""
        runtime = LocalExecRuntime(
            environment=local_spec,
            working_dir=tmp_path,
            command="cat",
        )
        assert runtime._prepare_stdin(None) is None

    def test_prepare_stdin_string(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """String stdin is encoded to bytes."""
        runtime = LocalExecRuntime(
            environment=local_spec,
            working_dir=tmp_path,
            command="cat",
        )
        result = runtime._prepare_stdin("hello")
        assert result == b"hello"

    def test_prepare_stdin_list(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """List stdin is joined and encoded."""
        runtime = LocalExecRuntime(
            environment=local_spec,
            working_dir=tmp_path,
            command="cat",
        )
        result = runtime._prepare_stdin(["a", "b", "c"])
        assert result == b"abc"
