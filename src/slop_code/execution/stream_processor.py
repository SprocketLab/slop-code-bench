"""Utilities for processing runtime output streams with threading.

This module provides utilities for handling streaming output from runtime processes
with proper threading and timeout management:

- **ensure_string**: Convert bytes to string with error handling
- **start_stream_pump**: Start threaded stream processing
- **make_timeout_fn**: Create timeout calculation functions
- **process_stream**: Main stream processing with timeout and filtering

The utilities support both Docker and local runtime streams, providing
consistent behavior across different execution environments with proper cleanup
and timeout handling.
"""

from __future__ import annotations

import queue
import threading
import time
from collections.abc import Callable
from collections.abc import Generator
from collections.abc import Iterator
from typing import Literal

import structlog

from slop_code.execution.runtime import RuntimeEvent
from slop_code.execution.runtime import RuntimeResult

logger = structlog.get_logger(__name__)

DEFAULT_WAIT_TIMEOUT = 7200.0  # 2 hours
# How long to wait for the pump thread to notice the stream is done. The thread
# is a daemon and only appends to an in-memory queue, so abandoning it is safe;
# blocking on it forever is not.
PUMP_JOIN_TIMEOUT = 30.0
# How long to wait for in-flight output before signalling the pump to stop.
# The window for output queued but not yet drained is milliseconds; a stream
# that keeps producing without ever reaching EOF must not extend it.
DRAIN_JOIN_TIMEOUT = 2.0
EXIT_CODE_WAIT = 10.0


def ensure_string(data: bytes | str) -> str:
    if isinstance(data, bytes):
        return data.decode("utf-8", errors="replace")
    return data


def start_stream_pump(
    stream: Iterator[tuple[bytes | str, bytes | str]],
    event_queue: queue.Queue[
        tuple[Literal["stdout", "stderr", "finished"], str | None]
    ],
    stop_event: threading.Event,
) -> threading.Thread:
    """Start a thread to pump a demuxed stream into an event queue.

    Args:
        stream: Iterator yielding (stdout, stderr) tuples
        event_queue: Queue to receive events
        stop_event: Event to check for early termination
        ensure_string: Function to convert bytes to string
    """

    def pump() -> None:
        """Pump demuxed stream to event queue."""
        for stdout, stderr in stream:
            if stdout:
                contents = ensure_string(stdout)
                event_queue.put(("stdout", contents))
            if stderr:
                contents = ensure_string(stderr)
                event_queue.put(("stderr", contents))
            if stop_event.is_set():
                break
        event_queue.put(("finished", None))

    thread = threading.Thread(target=pump, daemon=True)
    thread.start()
    return thread


def make_timeout_fn(
    timeout: float | None, start_time: float
) -> Callable[[], float]:
    deadline = start_time + (timeout or DEFAULT_WAIT_TIMEOUT)

    def timeout_fn() -> float:
        return deadline - time.monotonic()

    return timeout_fn


def process_stream(
    stream: Iterator[tuple[str | bytes, str | bytes]],
    timeout: float | None,
    poll_fn: Callable[[], int | None],
    yield_only_after: str | None = None,
) -> Generator[RuntimeEvent, None, RuntimeResult]:
    logger.debug("Starting to consume events with timeout", timeout=timeout)
    start_time = time.monotonic()
    timeout_fn = make_timeout_fn(timeout, start_time)
    stop_event = threading.Event()
    event_queue: queue.Queue[
        tuple[Literal["stdout", "stderr", "finished"], str | None]
    ] = queue.Queue()
    thread = start_stream_pump(stream, event_queue, stop_event)
    stdout = ""
    stderr = ""
    setup_stdout = ""
    setup_stderr = ""
    yielding_stdout = yield_only_after is None
    yielding_stderr = yield_only_after is None
    timed_out = False

    def handle_event(
        kind: Literal["stdout", "stderr"],
        payload: str,
    ) -> Iterator[RuntimeEvent]:
        nonlocal stdout, stderr, setup_stdout, setup_stderr
        nonlocal yielding_stdout, yielding_stderr

        if kind == "stdout":
            stdout += payload
            if (
                not yielding_stdout
                and yield_only_after
                and yield_only_after in stdout
            ):
                yielding_stdout = True
                setup_stdout, stdout = stdout.split(yield_only_after, 1)
                payload = stdout

            if yielding_stdout and payload.strip():
                yield RuntimeEvent(kind="stdout", text=payload)
            return

        if kind == "stderr":
            stderr += payload
            if (
                not yielding_stderr
                and yield_only_after
                and yield_only_after in stderr
            ):
                yielding_stderr = True
                setup_stderr, stderr = stderr.split(yield_only_after, 1)
                payload = stderr

            if yielding_stderr and payload.strip():
                yield RuntimeEvent(kind="stderr", text=payload)
            return

        logger.error("Received unknown event", kind=kind, payload=payload)

    while (exit_code := poll_fn()) is None:
        if (remaining := timeout_fn()) <= 0:
            timed_out = True
            break

        try:
            kind, payload = event_queue.get(timeout=remaining)
        except queue.Empty:
            if (exit_code := poll_fn()) is not None:
                break
            continue

        if kind == "finished":
            logger.debug("Received finished event")
            break

        if payload is None:
            logger.error("Received empty stream event", kind=kind)
            break

        yield from handle_event(kind, payload)

    elapsed = time.monotonic() - start_time
    if not timed_out:
        # The process can exit before the loop above polls it even once,
        # leaving its output in flight. The pump queues every event and ends
        # with "finished", so joining it first makes the drain below exact
        # instead of a race against the thread. The join must not be signalled
        # — the pump breaks as soon as ``stop_event`` is set, truncating a fast
        # multi-chunk command — so it is bounded by the in-flight window.
        thread.join(timeout=min(DRAIN_JOIN_TIMEOUT, max(timeout_fn(), 0.0)))

    # Handle any remaining events in the queue
    while True:
        try:
            kind, payload = event_queue.get_nowait()
        except queue.Empty:
            break

        if kind == "finished":
            logger.debug("Received finished event")
            break

        if payload is None:
            logger.error("Received empty stream event", kind=kind)
            break

        yield from handle_event(kind, payload)

    stop_event.set()
    thread.join(timeout=min(PUMP_JOIN_TIMEOUT, max(timeout_fn(), 1.0)))
    if thread.is_alive():
        logger.warning(
            "Stream pump thread did not finish; abandoning it",
            join_timeout=PUMP_JOIN_TIMEOUT,
        )

    if exit_code is None:
        # The stream can reach EOF an instant before the process is reaped;
        # give the exit code a bounded window to materialize instead of
        # misreporting a clean exit as -1.
        deadline = time.monotonic() + EXIT_CODE_WAIT
        while (exit_code := poll_fn()) is None:
            if time.monotonic() >= deadline:
                break
            time.sleep(0.05)
    if exit_code is None:
        logger.warning(
            "Process exit code unavailable after stream end; reporting -1",
            wait_seconds=EXIT_CODE_WAIT,
        )
        exit_code = -1
    logger.debug(
        "Setup stdout", setup_stdout=setup_stdout, setup_stderr=setup_stderr
    )
    return RuntimeResult(
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        setup_stdout=setup_stdout,
        setup_stderr=setup_stderr,
        elapsed=elapsed,
        timed_out=timed_out,
    )
