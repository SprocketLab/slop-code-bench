"""Fluent response validators for execution server tests."""

from __future__ import annotations

import uuid
from typing import Self

from .models import ExecuteResponse, StatsResponse


class ExecuteResponseValidator:
    """Fluent validator for ExecuteResponse."""

    def __init__(self, response: ExecuteResponse):
        self.response = response

    def status(self, expected: int) -> Self:
        assert self.response.status_code == expected, (
            f"Expected status {expected}, got {self.response.status_code}"
        )
        return self

    def success(self) -> Self:
        """Assert 201 status."""
        return self.status(201)

    def has_valid_uuid(self) -> Self:
        try:
            uuid.UUID(self.response.id)
        except ValueError:
            raise AssertionError(f"Invalid UUID: {self.response.id}")
        return self

    def stdout(self, expected: str, strip: bool = True) -> Self:
        actual = self.response.stdout.strip() if strip else self.response.stdout
        expected_val = expected.strip() if strip else expected
        assert actual == expected_val, (
            f"stdout mismatch: {actual!r} != {expected_val!r}"
        )
        return self

    def stdout_contains(self, substring: str) -> Self:
        assert substring in self.response.stdout, (
            f"stdout doesn't contain {substring!r}: {self.response.stdout!r}"
        )
        return self

    def stderr(self, expected: str, strip: bool = True) -> Self:
        actual = self.response.stderr.strip() if strip else self.response.stderr
        expected_val = expected.strip() if strip else expected
        assert actual == expected_val, (
            f"stderr mismatch: {actual!r} != {expected_val!r}"
        )
        return self

    def stderr_contains(self, substring: str) -> Self:
        assert substring in self.response.stderr, (
            f"stderr doesn't contain {substring!r}: {self.response.stderr!r}"
        )
        return self

    def exit_code(self, expected: int) -> Self:
        assert self.response.exit_code == expected, (
            f"exit_code: {self.response.exit_code} != {expected}"
        )
        return self

    def did_not_timeout(self) -> Self:
        assert not self.response.timed_out, "Expected no timeout"
        return self

    def timed_out(self) -> Self:
        assert self.response.timed_out, "Expected timeout"
        return self

    def duration_within(self, timeout: float, buffer: float = 0.5) -> Self:
        assert 0 < self.response.duration <= timeout + buffer, (
            f"duration {self.response.duration} not in (0, {timeout + buffer}]"
        )
        return self

    def has_files(self, expected: dict[str, str]) -> Self:
        assert self.response.files == expected, (
            f"files mismatch: {self.response.files} != {expected}"
        )
        return self

    def has_file(self, path: str, content: str) -> Self:
        assert path in self.response.files, f"File {path} not in response"
        assert self.response.files[path] == content, (
            f"File {path} content mismatch: {self.response.files[path]!r} != {content!r}"
        )
        return self

    def no_files(self) -> Self:
        assert self.response.files == {}, (
            f"Expected no files, got {self.response.files}"
        )
        return self

    def files_absent(self) -> Self:
        """Assert files field is not in response (for backward compat)."""
        assert not self.response.files, (
            f"Expected files to be absent/empty, got {self.response.files}"
        )
        return self

    def cached(self, expected: bool) -> Self:
        assert self.response.cached == expected, (
            f"cached: {self.response.cached} != {expected}"
        )
        return self

    def has_commands(self, count: int) -> Self:
        assert self.response.commands is not None, "Expected commands array"
        assert len(self.response.commands) == count, (
            f"Expected {count} commands, got {len(self.response.commands)}"
        )
        return self

    def command_at(self, index: int) -> CommandValidator:
        """Get validator for a specific command in the chain."""
        assert self.response.commands is not None, "Expected commands array"
        assert index < len(self.response.commands), (
            f"Command index {index} out of range"
        )
        return CommandValidator(self.response.commands[index], self)

    def error_code(self, expected: str) -> Self:
        assert self.response.code == expected, (
            f"error code: {self.response.code} != {expected}"
        )
        return self

    def has_error(self, substring: str | None = None) -> Self:
        assert self.response.error is not None, "Expected error message"
        if substring:
            assert substring in self.response.error, (
                f"Error doesn't contain {substring!r}: {self.response.error!r}"
            )
        return self

    def environment_name(self, expected: str) -> Self:
        assert self.response.environment is not None, "Expected environment"
        assert self.response.environment.get("name") == expected, (
            f"environment.name: {self.response.environment.get('name')} != {expected}"
        )
        return self

    def environment_committed(self, expected: bool) -> Self:
        assert self.response.environment is not None, "Expected environment"
        assert self.response.environment.get("committed") == expected, (
            f"environment.committed: {self.response.environment.get('committed')} != {expected}"
        )
        return self


class CommandValidator:
    """Validator for a single command in a chain."""

    def __init__(self, command: dict, parent: ExecuteResponseValidator):
        self.command = command
        self._parent = parent

    def cmd(self, expected: str) -> Self:
        assert self.command.get("cmd") == expected, (
            f"cmd: {self.command.get('cmd')} != {expected}"
        )
        return self

    def stdout(self, expected: str, strip: bool = True) -> Self:
        actual = self.command.get("stdout", "")
        actual = actual.strip() if strip else actual
        expected_val = expected.strip() if strip else expected
        assert actual == expected_val, f"stdout mismatch: {actual!r} != {expected_val!r}"
        return self

    def stderr(self, expected: str, strip: bool = True) -> Self:
        actual = self.command.get("stderr", "")
        actual = actual.strip() if strip else actual
        expected_val = expected.strip() if strip else expected
        assert actual == expected_val, f"stderr mismatch: {actual!r} != {expected_val!r}"
        return self

    def exit_code(self, expected: int) -> Self:
        assert self.command.get("exit_code") == expected, (
            f"exit_code: {self.command.get('exit_code')} != {expected}"
        )
        return self

    def timed_out(self, expected: bool = True) -> Self:
        assert self.command.get("timed_out") == expected, (
            f"timed_out: {self.command.get('timed_out')} != {expected}"
        )
        return self

    def is_required(self) -> Self:
        assert self.command.get("required") is True, "Expected required=true"
        return self

    def done(self) -> ExecuteResponseValidator:
        """Return to parent validator."""
        return self._parent


class StatsValidator:
    """Fluent validator for StatsResponse."""

    def __init__(self, response: StatsResponse):
        self.response = response

    def status(self, expected: int) -> Self:
        assert self.response.status_code == expected
        return self

    def ran(self, expected: int) -> Self:
        assert self.response.ran == expected, (
            f"ran: {self.response.ran} != {expected}"
        )
        return self

    def ran_at_least(self, minimum: int) -> Self:
        assert self.response.ran >= minimum, (
            f"ran {self.response.ran} < {minimum}"
        )
        return self

    def duration_all_null(self) -> Self:
        for key in ["average", "median", "max", "min", "stddev"]:
            assert self.response.duration.get(key) is None, (
                f"duration.{key} should be null, got {self.response.duration.get(key)}"
            )
        return self

    def duration_all_set(self) -> Self:
        for key in ["average", "median", "max", "min", "stddev"]:
            assert self.response.duration.get(key) is not None, (
                f"duration.{key} should be set"
            )
        return self

    def duration_positive(self) -> Self:
        for key in ["average", "median", "max", "min"]:
            val = self.response.duration.get(key)
            if val is not None:
                assert val >= 0, f"duration.{key} should be >= 0, got {val}"
        return self

    def has_commands_stats(self) -> Self:
        assert self.response.commands is not None, "Expected commands stats"
        return self

    def commands_total(self, expected: int) -> Self:
        assert self.response.commands is not None, "Expected commands stats"
        assert self.response.commands["total"] == expected, (
            f"commands.total: {self.response.commands['total']} != {expected}"
        )
        return self

    def has_cache_stats(self) -> Self:
        assert self.response.cache is not None, "Expected cache stats"
        return self

    def cache_hits(self, expected: int) -> Self:
        assert self.response.cache is not None, "Expected cache stats"
        assert self.response.cache["hits"] == expected, (
            f"cache.hits: {self.response.cache['hits']} != {expected}"
        )
        return self

    def cache_misses(self, expected: int) -> Self:
        assert self.response.cache is not None, "Expected cache stats"
        assert self.response.cache["misses"] == expected, (
            f"cache.misses: {self.response.cache['misses']} != {expected}"
        )
        return self


def check(response: ExecuteResponse) -> ExecuteResponseValidator:
    """Entry point for fluent execute response validation."""
    return ExecuteResponseValidator(response)


def check_stats(response: StatsResponse) -> StatsValidator:
    """Entry point for fluent stats validation."""
    return StatsValidator(response)
