"""Tests for checkpoint_1: Basic command execution and stats."""

import pytest

from .assertions import check, check_stats
from .models import ExecuteRequest


class TestBasicExecution:
    """Core tests for basic command execution."""

    def test_initial_stats(self, client):
        """Stats should show zero runs initially."""
        stats = client.get_stats()
        check_stats(stats).status(200).ran(0).duration_all_null()

    def test_echo_command(self, client):
        """Basic echo command should return stdout."""
        resp = client.execute(ExecuteRequest(command="echo 'Hello, world!'"))
        check(resp).success().has_valid_uuid().stdout("Hello, world!").exit_code(0).did_not_timeout()

    def test_command_with_stderr(self, client):
        """Command that writes to stderr."""
        resp = client.execute(ExecuteRequest(command="echo 'error' >&2"))
        check(resp).success().stderr("error").exit_code(0)

    def test_command_with_exit_code(self, client):
        """Command that exits with non-zero code."""
        resp = client.execute(ExecuteRequest(command="exit 42"))
        check(resp).success().exit_code(42).did_not_timeout()

    def test_timeout_exceeded(self, client):
        """Command that exceeds timeout should be terminated."""
        resp = client.execute(ExecuteRequest(command="sleep 2", timeout=1.0))
        check(resp).success().has_valid_uuid().timed_out().exit_code(-1).duration_within(1.0, buffer=0.5)

    def test_with_input_files(self, client):
        """Command using input files."""
        resp = client.execute(
            ExecuteRequest(
                command="cat input.txt",
                files={"input.txt": "Hello, world"},
            )
        )
        check(resp).success().stdout("Hello, world").exit_code(0)

    def test_with_nested_files(self, client):
        """Command using nested input files."""
        resp = client.execute(
            ExecuteRequest(
                command="cat subdir/nested.txt",
                files={"subdir/nested.txt": "nested content"},
            )
        )
        check(resp).success().stdout("nested content").exit_code(0)

    def test_with_stdin_list(self, client):
        """Command with stdin input as list."""
        resp = client.execute(
            ExecuteRequest(
                command="read city; echo $city; read state; echo $state",
                stdin=["Madison", "Wisconsin"],
            )
        )
        check(resp).success().stdout("Madison\nWisconsin")

    def test_with_stdin_string(self, client):
        """Command with stdin input as string."""
        resp = client.execute(
            ExecuteRequest(
                command="cat",
                stdin="hello from stdin",
            )
        )
        check(resp).success().stdout("hello from stdin")

    def test_with_env_vars(self, client):
        """Command with environment variables."""
        resp = client.execute(
            ExecuteRequest(
                command="echo $TEST_VAR",
                env={"TEST_VAR": "test_value"},
            )
        )
        check(resp).success().stdout("test_value")

    def test_duration_is_positive(self, client):
        """Duration should be a positive float."""
        resp = client.execute(ExecuteRequest(command="echo fast"))
        check(resp).success()
        assert resp.duration > 0, f"Duration should be positive, got {resp.duration}"
        assert isinstance(resp.duration, float), f"Duration should be float, got {type(resp.duration)}"

    def test_stats_after_runs(self, client):
        """Stats should reflect executed commands."""
        stats = client.get_stats()
        check_stats(stats).status(200).ran_at_least(1).duration_all_set().duration_positive()


@pytest.mark.functionality
class TestFunctionality:
    """Additional functionality tests."""

    def test_multiline_output(self, client):
        """Command with multiline output."""
        resp = client.execute(ExecuteRequest(command="echo -e 'line1\\nline2\\nline3'"))
        check(resp).success().stdout("line1\nline2\nline3")

    def test_multiple_env_vars(self, client):
        """Command with multiple environment variables."""
        resp = client.execute(
            ExecuteRequest(
                command="echo $VAR1-$VAR2",
                env={"VAR1": "first", "VAR2": "second"},
            )
        )
        check(resp).success().stdout("first-second")

    def test_empty_stdout(self, client):
        """Command that produces no output."""
        resp = client.execute(ExecuteRequest(command="true"))
        check(resp).success().stdout("").exit_code(0)

    def test_command_with_quotes(self, client):
        """Command with special characters."""
        resp = client.execute(ExecuteRequest(command="echo \"hello 'world'\""))
        check(resp).success().stdout("hello 'world'")

    def test_timeout_boundary(self, client):
        """Command that just fits within timeout."""
        resp = client.execute(ExecuteRequest(command="sleep 0.5", timeout=2.0))
        check(resp).success().did_not_timeout().exit_code(0)


@pytest.mark.error
class TestErrors:
    """Error handling tests."""

    def test_missing_command_field(self, client):
        """Missing command field should return 400."""
        resp = client.execute_raw({"timeout": 10})
        check(resp).status(400).error_code("MISSING_REQUIRED_FIELD")

    def test_empty_command(self, client):
        """Empty command string should return 400."""
        resp = client.execute_raw({"command": ""})
        check(resp).status(400).error_code("INVALID_COMMAND")

    def test_invalid_timeout_negative(self, client):
        """Negative timeout should return 400."""
        resp = client.execute_raw({"command": "echo test", "timeout": -5})
        check(resp).status(400).error_code("INVALID_TIMEOUT")

    def test_invalid_timeout_zero(self, client):
        """Zero timeout should return 400."""
        resp = client.execute_raw({"command": "echo test", "timeout": 0})
        check(resp).status(400).error_code("INVALID_TIMEOUT")

    def test_invalid_timeout_type(self, client):
        """Non-numeric timeout should return 400."""
        resp = client.execute_raw({"command": "echo test", "timeout": "abc"})
        check(resp).status(400).error_code("INVALID_TYPE")

    def test_invalid_env_type(self, client):
        """Non-object env should return 400."""
        resp = client.execute_raw({"command": "echo test", "env": "not an object"})
        check(resp).status(400).error_code("INVALID_TYPE")

    def test_invalid_files_type(self, client):
        """Non-object files should return 400."""
        resp = client.execute_raw({"command": "echo test", "files": "not an object"})
        check(resp).status(400).error_code("INVALID_TYPE")
