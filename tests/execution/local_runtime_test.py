"""Unit tests for LocalRuntime and related functions."""

import shutil
import subprocess
import time
from pathlib import Path

import pytest

from slop_code.execution.local_runtime import LocalEnvironmentSpec
from slop_code.execution.local_runtime import LocalRuntime
from slop_code.execution.local_runtime import _normalize_command
from slop_code.execution.models import CommandConfig
from slop_code.execution.models import EnvironmentConfig
from slop_code.execution.models import SetupConfig
from slop_code.execution.runtime import RuntimeEvent
from slop_code.execution.runtime import RuntimeResult
from slop_code.execution.runtime import SolutionRuntimeError


@pytest.fixture
def python_executable() -> str:
    """Get the Python executable."""
    return "python3" if shutil.which("python3") is not None else "python"


class TestNormalizeCommand:
    """Tests for _normalize_command helper function."""

    def test_normalize_string_command(self):
        """Test normalizing a string command."""
        result = _normalize_command("echo hello world")
        assert result == ["echo", "hello", "world"]

    def test_normalize_string_command_with_quotes(self):
        """Test normalizing a string command with quotes."""
        result = _normalize_command('echo "hello world"')
        assert result == ["echo", "hello world"]

    def test_normalize_list_command(self):
        """Test normalizing a list command."""
        result = _normalize_command(["echo", "hello", "world"])
        assert result == ["echo", "hello", "world"]

    def test_normalize_list_command_returns_copy(self):
        """Test that normalizing a list returns a copy."""
        original = ["echo", "test"]
        result = _normalize_command(original)
        assert result == original
        assert result is not original

    def test_normalize_empty_string(self):
        """Test normalizing an empty string."""
        result = _normalize_command("")
        assert result == []

    def test_normalize_empty_list(self):
        """Test normalizing an empty list."""
        result = _normalize_command([])
        assert result == []

    def test_normalize_complex_command(self):
        """Test normalizing a complex command with special characters."""
        result = _normalize_command("bash -c 'echo $PATH'")
        assert result == ["bash", "-c", "echo $PATH"]


class TestLocalRuntimeInit:
    """Tests for LocalRuntime initialization."""

    @pytest.fixture
    def temp_dir(self, tmp_path: Path):
        """Create a temporary directory."""
        return tmp_path

    @pytest.fixture
    def spec(self):
        """Create a basic environment spec."""
        return LocalEnvironmentSpec(
            type="local",
            name="test",
            commands=CommandConfig(command="bash"),
            environment=EnvironmentConfig(env={"TEST_VAR": "value"}),
        )

    def test_initialization(self, temp_dir: Path, spec: LocalEnvironmentSpec):
        """Test basic initialization."""
        runtime: LocalRuntime = LocalRuntime(
            environment=spec, working_dir=temp_dir
        )

        assert runtime.spec == spec
        assert runtime.cwd == temp_dir
        assert runtime._proc is None

    def test_process_property_not_started(
        self, temp_dir: Path, spec: LocalEnvironmentSpec
    ):
        """Test process property raises when process not started."""
        runtime: LocalRuntime = LocalRuntime(
            environment=spec, working_dir=temp_dir
        )

        with pytest.raises(SolutionRuntimeError, match="Process not running"):
            _ = runtime.process


class TestLocalRuntimeSpawn:
    """Tests for LocalRuntime.spawn class method."""

    @pytest.fixture
    def temp_dir(self, tmp_path: Path):
        """Create a temporary directory."""
        return tmp_path

    def test_spawn_success(self, temp_dir: Path):
        """Test successful spawn."""
        spec = LocalEnvironmentSpec(
            type="local",
            name="test",
            commands=CommandConfig(command="bash"),
            environment=EnvironmentConfig(
                env={"VAR": "value"}, include_os_env=True
            ),
        )
        runtime = LocalRuntime.spawn(environment=spec, working_dir=temp_dir)

        assert isinstance(runtime, LocalRuntime)
        assert runtime.cwd == temp_dir
        assert runtime.spec == spec

    def test_spawn_with_setup_commands(
        self, temp_dir: Path, python_executable: str
    ):
        """Test spawn with setup commands."""
        # Create a file using a cross-platform approach
        test_file = temp_dir / "setup.txt"
        spec = LocalEnvironmentSpec(
            type="local",
            name="test",
            commands=CommandConfig(command=python_executable),
            setup=SetupConfig(
                commands=[
                    f"{python_executable} -c \"with open(r'{test_file}', 'w') as f: f.write('setup')\""
                ]
            ),
        )
        runtime = LocalRuntime.spawn(environment=spec, working_dir=temp_dir)

        assert isinstance(runtime, LocalRuntime)
        # Setup command should have been executed
        assert test_file.exists()
        assert test_file.read_text().strip() == "setup"

    def test_spawn_with_multiple_setup_commands(
        self, temp_dir: Path, python_executable: str
    ):
        """Test spawn with multiple setup commands."""
        file1 = temp_dir / "file1.txt"
        file2 = temp_dir / "file2.txt"
        spec = LocalEnvironmentSpec(
            type="local",
            name="test",
            commands=CommandConfig(command=python_executable),
            setup=SetupConfig(
                commands=[
                    f"{python_executable} -c \"with open(r'{file1}', 'w') as f: f.write('first')\"",
                    f"{python_executable} -c \"with open(r'{file2}', 'w') as f: f.write('second')\"",
                ]
            ),
        )
        LocalRuntime.spawn(environment=spec, working_dir=temp_dir)

        assert file1.exists()
        assert file2.exists()
        assert file1.read_text().strip() == "first"
        assert file2.read_text().strip() == "second"

    def test_spawn_invalid_environment_spec(self, temp_dir: Path):
        """Test spawn with invalid environment spec."""
        # Create a mock spec that's not LocalEnvironmentSpec
        from slop_code.execution.models import EnvironmentSpec

        # Create a different type of EnvironmentSpec
        class OtherSpec(EnvironmentSpec):
            type: str = "other"  # type: ignore[assignment]

        mock_spec = OtherSpec(
            type="other", name="test", commands=CommandConfig(command="test")
        )
        with pytest.raises(ValueError, match="Invalid environment spec"):
            LocalRuntime.spawn(environment=mock_spec, working_dir=temp_dir)


class TestLocalRuntimeStartProc:
    """Tests for LocalRuntime._start_proc method."""

    @pytest.fixture
    def runtime(self, tmp_path: Path):
        """Create a runtime instance."""
        spec = LocalEnvironmentSpec(
            type="local", name="test", commands=CommandConfig(command="bash")
        )
        return LocalRuntime(environment=spec, working_dir=tmp_path)

    def test_start_proc_simple_command(self, runtime: LocalRuntime):
        """Test starting a simple process."""
        runtime._start_proc(
            command="bash -c 'echo test'",
            env={},
            stdin=None,
        )

        assert runtime._proc is not None
        assert isinstance(runtime._proc, subprocess.Popen)

        # Clean up
        runtime._proc.wait()

    def test_start_proc_with_list_command(self, runtime: LocalRuntime):
        """Test starting a process with list command."""
        runtime._start_proc(
            command="echo test",
            env={},
            stdin=None,
        )

        assert runtime._proc is not None
        runtime._proc.wait()

    def test_start_proc_with_stdin_string(self, runtime: LocalRuntime):
        """Test starting a process with stdin as string."""
        runtime._start_proc(
            command="cat",
            env={},
            stdin="test input",
        )

        assert runtime._proc is not None
        runtime._proc.wait()

    def test_start_proc_with_stdin_list(self, runtime: LocalRuntime):
        """Test starting a process with stdin as list."""
        runtime._start_proc(
            command="cat",
            env={},
            stdin=["input1", "input2"],
        )

        assert runtime._proc is not None
        runtime._proc.wait()

    def test_start_proc_with_custom_env(
        self, runtime: LocalRuntime, python_executable: str
    ):
        """Test starting a process with custom environment."""
        runtime._start_proc(
            command=f"{python_executable} -c \"import os; print(os.environ.get('CUSTOM_VAR', ''))\"",
            env={"CUSTOM_VAR": "custom_value"},
            stdin=None,
        )

        assert runtime._proc is not None
        runtime._proc.wait()

        stdout = runtime._proc.stdout.read()
        assert "custom_value" in stdout


class TestLocalRuntimeStream:
    """Tests for LocalRuntime.stream method."""

    @pytest.fixture
    def runtime(self, tmp_path: Path):
        """Create a runtime instance."""
        spec = LocalEnvironmentSpec(
            type="local",
            name="test",
            commands=CommandConfig(command="bash"),
            environment=EnvironmentConfig(include_os_env=True),
        )
        return LocalRuntime(environment=spec, working_dir=tmp_path)

    def test_stream_simple_command(self, runtime: LocalRuntime):
        """Test streaming a simple command."""
        events = list(
            runtime.stream(
                command="echo hello",
                env={},
                stdin=None,
                timeout=5.0,
            )
        )

        # Should have stdout events and a finished event
        assert len(events) >= 1
        assert events[-1].kind == "finished"
        assert events[-1].result is not None
        assert events[-1].result.exit_code == 0
        assert events[-1].result.timed_out is False

        # Check for stdout content
        stdout_events = [e for e in events if e.kind == "stdout"]
        assert len(stdout_events) >= 1
        stdout_text = "".join(e.text for e in stdout_events if e.text)
        assert "hello" in stdout_text

    def test_stream_stderr_output(
        self, runtime: LocalRuntime, python_executable: str
    ):
        """Test streaming a command with stderr output."""
        events = list(
            runtime.stream(
                command=f"{python_executable} -c \"import sys; sys.stderr.write('error\\n')\"",
                env={},
                stdin=None,
                timeout=5.0,
            )
        )

        # Should have stderr events
        stderr_events = [e for e in events if e.kind == "stderr"]
        assert len(stderr_events) >= 1
        stderr_text = "".join(e.text for e in stderr_events if e.text)
        assert "error" in stderr_text

        # Check finished event
        assert events[-1].kind == "finished"
        assert events[-1].result.exit_code == 0

    def test_stream_both_stdout_and_stderr(
        self, runtime: LocalRuntime, python_executable: str
    ):
        """Test streaming a command with both stdout and stderr."""
        events = list(
            runtime.stream(
                command=f"{python_executable} -c \"import sys; print('out'); sys.stderr.write('err\\n')\"",
                env={},
                stdin=None,
                timeout=5.0,
            )
        )

        stdout_events = [e for e in events if e.kind == "stdout"]
        stderr_events = [e for e in events if e.kind == "stderr"]

        assert len(stdout_events) >= 1
        assert len(stderr_events) >= 1

        stdout_text = "".join(e.text for e in stdout_events if e.text)
        stderr_text = "".join(e.text for e in stderr_events if e.text)

        assert "out" in stdout_text
        assert "err" in stderr_text

    def test_stream_nonzero_exit_code(
        self, runtime: LocalRuntime, python_executable: str
    ):
        """Test streaming a command with non-zero exit code."""
        events = list(
            runtime.stream(
                command=f'{python_executable} -c "import sys; sys.exit(42)"',
                env={},
                stdin=None,
                timeout=5.0,
            )
        )

        assert events[-1].kind == "finished"
        assert events[-1].result.exit_code == 42
        assert events[-1].result.timed_out is False

    def test_stream_timeout(self, runtime: LocalRuntime):
        """Test streaming a command that times out."""
        events = list(
            runtime.stream(
                command="sleep 10",
                env={},
                stdin=None,
                timeout=0.5,
            )
        )

        # Should timeout around 0.5 seconds
        assert events[-1].result.elapsed < 2.0
        assert events[-1].kind == "finished"
        assert events[-1].result.timed_out is True

    def test_stream_no_timeout(self, runtime: LocalRuntime):
        """Test streaming a command with no timeout."""
        events = list(
            runtime.stream(
                command="echo test",
                env={},
                stdin=None,
                timeout=None,
            )
        )

        assert events[-1].kind == "finished"
        assert events[-1].result.timed_out is False
        assert events[-1].result.exit_code == 0

    def test_stream_multiple_stdout_lines(
        self, runtime: LocalRuntime, python_executable: str
    ):
        """Test streaming a command with multiple output lines."""
        events = list(
            runtime.stream(
                command=f"{python_executable} -c \"print('line1'); print('line2'); print('line3')\"",
                env={},
                stdin=None,
                timeout=5.0,
            )
        )

        stdout_events = [e for e in events if e.kind == "stdout"]
        assert len(stdout_events) >= 1

    def test_stream_elapsed_time(self, runtime: LocalRuntime):
        """Test that elapsed time is tracked correctly."""
        events = list(
            runtime.stream(
                command="sleep 0.2",
                env={},
                stdin=None,
                timeout=5.0,
            )
        )

        assert events[-1].kind == "finished"
        assert events[-1].result.elapsed >= 0.15  # Allow some tolerance
        assert events[-1].result.elapsed < 1.0

    def test_stream_captures_all_output(
        self, runtime: LocalRuntime, python_executable: str
    ):
        """Test that all output is captured in the result."""
        events = list(
            runtime.stream(
                command=f"{python_executable} -c \"import sys; print('out1'); print('out2'); sys.stderr.write('err1\\n'); sys.stderr.write('err2\\n')\"",
                env={},
                stdin=None,
                timeout=5.0,
            )
        )

        result = events[-1].result
        assert "out1" in result.stdout
        assert "out2" in result.stdout
        assert "err1" in result.stderr
        assert "err2" in result.stderr

    def test_stream_fallback_buffers_used_when_result_empty(
        self,
        runtime: LocalRuntime,
        python_executable: str,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """Ensure fallback buffers hydrate stdout/stderr if process_stream drops them."""

        def fake_process_stream(
            stream, timeout, poll_fn, yield_only_after=None
        ):
            for stdout_chunk, stderr_chunk in stream:
                if stdout_chunk:
                    yield RuntimeEvent(kind="stdout", text=stdout_chunk)
                if stderr_chunk:
                    yield RuntimeEvent(kind="stderr", text=stderr_chunk)
            return RuntimeResult(
                exit_code=0,
                stdout="",
                stderr="",
                setup_stdout="",
                setup_stderr="",
                elapsed=0.01,
                timed_out=False,
            )

        monkeypatch.setattr(
            "slop_code.execution.local_runtime.process_stream",
            fake_process_stream,
        )

        events = list(
            runtime.stream(
                command=f"{python_executable} -c \"import sys; print('out1'); sys.stderr.write('err1\\n')\"",
                env={},
                stdin=None,
                timeout=5.0,
            )
        )

        result = events[-1].result
        assert "out1" in result.stdout
        assert "err1" in result.stderr

    def test_stream_with_stdin(
        self,
        runtime: LocalRuntime,
    ):
        """Test streaming with stdin input."""
        with pytest.raises(ValueError, match="stdin is not supported"):
            list(
                runtime.stream(
                    command="cat",
                    env={},
                    stdin="test input",
                    timeout=1.0,
                )
            )


class TestLocalRuntimeExecute:
    """Tests for LocalRuntime.execute method."""

    @pytest.fixture
    def runtime(self, tmp_path: Path):
        """Create a runtime instance."""
        spec = LocalEnvironmentSpec(
            type="local",
            name="test",
            commands=CommandConfig(command="bash"),
        )
        return LocalRuntime(environment=spec, working_dir=tmp_path)

    def test_execute_simple_command(self, runtime: LocalRuntime):
        """Test executing a simple command."""
        result = runtime.execute(
            command=["echo", "hello"],
            env={},
            stdin=None,
            timeout=5.0,
        )

        assert result.exit_code == 0
        assert "hello" in result.stdout
        assert result.stderr == ""
        assert result.timed_out is False
        assert result.elapsed > 0

    def test_execute_with_stderr(
        self, runtime: LocalRuntime, python_executable: str
    ):
        """Test executing a command with stderr output."""

        result = runtime.execute(
            command=f"{python_executable} -c \"import sys; sys.stderr.write('error\\n')\"",
            env={},
            stdin=None,
            timeout=5.0,
        )

        assert result.exit_code == 0
        assert "error" in result.stderr
        assert result.timed_out is False

    def test_execute_nonzero_exit(
        self, runtime: LocalRuntime, python_executable: str
    ):
        """Test executing a command with non-zero exit code."""
        result = runtime.execute(
            command=f'{python_executable} -c "import sys; sys.exit(13)"',
            env={},
            stdin=None,
            timeout=5.0,
        )

        assert result.exit_code == 13
        assert result.timed_out is False

    def test_execute_timeout(self, runtime: LocalRuntime):
        """Test executing a command that times out."""
        result = runtime.execute(
            command="sleep 10",
            env={},
            stdin=None,
            timeout=0.5,
        )

        assert result.timed_out is True
        assert result.elapsed <= 1.0

    def test_execute_no_timeout(self, runtime: LocalRuntime):
        """Test executing a command with no timeout."""
        result = runtime.execute(
            command="echo test",
            env={},
            stdin=None,
            timeout=None,
        )

        assert result.exit_code == 0
        assert result.timed_out is False

    def test_execute_with_custom_env(
        self, runtime: LocalRuntime, python_executable: str
    ):
        """Test executing a command with custom environment."""
        result = runtime.execute(
            command=f"{python_executable} -c \"import os; print(os.environ.get('MY_VAR', ''))\"",
            env={"MY_VAR": "my_value"},
            stdin=None,
            timeout=5.0,
        )

        assert result.exit_code == 0
        assert "my_value" in result.stdout

    def test_execute_string_command(self, runtime: LocalRuntime):
        """Test executing a string command."""
        result = runtime.execute(
            command="echo string_test",
            env={},
            stdin=None,
            timeout=5.0,
        )

        assert result.exit_code == 0
        assert "string_test" in result.stdout

    def test_execute_captures_multiline_output(
        self, runtime: LocalRuntime, python_executable: str
    ):
        """Test that execute captures all lines of output."""
        result = runtime.execute(
            command=f"{python_executable} -c \"print('line1'); print('line2'); print('line3')\"",
            env={},
            stdin=None,
            timeout=5.0,
        )

        assert result.exit_code == 0
        assert "line1" in result.stdout
        assert "line2" in result.stdout
        assert "line3" in result.stdout


class TestLocalRuntimeProcessManagement:
    """Tests for LocalRuntime process management methods."""

    @pytest.fixture
    def runtime(self, tmp_path: Path):
        """Create a runtime instance."""
        spec = LocalEnvironmentSpec(
            type="local",
            name="test",
            commands=CommandConfig(command="bash"),
        )
        return LocalRuntime(environment=spec, working_dir=tmp_path)

    def test_poll_running_process(self, runtime: LocalRuntime):
        """Test polling a running process."""
        runtime._start_proc(command="sleep 1", env={}, stdin=None)

        result = runtime.poll()
        # Process might be running or might have finished on fast systems
        assert result is None or result == 0

        runtime.kill()
        runtime.wait()

    def test_poll_finished_process(self, runtime: LocalRuntime):
        """Test polling a finished process."""
        runtime._start_proc(command="echo test", env={}, stdin=None)
        runtime.wait()

        result = runtime.poll()
        assert result == 0

    def test_kill_running_process(self, runtime: LocalRuntime):
        """Test killing a running process."""
        runtime._start_proc(command="sleep 10", env={}, stdin=None)
        time.sleep(0.1)  # Let it start

        runtime.kill()
        time.sleep(0.1)  # Let it die

        # Process should be terminated
        assert runtime.poll() is not None

    def test_wait_for_process(self, runtime: LocalRuntime):
        """Test waiting for a process to complete."""
        runtime._start_proc(command="echo test", env={}, stdin=None)

        exit_code = runtime.wait()
        assert exit_code == 0

    def test_wait_with_timeout(self, runtime: LocalRuntime):
        """Test waiting with a timeout."""
        runtime._start_proc(command="sleep 0.2", env={}, stdin=None)

        exit_code = runtime.wait(timeout=1.0)
        assert exit_code == 0

    def test_wait_timeout_expires(self, runtime: LocalRuntime):
        """Test that wait can timeout."""
        runtime._start_proc(command="sleep 10", env={}, stdin=None)

        with pytest.raises(subprocess.TimeoutExpired):
            runtime.wait(timeout=0.1)

        runtime.kill()
        runtime.wait()

    def test_cleanup_kills_process(self, runtime: LocalRuntime):
        """Test that cleanup kills a running process."""
        runtime._start_proc(command="sleep 10", env={}, stdin=None)
        time.sleep(0.1)

        runtime.cleanup()

        # Process should be killed
        assert runtime._proc.poll() is not None

    def test_cleanup_waits_for_process(self, runtime: LocalRuntime):
        """Test that cleanup waits for process to finish."""
        runtime._start_proc(command="echo test", env={}, stdin=None)

        runtime.cleanup()

        # Process should have exited
        assert runtime._proc.poll() is not None


class TestLocalRuntimeEdgeCases:
    """Tests for edge cases and error conditions."""

    @pytest.fixture
    def runtime(self, tmp_path: Path):
        """Create a runtime instance."""
        spec = LocalEnvironmentSpec(
            type="local",
            name="test",
            commands=CommandConfig(command="bash"),
        )
        return LocalRuntime(environment=spec, working_dir=tmp_path)

    def test_process_working_directory(self, tmp_path: Path):
        """Test that process runs in correct working directory."""
        test_file = tmp_path / "marker.txt"
        test_file.write_text("marker")

        spec = LocalEnvironmentSpec(
            type="local",
            name="test",
            commands=CommandConfig(command="bash"),
        )
        runtime = LocalRuntime(environment=spec, working_dir=tmp_path)

        result = runtime.execute(
            command="ls marker.txt",
            env={},
            stdin=None,
            timeout=5.0,
        )

        assert result.exit_code == 0

    def test_multiple_executions(self, runtime: LocalRuntime):
        """Test running multiple commands sequentially."""
        result1 = runtime.execute(
            command="echo first",
            env={},
            stdin=None,
            timeout=5.0,
        )

        result2 = runtime.execute(
            command="echo second",
            env={},
            stdin=None,
            timeout=5.0,
        )

        assert result1.exit_code == 0
        assert "first" in result1.stdout
        assert result2.exit_code == 0
        assert "second" in result2.stdout

    def test_command_with_special_characters(self, runtime: LocalRuntime):
        """Test command with special characters."""
        result = runtime.execute(
            command="echo test@#$%^&*()",
            env={},
            stdin=None,
            timeout=5.0,
        )

        assert result.exit_code == 0
        assert "test@#$%^&*()" in result.stdout

    def test_empty_stdout(self, runtime: LocalRuntime):
        """Test command with no stdout."""
        result = runtime.execute(
            command="true",
            env={},
            stdin=None,
            timeout=5.0,
        )

        assert result.exit_code == 0
        assert result.stdout == ""

    def test_large_output(self, runtime: LocalRuntime):
        """Test command with large output."""
        # Generate 1000 lines of output
        result = runtime.execute(
            command="bash -c 'for i in {1..1000}; do echo line$i; done'",
            env={},
            stdin=None,
            timeout=None,
        )

        assert result.exit_code == 0
        lines = result.stdout.strip().split("\n")
        assert len(lines) == 1000
        assert "line1" in result.stdout
        assert "line1000" in result.stdout

    def test_concurrent_output_streams(self, runtime: LocalRuntime):
        """Test handling concurrent stdout and stderr."""
        result = runtime.execute(
            command="bash -c 'for i in {1..10}; do echo out$i; echo err$i >&2; done'",
            env={},
            stdin=None,
            timeout=5.0,
        )

        assert result.exit_code == 0
        assert "out1" in result.stdout
        assert "out10" in result.stdout
        assert "err1" in result.stderr
        assert "err10" in result.stderr

    def test_process_state_after_timeout(self, runtime: LocalRuntime):
        """Test process state after timeout."""
        result = runtime.execute(
            command="sleep 10",
            env={},
            stdin=None,
            timeout=0.5,
        )

        assert result.timed_out is True
        # Process should be killed after timeout
        time.sleep(0.2)
        assert runtime._proc.poll() is not None


class TestLocalRuntimeStreamingEdgeCases:
    """Tests for streaming edge cases."""

    @pytest.fixture
    def runtime(self, tmp_path: Path):
        """Create a runtime instance."""
        spec = LocalEnvironmentSpec(
            type="local", name="test", commands=CommandConfig(command="bash")
        )
        return LocalRuntime(environment=spec, working_dir=tmp_path)

    def test_stream_immediate_exit(self, runtime: LocalRuntime):
        """Test streaming a command that exits immediately."""
        events = list(
            runtime.stream(
                command="true",
                env={},
                stdin=None,
                timeout=5.0,
            )
        )

        # Should have at least the finished event
        assert len(events) >= 1
        assert events[-1].kind == "finished"
        assert events[-1].result.exit_code == 0

    def test_stream_events_order(self, runtime: LocalRuntime):
        """Test that stream events are in correct order."""
        events = list(
            runtime.stream(
                command="bash -c 'echo out1; echo out2'",
                env={},
                stdin=None,
                timeout=5.0,
            )
        )

        # Last event should be finished
        assert events[-1].kind == "finished"

        # All events before last should be stdout or stderr
        for event in events[:-1]:
            assert event.kind in ["stdout", "stderr"]

    def test_stream_result_completeness(self, runtime: LocalRuntime):
        """Test that stream result contains all output."""
        events = list(
            runtime.stream(
                command="bash -c 'echo a; echo b; echo c'",
                env={},
                stdin=None,
                timeout=5.0,
            )
        )

        result = events[-1].result

        # Result should aggregate all output
        assert "a" in result.stdout
        assert "b" in result.stdout
        assert "c" in result.stdout


class TestLocalRuntimeIntegration:
    """Integration tests for LocalRuntime."""

    def test_full_lifecycle(self, tmp_path: Path):
        """Test full lifecycle of runtime from spawn to cleanup."""
        test_file = tmp_path / "output.txt"

        spec = LocalEnvironmentSpec(
            type="local",
            name="test",
            commands=CommandConfig(command="bash"),
            environment=EnvironmentConfig(env={"TEST": "value"}),
        )

        runtime = LocalRuntime.spawn(environment=spec, working_dir=tmp_path)

        # Execute a command
        result = runtime.execute(
            command=f"bash -c 'echo $TEST > {test_file}'",
            env={},
            stdin=None,
            timeout=5.0,
        )

        assert result.exit_code == 0
        assert test_file.exists()
        assert "value" in test_file.read_text()

        # Cleanup
        runtime.cleanup()

    def test_environment_inheritance(self, tmp_path: Path):
        """Test that environment variables are properly inherited."""
        spec = LocalEnvironmentSpec(
            type="local",
            name="test",
            commands=CommandConfig(command="bash"),
            environment=EnvironmentConfig(
                env={"BASE_VAR": "base", "OVERRIDE": "original"}
            ),
        )

        runtime = LocalRuntime.spawn(environment=spec, working_dir=tmp_path)

        result = runtime.execute(
            command="bash -c 'echo $BASE_VAR-$OVERRIDE-$CUSTOM'",
            env={"OVERRIDE": "new", "CUSTOM": "custom"},
            stdin=None,
            timeout=5.0,
        )

        assert result.exit_code == 0
        output = result.stdout.strip()
        assert "base" in output
        assert "new" in output
        assert "custom" in output
