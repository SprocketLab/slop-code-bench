"""Tests for pytest_runner module."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from slop_code.evaluation.config import CheckpointConfig
from slop_code.evaluation.config import ProblemConfig
from slop_code.evaluation.pytest_runner import EXIT_INTERNALERROR
from slop_code.evaluation.pytest_runner import EXIT_INTERRUPTED
from slop_code.evaluation.pytest_runner import EXIT_NOTESTSCOLLECTED
from slop_code.evaluation.pytest_runner import EXIT_OK
from slop_code.evaluation.pytest_runner import EXIT_TESTSFAILED
from slop_code.evaluation.pytest_runner import EXIT_USAGEERROR
from slop_code.evaluation.pytest_runner import INFRA_FAILURE_CODES
from slop_code.evaluation.pytest_runner import VALID_EXIT_CODES
from slop_code.evaluation.pytest_runner import PytestRunner
from slop_code.evaluation.pytest_runner import run_checkpoint_pytest
from slop_code.evaluation.report import GroupType
from slop_code.execution import EnvironmentSpec


@pytest.fixture
def mock_problem_config():
    """Create a mock ProblemConfig for testing."""
    problem = Mock(spec=ProblemConfig)
    problem.name = "test_problem"
    problem.version = 1
    problem.path = Path("/problems/test_problem")
    problem.entry_file = "main.py"
    problem.markers = {
        "functionality": "optional tests",
        "error": "error handling tests",
    }
    problem.static_assets = {}

    # Mock iterate_checkpoint_items to return checkpoints in order
    problem.iterate_checkpoint_items.return_value = [
        ("checkpoint_1", Mock(order=1)),
        ("checkpoint_2", Mock(order=2)),
        ("checkpoint_3", Mock(order=3)),
    ]

    return problem


@pytest.fixture
def mock_checkpoint_config():
    """Create a mock CheckpointConfig for testing."""
    checkpoint = Mock(spec=CheckpointConfig)
    checkpoint.name = "checkpoint_2"
    checkpoint.version = 1
    checkpoint.timeout = 30
    checkpoint.env = {}
    return checkpoint


@pytest.fixture
def mock_environment():
    """Create a mock EnvironmentSpec for testing."""
    env = Mock(spec=EnvironmentSpec)
    env.type = "local"
    env.get_command.return_value = "python main.py"
    env.get_full_env.return_value = {}
    return env


@pytest.fixture
def pytest_runner(mock_problem_config, mock_checkpoint_config, mock_environment):
    """Create a PytestRunner instance for testing."""
    return PytestRunner(
        problem=mock_problem_config,
        checkpoint=mock_checkpoint_config,
        environment=mock_environment,
        submission_path=Path("/tmp/submission"),
    )


class TestConstants:
    """Tests for module constants."""

    def test_exit_codes_defined(self):
        """Exit codes are defined correctly."""
        assert EXIT_OK == 0
        assert EXIT_TESTSFAILED == 1
        assert EXIT_INTERRUPTED == 2
        assert EXIT_INTERNALERROR == 3
        assert EXIT_USAGEERROR == 4
        assert EXIT_NOTESTSCOLLECTED == 5

    def test_valid_exit_codes(self):
        """Valid exit codes include OK and TESTSFAILED."""
        assert EXIT_OK in VALID_EXIT_CODES
        assert EXIT_TESTSFAILED in VALID_EXIT_CODES
        assert len(VALID_EXIT_CODES) == 2

    def test_infra_failure_codes(self):
        """Infrastructure failure codes are correct."""
        assert EXIT_INTERRUPTED in INFRA_FAILURE_CODES
        assert EXIT_INTERNALERROR in INFRA_FAILURE_CODES
        assert EXIT_USAGEERROR in INFRA_FAILURE_CODES
        assert EXIT_NOTESTSCOLLECTED in INFRA_FAILURE_CODES
        assert len(INFRA_FAILURE_CODES) == 4


class TestPytestRunner:
    """Tests for PytestRunner class."""

    def test_init(self, mock_problem_config, mock_checkpoint_config, mock_environment):
        """PytestRunner initializes correctly."""
        runner = PytestRunner(
            problem=mock_problem_config,
            checkpoint=mock_checkpoint_config,
            environment=mock_environment,
            submission_path=Path("/tmp/test"),
        )

        assert runner.problem == mock_problem_config
        assert runner.checkpoint == mock_checkpoint_config
        assert runner.environment == mock_environment
        assert runner.submission_path == Path("/tmp/test")

    def test_get_entrypoint_command(self, pytest_runner, mock_environment):
        """_get_entrypoint_command returns formatted command."""
        result = pytest_runner._get_entrypoint_command()

        assert result == "python main.py"
        mock_environment.get_command.assert_called_once_with(
            "main.py", is_agent_run=False
        )

    def test_get_test_files_for_checkpoint_includes_current_and_prior(
        self, pytest_runner
    ):
        """_get_test_files_for_checkpoint returns files up to current checkpoint."""
        # Evaluating checkpoint_2, should get checkpoint_1 and checkpoint_2
        files = pytest_runner._get_test_files_for_checkpoint()

        assert files == [
            "tests/test_checkpoint_1.py",
            "tests/test_checkpoint_2.py",
        ]
        # Should NOT include checkpoint_3

    def test_get_test_files_for_checkpoint_first_only(
        self, mock_problem_config, mock_environment
    ):
        """First checkpoint only gets its own test file."""
        checkpoint = Mock()
        checkpoint.name = "checkpoint_1"
        runner = PytestRunner(
            problem=mock_problem_config,
            checkpoint=checkpoint,
            environment=mock_environment,
            submission_path=Path("/tmp/submission"),
        )

        files = runner._get_test_files_for_checkpoint()

        assert files == ["tests/test_checkpoint_1.py"]

    def test_infer_checkpoint_from_file(self, pytest_runner):
        """_infer_checkpoint_from_file extracts checkpoint name."""
        assert (
            pytest_runner._infer_checkpoint_from_file("tests/test_checkpoint_1.py")
            == "checkpoint_1"
        )
        assert (
            pytest_runner._infer_checkpoint_from_file("tests/test_checkpoint_2.py")
            == "checkpoint_2"
        )
        assert (
            pytest_runner._infer_checkpoint_from_file("tests/foo/test_checkpoint_3.py")
            == "checkpoint_3"
        )

    def test_infer_checkpoint_from_file_fallback(self, pytest_runner):
        """_infer_checkpoint_from_file falls back to current checkpoint."""
        # Invalid path pattern
        result = pytest_runner._infer_checkpoint_from_file("invalid_path.py")
        assert result == "checkpoint_2"  # Current checkpoint

    def test_determine_group_type_current_core(self, pytest_runner):
        """Unmarked tests in current checkpoint are CORE."""
        group_type = pytest_runner._determine_group_type(
            test_checkpoint="checkpoint_2",
            markers=[],
            current_checkpoint="checkpoint_2",
        )
        assert group_type == GroupType.CORE

    def test_determine_group_type_current_functionality(self, pytest_runner):
        """Functionality-marked tests in current checkpoint are FUNCTIONALITY."""
        group_type = pytest_runner._determine_group_type(
            test_checkpoint="checkpoint_2",
            markers=["functionality"],
            current_checkpoint="checkpoint_2",
        )
        assert group_type == GroupType.FUNCTIONALITY

    def test_determine_group_type_current_error(self, pytest_runner):
        """Error-marked tests in current checkpoint are ERROR."""
        group_type = pytest_runner._determine_group_type(
            test_checkpoint="checkpoint_2",
            markers=["error"],
            current_checkpoint="checkpoint_2",
        )
        assert group_type == GroupType.ERROR

    def test_determine_group_type_prior_regression(self, pytest_runner):
        """Unmarked tests from prior checkpoints are REGRESSION."""
        group_type = pytest_runner._determine_group_type(
            test_checkpoint="checkpoint_1",  # Prior checkpoint
            markers=[],
            current_checkpoint="checkpoint_2",
        )
        assert group_type == GroupType.REGRESSION

    def test_determine_group_type_prior_error_still_error(self, pytest_runner):
        """Error-marked tests from prior checkpoints are still ERROR."""
        group_type = pytest_runner._determine_group_type(
            test_checkpoint="checkpoint_1",  # Prior checkpoint
            markers=["error"],
            current_checkpoint="checkpoint_2",
        )
        assert group_type == GroupType.ERROR

    def test_determine_group_type_prior_functionality_becomes_regression(
        self, pytest_runner
    ):
        """Functionality-marked tests from prior checkpoints become REGRESSION."""
        group_type = pytest_runner._determine_group_type(
            test_checkpoint="checkpoint_1",  # Prior checkpoint
            markers=["functionality"],
            current_checkpoint="checkpoint_2",
        )
        assert group_type == GroupType.REGRESSION

    def test_determine_group_type_error_always_wins(self, pytest_runner):
        """Error marker takes priority over functionality marker."""
        group_type = pytest_runner._determine_group_type(
            test_checkpoint="checkpoint_2",
            markers=["functionality", "error"],
            current_checkpoint="checkpoint_2",
        )
        assert group_type == GroupType.ERROR

    def test_generate_pytest_ini(self, pytest_runner, tmp_path):
        """_generate_pytest_ini creates valid pytest.ini."""
        pytest_runner._generate_pytest_ini(tmp_path)

        pytest_ini = tmp_path / "pytest.ini"
        assert pytest_ini.exists()

        content = pytest_ini.read_text()
        assert "[pytest]" in content
        assert "testpaths = tests" in content
        assert "functionality: optional tests" in content
        assert "error: error handling tests" in content

    def test_build_pytest_command(self, pytest_runner):
        """_build_pytest_command builds correct command."""
        cmd = pytest_runner._build_pytest_command(
            test_files=["tests/test_checkpoint_1.py"],
            static_assets={"sde_dir": "/data/sde"},
        )

        assert "uv run pytest" in cmd
        assert "tests/test_checkpoint_1.py" in cmd
        assert "--entrypoint=" in cmd
        assert "--checkpoint=" in cmd
        assert "checkpoint_2" in cmd
        assert "--static-assets=" in cmd
        assert "--ctrf=.scbench/ctrf-report.json" in cmd
        assert "-v" in cmd

    def test_build_pytest_command_multiple_files(self, pytest_runner):
        """_build_pytest_command includes multiple test files."""
        cmd = pytest_runner._build_pytest_command(
            test_files=[
                "tests/test_checkpoint_1.py",
                "tests/test_checkpoint_2.py",
            ],
            static_assets={},
        )

        assert "tests/test_checkpoint_1.py" in cmd
        assert "tests/test_checkpoint_2.py" in cmd

    def test_parse_ctrf_report_valid(self, pytest_runner, tmp_path):
        """_parse_ctrf_report parses valid CTRF JSON."""
        ctrf_data = {
            "results": {
                "tool": {"name": "pytest"},
                "tests": [
                    {"name": "test_1", "status": "passed", "duration": 100},
                    {"name": "test_2", "status": "failed", "duration": 50},
                ],
            }
        }

        ctrf_file = tmp_path / "report.json"
        ctrf_file.write_text(json.dumps(ctrf_data))

        tests = pytest_runner._parse_ctrf_report(ctrf_file)

        assert len(tests) == 2
        assert tests[0]["name"] == "test_1"
        assert tests[1]["name"] == "test_2"

    def test_parse_ctrf_report_missing_file(self, pytest_runner, tmp_path):
        """_parse_ctrf_report returns empty list if file missing."""
        missing_file = tmp_path / "nonexistent.json"
        tests = pytest_runner._parse_ctrf_report(missing_file)

        assert tests == []

    def test_parse_ctrf_report_invalid_json(self, pytest_runner, tmp_path):
        """_parse_ctrf_report returns empty list for invalid JSON."""
        invalid_file = tmp_path / "invalid.json"
        invalid_file.write_text("not valid json {{{")

        tests = pytest_runner._parse_ctrf_report(invalid_file)

        assert tests == []

    def test_parse_ctrf_report_missing_tests_key(self, pytest_runner, tmp_path):
        """_parse_ctrf_report returns empty list if tests key missing."""
        ctrf_data = {"results": {"tool": {"name": "pytest"}}}

        ctrf_file = tmp_path / "report.json"
        ctrf_file.write_text(json.dumps(ctrf_data))

        tests = pytest_runner._parse_ctrf_report(ctrf_file)

        assert tests == []

    def test_check_collection_line_success(self, pytest_runner):
        """_check_collection_line finds collection line."""
        stdout = "collected 10 items\n\ntest_example.py::test_1 PASSED"
        success, count = pytest_runner._check_collection_line(stdout)

        assert success is True
        assert count == 10

    def test_check_collection_line_single_item(self, pytest_runner):
        """_check_collection_line handles singular 'item'."""
        stdout = "collected 1 item\n\ntest_example.py::test_1 PASSED"
        success, count = pytest_runner._check_collection_line(stdout)

        assert success is True
        assert count == 1

    def test_check_collection_line_zero_items(self, pytest_runner):
        """_check_collection_line returns False for 0 items."""
        stdout = "collected 0 items\n"
        success, count = pytest_runner._check_collection_line(stdout)

        assert success is False
        assert count == 0

    def test_check_collection_line_not_found(self, pytest_runner):
        """_check_collection_line returns False if line not found."""
        stdout = "ERROR: something went wrong\n"
        success, count = pytest_runner._check_collection_line(stdout)

        assert success is False
        assert count == 0

    def test_convert_ctrf_test_to_result(self, pytest_runner):
        """_convert_ctrf_test_to_result creates TestResult."""
        ctrf_test = {
            "name": "test_example",
            "status": "passed",
            "duration": 123,
            "filePath": "tests/test_checkpoint_2.py",
            "tags": ["functionality"],
            "message": None,
        }

        result = pytest_runner._convert_ctrf_test_to_result(ctrf_test)

        assert result.id == "test_example"
        assert result.status == "passed"
        assert result.duration_ms == 123
        assert result.file_path == "tests/test_checkpoint_2.py"
        assert result.checkpoint == "checkpoint_2"
        assert result.group_type == GroupType.FUNCTIONALITY
        assert result.markers == ["functionality"]

    def test_convert_ctrf_test_to_result_failed(self, pytest_runner):
        """_convert_ctrf_test_to_result handles failed test with message."""
        ctrf_test = {
            "name": "test_failure",
            "status": "failed",
            "duration": 50,
            "filePath": "tests/test_checkpoint_2.py",
            "tags": [],
            "message": "AssertionError: expected 5, got 3",
        }

        result = pytest_runner._convert_ctrf_test_to_result(ctrf_test)

        assert result.status == "failed"
        assert result.failure_message == "AssertionError: expected 5, got 3"
        assert result.group_type == GroupType.CORE

    def test_convert_ctrf_test_to_result_regression(self, pytest_runner):
        """_convert_ctrf_test_to_result identifies regression tests."""
        ctrf_test = {
            "name": "test_prior",
            "status": "passed",
            "duration": 100,
            "filePath": "tests/test_checkpoint_1.py",  # Prior checkpoint
            "tags": [],
        }

        result = pytest_runner._convert_ctrf_test_to_result(ctrf_test)

        assert result.checkpoint == "checkpoint_1"
        assert result.group_type == GroupType.REGRESSION

    def test_convert_ctrf_test_to_result_missing_tags(self, pytest_runner):
        """_convert_ctrf_test_to_result handles missing tags."""
        ctrf_test = {
            "name": "test_no_tags",
            "status": "passed",
            "duration": 100,
            "filePath": "tests/test_checkpoint_2.py",
            # No tags key
        }

        result = pytest_runner._convert_ctrf_test_to_result(ctrf_test)

        assert result.markers == []
        assert result.group_type == GroupType.CORE

    def test_convert_ctrf_test_to_result_null_tags(self, pytest_runner):
        """_convert_ctrf_test_to_result handles null tags."""
        ctrf_test = {
            "name": "test_null_tags",
            "status": "passed",
            "duration": 100,
            "filePath": "tests/test_checkpoint_2.py",
            "tags": None,
        }

        result = pytest_runner._convert_ctrf_test_to_result(ctrf_test)

        assert result.markers == []

    def test_convert_ctrf_test_to_result_defaults(self, pytest_runner):
        """_convert_ctrf_test_to_result uses defaults for missing fields."""
        ctrf_test = {
            "name": "test_minimal",
            # Missing other fields
        }

        result = pytest_runner._convert_ctrf_test_to_result(ctrf_test)

        assert result.id == "test_minimal"
        assert result.status == "error"  # Default
        assert result.duration_ms == 0  # Default
        assert result.file_path == ""  # Default


class TestRunCheckpointPytest:
    """Tests for run_checkpoint_pytest function."""

    def test_creates_runner_and_calls_run(
        self, mock_problem_config, mock_checkpoint_config, mock_environment
    ):
        """run_checkpoint_pytest creates runner and calls run()."""
        from unittest.mock import patch

        mock_results = Mock()

        with patch.object(PytestRunner, "run", return_value=mock_results) as mock_run:
            result = run_checkpoint_pytest(
                submission_path=Path("/tmp/submission"),
                problem=mock_problem_config,
                checkpoint=mock_checkpoint_config,
                env_spec=mock_environment,
            )

            mock_run.assert_called_once()
            assert result == mock_results


class TestPytestRunnerRunMethod:
    """Integration tests for PytestRunner.run() with mocked execution."""

    def test_run_orchestration_success(
        self,
        mock_problem_config,
        mock_checkpoint_config,
        mock_environment,
        tmp_path,
    ):
        """run() orchestrates all steps correctly with passing tests."""
        from unittest.mock import MagicMock, patch

        # Create a mock submission directory with tests/ subdirectory
        submission_path = tmp_path / "submission"
        submission_path.mkdir()
        tests_dir = submission_path / "tests"
        tests_dir.mkdir()
        # Create pyproject.toml to skip uv init
        (tests_dir / "pyproject.toml").write_text("[project]\nname = 'tests'\n")

        # Mock CTRF report data
        ctrf_data = {
            "results": {
                "tool": {"name": "pytest"},
                "tests": [
                    {
                        "name": "test_core::test_basic",
                        "status": "passed",
                        "duration": 100,
                        "filePath": "tests/test_checkpoint_2.py",
                        "tags": [],
                    },
                    {
                        "name": "test_func::test_optional",
                        "status": "passed",
                        "duration": 50,
                        "filePath": "tests/test_checkpoint_2.py",
                        "tags": ["functionality"],
                    },
                    {
                        "name": "test_regression::test_old",
                        "status": "passed",
                        "duration": 30,
                        "filePath": "tests/test_checkpoint_1.py",
                        "tags": [],
                    },
                ],
            }
        }

        # Create mock execution results
        # First call is uv add, second call is pytest
        mock_uv_result = Mock()
        mock_uv_result.exit_code = 0
        mock_uv_result.stdout = "Resolved 4 packages"
        mock_uv_result.stderr = ""
        mock_uv_result.elapsed = 0.5

        mock_pytest_result = Mock()
        mock_pytest_result.exit_code = 0
        mock_pytest_result.stdout = "collected 3 items\n\nall tests passed"
        mock_pytest_result.stderr = ""
        mock_pytest_result.elapsed = 1.5

        # Create mock runtime that returns different results
        mock_runtime = MagicMock()
        mock_runtime.execute.side_effect = [mock_uv_result, mock_pytest_result]

        # Create mock session
        mock_session = MagicMock()
        mock_session.spawn.return_value = mock_runtime

        # Create mock workspace
        mock_workspace = MagicMock()
        mock_workspace.working_dir = submission_path

        runner = PytestRunner(
            problem=mock_problem_config,
            checkpoint=mock_checkpoint_config,
            environment=mock_environment,
            submission_path=submission_path,
        )

        # Patch the dependencies
        with (
            patch(
                "slop_code.evaluation.pytest_runner.Snapshot"
            ) as mock_snapshot_cls,
            patch(
                "slop_code.evaluation.pytest_runner.Workspace"
            ) as mock_workspace_cls,
            patch(
                "slop_code.evaluation.pytest_runner.Session"
            ) as mock_session_cls,
            patch(
                "slop_code.evaluation.pytest_runner.resolve_static_assets"
            ) as mock_resolve,
        ):
            mock_snapshot_cls.from_directory.return_value = Mock()
            mock_workspace_cls.return_value = mock_workspace
            mock_session_cls.return_value = mock_session
            mock_resolve.return_value = {}

            # Write CTRF report that will be read
            scbench_dir = submission_path / ".scbench"
            scbench_dir.mkdir()
            (scbench_dir / "ctrf-report.json").write_text(json.dumps(ctrf_data))

            results = runner.run()

        # Verify results
        assert results.problem_name == "test_problem"
        assert results.checkpoint_name == "checkpoint_2"
        assert results.pytest_exit_code == 0
        assert results.pytest_collected == 3
        assert results.infrastructure_failure is False

        # Check test counts
        assert len(results.tests) == 3
        assert results.total_counts[GroupType.CORE] == 1
        assert results.total_counts[GroupType.FUNCTIONALITY] == 1
        assert results.total_counts[GroupType.REGRESSION] == 1
        assert results.pass_counts[GroupType.CORE] == 1
        assert results.pass_counts[GroupType.FUNCTIONALITY] == 1
        assert results.pass_counts[GroupType.REGRESSION] == 1

    def test_run_passes_container_asset_paths_for_docker(
        self,
        mock_problem_config,
        mock_checkpoint_config,
        mock_environment,
        tmp_path,
    ):
        """run() uses container paths for static assets in Docker."""
        from unittest.mock import MagicMock, patch

        submission_path = tmp_path / "submission"
        submission_path.mkdir()

        mock_environment.type = "docker"

        resolved_asset = Mock()
        resolved_asset.absolute_path = Path("/host/stopwords.txt")
        resolved_asset.save_path = Path("static/stopwords.txt")
        resolved_assets = {"stopwords": resolved_asset}

        captured_assets: dict[str, str] = {}

        def _capture_assets(
            _test_files: list[str],
            static_assets: dict[str, str],
        ) -> str:
            captured_assets.update(static_assets)
            return "pytest"

        exec_result = Mock()
        exec_result.exit_code = 0
        exec_result.stdout = "collected 1 item"
        exec_result.stderr = ""
        exec_result.elapsed = 0.1

        runtime = MagicMock()
        runtime.execute.return_value = exec_result

        session = MagicMock()
        session.spawn.return_value = runtime

        workspace = MagicMock()
        workspace.working_dir = submission_path

        runner = PytestRunner(
            problem=mock_problem_config,
            checkpoint=mock_checkpoint_config,
            environment=mock_environment,
            submission_path=submission_path,
        )

        with (
            patch(
                "slop_code.evaluation.pytest_runner.Snapshot"
            ) as mock_snapshot_cls,
            patch(
                "slop_code.evaluation.pytest_runner.Workspace"
            ) as mock_workspace_cls,
            patch(
                "slop_code.evaluation.pytest_runner.Session"
            ) as mock_session_cls,
            patch(
                "slop_code.evaluation.pytest_runner.resolve_static_assets"
            ) as mock_resolve,
            patch.object(runner, "_setup_test_environment", return_value=None),
            patch.object(runner, "_generate_pytest_ini", return_value=None),
            patch.object(runner, "_parse_ctrf_report", return_value=[]),
            patch.object(
                runner, "_build_pytest_command", side_effect=_capture_assets
            ),
        ):
            mock_snapshot_cls.from_directory.return_value = Mock()
            mock_workspace_cls.return_value = workspace
            mock_session_cls.return_value = session
            mock_resolve.return_value = resolved_assets

            runner.run()

        assert captured_assets["stopwords"] == "/static/static/stopwords.txt"
        _, kwargs = mock_session_cls.call_args
        assert kwargs["static_assets"] == resolved_assets

    def test_run_passes_host_asset_paths_for_local(
        self,
        mock_problem_config,
        mock_checkpoint_config,
        mock_environment,
        tmp_path,
    ):
        """run() uses host paths for static assets in local runs."""
        from unittest.mock import MagicMock, patch

        submission_path = tmp_path / "submission"
        submission_path.mkdir()

        mock_environment.type = "local"

        resolved_asset = Mock()
        resolved_asset.absolute_path = Path("/host/stopwords.txt")
        resolved_asset.save_path = Path("static/stopwords.txt")
        resolved_assets = {"stopwords": resolved_asset}

        captured_assets: dict[str, str] = {}

        def _capture_assets(
            _test_files: list[str],
            static_assets: dict[str, str],
        ) -> str:
            captured_assets.update(static_assets)
            return "pytest"

        exec_result = Mock()
        exec_result.exit_code = 0
        exec_result.stdout = "collected 1 item"
        exec_result.stderr = ""
        exec_result.elapsed = 0.1

        runtime = MagicMock()
        runtime.execute.return_value = exec_result

        session = MagicMock()
        session.spawn.return_value = runtime

        workspace = MagicMock()
        workspace.working_dir = submission_path

        runner = PytestRunner(
            problem=mock_problem_config,
            checkpoint=mock_checkpoint_config,
            environment=mock_environment,
            submission_path=submission_path,
        )

        with (
            patch(
                "slop_code.evaluation.pytest_runner.Snapshot"
            ) as mock_snapshot_cls,
            patch(
                "slop_code.evaluation.pytest_runner.Workspace"
            ) as mock_workspace_cls,
            patch(
                "slop_code.evaluation.pytest_runner.Session"
            ) as mock_session_cls,
            patch(
                "slop_code.evaluation.pytest_runner.resolve_static_assets"
            ) as mock_resolve,
            patch.object(runner, "_setup_test_environment", return_value=None),
            patch.object(runner, "_generate_pytest_ini", return_value=None),
            patch.object(runner, "_parse_ctrf_report", return_value=[]),
            patch.object(
                runner, "_build_pytest_command", side_effect=_capture_assets
            ),
        ):
            mock_snapshot_cls.from_directory.return_value = Mock()
            mock_workspace_cls.return_value = workspace
            mock_session_cls.return_value = session
            mock_resolve.return_value = resolved_assets

            runner.run()

        assert captured_assets["stopwords"] == "/host/stopwords.txt"
        _, kwargs = mock_session_cls.call_args
        assert kwargs["static_assets"] == resolved_assets

    def test_run_handles_infrastructure_failure(
        self,
        mock_problem_config,
        mock_checkpoint_config,
        mock_environment,
        tmp_path,
    ):
        """run() correctly detects infrastructure failures."""
        from unittest.mock import MagicMock, patch

        # Create submission directory with tests
        submission_path = tmp_path / "submission"
        submission_path.mkdir()
        tests_dir = submission_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "pyproject.toml").write_text("[project]\nname = 'tests'\n")

        # Mock execution results - uv add succeeds, pytest has infra failure
        mock_uv_result = Mock()
        mock_uv_result.exit_code = 0
        mock_uv_result.stdout = "Resolved 4 packages"
        mock_uv_result.stderr = ""
        mock_uv_result.elapsed = 0.5

        mock_pytest_result = Mock()
        mock_pytest_result.exit_code = 5  # EXIT_NOTESTSCOLLECTED
        mock_pytest_result.stdout = "ERROR: no tests collected"
        mock_pytest_result.stderr = ""
        mock_pytest_result.elapsed = 0.5

        mock_runtime = MagicMock()
        mock_runtime.execute.side_effect = [mock_uv_result, mock_pytest_result]

        mock_session = MagicMock()
        mock_session.spawn.return_value = mock_runtime

        mock_workspace = MagicMock()
        mock_workspace.working_dir = submission_path

        runner = PytestRunner(
            problem=mock_problem_config,
            checkpoint=mock_checkpoint_config,
            environment=mock_environment,
            submission_path=submission_path,
        )

        with (
            patch(
                "slop_code.evaluation.pytest_runner.Snapshot"
            ) as mock_snapshot_cls,
            patch(
                "slop_code.evaluation.pytest_runner.Workspace"
            ) as mock_workspace_cls,
            patch(
                "slop_code.evaluation.pytest_runner.Session"
            ) as mock_session_cls,
            patch(
                "slop_code.evaluation.pytest_runner.resolve_static_assets"
            ) as mock_resolve,
        ):
            mock_snapshot_cls.from_directory.return_value = Mock()
            mock_workspace_cls.return_value = mock_workspace
            mock_session_cls.return_value = mock_session
            mock_resolve.return_value = {}

            # Create empty CTRF report directory
            scbench_dir = submission_path / ".scbench"
            scbench_dir.mkdir()
            (scbench_dir / "ctrf-report.json").write_text('{"results": {"tests": []}}')

            results = runner.run()

        # Verify infrastructure failure detection
        assert results.infrastructure_failure is True
        assert results.pytest_exit_code == 5
        assert results.pytest_collected == 0

    def test_run_handles_test_failures(
        self,
        mock_problem_config,
        mock_checkpoint_config,
        mock_environment,
        tmp_path,
    ):
        """run() correctly handles test failures (not infrastructure failures)."""
        from unittest.mock import MagicMock, patch

        # Create submission directory
        submission_path = tmp_path / "submission"
        submission_path.mkdir()
        tests_dir = submission_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "pyproject.toml").write_text("[project]\nname = 'tests'\n")

        # CTRF with mix of passed and failed
        ctrf_data = {
            "results": {
                "tests": [
                    {
                        "name": "test_pass",
                        "status": "passed",
                        "duration": 100,
                        "filePath": "tests/test_checkpoint_2.py",
                        "tags": [],
                    },
                    {
                        "name": "test_fail",
                        "status": "failed",
                        "duration": 50,
                        "filePath": "tests/test_checkpoint_2.py",
                        "tags": [],
                        "message": "AssertionError: expected True",
                    },
                ]
            }
        }

        # Mock execution results - uv add succeeds, pytest has test failures
        mock_uv_result = Mock()
        mock_uv_result.exit_code = 0
        mock_uv_result.stdout = "Resolved 4 packages"
        mock_uv_result.stderr = ""
        mock_uv_result.elapsed = 0.5

        # Exit code 1 = tests ran but some failed
        mock_pytest_result = Mock()
        mock_pytest_result.exit_code = 1
        mock_pytest_result.stdout = "collected 2 items\n\n1 passed, 1 failed"
        mock_pytest_result.stderr = ""
        mock_pytest_result.elapsed = 0.8

        mock_runtime = MagicMock()
        mock_runtime.execute.side_effect = [mock_uv_result, mock_pytest_result]

        mock_session = MagicMock()
        mock_session.spawn.return_value = mock_runtime

        mock_workspace = MagicMock()
        mock_workspace.working_dir = submission_path

        runner = PytestRunner(
            problem=mock_problem_config,
            checkpoint=mock_checkpoint_config,
            environment=mock_environment,
            submission_path=submission_path,
        )

        with (
            patch(
                "slop_code.evaluation.pytest_runner.Snapshot"
            ) as mock_snapshot_cls,
            patch(
                "slop_code.evaluation.pytest_runner.Workspace"
            ) as mock_workspace_cls,
            patch(
                "slop_code.evaluation.pytest_runner.Session"
            ) as mock_session_cls,
            patch(
                "slop_code.evaluation.pytest_runner.resolve_static_assets"
            ) as mock_resolve,
        ):
            mock_snapshot_cls.from_directory.return_value = Mock()
            mock_workspace_cls.return_value = mock_workspace
            mock_session_cls.return_value = mock_session
            mock_resolve.return_value = {}

            scbench_dir = submission_path / ".scbench"
            scbench_dir.mkdir()
            (scbench_dir / "ctrf-report.json").write_text(json.dumps(ctrf_data))

            results = runner.run()

        # Test failures are NOT infrastructure failures
        assert results.infrastructure_failure is False
        assert results.pytest_exit_code == 1
        assert results.pytest_collected == 2
        assert len(results.tests) == 2

        # Check counts
        assert results.pass_counts[GroupType.CORE] == 1
        assert results.total_counts[GroupType.CORE] == 2

        # Check failure message is captured
        failed_test = [t for t in results.tests if t.status == "failed"][0]
        assert failed_test.failure_message == "AssertionError: expected True"


def docker_available() -> bool:
    """Check if Docker is available and running."""
    try:
        import docker

        client = docker.from_env()
        client.ping()
        return True
    except Exception:
        return False


@pytest.mark.skipif(
    not docker_available(),
    reason="Docker is not available or not running",
)
class TestPytestRunnerE2E:
    """End-to-end tests that require actual Docker and problem setup."""

    def test_run_against_real_problem(self):
        """Full end-to-end test against a real problem."""
        pass
