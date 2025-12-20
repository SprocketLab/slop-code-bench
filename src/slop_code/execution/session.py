"""Session management for execution environments.

This module provides high-level session management that coordinates workspaces,
runtimes, and execution lifecycle:

- **Session**: Main session class managing workspace and runtime lifecycle
- **SessionError**: Session-specific exception
- Context manager support for automatic setup and cleanup
- Runtime spawning and management
- Input file materialization and content retrieval
- Static asset placeholder resolution
- Checkpoint completion and snapshot management

Sessions provide a convenient interface for managing complete execution
environments with proper resource cleanup and state management.
"""

from pathlib import Path
from typing import Any

from slop_code.execution.assets import ResolvedStaticAsset
from slop_code.execution.file_ops import InputFile
from slop_code.execution.file_ops import materialize_input_files
from slop_code.execution.models import EnvironmentSpec
from slop_code.execution.placeholders import resolve_static_placeholders
from slop_code.execution.runtime import SubmissionRuntime
from slop_code.execution.runtime import spawn_runtime
from slop_code.execution.snapshot import Snapshot
from slop_code.execution.snapshot import SnapshotDiff
from slop_code.execution.workspace import Workspace
from slop_code.logging import get_logger

logger = get_logger(__name__)


class SessionError(Exception):
    """Exception raised by the Session class."""


class Session:
    """Manages an execution session with workspace and runtime lifecycle.

    A session provides a high-level interface for managing execution
    environments, including workspace setup, runtime spawning, and cleanup.
    """

    def __init__(
        self,
        spec: EnvironmentSpec,
        workspace: Workspace,
        static_assets: dict[str, ResolvedStaticAsset] | None = None,
        is_agent_infer: bool = False,
    ):
        """Initialize a new session.

        Args:
            spec: Environment specification for execution
            workspace: Workspace instance for file management
            static_assets: Optional static assets available to the session
            is_agent_infer: Whether this is an agent inference session
        """
        logger.debug(
            "Initializing session",
            spec_type=spec.type,
            is_agent_infer=is_agent_infer,
            static_assets=list((static_assets or {}).keys()),
            verbose=True,
        )
        self.workspace = workspace
        self.static_assets = static_assets
        self.spec = spec
        self.runtimes: list[SubmissionRuntime] = []
        self.is_agent_infer = is_agent_infer

    def spawn(
        self,
        ports: dict[int, int] | None = None,
        mounts: dict[str, dict[str, str] | str] | None = None,
        env_vars: dict[str, str] | None = None,
        setup_command: str | None = None,
        disable_setup: bool = False,
        command: str | None = None,
        **runtime_kwargs: Any,
    ) -> SubmissionRuntime:
        """Spawn a new runtime for this session.

        Args:
            ports: Port mappings
            mounts: Volume mounts
            env_vars: Environment variables for runtime
            setup_command: Additional setup command
            disable_setup: Whether to disable setup commands
            command: Command for single-shot execution (uses docker run)
            **runtime_kwargs: Additional runtime-specific arguments

        Returns:
            New runtime instance configured for this session
        """
        logger.debug(
            "Spawning new runtime",
            single_shot=command is not None,
            verbose=True,
        )

        runtime = spawn_runtime(
            environment=self.spec,
            working_dir=self.workspace.working_dir,
            static_assets=self.static_assets,
            ports=ports or {},
            mounts=mounts or {},
            env_vars=env_vars or {},
            setup_command=setup_command,
            is_evaluation=not self.is_agent_infer,
            disable_setup=disable_setup,
            command=command,
            **runtime_kwargs,
        )

        self.runtimes.append(runtime)
        return runtime

    def prepare(self) -> None:
        """Prepare the session for execution."""
        logger.debug("Preparing session", verbose=True)
        self.workspace.prepare()

    def cleanup(self) -> None:
        """Clean up all session resources."""
        logger.debug(
            "Cleaning up session",
            num_runtimes=len(self.runtimes),
            verbose=True,
        )
        for runtime in self.runtimes:
            runtime.cleanup()
        self.workspace.cleanup()

    def __enter__(self) -> "Session":
        """Context manager entry."""
        self.prepare()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        """Context manager exit."""
        self.cleanup()

    @property
    def working_dir(self) -> Path:
        """Get the working directory for this session."""
        return self.workspace.working_dir

    def reset(self) -> None:
        """Reset the workspace to its initial state."""
        logger.debug("Resetting session workspace", verbose=True)
        self.workspace.reset()

    def restore_from_snapshot_dir(self, snapshot_dir: Path) -> None:
        """Restore workspace state from a snapshot directory.

        This copies all files from the snapshot directory into the workspace,
        used when resuming from a previous checkpoint.

        Args:
            snapshot_dir: Path to directory containing snapshot files

        Raises:
            SessionError: If snapshot directory does not exist
        """
        import shutil

        if not snapshot_dir.exists():
            raise SessionError(
                f"Snapshot directory does not exist: {snapshot_dir}"
            )

        logger.info(
            "Restoring workspace from snapshot directory",
            snapshot_dir=str(snapshot_dir),
            working_dir=str(self.working_dir),
        )

        # Copy all files from snapshot to workspace
        for item in snapshot_dir.iterdir():
            dest = self.working_dir / item.name
            if item.is_dir():
                if dest.exists():
                    shutil.rmtree(dest)
                shutil.copytree(item, dest)
            else:
                shutil.copy2(item, dest)

        # Re-materialize static assets (they may have been in snapshot ignores)
        self.workspace._maybe_materialize_static_assets()

        logger.debug(
            "Snapshot restoration complete",
            snapshot_dir=str(snapshot_dir),
        )

    def materialize_input_files(self, files: list[InputFile]) -> None:
        """Materialize input files into the workspace.

        Args:
            files: List of input files to write to workspace
        """
        materialize_input_files(files, self.workspace.working_dir)

    def get_file_contents(self, files: list[str]) -> dict[str, str | bytes]:
        """Get contents of files from the workspace.

        Args:
            files: Relative paths or glob patterns to read.

        Returns:
            Dictionary mapping matched file paths to their contents.
        """
        return self.workspace.get_file_contents(files)

    def resolve_static_placeholders(
        self, data: dict[str, Any]
    ) -> dict[str, Any]:
        """Resolve static asset placeholders in data.

        Args:
            data: Data structure potentially containing placeholders

        Returns:
            Data with placeholders resolved to appropriate paths
        """
        return resolve_static_placeholders(
            data,
            self.static_assets or {},
            is_docker=self.spec.type == "docker",
        )

    def finish_checkpoint(self, output_dir: Path) -> SnapshotDiff:
        """Finish a checkpoint and save results.

        Args:
            output_dir: Directory to save checkpoint results

        Returns:
            SnapshotDiff showing changes made during the checkpoint

        Raises:
            SessionError: If not in agent infer mode
        """
        if not self.is_agent_infer:
            raise SessionError(
                "Cannot finish checkpoint in non-agent infer mode"
            )

        logger.debug(
            "Finishing checkpoint",
            output_dir=output_dir,
            verbose=True,
        )

        old_snapshot = self.workspace.update_snapshot()
        new_snapshot = self.workspace.initial_snapshot

        output_dir.mkdir(parents=True, exist_ok=True)
        new_snapshot.extract_to_path(output_dir)

        archive_filename = new_snapshot.archive.name
        archive_in_output = output_dir / archive_filename
        if archive_in_output.exists():
            logger.debug(
                "Removing snapshot archive from output directory",
                archive=str(archive_in_output),
                verbose=True,
            )
            archive_in_output.unlink()

        return SnapshotDiff.from_snapshots(old_snapshot, new_snapshot)

    @classmethod
    def from_environment_spec(
        cls,
        spec: EnvironmentSpec,
        base_dir: Path | None,
        static_assets: dict[str, ResolvedStaticAsset] | None = None,
        image_name: str | None = None,
        is_agent_infer: bool = False,
    ) -> "Session":
        """Create a session from an environment specification.

        Args:
            spec: Environment specification
            base_dir: Optional base directory to initialize from
            static_assets: Optional static assets
            image_name: Optional image name to use for the session
            is_agent_infer: Whether this is an agent inference session

        Returns:
            New Session instance
        """
        logger.debug(
            "Creating session from environment spec",
            spec=spec.type,
            image_name=image_name,
            base_dir=base_dir,
            static_assets=list((static_assets or {}).keys()),
            verbose=True,
        )

        def snapshot_fn(cwd: Path) -> Snapshot:
            return Snapshot.from_environment_spec(
                cwd=cwd,
                env_spec=spec,
                static_assets=static_assets,
            )

        snapshot = None
        if base_dir is not None:
            logger.debug(
                "Creating initial snapshot from base directory",
                base_dir=base_dir,
                verbose=True,
            )
            snapshot = snapshot_fn(base_dir)

        workspace = Workspace(
            initial_snapshot=snapshot,
            snapshot_fn=snapshot_fn,
            static_assets=static_assets,
            is_agent_infer=is_agent_infer,
        )
        return cls(
            spec=spec,
            workspace=workspace,
            static_assets=static_assets,
            is_agent_infer=is_agent_infer,
        )
