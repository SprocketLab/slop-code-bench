"""Tests for pytest_runner module."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from slop_code.common import WORKSPACE_TEST_DIR
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
    # Built-in markers (error, functionality, regression) are handled by
    # PytestRunner.BUILTIN_MARKERS. problem.markers is only for custom markers.
    problem.markers = {}
    problem.static_assets = {}
    problem.test_dependencies = []

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
    checkpoint.include_prior_tests = True
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

    def test_determine_group_type_explicit_regression_marker(self, pytest_runner):
        """Explicit regression marker in current checkpoint becomes REGRESSION."""
        group_type = pytest_runner._determine_group_type(
            test_checkpoint="checkpoint_2",  # Current checkpoint
            markers=["regression"],
            current_checkpoint="checkpoint_2",
        )
        assert group_type == GroupType.REGRESSION

    def test_generate_pytest_ini(self, pytest_runner, tmp_path):
        """_generate_pytest_ini creates valid pytest.ini with built-in markers."""
        pytest_runner._generate_pytest_ini(tmp_path)

        pytest_ini = tmp_path / "pytest.ini"
        assert pytest_ini.exists()

        content = pytest_ini.read_text()
        assert "[pytest]" in content
        assert "testpaths = tests" in content
        # Check built-in markers are registered
        assert "error:" in content
        assert "functionality:" in content
        assert "regression:" in content

    def test_build_pytest_command(self, pytest_runner):
        """_build_pytest_command builds correct command using uvx."""
        cmd = pytest_runner._build_pytest_command(timeout=30)

        # Verify uvx is used instead of uv run
        assert cmd.startswith("uvx ")
        assert "--with=pytest" in cmd
        assert "--with=pytest-json-ctrf" in cmd
        assert "--with=pytest-json-report" in cmd
        assert "--with=pytest-timeout" in cmd
        assert "--with=jsonschema" in cmd
        assert "--with=deepdiff" in cmd
        # Verify pytest is the command being run
        assert " pytest " in cmd
        assert "--timeout=30" in cmd
        # Test files are discovered via pytest.ini testpaths, not passed explicitly
        assert "test_checkpoint" not in cmd
        assert "--entrypoint=" in cmd
        assert "--checkpoint=" in cmd
        assert "checkpoint_2" in cmd
        # Static assets are now passed via env vars, not CLI
        assert "--static-assets" not in cmd
        assert "--ctrf=.scbench/ctrf-report.json" in cmd
        assert "--json-report" in cmd
        assert "--json-report-file=.scbench/pytest-report.json" in cmd
        assert "-v" in cmd

    def test_build_pytest_command_no_timeout(self, pytest_runner):
        """_build_pytest_command omits timeout flag when not provided."""
        cmd = pytest_runner._build_pytest_command()

        assert "--timeout" not in cmd

    def test_build_pytest_command_with_extra_args(self, pytest_runner):
        """_build_pytest_command includes extra pytest args."""
        cmd = pytest_runner._build_pytest_command(
            extra_args=["-k", "test_specific"],
            timeout=60,
        )

        assert cmd.startswith("uvx ")
        assert "--timeout=60" in cmd
        assert "-k" in cmd
        assert "test_specific" in cmd

    def test_build_pytest_command_includes_problem_deps(
        self, mock_problem_config, mock_checkpoint_config, mock_environment
    ):
        """_build_pytest_command includes problem test_dependencies."""
        mock_problem_config.test_dependencies = ["httpx", "pytest-asyncio"]
        runner = PytestRunner(
            problem=mock_problem_config,
            checkpoint=mock_checkpoint_config,
            environment=mock_environment,
            submission_path=Path("/tmp/test"),
        )

        cmd = runner._build_pytest_command()

        assert "--with=httpx" in cmd
        assert "--with=pytest-asyncio" in cmd
        # Base deps still included
        assert "--with=pytest" in cmd
        assert "--with=pytest-json-ctrf" in cmd

    def test_build_pytest_command_no_problem_deps(
        self, mock_problem_config, mock_checkpoint_config, mock_environment
    ):
        """Empty test_dependencies should not add extra --with flags."""
        mock_problem_config.test_dependencies = []
        runner = PytestRunner(
            problem=mock_problem_config,
            checkpoint=mock_checkpoint_config,
            environment=mock_environment,
            submission_path=Path("/tmp/test"),
        )

        cmd = runner._build_pytest_command()

        # Only base deps
        assert cmd.count("--with=") == len(PytestRunner.TEST_DEPENDENCIES)

    def test_build_pytest_command_default_deps(
        self, mock_problem_config, mock_checkpoint_config, mock_environment
    ):
        """Missing test_dependencies field should default to empty list."""
        mock_problem_config.test_dependencies = None
        runner = PytestRunner(
            problem=mock_problem_config,
            checkpoint=mock_checkpoint_config,
            environment=mock_environment,
            submission_path=Path("/tmp/test"),
        )

        cmd = runner._build_pytest_command()

        # Should work without error, only base deps
        assert "--with=pytest" in cmd

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

        tests, report_data = pytest_runner._parse_ctrf_report(ctrf_file)

        assert len(tests) == 2
        assert tests[0]["name"] == "test_1"
        assert tests[1]["name"] == "test_2"
        assert report_data == ctrf_data

    def test_parse_pytest_json_report_valid(
        self, pytest_runner, tmp_path
    ):
        """_parse_pytest_json_report parses valid JSON."""
        report_data = {
            "tests": [
                {
                    "nodeid": "tests/test_checkpoint_1.py::test_failure",
                    "call": {
                        "outcome": "failed",
                        "longreprtext": "AssertionError: diff",
                    },
                }
            ]
        }
        report_path = tmp_path / "pytest-report.json"
        report_path.write_text(json.dumps(report_data))

        loaded = pytest_runner._parse_pytest_json_report(report_path)

        assert loaded == report_data

    def test_augment_ctrf_with_failures(self, pytest_runner):
        """Augment CTRF failures with pytest-json-report details."""
        ctrf_tests = [
            {
                "name": "test_failure",
                "status": "failed",
                "filePath": "tests/test_checkpoint_1.py",
            }
        ]
        report_data = {
            "tests": [
                {
                    "nodeid": "tests/test_checkpoint_1.py::test_failure",
                    "call": {
                        "outcome": "failed",
                        "longreprtext": "AssertionError: diff",
                    },
                }
            ]
        }

        failure_index = pytest_runner._build_failure_index(report_data)
        pytest_runner._augment_ctrf_with_failures(ctrf_tests, failure_index)

        assert ctrf_tests[0]["message"] == "AssertionError: diff"

    def test_parse_ctrf_report_missing_file(self, pytest_runner, tmp_path):
        """_parse_ctrf_report returns empty list if file missing."""
        missing_file = tmp_path / "nonexistent.json"
        tests, report_data = pytest_runner._parse_ctrf_report(missing_file)

        assert tests == []
        assert report_data is None

    def test_parse_ctrf_report_invalid_json(self, pytest_runner, tmp_path):
        """_parse_ctrf_report returns empty list for invalid JSON."""
        invalid_file = tmp_path / "invalid.json"
        invalid_file.write_text("not valid json {{{")

        tests, report_data = pytest_runner._parse_ctrf_report(invalid_file)

        assert tests == []
        assert report_data is None

    def test_parse_ctrf_report_missing_tests_key(self, pytest_runner, tmp_path):
        """_parse_ctrf_report returns empty list if tests key missing."""
        ctrf_data = {"results": {"tool": {"name": "pytest"}}}

        ctrf_file = tmp_path / "report.json"
        ctrf_file.write_text(json.dumps(ctrf_data))

        tests, report_data = pytest_runner._parse_ctrf_report(ctrf_file)

        assert tests == []
        assert report_data == ctrf_data

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

    def test_convert_ctrf_test_parametrized_single_param(self, pytest_runner):
        """Parametrized test with single parameter is parsed correctly."""
        ctrf_test = {
            "name": "test_calculation[1]",
            "status": "passed",
            "duration": 100,
            "filePath": "tests/test_checkpoint_2.py",
            "tags": [],
        }

        result = pytest_runner._convert_ctrf_test_to_result(ctrf_test)

        assert result.id == "test_calculation[1]"
        assert result.status == "passed"
        assert result.checkpoint == "checkpoint_2"
        assert result.file_path == "tests/test_checkpoint_2.py"

    def test_convert_ctrf_test_parametrized_multiple_params(self, pytest_runner):
        """Parametrized test with multiple parameters is parsed correctly."""
        ctrf_test = {
            "name": "test_func[param1-param2-param3]",
            "status": "failed",
            "duration": 50,
            "filePath": "tests/test_checkpoint_2.py",
            "tags": ["functionality"],
            "message": "AssertionError",
        }

        result = pytest_runner._convert_ctrf_test_to_result(ctrf_test)

        assert result.id == "test_func[param1-param2-param3]"
        assert result.status == "failed"
        assert result.checkpoint == "checkpoint_2"
        assert result.markers == ["functionality"]
        assert result.failure_message == "AssertionError"

    def test_convert_ctrf_test_parametrized_with_special_chars(self, pytest_runner):
        """Parametrized test with special chars in params (=, _) is parsed correctly."""
        ctrf_test = {
            "name": "test_func[range=5_reduction=90]",
            "status": "passed",
            "duration": 75,
            "filePath": "tests/test_checkpoint_1.py",
            "tags": [],
        }

        result = pytest_runner._convert_ctrf_test_to_result(ctrf_test)

        assert result.id == "test_func[range=5_reduction=90]"
        assert result.checkpoint == "checkpoint_1"
        assert result.group_type == GroupType.REGRESSION  # Prior checkpoint

    def test_convert_ctrf_test_parametrized_with_nodeid_format(self, pytest_runner):
        """Parametrized test with full nodeid format is parsed correctly."""
        ctrf_test = {
            "name": "tests/test_checkpoint_2.py::TestClass::test_method[case1]",
            "status": "passed",
            "duration": 100,
            "filePath": "",  # Empty filePath, should extract from name
            "tags": [],
        }

        result = pytest_runner._convert_ctrf_test_to_result(ctrf_test)

        assert result.id == "tests/test_checkpoint_2.py::TestClass::test_method[case1]"
        assert result.file_path == "tests/test_checkpoint_2.py"
        assert result.checkpoint == "checkpoint_2"


class TestParametrizedFailureLookup:
    """Tests for failure message lookup with parametrized tests."""

    def test_lookup_failure_message_parametrized_exact_match(self, pytest_runner):
        """Failure message found for specific parametrized variant via exact match."""
        failure_index = {
            "tests/test_checkpoint_1.py::test_func[case1]": "Error for case1",
            "tests/test_checkpoint_1.py::test_func[case2]": "Error for case2",
        }
        test_data = {
            "name": "test_func[case2]",
            "filePath": "tests/test_checkpoint_1.py",
        }

        message = pytest_runner._lookup_failure_message(test_data, failure_index)

        assert message == "Error for case2"

    def test_lookup_failure_message_parametrized_all_variants(self, pytest_runner):
        """Each parametrized variant gets its own failure message."""
        failure_index = {
            "tests/test_checkpoint_2.py::test_calc[1]": "Failed with input 1",
            "tests/test_checkpoint_2.py::test_calc[2]": "Failed with input 2",
            "tests/test_checkpoint_2.py::test_calc[3]": "Failed with input 3",
        }

        for i in range(1, 4):
            test_data = {
                "name": f"test_calc[{i}]",
                "filePath": "tests/test_checkpoint_2.py",
            }
            message = pytest_runner._lookup_failure_message(test_data, failure_index)
            assert message == f"Failed with input {i}"

    def test_lookup_failure_message_parametrized_with_special_ids(self, pytest_runner):
        """Failure lookup works with complex parameter IDs."""
        failure_index = {
            "tests/test_checkpoint_1.py::test_route[range=5_reduction=90]": "Route failed",
        }
        test_data = {
            "name": "test_route[range=5_reduction=90]",
            "filePath": "tests/test_checkpoint_1.py",
        }

        message = pytest_runner._lookup_failure_message(test_data, failure_index)

        assert message == "Route failed"

    def test_build_failure_index_with_parametrized_tests(self, pytest_runner):
        """_build_failure_index correctly indexes parametrized test failures."""
        report_data = {
            "tests": [
                {
                    "nodeid": "tests/test_checkpoint_1.py::test_func[case1]",
                    "call": {"outcome": "passed"},
                },
                {
                    "nodeid": "tests/test_checkpoint_1.py::test_func[case2]",
                    "call": {"outcome": "failed", "longreprtext": "case2 failed"},
                },
                {
                    "nodeid": "tests/test_checkpoint_1.py::test_func[case3]",
                    "call": {"outcome": "failed", "longreprtext": "case3 failed"},
                },
            ]
        }

        failure_index = pytest_runner._build_failure_index(report_data)

        # Only failed tests should be in the index
        assert len(failure_index) == 2
        assert "tests/test_checkpoint_1.py::test_func[case2]" in failure_index
        assert "tests/test_checkpoint_1.py::test_func[case3]" in failure_index
        assert failure_index["tests/test_checkpoint_1.py::test_func[case2]"] == "case2 failed"
        assert failure_index["tests/test_checkpoint_1.py::test_func[case3]"] == "case3 failed"


class TestParametrizedAugmentation:
    """Tests for augmenting CTRF with failures for parametrized tests."""

    def test_augment_ctrf_with_failures_parametrized(self, pytest_runner):
        """Parametrized test failures get correct messages from pytest-json-report."""
        ctrf_tests = [
            {
                "name": "test_func[case1]",
                "status": "passed",
                "filePath": "tests/test_checkpoint_1.py",
            },
            {
                "name": "test_func[case2]",
                "status": "failed",
                "filePath": "tests/test_checkpoint_1.py",
            },
            {
                "name": "test_func[case3]",
                "status": "passed",
                "filePath": "tests/test_checkpoint_1.py",
            },
        ]
        failure_index = {
            "tests/test_checkpoint_1.py::test_func[case2]": "AssertionError: case2 wrong",
        }

        pytest_runner._augment_ctrf_with_failures(ctrf_tests, failure_index)

        # Only case2 should have a message
        assert ctrf_tests[0].get("message") is None
        assert ctrf_tests[1]["message"] == "AssertionError: case2 wrong"
        assert ctrf_tests[2].get("message") is None

    def test_augment_ctrf_with_failures_multiple_parametrized_failures(self, pytest_runner):
        """Multiple parametrized test failures each get their own message."""
        ctrf_tests = [
            {
                "name": "test_calc[1]",
                "status": "failed",
                "filePath": "tests/test_checkpoint_2.py",
            },
            {
                "name": "test_calc[2]",
                "status": "failed",
                "filePath": "tests/test_checkpoint_2.py",
            },
        ]
        failure_index = {
            "tests/test_checkpoint_2.py::test_calc[1]": "Error: 1 is wrong",
            "tests/test_checkpoint_2.py::test_calc[2]": "Error: 2 is wrong",
        }

        pytest_runner._augment_ctrf_with_failures(ctrf_tests, failure_index)

        assert ctrf_tests[0]["message"] == "Error: 1 is wrong"
        assert ctrf_tests[1]["message"] == "Error: 2 is wrong"


class TestPytestJsonReportConversion:
    """Tests for pytest-json-report to TestResult conversion."""

    def test_convert_pytest_report_test_basic(self, pytest_runner):
        """Basic pytest-json-report test entry is converted correctly."""
        test_data = {
            "nodeid": "tests/test_checkpoint_2.py::test_example",
            "outcome": "passed",
            "keywords": ["test_example", "TestClass"],
            "setup": {"duration": 0.001, "outcome": "passed"},
            "call": {"duration": 0.120, "outcome": "passed"},
            "teardown": {"duration": 0.002, "outcome": "passed"},
        }

        result = pytest_runner._convert_pytest_report_test_to_result(test_data)

        assert result.id == "test_example"
        assert result.status == "passed"
        assert result.file_path == "tests/test_checkpoint_2.py"
        assert result.checkpoint == "checkpoint_2"
        assert result.duration_ms == 123.0  # Sum of setup + call + teardown

    def test_convert_pytest_report_test_parametrized(self, pytest_runner):
        """Parametrized test with [param] in nodeid is converted correctly."""
        test_data = {
            "nodeid": "tests/test_checkpoint_2.py::test_calculation[input=1]",
            "outcome": "passed",
            "keywords": ["test_calculation", "parametrize"],
            "call": {"duration": 0.05, "outcome": "passed"},
        }

        result = pytest_runner._convert_pytest_report_test_to_result(test_data)

        assert result.id == "test_calculation[input=1]"
        assert result.status == "passed"
        assert result.checkpoint == "checkpoint_2"

    def test_convert_pytest_report_test_failed_with_message(self, pytest_runner):
        """Failed test extracts failure message from call phase."""
        test_data = {
            "nodeid": "tests/test_checkpoint_2.py::test_fail",
            "outcome": "failed",
            "keywords": [],
            "call": {
                "duration": 0.1,
                "outcome": "failed",
                "longreprtext": "AssertionError: expected 5, got 3",
            },
        }

        result = pytest_runner._convert_pytest_report_test_to_result(test_data)

        assert result.status == "failed"
        assert result.failure_message == "AssertionError: expected 5, got 3"

    def test_convert_pytest_report_test_with_markers(self, pytest_runner):
        """Test with known markers extracts them correctly."""
        test_data = {
            "nodeid": "tests/test_checkpoint_2.py::test_optional",
            "outcome": "passed",
            "keywords": ["test_optional", "functionality", "some_other_keyword"],
            "call": {"duration": 0.05, "outcome": "passed"},
        }

        result = pytest_runner._convert_pytest_report_test_to_result(test_data)

        # Only known markers (from problem.markers) should be extracted
        assert "functionality" in result.markers
        assert result.group_type == GroupType.FUNCTIONALITY

    def test_convert_pytest_report_test_regression(self, pytest_runner):
        """Test from prior checkpoint is marked as regression."""
        test_data = {
            "nodeid": "tests/test_checkpoint_1.py::test_old",
            "outcome": "passed",
            "keywords": [],
            "call": {"duration": 0.03, "outcome": "passed"},
        }

        result = pytest_runner._convert_pytest_report_test_to_result(test_data)

        assert result.checkpoint == "checkpoint_1"
        assert result.group_type == GroupType.REGRESSION

    def test_convert_pytest_report_test_skipped(self, pytest_runner):
        """Skipped test is converted with correct status."""
        test_data = {
            "nodeid": "tests/test_checkpoint_2.py::test_skip",
            "outcome": "skipped",
            "keywords": [],
            "setup": {"duration": 0.001, "outcome": "skipped"},
        }

        result = pytest_runner._convert_pytest_report_test_to_result(test_data)

        assert result.status == "skipped"

    def test_convert_pytest_report_test_xfailed(self, pytest_runner):
        """Expected failure (xfail) is converted to skipped."""
        test_data = {
            "nodeid": "tests/test_checkpoint_2.py::test_xfail",
            "outcome": "xfailed",
            "keywords": [],
            "call": {"duration": 0.01, "outcome": "xfailed"},
        }

        result = pytest_runner._convert_pytest_report_test_to_result(test_data)

        assert result.status == "skipped"

    def test_parse_pytest_report_tests_valid(self, pytest_runner):
        """_parse_pytest_report_tests extracts test entries."""
        report_data = {
            "tests": [
                {"nodeid": "test1", "outcome": "passed"},
                {"nodeid": "test2", "outcome": "failed"},
            ]
        }

        tests = pytest_runner._parse_pytest_report_tests(report_data)

        assert len(tests) == 2
        assert tests[0]["nodeid"] == "test1"
        assert tests[1]["nodeid"] == "test2"

    def test_parse_pytest_report_tests_empty(self, pytest_runner):
        """_parse_pytest_report_tests returns empty list for empty report."""
        assert pytest_runner._parse_pytest_report_tests(None) == []
        assert pytest_runner._parse_pytest_report_tests({}) == []
        assert pytest_runner._parse_pytest_report_tests({"tests": []}) == []

    def test_parse_pytest_report_tests_invalid_format(self, pytest_runner):
        """_parse_pytest_report_tests handles invalid tests field."""
        report_data = {"tests": "not a list"}

        tests = pytest_runner._parse_pytest_report_tests(report_data)

        assert tests == []


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
        from unittest.mock import MagicMock
        from unittest.mock import patch

        # Create a mock submission directory with tests/ subdirectory
        submission_path = tmp_path / "submission"
        submission_path.mkdir()
        tests_dir = submission_path / WORKSPACE_TEST_DIR
        tests_dir.mkdir()
        # Create a test file (no pyproject.toml needed with uvx)
        (tests_dir / "test_checkpoint_1.py").write_text("# test file")

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

        # Create mock execution result for pytest (only one call now with uvx)
        mock_pytest_result = Mock()
        mock_pytest_result.exit_code = 0
        mock_pytest_result.stdout = "collected 3 items\n\nall tests passed"
        mock_pytest_result.stderr = ""
        mock_pytest_result.elapsed = 1.5

        # Create mock runtime that returns pytest result
        mock_runtime = MagicMock()
        mock_runtime.execute.return_value = mock_pytest_result

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

        # Patch the dependencies - use Session.from_environment_spec factory
        mock_session.workspace = mock_workspace

        with (
            patch(
                "slop_code.evaluation.pytest_runner.Session"
            ) as mock_session_cls,
            patch(
                "slop_code.evaluation.pytest_runner.resolve_static_assets"
            ) as mock_resolve,
        ):
            mock_session_cls.from_environment_spec.return_value = mock_session
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

    def test_run_materializes_static_assets_and_passes_env_vars(
        self,
        mock_problem_config,
        mock_checkpoint_config,
        mock_environment,
        tmp_path,
    ):
        """run() materializes static assets and passes paths via env vars."""
        from unittest.mock import MagicMock
        from unittest.mock import patch

        submission_path = tmp_path / "submission"
        submission_path.mkdir()

        mock_environment.type = "docker"

        resolved_asset = Mock()
        resolved_asset.absolute_path = Path("/host/stopwords.txt")
        resolved_asset.save_path = Path("static/stopwords.txt")
        resolved_assets = {"stopwords": resolved_asset}

        # Mock materialized asset paths
        materialized_assets = {
            "stopwords": submission_path / WORKSPACE_TEST_DIR / "assets" / "stopwords"
        }

        exec_result = Mock()
        exec_result.exit_code = 0
        exec_result.stdout = "collected 1 item"
        exec_result.stderr = ""
        exec_result.elapsed = 0.1

        runtime = MagicMock()
        runtime.execute.return_value = exec_result

        workspace = MagicMock()
        workspace.working_dir = submission_path
        workspace.materialize_static_assets_for_tests.return_value = (
            materialized_assets
        )

        session = MagicMock()
        session.spawn.return_value = runtime
        session.workspace = workspace

        runner = PytestRunner(
            problem=mock_problem_config,
            checkpoint=mock_checkpoint_config,
            environment=mock_environment,
            submission_path=submission_path,
        )

        with (
            patch(
                "slop_code.evaluation.pytest_runner.Session"
            ) as mock_session_cls,
            patch(
                "slop_code.evaluation.pytest_runner.resolve_static_assets"
            ) as mock_resolve,
            patch.object(runner, "_copy_tests_from_problem", return_value=None),
            patch.object(runner, "_generate_pytest_ini", return_value=None),
            patch.object(runner, "_parse_ctrf_report", return_value=([], None)),
            patch.object(
                runner, "_build_pytest_command", return_value="pytest"
            ),
        ):
            mock_session_cls.from_environment_spec.return_value = session
            mock_resolve.return_value = resolved_assets

            runner.run()

        # Verify materialize_static_assets_for_tests was called
        workspace.materialize_static_assets_for_tests.assert_called_once()

        # Verify env vars were passed to execute
        execute_call = runtime.execute.call_args
        env_passed = execute_call[0][1]  # Second positional arg is env dict
        assert "SCBENCH_ASSETS_DIR" in env_passed
        assert "SCBENCH_ASSET_STOPWORDS" in env_passed
        # Env vars use relative paths for Docker container compatibility
        assert env_passed["SCBENCH_ASSET_STOPWORDS"] == f"{WORKSPACE_TEST_DIR}/assets/stopwords"

        # Verify session was created with resolved assets
        _, kwargs = mock_session_cls.from_environment_spec.call_args
        assert kwargs["static_assets"] == resolved_assets

    def test_run_handles_infrastructure_failure(
        self,
        mock_problem_config,
        mock_checkpoint_config,
        mock_environment,
        tmp_path,
    ):
        """run() correctly detects infrastructure failures."""
        from unittest.mock import MagicMock
        from unittest.mock import patch

        # Create submission directory with tests
        submission_path = tmp_path / "submission"
        submission_path.mkdir()
        tests_dir = submission_path / WORKSPACE_TEST_DIR
        tests_dir.mkdir()
        # Create a test file (no pyproject.toml needed with uvx)
        (tests_dir / "test_checkpoint_1.py").write_text("# test file")

        # Mock execution result - pytest has infra failure (only one call with uvx)
        mock_pytest_result = Mock()
        mock_pytest_result.exit_code = 5  # EXIT_NOTESTSCOLLECTED
        mock_pytest_result.stdout = "ERROR: no tests collected"
        mock_pytest_result.stderr = ""
        mock_pytest_result.elapsed = 0.5

        mock_runtime = MagicMock()
        mock_runtime.execute.return_value = mock_pytest_result

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

        mock_session.workspace = mock_workspace

        with (
            patch(
                "slop_code.evaluation.pytest_runner.Session"
            ) as mock_session_cls,
            patch(
                "slop_code.evaluation.pytest_runner.resolve_static_assets"
            ) as mock_resolve,
        ):
            mock_session_cls.from_environment_spec.return_value = mock_session
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
        from unittest.mock import MagicMock
        from unittest.mock import patch

        # Create submission directory
        submission_path = tmp_path / "submission"
        submission_path.mkdir()
        tests_dir = submission_path / WORKSPACE_TEST_DIR
        tests_dir.mkdir()
        # Create a test file (no pyproject.toml needed with uvx)
        (tests_dir / "test_checkpoint_1.py").write_text("# test file")

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

        # Mock execution result - pytest has test failures (only one call with uvx)
        # Exit code 1 = tests ran but some failed
        mock_pytest_result = Mock()
        mock_pytest_result.exit_code = 1
        mock_pytest_result.stdout = "collected 2 items\n\n1 passed, 1 failed"
        mock_pytest_result.stderr = ""
        mock_pytest_result.elapsed = 0.8

        mock_runtime = MagicMock()
        mock_runtime.execute.return_value = mock_pytest_result

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

        mock_session.workspace = mock_workspace

        with (
            patch(
                "slop_code.evaluation.pytest_runner.Session"
            ) as mock_session_cls,
            patch(
                "slop_code.evaluation.pytest_runner.resolve_static_assets"
            ) as mock_resolve,
        ):
            mock_session_cls.from_environment_spec.return_value = mock_session
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

    def test_run_with_parametrized_tests(
        self,
        mock_problem_config,
        mock_checkpoint_config,
        mock_environment,
        tmp_path,
    ):
        """run() correctly handles CTRF with multiple parametrized test variants."""
        from unittest.mock import MagicMock
        from unittest.mock import patch

        # Create submission directory
        submission_path = tmp_path / "submission"
        submission_path.mkdir()
        tests_dir = submission_path / WORKSPACE_TEST_DIR
        tests_dir.mkdir()
        (tests_dir / "test_checkpoint_1.py").write_text("# test file")

        # CTRF with parametrized test variants - 3 variants, 2 pass, 1 fails
        ctrf_data = {
            "results": {
                "tool": {"name": "pytest"},
                "tests": [
                    {
                        "name": "test_calculation[input=1]",
                        "status": "passed",
                        "duration": 100,
                        "filePath": "tests/test_checkpoint_2.py",
                        "tags": [],
                    },
                    {
                        "name": "test_calculation[input=2]",
                        "status": "failed",
                        "duration": 50,
                        "filePath": "tests/test_checkpoint_2.py",
                        "tags": [],
                        "message": "AssertionError: input=2 failed",
                    },
                    {
                        "name": "test_calculation[input=3]",
                        "status": "passed",
                        "duration": 75,
                        "filePath": "tests/test_checkpoint_2.py",
                        "tags": [],
                    },
                    # Also include a regression test from checkpoint_1
                    {
                        "name": "test_basic[case1]",
                        "status": "passed",
                        "duration": 30,
                        "filePath": "tests/test_checkpoint_1.py",
                        "tags": [],
                    },
                ],
            }
        }

        # Mock execution result
        mock_pytest_result = Mock()
        mock_pytest_result.exit_code = 1  # Some tests failed
        mock_pytest_result.stdout = "collected 4 items\n\n3 passed, 1 failed"
        mock_pytest_result.stderr = ""
        mock_pytest_result.elapsed = 0.5

        mock_runtime = MagicMock()
        mock_runtime.execute.return_value = mock_pytest_result

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

        mock_session.workspace = mock_workspace

        with (
            patch(
                "slop_code.evaluation.pytest_runner.Session"
            ) as mock_session_cls,
            patch(
                "slop_code.evaluation.pytest_runner.resolve_static_assets"
            ) as mock_resolve,
        ):
            mock_session_cls.from_environment_spec.return_value = mock_session
            mock_resolve.return_value = {}

            scbench_dir = submission_path / ".scbench"
            scbench_dir.mkdir()
            (scbench_dir / "ctrf-report.json").write_text(json.dumps(ctrf_data))

            results = runner.run()

        # Verify all 4 parametrized variants are counted as separate tests
        assert len(results.tests) == 4
        assert results.pytest_collected == 4

        # Verify correct pass/fail counts
        # 3 tests from checkpoint_2 (current): 2 passed, 1 failed - all CORE
        assert results.total_counts[GroupType.CORE] == 3
        assert results.pass_counts[GroupType.CORE] == 2

        # 1 test from checkpoint_1 (prior): passed - REGRESSION
        assert results.total_counts[GroupType.REGRESSION] == 1
        assert results.pass_counts[GroupType.REGRESSION] == 1

        # Verify each parametrized variant has correct ID
        test_ids = [t.id for t in results.tests]
        assert "test_calculation[input=1]" in test_ids
        assert "test_calculation[input=2]" in test_ids
        assert "test_calculation[input=3]" in test_ids
        assert "test_basic[case1]" in test_ids

        # Verify failure message is captured for the failed variant
        failed_tests = [t for t in results.tests if t.status == "failed"]
        assert len(failed_tests) == 1
        assert failed_tests[0].id == "test_calculation[input=2]"
        assert failed_tests[0].failure_message == "AssertionError: input=2 failed"


def docker_available() -> bool:
    """Check if Docker is available and running."""
    try:
        import docker

        client = docker.from_env()
        client.ping()
        return True
    except Exception:
        return False


class TestCopyTestsFromProblem:
    """Regression tests for copying tests from problem directory to workspace."""

    def test_copies_tests_when_workspace_has_none(
        self,
        mock_problem_config,
        mock_checkpoint_config,
        mock_environment,
        tmp_path,
    ):
        """Tests are copied from problem dir when workspace has no tests."""
        # Create problem directory with tests
        problem_path = tmp_path / "problem"
        problem_path.mkdir()
        problem_tests = problem_path / "tests"
        problem_tests.mkdir()
        (problem_tests / "test_checkpoint_1.py").write_text("# test file")
        (problem_tests / "conftest.py").write_text("# conftest")

        # Create workspace without tests
        workspace_path = tmp_path / "workspace"
        workspace_path.mkdir()

        mock_problem_config.path = problem_path

        runner = PytestRunner(
            problem=mock_problem_config,
            checkpoint=mock_checkpoint_config,
            environment=mock_environment,
            submission_path=workspace_path,
        )

        # Call the method directly
        runner._copy_tests_from_problem(workspace_path)

        # Verify tests were copied
        assert (workspace_path / WORKSPACE_TEST_DIR).exists()
        assert (workspace_path / WORKSPACE_TEST_DIR / "test_checkpoint_1.py").exists()
        assert (workspace_path / WORKSPACE_TEST_DIR / "conftest.py").exists()

    def test_does_not_overwrite_existing_tests(
        self,
        mock_problem_config,
        mock_checkpoint_config,
        mock_environment,
        tmp_path,
    ):
        """Existing workspace tests are NOT overwritten."""
        # Create problem directory with tests
        problem_path = tmp_path / "problem"
        problem_path.mkdir()
        problem_tests = problem_path / "tests"
        problem_tests.mkdir()
        (problem_tests / "test_checkpoint_1.py").write_text("# problem test")

        # Create workspace WITH existing tests
        workspace_path = tmp_path / "workspace"
        workspace_path.mkdir()
        workspace_tests = workspace_path / WORKSPACE_TEST_DIR
        workspace_tests.mkdir()
        (workspace_tests / "test_checkpoint_1.py").write_text("# workspace test")

        mock_problem_config.path = problem_path

        runner = PytestRunner(
            problem=mock_problem_config,
            checkpoint=mock_checkpoint_config,
            environment=mock_environment,
            submission_path=workspace_path,
        )

        # Call the method directly
        runner._copy_tests_from_problem(workspace_path)

        # Verify workspace tests were NOT overwritten
        content = (workspace_tests / "test_checkpoint_1.py").read_text()
        assert content == "# workspace test"

    def test_raises_error_when_no_tests_anywhere(
        self,
        mock_problem_config,
        mock_checkpoint_config,
        mock_environment,
        tmp_path,
    ):
        """RuntimeError raised when neither workspace nor problem has tests."""
        # Create problem directory WITHOUT tests
        problem_path = tmp_path / "problem"
        problem_path.mkdir()

        # Create workspace without tests
        workspace_path = tmp_path / "workspace"
        workspace_path.mkdir()

        mock_problem_config.path = problem_path

        runner = PytestRunner(
            problem=mock_problem_config,
            checkpoint=mock_checkpoint_config,
            environment=mock_environment,
            submission_path=workspace_path,
        )

        # Should raise RuntimeError
        with pytest.raises(RuntimeError, match="No tests directory found"):
            runner._copy_tests_from_problem(workspace_path)

    def test_copies_only_checkpoints_up_to_current(
        self,
        mock_problem_config,
        mock_environment,
        tmp_path,
    ):
        """Only test files for checkpoints 0..N are copied."""
        # Create problem directory with tests for all checkpoints
        problem_path = tmp_path / "problem"
        problem_path.mkdir()
        problem_tests = problem_path / "tests"
        problem_tests.mkdir()
        (problem_tests / "conftest.py").write_text("# conftest")
        (problem_tests / "test_checkpoint_1.py").write_text("# test 1")
        (problem_tests / "test_checkpoint_2.py").write_text("# test 2")
        (problem_tests / "test_checkpoint_3.py").write_text("# test 3")

        # Create workspace without tests
        workspace_path = tmp_path / "workspace"
        workspace_path.mkdir()

        mock_problem_config.path = problem_path

        # Checkpoint is checkpoint_2, so only checkpoint_1 and checkpoint_2 should be copied
        checkpoint = Mock()
        checkpoint.name = "checkpoint_2"
        checkpoint.timeout = 30
        checkpoint.env = {}

        runner = PytestRunner(
            problem=mock_problem_config,
            checkpoint=checkpoint,
            environment=mock_environment,
            submission_path=workspace_path,
        )

        runner._copy_tests_from_problem(workspace_path)

        # Verify only checkpoints 1 and 2 were copied
        assert (workspace_path / WORKSPACE_TEST_DIR).exists()
        assert (workspace_path / WORKSPACE_TEST_DIR / "conftest.py").exists()
        assert (workspace_path / WORKSPACE_TEST_DIR / "test_checkpoint_1.py").exists()
        assert (workspace_path / WORKSPACE_TEST_DIR / "test_checkpoint_2.py").exists()
        # checkpoint_3 should NOT be copied
        assert not (workspace_path / WORKSPACE_TEST_DIR / "test_checkpoint_3.py").exists()

    def test_copies_non_checkpoint_test_files(
        self,
        mock_problem_config,
        mock_checkpoint_config,
        mock_environment,
        tmp_path,
    ):
        """Non-checkpoint test files (helpers, utilities) are copied."""
        problem_path = tmp_path / "problem"
        problem_path.mkdir()
        problem_tests = problem_path / "tests"
        problem_tests.mkdir()
        (problem_tests / "conftest.py").write_text("# conftest")
        (problem_tests / "test_checkpoint_1.py").write_text("# test 1")
        (problem_tests / "test_checkpoint_2.py").write_text("# test 2")
        (problem_tests / "helpers.py").write_text("# helper module")
        (problem_tests / "__init__.py").write_text("# init")

        workspace_path = tmp_path / "workspace"
        workspace_path.mkdir()

        mock_problem_config.path = problem_path

        runner = PytestRunner(
            problem=mock_problem_config,
            checkpoint=mock_checkpoint_config,
            environment=mock_environment,
            submission_path=workspace_path,
        )

        runner._copy_tests_from_problem(workspace_path)

        # Verify non-checkpoint files are copied
        assert (workspace_path / WORKSPACE_TEST_DIR / "helpers.py").exists()
        assert (workspace_path / WORKSPACE_TEST_DIR / "__init__.py").exists()

    def test_copies_subdirectories(
        self,
        mock_problem_config,
        mock_checkpoint_config,
        mock_environment,
        tmp_path,
    ):
        """Subdirectories in tests/ are fully copied."""
        problem_path = tmp_path / "problem"
        problem_path.mkdir()
        problem_tests = problem_path / "tests"
        problem_tests.mkdir()
        (problem_tests / "test_checkpoint_1.py").write_text("# test 1")
        (problem_tests / "test_checkpoint_2.py").write_text("# test 2")

        # Create fixtures subdirectory
        fixtures_dir = problem_tests / "fixtures"
        fixtures_dir.mkdir()
        (fixtures_dir / "data.json").write_text('{"key": "value"}')

        workspace_path = tmp_path / "workspace"
        workspace_path.mkdir()

        mock_problem_config.path = problem_path

        runner = PytestRunner(
            problem=mock_problem_config,
            checkpoint=mock_checkpoint_config,
            environment=mock_environment,
            submission_path=workspace_path,
        )

        runner._copy_tests_from_problem(workspace_path)

        # Verify subdirectory was copied
        assert (workspace_path / WORKSPACE_TEST_DIR / "fixtures").exists()
        assert (workspace_path / WORKSPACE_TEST_DIR / "fixtures" / "data.json").exists()


class TestSessionCreation:
    """Regression tests for proper Session creation (no source pollution)."""

    def test_uses_session_factory_method(
        self,
        mock_problem_config,
        mock_checkpoint_config,
        mock_environment,
        tmp_path,
    ):
        """run() uses Session.from_environment_spec() factory method."""
        from unittest.mock import MagicMock
        from unittest.mock import patch

        submission_path = tmp_path / "submission"
        submission_path.mkdir()
        tests_dir = submission_path / WORKSPACE_TEST_DIR
        tests_dir.mkdir()
        # Create a test file (no pyproject.toml needed with uvx)
        (tests_dir / "test_checkpoint_1.py").write_text("# test file")

        mock_workspace = MagicMock()
        mock_workspace.working_dir = submission_path

        mock_session = MagicMock()
        mock_session.workspace = mock_workspace

        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.stdout = "collected 0 items"
        mock_result.stderr = ""
        mock_result.elapsed = 0.1

        mock_runtime = MagicMock()
        mock_runtime.execute.return_value = mock_result
        mock_session.spawn.return_value = mock_runtime

        runner = PytestRunner(
            problem=mock_problem_config,
            checkpoint=mock_checkpoint_config,
            environment=mock_environment,
            submission_path=submission_path,
        )

        with (
            patch(
                "slop_code.evaluation.pytest_runner.Session"
            ) as mock_session_cls,
            patch(
                "slop_code.evaluation.pytest_runner.resolve_static_assets"
            ) as mock_resolve,
        ):
            mock_session_cls.from_environment_spec.return_value = mock_session
            mock_resolve.return_value = {}

            scbench_dir = submission_path / ".scbench"
            scbench_dir.mkdir()
            (scbench_dir / "ctrf-report.json").write_text('{"results": {"tests": []}}')

            runner.run()

        # Verify Session.from_environment_spec was called (not direct instantiation)
        mock_session_cls.from_environment_spec.assert_called_once()
        # Verify direct Session() was NOT called
        mock_session_cls.assert_not_called()


class TestTestMaterialization:
    """Regression tests ensuring tests are materialized to correct directory."""

    def test_tests_copied_to_workspace_not_submission_path(
        self,
        mock_problem_config,
        mock_checkpoint_config,
        mock_environment,
        tmp_path,
    ):
        """Tests are copied to workspace directory, NOT submission_path."""
        # Setup: problem has tests, we have separate submission and workspace dirs
        problem_path = tmp_path / "problem"
        problem_path.mkdir()
        problem_tests = problem_path / "tests"
        problem_tests.mkdir()
        (problem_tests / "test_checkpoint_1.py").write_text("# test")
        (problem_tests / "conftest.py").write_text("# conftest")

        # submission_path is where agent code lives (NO tests)
        submission_path = tmp_path / "submission"
        submission_path.mkdir()
        (submission_path / "main.py").write_text("# agent solution")

        # workspace_path is the temporary execution directory (separate from submission)
        workspace_path = tmp_path / "workspace"
        workspace_path.mkdir()

        mock_problem_config.path = problem_path

        runner = PytestRunner(
            problem=mock_problem_config,
            checkpoint=mock_checkpoint_config,
            environment=mock_environment,
            submission_path=submission_path,  # This is different from workspace
        )

        # Copy tests to WORKSPACE, not submission
        runner._copy_tests_from_problem(workspace_path)

        # CRITICAL: Tests should be in workspace_path
        assert (workspace_path / WORKSPACE_TEST_DIR).exists()
        assert (workspace_path / WORKSPACE_TEST_DIR / "test_checkpoint_1.py").exists()
        assert (workspace_path / WORKSPACE_TEST_DIR / "conftest.py").exists()

        # CRITICAL: submission_path should NOT have tests directory created
        assert not (submission_path / WORKSPACE_TEST_DIR).exists()

    def test_submission_path_unchanged_after_test_copy(
        self,
        mock_problem_config,
        mock_checkpoint_config,
        mock_environment,
        tmp_path,
    ):
        """Submission directory is not modified when copying tests to workspace."""
        # Setup problem with tests
        problem_path = tmp_path / "problem"
        problem_path.mkdir()
        problem_tests = problem_path / "tests"
        problem_tests.mkdir()
        (problem_tests / "test_checkpoint_1.py").write_text("# test")

        # Create submission with specific content
        submission_path = tmp_path / "submission"
        submission_path.mkdir()
        (submission_path / "main.py").write_text("# solution")
        (submission_path / "helper.py").write_text("# helper")

        # Create workspace
        workspace_path = tmp_path / "workspace"
        workspace_path.mkdir()

        # Record initial submission state
        initial_files = set(f.name for f in submission_path.iterdir())

        mock_problem_config.path = problem_path

        runner = PytestRunner(
            problem=mock_problem_config,
            checkpoint=mock_checkpoint_config,
            environment=mock_environment,
            submission_path=submission_path,
        )

        # Copy tests to workspace
        runner._copy_tests_from_problem(workspace_path)

        # Verify submission_path was not modified
        final_files = set(f.name for f in submission_path.iterdir())
        assert initial_files == final_files, (
            f"Submission directory was modified: "
            f"initial={initial_files}, final={final_files}"
        )


class TestSnapshotLocationRegression:
    """Regression tests ensuring snapshots don't pollute submission directory."""

    def test_no_snapshot_archives_in_submission_path_after_run(
        self,
        mock_problem_config,
        mock_checkpoint_config,
        mock_environment,
        tmp_path,
    ):
        """No snapshot archives should appear in submission_path after run()."""
        from unittest.mock import MagicMock
        from unittest.mock import patch

        # Setup submission directory
        submission_path = tmp_path / "submission"
        submission_path.mkdir()
        (submission_path / "main.py").write_text("# solution")

        # Setup mock session with SEPARATE workspace directory
        workspace_path = tmp_path / "workspace"
        workspace_path.mkdir()
        workspace_tests = workspace_path / WORKSPACE_TEST_DIR
        workspace_tests.mkdir()
        (workspace_tests / "pyproject.toml").write_text("[project]\nname = 'tests'\n")

        mock_workspace = MagicMock()
        mock_workspace.working_dir = workspace_path  # Different from submission_path!

        mock_session = MagicMock()
        mock_session.workspace = mock_workspace

        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.stdout = "collected 1 item"
        mock_result.stderr = ""
        mock_result.elapsed = 0.1

        mock_runtime = MagicMock()
        mock_runtime.execute.return_value = mock_result
        mock_session.spawn.return_value = mock_runtime

        runner = PytestRunner(
            problem=mock_problem_config,
            checkpoint=mock_checkpoint_config,
            environment=mock_environment,
            submission_path=submission_path,
        )

        with (
            patch(
                "slop_code.evaluation.pytest_runner.Session"
            ) as mock_session_cls,
            patch(
                "slop_code.evaluation.pytest_runner.resolve_static_assets"
            ) as mock_resolve,
        ):
            mock_session_cls.from_environment_spec.return_value = mock_session
            mock_resolve.return_value = {}

            # Create CTRF report in workspace
            scbench_dir = workspace_path / ".scbench"
            scbench_dir.mkdir()
            (scbench_dir / "ctrf-report.json").write_text('{"results": {"tests": []}}')

            runner.run()

        # CRITICAL: No snapshot archives should be in submission_path
        snapshot_patterns = ["*.tar.gz", "*.tar.bz2", "*.tar.xz", "*.tar"]
        for pattern in snapshot_patterns:
            archives = list(submission_path.glob(pattern))
            assert len(archives) == 0, (
                f"Found snapshot archive in submission_path: {archives}"
            )

            # Also check recursively
            recursive_archives = list(submission_path.rglob(pattern))
            assert len(recursive_archives) == 0, (
                f"Found snapshot archive (recursive) in submission_path: {recursive_archives}"
            )

        # Verify submission_path only has original file
        files_in_submission = list(submission_path.iterdir())
        assert files_in_submission == [submission_path / "main.py"], (
            f"Unexpected files in submission_path: {files_in_submission}"
        )

    def test_run_uses_workspace_working_dir_not_submission_path(
        self,
        mock_problem_config,
        mock_checkpoint_config,
        mock_environment,
        tmp_path,
    ):
        """run() operations use workspace.working_dir, not submission_path."""
        from unittest.mock import MagicMock
        from unittest.mock import patch

        submission_path = tmp_path / "submission"
        submission_path.mkdir()
        (submission_path / "main.py").write_text("# solution")

        # Create a DISTINCT workspace path
        workspace_path = tmp_path / "workspace"
        workspace_path.mkdir()
        workspace_tests = workspace_path / WORKSPACE_TEST_DIR
        workspace_tests.mkdir()
        # Create a test file (no pyproject.toml needed with uvx)
        (workspace_tests / "test_checkpoint_1.py").write_text("# test file")

        mock_workspace = MagicMock()
        mock_workspace.working_dir = workspace_path

        mock_session = MagicMock()
        mock_session.workspace = mock_workspace

        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.stdout = "collected 1 item"
        mock_result.stderr = ""
        mock_result.elapsed = 0.1

        mock_runtime = MagicMock()
        mock_runtime.execute.return_value = mock_result
        mock_session.spawn.return_value = mock_runtime

        runner = PytestRunner(
            problem=mock_problem_config,
            checkpoint=mock_checkpoint_config,
            environment=mock_environment,
            submission_path=submission_path,
        )

        with (
            patch(
                "slop_code.evaluation.pytest_runner.Session"
            ) as mock_session_cls,
            patch(
                "slop_code.evaluation.pytest_runner.resolve_static_assets"
            ) as mock_resolve,
            patch.object(
                runner, "_copy_tests_from_problem", return_value=None
            ) as mock_copy_tests,
            patch.object(
                runner, "_generate_pytest_ini", return_value=None
            ) as mock_ini,
        ):
            mock_session_cls.from_environment_spec.return_value = mock_session
            mock_resolve.return_value = {}

            # Create CTRF report in workspace
            scbench_dir = workspace_path / ".scbench"
            scbench_dir.mkdir()
            (scbench_dir / "ctrf-report.json").write_text('{"results": {"tests": []}}')

            runner.run()

        # Verify workspace_path (NOT submission_path) was passed to these methods
        mock_copy_tests.assert_called_once()
        call_args = mock_copy_tests.call_args
        assert call_args[0][0] == workspace_path, (
            f"_copy_tests_from_problem called with {call_args[0][0]}, "
            f"expected {workspace_path}"
        )

        mock_ini.assert_called_once_with(workspace_path)


@pytest.mark.skipif(
    not docker_available(),
    reason="Docker is not available or not running",
)
class TestPytestRunnerE2E:
    """End-to-end tests that require actual Docker and problem setup."""

    def test_run_against_real_problem(self):
        """Full end-to-end test against a real problem."""
        pass
