"""Tests for runtime stream processing helpers."""

from __future__ import annotations

from collections.abc import Iterator

from slop_code.execution.runtime import RuntimeEvent
from slop_code.execution.runtime import RuntimeResult
from slop_code.execution.shared import SPLIT_STRING
from slop_code.execution.stream_processor import ensure_string
from slop_code.execution.stream_processor import process_stream


def _collect_process_stream(
    chunks: Iterator[tuple[str, str]],
    *,
    yield_only_after: str | None = None,
) -> tuple[list[RuntimeEvent], RuntimeResult]:
    events: list[RuntimeEvent] = []
    generator = process_stream(
        chunks,
        timeout=1,
        poll_fn=lambda: None,
        yield_only_after=yield_only_after,
    )

    while True:
        try:
            events.append(next(generator))
        except StopIteration as stop:
            return events, stop.value


def test_ensure_string_preserves_text_around_invalid_utf8_bytes() -> None:
    decoded = ensure_string(b'{"type":"message_update","data":"ok"}\xff\n')

    assert '{"type":"message_update","data":"ok"}' in decoded
    assert decoded.endswith("\n")


def test_process_stream_splits_setup_marker_across_chunks() -> None:
    marker_start, marker_end = SPLIT_STRING[:10], SPLIT_STRING[10:]

    events, result = _collect_process_stream(
        iter(
            [
                ("setup stdout\n", ""),
                (marker_start, ""),
                (marker_end, ""),
                ("\ncommand stdout", ""),
                (" continued", ""),
                ("", "setup stderr\n"),
                ("", marker_start),
                ("", marker_end),
                ("", "\ncommand stderr"),
            ]
        ),
        yield_only_after=SPLIT_STRING,
    )

    assert [(event.kind, event.text) for event in events] == [
        ("stdout", "\ncommand stdout"),
        ("stdout", " continued"),
        ("stderr", "\ncommand stderr"),
    ]
    assert result.setup_stdout == "setup stdout\n"
    assert result.stdout == "\ncommand stdout continued"
    assert result.setup_stderr == "setup stderr\n"
    assert result.stderr == "\ncommand stderr"
