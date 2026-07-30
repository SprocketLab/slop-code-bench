"""Unit tests for the Cursor CLI agent."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from slop_code.agent_runner.agents.cursor_cli import CursorCliAgent
from slop_code.agent_runner.agents.cursor_cli import CursorCliConfig
from slop_code.agent_runner.credentials import CredentialType
from slop_code.agent_runner.credentials import ProviderCredential
from slop_code.agent_runner.models import AgentCostLimits
from slop_code.agent_runner.models import AgentError
from slop_code.common.llms import APIPricing
from slop_code.common.llms import ModelDefinition
from slop_code.execution.runtime import RuntimeEvent
from slop_code.execution.runtime import RuntimeResult
from slop_code.execution.session import Session


class FakeRuntime:
    """Minimal runtime stub for testing."""

    def __init__(self) -> None:
        self.events: list[RuntimeEvent] = []
        self.cleaned = False
        self.last_stream_args: tuple[tuple, dict] | None = None

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


@dataclass
class FakeSession:
    """Fake session for testing."""

    runtime: FakeRuntime
    working_dir: Path
    spec: object | None = None

    def spawn(self, **_: object) -> FakeRuntime:
        return self.runtime


@pytest.fixture
def mock_pricing() -> APIPricing:
    return APIPricing(
        input=3.0,
        output=15.0,
        cache_read=0.30,
        cache_write=3.75,
    )


@pytest.fixture
def mock_cost_limits() -> AgentCostLimits:
    return AgentCostLimits(
        step_limit=10,
        cost_limit=100.0,
        net_cost_limit=200.0,
    )


@pytest.fixture
def mock_model_def(mock_pricing: APIPricing) -> ModelDefinition:
    return ModelDefinition(
        internal_name="claude-sonnet-4-5-20250929",
        provider="anthropic",
        pricing=mock_pricing,
        aliases=["sonnet-4.5"],
    )


@pytest.fixture
def mock_credential() -> ProviderCredential:
    return ProviderCredential(
        provider="cursor",
        credential_type=CredentialType.ENV_VAR,
        value="cursor-key",
        source="CURSOR_API_KEY",
        destination_key="CURSOR_API_KEY",
    )


class TestCursorCliConfig:
    def test_version_is_required(
        self, mock_cost_limits: AgentCostLimits
    ) -> None:
        with pytest.raises(Exception):  # Pydantic validation error
            CursorCliConfig.model_validate(
                {
                    "type": "cursor_cli",
                    "cost_limits": mock_cost_limits,
                }
            )

    def test_get_docker_file_renders(
        self, mock_cost_limits: AgentCostLimits
    ) -> None:
        config = CursorCliConfig(
            type="cursor_cli",
            version="latest",
            cost_limits=mock_cost_limits,
        )
        dockerfile = config.get_docker_file("base-image:latest")
        assert dockerfile is not None
        assert "FROM base-image:latest" in dockerfile
        assert '"$HOME/.local/bin/cursor-agent" --version' in dockerfile


class TestCursorCliAgent:
    def test_from_config_creates_agent(
        self,
        mock_cost_limits: AgentCostLimits,
        mock_model_def: ModelDefinition,
        mock_credential: ProviderCredential,
    ) -> None:
        config = CursorCliConfig(
            type="cursor_cli",
            version="latest",
            cost_limits=mock_cost_limits,
        )
        agent = CursorCliAgent._from_config(
            config=config,
            model=mock_model_def,
            credential=mock_credential,
            problem_name="demo-problem",
            verbose=False,
            image="cursor-image",
        )
        assert isinstance(agent, CursorCliAgent)
        assert agent.binary == "cursor-agent"
        assert agent.model == "claude-sonnet-4-5-20250929"

    def test_from_config_requires_image(
        self,
        mock_cost_limits: AgentCostLimits,
        mock_model_def: ModelDefinition,
        mock_credential: ProviderCredential,
    ) -> None:
        config = CursorCliConfig(
            type="cursor_cli",
            version="latest",
            cost_limits=mock_cost_limits,
        )
        with pytest.raises(ValueError, match="requires an image"):
            CursorCliAgent._from_config(
                config=config,
                model=mock_model_def,
                credential=mock_credential,
                problem_name="demo-problem",
                verbose=False,
                image=None,
            )

    def test_build_command_with_mode_and_extra_args(
        self, mock_cost_limits: AgentCostLimits, mock_pricing: APIPricing
    ) -> None:
        agent = CursorCliAgent(
            problem_name="demo-problem",
            verbose=False,
            image="cursor-image",
            cost_limits=mock_cost_limits,
            pricing=mock_pricing,
            credential=None,
            binary="cursor-agent",
            model="sonnet-4.5",
            mode="plan",
            timeout=None,
            extra_args=["--foo", "bar"],
            env={},
        )
        command = agent._build_command("fix bug")
        command_text = " ".join(command)

        assert "cursor-agent" in command_text
        assert "--yolo" in command_text
        assert "--print" in command_text
        assert "--output-format=stream-json" in command_text
        assert "--model=sonnet-4.5" in command_text
        assert "--mode=plan" in command_text
        assert "--foo" in command_text
        assert "bar" in command_text

    def test_run_requires_cursor_api_key(
        self,
        tmp_path: Path,
        mock_cost_limits: AgentCostLimits,
        mock_pricing: APIPricing,
    ) -> None:
        runtime = FakeRuntime()
        runtime.events = [
            RuntimeEvent(
                kind="finished",
                text=None,
                result=RuntimeResult(
                    exit_code=0,
                    stdout="",
                    stderr="",
                    setup_stdout="",
                    setup_stderr="",
                    elapsed=0.01,
                    timed_out=False,
                ),
            )
        ]
        session = FakeSession(
            runtime=runtime,
            working_dir=tmp_path,
            spec=SimpleNamespace(type="docker"),
        )
        agent = CursorCliAgent(
            problem_name="demo-problem",
            verbose=False,
            image="cursor-image",
            cost_limits=mock_cost_limits,
            pricing=mock_pricing,
            credential=ProviderCredential(
                provider="anthropic",
                credential_type=CredentialType.ENV_VAR,
                value="wrong-key",
                source="ANTHROPIC_API_KEY",
                destination_key="ANTHROPIC_API_KEY",
            ),
            binary="cursor-agent",
            model="sonnet-4.5",
            mode=None,
            timeout=None,
            extra_args=[],
            env={},
        )
        agent.setup(cast("Session", session))

        with pytest.raises(AgentError, match="CURSOR_API_KEY"):
            agent.run("do a task")

    def test_save_artifacts_writes_expected_files(
        self,
        tmp_path: Path,
        mock_cost_limits: AgentCostLimits,
        mock_pricing: APIPricing,
    ) -> None:
        runtime = FakeRuntime()
        session = FakeSession(
            runtime=runtime,
            working_dir=tmp_path,
            spec=SimpleNamespace(type="docker"),
        )
        agent = CursorCliAgent(
            problem_name="demo-problem",
            verbose=False,
            image="cursor-image",
            cost_limits=mock_cost_limits,
            pricing=mock_pricing,
            credential=None,
            binary="cursor-agent",
            model="sonnet-4.5",
            mode=None,
            timeout=None,
            extra_args=[],
            env={},
        )
        agent.setup(cast("Session", session))
        agent._last_prompt = "test prompt"
        agent._last_command_text = "cursor-agent --yolo --print"
        agent._last_command_stdout = '{"type":"system","subtype":"init"}\n'
        agent._last_command_stderr = "stderr text"

        output_dir = tmp_path / "artifacts"
        agent.save_artifacts(output_dir)

        assert (output_dir / "prompt.txt").read_text(
            encoding="utf-8"
        ) == "test prompt"
        assert (output_dir / "command.txt").read_text(
            encoding="utf-8"
        ) == "cursor-agent --yolo --print"
        assert (output_dir / "stdout.jsonl").exists()
        assert (output_dir / "stderr.log").read_text(
            encoding="utf-8"
        ) == "stderr text"

    def test_save_artifacts_writes_empty_stderr_file(
        self,
        tmp_path: Path,
        mock_cost_limits: AgentCostLimits,
        mock_pricing: APIPricing,
    ) -> None:
        runtime = FakeRuntime()
        session = FakeSession(
            runtime=runtime,
            working_dir=tmp_path,
            spec=SimpleNamespace(type="docker"),
        )
        agent = CursorCliAgent(
            problem_name="demo-problem",
            verbose=False,
            image="cursor-image",
            cost_limits=mock_cost_limits,
            pricing=mock_pricing,
            credential=None,
            binary="cursor-agent",
            model="sonnet-4.5",
            mode=None,
            timeout=None,
            extra_args=[],
            env={},
        )
        agent.setup(cast("Session", session))
        agent._last_prompt = "test prompt"
        agent._last_command_stdout = '{"type":"system","subtype":"init"}\n'
        agent._last_command_stderr = ""

        output_dir = tmp_path / "artifacts-empty-stderr"
        agent.save_artifacts(output_dir)

        assert (output_dir / "stderr.log").exists()
        assert (output_dir / "stderr.log").read_text(encoding="utf-8") == ""

    def test_run_tracks_usage_from_stderr(
        self,
        tmp_path: Path,
        mock_cost_limits: AgentCostLimits,
        mock_pricing: APIPricing,
    ) -> None:
        stderr_payload = (
            '{"type":"result","usage":{"inputTokens":0,"outputTokens":1000,'
            '"cacheReadTokens":2000,"cacheWriteTokens":100}}\n'
        )
        runtime = FakeRuntime()
        runtime.events = [
            RuntimeEvent(kind="stderr", text=stderr_payload, result=None),
            RuntimeEvent(
                kind="finished",
                text=None,
                result=RuntimeResult(
                    exit_code=0,
                    stdout="",
                    stderr=stderr_payload,
                    setup_stdout="",
                    setup_stderr="",
                    elapsed=0.05,
                    timed_out=False,
                ),
            ),
        ]
        session = FakeSession(
            runtime=runtime,
            working_dir=tmp_path,
            spec=SimpleNamespace(type="docker"),
        )
        agent = CursorCliAgent(
            problem_name="demo-problem",
            verbose=False,
            image="cursor-image",
            cost_limits=mock_cost_limits,
            pricing=mock_pricing,
            credential=ProviderCredential(
                provider="cursor",
                credential_type=CredentialType.ENV_VAR,
                value="cursor-key",
                source="CURSOR_API_KEY",
                destination_key="CURSOR_API_KEY",
            ),
            binary="cursor-agent",
            model="sonnet-4.5",
            mode=None,
            timeout=None,
            extra_args=[],
            env={},
        )
        agent.setup(cast("Session", session))

        agent.run("do task")

        assert agent.usage.net_tokens.output == 1000
        assert agent.usage.net_tokens.cache_read == 2000
        assert agent.usage.net_tokens.cache_write == 100
        expected_cost = mock_pricing.get_cost(agent.usage.net_tokens)
        assert agent.usage.cost == pytest.approx(expected_cost)


class TestCursorCliAgentParseLine:
    def test_parse_line_result_usage(self, mock_pricing: APIPricing) -> None:
        line = (
            '{"type":"result","usage":{"inputTokens":1000,"outputTokens":50,'
            '"cacheReadTokens":100,"cacheWriteTokens":20}}'
        )
        cost, tokens, payload = CursorCliAgent.parse_line(
            line, pricing=mock_pricing
        )

        assert cost is not None
        assert tokens is not None
        assert payload is not None
        assert tokens.input == 1000
        assert tokens.output == 50
        assert tokens.cache_read == 100
        assert tokens.cache_write == 20

    def test_parse_line_non_result_event(
        self, mock_pricing: APIPricing
    ) -> None:
        line = '{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"Hi"}]}}'
        cost, tokens, payload = CursorCliAgent.parse_line(
            line, pricing=mock_pricing
        )

        assert cost is None
        assert tokens is None
        assert payload is not None
        assert payload["type"] == "assistant"

    def test_parse_line_invalid_json(self, mock_pricing: APIPricing) -> None:
        cost, tokens, payload = CursorCliAgent.parse_line(
            "not-json", pricing=mock_pricing
        )
        assert cost is None
        assert tokens is None
        assert payload == {}


class TestCursorCliAgentRegistration:
    def test_agent_is_registered(self) -> None:
        from slop_code.agent_runner.registry import available_agent_types
        from slop_code.agent_runner.registry import get_agent_cls

        assert "cursor_cli" in available_agent_types()
        assert get_agent_cls("cursor_cli") is CursorCliAgent
