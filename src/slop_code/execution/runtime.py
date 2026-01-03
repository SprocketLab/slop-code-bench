"""Runtime protocol and implementations for code execution.

This module defines the core runtime interfaces and supporting structures:

- **StreamingRuntime**: Protocol for interactive streaming execution (agents)
- **ExecRuntime**: Protocol for one-shot execution (evaluation)
- **RuntimeResult**: Summary of completed execution with output and metadata
- **RuntimeEvent**: Events emitted during streaming execution
- **LaunchSpec**: Configuration for spawning runtime instances
- **Runtime registries**: System for registering and spawning runtime implementations
- **SolutionRuntimeError**: Runtime-specific exception

The runtime protocols provide separate interfaces for streaming (interactive,
long-lived) and execution (one-shot, buffered) use cases.
"""

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel
from pydantic import Field

from slop_code.execution.assets import ResolvedStaticAsset
from slop_code.execution.models import EnvironmentSpec
from slop_code.execution.models import ExecutionError

if TYPE_CHECKING:
    from slop_code.execution.protocols import ExecRuntime
    from slop_code.execution.protocols import StreamingRuntime


class SolutionRuntimeError(ExecutionError):
    """Exception raised by runtime implementations."""


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


# Registries for streaming and exec runtimes
STREAMING_RUNTIME_REGISTRY: dict[str, type["StreamingRuntime"]] = {}
EXEC_RUNTIME_REGISTRY: dict[str, type["ExecRuntime"]] = {}


def register_streaming_runtime(
    name: str,
) -> Callable[[type], type]:
    """Register a streaming runtime class for a given environment type.

    Args:
        name: Name of the environment type (e.g., "docker", "local")

    Returns:
        Decorator function that registers the runtime class
    """

    def decorator(cls: type) -> type:
        STREAMING_RUNTIME_REGISTRY[name] = cls
        return cls

    return decorator


def register_exec_runtime(
    name: str,
) -> Callable[[type], type]:
    """Register an exec runtime class for a given environment type.

    Args:
        name: Name of the environment type (e.g., "docker", "local")

    Returns:
        Decorator function that registers the runtime class
    """

    def decorator(cls: type) -> type:
        EXEC_RUNTIME_REGISTRY[name] = cls
        return cls

    return decorator


# Lazy registration state
_runtimes_registered = False


def _ensure_runtimes_registered() -> None:
    """Ensure all runtime implementations are registered (lazy registration)."""
    global _runtimes_registered
    if _runtimes_registered:
        return

    # Docker runtimes
    from slop_code.execution.docker_runtime.exec import DockerExecRuntime
    from slop_code.execution.docker_runtime.streaming import (
        DockerStreamingRuntime,
    )

    STREAMING_RUNTIME_REGISTRY["docker"] = DockerStreamingRuntime
    EXEC_RUNTIME_REGISTRY["docker"] = DockerExecRuntime

    # Local runtimes
    from slop_code.execution.local_exec import LocalExecRuntime
    from slop_code.execution.local_streaming import LocalStreamingRuntime

    STREAMING_RUNTIME_REGISTRY["local"] = LocalStreamingRuntime
    EXEC_RUNTIME_REGISTRY["local"] = LocalExecRuntime

    _runtimes_registered = True


def spawn_streaming_runtime(
    environment: EnvironmentSpec, **kwargs
) -> "StreamingRuntime":
    """Spawn a streaming runtime for the given environment.

    Args:
        environment: Environment specification
        **kwargs: Additional arguments passed to spawn()

    Returns:
        StreamingRuntime instance appropriate for the environment type

    Raises:
        KeyError: If environment type is not registered
    """
    _ensure_runtimes_registered()
    runtime_cls = STREAMING_RUNTIME_REGISTRY[environment.type]
    return runtime_cls.spawn(environment=environment, **kwargs)


def spawn_exec_runtime(
    environment: EnvironmentSpec, command: str, **kwargs
) -> "ExecRuntime":
    """Spawn an exec runtime for the given environment.

    Args:
        environment: Environment specification
        command: Command to execute (immutable)
        **kwargs: Additional arguments passed to spawn()

    Returns:
        ExecRuntime instance appropriate for the environment type

    Raises:
        KeyError: If environment type is not registered
    """
    _ensure_runtimes_registered()
    runtime_cls = EXEC_RUNTIME_REGISTRY[environment.type]
    return runtime_cls.spawn(environment=environment, command=command, **kwargs)
