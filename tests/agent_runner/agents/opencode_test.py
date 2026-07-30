"""Unit tests for the OpenCode agent run loop."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import pytest

from slop_code.agent_runner.agents.opencode import OpenCodeAgent
from slop_code.agent_runner.agents.opencode import OpenCodeAgentConfig
from slop_code.agent_runner.agents.utils import HOME_PATH
from slop_code.agent_runner.credentials import CredentialType
from slop_code.agent_runner.credentials import ProviderCredential
from slop_code.agent_runner.models import AgentCostLimits
from slop_code.agent_runner.models import AgentError
from slop_code.common.llms import APIPricing
from slop_code.common.llms import ModelCatalog
from slop_code.common.llms import ModelDefinition
from slop_code.common.llms import ThinkingPreset
from slop_code.common.llms import TokenUsage
from slop_code.execution.runtime import RuntimeEvent
from slop_code.execution.runtime import RuntimeResult
from slop_code.execution.session import Session


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
        timeout: float | None,
    ) -> Iterable[RuntimeEvent]:
        self.last_stream_args = ((command, env, timeout), {})
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
    spawn_kwargs: dict[str, object] | None = None

    def spawn(
        self, **kwargs: object
    ) -> FakeRuntime:  # pragma: no cover - trivial
        self.spawn_kwargs = kwargs
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
        agent.setup(cast("Session", session))
        request.addfinalizer(agent.cleanup)
        return agent, runtime

    return _make


def _token_usage_from_part(part: dict[str, Any]) -> TokenUsage:
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
    events = [
        RuntimeEvent(kind="stdout", text=chunk, result=None) for chunk in chunks
    ]
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


class TestOpenCodeConfigGeneration:
    """Tests for _make_opencode_config behavior."""

    def _make_bare_agent(
        self,
        tmp_path: Path,
        *,
        provider: str = "openrouter",
        opencode_config: dict[str, Any] | None = None,
        thinking: ThinkingPreset | None = None,
    ) -> OpenCodeAgent:
        agent = OpenCodeAgent(
            problem_name="test",
            verbose=False,
            cost_limits=AgentCostLimits(
                step_limit=0, cost_limit=100.0, net_cost_limit=200.0
            ),
            pricing=None,
            credential=None,
            model_id="some-org/some-model",
            provider=provider,
            opencode_config=opencode_config or {},
            env={},
            thinking=thinking,
        )
        # Set up tmp_dir manually so _make_opencode_config works
        import tempfile

        agent._tmp_dir = tempfile.TemporaryDirectory(dir=str(tmp_path))
        return agent

    def test_empty_config_gets_schema_default(self, tmp_path):
        agent = self._make_bare_agent(
            tmp_path,
            provider="openai",
        )
        config_path = agent._make_opencode_config()

        cfg = json.loads(config_path.read_text())
        assert cfg["$schema"] == "https://opencode.ai/config.json"

    def test_existing_config_is_preserved(self, tmp_path):
        agent = self._make_bare_agent(
            tmp_path,
            provider="openai",
            opencode_config={
                "agent": {"maxSteps": 123},
                "provider": {"openai": {"options": {"baseURL": "https://x"}}},
            },
        )
        config_path = agent._make_opencode_config()

        cfg = json.loads(config_path.read_text())
        assert cfg["agent"]["maxSteps"] == 123
        assert cfg["provider"]["openai"]["options"]["baseURL"] == "https://x"

    def test_thinking_does_not_mutate_config_file(self, tmp_path):
        agent = self._make_bare_agent(
            tmp_path,
            provider="openai",
            thinking="high",
            opencode_config={
                "agent": {"maxSteps": 111},
            },
        )
        config_path = agent._make_opencode_config()

        cfg = json.loads(config_path.read_text())
        assert cfg["agent"]["maxSteps"] == 111
        assert "build" not in cfg["agent"]

    def test_non_openai_thinking_injects_agent_build_config(self, tmp_path):
        agent = self._make_bare_agent(
            tmp_path,
            provider="anthropic",
            thinking="high",
            opencode_config={},
        )
        config_path = agent._make_opencode_config()

        cfg = json.loads(config_path.read_text())
        assert cfg["agent"]["build"]["reasonEffort"] == "high"

    def test_moonshot_thinking_injects_agent_build_config(self, tmp_path):
        agent = self._make_bare_agent(
            tmp_path,
            provider="moonshot",
            thinking="medium",
            opencode_config={},
        )
        config_path = agent._make_opencode_config()

        cfg = json.loads(config_path.read_text())
        assert cfg["agent"]["build"]["reasonEffort"] == "medium"


@pytest.mark.parametrize("model_name", ["gpt-5.2-codex", "gpt-5.4-mini"])
def test_from_config_with_opencode_auth_file_mounts_auth_without_base_url(
    tmp_path,
    model_name: str,
):
    auth_source = tmp_path / "auth.json"
    auth_source.write_text(
        json.dumps({"openai": {"type": "oauth", "access": "test-token"}})
    )
    credential = ProviderCredential(
        provider="opencode_auth",
        credential_type=CredentialType.FILE,
        value=auth_source.read_text(),
        source=str(auth_source),
        destination_key="",
    )
    model = ModelCatalog.get(model_name)
    assert model is not None

    agent = OpenCodeAgent._from_config(
        config=OpenCodeAgentConfig(
            type="opencode",
            version="1.0.134",
            cost_limits=AgentCostLimits(
                step_limit=0,
                cost_limit=100.0,
                net_cost_limit=200.0,
            ),
        ),
        model=model,
        credential=credential,
        problem_name="sample-problem",
        verbose=False,
        image="test-image",
    )
    assert agent.provider == "openai"

    runtime = FakeRuntime()
    session = FakeSession(runtime=runtime, working_dir=str(tmp_path))
    agent.setup(cast("Session", session))
    assert session.spawn_kwargs is not None
    mounts = cast("dict[str, dict[str, str]]", session.spawn_kwargs["mounts"])

    assert any(
        mount.get("bind") == f"{HOME_PATH}/.local/share/opencode/auth.json"
        for mount in mounts.values()
    )
    opencode_config_source = next(
        source
        for source, mount in mounts.items()
        if mount.get("bind") == f"{HOME_PATH}/.config/opencode/opencode.json"
    )
    opencode_config = json.loads(Path(opencode_config_source).read_text())
    openai_options = (
        opencode_config.get("provider", {}).get("openai", {}).get("options", {})
    )
    assert "baseURL" not in openai_options

    agent.cleanup()


def test_run_collects_messages_and_updates_usage(make_agent):
    agent, runtime = make_agent()

    tool_use = {"type": "tool_use", "part": {"tool": "search"}}
    first_step: dict[str, Any] = {
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
    final_step: dict[str, Any] = {
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
    expected_cost = first_step["part"]["cost"] + final_step["part"]["cost"]
    assert agent.usage.cost == pytest.approx(expected_cost)
    assert (
        agent.usage.current_tokens.input
        == final_step["part"]["tokens"]["input"]
    )
    assert (
        agent.usage.current_tokens.output
        == final_step["part"]["tokens"]["output"]
    )
    assert agent.usage.net_tokens.reasoning == 3
    assert (
        agent.usage.current_tokens.cache_read
        == final_step["part"]["tokens"]["cache"]["read"]
    )
    assert agent.continue_on_run is False


def test_run_falls_back_to_pricing_when_reported_cost_is_zero(make_agent):
    agent, runtime = make_agent()

    step: dict[str, Any] = {
        "type": "step_finish",
        "part": {
            "reason": "stop",
            "cost": 0,
            "tokens": {
                "input": 1500,
                "output": 600,
                "reasoning": 0,
                "cache": {"read": 300, "write": 0},
            },
        },
    }
    runtime.events = _runtime_events_from_stdout_chunks([json.dumps(step)])

    agent.run("fallback-pricing")

    expected_cost = agent.pricing.get_cost(_token_usage_from_part(step["part"]))
    assert agent.usage.steps == 1
    assert agent.usage.cost == pytest.approx(expected_cost)
    assert agent.usage.cost > 0


def test_build_command_matches_harbor_shape(make_agent):
    agent, _ = make_agent()

    command = agent._build_opencode_command("build something cool")

    assert command == (
        "opencode --model=zai-coding-plan/glm-4.6 run --format=json "
        "--thinking --dangerously-skip-permissions -- "
        "'build something cool'"
    )


def test_build_command_for_retry_continues_last_session(make_agent):
    agent, _ = make_agent()

    command = agent._build_opencode_command(
        "continue",
        resume=True,
    )

    assert "--continue" in command


def test_build_command_includes_variant_for_thinking_level(make_agent):
    agent, _ = make_agent()
    agent.provider = "openai"
    agent.model_id = "gpt-5.4-mini"
    agent.thinking = "high"

    command = agent._build_opencode_command("build something cool")

    assert "--variant=high" in command


def test_build_command_keeps_xhigh_variant_for_openai(make_agent):
    agent, _ = make_agent()
    agent.provider = "openai"
    agent.model_id = "gpt-5.4-mini"
    agent.thinking = "xhigh"

    command = agent._build_opencode_command("build something cool")

    assert "--variant=xhigh" in command


def test_build_command_maps_xhigh_to_max_variant_for_non_openai(make_agent):
    agent, _ = make_agent()
    agent.provider = "openrouter"
    agent.model_id = "moonshotai/kimi-k2"
    agent.thinking = "xhigh"

    command = agent._build_opencode_command("build something cool")

    assert "--variant=max" in command


def test_build_command_omits_variant_for_none_thinking(make_agent):
    agent, _ = make_agent()
    agent.provider = "openai"
    agent.model_id = "gpt-5.4-mini"
    agent.thinking = "none"

    command = agent._build_opencode_command("build something cool")

    assert "--variant=" not in command


def test_from_config_falls_back_to_model_provider_when_provider_name_missing(
    tmp_path,
):
    auth_source = tmp_path / "auth.json"
    auth_source.write_text(
        json.dumps({"openai": {"type": "oauth", "access": "test-token"}})
    )
    credential = ProviderCredential(
        provider="opencode_auth",
        credential_type=CredentialType.FILE,
        value=auth_source.read_text(),
        source=str(auth_source),
        destination_key="",
    )
    model = ModelDefinition(
        internal_name="gpt-5.4-mini",
        provider="openai",
        pricing=APIPricing(
            input=0.75,
            output=4.5,
            cache_read=0.075,
            cache_write=0,
        ),
    )

    agent = OpenCodeAgent._from_config(
        config=OpenCodeAgentConfig(
            type="opencode",
            version="1.0.134",
            cost_limits=AgentCostLimits(
                step_limit=0,
                cost_limit=100.0,
                net_cost_limit=200.0,
            ),
        ),
        model=model,
        credential=credential,
        problem_name="sample-problem",
        verbose=False,
        image="test-image",
    )

    assert agent.provider == "openai"


def test_from_config_uses_provider_override_for_moonshot_kimi_model():
    model = ModelCatalog.get("kimi-k2.5")
    assert model is not None
    credential = ProviderCredential(
        provider="moonshot",
        credential_type=CredentialType.ENV_VAR,
        value="test-moonshot-key",
        source="MOONSHOT_API_KEY",
        destination_key="MOONSHOT_API_KEY",
    )

    agent = OpenCodeAgent._from_config(
        config=OpenCodeAgentConfig(
            type="opencode",
            version="1.0.134",
            cost_limits=AgentCostLimits(
                step_limit=0,
                cost_limit=100.0,
                net_cost_limit=200.0,
            ),
        ),
        model=model,
        credential=credential,
        problem_name="sample-problem",
        verbose=False,
        image="test-image",
    )

    assert agent.provider == "moonshot"
    assert agent.model_id == "kimi-k2.5"


def test_from_config_keeps_openrouter_default_for_kimi_model():
    model = ModelCatalog.get("kimi-k2.5")
    assert model is not None
    credential = ProviderCredential(
        provider="openrouter",
        credential_type=CredentialType.ENV_VAR,
        value="test-openrouter-key",
        source="OPENROUTER_API_KEY",
        destination_key="OPENROUTER_API_KEY",
    )

    agent = OpenCodeAgent._from_config(
        config=OpenCodeAgentConfig(
            type="opencode",
            version="1.0.134",
            cost_limits=AgentCostLimits(
                step_limit=0,
                cost_limit=100.0,
                net_cost_limit=200.0,
            ),
        ),
        model=model,
        credential=credential,
        problem_name="sample-problem",
        verbose=False,
        image="test-image",
    )

    assert agent.provider == "openrouter"
    assert agent.model_id == "moonshotai/kimi-k2.5"


def test_setup_exports_moonshot_api_key_for_moonshot_provider(tmp_path):
    model = ModelCatalog.get("kimi-k2.5")
    assert model is not None
    credential = ProviderCredential(
        provider="moonshot",
        credential_type=CredentialType.ENV_VAR,
        value="test-moonshot-key",
        source="MOONSHOT_API_KEY",
        destination_key="MOONSHOT_API_KEY",
    )

    agent = OpenCodeAgent._from_config(
        config=OpenCodeAgentConfig(
            type="opencode",
            version="1.0.134",
            cost_limits=AgentCostLimits(
                step_limit=0,
                cost_limit=100.0,
                net_cost_limit=200.0,
            ),
        ),
        model=model,
        credential=credential,
        problem_name="sample-problem",
        verbose=False,
        image="test-image",
    )

    runtime = FakeRuntime()
    session = FakeSession(runtime=runtime, working_dir=str(tmp_path))
    agent.setup(cast("Session", session))
    assert session.spawn_kwargs is not None
    env_vars = cast("dict[str, str]", session.spawn_kwargs["env_vars"])
    assert env_vars["MOONSHOT_API_KEY"] == "test-moonshot-key"
    agent.cleanup()


def test_provider_override_only_applies_when_model_opts_in():
    model = ModelCatalog.get("glm-5.1")
    assert model is not None
    credential = ProviderCredential(
        provider="zhipu",
        credential_type=CredentialType.ENV_VAR,
        value="test-zhipu-key",
        source="ZHIPU_API_KEY",
        destination_key="ZHIPU_API_KEY",
    )

    agent = OpenCodeAgent._from_config(
        config=OpenCodeAgentConfig(
            type="opencode",
            version="1.0.134",
            cost_limits=AgentCostLimits(
                step_limit=0,
                cost_limit=100.0,
                net_cost_limit=200.0,
            ),
        ),
        model=model,
        credential=credential,
        problem_name="sample-problem",
        verbose=False,
        image="test-image",
    )

    assert agent.provider == "openrouter"
    assert agent.model_id == "z-ai/glm-5.1"


def test_glm_5_1_openrouter_provider_order_is_preserved():
    model = ModelCatalog.get("glm-5.1")
    assert model is not None
    credential = ProviderCredential(
        provider="openrouter",
        credential_type=CredentialType.ENV_VAR,
        value="test-openrouter-key",
        source="OPENROUTER_API_KEY",
        destination_key="OPENROUTER_API_KEY",
    )

    agent = OpenCodeAgent._from_config(
        config=OpenCodeAgentConfig(
            type="opencode",
            version="1.0.134",
            cost_limits=AgentCostLimits(
                step_limit=0,
                cost_limit=100.0,
                net_cost_limit=200.0,
            ),
        ),
        model=model,
        credential=credential,
        problem_name="sample-problem",
        verbose=False,
        image="test-image",
    )

    provider_config = cast("dict[str, Any]", agent.open_code_config["provider"])
    provider_options = provider_config["openrouter"][
        "models"
    ]["z-ai/glm-5.1"]["options"]["provider"]
    assert provider_options["order"] == [
        "z-ai",
        "fireworks",
        "friendli",
        "inceptron/fp8",
    ]
    assert provider_options["allow_fallbacks"] is False


def test_setup_sets_fake_vcs_env(make_agent):
    agent, _ = make_agent()

    assert isinstance(agent.session, FakeSession)
    assert agent.session.spawn_kwargs is not None
    assert agent.session.spawn_kwargs["env_vars"]["OPENCODE_FAKE_VCS"] == "git"


def test_run_skips_invalid_json_lines(make_agent):
    agent, runtime = make_agent()

    good_step: dict[str, Any] = {
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
    assert agent.usage.cost == pytest.approx(good_step["part"]["cost"])


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


def test_run_raises_on_opencode_error_event(make_agent):
    agent, runtime = make_agent()

    error_message = {
        "type": "error",
        "error": {"message": "Model not found: zai-coding-plan/glm-5.1."},
    }
    runtime.events = _runtime_events_from_stdout_chunks(
        [json.dumps(error_message)]
    )

    with pytest.raises(AgentError, match="Model not found"):
        agent.run("trigger error")


def test_run_raises_when_no_step_finish_messages(make_agent):
    agent, runtime = make_agent()

    non_step_message = {
        "type": "tool_use",
        "part": {"tool": "read_file"},
    }
    runtime.events = _runtime_events_from_stdout_chunks(
        [json.dumps(non_step_message)]
    )

    with pytest.raises(AgentError, match="step_finish"):
        agent.run("no step finish")


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
    runtime.events = _runtime_events_from_stdout_chunks(
        [json.dumps(expensive_step)]
    )

    agent.run("too expensive")
    assert agent.messages[0] == expensive_step
    assert agent.cost_limits.is_above_limits(
        agent.usage,
        prior_cost=agent.prior_cost,
    )
    assert agent.continue_on_run is False
    assert agent.usage.cost > limits.cost_limit
