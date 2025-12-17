from __future__ import annotations

from collections.abc import Iterable

from slop_code.agent_runner.agents.cli_utils import decode_jsonl_stream
from slop_code.agent_runner.agents.cli_utils import run_cli_command
from slop_code.agent_runner.agents.cli_utils import run_streaming_cli_command
from slop_code.agent_runner.trajectory import StepRole
from slop_code.agent_runner.trajectory import TrajectoryStep
from slop_code.execution.runtime import RuntimeEvent
from slop_code.execution.runtime import RuntimeResult


class FakeSession:
    def __init__(self, runtime: object) -> None:
        self._runtime = runtime

    def spawn(self) -> object:
        return self._runtime


class FakeStreamingRuntime:
    def __init__(self, events: Iterable[RuntimeEvent]) -> None:
        self._events = list(events)
        self.cleanup_called = False
        self.stream_calls: list[dict[str, object]] = []

    def stream(self, *, command, env, stdin, timeout):
        self.stream_calls.append(
            {
                "command": command,
                "env": env,
                "stdin": stdin,
                "timeout": timeout,
            }
        )
        yield from self._events

    def cleanup(self) -> None:
        self.cleanup_called = True


class FakeExecuteRuntime:
    def __init__(self, result: RuntimeResult) -> None:
        self._result = result
        self.cleanup_called = False
        self.execute_calls: list[dict[str, object]] = []

    def execute(self, *, command, env, stdin, timeout):
        self.execute_calls.append(
            {
                "command": command,
                "env": env,
                "stdin": stdin,
                "timeout": timeout,
            }
        )
        return self._result

    def cleanup(self) -> None:
        self.cleanup_called = True


class FakeParser:
    def __init__(
        self,
        *,
        pending_steps: Iterable[TrajectoryStep] | None = None,
        finish_steps: Iterable[TrajectoryStep] | None = None,
        totals: dict[str, int] | None = None,
    ) -> None:
        self._pending = list(pending_steps or [])
        self._finish = list(finish_steps or [])
        self.totals = totals or {}
        self.consumed: list[RuntimeEvent] = []

    def consume(self, event: RuntimeEvent) -> None:
        self.consumed.append(event)

    def drain_steps(self):
        if self._pending:
            pending = tuple(self._pending)
            self._pending.clear()
            return pending
        return ()

    def finish(self):
        if self._finish:
            finished = tuple(self._finish)
            self._finish.clear()
            return finished
        return ()


def test_decode_jsonl_stream_handles_partial_and_invalid_lines() -> None:
    parsed, buffer = decode_jsonl_stream(
        "",
        '{"a": 1}\nnot-json\n{"b": 2}\n{"c": 3',
    )

    assert parsed == [{"a": 1}, {"b": 2}]
    assert buffer == '{"c": 3'

    parsed_2, buffer_2 = decode_jsonl_stream(buffer, '}\n{"d": 4}\n')
    assert parsed_2 == [{"c": 3}, {"d": 4}]
    assert buffer_2 == ""


def test_run_streaming_cli_command_collects_steps_and_usage() -> None:
    result_payload = RuntimeResult(
        exit_code=0,
        stdout="ok",
        stderr="",
        setup_stdout="",
        setup_stderr="",
        elapsed=0.5,
        timed_out=False,
    )
    events = [
        RuntimeEvent(kind="stdout", text="chunk-1"),
        RuntimeEvent(kind="finished", result=result_payload),
    ]

    runtime = FakeStreamingRuntime(events)

    parser = FakeParser(
        pending_steps=[TrajectoryStep(role=StepRole.SYSTEM, content="init")],
        finish_steps=[TrajectoryStep(role=StepRole.ASSISTANT, content="done")],
        totals={"input_tokens": 9},
    )

    generator = run_streaming_cli_command(
        runtime=runtime,
        command=["claude", "--run"],
        parser=parser,
    )
    produced_steps = []
    try:
        while True:
            produced_steps.append(next(generator))
    except StopIteration as exc:
        finished_result = exc.value

    assert finished_result is result_payload
    assert [step.content for step in produced_steps] == ["init", "done"]
    assert parser.totals == {"input_tokens": 9}
    assert result_payload.stdout == "ok"
    assert parser.consumed == events


def test_run_streaming_cli_command_returns_none_without_finished_event() -> None:
    events = [RuntimeEvent(kind="stdout", text="chunk")]
    runtime = FakeStreamingRuntime(events)
    parser = FakeParser()

    generator = run_streaming_cli_command(
        runtime=runtime,
        command="agent",
        parser=parser,
    )
    produced_steps = []
    try:
        while True:
            produced_steps.append(next(generator))
    except StopIteration as exc:
        finished_result = exc.value

    assert finished_result is None
    assert produced_steps == []


def test_run_cli_command_executes_command_and_cleans_up() -> None:
    runtime_result = RuntimeResult(
        exit_code=123,
        stdout="output",
        stderr="error",
        setup_stdout="",
        setup_stderr="",
        elapsed=1.2,
        timed_out=False,
    )
    runtime = FakeExecuteRuntime(runtime_result)
    session = FakeSession(runtime)

    command_result = run_cli_command(
        session,
        ["tool", "--flag"],
        env={"KEY": "value"},
        timeout=5,
    )

    assert command_result.result is runtime_result
    assert command_result.stdout == "output"
    assert command_result.stderr == "error"
    assert runtime.cleanup_called is True
    assert runtime.execute_calls[0]["command"] == ["tool", "--flag"]
    assert runtime.execute_calls[0]["env"] == {"KEY": "value"}
