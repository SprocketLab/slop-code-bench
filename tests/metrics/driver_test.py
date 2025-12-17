"""Tests for metrics driver (file measurement orchestration)."""

from __future__ import annotations

from pathlib import Path

import pytest

from slop_code.metrics.driver import _calculate_file_metrics
from slop_code.metrics.driver import measure_files
from slop_code.metrics.driver import measure_snapshot_quality
from slop_code.metrics.languages import EXT_TO_LANGUAGE
from slop_code.metrics.languages import LANGUAGE_REGISTRY
from slop_code.metrics.models import FileMetrics
from slop_code.metrics.models import LanguageSpec
from slop_code.metrics.models import LineCountMetrics
from slop_code.metrics.models import LintMetrics
from slop_code.metrics.models import SymbolMetrics


class TestCalculateFileMetrics:
    """Tests for _calculate_file_metrics function."""

    @pytest.fixture(autouse=True)
    def setup_test_language(self):
        """Register a test language spec."""
        LANGUAGE_REGISTRY.clear()
        EXT_TO_LANGUAGE.clear()

        def line_fn(path: Path) -> LineCountMetrics:
            return LineCountMetrics(
                total_lines=100,
                loc=80,
                comments=15,
                multi_comment=10,
                single_comment=5,
            )

        def lint_fn(path: Path) -> LintMetrics:
            return LintMetrics(errors=3, fixable=2, counts={"E501": 2, "E302": 1})

        def symbol_fn(path: Path) -> list[SymbolMetrics]:
            return [
                SymbolMetrics(
                    name="test_func",
                    type="function",
                    start=10,
                    start_col=0,
                    end=15,
                    end_col=0,
                    complexity=5,
                    branches=3,
                    statements=5,
                ),
            ]

        def mi_fn(path: Path) -> float:
            return 22.5

        spec = LanguageSpec(
            extensions={".test"},
            line=line_fn,
            lint=lint_fn,
            symbol=symbol_fn,
            mi=mi_fn,
        )

        LANGUAGE_REGISTRY["test"] = spec
        EXT_TO_LANGUAGE[".test"] = "test"

        yield

        LANGUAGE_REGISTRY.clear()
        EXT_TO_LANGUAGE.clear()

    def test_calculate_file_metrics_supported_extension(self, tmp_path):
        """Test calculating metrics for a file with supported extension."""
        test_file = tmp_path / "example.test"
        test_file.write_text("test content")

        metrics = _calculate_file_metrics(test_file, depth=2)

        assert metrics is not None
        assert isinstance(metrics, FileMetrics)
        assert metrics.lines.total_lines == 100
        assert metrics.lines.loc == 80
        assert metrics.lint.errors == 3
        assert metrics.lint.fixable == 2
        assert len(metrics.symbols) == 1
        assert metrics.symbols[0].name == "test_func"
        assert metrics.mi == 22.5
        assert metrics.depth == 2
        assert metrics.is_entry_language is False

    def test_calculate_file_metrics_unsupported_extension(self, tmp_path):
        """Test calculating metrics for unsupported file returns None."""
        test_file = tmp_path / "example.unknown"
        test_file.write_text("test content")

        metrics = _calculate_file_metrics(test_file, depth=1)

        assert metrics is None


class TestMeasureFiles:
    """Tests for measure_files generator."""

    @pytest.fixture(autouse=True)
    def setup_test_language(self):
        """Register a test language spec."""
        LANGUAGE_REGISTRY.clear()
        EXT_TO_LANGUAGE.clear()

        def line_fn(path: Path) -> LineCountMetrics:
            # Return different metrics based on file name for testing
            return LineCountMetrics(
                total_lines=10,
                loc=8,
                comments=2,
                multi_comment=1,
                single_comment=1,
            )

        def lint_fn(path: Path) -> LintMetrics:
            return LintMetrics(errors=0, fixable=0, counts={})

        def symbol_fn(path: Path) -> list[SymbolMetrics]:
            return []

        def mi_fn(path: Path) -> float:
            return 20.0

        spec = LanguageSpec(
            extensions={".py"},
            line=line_fn,
            lint=lint_fn,
            symbol=symbol_fn,
            mi=mi_fn,
        )

        LANGUAGE_REGISTRY["python"] = spec
        EXT_TO_LANGUAGE[".py"] = "python"

        yield

        LANGUAGE_REGISTRY.clear()
        EXT_TO_LANGUAGE.clear()

    def test_measure_files_finds_python_files(self, tmp_path):
        """Test that measure_files finds Python files in directory tree."""
        # Create test directory structure
        (tmp_path / "module1.py").write_text("# module 1")
        (tmp_path / "subdir").mkdir()
        (tmp_path / "subdir" / "module2.py").write_text("# module 2")
        (tmp_path / "other.txt").write_text("not python")

        results = list(measure_files(tmp_path, exclude_patterns=set(), entry_extensions={".py"}))

        # Should find 2 Python files
        assert len(results) == 2
        file_names = {path.name for path, _ in results}
        assert file_names == {"module1.py", "module2.py"}
        assert all(m.is_entry_language for _, m in results)

    def test_measure_files_respects_exclude_patterns(self, tmp_path):
        """Test that measure_files respects exclusion patterns.

        Note: Patterns match against file names, not paths or directories.
        """
        (tmp_path / "keep.py").write_text("# keep")
        (tmp_path / "test_skip.py").write_text("# skip")  # Matches test_*
        (tmp_path / "subdir").mkdir()
        (tmp_path / "subdir" / "also_keep.py").write_text("# also keep")

        results = list(measure_files(tmp_path, exclude_patterns={"test_*"}))

        # Should find keep.py and also_keep.py, but not test_skip.py
        assert len(results) == 2
        file_names = {path.name for path, _ in results}
        assert file_names == {"keep.py", "also_keep.py"}

    def test_measure_files_calculates_depth(self, tmp_path):
        """Test that measure_files calculates correct file depth."""
        (tmp_path / "root.py").write_text("# root")
        (tmp_path / "level1").mkdir()
        (tmp_path / "level1" / "file1.py").write_text("# level 1")
        (tmp_path / "level1" / "level2").mkdir()
        (tmp_path / "level1" / "level2" / "file2.py").write_text("# level 2")

        results = {path.name: metrics.depth for path, metrics in measure_files(tmp_path, exclude_patterns=set())}

        assert results["root.py"] == 1
        assert results["file1.py"] == 2
        assert results["file2.py"] == 3

    def test_measure_files_skips_directories(self, tmp_path):
        """Test that measure_files skips directory entries."""
        (tmp_path / "file.py").write_text("# file")
        (tmp_path / "subdir").mkdir()

        results = list(measure_files(tmp_path, exclude_patterns=set()))

        # Should only find the file, not the directory
        assert len(results) == 1
        assert results[0][0].name == "file.py"

    def test_measure_files_empty_directory(self, tmp_path):
        """Test measure_files on empty directory returns no results."""
        results = list(measure_files(tmp_path, exclude_patterns=set()))

        assert len(results) == 0


class TestMeasureSnapshotQuality:
    """Tests for measure_snapshot_quality function."""

    @pytest.fixture(autouse=True)
    def setup_test_language(self):
        """Register a test language spec with predictable metrics."""
        LANGUAGE_REGISTRY.clear()
        EXT_TO_LANGUAGE.clear()

        def line_fn(path: Path) -> LineCountMetrics:
            return LineCountMetrics(
                total_lines=50,
                loc=40,
                comments=8,
                multi_comment=5,
                single_comment=3,
            )

        def lint_fn(path: Path) -> LintMetrics:
            return LintMetrics(
                errors=2,
                fixable=1,
                counts={"E501": 1, "E302": 1},
            )

        def symbol_fn(path: Path) -> list[SymbolMetrics]:
            return [
                SymbolMetrics(
                    name="func",
                    type="function",
                    start=1,
                    start_col=0,
                    end=5,
                    end_col=0,
                    complexity=3,
                    branches=2,
                    statements=3,
                ),
            ]

        def mi_fn(path: Path) -> float:
            return 25.0

        spec = LanguageSpec(
            extensions={".py"},
            line=line_fn,
            lint=lint_fn,
            symbol=symbol_fn,
            mi=mi_fn,
        )

        LANGUAGE_REGISTRY["python"] = spec
        EXT_TO_LANGUAGE[".py"] = "python"

        yield

        LANGUAGE_REGISTRY.clear()
        EXT_TO_LANGUAGE.clear()

    def test_measure_snapshot_quality_aggregates_metrics(self, tmp_path):
        """Test that measure_snapshot_quality aggregates file metrics correctly."""
        # Create two Python files
        (tmp_path / "file1.py").write_text("# file 1")
        (tmp_path / "file2.py").write_text("# file 2")

        snapshot, file_metrics_list = measure_snapshot_quality("file1.py", tmp_path)

        # Should have 2 files in the list
        assert len(file_metrics_list) == 2
        file_paths = {fm.file_path for fm in file_metrics_list}
        assert file_paths == {"file1.py", "file2.py"}
        assert all(fm.is_entry_language for fm in file_metrics_list)

        # Aggregates should reflect both files measured
        assert snapshot.file_count == 2
        # source_file_count reflects traced files from entry (file1.py has no imports)
        assert snapshot.source_file_count == 1

        # Overall metrics should reflect ALL files found (both file1.py and file2.py)
        assert snapshot.lines.total_lines == 100  # 50 + 50
        assert snapshot.lines.loc == 80  # 40 + 40
        assert snapshot.lines.comments == 16  # 8 + 8
        assert snapshot.lines.multi_comment == 10  # 5 + 5
        assert snapshot.lines.single_comment == 6  # 3 + 3

        assert snapshot.lint.errors == 4  # 2 + 2
        assert snapshot.lint.fixable == 2  # 1 + 1
        assert snapshot.lint.counts["E501"] == 2  # 1 + 1
        assert snapshot.lint.counts["E302"] == 2  # 1 + 1

    def test_measure_snapshot_quality_excludes_patterns(self, tmp_path):
        """Test that default exclude patterns are applied.

        Note: Default patterns match filenames like '.pyc', not directory names.
        """
        (tmp_path / "keep.py").write_text("# keep")
        (tmp_path / "skip.pyc").write_text("# compiled")  # Matches .pyc pattern
        (tmp_path / "subdir").mkdir()
        (tmp_path / "subdir" / "also_keep.py").write_text("# also keep")

        snapshot, file_metrics_list = measure_snapshot_quality("keep.py", tmp_path)

        # Should include Python files but not .pyc files
        assert len(file_metrics_list) == 2
        file_paths = {fm.file_path for fm in file_metrics_list}
        assert file_paths == {"keep.py", "subdir/also_keep.py"}
        assert all(fm.is_entry_language for fm in file_metrics_list)

    def test_measure_snapshot_quality_nested_structure(self, tmp_path):
        """Test with nested directory structure."""
        (tmp_path / "root.py").write_text("# root")
        (tmp_path / "subdir").mkdir()
        (tmp_path / "subdir" / "nested.py").write_text("# nested")

        snapshot, file_metrics_list = measure_snapshot_quality("root.py", tmp_path)

        assert len(file_metrics_list) == 2
        file_paths = {fm.file_path for fm in file_metrics_list}
        assert file_paths == {"root.py", "subdir/nested.py"}

        # Verify depths are stored correctly
        file_by_path = {fm.file_path: fm for fm in file_metrics_list}
        assert file_by_path["root.py"].depth == 1
        assert file_by_path["subdir/nested.py"].depth == 2
        assert all(fm.is_entry_language for fm in file_metrics_list)

    def test_measure_snapshot_quality_empty_directory(self, tmp_path):
        """Test with empty directory returns zero metrics."""
        snapshot, file_metrics_list = measure_snapshot_quality("main.py", tmp_path)

        assert len(file_metrics_list) == 0
        assert snapshot.file_count == 0
        assert snapshot.lines.total_lines == 0
        assert snapshot.lines.loc == 0
        assert snapshot.lint.errors == 0
        assert snapshot.lint.fixable == 0
        assert snapshot.lint.counts == {}

    def test_measure_snapshot_quality_mixed_file_types(self, tmp_path):
        """Test with mixed file types (only Python is analyzed)."""
        (tmp_path / "code.py").write_text("# python")
        (tmp_path / "readme.md").write_text("# readme")
        (tmp_path / "data.json").write_text("{}")

        snapshot, file_metrics_list = measure_snapshot_quality("code.py", tmp_path)

        # Should only analyze Python file
        assert len(file_metrics_list) == 1
        assert file_metrics_list[0].file_path == "code.py"
        assert file_metrics_list[0].is_entry_language is True
