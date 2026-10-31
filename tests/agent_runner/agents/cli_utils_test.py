"""Tests for shared CLI agent utilities."""

from __future__ import annotations

from collections.abc import Iterator
from typing import cast

from slop_code.agent_runner.agents.cli_utils import stream_cli_command
from slop_code.common.llms import TokenUsage
from slop_code.execution.protocols import StreamingRuntime
from slop_code.execution.runtime import RuntimeEvent
from slop_code.execution.runtime import RuntimeResult


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


def test_stream_cli_command_buffers_split_output() -> None:
    runtime = cast(
        "StreamingRuntime",
        FakeRuntime(
            [
                RuntimeEvent(kind="stdout", text='{"step"'),
                RuntimeEvent(kind="stdout", text=": 1}\ntrail"),
                RuntimeEvent(kind="stdout", text="ing"),
                RuntimeEvent(kind="stderr", text='{"err"'),
                RuntimeEvent(kind="stderr", text=": true}\n"),
            ]
        ),
    )

    items = list(
        stream_cli_command(
            runtime=runtime,
            command="agent",
            parser=_parse_line,
            parse_stderr=True,
        )
    )

    assert items[:-1] == [
        (None, None, {"line": '{"step": 1}'}),
        (None, None, {"line": '{"err": true}'}),
        (None, None, {"line": "trailing"}),
    ]
    result = items[-1]
    assert isinstance(result, RuntimeResult)
    assert result.stdout == '{"step": 1}\ntrailing'
    assert result.stderr == '{"err": true}\n'
