"""Tests for shared CLI agent helpers."""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING, cast

from slop_code.agent_runner.agents.cli_utils import stream_cli_command
from slop_code.common.llms import TokenUsage
from slop_code.execution.runtime import RuntimeEvent
from slop_code.execution.runtime import RuntimeResult

if TYPE_CHECKING:
    from slop_code.execution.protocols import StreamingRuntime


class FakeRuntime:
    def __init__(self, events: list[RuntimeEvent]) -> None:
        self.events = events

    def stream(
        self,
        command: str,
        env: dict[str, str],
        timeout: float | None,
    ) -> Iterator[RuntimeEvent]:
        yield from self.events


def _parse_line(line: str) -> tuple[float | None, TokenUsage | None, dict]:
    return None, None, {"line": line}


def test_stream_cli_command_parses_lines_across_chunk_boundaries() -> None:
    result = RuntimeResult(
        exit_code=0,
        stdout='{"step": 1}\n{"step": 2}\n',
        stderr='{"err": true}\n',
        setup_stdout="",
        setup_stderr="",
        elapsed=0.1,
        timed_out=False,
    )
    runtime = cast(
        "StreamingRuntime",
        FakeRuntime(
            [
                RuntimeEvent(kind="stdout", text='{"step"'),
                RuntimeEvent(kind="stdout", text=': 1}\n{"step":'),
                RuntimeEvent(kind="stdout", text=" 2}\n"),
                RuntimeEvent(kind="stderr", text='{"err"'),
                RuntimeEvent(kind="stderr", text=": true}\n"),
                RuntimeEvent(kind="finished", result=result),
            ]
        ),
    )

    items = list(
        stream_cli_command(
            runtime=runtime,
            command="agent --json",
            parser=_parse_line,
            parse_stderr=True,
        )
    )

    assert items == [
        (None, None, {"line": '{"step": 1}'}),
        (None, None, {"line": '{"step": 2}'}),
        (None, None, {"line": '{"err": true}'}),
        result,
    ]
