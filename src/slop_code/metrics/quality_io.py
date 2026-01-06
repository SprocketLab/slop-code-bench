"""I/O utilities for quality metrics storage.

This module provides the save function for quality metrics,
ensuring consistent flat file storage across all save locations.
"""

from __future__ import annotations

import json
from pathlib import Path

from slop_code.common import AST_GREP_QUALITY_SAVENAME
from slop_code.common import FILES_QUALITY_SAVENAME
from slop_code.common import QUALITY_DIR
from slop_code.common import QUALITY_METRIC_SAVENAME
from slop_code.common import SYMBOLS_QUALITY_SAVENAME
from slop_code.logging import get_logger
from slop_code.metrics.models import FileMetrics
from slop_code.metrics.models import SnapshotMetrics

logger = get_logger(__name__)


def save_quality_metrics(
    save_dir: Path,
    snapshot_metrics: SnapshotMetrics,
    file_metrics: list[FileMetrics],
) -> int:
    """Save quality metrics to flat files in quality_analysis directory.

    Creates a quality_analysis/ subdirectory containing:
    - overall_quality.json: Aggregate snapshot metrics
    - files.jsonl: Flat file metrics (one row per file)
    - symbols.jsonl: Symbol metrics with file_path (one row per symbol)
    - ast_grep.jsonl: AST-grep violations with file_path (one row per violation)

    Args:
        save_dir: Directory to save quality_analysis/ into.
        snapshot_metrics: Aggregate metrics for the snapshot.
        file_metrics: List of per-file metrics.

    Returns:
        Number of files saved.
    """
    quality_dir = save_dir / QUALITY_DIR
    quality_dir.mkdir(parents=True, exist_ok=True)

    files_saved = 0

    # Save aggregate metrics
    with (quality_dir / QUALITY_METRIC_SAVENAME).open("w") as f:
        json.dump(
            snapshot_metrics.model_dump(mode="json"),
            f,
            indent=2,
            sort_keys=True,
        )
    files_saved += 1

    # Save flat file metrics
    with (quality_dir / FILES_QUALITY_SAVENAME).open("w") as f:
        for fm in file_metrics:
            data = {
                "file_path": fm.file_path,
                "loc": fm.lines.loc,
                "total_lines": fm.lines.total_lines,
                "comments": fm.lines.comments,
                "multi_comment": fm.lines.multi_comment,
                "single_comment": fm.lines.single_comment,
                "lint_errors": fm.lint.errors,
                "lint_fixable": fm.lint.fixable,
                "mi": fm.mi,
                "depth": fm.depth,
                "is_entry_language": fm.is_entry_language,
                "import_count": fm.import_count,
                "global_count": fm.global_count,
                "symbol_count": len(fm.symbols),
                "ast_grep_violation_count": len(fm.ast_grep_violations),
                "ast_grep_rules_checked": fm.ast_grep_rules_checked,
                "clone_instances": (
                    fm.redundancy.total_clone_instances if fm.redundancy else 0
                ),
                "clone_lines": fm.redundancy.clone_lines
                if fm.redundancy
                else 0,
                "clone_ratio": (
                    fm.redundancy.clone_ratio if fm.redundancy else 0.0
                ),
                "single_use_count": (
                    fm.waste.single_use_count if fm.waste else 0
                ),
                "trivial_wrapper_count": (
                    fm.waste.trivial_wrapper_count if fm.waste else 0
                ),
                "single_method_class_count": (
                    fm.waste.single_method_class_count if fm.waste else 0
                ),
            }
            f.write(json.dumps(data) + "\n")
    files_saved += 1

    # Save symbol metrics with file_path
    with (quality_dir / SYMBOLS_QUALITY_SAVENAME).open("w") as f:
        for fm in file_metrics:
            for sym in fm.symbols:
                data = sym.model_dump(mode="json")
                data["file_path"] = fm.file_path
                f.write(json.dumps(data) + "\n")
    files_saved += 1

    # Save AST-grep violations with file_path
    with (quality_dir / AST_GREP_QUALITY_SAVENAME).open("w") as f:
        for fm in file_metrics:
            for v in fm.ast_grep_violations:
                data = v.model_dump(mode="json")
                data["file_path"] = fm.file_path
                f.write(json.dumps(data) + "\n")
    files_saved += 1

    logger.debug(
        "Saved quality metrics",
        save_dir=str(save_dir),
        quality_dir=str(quality_dir),
        files_saved=files_saved,
        file_count=len(file_metrics),
    )

    return files_saved
