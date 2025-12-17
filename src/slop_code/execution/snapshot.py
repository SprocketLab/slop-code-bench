"""Snapshot and diff functionality for execution environments.

This module provides filesystem state capture and comparison capabilities:

- **Snapshot**: Create compressed archives of directory state with file filtering
- **SnapshotDiff**: Compare snapshots to produce line-by-line file diffs (text files only)
- **File type detection**: Automatically handles text vs binary files
- **Glob filtering**: Include/exclude files using glob patterns

Example:
    >>> from pathlib import Path
    >>> from slop_code.execution.snapshot import Snapshot
    >>>
    >>> before = Snapshot.from_directory(cwd=Path("workspace"), env={})
    >>> # ... make changes ...
    >>> after = Snapshot.from_directory(cwd=Path("workspace"), env={})
    >>>
    >>> diff = before.diff(after)
    >>> for path, file_diff in diff.file_diffs.items():
    ...     print(f"{path}: {file_diff.change_type}")

See Also:
    - docs/execution/snapshots.md for detailed usage guide
"""

from __future__ import annotations

import contextlib
import difflib
import fnmatch
import hashlib
import os
import tarfile
from collections.abc import Generator
from collections.abc import Iterable
from datetime import datetime
from enum import Enum
from pathlib import Path

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from slop_code.execution.assets import ResolvedStaticAsset
from slop_code.execution.models import EnvironmentSpec
from slop_code.execution.models import ExecutionError
from slop_code.logging import get_logger

logger = get_logger(__name__)

DEFAULT_ARCHIVE_NAME = "slop_code_snapshot"

IS_WINDOWS = os.name == "nt"


def _normalize_compression(compression: str) -> tuple[str, str]:
    """Convert compression name to tarfile mode and file extension.

    Args:
        compression: Compression algorithm name ("gz", "bz2", "xz", "none", or "").

    Returns:
        Tuple of (tar_mode, file_extension) for use with tarfile module.

    Raises:
        ValueError: If compression algorithm is not supported.

    Example:
        >>> _normalize_compression("gz")
        ('w:gz', '.tar.gz')
        >>> _normalize_compression("xz")
        ('w:xz', '.tar.xz')
    """
    compression = (compression or "").lower()
    mode_map = {
        "gz": "w:gz",
        "bz2": "w:bz2",
        "xz": "w:xz",
        "": "w",
        "none": "w",
    }
    if compression not in mode_map:
        raise ValueError(
            f"Unsupported compression '{compression}'. "
            f"Choose one of {list(mode_map.keys())}."
        )
    tar_mode = mode_map[compression]
    ext_map = {
        "w:gz": ".tar.gz",
        "w:bz2": ".tar.bz2",
        "w:xz": ".tar.xz",
        "w": ".tar",
    }
    return tar_mode, ext_map[tar_mode]


def _tar_read_mode(compression: str) -> str:
    """Convert compression name to tarfile read mode.

    Args:
        compression: Compression algorithm name ("gz", "bz2", "xz", "none", or "").

    Returns:
        Tarfile read mode string (e.g., "r:gz", "r:xz").

    Raises:
        ValueError: If compression algorithm is not supported.
    """

    compression = (compression or "").lower()
    mode_map = {
        "gz": "r:gz",
        "bz2": "r:bz2",
        "xz": "r:xz",
        "": "r:",
        "none": "r:",
    }
    if compression not in mode_map:
        raise ValueError(
            f"Unsupported compression '{compression}'. "
            f"Choose one of {list(mode_map.keys())}."
        )
    return mode_map[compression]


def _resolve_archive_path(
    cwd: Path, save_dir: Path | None, tar_ext: str
) -> Path:
    """Determine the full path for saving a snapshot archive.

    Creates a unique filename using timestamp and UUID to prevent collisions.
    If save_dir is None, saves in cwd. Otherwise saves in save_dir with
    the workspace name.

    Args:
        cwd: The workspace directory being snapshotted.
        save_dir: Optional directory to save archive. If None, saves in cwd.
        tar_ext: File extension including compression (e.g., ".tar.gz").

    Returns:
        Resolved absolute path for the archive file.

    Raises:
        FileExistsError: If save_dir exists but is not a directory.

    Example:
        >>> cwd = Path("/workspace")
        >>> save_dir = Path("/snapshots")
        >>> path = _resolve_archive_path(cwd, save_dir, ".tar.gz")
        >>> # Returns: /snapshots/20251010T140732.abc123de.workspace.tar.gz
    """
    import uuid

    now = datetime.now().strftime("%Y%m%dT%H%M%S")
    unique_id = uuid.uuid4().hex[:8]
    if save_dir is None:
        return (
            cwd / f"{now}.{unique_id}.{DEFAULT_ARCHIVE_NAME}{tar_ext}"
        ).resolve()

    save_dir = Path(save_dir)
    if not save_dir.exists():
        save_dir.mkdir(parents=True, exist_ok=True)
    elif not save_dir.is_dir():
        raise FileExistsError(
            f"Save directory already exists and is not a directory: {save_dir}"
        )
    return (save_dir / f"{now}.{unique_id}.{cwd.name}{tar_ext}").resolve()


def _matches_any(patterns: Iterable[str], rel_posix: str) -> bool:
    """Return True when any glob pattern matches the relative path.

    Some user-provided glob patterns (for example ``"**/*"``) expect paths to
    contain at least one separator. When evaluating files located at the
    workspace root (e.g. ``"main.py"``), those patterns would otherwise fail to
    match because the relative path lacks a separator. To make the matching
    behaviour align with common shell-style expectations, we evaluate both the
    raw relative path and a ``"./"``-prefixed variant against each pattern.
    """

    candidates = (rel_posix, f"./{rel_posix}")
    for pattern in patterns:
        for candidate in candidates:
            if fnmatch.fnmatch(candidate, pattern):
                return True
    return False


def _walk_candidates(
    cwd: Path,
    ignore_globs: set[str],
    keep_globs: set[str],
) -> tuple[set[Path], set[Path]]:
    other_paths: set[Path] = set()
    matched_paths: set[Path] = set()

    for root, dirs, files in os.walk(cwd, topdown=True, followlinks=False):
        root_path = Path(root)

        # Prune directories early (using trailing slash to match dir globs)
        kept_dirs = []
        for d in list(dirs):
            rel_dir = (root_path / d).relative_to(cwd).as_posix() + "/"
            if _matches_any(ignore_globs, rel_dir):
                continue
            kept_dirs.append(d)
        dirs[:] = kept_dirs

        # Collect files
        for f in files:
            abs_path = root_path / f
            rel_path = abs_path.relative_to(cwd)
            rel_posix = rel_path.as_posix()

            if _matches_any(ignore_globs, rel_posix):
                other_paths.add(rel_path)
                continue

            if not keep_globs or _matches_any(keep_globs, rel_posix):
                matched_paths.add(rel_path)

    return matched_paths, other_paths


class Snapshot(BaseModel):
    """Snapshot that stores file contents in a compressed archive.

    Only the contents of the matched paths are included in the archive snapshot.

    Args:
        archive: The path to the compressed archive that contains the snapshot.
        checksum: The checksum of the snapshot.
        compression: The compression algorithm used for the archive.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: Path
    archive: Path
    checksum: str
    compression: str = "gz"
    timestamp: datetime = Field(default_factory=datetime.now)
    env: dict[str, str] = Field(default_factory=dict)
    matched_paths: set[Path] = Field(default_factory=set)
    other_paths: set[Path] = Field(default_factory=set)

    def __repr__(self) -> str:
        return (
            f"Snapshot(path={self.path}, timestamp={self.timestamp}, "
            f"env={list(self.env.keys())}, "  # type: ignore
            f"archive={self.archive.stat().st_size / (1024**2):.2f} MB, "
            f"checksum={self.checksum[:8]}, "
            f"matched_paths={len(self.matched_paths):,}, "
            f"other_paths={len(self.other_paths):,})"
        )

    @classmethod
    def from_directory(
        cls,
        cwd: Path,
        env: dict[str, str],
        compression: str = "gz",
        save_path: Path | None = None,
        keep_globs: set[str] | None = None,
        ignore_globs: set[str] | None = None,
    ) -> Snapshot:
        """Snapshot the directory by creating a compressed archive with the
        patterns specified by the execution environment.

        Args:
            cwd: The directory to snapshot.
            compression: The compression algorithm to use.
            save_path: Optional directory where the archive should be stored.

        Returns:
            Snapshot containing archive metadata.
        """
        if not cwd.exists() or not cwd.is_dir():
            raise ExecutionError(
                f"`cwd` must be an existing directory, got: {cwd!s}"
            )

        tar_mode, tar_ext = _normalize_compression(compression)
        archive_path = _resolve_archive_path(cwd, save_path, tar_ext)

        logger.debug(
            "Snapshotting directory",
            cwd=cwd,
            compression=compression,
            save_path=save_path,
            keep_globs=keep_globs,
            ignore_globs=ignore_globs,
        )
        ignore_globs = ignore_globs or {
            "*.pyc",
            "venv/*",
            ".venv/*",
            "**/.DS_Store",
        }

        matched_paths, other_paths = _walk_candidates(
            cwd, ignore_globs, keep_globs or set()
        )
        logger.debug(
            "Creating archive",
            num_matched_paths=len(matched_paths),
            num_other_paths=len(other_paths),
            archive_path=str(archive_path),
        )

        archive_path.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(str(archive_path), mode=tar_mode) as tf:  # type: ignore
            for rel_path in matched_paths:
                abs_path = cwd / rel_path
                tf.add(
                    abs_path,
                    arcname=rel_path.as_posix(),
                    recursive=False,
                )

        logger.debug(
            "Calculating checksum",
            archive_path=str(archive_path),
            size=f"{archive_path.stat().st_size / (1024**2):.4f} MB",
        )

        hash_md5 = hashlib.md5()
        with archive_path.open("rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        checksum = hash_md5.hexdigest()

        return cls(
            path=cwd,
            env=env,
            archive=archive_path,
            checksum=checksum,
            compression=compression,
            matched_paths=matched_paths,
            other_paths=other_paths,
        )

    def diff(self, other: Snapshot) -> SnapshotDiff:
        """Create a diff between this snapshot and another.

        Args:
            other: Snapshot to compare against

        Returns:
            SnapshotDiff showing the differences
        """
        logger.debug(
            "Creating diff between snapshots",
            from_checksum=self.checksum[:8],
            to_checksum=other.checksum[:8],
            verbose=True,
        )
        return SnapshotDiff.from_snapshots(self, other)

    def _extract_contents(self) -> Generator[tuple[Path, bytes], None, None]:
        """Extract all file contents from the snapshot archive.

        Yields:
            Tuples of (file_path, file_contents) for each file in the archive
        """
        read_mode = _tar_read_mode(self.compression)
        file_count = 0

        logger.debug(
            "Extracting contents from snapshot archive",
            archive=self.archive,
            compression=self.compression,
            verbose=True,
        )

        with tarfile.open(self.archive, read_mode) as tf:  # type: ignore[arg-type]
            for member in tf.getmembers():
                if member.isfile():
                    extracted = tf.extractfile(member)
                    if extracted is not None:
                        file_count += 1
                        yield Path(member.name), extracted.read()

        logger.debug(
            "Extracted file contents",
            file_count=file_count,
            verbose=True,
        )

    def extract_contents(self) -> dict[Path, bytes]:
        """Materialize all file contents from the snapshot archive.

        Returns:
            Dictionary mapping file paths to their contents as bytes
        """
        return dict(self._extract_contents())

    def extract_to_path(self, target_dir: Path) -> None:
        """Extract the snapshot contents to a directory.

        Args:
            target_dir: Directory to extract contents to
        """
        logger.debug(
            "Extracting snapshot to directory",
            target_dir=target_dir,
            verbose=True,
        )

        # get your target uid/gid (e.g., from env vars set by Docker)
        if not IS_WINDOWS:
            uid = int(os.environ.get("HUID", os.getuid()))
            gid = int(os.environ.get("HGID", os.getgid()))

        file_count = 0
        for path, data in self._extract_contents():
            out_path = target_dir / path
            out_path.parent.mkdir(parents=True, exist_ok=True)

            out_path.write_bytes(data)
            if not IS_WINDOWS:
                os.chown(out_path, uid, gid)
                os.chown(out_path.parent, uid, gid)
            file_count += 1

        if not IS_WINDOWS:
            os.chown(target_dir, uid, gid)

        logger.debug(
            "Extracted snapshot to directory",
            target_dir=target_dir,
            file_count=file_count,
            verbose=True,
        )

    def extract_text_contents(self) -> dict[Path, str]:
        """Extract text file contents from the snapshot archive.

        Returns:
            Dictionary mapping file paths to their text contents
        """
        text_contents: dict[Path, str] = {}

        for path, data in self._extract_contents():
            if not _is_binary(data):
                text = _decode_text(data)
                if text is not None:
                    text_contents[path] = text

        logger.debug(
            "Extracted text contents",
            total_files=len(text_contents),
            verbose=True,
        )
        return text_contents

    @classmethod
    def from_environment_spec(
        cls,
        cwd: Path,
        env_spec: EnvironmentSpec,
        static_assets: dict[str, ResolvedStaticAsset] | None = None,
        env: dict[str, str] | None = None,
    ) -> Snapshot:
        """Create a snapshot from an environment specification.

        Args:
            cwd: Directory to snapshot
            env_spec: Environment specification
            static_assets: Optional static assets
            env: Additional environment variables

        Returns:
            Snapshot created according to the environment specification
        """
        logger.debug(
            "Creating snapshot from environment spec",
            cwd=cwd,
            compression=env_spec.snapshot.compression,
            has_static_assets=bool(static_assets),
            verbose=True,
        )
        return cls.from_directory(
            cwd=cwd,
            env=env_spec.get_full_env(env or {}),
            compression=env_spec.snapshot.compression,
            save_path=env_spec.get_archive_save_dir(),
            ignore_globs=env_spec.get_ignore_globs(static_assets),
            keep_globs=env_spec.snapshot.keep_globs,
        )

    def cleanup(self) -> None:
        """Clean up the snapshot archive file."""
        logger.debug(
            "Cleaning up snapshot",
            verbose=True,
            snapshot=self.checksum[:8],
            archive=self.archive,
        )
        self.archive.unlink()


class FileChangeType(str, Enum):
    """Enum representing the type of change to a file."""

    CREATED = "created"
    DELETED = "deleted"
    MODIFIED = "modified"


class FileDiff(BaseModel):
    """Represents changes to a single file between two snapshots."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: Path
    change_type: FileChangeType
    is_binary: bool = False

    # For text files
    diff_text: str | None = None
    lines_added: int = 0
    lines_removed: int = 0

    # For binary files
    old_size: int | None = None
    new_size: int | None = None

    def __repr__(self) -> str:
        if self.change_type == FileChangeType.CREATED:
            size_info = (
                f", size={self.new_size}"
                if self.is_binary
                else f", +{self.lines_added} lines"
            )
            return f"FileDiff({self.path}, CREATED{size_info})"
        if self.change_type == FileChangeType.DELETED:
            size_info = (
                f", size={self.old_size}"
                if self.is_binary
                else f", -{self.lines_removed} lines"
            )
            return f"FileDiff({self.path}, DELETED{size_info})"
        if self.is_binary:
            return f"FileDiff({self.path}, MODIFIED, binary: {self.old_size} -> {self.new_size})"
        return f"FileDiff({self.path}, MODIFIED, +{self.lines_added}/-{self.lines_removed})"

    def get_stats(self) -> dict[str, int]:
        return {
            "added": self.lines_added,
            "removed": self.lines_removed,
        }


class SnapshotDiff(BaseModel):
    """Represents the differences between two snapshots."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    from_checksum: str
    to_checksum: str
    from_timestamp: datetime
    to_timestamp: datetime
    file_diffs: dict[Path, FileDiff]

    def _file_stats(self) -> tuple[int, int, int]:
        created = sum(
            1
            for d in self.file_diffs.values()
            if d.change_type == FileChangeType.CREATED
        )
        deleted = sum(
            1
            for d in self.file_diffs.values()
            if d.change_type == FileChangeType.DELETED
        )
        modified = sum(
            1
            for d in self.file_diffs.values()
            if d.change_type == FileChangeType.MODIFIED
        )
        return created, deleted, modified

    def __repr__(self) -> str:
        created, deleted, modified = self._file_stats()
        return (
            f"SnapshotDiff({self.from_checksum[:8]} -> {self.to_checksum[:8]}, "
            f"+{created} -{deleted} ~{modified} files)"
        )

    @classmethod
    def from_snapshots(
        cls,
        from_snapshot: Snapshot,
        to_snapshot: Snapshot,
    ) -> SnapshotDiff:
        """Create a diff between two snapshots.

        Only compares text files that can be decoded as strings.

        Args:
            from_snapshot: The original snapshot (the "before" state).
            to_snapshot: The new snapshot (the "after" state).

        Returns:
            A SnapshotDiff object containing the differences.
        """
        # Generate checksums for snapshots
        from_checksum = _generate_snapshot_checksum(from_snapshot)
        to_checksum = _generate_snapshot_checksum(to_snapshot)

        logger.debug(
            "Creating diff between snapshots",
            from_checksum=from_checksum[:8],
            to_checksum=to_checksum[:8],
        )

        # Extract text contents from both snapshots
        from_contents = from_snapshot.extract_text_contents()
        to_contents = to_snapshot.extract_text_contents()

        # Get all file paths from both snapshots
        all_paths = set(from_contents.keys()) | set(to_contents.keys())

        file_diffs: dict[Path, FileDiff] = {}

        for path in all_paths:
            from_text = from_contents.get(path)
            to_text = to_contents.get(path)

            if from_text is None and to_text is not None:
                # File was created
                file_diffs[path] = _create_text_file_diff(
                    path, None, to_text, FileChangeType.CREATED
                )
            elif from_text is not None and to_text is None:
                # File was deleted
                file_diffs[path] = _create_text_file_diff(
                    path, from_text, None, FileChangeType.DELETED
                )
            elif from_text != to_text:
                # File was modified
                file_diffs[path] = _create_text_file_diff(
                    path, from_text, to_text, FileChangeType.MODIFIED
                )

        logger.debug(
            "Diff created",
            num_changed_files=len(file_diffs),
        )

        return cls(
            from_checksum=from_checksum,
            to_checksum=to_checksum,
            from_timestamp=from_snapshot.timestamp,
            to_timestamp=to_snapshot.timestamp,
            file_diffs=file_diffs,
        )

    def get_stats(self) -> dict[str, int]:
        created, deleted, modified = self._file_stats()
        lines_added = lines_removed = 0
        for file in self.file_diffs.values():
            if file.is_binary:
                continue
            lines_added += file.lines_added
            lines_removed += file.lines_removed
        return {
            "created": created,
            "deleted": deleted,
            "modified": modified,
            "lines_added": lines_added,
            "lines_removed": lines_removed,
        }


def _generate_snapshot_checksum(snapshot: Snapshot) -> str:
    """Generate a checksum for a snapshot."""
    return snapshot.checksum


def _is_binary(data: bytes) -> bool:
    """Detect if file data is binary using heuristics.

    Uses multiple indicators to determine if data is binary:
    1. Presence of null bytes (strong indicator)
    2. Ratio of non-printable characters (>30% threshold)

    Tabs, line feeds, and carriage returns are considered printable.
    Only the first 8KB is sampled for performance.

    Args:
        data: Raw file contents to analyze.

    Returns:
        True if data appears to be binary, False if likely text.

    Example:
        >>> _is_binary(b"Hello, world!")
        False
        >>> _is_binary(b"\\x89PNG\\r\\n\\x1a\\n")
        True
        >>> _is_binary(b"Text with\\x00null byte")
        True
    """
    # Check for null bytes (strong indicator of binary)
    if b"\x00" in data:
        return True

    # Sample the first 8KB for performance
    sample = data[:8192]
    if not sample:
        return False

    # Count non-text bytes
    non_text = sum(
        1
        for byte in sample
        if byte < 0x20 and byte not in (0x09, 0x0A, 0x0D)  # tab, LF, CR
    )

    # If more than 30% non-text, consider binary
    return (non_text / len(sample)) > 0.3


def _decode_text(data: bytes) -> str | None:
    """Attempt to decode bytes as text using multiple encodings.

    Tries common encodings in order: UTF-8, Latin-1, CP1252.
    Returns None if all decoding attempts fail.

    Args:
        data: Raw bytes to decode.

    Returns:
        Decoded string if successful, None if all encodings fail.

    Note:
        Latin-1 can decode any byte sequence, so it serves as a fallback
        that will almost never return None. CP1252 handles Windows-specific
        characters.

    Example:
        >>> _decode_text(b"Hello")
        'Hello'
        >>> _decode_text("Café".encode('utf-8'))
        'Café'
    """
    encodings = ["utf-8", "latin-1", "cp1252"]
    for encoding in encodings:
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, AttributeError):
            continue
    return None


def _create_text_file_diff(
    path: Path,
    from_text: str | None,
    to_text: str | None,
    change_type: FileChangeType,
) -> FileDiff:
    """Create a FileDiff for a single text file.

    Args:
        path: The relative path to the file.
        from_text: The original file contents (None if created).
        to_text: The new file contents (None if deleted).
        change_type: The type of change.

    Returns:
        A FileDiff object representing the changes.
    """
    from_text = from_text or ""
    to_text = to_text or ""

    # Generate unified diff
    from_lines = from_text.splitlines(keepends=True)
    to_lines = to_text.splitlines(keepends=True)

    # Use difflib to generate a unified diff
    diff_lines = list(
        difflib.unified_diff(
            from_lines,
            to_lines,
            fromfile=str(path),
            tofile=str(path),
            lineterm="",
            n=3,  # context lines
        )
    )

    # Join diff lines into a single string
    diff_text = "\n".join(diff_lines) if diff_lines else ""

    # Count added and removed lines
    lines_added = 0
    lines_removed = 0

    for line in diff_lines:
        if line.startswith("+") and not line.startswith("+++"):
            lines_added += 1
        elif line.startswith("-") and not line.startswith("---"):
            lines_removed += 1

    return FileDiff(
        path=path,
        change_type=change_type,
        is_binary=False,
        diff_text=diff_text,
        lines_added=lines_added,
        lines_removed=lines_removed,
    )


def _extract_text_contents_from_directory(
    directory: Path,
    ignore_globs: set[str] | None = None,
) -> dict[Path, str]:
    """Extract text file contents from a directory.

    Args:
        directory: Path to the directory to scan.
        ignore_globs: Optional set of glob patterns to ignore.

    Returns:
        Dictionary mapping relative file paths to their text contents.
    """
    if not directory.exists() or not directory.is_dir():
        return {}

    ignore_globs = ignore_globs or {
        "*.pyc",
        "venv/*",
        ".venv/*",
        "**/.DS_Store",
    }
    text_contents: dict[Path, str] = {}

    for root, dirs, files in os.walk(
        directory, topdown=True, followlinks=False
    ):
        root_path = Path(root)

        # Prune directories early
        kept_dirs = []
        for d in list(dirs):
            rel_dir = (root_path / d).relative_to(directory).as_posix() + "/"
            if _matches_any(ignore_globs, rel_dir):
                continue
            kept_dirs.append(d)
        dirs[:] = kept_dirs

        # Process files
        for f in files:
            abs_path = root_path / f
            rel_path = abs_path.relative_to(directory)
            rel_posix = rel_path.as_posix()

            if _matches_any(ignore_globs, rel_posix):
                continue

            try:
                data = abs_path.read_bytes()
                if not _is_binary(data):
                    text = _decode_text(data)
                    if text is not None:
                        text_contents[rel_path] = text
            except OSError as e:
                logger.warning(
                    "Failed to read file",
                    path=str(abs_path),
                    error=str(e),
                )
                continue

    return text_contents


def _compute_directory_checksum(directory: Path) -> str:
    """Compute a checksum for a directory based on its file contents.

    Args:
        directory: Path to the directory.

    Returns:
        MD5 hex digest of the directory contents.
    """
    if not directory.exists():
        return "empty"

    hash_md5 = hashlib.md5(usedforsecurity=False)

    # Get all files sorted by path for deterministic ordering
    all_files: list[Path] = []
    for root, _, files in os.walk(directory, followlinks=False):
        for f in files:
            all_files.append(Path(root) / f)

    for file_path in sorted(all_files):
        try:
            rel_path = file_path.relative_to(directory)
            hash_md5.update(rel_path.as_posix().encode())
            hash_md5.update(file_path.read_bytes())
        except OSError:
            continue

    return hash_md5.hexdigest()


def create_diff_from_directories(
    from_dir: Path | None,
    to_dir: Path,
    from_checksum: str | None = None,
    to_checksum: str | None = None,
) -> SnapshotDiff:
    """Create a SnapshotDiff between two directories.

    This function is useful for regenerating diffs from extracted snapshot
    directories without needing the original tar archives.

    Args:
        from_dir: The "before" directory. If None, treated as empty (all files
            in to_dir will be marked as created).
        to_dir: The "after" directory.
        from_checksum: Optional checksum for from_dir. If not provided, computed
            from directory contents.
        to_checksum: Optional checksum for to_dir. If not provided, computed
            from directory contents.

    Returns:
        A SnapshotDiff representing the changes between directories.

    Example:
        >>> diff = create_diff_from_directories(
        ...     from_dir=Path("checkpoint_1/snapshot"),
        ...     to_dir=Path("checkpoint_2/snapshot"),
        ... )
        >>> print(diff)
    """
    # Extract text contents from both directories
    from_contents: dict[Path, str] = {}
    if from_dir is not None:
        from_contents = _extract_text_contents_from_directory(from_dir)

    to_contents = _extract_text_contents_from_directory(to_dir)

    # Compute checksums if not provided
    if from_checksum is None:
        from_checksum = (
            _compute_directory_checksum(from_dir) if from_dir else "empty"
        )
    if to_checksum is None:
        to_checksum = _compute_directory_checksum(to_dir)

    # Get all file paths from both directories
    all_paths = set(from_contents.keys()) | set(to_contents.keys())

    file_diffs: dict[Path, FileDiff] = {}

    for path in all_paths:
        from_text = from_contents.get(path)
        to_text = to_contents.get(path)

        if from_text is None and to_text is not None:
            # File was created
            file_diffs[path] = _create_text_file_diff(
                path, None, to_text, FileChangeType.CREATED
            )
        elif from_text is not None and to_text is None:
            # File was deleted
            file_diffs[path] = _create_text_file_diff(
                path, from_text, None, FileChangeType.DELETED
            )
        elif from_text != to_text:
            # File was modified
            file_diffs[path] = _create_text_file_diff(
                path, from_text, to_text, FileChangeType.MODIFIED
            )

    # Use directory mtime or current time for timestamps
    now = datetime.now()
    from_timestamp = now
    to_timestamp = now

    if from_dir is not None and from_dir.exists():
        with contextlib.suppress(OSError):
            from_timestamp = datetime.fromtimestamp(from_dir.stat().st_mtime)

    if to_dir.exists():
        with contextlib.suppress(OSError):
            to_timestamp = datetime.fromtimestamp(to_dir.stat().st_mtime)

    logger.debug(
        "Created diff from directories",
        from_dir=str(from_dir) if from_dir else "empty",
        to_dir=str(to_dir),
        num_changed_files=len(file_diffs),
    )

    return SnapshotDiff(
        from_checksum=from_checksum,
        to_checksum=to_checksum,
        from_timestamp=from_timestamp,
        to_timestamp=to_timestamp,
        file_diffs=file_diffs,
    )
