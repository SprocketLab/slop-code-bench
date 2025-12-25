"""Tests for migrate_evaluation_format command."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from slop_code.entrypoints.commands.migrate_evaluation_format import (
    _convert_tests_to_grouped_format,
    _migrate_single_file,
)


class TestConvertTestsToGroupedFormat:
    """Tests for _convert_tests_to_grouped_format."""

    def test_empty_list(self):
        """Empty list returns empty dict."""
        result = _convert_tests_to_grouped_format([])
        assert result == {}

    def test_single_test_passed(self):
        """Single passing test is grouped correctly."""
        tests = [
            {
                "id": "test_foo",
                "checkpoint": "checkpoint_1",
                "group_type": "Core",
                "status": "passed",
            }
        ]
        result = _convert_tests_to_grouped_format(tests)

        assert "checkpoint_1-Core" in result
        assert result["checkpoint_1-Core"]["passed"] == ["test_foo"]
        assert result["checkpoint_1-Core"]["failed"] == []

    def test_single_test_failed(self):
        """Single failing test is grouped correctly."""
        tests = [
            {
                "id": "test_bar",
                "checkpoint": "checkpoint_1",
                "group_type": "Core",
                "status": "failed",
            }
        ]
        result = _convert_tests_to_grouped_format(tests)

        assert result["checkpoint_1-Core"]["passed"] == []
        assert result["checkpoint_1-Core"]["failed"] == ["test_bar"]

    def test_multiple_tests_same_group(self):
        """Multiple tests in same group are collected correctly."""
        tests = [
            {
                "id": "test_1",
                "checkpoint": "checkpoint_1",
                "group_type": "Core",
                "status": "passed",
            },
            {
                "id": "test_2",
                "checkpoint": "checkpoint_1",
                "group_type": "Core",
                "status": "passed",
            },
            {
                "id": "test_3",
                "checkpoint": "checkpoint_1",
                "group_type": "Core",
                "status": "failed",
            },
        ]
        result = _convert_tests_to_grouped_format(tests)

        assert result["checkpoint_1-Core"]["passed"] == ["test_1", "test_2"]
        assert result["checkpoint_1-Core"]["failed"] == ["test_3"]

    def test_multiple_groups(self):
        """Tests are separated by group type."""
        tests = [
            {
                "id": "test_core",
                "checkpoint": "checkpoint_1",
                "group_type": "Core",
                "status": "passed",
            },
            {
                "id": "test_func",
                "checkpoint": "checkpoint_1",
                "group_type": "Functionality",
                "status": "passed",
            },
            {
                "id": "test_error",
                "checkpoint": "checkpoint_1",
                "group_type": "Error",
                "status": "failed",
            },
        ]
        result = _convert_tests_to_grouped_format(tests)

        assert "checkpoint_1-Core" in result
        assert "checkpoint_1-Functionality" in result
        assert "checkpoint_1-Error" in result
        assert result["checkpoint_1-Core"]["passed"] == ["test_core"]
        assert result["checkpoint_1-Functionality"]["passed"] == ["test_func"]
        assert result["checkpoint_1-Error"]["failed"] == ["test_error"]

    def test_multiple_checkpoints(self):
        """Tests are separated by checkpoint."""
        tests = [
            {
                "id": "test_old",
                "checkpoint": "checkpoint_1",
                "group_type": "Regression",
                "status": "passed",
            },
            {
                "id": "test_new",
                "checkpoint": "checkpoint_2",
                "group_type": "Core",
                "status": "passed",
            },
        ]
        result = _convert_tests_to_grouped_format(tests)

        assert "checkpoint_1-Regression" in result
        assert "checkpoint_2-Core" in result


class TestMigrateSingleFile:
    """Tests for _migrate_single_file."""

    def test_migrates_old_format(self, tmp_path):
        """Old list format is converted to grouped format."""
        eval_path = tmp_path / "evaluation.json"
        old_data = {
            "problem_name": "test",
            "tests": [
                {
                    "id": "test_foo",
                    "checkpoint": "checkpoint_1",
                    "group_type": "Core",
                    "status": "passed",
                }
            ],
        }
        eval_path.write_text(json.dumps(old_data))

        class MockLogger:
            def debug(self, *args, **kwargs):
                pass

            def info(self, *args, **kwargs):
                pass

            def warning(self, *args, **kwargs):
                pass

        success, message = _migrate_single_file(eval_path, dry_run=False, logger=MockLogger())

        assert success
        assert "Migrated 1 tests" in message

        # Verify file was updated
        with eval_path.open() as f:
            data = json.load(f)

        assert isinstance(data["tests"], dict)
        assert "checkpoint_1-Core" in data["tests"]
        assert data["tests"]["checkpoint_1-Core"]["passed"] == ["test_foo"]

    def test_skips_already_migrated(self, tmp_path):
        """Already migrated files are skipped."""
        eval_path = tmp_path / "evaluation.json"
        new_data = {
            "problem_name": "test",
            "tests": {
                "checkpoint_1-Core": {"passed": ["test_foo"], "failed": []},
            },
        }
        eval_path.write_text(json.dumps(new_data))

        class MockLogger:
            def debug(self, *args, **kwargs):
                pass

            def info(self, *args, **kwargs):
                pass

        success, message = _migrate_single_file(eval_path, dry_run=False, logger=MockLogger())

        assert success
        assert "Already migrated" in message

    def test_dry_run_does_not_modify(self, tmp_path):
        """Dry run does not modify files."""
        eval_path = tmp_path / "evaluation.json"
        old_data = {
            "problem_name": "test",
            "tests": [
                {
                    "id": "test_foo",
                    "checkpoint": "checkpoint_1",
                    "group_type": "Core",
                    "status": "passed",
                }
            ],
        }
        eval_path.write_text(json.dumps(old_data))
        original_content = eval_path.read_text()

        class MockLogger:
            def debug(self, *args, **kwargs):
                pass

            def info(self, *args, **kwargs):
                pass

        success, message = _migrate_single_file(eval_path, dry_run=True, logger=MockLogger())

        assert success
        assert "Would migrate" in message

        # File should be unchanged
        assert eval_path.read_text() == original_content
