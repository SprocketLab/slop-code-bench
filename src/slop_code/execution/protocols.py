"""Protocol definitions for runtime implementations.

This module defines the core runtime protocols:

- **StreamingRuntime**: For interactive agent sessions with streamed output
- **ExecRuntime**: For one-shot evaluation with buffered output

These protocols provide a clean separation between streaming (long-lived,
multiple commands) and execution (single command, immutable at spawn).
"""

from abc import ABC
from abc import abstractmethod
from collections.abc import Iterator
from pathlib import Path

from slop_code.execution.assets import ResolvedStaticAsset
from slop_code.execution.models import EnvironmentSpec
from slop_code.execution.runtime import RuntimeEvent
from slop_code.execution.runtime import RuntimeResult


class StreamingRuntime(ABC):
    """Protocol for streaming/interactive runtime implementations.

    Used by agents for long-running sessions where multiple commands
    are executed and output is streamed in real-time.

    Key characteristics:
    - Persistent container/process across multiple stream() calls
    - Real-time output streaming via RuntimeEvent iterator
    - No stdin support (use ExecRuntime for stdin)
    """

    @abstractmethod
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

    @abstractmethod
    def poll(self) -> int | None:
        """Check if the process is still running.

        Returns:
            Exit code if process has finished, None if still running
        """

    @abstractmethod
    def kill(self) -> None:
        """Kill the running process/container."""

    @abstractmethod
    def cleanup(self) -> None:
        """Clean up all resources used by the runtime."""

    @classmethod
    @abstractmethod
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
        **runtime_kwargs,
    ) -> "StreamingRuntime":
        """Spawn a new streaming runtime instance.

        Args:
            environment: Environment specification
            working_dir: Directory to mount as workspace
            static_assets: Optional static assets to mount
            ports: Optional port mappings
            mounts: Optional volume mounts
            env_vars: Optional environment variables
            setup_command: Optional setup command
            is_evaluation: Whether this is an evaluation context
            disable_setup: Whether to disable setup commands
            runtime_kwargs: Additional runtime-specific arguments

        Returns:
            New streaming runtime instance
        """


class ExecRuntime(ABC):
    """Protocol for one-shot execution runtime implementations.

    Used by evaluation for single command execution with buffered output.

    Key characteristics:
    - Command is immutable, set at spawn time
    - Single execute() call returns complete RuntimeResult
    - Supports stdin input
    - Ephemeral container/process (cleaned up after execute)
    """

    @abstractmethod
    def execute(
        self,
        env: dict[str, str],
        stdin: str | list[str] | None,
        timeout: float | None,
    ) -> RuntimeResult:
        """Execute the runtime's command and return the result.

        Note: The command was set at spawn time and cannot be changed.

        Args:
            env: Environment variables
            stdin: Optional stdin input
            timeout: Optional timeout in seconds

        Returns:
            RuntimeResult with execution details
        """

    @abstractmethod
    def poll(self) -> int | None:
        """Check if the process is still running.

        Returns:
            Exit code if process has finished, None if still running
        """

    @abstractmethod
    def kill(self) -> None:
        """Kill the running process/container."""

    @abstractmethod
    def cleanup(self) -> None:
        """Clean up all resources used by the runtime."""

    @classmethod
    @abstractmethod
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
        **runtime_kwargs,
    ) -> "ExecRuntime":
        """Spawn a new execution runtime instance.

        Args:
            environment: Environment specification
            working_dir: Directory to mount as workspace
            command: Command to execute (immutable)
            static_assets: Optional static assets to mount
            ports: Optional port mappings
            mounts: Optional volume mounts
            env_vars: Optional environment variables
            setup_command: Optional setup command
            is_evaluation: Whether this is an evaluation context
            disable_setup: Whether to disable setup commands
            runtime_kwargs: Additional runtime-specific arguments

        Returns:
            New execution runtime instance
        """
