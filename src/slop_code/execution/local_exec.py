"""Local process execution runtime for one-shot command execution.

This runtime executes commands directly on the host system with
buffered output, suitable for evaluation and testing.
"""

from __future__ import annotations

import shlex
import subprocess
import time
from pathlib import Path

from slop_code.execution.assets import ResolvedStaticAsset
from slop_code.execution.local_streaming import LocalEnvironmentSpec
from slop_code.execution.models import EnvironmentSpec
from slop_code.execution.protocols import ExecRuntime
from slop_code.execution.runtime import RuntimeResult
from slop_code.logging import get_logger

logger = get_logger(__name__)


class LocalExecRuntime(ExecRuntime):
    """Local process execution runtime for evaluation.

    Simple subprocess.run() wrapper with stdin support for
    one-shot command execution.
    """

    def __init__(
        self,
        environment: LocalEnvironmentSpec,
        working_dir: Path,
        command: str,
        static_assets: dict[str, ResolvedStaticAsset] | None = None,
        ports: dict[int, int] | None = None,
        mounts: dict[str, dict[str, str] | str] | None = None,
        env_vars: dict[str, str] | None = None,
        setup_command: str | None = None,
        *,
        is_evaluation: bool = False,
    ) -> None:
        """Initialize local exec runtime.

        Args:
            environment: Local environment specification
            working_dir: Directory to execute commands in
            command: Command to execute (immutable)
            static_assets: Static assets (ignored for local)
            ports: Ports (ignored for local)
            mounts: Mounts (ignored for local)
            env_vars: Environment variables to set
            setup_command: Setup command to run
            is_evaluation: Whether this is an evaluation run
        """
        logger.debug(
            "Initializing local exec runtime",
            working_dir=working_dir,
            command=command[:100],
            verbose=True,
        )
        self.spec = environment
        self._command = command
        self._static_assets = static_assets or {}
        self._ports = ports or {}
        self._mounts = mounts or {}
        self._env_vars = env_vars or {}
        self._is_evaluation = is_evaluation
        self._setup_command = setup_command
        self.cwd = working_dir
        self._proc: subprocess.Popen | None = None
        self._exit_code: int | None = None

    def _prepare_stdin(self, stdin: str | list[str] | None) -> bytes | None:
        """Prepare stdin data for subprocess."""
        if stdin is None:
            return None
        if isinstance(stdin, list):
            return "".join(stdin).encode("utf-8")
        return stdin.encode("utf-8")

    def execute(
        self,
        env: dict[str, str],
        stdin: str | list[str] | None,
        timeout: float | None,
    ) -> RuntimeResult:
        """Execute the command and return the result.

        Args:
            env: Environment variables
            stdin: Optional stdin input
            timeout: Optional timeout in seconds

        Returns:
            RuntimeResult with execution details
        """
        logger.debug(
            "Executing local command",
            command=self._command[:200],
            timeout=timeout,
            has_stdin=stdin is not None,
            verbose=True,
        )

        cmd_args = shlex.split(self._command)
        stdin_data = self._prepare_stdin(stdin)
        full_env = self.spec.get_full_env({**self._env_vars, **env})

        start_time = time.time()
        timed_out = False

        try:
            proc = subprocess.Popen(
                cmd_args,
                cwd=self.cwd,
                env=full_env,
                stdin=subprocess.PIPE if stdin_data is not None else None,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self._proc = proc

            try:
                stdout_bytes, stderr_bytes = proc.communicate(
                    input=stdin_data, timeout=timeout
                )
            except subprocess.TimeoutExpired:
                timed_out = True
                proc.kill()
                stdout_bytes, stderr_bytes = proc.communicate()

            exit_code = proc.returncode
        except Exception as e:
            logger.error("Failed to execute command", error=str(e))
            return RuntimeResult(
                exit_code=-1,
                stdout="",
                stderr=str(e),
                setup_stdout="",
                setup_stderr="",
                elapsed=time.time() - start_time,
                timed_out=False,
            )
        finally:
            self._proc = None

        elapsed = time.time() - start_time
        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")

        self._exit_code = exit_code

        logger.debug(
            "Local command completed",
            exit_code=exit_code,
            elapsed=elapsed,
            timed_out=timed_out,
            verbose=True,
        )

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
        """Check if the process is still running."""
        if self._proc is not None:
            exit_code = self._proc.poll()
            if exit_code is not None:
                self._exit_code = exit_code
                self._proc = None
            return exit_code
        return self._exit_code

    def kill(self) -> None:
        """Kill the running process."""
        if self._proc is not None:
            logger.debug("Killing subprocess", verbose=True)
            self._proc.kill()
            self._proc.wait(timeout=5)
            self._proc = None

    def cleanup(self) -> None:
        """Clean up the process."""
        logger.debug("Cleaning up local exec runtime", verbose=True)
        self.kill()

    @classmethod
    def spawn(
        cls,
        environment: EnvironmentSpec,
        working_dir: Path,
        command: str,
        static_assets: dict[str, ResolvedStaticAsset] | None = None,
        ports: dict[int, int] | None = None,
        mounts: dict[str, dict[str, str] | str] | None = None,
        env_vars: dict[str, str] | None = None,
        setup_command: str | None = None,
        *,
        is_evaluation: bool = False,
        disable_setup: bool = False,
        **_runtime_kwargs,
    ) -> LocalExecRuntime:
        """Spawn a new local exec runtime instance.

        Args:
            environment: Environment specification
            working_dir: Working directory path
            command: Command to execute (immutable)
            static_assets: Optional static assets
            ports: Optional port mappings (ignored)
            mounts: Optional volume mounts (ignored)
            env_vars: Optional environment variables
            setup_command: Optional setup command
            is_evaluation: Whether this is an evaluation context
            disable_setup: Whether to disable setup commands

        Returns:
            New LocalExecRuntime instance

        Raises:
            ValueError: If environment spec is not for local runtime
        """
        if not isinstance(environment, LocalEnvironmentSpec):
            raise ValueError("Invalid environment spec for local runtime")

        # Run setup commands before creating runtime if not disabled
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

        return cls(
            environment=environment,
            working_dir=working_dir,
            command=command,
            static_assets=static_assets,
            ports=ports,
            mounts=mounts,
            env_vars=env_vars,
            setup_command=setup_command,
            is_evaluation=is_evaluation,
        )
