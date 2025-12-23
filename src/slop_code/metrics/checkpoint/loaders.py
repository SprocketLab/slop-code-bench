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


def load_snapshot_metrics(
    checkpoint_dir: Path, quality_file_name: str = QUALITY_METRIC_SAVENAME
) -> dict | None:
    """Load overall_quality.json and return as dict, or None if missing."""
    quality_file = checkpoint_dir / QUALITY_DIR / quality_file_name
    if not quality_file.exists():
        return None
    try:
        with quality_file.open("r") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        logger.error(
            "Failed to parse quality metrics JSON",
            checkpoint_dir=str(checkpoint_dir),
            quality_file=str(quality_file),
            error=str(e),
        )
        raise MetricsError(
            f"Failed to parse quality file '{quality_file}': {e}",
            context={"checkpoint_dir": str(checkpoint_dir)},
        ) from e


def load_file_metrics(
    checkpoint_dir: Path,
    file_quality_name: str = FILES_QUALITY_SAVENAME,
) -> Generator[dict, None, None]:
    """Yield file metrics from files.jsonl."""
    file_quality_path = checkpoint_dir / QUALITY_DIR / file_quality_name
    if not file_quality_path.exists():
        return
    with file_quality_path.open("r") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def load_symbol_metrics(
    checkpoint_dir: Path,
    symbol_file_name: str = SYMBOLS_QUALITY_SAVENAME,
) -> Generator[dict, None, None]:
    """Yield symbol metrics from symbols.jsonl."""
    symbol_path = checkpoint_dir / QUALITY_DIR / symbol_file_name
    if not symbol_path.exists():
        return
    with symbol_path.open("r") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def load_diff_metrics(checkpoint_dir: Path) -> dict | None:
    """Load diff.json and return as dict, or None if missing/invalid."""
    diff_file = checkpoint_dir / DIFF_FILENAME
    if not diff_file.exists():
        logger.debug(
            "diff.json not found, skipping diff metrics",
            checkpoint_dir=str(checkpoint_dir),
        )
        return None
    try:
        return json.loads(diff_file.read_text())
    except json.JSONDecodeError as e:
        logger.warning(
            "Failed to parse diff.json, skipping diff metrics",
            checkpoint_dir=str(checkpoint_dir),
            error=str(e),
        )
        return None
