"""Path serialization utilities for config files.

Provides functions to convert absolute paths to paths relative to the
project root for portable YAML/JSON configuration storage.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from slop_code.utils import ROOT as PROJECT_ROOT


def to_relative_path(
    path: Path | str | None, base: Path | None = None
) -> str | None:
    """Convert an absolute path to a path relative to project root.

    Args:
        path: The path to convert (can be Path or str)
        base: Optional base directory (defaults to PROJECT_ROOT)

    Returns:
        String representation of the relative path, or the original
        path string if it cannot be made relative (e.g., outside project).
        Returns None if path is None.
    """
    if path is None:
        return None
    if base is None:
        base = PROJECT_ROOT

    path = Path(path) if isinstance(path, str) else path

    # Already relative - return as-is
    if not path.is_absolute():
        return str(path)

    # Try to make relative to base
    try:
        return str(path.relative_to(base))
    except ValueError:
        # Path is outside base directory - return as string
        return str(path)


def serialize_path_dict(
    data: dict[str, Any],
    base: Path | None = None,
) -> dict[str, Any]:
    """Recursively convert Path values in a dict to relative path strings.

    Args:
        data: Dictionary potentially containing Path objects
        base: Base directory for relative path calculation

    Returns:
        New dictionary with Path values converted to relative strings
    """
    result: dict[str, Any] = {}
    for key, value in data.items():
        if isinstance(value, Path):
            result[key] = to_relative_path(value, base)
        elif isinstance(value, dict):
            result[key] = serialize_path_dict(value, base)
        elif isinstance(value, list):
            result[key] = [
                serialize_path_dict(item, base)
                if isinstance(item, dict)
                else item
                for item in value
            ]
        else:
            result[key] = value
    return result
