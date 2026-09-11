"""Tests for runtime stream processing helpers."""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator

from slop_code.execution import stream_processor
from slop_code.execution.runtime import RuntimeResult
from slop_code.execution.stream_processor import ensure_string
from slop_code.execution.stream_processor import process_stream


def test_ensure_string_preserves_text_around_invalid_utf8_bytes() -> None:
    decoded = ensure_string(b'{"type":"message_update","data":"ok"}\xff\n')

    assert '{"type":"message_update","data":"ok"}' in decoded
    assert decoded.endswith("\n")


def test_process_stream_returns_when_stream_never_ends(
    monkeypatch,
) -> None:
    """A stream that never reaches EOF must not wedge the consumer forever."""
    monkeypatch.setattr(stream_processor, "PUMP_JOIN_TIMEOUT", 0.5)
    release = threading.Event()

    def blocking_stream() -> Iterator[tuple[bytes, bytes]]:
        yield b'{"type":"message_end"}\n', b""
        release.wait()

    result: list[RuntimeResult] = []

    def consume() -> None:
        generator = process_stream(
            blocking_stream(),
            timeout=600.0,
            poll_fn=lambda: 0,
        )
        try:
            while True:
                next(generator)
        except StopIteration as stop:
            result.append(stop.value)

    thread = threading.Thread(target=consume, daemon=True)
    started = time.monotonic()
    thread.start()
    thread.join(timeout=10.0)
    release.set()

    assert not thread.is_alive(), "process_stream blocked on the pump thread"
    assert time.monotonic() - started < 10.0
    assert result[0].exit_code == 0


def test_process_stream_collects_output_from_already_exited_process() -> None:
    """Output still in flight when the first poll reports an exit is kept."""

    def delayed_stream() -> Iterator[tuple[bytes, bytes]]:
        time.sleep(0.2)
        yield b"out\n", b""
        yield b"", b"err\n"

    generator = process_stream(
        delayed_stream(),
        timeout=600.0,
        poll_fn=lambda: 0,
    )
    events = []
    try:
        while True:
            events.append(next(generator))
    except StopIteration as stop:
        result = stop.value

    assert [(event.kind, event.text) for event in events] == [
        ("stdout", "out\n"),
        ("stderr", "err\n"),
    ]
    assert result.stdout == "out\n"
    assert result.stderr == "err\n"
    assert result.exit_code == 0
    assert not result.timed_out


def test_process_stream_returns_when_stream_keeps_producing(
    monkeypatch,
) -> None:
    """An exited process whose stream never ends must not stall the drain."""
    monkeypatch.setattr(stream_processor, "DRAIN_JOIN_TIMEOUT", 0.5)

    def endless_stream() -> Iterator[tuple[bytes, bytes]]:
        yield b"out\n", b""
        yield b"", b"err\n"
        while True:
            time.sleep(0.01)
            yield b"more\n", b""

    generator = process_stream(
        endless_stream(),
        timeout=600.0,
        poll_fn=lambda: 0,
    )
    started = time.monotonic()
    try:
        while True:
            next(generator)
    except StopIteration as stop:
        result = stop.value
    elapsed = time.monotonic() - started

    assert elapsed < 5.0, "process_stream waited on a stream that never ends"
    assert result.stdout.startswith("out\n")
    assert result.stderr == "err\n"
    assert result.exit_code == 0
