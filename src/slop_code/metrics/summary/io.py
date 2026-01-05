"""I/O for checkpoint results data and summary persistence.

This module provides functions for loading checkpoint data from JSONL files
and saving computed summaries to JSON.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from slop_code.common import SUMMARY_FILENAME
from slop_code.logging import get_logger
from slop_code.metrics.models import RunSummary

logger = get_logger(__name__)


def load_checkpoint_data(results_file: Path) -> list[dict[str, Any]]:
    """Load checkpoint data from checkpoint_results.jsonl.

    Args:
        results_file: Path to checkpoint_results.jsonl file.

    Returns:
        List of checkpoint dictionaries.

    Raises:
        FileNotFoundError: If checkpoint_results file doesn't exist.
    """
    if not results_file.exists():
        raise FileNotFoundError(
            f"Checkpoint results file not found: {results_file}"
        )

    checkpoints = []
    with results_file.open("r") as f:
        for line_num, line in enumerate(f, 1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                checkpoints.append(json.loads(stripped))
            except json.JSONDecodeError as e:
                logger.warning(
                    "Skipping malformed JSON line",
                    file=str(results_file),
                    line_num=line_num,
                    error=str(e),
                )

    return checkpoints


def save_summary_json(
    summary: RunSummary,
    run_dir: Path,
    filename: str = SUMMARY_FILENAME,
) -> Path:
    """Save full summary statistics to JSON file.

    Args:
        summary: Computed summary statistics.
        run_dir: Directory to save results to.
        filename: Output filename.

    Returns:
        Path to saved file.
    """
    output_path = run_dir / filename
    output_path.write_text(json.dumps(summary.model_dump(), indent=2))
    logger.info("Saved run summary", path=str(output_path))
    return output_path
