"""Workspace management for execution environments.

This module provides workspace management with snapshot support and static asset handling:

- **Workspace**: Manages temporary workspace directories with lifecycle
- **WorkspaceError**: Workspace-specific exception
- Context manager support for automatic setup and cleanup
- Snapshot creation and restoration capabilities
- Static asset materialization for agent inference
- File content reading from workspace
- Workspace reset to initial state

Workspaces provide isolated execution environments with proper state management
and cleanup, supporting both evaluation and agent inference scenarios.
"""

import shutil
import tempfile
from collections.abc import Callable
from collections.abc import Sequence
from pathlib import Path

from slop_code.execution.assets import ResolvedStaticAsset
from slop_code.execution.models import ExecutionError
from slop_code.execution.snapshot import Snapshot
from slop_code.logging import get_logger
from slop_code.common import WORKSPACE_TEST_DIR

logger = get_logger(__name__)


class WorkspaceError(ExecutionError):
    """Exception raised by the Workspace class."""


class Workspace:
    """Manages a temporary workspace directory with snapshot support.

    A workspace provides an isolated directory for execution with the ability
    to create snapshots, reset state, and manage static assets.
    """

    def __init__(
        self,
        initial_snapshot: Snapshot | None,
        snapshot_fn: Callable[[Path], Snapshot],
        static_assets: dict[str, ResolvedStaticAsset] | None = None,
        is_agent_infer: bool = False,
    ):
        """Initialize a new workspace.

        Args:
            initial_snapshot: Optional initial snapshot to restore from
            snapshot_fn: Function to create snapshots of the workspace
            static_assets: Optional static assets to materialize
            is_agent_infer: Whether this is for agent inference
        """
        logger.debug(
            "Initializing workspace",
            has_initial_snapshot=initial_snapshot is not None,
            static_assets=list((static_assets or {}).keys()),
            is_agent_infer=is_agent_infer,
            verbose=True,
        )
        self._temp_dir: tempfile.TemporaryDirectory[str] | None = None
        self._initial_snapshot = initial_snapshot
        self._static_assets = static_assets
        self._snapshot_fn = snapshot_fn
        self._is_agent_infer = is_agent_infer

    @property
    def initial_snapshot(self) -> Snapshot:
        """Get the initial snapshot for this workspace.

        Returns:
            Initial snapshot

        Raises:
            WorkspaceError: If no initial snapshot was provided
        """
        if self._initial_snapshot is None:
            raise WorkspaceError("Initial snapshot not provided")
        return self._initial_snapshot

    def __enter__(self) -> "Workspace":
        """Context manager entry."""
        self.prepare()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        """Context manager exit."""
        self.cleanup()

    @property
    def working_dir(self) -> Path:
        """Get the working directory path.

        Returns:
            Path to the temporary working directory

        Raises:
            WorkspaceError: If workspace has not been prepared
        """
        if self._temp_dir is None:
            raise WorkspaceError("Workspace not prepared")
        return Path(self._temp_dir.name)

    def get_file_contents(self, paths: Sequence[str]) -> dict[str, str | bytes]:
        """Reads files from the working directory, supporting glob patterns.

        Args:
            paths: Literal relative paths or glob patterns to collect.

        Returns:
            Mapping of matched relative paths to file contents (text or bytes).

        Raises:
            ExecutionError: If environment not prepared.
        """
        if not paths:
            return {}

        contents: dict[str, str | bytes] = {}
        matched_paths: dict[str, Path] = {}

        def _looks_like_glob(pattern: str) -> bool:
            return any(ch in pattern for ch in ("*", "?", "["))

        for raw_path in paths:
            if not raw_path:
                continue
            normalized = raw_path.lstrip("./")
            if not normalized:
                continue

            if _looks_like_glob(normalized):
                candidates = self.working_dir.glob(normalized)
            else:
                candidates = [self.working_dir / normalized]

            for candidate in candidates:
                if not candidate.exists():
                    continue

                if candidate.is_file():
                    rel_path = candidate.relative_to(
                        self.working_dir
                    ).as_posix()
                    matched_paths.setdefault(rel_path, candidate)
                elif candidate.is_dir():
                    # Recursively collect all files in directory
                    for file_path in candidate.rglob("*"):
                        if file_path.is_file() and not file_path.is_symlink():
                            rel_path = file_path.relative_to(
                                self.working_dir
                            ).as_posix()
                            matched_paths.setdefault(rel_path, file_path)

        for rel_path, file_path in matched_paths.items():
            try:
                contents[rel_path] = file_path.read_text()
            except UnicodeDecodeError:
                contents[rel_path] = file_path.read_bytes()

        logger.debug(
            "Read files",
            requested=len(paths),
            matched=len(matched_paths),
            returned=len(contents),
        )
        return contents

    def _maybe_materialize_static_assets(self) -> None:
        """Materialize static assets if in agent infer mode."""
        if not self._is_agent_infer:
            logger.debug(
                "Skipping materialization of static assets in evaluation",
                verbose=True,
            )
            return
        logger.debug("Materializing static assets", verbose=True)
        asset_count = 0
        for asset in (self._static_assets or {}).values():
            target_path = self.working_dir / asset.save_path
            if asset.absolute_path.is_dir():
                logger.debug(
                    "Copying directory asset",
                    source=asset.absolute_path,
                    target=target_path,
                    verbose=True,
                )
                shutil.copytree(asset.absolute_path, target_path)
            else:
                logger.debug(
                    "Copying file asset",
                    source=asset.absolute_path,
                    target=target_path,
                    verbose=True,
                )
                shutil.copy(asset.absolute_path, target_path)
            asset_count += 1
        logger.debug(
            "Materialized static assets",
            count=asset_count,
            verbose=True,
        )

    def materialize_static_assets_for_tests(self) -> dict[str, Path]:
        """Materialize static assets into tests/assets/ directory for test access.

        Copies static assets to tests/assets/{asset_name}/ so tests can access
        them via simple relative paths or environment variables.

        Returns:
            Dict mapping asset names to their materialized paths within workspace.
            Empty dict if no static assets configured.

        Raises:
            WorkspaceError: If workspace not prepared
        """
        if self._temp_dir is None:
            raise WorkspaceError("Workspace not prepared")

        if not self._static_assets:
            logger.debug("No static assets to materialize for tests")
            return {}

        assets_dir = self.working_dir / WORKSPACE_TEST_DIR / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)

        materialized: dict[str, Path] = {}
        for name, asset in self._static_assets.items():
            target_path = assets_dir / name

            if asset.absolute_path.is_dir():
                logger.debug(
                    "Copying directory asset for tests",
                    name=name,
                    source=str(asset.absolute_path),
                    target=str(target_path),
                    verbose=True,
                )
                shutil.copytree(asset.absolute_path, target_path)
            else:
                logger.debug(
                    "Copying file asset for tests",
                    name=name,
                    source=str(asset.absolute_path),
                    target=str(target_path),
                    verbose=True,
                )
                shutil.copy(asset.absolute_path, target_path)

            materialized[name] = target_path

        logger.info(
            "Materialized static assets for tests",
            count=len(materialized),
            assets=list(materialized.keys()),
        )
        return materialized

    def _prepare_initial_snapshot(self) -> None:
        """Prepare the workspace from the initial snapshot."""
        if self._initial_snapshot is not None:
            logger.debug(
                "Extracting initial snapshot to workspace",
                snapshot=self._initial_snapshot.checksum[:8],
                working_dir=self.working_dir,
                verbose=True,
            )
            self._initial_snapshot.extract_to_path(self.working_dir)
            return

        logger.debug(
            "Creating initial snapshot of empty directory.",
            working_dir=self.working_dir,
            verbose=True,
        )
        self._initial_snapshot = self._snapshot_fn(self.working_dir)

    def update_snapshot(self) -> Snapshot:
        """Update the workspace snapshot.

        Returns:
            The previous snapshot
        """
        logger.debug(
            "Updating snapshot",
            working_dir=self.working_dir,
            snapshot=self.initial_snapshot.checksum[:8],
            verbose=True,
        )
        old_snapshot = self.initial_snapshot
        self._initial_snapshot = self._snapshot_fn(self.working_dir)
        return old_snapshot

    def prepare(self) -> None:
        """Prepare the workspace for use."""
        if self._temp_dir is not None:
            raise WorkspaceError("Workspace already prepared")
        logger.debug("Preparing workspace", verbose=True)
        self._temp_dir = tempfile.TemporaryDirectory()
        self._prepare_initial_snapshot()
        self._maybe_materialize_static_assets()
        logger.debug(
            "Workspace prepared",
            working_dir=self.working_dir,
            verbose=True,
        )

    def cleanup(self) -> None:
        """Clean up workspace resources."""
        if self._temp_dir is None:
            return
        logger.debug(
            "Cleaning up workspace",
            working_dir=self.working_dir,
            verbose=True,
        )
        self._temp_dir.cleanup()
        self._temp_dir = None

    def reset(self) -> None:
        """Reset the workspace to its initial state."""
        if self._temp_dir is None:
            raise WorkspaceError("Workspace not prepared")
        logger.debug("Resetting workspace", verbose=True)
        self.cleanup()
        self.prepare()
