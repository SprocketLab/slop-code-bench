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

type ParsedCliLine = tuple[float | None, TokenUsage | None, dict]
type CliLineParser = Callable[[str], ParsedCliLine]


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


def _parse_buffered_lines(
    buffer_parts: list[str],
    parser: CliLineParser,
    *,
    flush: bool = False,
) -> Generator[ParsedCliLine, None, None]:
    buffer = "".join(buffer_parts)
    if flush:
        lines = buffer.split("\n")
        buffer_parts.clear()
    else:
        *lines, tail = buffer.split("\n")
        buffer_parts[:] = [tail] if tail else []

    for line in lines:
        line = line.strip()
        if line:
            yield parser(line)


def stream_cli_command(
    runtime: StreamingRuntime,
    command: str,
    parser: CliLineParser,
    env: Mapping[str, str] | None = None,
    timeout: float | None = None,
    *,
    parse_stderr: bool = False,
) -> Generator[
    ParsedCliLine | RuntimeResult | None,
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
                yield from _parse_buffered_lines(stdout_buffer_parts, parser)
        elif event.kind == "stderr":
            chunk = event.text or ""
            stderr_parts.append(chunk)
            if parse_stderr:
                stderr_buffer_parts.append(chunk)
                if "\n" in chunk:
                    yield from _parse_buffered_lines(
                        stderr_buffer_parts,
                        parser,
                    )
        elif event.kind == "finished":
            result = event.result
            break

    # Flush remaining stdout buffer
    yield from _parse_buffered_lines(stdout_buffer_parts, parser, flush=True)

    # Flush remaining stderr buffer if parsing stderr
    if parse_stderr:
        yield from _parse_buffered_lines(
            stderr_buffer_parts,
            parser,
            flush=True,
        )

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
