"""Tests for discovery utility functions."""

from __future__ import annotations

from pathlib import Path

from slop_code.entrypoints.utils import discover_checkpoints
from slop_code.entrypoints.utils import discover_problems


class TestDiscoverProblems:
    """Tests for discover_problems function."""

    def test_empty_directory(self, tmp_path: Path) -> None:
        """Empty directory returns empty list."""
        result = discover_problems(tmp_path)
        assert result == []

    def test_no_checkpoint_subdirs(self, tmp_path: Path) -> None:
        """Directories without checkpoint_* subdirs are not problems."""
        (tmp_path / "problem1").mkdir()
        (tmp_path / "problem1" / "src").mkdir()

        result = discover_problems(tmp_path)
        assert result == []

    def test_discovers_problems_with_checkpoints(self, tmp_path: Path) -> None:
        """Directories with checkpoint_* subdirs are discovered."""
        problem1 = tmp_path / "problem1"
        problem1.mkdir()
        (problem1 / "checkpoint_1").mkdir()

        problem2 = tmp_path / "problem2"
        problem2.mkdir()
        (problem2 / "checkpoint_1").mkdir()
        (problem2 / "checkpoint_2").mkdir()

        result = discover_problems(tmp_path)
        assert len(result) == 2
        assert problem1 in result
        assert problem2 in result

    def test_returns_sorted_by_name(self, tmp_path: Path) -> None:
        """Results are sorted alphabetically by name."""
        for name in ["zebra", "apple", "middle"]:
            problem = tmp_path / name
            problem.mkdir()
            (problem / "checkpoint_1").mkdir()

        result = discover_problems(tmp_path)
        names = [p.name for p in result]
        assert names == ["apple", "middle", "zebra"]

    def test_ignores_files(self, tmp_path: Path) -> None:
        """Files in run directory are ignored."""
        (tmp_path / "config.yaml").write_text("test")
        problem = tmp_path / "problem1"
        problem.mkdir()
        (problem / "checkpoint_1").mkdir()

        result = discover_problems(tmp_path)
        assert len(result) == 1
        assert result[0].name == "problem1"


class TestDiscoverCheckpoints:
    """Tests for discover_checkpoints function."""

    def test_empty_directory(self, tmp_path: Path) -> None:
        """Empty directory returns empty list."""
        result = discover_checkpoints(tmp_path)
        assert result == []

    def test_no_checkpoint_dirs(self, tmp_path: Path) -> None:
        """Directories not matching checkpoint_* are ignored."""
        (tmp_path / "src").mkdir()
        (tmp_path / "tests").mkdir()

        result = discover_checkpoints(tmp_path)
        assert result == []

    def test_discovers_checkpoints(self, tmp_path: Path) -> None:
        """checkpoint_* directories are discovered."""
        (tmp_path / "checkpoint_1").mkdir()
        (tmp_path / "checkpoint_2").mkdir()
        (tmp_path / "checkpoint_3").mkdir()

        result = discover_checkpoints(tmp_path)
        assert len(result) == 3

    def test_sorted_by_number(self, tmp_path: Path) -> None:
        """Checkpoints are sorted by numeric order, not lexicographic."""
        # Create in non-numeric order
        for num in [10, 2, 1, 20, 3]:
            (tmp_path / f"checkpoint_{num}").mkdir()

        result = discover_checkpoints(tmp_path)
        numbers = [int(p.name.split("_")[1]) for p in result]
        assert numbers == [1, 2, 3, 10, 20]

    def test_ignores_files(self, tmp_path: Path) -> None:
        """Files are ignored even if named like checkpoints."""
        (tmp_path / "checkpoint_1.txt").write_text("test")
        (tmp_path / "checkpoint_1").mkdir()

        result = discover_checkpoints(tmp_path)
        assert len(result) == 1
        assert result[0].name == "checkpoint_1"

    def test_ignores_non_checkpoint_dirs(self, tmp_path: Path) -> None:
        """Directories not matching pattern are ignored."""
        (tmp_path / "checkpoint_1").mkdir()
        (tmp_path / "checkpoint_abc").mkdir()  # Non-numeric
        (tmp_path / "other_1").mkdir()  # Wrong prefix

        result = discover_checkpoints(tmp_path)
        assert len(result) == 1
        assert result[0].name == "checkpoint_1"
