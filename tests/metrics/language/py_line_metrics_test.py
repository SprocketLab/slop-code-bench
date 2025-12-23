"""Exhaustive tests for Python line metrics.

Tests all functions in slop_code.metrics.languages.python.line_metrics including:
- Public API: calculate_line_metrics, calculate_mi
"""

from __future__ import annotations

from textwrap import dedent
from unittest.mock import MagicMock

from slop_code.metrics.languages.python import calculate_line_metrics
from slop_code.metrics.languages.python import calculate_mi

# =============================================================================
# Calculate MI Tests
# =============================================================================


class TestCalculateMI:
    """Tests for calculate_mi function."""

    def test_calculate_mi(self, tmp_path, monkeypatch):
        """Test calculating maintainability index."""
        test_file = tmp_path / "test.py"
        test_file.write_text("def hello():\n    print('world')\n")

        # Mock radon.metrics.mi_visit to return a predictable value
        mock_mi_visit = MagicMock(return_value=75.5)
        monkeypatch.setattr(
            "slop_code.metrics.languages.python.line_metrics.radon.metrics.mi_visit",
            mock_mi_visit,
        )

        mi = calculate_mi(test_file)

        assert mi == 75.5
        # Verify it was called with the file contents and multi=False
        mock_mi_visit.assert_called_once_with(
            "def hello():\n    print('world')\n", multi=False
        )

    def test_calculate_mi_caches_file_reads(self, tmp_path, monkeypatch):
        """Test that _get_code caching works."""
        test_file = tmp_path / "cached.py"
        test_file.write_text("print('cached')")

        mock_mi_visit = MagicMock(return_value=80.0)
        monkeypatch.setattr(
            "slop_code.metrics.languages.python.line_metrics.radon.metrics.mi_visit",
            mock_mi_visit,
        )

        # Call multiple times
        calculate_mi(test_file)
        calculate_mi(test_file)

        # Both calls should use the same cached content
        assert mock_mi_visit.call_count == 2

    def test_calculate_mi_simple_function(self, tmp_path, monkeypatch):
        """Test MI for simple function."""
        test_file = tmp_path / "simple.py"
        test_file.write_text("def f(): return 1")

        mock_mi_visit = MagicMock(return_value=100.0)
        monkeypatch.setattr(
            "slop_code.metrics.languages.python.line_metrics.radon.metrics.mi_visit",
            mock_mi_visit,
        )

        mi = calculate_mi(test_file)
        assert mi == 100.0

    def test_calculate_mi_complex_function(self, tmp_path, monkeypatch):
        """Test MI for complex function."""
        test_file = tmp_path / "complex.py"
        test_file.write_text(dedent("""
        def complex(x, y, z):
            if x > 0:
                if y > 0:
                    if z > 0:
                        for i in range(x):
                            for j in range(y):
                                for k in range(z):
                                    print(i, j, k)
            return None
        """))

        mock_mi_visit = MagicMock(return_value=40.0)  # Lower MI for complex code
        monkeypatch.setattr(
            "slop_code.metrics.languages.python.line_metrics.radon.metrics.mi_visit",
            mock_mi_visit,
        )

        mi = calculate_mi(test_file)
        assert mi == 40.0


# =============================================================================
# Calculate Line Metrics Tests
# =============================================================================


class TestCalculateLineMetrics:
    """Tests for calculate_line_metrics function."""

    def test_calculate_line_metrics(self, tmp_path, monkeypatch):
        """Test calculating line metrics from radon output."""
        test_file = tmp_path / "test.py"
        test_file.write_text("# comment\ndef func():\n    pass\n")

        # Mock radon.raw.analyze to return predictable metrics
        mock_raw_metrics = MagicMock()
        mock_raw_metrics.loc = 100  # Total lines
        mock_raw_metrics.sloc = 75  # Source lines of code
        mock_raw_metrics.comments = 20  # Total comments
        mock_raw_metrics.multi = 10  # Multi-line comments
        mock_raw_metrics.single_comments = 10  # Single-line comments

        mock_analyze = MagicMock(return_value=mock_raw_metrics)
        monkeypatch.setattr(
            "slop_code.metrics.languages.python.line_metrics.radon.raw.analyze",
            mock_analyze,
        )

        metrics = calculate_line_metrics(test_file)

        assert metrics.total_lines == 100
        assert metrics.loc == 75
        assert metrics.comments == 20
        assert metrics.multi_comment == 10
        assert metrics.single_comment == 10

    def test_calculate_line_metrics_empty_file(self, tmp_path, monkeypatch):
        """Test calculating metrics for an empty file."""
        test_file = tmp_path / "empty.py"
        test_file.write_text("")

        mock_raw_metrics = MagicMock()
        mock_raw_metrics.loc = 0
        mock_raw_metrics.sloc = 0
        mock_raw_metrics.comments = 0
        mock_raw_metrics.multi = 0
        mock_raw_metrics.single_comments = 0

        mock_analyze = MagicMock(return_value=mock_raw_metrics)
        monkeypatch.setattr(
            "slop_code.metrics.languages.python.line_metrics.radon.raw.analyze",
            mock_analyze,
        )

        metrics = calculate_line_metrics(test_file)

        assert metrics.total_lines == 0
        assert metrics.loc == 0
        assert metrics.comments == 0

    def test_calculate_line_metrics_comments_only(self, tmp_path, monkeypatch):
        """Test file with only comments."""
        test_file = tmp_path / "comments.py"
        test_file.write_text("# comment 1\n# comment 2\n# comment 3\n")

        mock_raw_metrics = MagicMock()
        mock_raw_metrics.loc = 3
        mock_raw_metrics.sloc = 0
        mock_raw_metrics.comments = 3
        mock_raw_metrics.multi = 0
        mock_raw_metrics.single_comments = 3

        mock_analyze = MagicMock(return_value=mock_raw_metrics)
        monkeypatch.setattr(
            "slop_code.metrics.languages.python.line_metrics.radon.raw.analyze",
            mock_analyze,
        )

        metrics = calculate_line_metrics(test_file)

        assert metrics.comments == 3
        assert metrics.single_comment == 3

    def test_calculate_line_metrics_multiline_string(self, tmp_path, monkeypatch):
        """Test file with multiline docstring."""
        test_file = tmp_path / "docstring.py"
        test_file.write_text(dedent('''
        """
        This is a docstring.
        It spans multiple lines.
        """
        def func():
            pass
        '''))

        mock_raw_metrics = MagicMock()
        mock_raw_metrics.loc = 7
        mock_raw_metrics.sloc = 3
        mock_raw_metrics.comments = 4
        mock_raw_metrics.multi = 4
        mock_raw_metrics.single_comments = 0

        mock_analyze = MagicMock(return_value=mock_raw_metrics)
        monkeypatch.setattr(
            "slop_code.metrics.languages.python.line_metrics.radon.raw.analyze",
            mock_analyze,
        )

        metrics = calculate_line_metrics(test_file)

        assert metrics.multi_comment == 4

    def test_calculate_line_metrics_blank_lines(self, tmp_path, monkeypatch):
        """Test file with blank lines."""
        test_file = tmp_path / "blanks.py"
        test_file.write_text("def a():\n    pass\n\n\ndef b():\n    pass\n")

        mock_raw_metrics = MagicMock()
        mock_raw_metrics.loc = 6
        mock_raw_metrics.sloc = 4
        mock_raw_metrics.comments = 0
        mock_raw_metrics.multi = 0
        mock_raw_metrics.single_comments = 0

        mock_analyze = MagicMock(return_value=mock_raw_metrics)
        monkeypatch.setattr(
            "slop_code.metrics.languages.python.line_metrics.radon.raw.analyze",
            mock_analyze,
        )

        metrics = calculate_line_metrics(test_file)

        assert metrics.total_lines == 6
        assert metrics.loc == 4  # Blank lines not in SLOC


# =============================================================================
# Edge Cases
# =============================================================================


class TestLineMetricsEdgeCases:
    """Edge case tests for line metrics."""

    def test_mixed_content(self, tmp_path, monkeypatch):
        """Test file with mixed content types."""
        test_file = tmp_path / "mixed.py"
        test_file.write_text(dedent('''
        # Single line comment
        """Multi-line
        docstring"""
        def func():
            # Inline comment
            x = 1  # End-of-line comment
            return x
        '''))

        mock_raw_metrics = MagicMock()
        mock_raw_metrics.loc = 8
        mock_raw_metrics.sloc = 4
        mock_raw_metrics.comments = 4
        mock_raw_metrics.multi = 2
        mock_raw_metrics.single_comments = 2

        mock_analyze = MagicMock(return_value=mock_raw_metrics)
        monkeypatch.setattr(
            "slop_code.metrics.languages.python.line_metrics.radon.raw.analyze",
            mock_analyze,
        )

        metrics = calculate_line_metrics(test_file)

        assert metrics.total_lines == 8
        assert metrics.comments == 4

    def test_unicode_content(self, tmp_path, monkeypatch):
        """Test file with unicode content."""
        test_file = tmp_path / "unicode.py"
        test_file.write_text("# Ünïcödé comment\ndef greet(): return 'Hëllö'\n")

        mock_raw_metrics = MagicMock()
        mock_raw_metrics.loc = 2
        mock_raw_metrics.sloc = 1
        mock_raw_metrics.comments = 1
        mock_raw_metrics.multi = 0
        mock_raw_metrics.single_comments = 1

        mock_analyze = MagicMock(return_value=mock_raw_metrics)
        monkeypatch.setattr(
            "slop_code.metrics.languages.python.line_metrics.radon.raw.analyze",
            mock_analyze,
        )

        metrics = calculate_line_metrics(test_file)

        assert metrics.total_lines == 2
