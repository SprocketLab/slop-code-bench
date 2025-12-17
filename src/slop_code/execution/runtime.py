"""Runtime protocol and implementations for code execution.

This module defines the core runtime interface and supporting structures:

- **SubmissionRuntime**: Protocol defining runtime interface for all implementations
- **LaunchSpec**: Configuration for spawning runtime instances
- **RuntimeResult**: Summary of completed execution with output and metadata
- **RuntimeEvent**: Events emitted during streaming execution
- **Runtime registry**: System for registering and spawning runtime implementations
- **SolutionRuntimeError**: Runtime-specific exception

The runtime protocol provides a unified interface for both Docker and local
execution environments, supporting streaming output, timeouts, and proper cleanup.
"""

from abc import ABC
from abc import abstractmethod
from collections.abc import Callable
from collections.abc import Iterator
from pathlib import Path
from typing import Literal

from pydantic import BaseModel
from pydantic import Field

from slop_code.execution.assets import ResolvedStaticAsset
from slop_code.execution.models import EnvironmentSpec
from slop_code.execution.models import ExecutionError


class SolutionRuntimeError(ExecutionError):
    """Exception raised by the SolutionRuntime class."""


class LaunchSpec(BaseModel):
    """Specification for launching a runtime instance.

    Attributes:
        working_dir: Directory where the runtime should operate
        environment: Environment specification for execution
        static_assets: Optional static assets to make available
        is_evaluation: Whether this is for evaluation vs agent execution
        ports: Extra ports to use
        mounts: Extra mounts to use
        setup_command: Setup command to use in addition to the spec commands.
    """

    working_dir: Path
    environment: EnvironmentSpec
    static_assets: dict[str, ResolvedStaticAsset] | None = None
    is_evaluation: bool = False
    ports: dict[int, int] = Field(default_factory=dict)
    mounts: dict[str, dict[str, str] | str] = Field(default_factory=dict)
    env_vars: dict[str, str] = Field(default_factory=dict)
    setup_command: str | None = None


class RuntimeResult(BaseModel):
    """Summary of a completed runtime invocation.

    Attributes:
        exit_code: Process exit code
        stdout: Captured stdout output
        stderr: Captured stderr output
        setup_stdout: Captured stdout output from setup command
        setup_stderr: Captured stderr output from setup command
        elapsed: Execution time in seconds
        timed_out: Whether execution timed out
    """

    exit_code: int
    stdout: str
    stderr: str
    setup_stdout: str
    setup_stderr: str
    elapsed: float
    timed_out: bool


class RuntimeEvent(BaseModel):
    """Event emitted during runtime execution.

    Attributes:
        kind: Type of event (stdout, stderr, or finished)
        text: Text content for stdout/stderr events
        result: Runtime result for finished events
    """

    kind: Literal["stdout", "stderr", "finished"]
    text: str | None = None
    result: RuntimeResult | None = None


class SubmissionRuntime(ABC):
    """Protocol for runtime implementations that can execute code.

    This protocol defines the interface that all runtime implementations
    (Docker, local, etc.) must provide for executing commands and managing
    process lifecycle.
    """

    @abstractmethod
    def stream(
        self,
        command: str,
        env: dict[str, str],
        stdin: str | list[str] | None,
        timeout: float | None,
    ) -> Iterator[RuntimeEvent]:
        """Stream execution of a command.

        Note:
            Most implementations do not support stdin for streaming execution.
            If stdin is required, use execute() instead.

        Args:
            command: Command to execute
            env: Environment variables
            stdin: Optional stdin input (may not be supported by all implementations)
            timeout: Optional timeout in seconds
            ports: Optional port mappings

        Yields:
            RuntimeEvent objects for stdout, stderr, and completion
        """

    @abstractmethod
    def execute(
        self,
        command: str,
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
            ports: Optional port mappings

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
        static_assets: dict[str, ResolvedStaticAsset] | None = None,
        ports: dict[int, int] | None = None,
        mounts: dict[str, dict[str, str] | str] | None = None,
        env_vars: dict[str, str] | None = None,
        *,
        is_evaluation: bool = False,
        disable_setup: bool = False,
        **runtime_kwargs,
    ) -> "SubmissionRuntime":
        """Spawn a new runtime instance.

        Args:
            environment: Environment specification
            working_dir: Directory to mount as workspace in container
            static_assets: Optional static assets to mount in container
            is_evaluation: Whether this is an evaluation context
            ports: Extra ports to use
            mounts: Extra mounts to use
            env_vars: Extra environment variables to use
            disable_setup: Whether to disable setup
            runtime_kwargs: Additional runtime-specific arguments
        Returns:
            New runtime instance
        """


RUNTIME_REGISTRY: dict[str, type[SubmissionRuntime]] = {}


def register_runtime(
    name: str,
) -> Callable[[type[SubmissionRuntime]], type[SubmissionRuntime]]:
    """Registers a runtime class for a given environment type.

    Args:
        name: Name of the environment type (e.g., "docker", "local")

    Returns:
        Decorator function that registers the runtime class
    """

    def decorator(cls: type[SubmissionRuntime]) -> type[SubmissionRuntime]:
        RUNTIME_REGISTRY[name] = cls
        return cls

    return decorator


def spawn_runtime(environment: EnvironmentSpec, **kwargs) -> SubmissionRuntime:
    """Spawns a runtime for a given launch spec.

    Args:
        spec: Launch specification containing environment and settings

    Returns:
        Runtime instance appropriate for the environment type

    Raises:
        KeyError: If environment type is not registered
    """
    runtime_cls = RUNTIME_REGISTRY[environment.type]
    return runtime_cls.spawn(environment=environment, **kwargs)
