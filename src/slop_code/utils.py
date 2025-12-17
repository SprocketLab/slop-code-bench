"""General-purpose utilities used across the project.

Functions here are side-effect free except where interacting with the git
repository (e.g., ``check_unstaged_files``). Keep imports lightweight so the
module stays safe to import in library contexts and CLIs alike.
"""

import re
import sys
from pathlib import Path
from typing import Any, TypeVar, cast

import git
import structlog
from rich.console import Console

logger = structlog.get_logger(__name__)

ROOT = Path(__file__).parents[2]
CONSOLE = Console(width=200)


T = TypeVar("T")


def human_readable_bytes(num_bytes: int) -> str:
    """Convert a byte count into a human-readable string.

    Args:
        num_bytes: Size in bytes.

    Returns:
        A string like ``"1.23 MB"`` with two decimal precision.
    """
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if num_bytes < 1024.0:
            return f"{num_bytes:.2f} {unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:.2f} PB"


# Use sys.getsizeof for a rough estimate, but for containers, sum recursively
def get_total_size(obj, seen=None):
    """Recursively estimate memory footprint of a Python object.

    Notes:
        - ``sys.getsizeof`` under-reports for container references; we walk
          common containers (dict/list/tuple/set) to accumulate sizes.
        - This is only an approximation and may differ across interpreters.

    Args:
        obj: Object to estimate size for.
        seen: Internal set of visited object ids to avoid double-counting.

    Returns:
        Estimated size in bytes as an ``int``.
    """
    size = sys.getsizeof(obj)
    if seen is None:
        seen = set()
    obj_id = id(obj)
    if obj_id in seen:
        return 0
    seen.add(obj_id)
    if isinstance(obj, dict):
        size += sum(
            get_total_size(v, seen) + get_total_size(k, seen) for k, v in obj.items()
        )
    elif hasattr(obj, "__dict__"):
        size += get_total_size(vars(obj), seen)
    elif isinstance(obj, (list, tuple, set, frozenset)):
        size += sum(get_total_size(i, seen) for i in obj)
    return size


def check_unstaged_files(debug: bool = False, force: bool = False) -> bool:
    """Check for unstaged changes under the repo root and gate execution.

    Uses the global ``ROOT`` path to open the repository. If unstaged changes
    are present and neither ``debug`` nor ``force`` is True, a RuntimeError is
    raised. This is useful for preventing accidental execution against dirty
    trees in automation.

    Args:
        debug: When True, allow continuing with unstaged files.
        force: When True, allow continuing with unstaged files.

    Returns:
        True if unstaged files exist but execution is explicitly permitted;
        False if no unstaged files are found.

    Raises:
        RuntimeError: When dirty and not allowed by flags.
        git.InvalidGitRepositoryError: If ``ROOT`` is not a git repository.
    """
    logger.debug("Checking for unstaged files")
    try:
        repo = git.Repo(ROOT)
    except git.InvalidGitRepositoryError as e:
        logger.error("Not in a git repository. Skipping unstaged files check.")
        raise e
    has_unstaged_files = repo.is_dirty()
    if not has_unstaged_files:
        logger.debug("No unstaged files found")
        return False
    logger.debug(
        f"Unstaged files found:\n{[item.a_path for item in repo.index.diff(None)]}"
    )
    if debug or force:
        return True

    raise RuntimeError(
        "There are unstaged files in the repository. "
        "Please commit or stash them before proceeding. "
        "To bypass this check, set debug=True or force=True. Note that this "
        "will add a warning to all logging methods."
    )


def get_next_experiment_dir(
    experiment_dir: Path,
    exp_id_prefix: str = "exp_",
) -> str:
    """Create a new experiment directory with an incremented numeric suffix.

    Args:
        experiment_dir: Parent directory where experiment subdirs are created.
        exp_id_prefix: Prefix for experiment directories, e.g. ``"exp_"``.

    Returns:
        Absolute path of the created experiment directory as a string.
    """
    # Check if the log directory already contains an experiment ID pattern (e.g., /exp_001/)
    pattern = re.compile(rf"{exp_id_prefix}(\d+)")
    next_exp_id = 1

    logger.info(
        f"Checking for existing experiment directories in {experiment_dir} with prefix {exp_id_prefix}"
    )

    # Check for existing experiment directories
    existing_dirs = list(experiment_dir.glob(f"{exp_id_prefix}*"))

    if existing_dirs:
        logger.debug(f"Existing experiment directories:\n{existing_dirs}")
        # Extract experiment IDs and find the maximum
        exp_ids = []
        for dir_path in existing_dirs:
            match = pattern.search(str(dir_path))
            if match:
                exp_ids.append(int(match.group(1)))

        if exp_ids:
            # Increment the highest experiment ID
            next_exp_id = max(exp_ids) + 1

    # Format the new log directory with the incremented experiment ID
    new_log_dir = experiment_dir / f"{exp_id_prefix}{next_exp_id:03d}"
    new_log_dir.mkdir(parents=True, exist_ok=True)

    return str(new_log_dir)


def get_current_repo_hash():
    """Return the current repository HEAD commit hash.

    Returns:
        The 40-character hex SHA of ``HEAD``.

    Raises:
        git.InvalidGitRepositoryError: If ``ROOT`` is not a git repository.
    """
    repo = git.Repo(ROOT)
    return repo.head.object.hexsha


def log_command_args(output_dir: Path | None) -> None:
    """Log sys.argv to cmd.txt in the output directory.

    This is useful for reproducibility and debugging, as it records exactly
    what command was executed with what arguments.

    Args:
        output_dir: Directory where cmd.txt should be written. If None, no
            logging is performed.
    """
    if output_dir:
        cmd_file = output_dir / "cmd.txt"
        cmd_file.parent.mkdir(parents=True, exist_ok=True)
        cmd_file.write_text(" ".join(sys.argv) + "\n")


def coerce(value: Any, target_type: type[T], *, allow_none: bool = False) -> T | None:
    """
    Coerce a value to a target type.

    Args:
        value: The value to coerce
        target_type: The type to coerce to

    Returns:
        The coerced value

    Raises:
        TypeError: If the value cannot be coerced to the target type
        ValueError: If the coercion fails (e.g., invalid string to int conversion)
    """
    # If value is already the correct type, return it
    if isinstance(value, target_type):
        return cast("T", value)
    if value is None:
        return None

    # Try to coerce using the target type's constructor
    try:
        return cast("T", target_type(value))
    except (TypeError, ValueError) as e:
        if allow_none:
            return None
        raise type(e)(
            f"Cannot coerce {value!r} (type {type(value).__name__}) "
            f"to {target_type.__name__}: {e}"
        ) from e
