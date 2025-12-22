"""Typed report models emitted by the evaluation runner.

The runner serializes results at multiple granularities—case, group, and
checkpoint. These Pydantic models make that structure explicit and provide
helper methods for flattening data into analytics-friendly shapes (JSON,
Parquet) while preserving enough context for downstream visualization.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from slop_code.logging import get_logger

logger = get_logger(__name__)


class GroupType(str, Enum):
    """Test categorization types for SCBench evaluation.

    Used to classify tests and determine pass policies:
    - CORE: Must-pass tests for checkpoint success
    - FUNCTIONALITY: Nice-to-have / optional features
    - REGRESSION: Tests from prior checkpoints (prevent breakage)
    - ERROR: Error-handling / edge-case tests

    In pytest-based evaluation:
    - Unmarked tests in current checkpoint → CORE
    - @pytest.mark.functionality → FUNCTIONALITY
    - @pytest.mark.error → ERROR
    - Tests from prior checkpoints (no error marker) → REGRESSION
    """

    CORE = "Core"
    FUNCTIONALITY = "Functionality"
    REGRESSION = "Regression"
    ERROR = "Error"


class TestResult(BaseModel):
    """Individual test result from pytest execution.

    Represents a single test case with categorization metadata and outcome.
    Replaces the old CaseReport/AttributeResult model from the Adapter system.

    Attributes:
        id: Pytest nodeid or unique test identifier (e.g., "test_basic_functionality")
        checkpoint: Checkpoint this test belongs to (e.g., "checkpoint_1")
        group_type: Categorization of this test (CORE, FUNCTIONALITY, REGRESSION, ERROR)
        status: Test outcome from pytest ("passed", "failed", "skipped", "error")
        duration_ms: Test execution time in milliseconds
        file_path: Test file path relative to tests/ (e.g., "tests/test_checkpoint_1.py")
        markers: Pytest markers applied to this test (e.g., ["functionality", "slow"])
        failure_message: Optional failure message if test failed/errored

    Example:
        >>> result = TestResult(
        ...     id="test_basic[case1]",
        ...     checkpoint="checkpoint_1",
        ...     group_type=GroupType.CORE,
        ...     status="passed",
        ...     duration_ms=123.45,
        ...     file_path="tests/test_checkpoint_1.py",
        ...     markers=[],
        ... )
    """

    id: str = Field(description="Pytest nodeid or unique test identifier")
    checkpoint: str = Field(
        description="Checkpoint this test belongs to (e.g., 'checkpoint_1')"
    )
    group_type: GroupType = Field(description="Categorization of this test")
    status: Literal["passed", "failed", "skipped", "error"] = Field(
        description="Test outcome from pytest"
    )
    duration_ms: float = Field(
        description="Test execution time in milliseconds"
    )
    file_path: str = Field(description="Test file path relative to tests/")
    markers: list[str] = Field(
        default_factory=list,
        description="Pytest markers applied to this test",
        exclude=True,  # Don't include in JSON serialization
    )
    failure_message: str | None = Field(
        default=None,
        description="Failure message if test failed/errored",
        exclude=True,  # Don't include in JSON serialization
    )


# Constants
DEFAULT_STAGE = "step-1"
FLATTENING_DELIMITER = "-"
PASSING_SCORE_THRESHOLD = 1.0


class PassPolicy(str, Enum):
    ANY = "any"
    ANY_CASE = "any-case"
    ALL_CASES = "all-cases"
    ALL_NON_ERROR_CASES = "all-non-error-cases"
    CORE_CASES = "core-cases"
    ANY_CORE_CASES = "any-core-cases"
    ALL_CORE_CASES = "all-core-cases"

    def check(
        self,
        pass_counts: Mapping[GroupType, int],
        total_counts: Mapping[GroupType, int],
    ) -> bool:
        """Return ``True`` when the counts satisfy the configured policy.

        Args:
            pass_counts: Number of passing cases per :class:`GroupType`.
            total_counts: Total executed cases per :class:`GroupType`.
        """
        core_passed = core_tests = 0
        non_error_passed = non_error_tests = 0
        total_passed = total_tests = 0

        for group_type in GroupType:
            if group_type == GroupType.CORE:
                core_passed += pass_counts.get(group_type, 0)
                core_tests += total_counts.get(group_type, 0)
            if group_type != GroupType.ERROR:
                non_error_passed += pass_counts.get(group_type, 0)
                non_error_tests += total_counts.get(group_type, 0)
            total_passed += pass_counts.get(group_type, 0)
            total_tests += total_counts.get(group_type, 0)

        match self:
            case PassPolicy.ANY_CASE:
                return total_passed > 0
            case PassPolicy.ALL_CASES:
                return total_passed == total_tests
            case PassPolicy.ALL_NON_ERROR_CASES:
                return non_error_passed == non_error_tests
            case PassPolicy.CORE_CASES:
                return core_passed == core_tests
            case PassPolicy.ANY_CORE_CASES:
                return core_passed > 0
            case PassPolicy.ALL_CORE_CASES:
                return core_passed == core_tests
            case _:
                return True


class GroupReport(BaseModel):
    """Aggregate pass/fail outcome for a single group."""

    duration: float
    results: dict[str, float]
    type: GroupType


class CorrectnessResults(BaseModel):
    """Aggregated test results for a checkpoint evaluation.

    Replaces the old Adapter-based report system with pytest-based aggregation.
    Contains all individual test results plus aggregated statistics by GroupType.

    Attributes:
        problem_name: Name of the problem being evaluated
        problem_version: Version number of the problem
        checkpoint_name: Name of the checkpoint (e.g., "checkpoint_1")
        checkpoint_version: Version number of the checkpoint
        duration: Total evaluation duration in seconds
        entrypoint: Command used to run the submission (e.g., "python main.py")
        tests: List of all individual test results
        pass_counts: Number of passed tests by GroupType
        total_counts: Total number of tests by GroupType
        pytest_exit_code: Exit code from pytest execution
        pytest_collected: Number of tests collected by pytest
        infrastructure_failure: Whether pytest execution itself failed
        stdout: Captured pytest stdout (not stored in evaluation.json)
        stderr: Captured pytest stderr (not stored in evaluation.json)
        pytest_ctrf_report: Raw CTRF JSON report (not stored in evaluation.json)

    Example:
        >>> results = CorrectnessResults(
        ...     problem_name="example",
        ...     problem_version=1,
        ...     checkpoint_name="checkpoint_1",
        ...     checkpoint_version=1,
        ...     duration=5.2,
        ...     entrypoint="python main.py",
        ...     pytest_exit_code=0,
        ...     pytest_collected=10,
        ... )
    """

    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    # Metadata
    problem_name: str = Field(description="Name of the problem")
    problem_version: int = Field(description="Version number of the problem")
    checkpoint_name: str = Field(description="Name of the checkpoint")
    checkpoint_version: int = Field(
        description="Version number of the checkpoint"
    )
    duration: float = Field(description="Total evaluation duration in seconds")
    entrypoint: str = Field(description="Command used to run the submission")

    # Test results
    tests: list[TestResult] = Field(
        default_factory=list, description="All individual test results"
    )

    # Aggregated counts by GroupType
    pass_counts: dict[GroupType, int] = Field(
        default_factory=dict, description="Number of passed tests by GroupType"
    )
    total_counts: dict[GroupType, int] = Field(
        default_factory=dict, description="Total number of tests by GroupType"
    )

    # Pytest execution metadata
    pytest_exit_code: int = Field(description="Exit code from pytest execution")
    pytest_collected: int = Field(
        description="Number of tests collected by pytest"
    )
    infrastructure_failure: bool = Field(
        default=False,
        description="Whether pytest execution itself failed (not just test failures)",
    )
    stdout: str | None = Field(
        default=None,
        exclude=True,
        description="Captured pytest stdout (not stored in evaluation.json)",
    )
    stderr: str | None = Field(
        default=None,
        exclude=True,
        description="Captured pytest stderr (not stored in evaluation.json)",
    )
    pytest_ctrf_report: dict[str, Any] | None = Field(
        default=None,
        exclude=True,
        description="Raw CTRF JSON report (not stored in evaluation.json)",
    )

    def add_test_result(self, result: TestResult) -> None:
        """Add a test result and update aggregated counts.

        Args:
            result: TestResult to add

        Example:
            >>> results.add_test_result(TestResult(...))
        """
        self.tests.append(result)

        # Update total count for this GroupType
        self.total_counts[result.group_type] = (
            self.total_counts.get(result.group_type, 0) + 1
        )

        # Update pass count if test passed
        if result.status == "passed":
            self.pass_counts[result.group_type] = (
                self.pass_counts.get(result.group_type, 0) + 1
            )

    def passes_policy(self, policy: str = "core-cases") -> bool:
        """Check if results pass the given policy.

        Policies:
        - "core-cases": All CORE tests must pass (default for checkpoint success)
        - "all-non-error-cases": All CORE, FUNCTIONALITY, and REGRESSION tests must pass

        Infrastructure failures always result in policy failure.

        Args:
            policy: Name of the pass policy to evaluate

        Returns:
            True if the policy passes, False otherwise

        Raises:
            ValueError: If policy name is not recognized

        Example:
            >>> results.passes_policy("core-cases")
            True
        """
        # Infrastructure failures always fail
        if self.infrastructure_failure:
            return False

        if policy == "core-cases":
            # All CORE tests must pass
            core_total = self.total_counts.get(GroupType.CORE, 0)
            core_passed = self.pass_counts.get(GroupType.CORE, 0)

            # Need at least one core test and all must pass
            return core_total > 0 and core_passed == core_total

        if policy == "all-non-error-cases":
            # All non-ERROR tests must pass
            for group_type in [
                GroupType.CORE,
                GroupType.FUNCTIONALITY,
                GroupType.REGRESSION,
            ]:
                total = self.total_counts.get(group_type, 0)
                passed = self.pass_counts.get(group_type, 0)

                # If there are tests of this type, they must all pass
                if total > 0 and passed != total:
                    return False

            return True

        raise ValueError(f"Unknown policy: {policy}")

    def save(self, save_dir: Path) -> None:
        """Save results to evaluation.json in the specified directory.

        Args:
            save_dir: Directory to save results (creates if doesn't exist)

        Example:
            >>> results.save(Path("outputs/checkpoint_1"))
        """
        save_dir.mkdir(parents=True, exist_ok=True)
        save_path = save_dir / "evaluation.json"

        with save_path.open("w") as f:
            json.dump(self.model_dump(mode="json"), f, indent=2)

        evaluation_dir = save_dir / "evaluation"
        evaluation_dir.mkdir(parents=True, exist_ok=True)

        if self.stdout is not None:
            (evaluation_dir / "stdout.txt").write_text(
                self.stdout, encoding="utf-8"
            )
        if self.stderr is not None:
            (evaluation_dir / "stderr.txt").write_text(
                self.stderr, encoding="utf-8"
            )
        if self.pytest_ctrf_report is not None:
            report_path = evaluation_dir / "report.json"
            with report_path.open("w", encoding="utf-8") as f:
                json.dump(self.pytest_ctrf_report, f, indent=2)
