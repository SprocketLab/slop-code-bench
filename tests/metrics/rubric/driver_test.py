"""Tests for metrics driver batching logic."""

from __future__ import annotations

from pathlib import Path

from slop_code.metrics.driver import batch_files_by_size as _batch_files_by_size
from slop_code.metrics.driver import count_file_lines as _count_file_lines


class TestCountFileLines:
    """Tests for _count_file_lines helper."""

    def test_counts_lines_correctly(self, tmp_path: Path) -> None:
        """Count lines in a regular file."""
        test_file = tmp_path / "test.py"
        test_file.write_text("line1\nline2\nline3\n")

        result = _count_file_lines(test_file)

        assert result == 3

    def test_returns_zero_for_nonexistent_file(self) -> None:
        """Return 0 for files that don't exist."""
        result = _count_file_lines(Path("/nonexistent/file.py"))

        assert result == 0

    def test_handles_empty_file(self, tmp_path: Path) -> None:
        """Handle empty files."""
        test_file = tmp_path / "empty.py"
        test_file.write_text("")

        result = _count_file_lines(test_file)

        assert result == 0


class TestBatchFilesBySize:
    """Tests for _batch_files_by_size function."""

    def test_empty_file_list(self) -> None:
        """Handle empty file list."""
        result = _batch_files_by_size([])

        assert result == []

    def test_single_small_file(self, tmp_path: Path) -> None:
        """Single small file creates one batch."""
        small_file = tmp_path / "small.py"
        small_file.write_text("line1\nline2\n")

        result = _batch_files_by_size(
            [small_file], max_batch_lines=1000, large_file_threshold=500
        )

        assert len(result) == 1
        assert result[0] == [small_file]

    def test_large_file_gets_own_batch(self, tmp_path: Path) -> None:
        """Large files get their own batch."""
        large_file = tmp_path / "large.py"
        large_file.write_text("\n".join(f"line{i}" for i in range(600)))

        small_file = tmp_path / "small.py"
        small_file.write_text("line1\nline2\n")

        result = _batch_files_by_size(
            [large_file, small_file],
            max_batch_lines=1000,
            large_file_threshold=500,
        )

        assert len(result) == 2
        assert result[0] == [large_file]  # Large file in own batch
        assert result[1] == [small_file]  # Small file in own batch

    def test_small_files_batched_together(self, tmp_path: Path) -> None:
        """Small files are batched together."""
        file1 = tmp_path / "file1.py"
        file1.write_text("\n".join(f"line{i}" for i in range(100)))

        file2 = tmp_path / "file2.py"
        file2.write_text("\n".join(f"line{i}" for i in range(100)))

        file3 = tmp_path / "file3.py"
        file3.write_text("\n".join(f"line{i}" for i in range(100)))

        result = _batch_files_by_size(
            [file1, file2, file3],
            max_batch_lines=1000,
            max_batch_files=5,
            large_file_threshold=500,
        )

        assert len(result) == 1
        assert set(result[0]) == {file1, file2, file3}

    def test_respects_max_batch_lines(self, tmp_path: Path) -> None:
        """Batches are split when max lines exceeded."""
        file1 = tmp_path / "file1.py"
        file1.write_text("\n".join(f"line{i}" for i in range(400)))

        file2 = tmp_path / "file2.py"
        file2.write_text("\n".join(f"line{i}" for i in range(400)))

        file3 = tmp_path / "file3.py"
        file3.write_text("\n".join(f"line{i}" for i in range(400)))

        result = _batch_files_by_size(
            [file1, file2, file3],
            max_batch_lines=500,  # file1+file2 would be 800, exceeds 500
            max_batch_files=10,
            large_file_threshold=500,
        )

        assert len(result) == 3  # Each file in own batch

    def test_respects_max_batch_files(self, tmp_path: Path) -> None:
        """Batches are split when max files exceeded."""
        files = []
        for i in range(6):
            f = tmp_path / f"file{i}.py"
            f.write_text("line1\nline2\n")
            files.append(f)

        result = _batch_files_by_size(
            files,
            max_batch_lines=10000,
            max_batch_files=2,  # Max 2 files per batch
            large_file_threshold=500,
        )

        assert len(result) == 3  # 6 files / 2 per batch = 3 batches
        assert all(len(batch) <= 2 for batch in result)
