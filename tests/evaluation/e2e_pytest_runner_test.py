"""End-to-end tests for the pytest-based evaluation runner.

These tests verify the full evaluation pipeline using a simple fixture problem
(word_stats) with multiple checkpoints and static assets.

These tests require Docker to be running. They will be skipped if Docker is
unavailable.
"""

import shutil
from pathlib import Path

import pytest

from slop_code.evaluation.config import ProblemConfig
from slop_code.evaluation.pytest_runner import run_checkpoint_pytest
from slop_code.evaluation.report import GroupType

# Path to fixtures
FIXTURES_DIR = Path(__file__).parent / "fixtures" / "word_stats"
PROBLEM_DIR = FIXTURES_DIR / "problem"
SUBMISSION_DIR = FIXTURES_DIR / "submission"


def docker_available() -> bool:
    """Check if Docker is available and running."""
    try:
        import docker

        client = docker.from_env()
        client.ping()
        return True
    except Exception:
        return False


# Skip all tests in this module if Docker is not available
pytestmark = pytest.mark.skipif(
    not docker_available(),
    reason="Docker is not available or not running",
)


@pytest.fixture
def problem_config() -> ProblemConfig:
    """Load the word_stats problem configuration."""
    return ProblemConfig.from_yaml(PROBLEM_DIR)


@pytest.fixture
def submission_path(tmp_path) -> Path:
    """Create a copy of the submission in a temp directory."""
    dest = tmp_path / "submission"
    shutil.copytree(SUBMISSION_DIR, dest)
    return dest


class TestPytestRunnerE2ECheckpoint1:
    """E2E tests for checkpoint 1 evaluation."""

    def test_checkpoint_1_passes(
        self,
        problem_config: ProblemConfig,
        submission_path: Path,
        docker_environment_spec,
    ):
        """Test that checkpoint 1 passes with correct submission."""
        checkpoint = problem_config.load_checkpoint("checkpoint_1")

        results = run_checkpoint_pytest(
            submission_path=submission_path,
            problem=problem_config,
            checkpoint=checkpoint,
            env_spec=docker_environment_spec,
        )

        # Should have collected tests
        assert results.pytest_collected > 0, "No tests were collected"

        # Should not have infrastructure failure
        assert not results.infrastructure_failure, (
            f"Infrastructure failure: exit_code={results.pytest_exit_code}"
        )

        # Should have CORE tests
        assert results.total_counts.get(GroupType.CORE, 0) > 0, (
            "No CORE tests found"
        )

        # All CORE tests should pass
        core_passed = results.pass_counts.get(GroupType.CORE, 0)
        core_total = results.total_counts.get(GroupType.CORE, 0)
        assert core_passed == core_total, (
            f"CORE tests failed: {core_passed}/{core_total} passed"
        )

        # Should pass core policy
        assert results.passes_policy("core-cases"), "Failed core-cases policy"


class TestPytestRunnerE2ECheckpoint2:
    """E2E tests for checkpoint 2 evaluation."""

    def test_checkpoint_2_passes(
        self,
        problem_config: ProblemConfig,
        submission_path: Path,
        docker_environment_spec,
    ):
        """Test that checkpoint 2 passes with correct submission."""
        checkpoint = problem_config.load_checkpoint("checkpoint_2")

        results = run_checkpoint_pytest(
            submission_path=submission_path,
            problem=problem_config,
            checkpoint=checkpoint,
            env_spec=docker_environment_spec,
        )

        # Should have collected tests
        assert results.pytest_collected > 0, "No tests were collected"

        # Should not have infrastructure failure
        assert not results.infrastructure_failure, (
            f"Infrastructure failure: exit_code={results.pytest_exit_code}"
        )

        # Should have CORE tests (including regression from checkpoint_1)
        core_total = results.total_counts.get(GroupType.CORE, 0)
        assert core_total > 0, "No CORE tests found"

        # All CORE tests should pass
        core_passed = results.pass_counts.get(GroupType.CORE, 0)
        assert core_passed == core_total, (
            f"CORE tests failed: {core_passed}/{core_total} passed"
        )

        # Should pass core policy
        assert results.passes_policy("core-cases"), "Failed core-cases policy"

    def test_checkpoint_2_runs_checkpoint_1_tests(
        self,
        problem_config: ProblemConfig,
        submission_path: Path,
        docker_environment_spec,
    ):
        """Test that checkpoint 2 also runs checkpoint 1 tests (regression)."""
        checkpoint = problem_config.load_checkpoint("checkpoint_2")

        results = run_checkpoint_pytest(
            submission_path=submission_path,
            problem=problem_config,
            checkpoint=checkpoint,
            env_spec=docker_environment_spec,
        )

        # Count tests from each checkpoint by looking at test IDs
        checkpoint_1_tests = [
            t for t in results.tests if "test_checkpoint_1" in t.file_path
        ]
        checkpoint_2_tests = [
            t for t in results.tests if "test_checkpoint_2" in t.file_path
        ]

        # Should have tests from both checkpoints
        assert len(checkpoint_1_tests) > 0, (
            "No tests from checkpoint_1 were run"
        )
        assert len(checkpoint_2_tests) > 0, (
            "No tests from checkpoint_2 were run"
        )


class TestPytestRunnerE2EStaticAssets:
    """E2E tests verifying static asset handling."""

    def test_static_assets_available_to_tests(
        self,
        problem_config: ProblemConfig,
        submission_path: Path,
        docker_environment_spec,
    ):
        """Test that static assets are correctly passed to tests."""
        # The word_stats problem has a 'stopwords' static asset
        assert "stopwords" in problem_config.static_assets, (
            "stopwords asset not found in problem config"
        )

        checkpoint = problem_config.load_checkpoint("checkpoint_2")

        results = run_checkpoint_pytest(
            submission_path=submission_path,
            problem=problem_config,
            checkpoint=checkpoint,
            env_spec=docker_environment_spec,
        )

        # Tests that use stopwords should pass
        # (they would fail or skip if static assets weren't available)
        stopword_tests = [
            t for t in results.tests if "stopword" in t.id.lower()
        ]

        # Should have some stopword-related tests
        assert len(stopword_tests) > 0, (
            "No stopword tests found - static assets may not be working"
        )

        # Stopword tests should pass (not skip)
        passed_stopword_tests = [
            t for t in stopword_tests if t.status == "passed"
        ]
        assert len(passed_stopword_tests) > 0, (
            f"Stopword tests did not pass: {[t.status for t in stopword_tests]}"
        )


class TestPytestRunnerE2EMarkers:
    """E2E tests verifying pytest marker handling."""

    def test_functionality_marker_categorized_correctly(
        self,
        problem_config: ProblemConfig,
        submission_path: Path,
        docker_environment_spec,
    ):
        """Test that @pytest.mark.functionality tests are categorized as FUNCTIONALITY."""
        checkpoint = problem_config.load_checkpoint("checkpoint_2")

        results = run_checkpoint_pytest(
            submission_path=submission_path,
            problem=problem_config,
            checkpoint=checkpoint,
            env_spec=docker_environment_spec,
        )

        # Should have some FUNCTIONALITY tests
        functionality_total = results.total_counts.get(
            GroupType.FUNCTIONALITY, 0
        )

        # The test_checkpoint_2.py has @pytest.mark.functionality tests
        assert functionality_total > 0, (
            "No FUNCTIONALITY tests found - marker handling may be broken"
        )

        # Functionality tests should be tracked separately from CORE
        core_total = results.total_counts.get(GroupType.CORE, 0)
        assert core_total > 0, "No CORE tests found"

        # Total should be more than just CORE (has FUNCTIONALITY too)
        total_tests = sum(results.total_counts.values())
        assert total_tests > core_total, (
            "Only CORE tests found, expected FUNCTIONALITY tests too"
        )
