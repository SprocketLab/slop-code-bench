"""File loaders for checkpoint metric extraction.

This module provides low-level I/O for reading metric files from checkpoint directories.
"""

from __future__ import annotations

import json
from collections.abc import Generator
from pathlib import Path

from slop_code.common import DIFF_FILENAME
from slop_code.common import FILES_QUALITY_SAVENAME
from slop_code.common import QUALITY_DIR
from slop_code.common import QUALITY_METRIC_SAVENAME
from slop_code.common import SYMBOLS_QUALITY_SAVENAME
from slop_code.logging import get_logger
from slop_code.metrics.utils import MetricsError

logger = get_logger(__name__)


def _load_json_file(file_path: Path, checkpoint_dir: Path, *, raise_on_error: bool = False) -> dict | None:
    """Load a JSON file and return as dict, or None if missing/invalid.

    Args:
        file_path: Path to the JSON file to load
        checkpoint_dir: Parent checkpoint directory (for logging context)
        raise_on_error: If True, raise MetricsError on parse errors; otherwise log warning and return None

    Returns:
        Parsed JSON dict, or None if file doesn't exist or parsing fails (when raise_on_error=False)
    """
    if not file_path.exists():
        if raise_on_error:
            return None
        logger.warning(
            "JSON file not found",
            checkpoint_dir=str(checkpoint_dir),
            file=str(file_path),
        )
        return None

    try:
        with file_path.open("r") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        if raise_on_error:
            logger.error(
                "Failed to parse JSON file",
                checkpoint_dir=str(checkpoint_dir),
                file=str(file_path),
                error=str(e),
            )
            raise MetricsError(
                f"Failed to parse file '{file_path}': {e}",
                context={"checkpoint_dir": str(checkpoint_dir)},
            ) from e

        logger.warning(
            "Failed to parse JSON file",
            checkpoint_dir=str(checkpoint_dir),
            file=str(file_path),
            error=str(e),
        )
        return None


def _load_jsonl_file(file_path: Path) -> Generator[dict, None, None]:
    """Yield JSON objects from a JSONL file, skipping empty lines."""
    if not file_path.exists():
        return
    with file_path.open("r") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def load_snapshot_metrics(
    checkpoint_dir: Path, quality_file_name: str = QUALITY_METRIC_SAVENAME
) -> dict | None:
    """Load overall_quality.json and return as dict, or None if missing."""
    quality_file = checkpoint_dir / QUALITY_DIR / quality_file_name
    return _load_json_file(quality_file, checkpoint_dir, raise_on_error=True)


def load_file_metrics(
    checkpoint_dir: Path,
    file_quality_name: str = FILES_QUALITY_SAVENAME,
) -> Generator[dict, None, None]:
    """Yield file metrics from files.jsonl."""
    file_quality_path = checkpoint_dir / QUALITY_DIR / file_quality_name
    return _load_jsonl_file(file_quality_path)


def load_symbol_metrics(
    checkpoint_dir: Path,
    symbol_file_name: str = SYMBOLS_QUALITY_SAVENAME,
) -> Generator[dict, None, None]:
    """Yield symbol metrics from symbols.jsonl."""
    symbol_path = checkpoint_dir / QUALITY_DIR / symbol_file_name
    return _load_jsonl_file(symbol_path)


def load_diff_metrics(checkpoint_dir: Path) -> dict | None:
    """Load diff.json and return as dict, or None if missing/invalid."""
    diff_file = checkpoint_dir / DIFF_FILENAME
    return _load_json_file(diff_file, checkpoint_dir, raise_on_error=False)
