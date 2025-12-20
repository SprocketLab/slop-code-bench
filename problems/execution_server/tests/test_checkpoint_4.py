"""Tests for checkpoint_4: Command chains."""

import pytest

from .assertions import check, check_stats
from .models import ExecuteRequest


class TestCommandChains:
    """Core tests for command chain execution."""

    def test_simple_chain(self, client):
        """Basic chain of commands."""
        resp = client.execute(
            ExecuteRequest(
                command=[
                    {"cmd": "echo 'step 1'"},
                    {"cmd": "echo 'step 2'"},
                    {"cmd": "echo 'step 3'"},
                ]
            )
        )
        check(resp).success().has_commands(3).exit_code(0)
        check(resp).command_at(0).stdout("step 1").exit_code(0).done()
        check(resp).command_at(1).stdout("step 2").exit_code(0).done()
        check(resp).command_at(2).stdout("step 3").exit_code(0).done()

    def test_chain_stop_on_failure(self, client):
        """Chain stops on first failure by default."""
        resp = client.execute(
            ExecuteRequest(
                command=[
                    {"cmd": "echo 'step 1' && exit 0"},
                    {"cmd": "echo 'step 2' && exit 1"},
                    {"cmd": "echo 'step 3'"},
                ]
            )
        )
        check(resp).success().has_commands(2).exit_code(1)
        check(resp).command_at(0).stdout("step 1").exit_code(0).done()
        check(resp).command_at(1).stdout("step 2").exit_code(1).done()

    def test_required_runs_after_failure(self, client):
        """Required command runs even after failure."""
        resp = client.execute(
            ExecuteRequest(
                command=[
                    {"cmd": "sh -c 'echo build > artifact.txt'"},
                    {"cmd": "sh -c 'cat nope.txt'"},
                    {"cmd": "sh -c 'echo cleanup >> artifact.txt'", "required": True},
                ],
                track=["*.txt"],
            )
        )
        check(resp).success().has_commands(3).exit_code(1)
        check(resp).command_at(2).exit_code(0).is_required().done()
        check(resp).has_file("artifact.txt", "build\ncleanup\n")

    def test_continue_on_error(self, client):
        """All commands run when continue_on_error is true."""
        resp = client.execute(
            ExecuteRequest(
                command=[
                    {"cmd": "echo 'test 1' && exit 1"},
                    {"cmd": "echo 'test 2' && exit 0"},
                    {"cmd": "echo 'test 3' && exit 1"},
                ],
                continue_on_error=True,
            )
        )
        check(resp).success().has_commands(3).exit_code(1)
        check(resp).command_at(0).stdout("test 1").exit_code(1).done()
        check(resp).command_at(1).stdout("test 2").exit_code(0).done()
        check(resp).command_at(2).stdout("test 3").exit_code(1).done()

    def test_per_command_timeout(self, client):
        """Command-specific timeout overrides default."""
        resp = client.execute(
            ExecuteRequest(
                command=[
                    {"cmd": "echo fast"},
                    {"cmd": "sleep 5", "timeout": 1},
                    {"cmd": "echo 'never runs'", "required": True},
                ],
                timeout=10,
            )
        )
        check(resp).success().has_commands(3).timed_out().exit_code(-1)
        check(resp).command_at(0).stdout("fast").exit_code(0).done()
        check(resp).command_at(1).exit_code(-1).timed_out(True).done()
        check(resp).command_at(2).is_required().done()

    def test_backward_compat_string_command(self, client):
        """String command still works (no commands array in response)."""
        resp = client.execute(ExecuteRequest(command="echo 'hello world'"))
        check(resp).success().stdout("hello world").exit_code(0)
        assert resp.commands is None, "String command should not return commands array"

    def test_chain_duration_is_sum(self, client):
        """Chain duration is sum of all command durations."""
        resp = client.execute(
            ExecuteRequest(
                command=[
                    {"cmd": "sleep 0.1"},
                    {"cmd": "sleep 0.1"},
                ]
            )
        )
        check(resp).success().has_commands(2)
        total_cmd_duration = sum(cmd["duration"] for cmd in resp.commands)
        assert abs(resp.duration - total_cmd_duration) < 0.05

    def test_stats_with_commands(self, client):
        """Stats include commands sub-object."""
        stats = client.get_stats()
        check_stats(stats).status(200).has_commands_stats()


@pytest.mark.functionality
class TestCommandChainsFunctionality:
    """Additional command chain tests."""

    def test_chain_with_files(self, client):
        """Chain with input files and tracking."""
        resp = client.execute(
            ExecuteRequest(
                command=[
                    {"cmd": "cat input.txt > step1.txt"},
                    {"cmd": "cat step1.txt >> output.txt"},
                ],
                files={"input.txt": "initial"},
                track=["output.txt"],
            )
        )
        check(resp).success().has_file("output.txt", "initial")

    def test_empty_chain(self, client):
        """Empty command array."""
        resp = client.execute(ExecuteRequest(command=[]))
        check(resp).success().has_commands(0).exit_code(0)

    def test_single_command_chain(self, client):
        """Chain with single command."""
        resp = client.execute(
            ExecuteRequest(command=[{"cmd": "echo solo"}])
        )
        check(resp).success().has_commands(1)
        check(resp).command_at(0).stdout("solo").done()

    def test_chain_preserves_working_dir(self, client):
        """Commands share working directory."""
        resp = client.execute(
            ExecuteRequest(
                command=[
                    {"cmd": "mkdir subdir && cd subdir && echo 'in subdir' > file.txt"},
                    {"cmd": "cat subdir/file.txt"},
                ]
            )
        )
        check(resp).success().has_commands(2)
        check(resp).command_at(1).stdout("in subdir").done()


@pytest.mark.error
class TestCommandChainErrors:
    """Error handling for command chains."""

    def test_invalid_command_object(self, client):
        """Command object without cmd field."""
        resp = client.execute_raw(
            {"command": [{"timeout": 10}]}
        )
        check(resp).status(400)

    def test_invalid_command_type_in_array(self, client):
        """Non-object in command array."""
        resp = client.execute_raw(
            {"command": ["echo test"]}
        )
        check(resp).status(400)
