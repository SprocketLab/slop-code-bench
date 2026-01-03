"""Execution environment abstractions for evaluation adapters."""

from typing import Annotated

from pydantic import Field

from slop_code.execution.assets import ResolvedStaticAsset
from slop_code.execution.assets import StaticAssetConfig
from slop_code.execution.assets import resolve_static_assets
from slop_code.execution.docker_runtime import DockerConfig
from slop_code.execution.docker_runtime import DockerEnvironmentSpec
from slop_code.execution.docker_runtime import network_mode_for_address
from slop_code.execution.docker_runtime.exec import DockerExecRuntime
from slop_code.execution.docker_runtime.streaming import DockerStreamingRuntime
from slop_code.execution.file_ops import Compression
from slop_code.execution.file_ops import FileSignature
from slop_code.execution.file_ops import FileType
from slop_code.execution.file_ops import InputFile
from slop_code.execution.file_ops import InputFileReadError
from slop_code.execution.file_ops import InputFileWriteError
from slop_code.execution.file_ops import detect_file_signature
from slop_code.execution.local_exec import LocalExecRuntime
from slop_code.execution.local_streaming import LocalEnvironmentSpec
from slop_code.execution.local_streaming import LocalStreamingRuntime
from slop_code.execution.models import EnvironmentSpec
from slop_code.execution.models import ExecutionError
from slop_code.execution.placeholders import resolve_static_placeholders
from slop_code.execution.protocols import ExecRuntime
from slop_code.execution.protocols import StreamingRuntime
from slop_code.execution.runtime import LaunchSpec
from slop_code.execution.runtime import RuntimeEvent
from slop_code.execution.runtime import RuntimeResult
from slop_code.execution.runtime import SolutionRuntimeError
from slop_code.execution.runtime import spawn_exec_runtime
from slop_code.execution.runtime import spawn_streaming_runtime
from slop_code.execution.session import Session
from slop_code.execution.snapshot import FileChangeType
from slop_code.execution.snapshot import FileDiff
from slop_code.execution.snapshot import Snapshot
from slop_code.execution.snapshot import SnapshotDiff
from slop_code.execution.workspace import Workspace

EnvironmentSpecType = Annotated[
    LocalEnvironmentSpec | DockerEnvironmentSpec,
    Field(discriminator="type"),
]
__all__ = [
    # Session and workspace
    "Session",
    "Workspace",
    # Runtime protocols
    "StreamingRuntime",
    "ExecRuntime",
    # Runtime implementations
    "DockerStreamingRuntime",
    "DockerExecRuntime",
    "LocalStreamingRuntime",
    "LocalExecRuntime",
    # Runtime utilities
    "LaunchSpec",
    "RuntimeResult",
    "RuntimeEvent",
    "SolutionRuntimeError",
    "spawn_streaming_runtime",
    "spawn_exec_runtime",
    # Environment specs
    "EnvironmentSpec",
    "EnvironmentSpecType",
    "LocalEnvironmentSpec",
    "DockerEnvironmentSpec",
    # Execution models
    "ExecutionError",
    # Snapshot models
    "Snapshot",
    "SnapshotDiff",
    "FileDiff",
    "FileChangeType",
    # Static assets
    "StaticAssetConfig",
    "ResolvedStaticAsset",
    "resolve_static_assets",
    "resolve_static_placeholders",
    # Docker utilities
    "network_mode_for_address",
    # File operations
    "Compression",
    "FileType",
    "FileSignature",
    "InputFile",
    "InputFileReadError",
    "InputFileWriteError",
    "detect_file_signature",
]
