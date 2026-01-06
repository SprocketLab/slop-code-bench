"""CLI utilities for agent execution."""

from __future__ import annotations

import time
from collections.abc import Callable, Generator, Mapping
from dataclasses import dataclass
from typing import Any

from slop_code.common.llms import TokenUsage
from slop_code.execution.protocols import StreamingRuntime
from slop_code.execution.runtime import RuntimeResult

__all__ = [
    "AgentCommandResult",
    "stream_cli_command",
]


@dataclass(slots=True)
class AgentCommandResult:
    """Result of running an agent CLI command."""

    result: RuntimeResult | None
    steps: list[Any]  # Vestigial - always empty
    usage_totals: dict[str, int]
    stdout: str | None
    stderr: str | None
    had_error: bool = False
    error_message: str | None = None


def stream_cli_command(
    runtime: StreamingRuntime,
    command: str,
    parser: Callable[[str], tuple[float | None, TokenUsage | None, dict]],
    env: Mapping[str, str] | None = None,
    timeout: float | None = None,
    *,
    parse_stderr: bool = False,
) -> Generator[
    tuple[float | None, TokenUsage | None, dict] | RuntimeResult | None,
    None,
    None,
]:
    """Stream CLI command output and parse lines through the provided parser.

    Args:
        runtime: The streaming runtime to execute the command
        command: The command to execute
        parser: Callable that parses a line and returns (cost, tokens, payload)
        env: Environment variables for the command
        timeout: Optional timeout in seconds
        parse_stderr: If True, also parse stderr lines through the parser
    """
    env = dict(env or {})
    stdout_buffer = ""
    stderr_buffer = ""
    stdout = stderr = ""
    start = time.monotonic()
    result: RuntimeResult | None = None

    for event in runtime.stream(command=command, env=env, timeout=timeout):
        if event.kind == "stdout":
            stdout += event.text or ""
            stdout_buffer += event.text or ""
            while "\n" in stdout_buffer:
                line, stdout_buffer = stdout_buffer.split("\n", 1)
                line = line.strip()
                if not line:
                    continue
                yield parser(line)
        elif event.kind == "stderr":
            stderr += event.text or ""
            if parse_stderr:
                stderr_buffer += event.text or ""
                while "\n" in stderr_buffer:
                    line, stderr_buffer = stderr_buffer.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    yield parser(line)
        elif event.kind == "finished":
            result = event.result
            break

    # Flush remaining stdout buffer
    for line in stdout_buffer.split("\n"):
        line = line.strip()
        if not line:
            continue
        yield parser(line)

    # Flush remaining stderr buffer if parsing stderr
    if parse_stderr:
        for line in stderr_buffer.split("\n"):
            line = line.strip()
            if not line:
                continue
            yield parser(line)

    if result is None:
        result = RuntimeResult(
            exit_code=0,
            stdout=stdout,
            stderr=stderr,
            setup_stdout="",
            setup_stderr="",
            elapsed=time.monotonic() - start,
            timed_out=False,
        )
    yield result
