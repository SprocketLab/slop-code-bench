"""Tests for report models (TestResult, CorrectnessResults, GroupType)."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from slop_code.evaluation.report import CorrectnessResults
from slop_code.evaluation.report import GroupType
from slop_code.evaluation.report import TestResult as EvalTestResult


class TestGroupType:
    """Tests for GroupType enum."""

    def test_all_values_present(self):
        """GroupType has all required values."""
        assert GroupType.CORE == "Core"
        assert GroupType.FUNCTIONALITY == "Functionality"
        assert GroupType.REGRESSION == "Regression"
        assert GroupType.ERROR == "Error"

    def test_is_string_enum(self):
        """GroupType values are strings."""
        assert isinstance(GroupType.CORE.value, str)
        assert isinstance(GroupType.FUNCTIONALITY.value, str)
        assert isinstance(GroupType.REGRESSION.value, str)
        assert isinstance(GroupType.ERROR.value, str)

    def test_enum_membership(self):
        """Can iterate over all GroupType values."""
        all_types = list(GroupType)
        assert len(all_types) == 4
        assert GroupType.CORE in all_types
        assert GroupType.FUNCTIONALITY in all_types
        assert GroupType.REGRESSION in all_types
        assert GroupType.ERROR in all_types


class TestTestResult:
    """Tests for TestResult model."""

    def test_create_minimal(self):
        """Can create TestResult with minimal required fields."""
        result = EvalTestResult(
            id="test_example",
            checkpoint="checkpoint_1",
            group_type=GroupType.CORE,
            status="passed",
            duration_ms=100.0,
            file_path="tests/test_checkpoint_1.py",
        )
        assert result.id == "test_example"
        assert result.status == "passed"
        assert result.markers == []  # Default empty list
        assert result.failure_message is None  # Default None

    def test_create_with_all_fields(self):
        """Can create TestResult with all fields."""
        result = EvalTestResult(
            id="test_failure",
            checkpoint="checkpoint_2",
            group_type=GroupType.FUNCTIONALITY,
            status="failed",
            duration_ms=250.5,
            file_path="tests/test_checkpoint_2.py",
            markers=["functionality", "slow"],
            failure_message="AssertionError: expected 5, got 3",
        )
        assert result.failure_message is not None
        assert "AssertionError" in result.failure_message
        assert len(result.markers) == 2

    def test_status_validation(self):
        """Status field accepts only valid values."""
        # Valid statuses
        for status in ["passed", "failed", "skipped", "error"]:
            result = EvalTestResult(
                id="test",
                checkpoint="checkpoint_1",
                group_type=GroupType.CORE,
                status=status,
                duration_ms=1.0,
                file_path="tests/test.py",
            )
            assert result.status == status

        # Invalid status should raise validation error
        with pytest.raises(Exception):  # Pydantic ValidationError
            EvalTestResult(
                id="test",
                checkpoint="checkpoint_1",
                group_type=GroupType.CORE,
                status="invalid_status",
                duration_ms=1.0,
                file_path="tests/test.py",
            )

    def test_group_type_values(self):
        """Can create TestResult with any GroupType."""
        for group_type in GroupType:
            result = EvalTestResult(
                id="test",
                checkpoint="checkpoint_1",
                group_type=group_type,
                status="passed",
                duration_ms=1.0,
                file_path="tests/test.py",
            )
            assert result.group_type == group_type

    def test_serialization(self):
        """TestResult serializes to dict correctly."""
        result = EvalTestResult(
            id="test_example",
            checkpoint="checkpoint_1",
            group_type=GroupType.CORE,
            status="passed",
            duration_ms=100.0,
            file_path="tests/test.py",
            markers=["slow"],
        )
        data = result.model_dump()
        assert data["id"] == "test_example"
        assert data["group_type"] == "Core"  # Serializes as string
        # markers is excluded from serialization to reduce output verbosity
        assert "markers" not in data


class TestCorrectnessResults:
    """Tests for CorrectnessResults model."""

    def test_create_empty(self):
        """Can create CorrectnessResults with no tests."""
        results = CorrectnessResults(
            problem_name="test_problem",
            problem_version=1,
            checkpoint_name="checkpoint_1",
            checkpoint_version=1,
            duration=5.0,
            entrypoint="python main.py",
            pytest_exit_code=0,
            pytest_collected=0,
        )
        assert len(results.tests) == 0
        assert len(results.pass_counts) == 0
        assert len(results.total_counts) == 0

    def test_add_test_result_updates_counts(self):
        """Adding test results updates pass/total counts."""
        results = CorrectnessResults(
            problem_name="test",
            problem_version=1,
            checkpoint_name="checkpoint_1",
            checkpoint_version=1,
            duration=5.0,
            entrypoint="python main.py",
            pytest_exit_code=0,
            pytest_collected=2,
        )

        # Add passing CORE test
        results.add_test_result(
            EvalTestResult(
                id="test_1",
                checkpoint="checkpoint_1",
                group_type=GroupType.CORE,
                status="passed",
                duration_ms=100.0,
                file_path="tests/test.py",
            )
        )

        assert results.total_counts[GroupType.CORE] == 1
        assert results.pass_counts[GroupType.CORE] == 1

        # Add failing CORE test
        results.add_test_result(
            EvalTestResult(
                id="test_2",
                checkpoint="checkpoint_1",
                group_type=GroupType.CORE,
                status="failed",
                duration_ms=50.0,
                file_path="tests/test.py",
            )
        )

        assert results.total_counts[GroupType.CORE] == 2
        assert results.pass_counts[GroupType.CORE] == 1  # Still only 1 passed

    def test_passes_policy_core_cases_all_pass(self):
        """core-cases policy passes when all CORE tests pass."""
        results = CorrectnessResults(
            problem_name="test",
            problem_version=1,
            checkpoint_name="checkpoint_1",
            checkpoint_version=1,
            duration=5.0,
            entrypoint="python main.py",
            pytest_exit_code=0,
            pytest_collected=2,
        )

        # Two passing CORE tests
        for i in range(2):
            results.add_test_result(
                EvalTestResult(
                    id=f"test_{i}",
                    checkpoint="checkpoint_1",
                    group_type=GroupType.CORE,
                    status="passed",
                    duration_ms=100.0,
                    file_path="tests/test.py",
                )
            )

        assert results.passes_policy("core-cases")

    def test_passes_policy_core_cases_one_fails(self):
        """core-cases policy fails when any CORE test fails."""
        results = CorrectnessResults(
            problem_name="test",
            problem_version=1,
            checkpoint_name="checkpoint_1",
            checkpoint_version=1,
            duration=5.0,
            entrypoint="python main.py",
            pytest_exit_code=1,
            pytest_collected=2,
        )

        # One passing, one failing CORE test
        results.add_test_result(
            EvalTestResult(
                id="test_pass",
                checkpoint="checkpoint_1",
                group_type=GroupType.CORE,
                status="passed",
                duration_ms=100.0,
                file_path="tests/test.py",
            )
        )
        results.add_test_result(
            EvalTestResult(
                id="test_fail",
                checkpoint="checkpoint_1",
                group_type=GroupType.CORE,
                status="failed",
                duration_ms=100.0,
                file_path="tests/test.py",
            )
        )

        assert not results.passes_policy("core-cases")

    def test_passes_policy_core_cases_no_core_tests(self):
        """core-cases policy fails when no CORE tests exist."""
        results = CorrectnessResults(
            problem_name="test",
            problem_version=1,
            checkpoint_name="checkpoint_1",
            checkpoint_version=1,
            duration=5.0,
            entrypoint="python main.py",
            pytest_exit_code=0,
            pytest_collected=1,
        )

        # Only ERROR test, no CORE
        results.add_test_result(
            EvalTestResult(
                id="test_error",
                checkpoint="checkpoint_1",
                group_type=GroupType.ERROR,
                status="passed",
                duration_ms=100.0,
                file_path="tests/test.py",
            )
        )

        assert not results.passes_policy("core-cases")

    def test_passes_policy_all_non_error_cases(self):
        """all-non-error-cases policy ignores ERROR tests."""
        results = CorrectnessResults(
            problem_name="test",
            problem_version=1,
            checkpoint_name="checkpoint_1",
            checkpoint_version=1,
            duration=5.0,
            entrypoint="python main.py",
            pytest_exit_code=1,  # Exit 1 due to ERROR test failing
            pytest_collected=3,
        )

        # CORE passes
        results.add_test_result(
            EvalTestResult(
                id="test_core",
                checkpoint="checkpoint_1",
                group_type=GroupType.CORE,
                status="passed",
                duration_ms=100.0,
                file_path="tests/test.py",
            )
        )

        # FUNCTIONALITY passes
        results.add_test_result(
            EvalTestResult(
                id="test_func",
                checkpoint="checkpoint_1",
                group_type=GroupType.FUNCTIONALITY,
                status="passed",
                duration_ms=100.0,
                file_path="tests/test.py",
            )
        )

        # ERROR fails (should be ignored)
        results.add_test_result(
            EvalTestResult(
                id="test_error",
                checkpoint="checkpoint_1",
                group_type=GroupType.ERROR,
                status="failed",
                duration_ms=100.0,
                file_path="tests/test.py",
            )
        )

        assert results.passes_policy("all-non-error-cases")

    def test_passes_policy_all_non_error_cases_fails(self):
        """all-non-error-cases policy fails when FUNCTIONALITY fails."""
        results = CorrectnessResults(
            problem_name="test",
            problem_version=1,
            checkpoint_name="checkpoint_1",
            checkpoint_version=1,
            duration=5.0,
            entrypoint="python main.py",
            pytest_exit_code=1,
            pytest_collected=2,
        )

        # CORE passes
        results.add_test_result(
            EvalTestResult(
                id="test_core",
                checkpoint="checkpoint_1",
                group_type=GroupType.CORE,
                status="passed",
                duration_ms=100.0,
                file_path="tests/test.py",
            )
        )

        # FUNCTIONALITY fails
        results.add_test_result(
            EvalTestResult(
                id="test_func",
                checkpoint="checkpoint_1",
                group_type=GroupType.FUNCTIONALITY,
                status="failed",
                duration_ms=100.0,
                file_path="tests/test.py",
            )
        )

        assert not results.passes_policy("all-non-error-cases")

    def test_passes_policy_infrastructure_failure(self):
        """Any policy fails when infrastructure_failure=True."""
        results = CorrectnessResults(
            problem_name="test",
            problem_version=1,
            checkpoint_name="checkpoint_1",
            checkpoint_version=1,
            duration=0.1,
            entrypoint="python main.py",
            pytest_exit_code=5,  # EXIT_NOTESTSCOLLECTED
            pytest_collected=0,
            infrastructure_failure=True,
        )

        assert not results.passes_policy("core-cases")
        assert not results.passes_policy("all-non-error-cases")

    def test_passes_policy_invalid_policy_name(self):
        """Raises ValueError for unknown policy name."""
        results = CorrectnessResults(
            problem_name="test",
            problem_version=1,
            checkpoint_name="checkpoint_1",
            checkpoint_version=1,
            duration=5.0,
            entrypoint="python main.py",
            pytest_exit_code=0,
            pytest_collected=0,
        )

        with pytest.raises(ValueError, match="Unknown policy"):
            results.passes_policy("invalid-policy-name")

    def test_save_creates_file(self):
        """save() creates evaluation.json file."""
        results = CorrectnessResults(
            problem_name="test",
            problem_version=1,
            checkpoint_name="checkpoint_1",
            checkpoint_version=1,
            duration=5.0,
            entrypoint="python main.py",
            pytest_exit_code=0,
            pytest_collected=1,
        )

        results.add_test_result(
            EvalTestResult(
                id="test_1",
                checkpoint="checkpoint_1",
                group_type=GroupType.CORE,
                status="passed",
                duration_ms=100.0,
                file_path="tests/test.py",
            )
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            save_path = Path(tmpdir)
            results.save(save_path)

            eval_file = save_path / "evaluation.json"
            assert eval_file.exists()

            # Verify it's valid JSON
            with eval_file.open() as f:
                data = json.load(f)

            assert data["problem_name"] == "test"
            assert data["checkpoint_name"] == "checkpoint_1"
            # tests is now a grouped dict, not a list
            assert isinstance(data["tests"], dict)
            assert "checkpoint_1-Core" in data["tests"]
            assert data["tests"]["checkpoint_1-Core"]["passed"] == ["test_1"]
            assert "pytest_stdout" not in data
            assert "pytest_stderr" not in data

    def test_save_creates_grouped_tests_format(self):
        """save() creates tests as grouped dict with passed/failed arrays."""
        results = CorrectnessResults(
            problem_name="test",
            problem_version=1,
            checkpoint_name="checkpoint_1",
            checkpoint_version=1,
            duration=5.0,
            entrypoint="python main.py",
            pytest_exit_code=1,
            pytest_collected=3,
        )

        # Add tests from different groups with different statuses
        results.add_test_result(
            EvalTestResult(
                id="test_core_pass",
                checkpoint="checkpoint_1",
                group_type=GroupType.CORE,
                status="passed",
                duration_ms=100.0,
                file_path="tests/test.py",
            )
        )
        results.add_test_result(
            EvalTestResult(
                id="test_core_fail",
                checkpoint="checkpoint_1",
                group_type=GroupType.CORE,
                status="failed",
                duration_ms=50.0,
                file_path="tests/test.py",
            )
        )
        results.add_test_result(
            EvalTestResult(
                id="test_func_pass",
                checkpoint="checkpoint_1",
                group_type=GroupType.FUNCTIONALITY,
                status="passed",
                duration_ms=75.0,
                file_path="tests/test.py",
            )
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            save_path = Path(tmpdir)
            results.save(save_path)

            with (save_path / "evaluation.json").open() as f:
                data = json.load(f)

        # tests should be a dict, not a list
        assert isinstance(data["tests"], dict)

        # Check structure for Core tests
        assert "checkpoint_1-Core" in data["tests"]
        assert data["tests"]["checkpoint_1-Core"]["passed"] == [
            "test_core_pass"
        ]
        assert data["tests"]["checkpoint_1-Core"]["failed"] == [
            "test_core_fail"
        ]

        # Check structure for Functionality tests
        assert "checkpoint_1-Functionality" in data["tests"]
        assert data["tests"]["checkpoint_1-Functionality"]["passed"] == [
            "test_func_pass"
        ]
        assert data["tests"]["checkpoint_1-Functionality"]["failed"] == []

    def test_save_grouped_tests_multiple_checkpoints(self):
        """Grouped tests correctly separate different checkpoints."""
        results = CorrectnessResults(
            problem_name="test",
            problem_version=1,
            checkpoint_name="checkpoint_2",
            checkpoint_version=1,
            duration=5.0,
            entrypoint="python main.py",
            pytest_exit_code=0,
            pytest_collected=2,
        )

        # Add test from checkpoint_1 (regression)
        results.add_test_result(
            EvalTestResult(
                id="test_old",
                checkpoint="checkpoint_1",
                group_type=GroupType.REGRESSION,
                status="passed",
                duration_ms=50.0,
                file_path="tests/test.py",
            )
        )

        # Add test from checkpoint_2 (current)
        results.add_test_result(
            EvalTestResult(
                id="test_new",
                checkpoint="checkpoint_2",
                group_type=GroupType.CORE,
                status="passed",
                duration_ms=100.0,
                file_path="tests/test.py",
            )
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            save_path = Path(tmpdir)
            results.save(save_path)

            with (save_path / "evaluation.json").open() as f:
                data = json.load(f)

        # Both checkpoints should appear as separate keys
        assert "checkpoint_1-Regression" in data["tests"]
        assert "checkpoint_2-Core" in data["tests"]
        assert data["tests"]["checkpoint_1-Regression"]["passed"] == [
            "test_old"
        ]
        assert data["tests"]["checkpoint_2-Core"]["passed"] == ["test_new"]

    def test_save_grouped_tests_all_group_types(self):
        """All group types (Core, Functionality, Regression, Error) are handled."""
        results = CorrectnessResults(
            problem_name="test",
            problem_version=1,
            checkpoint_name="checkpoint_1",
            checkpoint_version=1,
            duration=5.0,
            entrypoint="python main.py",
            pytest_exit_code=0,
            pytest_collected=4,
        )

        # Add one test of each group type
        for group_type in GroupType:
            results.add_test_result(
                EvalTestResult(
                    id=f"test_{group_type.value.lower()}",
                    checkpoint="checkpoint_1",
                    group_type=group_type,
                    status="passed",
                    duration_ms=50.0,
                    file_path="tests/test.py",
                )
            )

        with tempfile.TemporaryDirectory() as tmpdir:
            save_path = Path(tmpdir)
            results.save(save_path)

            with (save_path / "evaluation.json").open() as f:
                data = json.load(f)

        # All group types should have their own key
        assert "checkpoint_1-Core" in data["tests"]
        assert "checkpoint_1-Functionality" in data["tests"]
        assert "checkpoint_1-Regression" in data["tests"]
        assert "checkpoint_1-Error" in data["tests"]

        # Each should have the correct test ID
        assert data["tests"]["checkpoint_1-Core"]["passed"] == ["test_core"]
        assert data["tests"]["checkpoint_1-Functionality"]["passed"] == [
            "test_functionality"
        ]
        assert data["tests"]["checkpoint_1-Regression"]["passed"] == [
            "test_regression"
        ]
        assert data["tests"]["checkpoint_1-Error"]["passed"] == ["test_error"]

    def test_to_output_dict_returns_grouped_format(self):
        """to_output_dict() returns dict with grouped tests format."""
        results = CorrectnessResults(
            problem_name="test",
            problem_version=1,
            checkpoint_name="checkpoint_1",
            checkpoint_version=1,
            duration=5.0,
            entrypoint="python main.py",
            pytest_exit_code=0,
            pytest_collected=2,
        )

        results.add_test_result(
            EvalTestResult(
                id="test_pass",
                checkpoint="checkpoint_1",
                group_type=GroupType.CORE,
                status="passed",
                duration_ms=100.0,
                file_path="tests/test.py",
            )
        )
        results.add_test_result(
            EvalTestResult(
                id="test_fail",
                checkpoint="checkpoint_1",
                group_type=GroupType.CORE,
                status="failed",
                duration_ms=50.0,
                file_path="tests/test.py",
            )
        )

        data = results.to_output_dict()

        # Should have grouped tests format
        assert isinstance(data["tests"], dict)
        assert "checkpoint_1-Core" in data["tests"]
        assert data["tests"]["checkpoint_1-Core"]["passed"] == ["test_pass"]
        assert data["tests"]["checkpoint_1-Core"]["failed"] == ["test_fail"]

        # Should still have other fields
        assert data["problem_name"] == "test"
        assert data["checkpoint_name"] == "checkpoint_1"

    def test_save_creates_directory(self):
        """save() creates directory if it doesn't exist."""
        results = CorrectnessResults(
            problem_name="test",
            problem_version=1,
            checkpoint_name="checkpoint_1",
            checkpoint_version=1,
            duration=5.0,
            entrypoint="python main.py",
            pytest_exit_code=0,
            pytest_collected=0,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            nested_path = Path(tmpdir) / "nested" / "dir"
            results.save(nested_path)

            assert nested_path.exists()
            assert (nested_path / "evaluation.json").exists()

    def test_serialization_roundtrip(self):
        """Results can be serialized and deserialized."""
        results = CorrectnessResults(
            problem_name="test",
            problem_version=1,
            checkpoint_name="checkpoint_1",
            checkpoint_version=1,
            duration=5.0,
            entrypoint="python main.py",
            pytest_exit_code=0,
            pytest_collected=1,
        )

        results.add_test_result(
            EvalTestResult(
                id="test_example",
                checkpoint="checkpoint_1",
                group_type=GroupType.CORE,
                status="passed",
                duration_ms=100.0,
                file_path="tests/test.py",
            )
        )

        # Serialize to JSON
        data = results.model_dump(mode="json")
        json_str = json.dumps(data)

        # Deserialize
        loaded_data = json.loads(json_str)
        loaded = CorrectnessResults(**loaded_data)

        assert loaded.problem_name == "test"
        assert len(loaded.tests) == 1
        assert loaded.tests[0].id == "test_example"
