"""Local process runtime implementation for executing commands directly on the host.

This module provides a runtime that executes commands directly on the host system
without containerization, including:

- **LocalEnvironmentSpec**: Configuration for local execution environments
- **LocalRuntime**: Runtime implementation for local process execution
- Process lifecycle management with proper cleanup
- Streaming output capture for stdout/stderr
- Timeout handling and process termination

The local runtime is useful for development, testing, and scenarios where
containerization is not required or desired.
"""

from __future__ import annotations

import selectors
import shlex
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Literal

from pydantic import Field

from slop_code.execution.assets import ResolvedStaticAsset
from slop_code.execution.models import EnvironmentSpec
from slop_code.execution.models import LocalConfig
from slop_code.execution.runtime import RuntimeEvent
from slop_code.execution.runtime import RuntimeResult
from slop_code.execution.runtime import SolutionRuntimeError
from slop_code.execution.runtime import SubmissionRuntime
from slop_code.execution.runtime import register_runtime
from slop_code.execution.stream_processor import process_stream
from slop_code.logging import get_logger

log = get_logger(__name__)


class LocalEnvironmentSpec(EnvironmentSpec):
    """Host-based execution with no containerization.

    Attributes:
        local: Local execution-specific configuration
    """

    type: Literal["local"] = "local"  # type: ignore[assignment]
    local: LocalConfig = Field(
        default_factory=LocalConfig,
        description="Local execution-specific configuration.",
    )


def _normalize_command(command: str | list[str]) -> list[str]:
    """Normalize command to list of strings.

    Args:
        command: Command as string or list

    Returns:
        Command as list of strings
    """
    if isinstance(command, list):
        return list(command)
    return shlex.split(command)


@register_runtime("local")
class LocalRuntime(SubmissionRuntime):
    """Local process runtime implementation.

    Executes commands directly on the host system without containerization.
    """

    def __init__(
        self,
        environment: LocalEnvironmentSpec,
        working_dir: Path,
        static_assets: dict[str, ResolvedStaticAsset] | None = None,
        ports: dict[int, int] | None = None,
        mounts: dict[str, dict[str, str] | str] | None = None,
        env_vars: dict[str, str] | None = None,
        setup_command: str | None = None,
        *,
        is_evaluation: bool = False,
    ) -> None:
        """Initialize local runtime.

        Args:
            environment: Local environment specification
            working_dir: Directory to execute commands in
            static_assets: Static assets to mount
            ports: Ports to expose
            mounts: Mounts to use
            env_vars: Environment variables to set
            setup_command: Setup command to run
            is_evaluation: Whether this is an evaluation run
        """
        log.debug(
            "Initializing local runtime",
            working_dir=working_dir,
            requires_tty=environment.local.requires_tty,
            verbose=True,
        )
        self.spec = environment
        self._static_assets = static_assets or {}
        self._setup_command = setup_command
        self._ports = ports or {}
        self._mounts = mounts or {}
        self._env_vars = env_vars or {}
        self._is_evaluation = is_evaluation
        self._proc = None
        self.cwd = working_dir
        self._stream_stdout_buffer = ""
        self._stream_stderr_buffer = ""

    @property
    def process(self) -> subprocess.Popen:
        """Get the current subprocess instance.

        Returns:
            Running subprocess instance

        Raises:
            SolutionRuntimeError: If no process is running
        """
        if self._proc is None:
            raise SolutionRuntimeError("Process not running")
        return self._proc

    @classmethod
    def spawn(
        cls,
        environment: EnvironmentSpec,
        working_dir: Path,
        static_assets: dict[str, ResolvedStaticAsset] | None = None,
        ports: dict[int, int] | None = None,
        mounts: dict[str, dict[str, str] | str] | None = None,
        env_vars: dict[str, str] | None = None,
        setup_command: str | None = None,
        *,
        is_evaluation: bool = False,
        **_,
    ) -> LocalRuntime:
        """Spawn a new local runtime instance.

        Args:
            spec: Launch specification containing environment and settings

        Returns:
            New LocalRuntime instance

        Raises:
            ValueError: If environment spec is not for local runtime
        """
        if not isinstance(environment, LocalEnvironmentSpec):
            raise ValueError("Invalid environment spec for local runtime")
        runtime = cls(
            environment=environment,
            working_dir=working_dir,
            static_assets=static_assets,
            ports=ports,
            mounts=mounts,
            env_vars=env_vars,
            setup_command=setup_command,
            is_evaluation=is_evaluation,
        )

        setup_commands = environment.get_setup_commands(is_evaluation)
        if setup_command:
            setup_commands.append(setup_command)
        log.debug(
            "Running setup commands",
            num_commands=len(setup_commands),
            is_evaluation=is_evaluation,
            verbose=True,
        )

        for command in setup_commands:
            runtime.execute(
                command=command,
                env=environment.get_full_env({}),
                stdin=None,
                timeout=None,
            )
        return runtime

    def _start_proc(
        self,
        command: str | list[str],
        env: dict[str, str],
        stdin: str | list[str] | None,
    ):
        """Start a subprocess for the given command.

        Args:
            command: Command to execute
            env: Environment variables
            stdin: Optional stdin input

        Raises:
            SolutionRuntimeError: If a process is already running
        """
        if self._proc is not None and self._proc.poll() is None:
            try:
                self._proc.wait(timeout=10)
            except subprocess.TimeoutExpired as e:
                self._proc.kill()
                raise SolutionRuntimeError("Process is still running") from e

        log.debug(
            "Starting subprocess",
            command=command,
            cwd=self.cwd,
            has_stdin=stdin is not None,
            verbose=True,
        )

        # Handle both string and list commands
        cmd_args = (
            command if isinstance(command, list) else shlex.split(command)  # type: ignore[arg-type]
        )

        self._proc = subprocess.Popen(
            cmd_args,
            env=self.spec.get_full_env(env),
            stdin=subprocess.PIPE if stdin is not None else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=self.cwd,
            encoding="utf-8",
            errors="replace",
            bufsize=0,
        )
        if stdin is None:
            return
        # Write all stdin data and close the pipe
        if self._proc.stdin:
            payloads = stdin if isinstance(stdin, list) else [stdin]
            log.debug(
                "Writing stdin to subprocess",
                num_payloads=len(payloads),
                total_bytes=sum(len(p.encode("utf-8")) for p in payloads),
                verbose=True,
            )
            for payload in payloads:
                self._proc.stdin.write(payload)
            self._proc.stdin.close()

    def _create_demuxed_stream(self) -> Iterator[tuple[str, str]]:
        """Create a demuxed stream from stdout/stderr.

        Yields:
            Tuples of (stdout_chunk, stderr_chunk)
        """
        self._stream_stdout_buffer = ""
        self._stream_stderr_buffer = ""
        sel = selectors.DefaultSelector()
        sel.register(self._proc.stdout, selectors.EVENT_READ, data="OUT")
        sel.register(self._proc.stderr, selectors.EVENT_READ, data="ERR")

        try:
            while sel.get_map():
                for key, _ in sel.select():
                    chunk = key.fileobj.read(8192)
                    if not chunk:
                        sel.unregister(key.fileobj)
                        continue
                    if key.data == "OUT":
                        self._stream_stdout_buffer += chunk
                        yield (chunk, "")
                    else:
                        self._stream_stderr_buffer += chunk
                        yield ("", chunk)

        finally:
            # Close streams
            if self.process.stdout:
                self.process.stdout.close()
            if self.process.stderr:
                self.process.stderr.close()

    def stream(
        self,
        command: str | list[str],
        env: dict[str, str],
        stdin: str | list[str] | None,
        timeout: float | None,
    ) -> Iterator[RuntimeEvent]:
        """Stream execution of a command.

        Args:
            command: Command to execute
            env: Environment variables
            stdin: Must be None (stdin not supported for streaming)
            timeout: Optional timeout in seconds

        Yields:
            RuntimeEvent objects for stdout, stderr, and completion

        Raises:
            ValueError: If stdin is provided (not supported for streaming)
        """
        if stdin is not None:
            raise ValueError(
                "stdin is not supported for stream(). Use execute() instead."
            )
        self._start_proc(command, env, None)

        log.debug(
            "Streaming from local process",
            command=command,
            timeout=timeout,
            verbose=True,
        )
        stream = self._create_demuxed_stream()
        # Use process_stream with demuxed stream
        result = yield from process_stream(
            stream,
            timeout,
            self.poll,
        )

        # Kill process if it timed out
        if result.timed_out:
            log.warning("local_runtime.timeout", command=command, verbose=True)

            self.kill()

        # Get exit code
        exit_code = self.process.wait()
        fallback_stdout = self._stream_stdout_buffer
        fallback_stderr = self._stream_stderr_buffer
        self._stream_stdout_buffer = ""
        self._stream_stderr_buffer = ""
        stdout = result.stdout or fallback_stdout
        stderr = result.stderr or fallback_stderr

        log.debug(
            "Streaming from local process completed",
            exit_code=exit_code,
            elapsed=result.elapsed,
            timed_out=result.timed_out,
            verbose=True,
        )

        # Yield finished event with correct exit code
        final_result = RuntimeResult(
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            setup_stdout=result.setup_stdout,
            setup_stderr=result.setup_stderr,
            elapsed=result.elapsed,
            timed_out=result.timed_out,
        )
        yield RuntimeEvent(kind="finished", result=final_result)

    def execute(
        self,
        command: str | list[str],
        env: dict[str, str],
        stdin: str | list[str] | None,
        timeout: float | None,
    ) -> RuntimeResult:
        """Execute a command and return the result.

        Args:
            command: Command to execute
            env: Environment variables
            stdin: Optional stdin input
            timeout: Optional timeout in seconds
            ports: Ignored for local runtime

        Returns:
            RuntimeResult with execution details
        """
        start_time = time.time()
        timed_out = False
        self._start_proc(command, env, stdin)
        try:
            exit_code = self.process.wait(timeout=timeout or None)
        except subprocess.TimeoutExpired:
            self.kill()
            timed_out = True
            exit_code = -1
        finally:
            elapsed = time.time() - start_time
            if self.process.stdout:
                stdout = self.process.stdout.read()
            else:
                stdout = "NO_STDOUT_FOUND"
            if self.process.stderr:
                stderr = self.process.stderr.read()
            else:
                stderr = "NO_STDERR_FOUND"

        return RuntimeResult(
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            setup_stdout="",
            setup_stderr="",
            elapsed=elapsed,
            timed_out=timed_out,
        )

    def poll(self) -> int | None:
        """Check if the process is still running.

        Returns:
            Exit code if process has finished, None if still running
        """
        return self.process.poll()

    def kill(self) -> None:
        """Kill the running process."""
        log.debug("Killing subprocess", verbose=True)
        self.process.kill()

    def wait(self, timeout: float | None = None) -> int:
        """Wait for the process to finish.

        Args:
            timeout: Optional timeout in seconds

        Returns:
            Process exit code
        """
        return self.process.wait(timeout=timeout)

    def cleanup(self) -> None:
        """Clean up the process."""
        log.debug("Cleaning up local runtime resources", verbose=True)
        self.kill()
        self.wait(timeout=10)
