"""Exhaustive tests for Python lint metrics.

Tests all functions in slop_code.metrics.languages.python.lint_metrics including:
- Public API: calculate_lint_metrics
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from textwrap import dedent
from unittest.mock import MagicMock

import pytest

from slop_code.metrics.languages.python import calculate_lint_metrics


# =============================================================================
# Calculate Lint Metrics Tests
# =============================================================================


class TestCalculateLintMetrics:
    """Tests for calculate_lint_metrics function."""

    def test_calculate_lint_metrics_with_errors(self, tmp_path, monkeypatch):
        """Test parsing ruff JSON output with lint errors."""
        test_file = tmp_path / "test.py"
        test_file.write_text("def func():\n    x=1\n")

        # Mock ruff output
        ruff_output = json.dumps([
            {"code": "E501", "count": 3, "fixable": True},
            {"code": "E302", "count": 2, "fixable": False},
            {"code": "W503", "count": 1, "fixable": True},
        ])

        mock_result = MagicMock()
        mock_result.stdout = ruff_output
        mock_result.returncode = 1

        mock_run = MagicMock(return_value=mock_result)
        monkeypatch.setattr("subprocess.run", mock_run)

        metrics = calculate_lint_metrics(test_file)

        assert metrics.errors == 6  # 3 + 2 + 1
        assert metrics.fixable == 4  # 3 + 1
        assert metrics.counts["E501"] == 3
        assert metrics.counts["E302"] == 2
        assert metrics.counts["W503"] == 1

        # Verify subprocess was called with correct args
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert call_args[0:3] == ["uv", "run", "ruff"]
        assert str(test_file.absolute()) in call_args

    def test_calculate_lint_metrics_no_errors(self, tmp_path, monkeypatch):
        """Test with clean code (no lint errors)."""
        test_file = tmp_path / "clean.py"
        test_file.write_text("def func():\n    pass\n")

        # Empty ruff output (no errors)
        mock_result = MagicMock()
        mock_result.stdout = "[]"
        mock_result.returncode = 0

        mock_run = MagicMock(return_value=mock_result)
        monkeypatch.setattr("subprocess.run", mock_run)

        metrics = calculate_lint_metrics(test_file)

        assert metrics.errors == 0
        assert metrics.fixable == 0
        assert metrics.counts == {}

    def test_calculate_lint_metrics_malformed_json(self, tmp_path, monkeypatch):
        """Test handling malformed JSON output with multiple lines."""
        test_file = tmp_path / "test.py"
        test_file.write_text("code")

        # Multi-line malformed output that will eventually be exhausted
        mock_result = MagicMock()
        mock_result.stdout = "invalid json line 1\ninvalid json line 2\n"
        mock_result.returncode = 1

        mock_run = MagicMock(return_value=mock_result)
        monkeypatch.setattr("subprocess.run", mock_run)

        metrics = calculate_lint_metrics(test_file)

        # Should return zero metrics on parse failure
        assert metrics.errors == 0
        assert metrics.fixable == 0
        assert metrics.counts == {}

    def test_calculate_lint_metrics_with_prefix(self, tmp_path, monkeypatch):
        """Test parsing JSON that has a prefix before the actual JSON."""
        test_file = tmp_path / "test.py"
        test_file.write_text("code")

        # Simulate output with a warning prefix
        ruff_output = 'Warning: something\n[{"code": "E501", "count": 1, "fixable": true}]'

        mock_result = MagicMock()
        mock_result.stdout = ruff_output
        mock_result.returncode = 1

        mock_run = MagicMock(return_value=mock_result)
        monkeypatch.setattr("subprocess.run", mock_run)

        metrics = calculate_lint_metrics(test_file)

        # Should skip the first line and parse the JSON
        assert metrics.errors == 1
        assert metrics.fixable == 1
        assert metrics.counts["E501"] == 1

    def test_calculate_lint_metrics_subprocess_error(self, tmp_path, monkeypatch):
        """Test handling subprocess errors gracefully."""
        test_file = tmp_path / "test.py"
        test_file.write_text("code")

        # Mock subprocess to raise CalledProcessError
        mock_run = MagicMock(side_effect=subprocess.CalledProcessError(1, "ruff"))
        monkeypatch.setattr("subprocess.run", mock_run)

        metrics = calculate_lint_metrics(test_file)

        # Should return zero metrics on error
        assert metrics.errors == 0
        assert metrics.fixable == 0
        assert metrics.counts == {}


# =============================================================================
# Error Code Tests
# =============================================================================


class TestErrorCodes:
    """Tests for specific error code handling."""

    def test_single_error_code(self, tmp_path, monkeypatch):
        """Test with single error code."""
        test_file = tmp_path / "test.py"
        test_file.write_text("x=1")

        ruff_output = json.dumps([
            {"code": "E501", "count": 5, "fixable": True},
        ])

        mock_result = MagicMock()
        mock_result.stdout = ruff_output
        mock_result.returncode = 1

        mock_run = MagicMock(return_value=mock_result)
        monkeypatch.setattr("subprocess.run", mock_run)

        metrics = calculate_lint_metrics(test_file)

        assert metrics.errors == 5
        assert metrics.fixable == 5
        assert len(metrics.counts) == 1
        assert metrics.counts["E501"] == 5

    def test_multiple_error_codes(self, tmp_path, monkeypatch):
        """Test with multiple error codes."""
        test_file = tmp_path / "test.py"
        test_file.write_text("code")

        ruff_output = json.dumps([
            {"code": "E501", "count": 2, "fixable": True},
            {"code": "E302", "count": 3, "fixable": True},
            {"code": "W503", "count": 1, "fixable": False},
            {"code": "F401", "count": 4, "fixable": True},
        ])

        mock_result = MagicMock()
        mock_result.stdout = ruff_output
        mock_result.returncode = 1

        mock_run = MagicMock(return_value=mock_result)
        monkeypatch.setattr("subprocess.run", mock_run)

        metrics = calculate_lint_metrics(test_file)

        assert metrics.errors == 10  # 2 + 3 + 1 + 4
        assert metrics.fixable == 9  # 2 + 3 + 4
        assert len(metrics.counts) == 4

    def test_no_fixable_errors(self, tmp_path, monkeypatch):
        """Test with only non-fixable errors."""
        test_file = tmp_path / "test.py"
        test_file.write_text("code")

        ruff_output = json.dumps([
            {"code": "E999", "count": 1, "fixable": False},
            {"code": "E501", "count": 2, "fixable": False},
        ])

        mock_result = MagicMock()
        mock_result.stdout = ruff_output
        mock_result.returncode = 1

        mock_run = MagicMock(return_value=mock_result)
        monkeypatch.setattr("subprocess.run", mock_run)

        metrics = calculate_lint_metrics(test_file)

        assert metrics.errors == 3
        assert metrics.fixable == 0


# =============================================================================
# Edge Cases
# =============================================================================


class TestLintMetricsEdgeCases:
    """Edge case tests for lint metrics."""

    def test_empty_array_output(self, tmp_path, monkeypatch):
        """Test with empty array output."""
        test_file = tmp_path / "test.py"
        test_file.write_text("pass")

        mock_result = MagicMock()
        mock_result.stdout = "[]"
        mock_result.returncode = 0

        mock_run = MagicMock(return_value=mock_result)
        monkeypatch.setattr("subprocess.run", mock_run)

        metrics = calculate_lint_metrics(test_file)

        assert metrics.errors == 0
        assert metrics.counts == {}

    def test_whitespace_in_output(self, tmp_path, monkeypatch):
        """Test handling whitespace in output."""
        test_file = tmp_path / "test.py"
        test_file.write_text("code")

        ruff_output = '  \n  [{"code": "E501", "count": 1, "fixable": true}]  \n'

        mock_result = MagicMock()
        mock_result.stdout = ruff_output
        mock_result.returncode = 1

        mock_run = MagicMock(return_value=mock_result)
        monkeypatch.setattr("subprocess.run", mock_run)

        metrics = calculate_lint_metrics(test_file)

        # Should handle whitespace and parse correctly
        assert metrics.errors == 1

    def test_missing_count_field(self, tmp_path, monkeypatch):
        """Test handling missing count field.

        Note: Current implementation doesn't handle missing fields gracefully
        and will raise KeyError.
        """
        test_file = tmp_path / "test.py"
        test_file.write_text("code")

        # Missing count field
        ruff_output = json.dumps([
            {"code": "E501", "fixable": True},
        ])

        mock_result = MagicMock()
        mock_result.stdout = ruff_output
        mock_result.returncode = 1

        mock_run = MagicMock(return_value=mock_result)
        monkeypatch.setattr("subprocess.run", mock_run)

        # Current implementation raises KeyError on missing fields
        with pytest.raises(KeyError):
            calculate_lint_metrics(test_file)

    def test_missing_fixable_field(self, tmp_path, monkeypatch):
        """Test handling missing fixable field.

        Note: Current implementation doesn't handle missing fields gracefully
        and will raise KeyError.
        """
        test_file = tmp_path / "test.py"
        test_file.write_text("code")

        # Missing fixable field
        ruff_output = json.dumps([
            {"code": "E501", "count": 1},
        ])

        mock_result = MagicMock()
        mock_result.stdout = ruff_output
        mock_result.returncode = 1

        mock_run = MagicMock(return_value=mock_result)
        monkeypatch.setattr("subprocess.run", mock_run)

        # Current implementation raises KeyError on missing fields
        with pytest.raises(KeyError):
            calculate_lint_metrics(test_file)

    def test_extra_fields_ignored(self, tmp_path, monkeypatch):
        """Test that extra fields in output are ignored."""
        test_file = tmp_path / "test.py"
        test_file.write_text("code")

        ruff_output = json.dumps([
            {
                "code": "E501",
                "count": 1,
                "fixable": True,
                "extra_field": "ignored",
                "another": 123,
            },
        ])

        mock_result = MagicMock()
        mock_result.stdout = ruff_output
        mock_result.returncode = 1

        mock_run = MagicMock(return_value=mock_result)
        monkeypatch.setattr("subprocess.run", mock_run)

        metrics = calculate_lint_metrics(test_file)

        assert metrics.errors == 1
        assert metrics.fixable == 1

    def test_zero_count(self, tmp_path, monkeypatch):
        """Test handling of zero count."""
        test_file = tmp_path / "test.py"
        test_file.write_text("code")

        ruff_output = json.dumps([
            {"code": "E501", "count": 0, "fixable": True},
        ])

        mock_result = MagicMock()
        mock_result.stdout = ruff_output
        mock_result.returncode = 0

        mock_run = MagicMock(return_value=mock_result)
        monkeypatch.setattr("subprocess.run", mock_run)

        metrics = calculate_lint_metrics(test_file)

        assert metrics.errors == 0


# =============================================================================
# Model Tests
# =============================================================================


class TestLintMetricsModel:
    """Tests for LintMetrics model."""

    def test_lint_metrics_serialization(self, tmp_path, monkeypatch):
        """Test that LintMetrics can be serialized."""
        test_file = tmp_path / "test.py"
        test_file.write_text("code")

        ruff_output = json.dumps([
            {"code": "E501", "count": 2, "fixable": True},
            {"code": "W503", "count": 1, "fixable": False},
        ])

        mock_result = MagicMock()
        mock_result.stdout = ruff_output
        mock_result.returncode = 1

        mock_run = MagicMock(return_value=mock_result)
        monkeypatch.setattr("subprocess.run", mock_run)

        metrics = calculate_lint_metrics(test_file)

        # Test Pydantic serialization
        data = metrics.model_dump()

        assert "errors" in data
        assert "fixable" in data
        assert "counts" in data
        assert data["errors"] == 3
        assert data["fixable"] == 2
        assert data["counts"]["E501"] == 2
        assert data["counts"]["W503"] == 1
