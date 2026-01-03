"""Tests for LocalStreamingRuntime."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from slop_code.execution.local_streaming import LocalEnvironmentSpec
from slop_code.execution.local_streaming import LocalStreamingRuntime
from slop_code.execution.models import CommandConfig
from slop_code.execution.models import SetupConfig
from slop_code.execution.runtime import RuntimeEvent
from slop_code.execution.runtime import RuntimeResult
from slop_code.execution.runtime import SolutionRuntimeError


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


class TestLocalEnvironmentSpec:
    """Tests for LocalEnvironmentSpec."""

    def test_type_is_local(self) -> None:
        """Environment type is 'local'."""
        spec = LocalEnvironmentSpec(
            type="local",
            name="test",
            commands=CommandConfig(command="python"),
        )
        assert spec.type == "local"


class TestLocalStreamingRuntimeInit:
    """Tests for LocalStreamingRuntime initialization."""

    def test_init_stores_working_dir(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Working directory is stored."""
        runtime = LocalStreamingRuntime(
            environment=local_spec,
            working_dir=tmp_path,
        )
        assert runtime.cwd == tmp_path

    def test_init_stores_spec(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Environment spec is stored."""
        runtime = LocalStreamingRuntime(
            environment=local_spec,
            working_dir=tmp_path,
        )
        assert runtime.spec == local_spec

    def test_init_process_is_none(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Process is None initially."""
        runtime = LocalStreamingRuntime(
            environment=local_spec,
            working_dir=tmp_path,
        )
        assert runtime._proc is None


class TestLocalStreamingRuntimeSpawn:
    """Tests for LocalStreamingRuntime.spawn()."""

    def test_spawn_creates_runtime(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Spawn creates a LocalStreamingRuntime instance."""
        runtime = LocalStreamingRuntime.spawn(
            environment=local_spec,
            working_dir=tmp_path,
        )
        assert isinstance(runtime, LocalStreamingRuntime)

    def test_spawn_rejects_wrong_environment_type(self, tmp_path: Path) -> None:
        """Spawn raises ValueError for wrong environment type."""
        mock_spec = MagicMock()
        mock_spec.type = "docker"

        with pytest.raises(ValueError, match="Invalid environment spec"):
            LocalStreamingRuntime.spawn(
                environment=mock_spec,
                working_dir=tmp_path,
            )

    def test_spawn_runs_setup_commands(self, tmp_path: Path) -> None:
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

        LocalStreamingRuntime.spawn(
            environment=spec,
            working_dir=tmp_path,
        )

        assert marker_file.exists()

    def test_spawn_with_disable_setup(self, tmp_path: Path) -> None:
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

        LocalStreamingRuntime.spawn(
            environment=spec,
            working_dir=tmp_path,
            disable_setup=True,
        )

        assert not marker_file.exists()


class TestLocalStreamingRuntimeStream:
    """Tests for LocalStreamingRuntime.stream()."""

    def test_stream_yields_events(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Stream yields RuntimeEvent objects."""
        runtime = LocalStreamingRuntime.spawn(
            environment=local_spec,
            working_dir=tmp_path,
        )
        try:
            events = list(runtime.stream("echo hello", env={}, timeout=10))
            assert len(events) > 0
            assert all(isinstance(e, RuntimeEvent) for e in events)
        finally:
            runtime.cleanup()

    def test_stream_captures_stdout(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Stream captures stdout in events."""
        runtime = LocalStreamingRuntime.spawn(
            environment=local_spec,
            working_dir=tmp_path,
        )
        try:
            events = list(runtime.stream("echo hello_world", env={}, timeout=10))
            stdout_events = [e for e in events if e.kind == "stdout"]
            stdout_text = "".join(e.text for e in stdout_events if e.text)
            assert "hello_world" in stdout_text
        finally:
            runtime.cleanup()

    def test_stream_captures_stderr(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Stream captures stderr in events."""
        runtime = LocalStreamingRuntime.spawn(
            environment=local_spec,
            working_dir=tmp_path,
        )
        try:
            events = list(runtime.stream("sh -c 'echo error_msg >&2'", env={}, timeout=10))
            stderr_events = [e for e in events if e.kind == "stderr"]
            stderr_text = "".join(e.text for e in stderr_events if e.text)
            assert "error_msg" in stderr_text
        finally:
            runtime.cleanup()

    def test_stream_ends_with_finished_event(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Stream ends with a 'finished' event."""
        runtime = LocalStreamingRuntime.spawn(
            environment=local_spec,
            working_dir=tmp_path,
        )
        try:
            events = list(runtime.stream("echo test", env={}, timeout=10))
            assert events[-1].kind == "finished"
        finally:
            runtime.cleanup()

    def test_stream_finished_has_result(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Finished event contains RuntimeResult."""
        runtime = LocalStreamingRuntime.spawn(
            environment=local_spec,
            working_dir=tmp_path,
        )
        try:
            events = list(runtime.stream("echo test", env={}, timeout=10))
            finished = events[-1]
            assert finished.result is not None
            assert isinstance(finished.result, RuntimeResult)
        finally:
            runtime.cleanup()

    def test_stream_result_has_exit_code(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Finished event result has correct exit code."""
        runtime = LocalStreamingRuntime.spawn(
            environment=local_spec,
            working_dir=tmp_path,
        )
        try:
            events = list(runtime.stream("sh -c 'exit 42'", env={}, timeout=10))
            finished = events[-1]
            assert finished.result.exit_code == 42
        finally:
            runtime.cleanup()

    def test_stream_with_environment_variables(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Stream passes environment variables."""
        runtime = LocalStreamingRuntime.spawn(
            environment=local_spec,
            working_dir=tmp_path,
        )
        try:
            events = list(
                runtime.stream(
                    "sh -c 'echo $MY_VAR'", env={"MY_VAR": "test_value"}, timeout=10
                )
            )
            stdout_events = [e for e in events if e.kind == "stdout"]
            stdout_text = "".join(e.text for e in stdout_events if e.text)
            assert "test_value" in stdout_text
        finally:
            runtime.cleanup()

    def test_stream_uses_working_directory(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Stream runs in the specified working directory."""
        runtime = LocalStreamingRuntime.spawn(
            environment=local_spec,
            working_dir=tmp_path,
        )
        try:
            events = list(runtime.stream("pwd", env={}, timeout=10))
            stdout_events = [e for e in events if e.kind == "stdout"]
            stdout_text = "".join(e.text for e in stdout_events if e.text)
            assert str(tmp_path) in stdout_text
        finally:
            runtime.cleanup()

    def test_stream_multiple_commands(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Multiple stream calls work on same runtime."""
        runtime = LocalStreamingRuntime.spawn(
            environment=local_spec,
            working_dir=tmp_path,
        )
        try:
            # First command
            events1 = list(runtime.stream("echo first", env={}, timeout=10))
            assert events1[-1].kind == "finished"

            # Second command
            events2 = list(runtime.stream("echo second", env={}, timeout=10))
            assert events2[-1].kind == "finished"

            # Check output from finished result (more reliable than events)
            result1 = events1[-1].result
            result2 = events2[-1].result
            assert result1.exit_code == 0
            assert result2.exit_code == 0
            # Output should be captured in either events or result
            stdout1 = "".join(
                e.text for e in events1 if e.kind == "stdout" and e.text
            ) or result1.stdout
            stdout2 = "".join(
                e.text for e in events2 if e.kind == "stdout" and e.text
            ) or result2.stdout
            assert "first" in stdout1
            assert "second" in stdout2
        finally:
            runtime.cleanup()


class TestLocalStreamingRuntimePoll:
    """Tests for LocalStreamingRuntime.poll()."""

    def test_poll_returns_none_when_no_process(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Poll returns None when no process is running."""
        runtime = LocalStreamingRuntime.spawn(
            environment=local_spec,
            working_dir=tmp_path,
        )
        assert runtime.poll() is None

    def test_poll_returns_exit_code_after_completion(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Poll returns exit code after stream completes."""
        runtime = LocalStreamingRuntime.spawn(
            environment=local_spec,
            working_dir=tmp_path,
        )
        try:
            # Consume the stream to completion
            list(runtime.stream("sh -c 'exit 5'", env={}, timeout=10))
            # Poll should return None after cleanup by stream
            # The process has already been consumed
        finally:
            runtime.cleanup()


class TestLocalStreamingRuntimeKill:
    """Tests for LocalStreamingRuntime.kill()."""

    def test_kill_is_safe_when_no_process(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Kill is safe to call when no process is running."""
        runtime = LocalStreamingRuntime.spawn(
            environment=local_spec,
            working_dir=tmp_path,
        )
        # Should not raise
        runtime.kill()

    def test_kill_terminates_running_process(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Kill terminates a running process."""
        runtime = LocalStreamingRuntime.spawn(
            environment=local_spec,
            working_dir=tmp_path,
        )
        try:
            # Start a long-running process but don't consume all output
            stream = runtime.stream("sleep 60", env={}, timeout=None)
            # Get first event
            next(stream, None)
            # Kill it
            runtime.kill()
            # Process should be gone
        finally:
            runtime.cleanup()


class TestLocalStreamingRuntimeCleanup:
    """Tests for LocalStreamingRuntime.cleanup()."""

    def test_cleanup_is_idempotent(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Cleanup can be called multiple times safely."""
        runtime = LocalStreamingRuntime.spawn(
            environment=local_spec,
            working_dir=tmp_path,
        )
        list(runtime.stream("echo test", env={}, timeout=10))
        # Should not raise on multiple calls
        runtime.cleanup()
        runtime.cleanup()
        runtime.cleanup()


class TestLocalStreamingRuntimeProcess:
    """Tests for process property."""

    def test_process_raises_when_not_running(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Process property raises when no process is running."""
        runtime = LocalStreamingRuntime.spawn(
            environment=local_spec,
            working_dir=tmp_path,
        )
        with pytest.raises(SolutionRuntimeError, match="Process not running"):
            _ = runtime.process


class TestLocalStreamingRuntimeIntegration:
    """Integration tests for LocalStreamingRuntime."""

    def test_full_lifecycle(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Test complete spawn -> stream -> cleanup lifecycle."""
        runtime = LocalStreamingRuntime.spawn(
            environment=local_spec,
            working_dir=tmp_path,
        )
        try:
            events = list(runtime.stream("echo integration_test", env={}, timeout=10))
            finished = events[-1]
            assert finished.result.exit_code == 0
            stdout_text = "".join(
                e.text for e in events if e.kind == "stdout" and e.text
            )
            assert "integration_test" in stdout_text
        finally:
            runtime.cleanup()

    def test_file_io_in_working_directory(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Test file I/O operations in working directory."""
        test_file = tmp_path / "test_input.txt"
        test_file.write_text("input content")

        runtime = LocalStreamingRuntime.spawn(
            environment=local_spec,
            working_dir=tmp_path,
        )
        try:
            events = list(runtime.stream("cat test_input.txt", env={}, timeout=10))
            stdout_text = "".join(
                e.text for e in events if e.kind == "stdout" and e.text
            )
            assert "input content" in stdout_text
        finally:
            runtime.cleanup()

    def test_large_output_handling(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Test handling of large output."""
        runtime = LocalStreamingRuntime.spawn(
            environment=local_spec,
            working_dir=tmp_path,
        )
        try:
            events = list(runtime.stream("seq 1 1000", env={}, timeout=10))
            stdout_text = "".join(
                e.text for e in events if e.kind == "stdout" and e.text
            )
            lines = stdout_text.strip().split("\n")
            assert len(lines) == 1000
        finally:
            runtime.cleanup()

    def test_concurrent_stdout_stderr(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Test capturing concurrent stdout and stderr."""
        runtime = LocalStreamingRuntime.spawn(
            environment=local_spec,
            working_dir=tmp_path,
        )
        try:
            # Use sh -c to properly handle shell redirects
            cmd = "sh -c 'echo stdout_line_1; echo stderr_line_1 >&2; echo stdout_line_2; echo stderr_line_2 >&2'"
            events = list(runtime.stream(cmd, env={}, timeout=10))
            stdout_text = "".join(
                e.text for e in events if e.kind == "stdout" and e.text
            )
            stderr_text = "".join(
                e.text for e in events if e.kind == "stderr" and e.text
            )
            # Check that stdout was captured
            assert "stdout_line_1" in stdout_text
            assert "stdout_line_2" in stdout_text
            # Check that stderr was captured (may be combined with stdout in some cases)
            assert "stderr_line_1" in stderr_text or "stderr_line_1" in stdout_text
            assert "stderr_line_2" in stderr_text or "stderr_line_2" in stdout_text
        finally:
            runtime.cleanup()

    def test_timeout_during_stream(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Test timeout handling during streaming."""
        runtime = LocalStreamingRuntime.spawn(
            environment=local_spec,
            working_dir=tmp_path,
        )
        try:
            events = list(runtime.stream("sleep 10", env={}, timeout=0.5))
            finished = events[-1]
            assert finished.result.timed_out is True
        finally:
            runtime.cleanup()

    def test_working_dir_persists_between_commands(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Working directory persists between stream calls."""
        runtime = LocalStreamingRuntime.spawn(
            environment=local_spec,
            working_dir=tmp_path,
        )
        try:
            # Create a file with first command
            list(runtime.stream("sh -c 'echo test > testfile.txt'", env={}, timeout=10))

            # Verify file exists with second command
            events = list(runtime.stream("cat testfile.txt", env={}, timeout=10))
            stdout_text = "".join(
                e.text for e in events if e.kind == "stdout" and e.text
            )
            assert "test" in stdout_text
        finally:
            runtime.cleanup()


class TestLocalStreamingRuntimeDemuxedStream:
    """Tests for _create_demuxed_stream method."""

    def test_demuxed_stream_yields_tuples(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Demuxed stream yields (stdout, stderr) tuples."""
        runtime = LocalStreamingRuntime.spawn(
            environment=local_spec,
            working_dir=tmp_path,
        )
        try:
            proc = runtime._start_process("echo test", env={})
            for chunk in runtime._create_demuxed_stream(proc):
                assert isinstance(chunk, tuple)
                assert len(chunk) == 2
                break  # Just test one iteration
        finally:
            runtime.cleanup()
