version: 1.1
last_updated: 2025-11-15
---

# Snapshots and Diffs

The snapshot system provides filesystem state capture and comparison for execution environments. This enables tracking changes made during task execution, debugging agent behavior, and analyzing submission modifications.

## Overview

Snapshots create compressed archives of workspace directories with configurable file filtering. The diff system then compares snapshots to produce detailed, line-by-line changes similar to Git diffs.

## Core Concepts

### Snapshot

A `Snapshot` is an immutable record of a directory's state at a point in time:

```python
from pathlib import Path
from slop_code.execution import Snapshot

# Create a snapshot
snapshot = Snapshot.from_directory(
    cwd=Path("/path/to/workspace"),
    env={"ENV_VAR": "value"},
    compression="gz",
    keep_globs={"*.py", "*.md"},  # Optional: only snapshot these
    ignore_globs={"*.pyc", "__pycache__/*"}  # Optional: exclude these
)

# Snapshot properties
print(snapshot.checksum)  # MD5 hash for quick comparison
print(snapshot.matched_paths)  # Set of included file paths
print(snapshot.timestamp)  # When snapshot was created
```

**Key features:**
- Compressed tar archives (`gz`, `bz2`, `xz`, or uncompressed)
- Glob-based file filtering (include/exclude patterns)
- MD5 checksums for integrity verification
- Environment variable capture
- Metadata about matched/ignored paths
- Text-focused diffing (non-decodable files are skipped rather than treated as binary)

### Snapshot Diff

A `SnapshotDiff` represents changes between two snapshots:

```python
# Compare snapshots
diff = snapshot1.diff(snapshot2)

# Summary information
print(diff)  # SnapshotDiff(abc123 -> def456, +2 -1 ~3 files)

# Examine specific file changes
for path, file_diff in diff.file_diffs.items():
    print(f"{path}: {file_diff.change_type}")
    if not file_diff.is_binary:
        print(f"  +{file_diff.lines_added} -{file_diff.lines_removed}")
```

### File Change Types

The `FileChangeType` enum indicates what happened to a decoded text file:

- **CREATED**: File exists in `to_snapshot` but not `from_snapshot`
- **DELETED**: File exists in `from_snapshot` but not `to_snapshot`
- **MODIFIED**: File exists in both but contents differ

`SnapshotDiff` currently emits entries only for files that can be decoded as text.
Heuristics consider null bytes and the ratio of printable characters; if decoding
fails, the file is skipped. Non-text files therefore remain excluded from
`file_diffs` to avoid noisy blob diffs.

```python
file_diff = diff.file_diffs[Path("script.py")]
print(f"Lines: +{file_diff.lines_added} -{file_diff.lines_removed}")
print(file_diff.diff_text)  # Full unified diff output
```

## Usage Examples

### Basic Snapshot Workflow

```python
from pathlib import Path
from slop_code.execution import Snapshot

workspace = Path("/workspace")

# Take initial snapshot
snapshot_before = Snapshot.from_directory(
    cwd=workspace,
    env={},
    compression="gz",
)

# ... code execution happens ...

# Take final snapshot
snapshot_after = Snapshot.from_directory(
    cwd=workspace,
    env={},
    compression="gz",
)

# Compare
diff = snapshot_before.diff(snapshot_after)

# Analyze changes
created = [p for p, d in diff.file_diffs.items() 
           if d.change_type == FileChangeType.CREATED]
modified = [p for p, d in diff.file_diffs.items() 
            if d.change_type == FileChangeType.MODIFIED]

print(f"Created {len(created)} files, modified {len(modified)} files")
```

### Filtering Files

Control which files are included in snapshots:

```python
# Only snapshot Python and Markdown files
snapshot = Snapshot.from_directory(
    cwd=workspace,
    env={},
    keep_globs={"*.py", "*.md", "**/*.py"},
)

# Exclude common files
snapshot = Snapshot.from_directory(
    cwd=workspace,
    env={},
    ignore_globs={
        "*.pyc",
        "__pycache__/*",
        ".venv/*",
        "*.log",
        ".git/*",
    },
)

# Combine both
snapshot = Snapshot.from_directory(
    cwd=workspace,
    env={},
    keep_globs={"src/**/*.py", "tests/**/*.py"},
    ignore_globs={"**/__pycache__/*", "*.pyc"},
)
```

### Detailed Diff Analysis

```python
from slop_code.execution import FileChangeType

diff = snapshot1.diff(snapshot2)

for path, file_diff in sorted(diff.file_diffs.items()):
    print(f"\n{path}")
    print("-" * 60)

    if file_diff.change_type == FileChangeType.CREATED:
        print(f"  New file with {file_diff.lines_added} lines")
        if file_diff.diff_text:
            print(file_diff.diff_text)

    elif file_diff.change_type == FileChangeType.DELETED:
        print(f"  Deleted file with {file_diff.lines_removed} lines")

    elif file_diff.change_type == FileChangeType.MODIFIED:
        print(f"  +{file_diff.lines_added} -{file_diff.lines_removed} lines")
        if file_diff.diff_text:
            print(file_diff.diff_text)
```

### Working with Environments

Sessions automatically manage snapshot creation through their workspaces:

```python
from pathlib import Path
from slop_code.execution import Session, LocalEnvironmentSpec

base_dir = Path("/problem/checkpoint")
session = Session.from_environment_spec(
    spec=LocalEnvironmentSpec(),
    base_dir=base_dir,
)

with session as active:
    # Initial snapshot is created when the workspace is prepared
    before = active.workspace.initial_snapshot

    runtime = active.spawn()
    runtime.execute("python main.py", env={}, stdin=None, timeout=30)

    # update_snapshot returns the previous snapshot and stores the new one
    old_snapshot = active.workspace.update_snapshot()
    after = active.workspace.initial_snapshot

diff = old_snapshot.diff(after)
# Context manager exit cleans up runtimes and temporary directories
```

When building fixtures outside of a full session, call
`Snapshot.from_environment_spec(cwd, env_spec, static_assets)` to honour the same
ignore rules, compression choice, and archive location that a session would
produce.

## API Reference

### Snapshot Class

```python
class Snapshot(BaseModel):
    """Immutable snapshot of a directory state."""
    
    path: Path                  # Directory that was snapshotted
    timestamp: datetime         # When snapshot was created
    env: dict[str, str]        # Environment variables
    archive: Path              # Path to tar archive
    checksum: str              # MD5 hash of archive
    matched_paths: set[Path]   # Files included in snapshot
    other_paths: set[Path]     # Files ignored by filters
    
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
        """Create snapshot from directory."""
    @classmethod
    def from_environment_spec(
        cls,
        cwd: Path,
        env_spec: EnvironmentSpec,
        static_assets: dict[str, ResolvedStaticAsset] | None = None,
        env: dict[str, str] | None = None,
    ) -> Snapshot:
        """Create snapshot using ignore/keep rules from an EnvironmentSpec."""
    
    def extract_contents(self) -> dict[Path, bytes]:
        """Materialise all archived files in memory."""
    
    def extract_text_contents(self) -> dict[Path, str]:
        """Return only text-decoded files."""
    
    def extract_to_path(self, target_dir: Path) -> None:
        """Write the archive contents to disk, preserving ownership when possible."""
    
    def diff(self, other: Snapshot) -> SnapshotDiff:
        """Compare with another snapshot."""
    
    def cleanup(self) -> None:
        """Delete the on-disk archive."""
```

### SnapshotDiff Class

```python
class SnapshotDiff(BaseModel):
    """Differences between two snapshots."""
    
    from_checksum: str
    to_checksum: str
    from_timestamp: datetime
    to_timestamp: datetime
    file_diffs: dict[Path, FileDiff]
    
    @classmethod
    def from_snapshots(
        cls,
        from_snapshot: Snapshot,
        to_snapshot: Snapshot,
    ) -> SnapshotDiff:
        """Create diff between snapshots."""
```

### FileDiff Class

```python
class FileDiff(BaseModel):
    """Changes to a single file."""

    path: Path
    change_type: FileChangeType  # CREATED, DELETED, or MODIFIED
    is_binary: bool = False

    # For text files:
    diff_text: str | None  # Unified diff output
    lines_added: int       # Number of lines added
    lines_removed: int     # Number of lines removed

    # For binary files:
    old_size: int | None
    new_size: int | None
```

## Performance Considerations

### Memory Usage

- **Archive creation**: Streams files to disk, minimal memory
- **Diff computation**: Loads both archives into memory
- **Large files**: Text diffs can be memory-intensive

For large workspaces:
```python
# Use compression to reduce archive size
snapshot = Snapshot.from_directory(
    cwd=workspace,
    env={},
    compression="xz",  # Best compression
)

# Filter aggressively
snapshot = Snapshot.from_directory(
    cwd=workspace,
    env={},
    keep_globs={"src/**/*.py"},  # Only source files
    ignore_globs={"**/*.pyc", "**/node_modules/*"},
)
```

### Archive Storage

By default, archives are stored in temporary directories and cleaned up automatically. For persistent storage:

```python
import tempfile
from pathlib import Path

# Create a persistent directory
archive_dir = Path("./snapshots")
archive_dir.mkdir(exist_ok=True)

snapshot = Snapshot.from_directory(
    cwd=workspace,
    env={},
    save_path=archive_dir,  # Archives saved here
)

# Archive name includes timestamp and unique ID
print(snapshot.archive)  # ./snapshots/20251010T140732.abc123.workspace.tar.gz
```

## Common Patterns

### Checkpoint Comparison

Compare execution state at different checkpoints:

```python
checkpoints = {}

# Checkpoint 1
checkpoints["setup"] = Snapshot.from_directory(cwd=workspace, env={})

# ... run setup code ...

# Checkpoint 2
checkpoints["after_setup"] = Snapshot.from_directory(cwd=workspace, env={})

# ... run main code ...

# Checkpoint 3
checkpoints["complete"] = Snapshot.from_directory(cwd=workspace, env={})

# Compare checkpoints
setup_changes = checkpoints["setup"].diff(checkpoints["after_setup"])
main_changes = checkpoints["after_setup"].diff(checkpoints["complete"])
```

### Change Validation

Verify expected changes occurred:

```python
diff = before.diff(after)

# Ensure specific file was modified
assert Path("config.json") in diff.file_diffs
assert diff.file_diffs[Path("config.json")].change_type == FileChangeType.MODIFIED

# Ensure no unexpected deletions
deleted = [p for p, d in diff.file_diffs.items() 
           if d.change_type == FileChangeType.DELETED]
assert len(deleted) == 0, f"Unexpected deletions: {deleted}"
```

### Debugging Agent Behavior

Track what an agent modified:

```python
from slop_code.execution import Session

session = Session.from_environment_spec(spec, base_dir=workspace)

with session as active:
    before_snapshot = active.workspace.initial_snapshot

    # Agent execution
    result = agent.run(task)

    previous_snapshot = active.workspace.update_snapshot()
    after_snapshot = active.workspace.initial_snapshot
    diff = previous_snapshot.diff(after_snapshot)

    # Log all changes
    logger.info("Agent made %s file changes", len(diff.file_diffs))
    for path, file_diff in diff.file_diffs.items():
        logger.info("  %s: %s", file_diff.change_type.value, path)
```

## See Also

- [Environment Specs](environment_specs.md) – Configuration shared by all runtimes
- [Session Lifecycle](manager.md) – Workspace orchestration and runtime spawning
- [Extending Execution](extending.md) – Custom execution backends

