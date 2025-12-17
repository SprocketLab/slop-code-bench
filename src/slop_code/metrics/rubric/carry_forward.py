"""Carry forward unchanged rubric grades across checkpoints.

This module provides functionality to identify grades from a previous checkpoint
that should be carried forward to the current checkpoint because the underlying
code hasn't changed. It uses diff information to:

1. Parse unified diff hunks to understand which regions changed
2. Calculate new line offsets for unchanged regions
3. Identify grades that weren't re-flagged but should persist
4. Return carried-forward grades with adjusted line numbers

Example:
    >>> prev_grades = [{"criteria": "overdoc", "start": 50, "end": 51, ...}]
    >>> new_grades = []
    >>> diff_text = "@@ -78,6 +80,269 @@\\n+new lines..."
    >>> carried = carry_forward_grades(
    ...     prev_grades, new_grades, diff_text, "main.py", "checkpoint_1"
    ... )
    >>> # Grade at line 50 is before the hunk, so it's unchanged
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from slop_code.common import DIFF_FILENAME
from slop_code.common import RUBRIC_FILENAME
from slop_code.logging import get_logger

logger = get_logger(__name__)

HUNK_HEADER_PATTERN = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def load_diff_text(diff_path: Path) -> dict[str, str]:
    """Load diff.json and extract diff_text per file.

    Args:
        diff_path: Path to the diff.json file.

    Returns:
        Dict mapping file names to their diff text. Empty dict if file
        doesn't exist or has no file_diffs.
    """
    if not diff_path.exists():
        return {}

    diff_data = json.loads(diff_path.read_text())
    file_diffs: dict[str, str] = {}

    for file_name, file_diff in diff_data.get("file_diffs", {}).items():
        diff_text = file_diff.get("diff_text", "")
        if diff_text:
            file_diffs[file_name] = diff_text

    return file_diffs


LINE_MATCH_TOLERANCE = 2


@dataclass
class DiffHunk:
    """Represents a single hunk from a unified diff.

    Attributes:
        old_start: Starting line number in the old file.
        old_count: Number of lines from the old file in this hunk.
        new_start: Starting line number in the new file.
        new_count: Number of lines in the new file in this hunk.
    """

    old_start: int
    old_count: int
    new_start: int
    new_count: int

    @property
    def old_end(self) -> int:
        """End line (exclusive) in the old file."""
        return self.old_start + self.old_count

    @property
    def new_end(self) -> int:
        """End line (exclusive) in the new file."""
        return self.new_start + self.new_count

    @property
    def delta(self) -> int:
        """Net change in line count (positive = lines added)."""
        return self.new_count - self.old_count


def parse_diff_hunks(diff_text: str) -> list[DiffHunk]:
    """Parse unified diff text to extract hunk headers.

    Args:
        diff_text: Unified diff text (e.g., from difflib or git diff).

    Returns:
        List of DiffHunk objects representing each hunk in the diff.

    Example:
        >>> diff = "@@ -78,6 +80,269 @@\\n context\\n+added"
        >>> hunks = parse_diff_hunks(diff)
        >>> hunks[0].old_start
        78
        >>> hunks[0].new_count
        269
    """
    hunks: list[DiffHunk] = []

    for line in diff_text.splitlines():
        match = HUNK_HEADER_PATTERN.match(line)
        if match:
            old_start = int(match.group(1))
            old_count = int(match.group(2)) if match.group(2) else 1
            new_start = int(match.group(3))
            new_count = int(match.group(4)) if match.group(4) else 1

            hunks.append(
                DiffHunk(
                    old_start=old_start,
                    old_count=old_count,
                    new_start=new_start,
                    new_count=new_count,
                )
            )

    return hunks


def compute_line_offset(
    hunks: list[DiffHunk], old_line: int
) -> tuple[int, bool]:
    """Compute the new line number for a line from the old file.

    Args:
        hunks: List of diff hunks, assumed to be in order.
        old_line: Line number in the old file.

    Returns:
        Tuple of (new_line, is_in_changed_region):
        - new_line: The corresponding line number in the new file.
        - is_in_changed_region: True if the line falls within a modified hunk.
    """
    if not hunks:
        return old_line, False

    cumulative_delta = 0

    for hunk in hunks:
        if old_line < hunk.old_start:
            # Line is before this hunk - apply cumulative delta so far
            return old_line + cumulative_delta, False

        if old_line < hunk.old_end:
            # Line is inside this hunk's old range - it's in a changed region
            # Return approximate new position but mark as changed
            offset_within_hunk = old_line - hunk.old_start
            new_line = hunk.new_start + offset_within_hunk
            return new_line, True

        # Line is after this hunk - accumulate the delta
        cumulative_delta += hunk.delta

    # Line is after all hunks
    return old_line + cumulative_delta, False


def is_span_unchanged(
    hunks: list[DiffHunk],
    start: int,
    end: int | None,
) -> tuple[bool, int, int | None]:
    """Check if a line span is unchanged and compute new offsets.

    A span is considered unchanged if neither its start nor end falls within
    a modified hunk region, and no hunk falls entirely within the span.

    Args:
        hunks: List of diff hunks.
        start: Starting line number in the old file.
        end: Ending line number in the old file (None for single-line spans).

    Returns:
        Tuple of (is_unchanged, new_start, new_end):
        - is_unchanged: True if the span doesn't overlap any changed regions.
        - new_start: Adjusted start line in the new file.
        - new_end: Adjusted end line in the new file (None if input was None).
    """
    effective_end = end if end is not None else start

    new_start, start_changed = compute_line_offset(hunks, start)
    new_end_val, end_changed = compute_line_offset(hunks, effective_end)

    if start_changed or end_changed:
        return False, new_start, new_end_val if end is not None else None

    # Check if any hunk falls entirely within the span
    for hunk in hunks:
        if hunk.old_start >= start and hunk.old_end <= effective_end + 1:
            return False, new_start, new_end_val if end is not None else None

    return True, new_start, new_end_val if end is not None else None


def _grade_matches(
    grade: dict,
    new_grades: list[dict],
    new_start: int,
    tolerance: int = LINE_MATCH_TOLERANCE,
) -> bool:
    """Check if a grade was re-flagged in the new checkpoint.

    Args:
        grade: The grade from the previous checkpoint.
        new_grades: List of grades from the new checkpoint.
        new_start: The adjusted start line for the old grade.
        tolerance: Line number tolerance for matching.

    Returns:
        True if a matching grade exists in new_grades.
    """
    criteria = grade.get("criteria")
    file_name = grade.get("file_name")

    for new_grade in new_grades:
        if new_grade.get("criteria") != criteria:
            continue
        if new_grade.get("file_name") != file_name:
            continue

        new_grade_start = new_grade.get("start", 0)
        if abs(new_grade_start - new_start) <= tolerance:
            return True

    return False


def carry_forward_grades(
    prev_grades: list[dict],
    new_grades: list[dict],
    diff_text: str,
    file_name: str,
    prev_checkpoint_name: str,
) -> list[dict]:
    """Carry forward grades from previous checkpoint for unchanged regions.

    For each grade from the previous checkpoint:
    1. Check if the grade's span is in an unchanged region (based on diff)
    2. Calculate new line numbers with offset adjustments
    3. Check if the grade was already re-flagged in the new checkpoint
    4. If unchanged and not re-flagged, carry it forward

    Args:
        prev_grades: Grades from the previous checkpoint's rubric.jsonl.
        new_grades: Grades from the current checkpoint's rubric.jsonl.
        diff_text: Unified diff text for the file.
        file_name: Name of the file to process.
        prev_checkpoint_name: Name of the previous checkpoint (for carried_over
            field).

    Returns:
        List of carried-forward grades with adjusted line numbers and
        carried_over field set.
    """
    hunks = parse_diff_hunks(diff_text)
    carried: list[dict] = []

    # Filter to grades for this file
    file_prev_grades = [
        g for g in prev_grades if g.get("file_name") == file_name
    ]
    file_new_grades = [g for g in new_grades if g.get("file_name") == file_name]

    logger.debug(
        "Processing carry-forward for file",
        file_name=file_name,
        prev_grade_count=len(file_prev_grades),
        new_grade_count=len(file_new_grades),
        hunk_count=len(hunks),
    )

    for grade in file_prev_grades:
        start = grade.get("start")
        end = grade.get("end")

        if start is None:
            continue

        # Check if span is unchanged
        is_unchanged, new_start, new_end = is_span_unchanged(hunks, start, end)

        if not is_unchanged:
            logger.debug(
                "Grade in changed region, skipping",
                criteria=grade.get("criteria"),
                start=start,
                end=end,
                verbose=True,
            )
            continue

        # Check if already re-flagged
        if _grade_matches(grade, file_new_grades, new_start):
            logger.debug(
                "Grade already re-flagged, skipping",
                criteria=grade.get("criteria"),
                start=start,
                new_start=new_start,
                verbose=True,
            )
            continue

        # Carry forward with adjusted lines
        # Preserve original source checkpoint if already carried
        original_checkpoint = grade.get("carried_over", prev_checkpoint_name)

        carried_grade = {
            "criteria": grade.get("criteria"),
            "start": new_start,
            "confidence": grade.get("confidence"),
            "file_name": file_name,
            "carried_over": original_checkpoint,
        }

        if new_end is not None:
            carried_grade["end"] = new_end

        # Preserve any additional fields (like explanation, category)
        for key in ["explanation", "category"]:
            if key in grade:
                carried_grade[key] = grade[key]

        carried.append(carried_grade)
        logger.debug(
            "Carrying forward grade",
            criteria=grade.get("criteria"),
            old_start=start,
            new_start=new_start,
            verbose=True,
        )

    logger.info(
        "Carry-forward complete for file",
        file_name=file_name,
        carried_count=len(carried),
        prev_grade_count=len(file_prev_grades),
    )

    return carried


def carry_forward_all_files(
    prev_grades: list[dict],
    new_grades: list[dict],
    file_diffs: dict[str, str],
    prev_checkpoint_name: str,
) -> list[dict]:
    """Carry forward grades for all files with diffs.

    Args:
        prev_grades: All grades from previous checkpoint.
        new_grades: All grades from current checkpoint.
        file_diffs: Dict mapping file names to their diff text.
        prev_checkpoint_name: Name of the previous checkpoint.

    Returns:
        List of all carried-forward grades across all files.
    """
    all_carried: list[dict] = []

    # Get unique file names from previous grades
    prev_files = {g.get("file_name") for g in prev_grades if g.get("file_name")}

    for file_name in prev_files:
        diff_text = file_diffs.get(file_name, "")

        # If no diff for this file, it's unchanged - carry all grades
        # (with same line numbers since nothing changed)
        carried = carry_forward_grades(
            prev_grades=prev_grades,
            new_grades=new_grades,
            diff_text=diff_text,
            file_name=file_name,
            prev_checkpoint_name=prev_checkpoint_name,
        )
        all_carried.extend(carried)

    logger.info(
        "Carry-forward complete for all files",
        total_carried=len(all_carried),
        file_count=len(prev_files),
    )

    return all_carried


# =============================================================================
# Problem Processing
# =============================================================================


def _load_rubric(rubric_path: Path) -> list[dict]:
    """Load grades from a rubric.jsonl file."""
    if not rubric_path.exists():
        return []

    grades = []
    for line in rubric_path.read_text().splitlines():
        if line.strip():
            grades.append(json.loads(line))
    return grades


def _save_rubric(rubric_path: Path, grades: list[dict]) -> None:
    """Save grades to a rubric.jsonl file."""
    with rubric_path.open("w") as f:
        for g in grades:
            f.write(json.dumps(g) + "\n")


def process_problem_carry_forward(
    problem_dir: Path,
    discover_checkpoints: Callable[[Path], list[Path]],
) -> dict[str, dict[str, int]]:
    """Process a single problem, carrying forward grades for each checkpoint.

    Args:
        problem_dir: Path to the problem directory.
        discover_checkpoints: Function to discover checkpoint directories.

    Returns:
        Dictionary mapping checkpoint names to carry-forward stats.
    """
    checkpoints = discover_checkpoints(problem_dir)
    results: dict[str, dict[str, int]] = {}

    prev_rubric_path: Path | None = None
    prev_checkpoint_name: str | None = None

    for checkpoint_dir in checkpoints:
        checkpoint_name = checkpoint_dir.name
        rubric_path = checkpoint_dir / RUBRIC_FILENAME
        diff_path = checkpoint_dir / DIFF_FILENAME

        if not rubric_path.exists():
            logger.debug(
                "No rubric.jsonl found, skipping checkpoint",
                checkpoint=checkpoint_name,
                problem=problem_dir.name,
            )
            prev_rubric_path = rubric_path
            prev_checkpoint_name = checkpoint_name
            continue

        if prev_rubric_path is None or not prev_rubric_path.exists():
            # First checkpoint or previous had no rubric - nothing to carry
            prev_rubric_path = rubric_path
            prev_checkpoint_name = checkpoint_name
            results[checkpoint_name] = {
                "carried": 0,
                "total": len(_load_rubric(rubric_path)),
            }
            continue

        # Load previous and current rubrics
        prev_grades = _load_rubric(prev_rubric_path)
        current_grades = _load_rubric(rubric_path)

        # Filter out already-carried grades from current (avoid duplicates on re-run)
        current_non_carried = [
            g for g in current_grades if "carried_over" not in g
        ]
        original_total = len(current_non_carried)

        # Load diff
        file_diffs = load_diff_text(diff_path)

        # Carry forward grades
        carried = carry_forward_all_files(
            prev_grades=prev_grades,
            new_grades=current_non_carried,
            file_diffs=file_diffs,
            prev_checkpoint_name=prev_checkpoint_name,
        )

        if carried:
            # Merge carried grades with current (non-carried) grades
            merged = current_non_carried + carried
            _save_rubric(rubric_path, merged)

            logger.info(
                "Carried forward grades",
                checkpoint=checkpoint_name,
                problem=problem_dir.name,
                carried_count=len(carried),
                total_count=len(merged),
            )

        results[checkpoint_name] = {
            "original_total": original_total,
            "carried": len(carried),
            "total": len(current_non_carried) + len(carried),
        }

        # Update for next iteration
        prev_rubric_path = rubric_path
        prev_checkpoint_name = checkpoint_name

    return results
