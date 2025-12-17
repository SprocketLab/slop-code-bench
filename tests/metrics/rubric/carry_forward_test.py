"""Tests for grade carry-forward functionality."""

from __future__ import annotations

from slop_code.metrics.rubric.carry_forward import DiffHunk
from slop_code.metrics.rubric.carry_forward import carry_forward_all_files
from slop_code.metrics.rubric.carry_forward import carry_forward_grades
from slop_code.metrics.rubric.carry_forward import compute_line_offset
from slop_code.metrics.rubric.carry_forward import is_span_unchanged
from slop_code.metrics.rubric.carry_forward import parse_diff_hunks


class TestParseDiffHunks:
    """Tests for parse_diff_hunks function."""

    def test_single_hunk(self) -> None:
        """Parse a single hunk header."""
        diff = "@@ -78,6 +80,269 @@\n context line\n+added line"
        hunks = parse_diff_hunks(diff)

        assert len(hunks) == 1
        assert hunks[0].old_start == 78
        assert hunks[0].old_count == 6
        assert hunks[0].new_start == 80
        assert hunks[0].new_count == 269

    def test_multiple_hunks(self) -> None:
        """Parse multiple hunk headers in sequence."""
        diff = """@@ -25,8 +25,10 @@
 context
+added
@@ -78,6 +80,269 @@
 more context
+more added
@@ -525,6 +790,18 @@
 even more"""
        hunks = parse_diff_hunks(diff)

        assert len(hunks) == 3
        assert hunks[0].old_start == 25
        assert hunks[0].old_count == 8
        assert hunks[0].new_count == 10
        assert hunks[1].old_start == 78
        assert hunks[1].new_count == 269
        assert hunks[2].old_start == 525
        assert hunks[2].new_start == 790

    def test_count_omitted_when_one(self) -> None:
        """Count defaults to 1 when omitted in hunk header."""
        diff = "@@ -1 +1,5 @@\n+added lines"
        hunks = parse_diff_hunks(diff)

        assert len(hunks) == 1
        assert hunks[0].old_start == 1
        assert hunks[0].old_count == 1
        assert hunks[0].new_start == 1
        assert hunks[0].new_count == 5

    def test_empty_diff(self) -> None:
        """Empty diff returns empty list."""
        hunks = parse_diff_hunks("")
        assert hunks == []

    def test_no_hunks(self) -> None:
        """Diff text without hunk headers returns empty list."""
        diff = "--- old.py\n+++ new.py\nsome other content"
        hunks = parse_diff_hunks(diff)
        assert hunks == []


class TestComputeLineOffset:
    """Tests for compute_line_offset function."""

    def test_line_before_any_hunks(self) -> None:
        """Line before first hunk has no offset."""
        hunks = [DiffHunk(old_start=100, old_count=5, new_start=100, new_count=10)]
        new_line, is_changed = compute_line_offset(hunks, 50)

        assert new_line == 50
        assert is_changed is False

    def test_line_after_single_hunk(self) -> None:
        """Line after hunk gets cumulative offset."""
        # Hunk adds 5 lines (10 - 5 = +5 delta)
        hunks = [DiffHunk(old_start=100, old_count=5, new_start=100, new_count=10)]
        new_line, is_changed = compute_line_offset(hunks, 200)

        assert new_line == 205  # 200 + 5
        assert is_changed is False

    def test_line_after_multiple_hunks(self) -> None:
        """Line after multiple hunks gets accumulated offset."""
        hunks = [
            DiffHunk(old_start=10, old_count=5, new_start=10, new_count=15),  # +10
            DiffHunk(old_start=50, old_count=10, new_start=60, new_count=5),  # -5
        ]
        new_line, is_changed = compute_line_offset(hunks, 100)

        # Total delta: +10 - 5 = +5
        assert new_line == 105
        assert is_changed is False

    def test_line_inside_modified_region(self) -> None:
        """Line inside hunk is marked as changed."""
        hunks = [DiffHunk(old_start=100, old_count=10, new_start=100, new_count=20)]
        new_line, is_changed = compute_line_offset(hunks, 105)

        assert is_changed is True
        # Position within hunk: 105 - 100 = 5, so new = 100 + 5 = 105
        assert new_line == 105

    def test_line_at_hunk_boundary_start(self) -> None:
        """Line at exact start of hunk is inside changed region."""
        hunks = [DiffHunk(old_start=100, old_count=10, new_start=100, new_count=20)]
        new_line, is_changed = compute_line_offset(hunks, 100)

        assert is_changed is True
        assert new_line == 100

    def test_line_at_hunk_boundary_end(self) -> None:
        """Line just after hunk end is not changed."""
        hunks = [DiffHunk(old_start=100, old_count=10, new_start=100, new_count=20)]
        # old_end = 100 + 10 = 110, so line 110 is just after
        new_line, is_changed = compute_line_offset(hunks, 110)

        assert is_changed is False
        # Delta is +10, so 110 + 10 = 120
        assert new_line == 120

    def test_empty_hunks(self) -> None:
        """Empty hunk list returns original line."""
        new_line, is_changed = compute_line_offset([], 50)

        assert new_line == 50
        assert is_changed is False

    def test_between_hunks(self) -> None:
        """Line between two hunks gets offset from first hunk only."""
        hunks = [
            DiffHunk(old_start=10, old_count=5, new_start=10, new_count=15),  # +10
            DiffHunk(old_start=100, old_count=5, new_start=110, new_count=10),
        ]
        new_line, is_changed = compute_line_offset(hunks, 50)

        assert new_line == 60  # 50 + 10 from first hunk
        assert is_changed is False


class TestIsSpanUnchanged:
    """Tests for is_span_unchanged function."""

    def test_span_before_modified_region(self) -> None:
        """Span entirely before hunks is unchanged."""
        hunks = [DiffHunk(old_start=100, old_count=10, new_start=100, new_count=20)]
        is_unchanged, new_start, new_end = is_span_unchanged(hunks, 50, 55)

        assert is_unchanged is True
        assert new_start == 50
        assert new_end == 55

    def test_span_after_modified_region(self) -> None:
        """Span entirely after hunks is unchanged with offset."""
        hunks = [DiffHunk(old_start=100, old_count=10, new_start=100, new_count=20)]
        is_unchanged, new_start, new_end = is_span_unchanged(hunks, 200, 205)

        assert is_unchanged is True
        # Delta is +10
        assert new_start == 210
        assert new_end == 215

    def test_span_overlapping_modified_region_start(self) -> None:
        """Span with start in modified region is changed."""
        hunks = [DiffHunk(old_start=100, old_count=10, new_start=100, new_count=20)]
        is_unchanged, new_start, new_end = is_span_unchanged(hunks, 105, 115)

        assert is_unchanged is False

    def test_span_overlapping_modified_region_end(self) -> None:
        """Span with end in modified region is changed."""
        hunks = [DiffHunk(old_start=100, old_count=10, new_start=100, new_count=20)]
        is_unchanged, new_start, new_end = is_span_unchanged(hunks, 95, 105)

        assert is_unchanged is False

    def test_span_containing_modified_region(self) -> None:
        """Span containing a hunk is changed."""
        hunks = [DiffHunk(old_start=100, old_count=5, new_start=100, new_count=10)]
        is_unchanged, new_start, new_end = is_span_unchanged(hunks, 90, 120)

        assert is_unchanged is False

    def test_single_line_span(self) -> None:
        """Single line span (end=None) is handled correctly."""
        hunks = [DiffHunk(old_start=100, old_count=10, new_start=100, new_count=20)]
        is_unchanged, new_start, new_end = is_span_unchanged(hunks, 50, None)

        assert is_unchanged is True
        assert new_start == 50
        assert new_end is None

    def test_single_line_in_changed_region(self) -> None:
        """Single line in changed region is marked changed."""
        hunks = [DiffHunk(old_start=100, old_count=10, new_start=100, new_count=20)]
        is_unchanged, new_start, new_end = is_span_unchanged(hunks, 105, None)

        assert is_unchanged is False


class TestCarryForwardGrades:
    """Tests for carry_forward_grades function."""

    def test_grade_in_unchanged_region_not_reflagged(self) -> None:
        """Grade in unchanged region not re-flagged is carried forward."""
        prev_grades = [
            {
                "criteria": "overdoc",
                "start": 50,
                "end": 51,
                "confidence": 5,
                "file_name": "main.py",
            }
        ]
        new_grades: list[dict] = []
        diff_text = "@@ -100,5 +100,10 @@\n context"

        carried = carry_forward_grades(
            prev_grades, new_grades, diff_text, "main.py", "checkpoint_1"
        )

        assert len(carried) == 1
        assert carried[0]["criteria"] == "overdoc"
        assert carried[0]["start"] == 50
        assert carried[0]["end"] == 51
        assert carried[0]["carried_over"] == "checkpoint_1"
        assert carried[0]["confidence"] == 5

    def test_grade_in_unchanged_region_reflagged(self) -> None:
        """Grade in unchanged region already re-flagged is not duplicated."""
        prev_grades = [
            {
                "criteria": "overdoc",
                "start": 50,
                "end": 51,
                "confidence": 5,
                "file_name": "main.py",
            }
        ]
        new_grades = [
            {
                "criteria": "overdoc",
                "start": 50,
                "end": 52,
                "confidence": 4,
                "file_name": "main.py",
            }
        ]
        diff_text = "@@ -100,5 +100,10 @@\n context"

        carried = carry_forward_grades(
            prev_grades, new_grades, diff_text, "main.py", "checkpoint_1"
        )

        assert len(carried) == 0

    def test_grade_in_changed_region(self) -> None:
        """Grade in changed region is not carried forward."""
        prev_grades = [
            {
                "criteria": "overdoc",
                "start": 105,
                "end": 106,
                "confidence": 5,
                "file_name": "main.py",
            }
        ]
        new_grades: list[dict] = []
        diff_text = "@@ -100,10 +100,20 @@\n context"

        carried = carry_forward_grades(
            prev_grades, new_grades, diff_text, "main.py", "checkpoint_1"
        )

        assert len(carried) == 0

    def test_grade_with_adjusted_offset(self) -> None:
        """Grade after changed region gets offset adjustment."""
        prev_grades = [
            {
                "criteria": "overdoc",
                "start": 200,
                "end": 201,
                "confidence": 5,
                "file_name": "main.py",
            }
        ]
        new_grades: list[dict] = []
        # Delta is +10 (15 - 5)
        diff_text = "@@ -100,5 +100,15 @@\n context"

        carried = carry_forward_grades(
            prev_grades, new_grades, diff_text, "main.py", "checkpoint_1"
        )

        assert len(carried) == 1
        assert carried[0]["start"] == 210  # 200 + 10
        assert carried[0]["end"] == 211  # 201 + 10

    def test_grade_near_reflagged_with_tolerance(self) -> None:
        """Grade near re-flagged grade within tolerance is not duplicated."""
        prev_grades = [
            {
                "criteria": "overdoc",
                "start": 50,
                "end": 51,
                "confidence": 5,
                "file_name": "main.py",
            }
        ]
        # Re-flagged at 51 (within tolerance of 2)
        new_grades = [
            {
                "criteria": "overdoc",
                "start": 51,
                "end": 52,
                "confidence": 4,
                "file_name": "main.py",
            }
        ]
        diff_text = ""

        carried = carry_forward_grades(
            prev_grades, new_grades, diff_text, "main.py", "checkpoint_1"
        )

        assert len(carried) == 0

    def test_multiple_grades_mixed_results(self) -> None:
        """Multiple grades with different outcomes."""
        prev_grades = [
            # Unchanged, not re-flagged - should carry
            {"criteria": "a", "start": 10, "confidence": 5, "file_name": "main.py"},
            # In changed region (100-104) - should not carry
            {"criteria": "b", "start": 102, "confidence": 5, "file_name": "main.py"},
            # Unchanged, re-flagged - should not carry
            {"criteria": "c", "start": 200, "confidence": 5, "file_name": "main.py"},
        ]
        new_grades = [
            {"criteria": "c", "start": 210, "confidence": 4, "file_name": "main.py"},
        ]
        # Delta is +10, hunk covers old lines 100-104
        diff_text = "@@ -100,5 +100,15 @@\n context"

        carried = carry_forward_grades(
            prev_grades, new_grades, diff_text, "main.py", "checkpoint_1"
        )

        assert len(carried) == 1
        assert carried[0]["criteria"] == "a"
        assert carried[0]["start"] == 10

    def test_different_file_grades_ignored(self) -> None:
        """Grades for different files are not processed."""
        prev_grades = [
            {"criteria": "a", "start": 10, "confidence": 5, "file_name": "other.py"},
        ]
        new_grades: list[dict] = []
        diff_text = ""

        carried = carry_forward_grades(
            prev_grades, new_grades, diff_text, "main.py", "checkpoint_1"
        )

        assert len(carried) == 0

    def test_preserves_explanation_field(self) -> None:
        """Explanation field is preserved when carrying forward."""
        prev_grades = [
            {
                "criteria": "overdoc",
                "start": 50,
                "confidence": 5,
                "file_name": "main.py",
                "explanation": "This comment is redundant",
            }
        ]
        new_grades: list[dict] = []
        diff_text = ""

        carried = carry_forward_grades(
            prev_grades, new_grades, diff_text, "main.py", "checkpoint_1"
        )

        assert len(carried) == 1
        assert carried[0]["explanation"] == "This comment is redundant"

    def test_preserves_original_carried_over_source(self) -> None:
        """Already-carried grades preserve their original source checkpoint."""
        # Grade was originally from checkpoint_1, carried to checkpoint_2
        prev_grades = [
            {
                "criteria": "overdoc",
                "start": 50,
                "confidence": 5,
                "file_name": "main.py",
                "carried_over": "checkpoint_1",  # Already carried
            }
        ]
        new_grades: list[dict] = []
        diff_text = ""

        # Now carrying from checkpoint_2 to checkpoint_3
        carried = carry_forward_grades(
            prev_grades, new_grades, diff_text, "main.py", "checkpoint_2"
        )

        assert len(carried) == 1
        # Should preserve original source, not the immediate previous
        assert carried[0]["carried_over"] == "checkpoint_1"


class TestCarryForwardAllFiles:
    """Tests for carry_forward_all_files function."""

    def test_multiple_files_with_different_diffs(self) -> None:
        """Process multiple files with different diffs."""
        prev_grades = [
            {"criteria": "a", "start": 50, "confidence": 5, "file_name": "main.py"},
            {"criteria": "b", "start": 30, "confidence": 5, "file_name": "utils.py"},
        ]
        new_grades: list[dict] = []
        file_diffs = {
            "main.py": "@@ -100,5 +100,15 @@\n context",  # Delta +10
            "utils.py": "",  # No changes
        }

        carried = carry_forward_all_files(
            prev_grades, new_grades, file_diffs, "checkpoint_1"
        )

        assert len(carried) == 2

        main_carried = [g for g in carried if g["file_name"] == "main.py"]
        utils_carried = [g for g in carried if g["file_name"] == "utils.py"]

        assert len(main_carried) == 1
        assert main_carried[0]["start"] == 50  # Before hunk, no offset

        assert len(utils_carried) == 1
        assert utils_carried[0]["start"] == 30  # No changes, same line

    def test_file_not_in_diffs(self) -> None:
        """File without diff entry is treated as unchanged."""
        prev_grades = [
            {"criteria": "a", "start": 50, "confidence": 5, "file_name": "main.py"},
        ]
        new_grades: list[dict] = []
        file_diffs: dict[str, str] = {}  # No diff for main.py

        carried = carry_forward_all_files(
            prev_grades, new_grades, file_diffs, "checkpoint_1"
        )

        assert len(carried) == 1
        assert carried[0]["start"] == 50
        assert carried[0]["carried_over"] == "checkpoint_1"
