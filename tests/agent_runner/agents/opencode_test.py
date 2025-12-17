"""Unit tests for the OpenCode agent run loop."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass

import pytest

from slop_code.agent_runner.agents.opencode import OpenCodeAgent
from slop_code.agent_runner.models import AgentCostLimits
from slop_code.agent_runner.models import AgentError
from slop_code.common.llms import APIPricing
from slop_code.common.llms import TokenUsage
from slop_code.execution.runtime import RuntimeEvent
from slop_code.execution.runtime import RuntimeResult


class FakeRuntime:
    """Minimal runtime stub used to feed deterministic events to the agent."""

    def __init__(self) -> None:
        self.events: list[RuntimeEvent] = []
        self.cleaned = False
        self.last_stream_args: tuple[tuple, dict] | None = None
        self.kill_calls = 0

    def stream(
        self,
        command: str,
        env: dict,
        stdin: str | list[str] | None,
        timeout: float | None,
    ) -> Iterable[RuntimeEvent]:
        self.last_stream_args = ((command, env, stdin, timeout), {})
        yield from self.events

    def cleanup(self) -> None:
        self.cleaned = True

    def kill(self) -> None:
        self.kill_calls += 1


@dataclass
class FakeSession:
    runtime: FakeRuntime
    working_dir: str

    spec: object | None = None

    def spawn(self, **_: object) -> FakeRuntime:  # pragma: no cover - trivial
        return self.runtime


@pytest.fixture
def make_agent(tmp_path_factory, request):
    def _make(
        *,
        cost_limits: AgentCostLimits = AgentCostLimits(
            step_limit=0,
            cost_limit=100.0,
            net_cost_limit=200.0,
        ),
    ) -> tuple[OpenCodeAgent, FakeRuntime]:
        tmp_dir = tmp_path_factory.mktemp("opencode_agent")
        runtime = FakeRuntime()
        session = FakeSession(runtime=runtime, working_dir=str(tmp_dir))

        agent = OpenCodeAgent(
            problem_name="sample-problem",
            verbose=False,
            cost_limits=cost_limits,
            pricing=APIPricing(
                input=0.6,
                output=2.2,
                cache_read=0.11,
            ),
            credential=None,
            model_id="glm-4.6",
            provider="zai-coding-plan",
            opencode_config={},
            env={},
            thinking=None,
        )
        agent.setup(session)
        request.addfinalizer(agent.cleanup)
        return agent, runtime

    return _make


def _token_usage_from_part(part: dict[str, dict]) -> TokenUsage:
    tokens = part["tokens"]
    return TokenUsage(
        input=tokens["input"],
        output=tokens["output"],
        cache_read=tokens["cache"]["read"],
        cache_write=tokens["cache"].get("write", 0),
        reasoning=tokens["reasoning"],
    )


def _runtime_events_from_stdout_chunks(
    chunks: list[str],
    *,
    exit_code: int = 0,
    stderr: str = "",
) -> list[RuntimeEvent]:
    events = [RuntimeEvent(kind="stdout", text=chunk, result=None) for chunk in chunks]
    events.append(
        RuntimeEvent(
            kind="finished",
            text=None,
            result=RuntimeResult(
                exit_code=exit_code,
                stdout="".join(chunks),
                stderr=stderr,
                elapsed=1.0,
                timed_out=False,
                setup_stdout="",
                setup_stderr="",
            ),
        )
    )
    return events


def test_run_collects_messages_and_updates_usage(make_agent):
    agent, runtime = make_agent()

    tool_use = {"type": "tool_use", "part": {"tool": "search"}}
    first_step = {
        "type": "step_finish",
        "part": {
            "reason": "tool-calls",
            "cost": 0.3,
            "tokens": {
                "input": 10,
                "output": 4,
                "reasoning": 1,
                "cache": {"read": 2, "write": 0},
            },
        },
    }
    final_step = {
        "type": "step_finish",
        "part": {
            "reason": "stop",
            "cost": 1.0,
            "tokens": {
                "input": 5,
                "output": 6,
                "reasoning": 2,
                "cache": {"read": 4, "write": 0},
            },
        },
    }

    chunk_1 = json.dumps(tool_use) + "\n" + json.dumps(first_step)[:20]
    chunk_2 = json.dumps(first_step)[20:] + "\n" + json.dumps(final_step)
    runtime.events = _runtime_events_from_stdout_chunks([chunk_1, chunk_2])

    agent.run("build something cool")
    messages = agent.messages

    assert messages[0] == tool_use
    assert messages[1] == first_step
    assert messages[2] == final_step

    assert agent.usage.steps == 2
    expected_cost = sum(
        agent.pricing.get_cost(_token_usage_from_part(step["part"]))
        for step in (first_step, final_step)
    )
    assert agent.usage.cost == pytest.approx(expected_cost)
    assert agent.usage.current_tokens.input == final_step["part"]["tokens"]["input"]
    assert agent.usage.current_tokens.output == final_step["part"]["tokens"]["output"]
    assert agent.usage.net_tokens.reasoning == 3
    assert (
        agent.usage.current_tokens.cache_read
        == final_step["part"]["tokens"]["cache"]["read"]
    )
    assert agent.continue_on_run is False


def test_run_skips_invalid_json_lines(make_agent):
    agent, runtime = make_agent()

    good_step = {
        "type": "step_finish",
        "part": {
            "reason": "stop",
            "cost": 0.25,
            "tokens": {
                "input": 3,
                "output": 2,
                "reasoning": 0,
                "cache": {"read": 1, "write": 0},
            },
        },
    }

    chunk = "this is not json\n" + json.dumps(good_step)
    runtime.events = _runtime_events_from_stdout_chunks([chunk])

    agent.run("ignore malformed lines")
    messages = agent.messages

    assert messages == [good_step]
    assert agent.usage.steps == 1
    expected_cost = agent.pricing.get_cost(
        _token_usage_from_part(good_step["part"])
    )
    assert agent.usage.cost == pytest.approx(expected_cost)


def test_run_raises_when_finished_event_missing(make_agent):
    agent, runtime = make_agent()

    unfinished_step = {
        "type": "step_finish",
        "part": {
            "reason": "tool-calls",
            "cost": 0.1,
            "tokens": {
                "input": 1,
                "output": 1,
                "reasoning": 0,
                "cache": {"read": 0, "write": 0},
            },
        },
    }
    runtime.events = [
        RuntimeEvent(
            kind="stdout",
            text=json.dumps(unfinished_step),
            result=None,
        ),
    ]

    with pytest.raises(AgentError):
        agent.run("no finished event")


def test_run_respects_step_limit(make_agent):
    limits = AgentCostLimits(
        step_limit=1,
        cost_limit=100.0,
        net_cost_limit=200.0,
    )
    agent, runtime = make_agent(cost_limits=limits)

    step = {
        "type": "step_finish",
        "part": {
            "reason": "tool-calls",
            "cost": 0.1,
            "tokens": {
                "input": 1,
                "output": 2,
                "reasoning": 0,
                "cache": {"read": 0, "write": 0},
            },
        },
    }
    runtime.events = _runtime_events_from_stdout_chunks([json.dumps(step)])

    agent.run("should stop by step")
    assert agent.messages[0] == step
    assert agent.cost_limits.is_above_limits(
        agent.usage,
        prior_cost=agent.prior_cost,
    )
    assert agent.continue_on_run is False
    assert agent.usage.steps == limits.step_limit


def test_run_respects_cost_limit(make_agent):
    limits = AgentCostLimits(
        step_limit=0,
        cost_limit=1e-6,
        net_cost_limit=200.0,
    )
    agent, runtime = make_agent(cost_limits=limits)

    expensive_step = {
        "type": "step_finish",
        "part": {
            "reason": "tool-calls",
            "cost": 0.75,
            "tokens": {
                "input": 2,
                "output": 3,
                "reasoning": 0,
                "cache": {"read": 0, "write": 0},
            },
        },
    }
    runtime.events = _runtime_events_from_stdout_chunks([json.dumps(expensive_step)])

    agent.run("too expensive")
    assert agent.messages[0] == expensive_step
    assert agent.cost_limits.is_above_limits(
        agent.usage,
        prior_cost=agent.prior_cost,
    )
    assert agent.continue_on_run is False
    assert agent.usage.cost > limits.cost_limit
