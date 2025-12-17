import glob
from collections.abc import Generator
from pathlib import Path

from slop_code.evaluation.adapters import GroupType
from slop_code.evaluation.config import CheckpointConfig
from slop_code.evaluation.config import GroupConfig
from slop_code.evaluation.config import ProblemConfig
from slop_code.evaluation.loaders.loader_protocol import LoaderError
from slop_code.logging import get_logger

logger = get_logger(__name__)


def _expand_pattern(read_dir: Path, pattern: str | Path) -> set[Path]:
    """Expand a single pattern (glob or literal path) to a set of files.

    Args:
        read_dir: The directory to read files from.
        pattern: The pattern to expand (glob or literal path).

    Returns:
        Set of file paths matching the pattern.
    """
    pattern_str = str(pattern)
    files = set()

    if glob.has_magic(pattern_str):
        # Handle glob patterns
        for path in read_dir.glob(pattern_str):
            if path.is_file():
                files.add(path)
            elif path.is_dir():
                files.update(path.rglob("*"))
    else:
        # Handle literal paths
        path = read_dir / pattern_str
        if path.exists():
            if path.is_file():
                files.add(path)
            elif path.is_dir():
                files.update(path.rglob("*"))

    return {f for f in files if f.is_file()}


def _should_include_file(
    file_path: Path,
    excluded_files: set[Path],
    include_patterns: list[str | Path],
    exclude_patterns: list[str | Path],
    read_dir: Path,
) -> bool:
    """Determine if a file should be included based on exclusion rules.

    Args:
        file_path: The file path to check.
        excluded_files: Set of files that should be excluded.
        include_patterns: List of include patterns to check against.
        exclude_patterns: List of exclude patterns that were used.
        read_dir: The directory being read from.

    Returns:
        True if the file should be included, False otherwise.
    """
    if file_path not in excluded_files:
        return True

    # Check if file was excluded by a literal (non-glob) pattern
    # If so, it should stay excluded regardless of include patterns
    for pattern in exclude_patterns:
        pattern_str = str(pattern)
        if not glob.has_magic(pattern_str):
            # Literal pattern - check if this file matches it
            excluded_path = read_dir / pattern_str
            if file_path == excluded_path:
                return False

    # Special case: if file is excluded by a glob but specifically matches
    # an include glob at a lower level, include it
    for pattern in include_patterns:
        pattern_str = str(pattern)
        if glob.has_magic(pattern_str):
            try:
                if file_path.match(pattern_str):
                    return True
            except ValueError:
                # Invalid pattern, skip
                pass

    return False


def get_files_from_globs(
    read_dir: Path,
    globs: list[str | Path],
    exclude: set[str | Path] | None = None,
) -> list[Path]:
    """Get files from glob patterns with exclusion support.

    If a glob is a directory, all files within the directory will be included.
    If an exclude is a directory, all files within it will be excluded
    unless they specifically match an included glob at a lower level.

    Args:
        read_dir: The directory to read files from.
        globs: The glob patterns to include.
        exclude: Patterns to exclude. Can be paths or glob patterns.

    Returns:
        List of file paths that match include patterns but don't match exclude
        patterns, with priority given to specific include matches.
    """
    exclude = exclude or set()

    # Collect all files matching include patterns
    included_files = set()
    for pattern in globs:
        included_files.update(_expand_pattern(read_dir, pattern))

    # Collect all files matching exclude patterns
    excluded_files = set()
    for pattern in exclude:
        excluded_files.update(_expand_pattern(read_dir, pattern))

    # Apply exclusion logic with priority to specific include matches
    exclude_list = list(exclude)
    return [
        file_path.relative_to(read_dir)
        for file_path in included_files
        if _should_include_file(
            file_path, excluded_files, globs, exclude_list, read_dir
        )
    ]


def discover_dir_cases(
    group_config: GroupConfig, checkpoint_dir: Path
) -> Generator[Path, None, None]:
    """Discover directory cases, excluding configured groups.

    Args:
        group_config: Configuration containing group files to exclude.
        checkpoint_dir: Directory to search for case directories.

    Yields:
        Paths to directories containing cases but not in excluded groups.
    """
    # Extract top-level directory names from group files to exclude
    excluded_dirs = {
        Path(group_file).parts[0] for group_file in group_config.group_files
    }

    for dir_path in checkpoint_dir.iterdir():
        if not dir_path.is_dir() or dir_path.name in excluded_dirs:
            continue
        yield dir_path


def get_actual_checkpoint(
    group: GroupConfig, problem: ProblemConfig, checkpoint: CheckpointConfig
) -> str:
    if group.type == GroupType.REGRESSION and group.original_group is not None:
        if group.original_checkpoint is None or group.original_group is None:
            raise LoaderError(
                "Original checkpoint or group is not set for regression group"
            )
        logger.debug(
            "Getting regression group from original checkpoint",
            original_checkpoint=group.original_checkpoint,
            original_group=group.original_group,
            group=group.name,
            checkpoint=checkpoint.name,
            problem=problem.name,
        )
        return group.original_checkpoint
    logger.debug(
        "Getting group from checkpoint",
        group=group.name,
        checkpoint=checkpoint.name,
        problem=problem.name,
    )
    return checkpoint.name


def get_chkpt_path(
    group: GroupConfig, problem: ProblemConfig, checkpoint: CheckpointConfig
) -> Path:
    if group.type == GroupType.REGRESSION and group.original_group is not None:
        if group.original_checkpoint is None or group.original_group is None:
            raise LoaderError(
                "Original checkpoint or group is not set for regression group"
            )
        logger.debug(
            "Getting regression group from original checkpoint",
            original_checkpoint=group.original_checkpoint,
            original_group=group.original_group,
            group=group.name,
            checkpoint=checkpoint.name,
            problem=problem.name,
        )
        out = checkpoint.path.parent / group.original_checkpoint
    else:
        logger.debug(
            "Getting group from checkpoint",
            group=group.name,
            checkpoint=checkpoint.name,
            problem=problem.name,
        )
        out = checkpoint.path
    if not out.exists():
        raise LoaderError(f"Checkpoint directory {out} does not exist")
    return out


def get_group_path(
    group: GroupConfig, problem: ProblemConfig, checkpoint: CheckpointConfig
) -> Path:
    out = get_chkpt_path(group=group, problem=problem, checkpoint=checkpoint)
    if group.original_group:
        out = out / group.original_group
    else:
        out = out / group.name
    if not out.exists():
        raise LoaderError(f"Group directory {out} does not exist")
    return out
