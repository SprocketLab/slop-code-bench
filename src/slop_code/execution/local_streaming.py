"""Local process streaming runtime for interactive execution.

This runtime executes commands directly on the host system with
streaming output, suitable for agent development and testing.
"""

from __future__ import annotations

import selectors
import shlex
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Literal

from pydantic import Field

from slop_code.execution.assets import ResolvedStaticAsset
from slop_code.execution.models import EnvironmentSpec
from slop_code.execution.models import LocalConfig
from slop_code.execution.protocols import StreamingRuntime
from slop_code.execution.runtime import RuntimeEvent
from slop_code.execution.runtime import RuntimeResult
from slop_code.execution.runtime import SolutionRuntimeError
from slop_code.execution.stream_processor import process_stream
from slop_code.logging import get_logger

logger = get_logger(__name__)


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


class LocalStreamingRuntime(StreamingRuntime):
    """Local process streaming runtime for development.

    Uses subprocess with selector-based output demuxing for
    streaming execution without containerization.
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
        """Initialize local streaming runtime.

        Args:
            environment: Local environment specification
            working_dir: Directory to execute commands in
            static_assets: Static assets (ignored for local)
            ports: Ports (ignored for local)
            mounts: Mounts (ignored for local)
            env_vars: Environment variables to set
            setup_command: Setup command to run
            is_evaluation: Whether this is an evaluation run
        """
        logger.debug(
            "Initializing local streaming runtime",
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
        self._proc: subprocess.Popen | None = None
        self.cwd = working_dir

    @property
    def process(self) -> subprocess.Popen:
        """Get the current subprocess instance."""
        if self._proc is None:
            raise SolutionRuntimeError("Process not running")
        return self._proc

    def _start_process(
        self,
        command: str,
        env: dict[str, str],
    ) -> subprocess.Popen:
        """Start a subprocess for the given command.

        Args:
            command: Command to execute
            env: Environment variables
        """
        if self._proc is not None and self._proc.poll() is None:
            try:
                self._proc.wait(timeout=10)
            except subprocess.TimeoutExpired as e:
                self._proc.kill()
                raise SolutionRuntimeError("Process is still running") from e

        logger.debug(
            "Starting subprocess",
            command=command,
            cwd=self.cwd,
            verbose=True,
        )

        cmd_args = shlex.split(command)

        self._proc = subprocess.Popen(
            cmd_args,
            env=self.spec.get_full_env(env),
            stdin=None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=self.cwd,
            encoding="utf-8",
            errors="replace",
            bufsize=0,
        )
        return self._proc

    def _create_demuxed_stream(
        self, proc: subprocess.Popen
    ) -> Iterator[tuple[str, str]]:
        """Create a demuxed stream from stdout/stderr.

        Yields:
            Tuples of (stdout_chunk, stderr_chunk)
        """
        sel = selectors.DefaultSelector()
        sel.register(proc.stdout, selectors.EVENT_READ, data="OUT")
        sel.register(proc.stderr, selectors.EVENT_READ, data="ERR")

        try:
            while sel.get_map():
                for key, _ in sel.select():
                    chunk = key.fileobj.read(8192)
                    if not chunk:
                        sel.unregister(key.fileobj)
                        continue
                    if key.data == "OUT":
                        yield (chunk, "")
                    else:
                        yield ("", chunk)
        finally:
            if proc.stdout:
                proc.stdout.close()
            if proc.stderr:
                proc.stderr.close()

    def stream(
        self,
        command: str,
        env: dict[str, str],
        timeout: float | None,
    ) -> Iterator[RuntimeEvent]:
        """Stream execution of a command.

        Args:
            command: Command to execute
            env: Environment variables
            timeout: Optional timeout in seconds

        Yields:
            RuntimeEvent objects for stdout, stderr, and completion
        """
        proc = self._start_process(command, env)

        logger.debug(
            "Streaming from local process",
            command=command,
            timeout=timeout,
            verbose=True,
        )

        stream = self._create_demuxed_stream(proc)
        result = yield from process_stream(stream, timeout, self.poll)

        # Kill process if it timed out
        if result.timed_out:
            logger.warning("local_runtime.timeout", command=command)
            self.kill()

        # Get exit code
        exit_code = proc.wait()

        logger.debug(
            "Streaming from local process completed",
            exit_code=exit_code,
            elapsed=result.elapsed,
            timed_out=result.timed_out,
            verbose=True,
        )

        # Yield finished event
        final_result = RuntimeResult(
            exit_code=exit_code,
            stdout=result.stdout,
            stderr=result.stderr,
            setup_stdout=result.setup_stdout,
            setup_stderr=result.setup_stderr,
            elapsed=result.elapsed,
            timed_out=result.timed_out,
        )
        yield RuntimeEvent(kind="finished", result=final_result)

    def poll(self) -> int | None:
        """Check if the process is still running."""
        if self._proc is None:
            return None
        return self._proc.poll()

    def kill(self) -> None:
        """Kill the running process."""
        if self._proc is None:
            return
        logger.debug("Killing subprocess", verbose=True)
        self._proc.kill()

    def cleanup(self) -> None:
        """Clean up the process."""
        logger.debug("Cleaning up local streaming runtime", verbose=True)
        if self._proc is not None:
            self.kill()
            self._proc.wait(timeout=10)

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
        disable_setup: bool = False,
        **_runtime_kwargs,
    ) -> LocalStreamingRuntime:
        """Spawn a new local streaming runtime instance.

        Args:
            environment: Environment specification
            working_dir: Working directory path
            static_assets: Optional static assets
            ports: Optional port mappings (ignored)
            mounts: Optional volume mounts (ignored)
            env_vars: Optional environment variables
            setup_command: Optional setup command
            is_evaluation: Whether this is an evaluation context
            disable_setup: Whether to disable setup commands

        Returns:
            New LocalStreamingRuntime instance

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

        # Run setup commands if not disabled
        if not disable_setup:
            setup_commands = environment.get_setup_commands(is_evaluation)
            if setup_command:
                setup_commands.append(setup_command)
            logger.debug(
                "Running setup commands",
                num_commands=len(setup_commands),
                is_evaluation=is_evaluation,
                verbose=True,
            )
            for cmd in setup_commands:
                # Execute setup commands synchronously
                proc = subprocess.run(
                    shlex.split(cmd),
                    cwd=working_dir,
                    env=environment.get_full_env(env_vars or {}),
                    capture_output=True,
                    text=True,
                )
                if proc.returncode != 0:
                    logger.warning(
                        "Setup command failed",
                        command=cmd,
                        exit_code=proc.returncode,
                        stderr=proc.stderr[:500] if proc.stderr else "",
                    )

        return runtime
