"""CLI utilities for agent execution."""

from __future__ import annotations

import time
from collections.abc import Callable
from collections.abc import Generator
from collections.abc import Mapping
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
    stdout_buffer_parts: list[str] = []
    stderr_buffer_parts: list[str] = []
    stdout_parts: list[str] = []
    stderr_parts: list[str] = []
    start = time.monotonic()
    result: RuntimeResult | None = None

    for event in runtime.stream(command=command, env=env, timeout=timeout):
        if event.kind == "stdout":
            chunk = event.text or ""
            stdout_parts.append(chunk)
            stdout_buffer_parts.append(chunk)
            if "\n" in chunk:
                stdout_buffer = "".join(stdout_buffer_parts)
                while "\n" in stdout_buffer:
                    line, stdout_buffer = stdout_buffer.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    yield parser(line)
                stdout_buffer_parts = [stdout_buffer] if stdout_buffer else []
        elif event.kind == "stderr":
            chunk = event.text or ""
            stderr_parts.append(chunk)
            if parse_stderr:
                stderr_buffer_parts.append(chunk)
                if "\n" in chunk:
                    stderr_buffer = "".join(stderr_buffer_parts)
                    while "\n" in stderr_buffer:
                        line, stderr_buffer = stderr_buffer.split("\n", 1)
                        line = line.strip()
                        if not line:
                            continue
                        yield parser(line)
                    stderr_buffer_parts = (
                        [stderr_buffer] if stderr_buffer else []
                    )
        elif event.kind == "finished":
            result = event.result
            break

    # Flush remaining stdout buffer
    stdout_buffer = "".join(stdout_buffer_parts)
    for line in stdout_buffer.split("\n"):
        line = line.strip()
        if not line:
            continue
        yield parser(line)

    # Flush remaining stderr buffer if parsing stderr
    if parse_stderr:
        stderr_buffer = "".join(stderr_buffer_parts)
        for line in stderr_buffer.split("\n"):
            line = line.strip()
            if not line:
                continue
            yield parser(line)

    if result is None:
        result = RuntimeResult(
            exit_code=0,
            stdout="".join(stdout_parts),
            stderr="".join(stderr_parts),
            setup_stdout="",
            setup_stderr="",
            elapsed=time.monotonic() - start,
            timed_out=False,
        )
    yield result
