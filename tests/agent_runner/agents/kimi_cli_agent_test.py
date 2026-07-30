"""Unit tests for the Kimi CLI agent."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
import yaml

from slop_code.agent_runner.agents.kimi_cli import KimiCliAgent
from slop_code.agent_runner.agents.kimi_cli import KimiCliConfig
from slop_code.agent_runner.agents.kimi_cli.parser import _PendingToolCall
from slop_code.agent_runner.agents.kimi_cli.parser import _WireStep
from slop_code.agent_runner.agents.kimi_cli.parser import (
    group_events_into_steps,
)
from slop_code.agent_runner.agents.kimi_cli.parser import parse_wire_events
from slop_code.agent_runner.credentials import CredentialType
from slop_code.agent_runner.credentials import ProviderCredential
from slop_code.agent_runner.models import AgentCostLimits
from slop_code.agent_runner.models import AgentError
from slop_code.agent_runner.registry import build_agent_config
from slop_code.agent_runner.registry import get_agent_cls
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
        env: dict[str, str],
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
        input=1.0,
        output=2.0,
        cache_read=0.5,
        cache_write=4.0,
    )


@pytest.fixture
def mock_cost_limits() -> AgentCostLimits:
    return AgentCostLimits(
        step_limit=100,
        cost_limit=100.0,
        net_cost_limit=200.0,
    )


@pytest.fixture
def mock_model_def(mock_pricing: APIPricing) -> ModelDefinition:
    return ModelDefinition(
        internal_name="kimi-k2-5",
        provider="moonshot",
        pricing=mock_pricing,
    )


@pytest.fixture
def moonshot_credential() -> ProviderCredential:
    return ProviderCredential(
        provider="moonshot",
        credential_type=CredentialType.ENV_VAR,
        value="moonshot-key",
        source="MOONSHOT_API_KEY",
        destination_key="MOONSHOT_API_KEY",
    )


def _finished_event(
    *,
    exit_code: int,
    stdout: str = "",
    stderr: str = "",
) -> RuntimeEvent:
    return RuntimeEvent(
        kind="finished",
        result=RuntimeResult(
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            setup_stdout="",
            setup_stderr="",
            elapsed=0.05,
            timed_out=False,
        ),
    )


class TestKimiCliConfig:
    def test_version_is_required(
        self, mock_cost_limits: AgentCostLimits
    ) -> None:
        with pytest.raises(Exception):
            KimiCliConfig.model_validate(
                {
                    "type": "kimi_cli",
                    "cost_limits": mock_cost_limits,
                }
            )

    def test_get_docker_file_renders(
        self, mock_cost_limits: AgentCostLimits
    ) -> None:
        config = KimiCliConfig(
            type="kimi_cli",
            version="0.2.0",
            cost_limits=mock_cost_limits,
        )
        dockerfile = config.get_docker_file("base-image:latest")
        assert dockerfile is not None
        assert "FROM base-image:latest" in dockerfile
        assert "uv tool install --python 3.13 kimi-cli==0.2.0" in dockerfile
        assert "kimi --version" in dockerfile


class TestKimiCliWireHelpers:
    def test_parse_wire_events_filters_final_jsonrpc_result(self) -> None:
        lines = [
            (
                '{"jsonrpc":"2.0","method":"event","params":{"type":"StepBegin",'
                '"payload":{"n":1}}}'
            ),
            (
                '{"jsonrpc":"2.0","method":"event","params":{"type":"StatusUpdate",'
                '"payload":{"token_usage":{"input_other":10,"output":2,'
                '"input_cache_read":3,"input_cache_creation":4}}}}'
            ),
            '{"jsonrpc":"2.0","id":"1","result":{"status":"finished"}}',
        ]
        events = parse_wire_events("\n".join(lines))
        assert [event["type"] for event in events] == [
            "StepBegin",
            "StatusUpdate",
        ]

    def test_parse_wire_events_handles_multiline_tool_result(self) -> None:
        tool_result = (
            '{"jsonrpc":"2.0","method":"event","params":{"type":"ToolResult",'
            '"payload":{"tool_call_id":"ReadFile:0","return_value":{"is_error":false,'
            '"output":"     1\\tdef foo():\\n     2\\t    pass\\n","message":"ok"}}}}'
        )
        raw_tool_result = tool_result.replace("\\t", "\t").replace("\\n", "\n")
        raw = (
            '{"jsonrpc":"2.0","method":"event","params":{"type":"StepBegin",'
            '"payload":{"n":1}}}\n'
            f"{raw_tool_result}\n"
            '{"jsonrpc":"2.0","method":"event","params":{"type":"TurnEnd",'
            '"payload":{}}}\n'
        )
        events = parse_wire_events(raw)
        assert [event["type"] for event in events] == [
            "StepBegin",
            "ToolResult",
            "TurnEnd",
        ]

    def test_wire_step_finalize_pending_tool_invalid_json_falls_back(
        self,
    ) -> None:
        step = _WireStep(n=1)
        step.pending_tool = _PendingToolCall(
            call_id="tool-1",
            name="Shell",
            arguments_buffer="{oops",
        )
        step.finalize_pending_tool()
        assert step.pending_tool is None
        assert step.tool_calls[0]["arguments"] == {"raw": "{oops"}

    def test_group_events_concatenates_tool_argument_chunks(self) -> None:
        events = [
            {"type": "StepBegin", "payload": {"n": 1}},
            {
                "type": "ToolCall",
                "payload": {
                    "id": "ReadFile:0",
                    "function": {"name": "ReadFile", "arguments": ""},
                },
            },
            {"type": "ToolCallPart", "payload": {"arguments_part": '{"path"'}},
            {
                "type": "ToolCallPart",
                "payload": {"arguments_part": ':"/a.py"}'},
            },
            {"type": "TurnEnd", "payload": {}},
        ]
        steps = group_events_into_steps(events)
        assert len(steps) == 1
        assert steps[0].tool_calls[0]["name"] == "ReadFile"
        assert steps[0].tool_calls[0]["arguments"] == {"path": "/a.py"}


class TestKimiCliAgent:
    def test_from_config_creates_agent(
        self,
        mock_cost_limits: AgentCostLimits,
        mock_model_def: ModelDefinition,
        moonshot_credential: ProviderCredential,
    ) -> None:
        config = KimiCliConfig(
            type="kimi_cli",
            version="0.2.0",
            cost_limits=mock_cost_limits,
        )
        agent = KimiCliAgent._from_config(
            config=config,
            model=mock_model_def,
            credential=moonshot_credential,
            problem_name="demo-problem",
            verbose=False,
            image="kimi-image",
        )
        assert isinstance(agent, KimiCliAgent)
        assert agent.model == "kimi-k2-5"
        assert agent.provider == "moonshot"

    def test_from_config_wires_thinking_preset(
        self,
        mock_cost_limits: AgentCostLimits,
        mock_model_def: ModelDefinition,
        moonshot_credential: ProviderCredential,
    ) -> None:
        config = KimiCliConfig(
            type="kimi_cli",
            version="0.2.0",
            cost_limits=mock_cost_limits,
        )
        agent = KimiCliAgent._from_config(
            config=config,
            model=mock_model_def,
            credential=moonshot_credential,
            problem_name="demo-problem",
            verbose=False,
            image="kimi-image",
            thinking_preset="high",
        )
        assert isinstance(agent, KimiCliAgent)
        assert agent.thinking == "high"
        assert agent.max_thinking_tokens is None

    def test_build_config_json_rejects_unsupported_provider(
        self,
        mock_cost_limits: AgentCostLimits,
        mock_pricing: APIPricing,
    ) -> None:
        agent = KimiCliAgent(
            problem_name="demo-problem",
            verbose=False,
            image="kimi-image",
            cost_limits=mock_cost_limits,
            pricing=mock_pricing,
            credential=None,
            binary="kimi",
            provider="moonshot",
            model="kimi-k2-5",
            timeout=None,
            extra_args=[],
            env={},
            base_url=None,
            max_context_size=None,
        )
        with pytest.raises(ValueError, match="Unsupported provider"):
            agent._build_config_json(provider="openai", model="gpt-4.1")

    def test_build_config_json_uses_moonshot_ai_base_url_by_default(
        self,
        mock_cost_limits: AgentCostLimits,
        mock_pricing: APIPricing,
        moonshot_credential: ProviderCredential,
    ) -> None:
        agent = KimiCliAgent(
            problem_name="demo-problem",
            verbose=False,
            image="kimi-image",
            cost_limits=mock_cost_limits,
            pricing=mock_pricing,
            credential=moonshot_credential,
            binary="kimi",
            provider="moonshot",
            model="kimi-k2-5",
            timeout=None,
            extra_args=[],
            env={},
            base_url=None,
            max_context_size=None,
        )
        payload = json.loads(
            agent._build_config_json(provider="moonshot", model="kimi-k2.5")
        )
        assert (
            payload["providers"]["slop_code"]["base_url"]
            == "https://api.moonshot.ai/v1"
        )

    def test_parse_line_uses_event_only_and_ignores_final_result(
        self, mock_pricing: APIPricing
    ) -> None:
        status_line = (
            '{"jsonrpc":"2.0","method":"event","params":{"type":"StatusUpdate",'
            '"payload":{"token_usage":{"input_other":10,"output":2,'
            '"input_cache_read":3,"input_cache_creation":4}}}}'
        )
        cost, tokens, payload = KimiCliAgent.parse_line(
            status_line, pricing=mock_pricing
        )
        assert payload is not None
        assert payload["type"] == "StatusUpdate"
        assert tokens is not None
        assert tokens.input == 17
        assert tokens.output == 2
        assert tokens.cache_read == 3
        assert tokens.cache_write == 4
        assert tokens.reasoning == 0
        assert cost == pytest.approx(35.5 / 1_000_000)

        final_result = (
            '{"jsonrpc":"2.0","id":"1","result":{"status":"finished"}}'
        )
        assert KimiCliAgent.parse_line(final_result, pricing=mock_pricing) == (
            None,
            None,
            None,
        )

    def test_summarize_wire_steps_keeps_cache_fields_distinct(
        self,
        mock_cost_limits: AgentCostLimits,
        mock_pricing: APIPricing,
    ) -> None:
        agent = KimiCliAgent(
            problem_name="demo-problem",
            verbose=False,
            image="kimi-image",
            cost_limits=mock_cost_limits,
            pricing=mock_pricing,
            credential=None,
            binary="kimi",
            provider="moonshot",
            model="kimi-k2-5",
            timeout=None,
            extra_args=[],
            env={},
            base_url=None,
            max_context_size=None,
        )
        steps = [
            _WireStep(
                n=1,
                token_usage={
                    "input_other": 100,
                    "output": 20,
                    "input_cache_read": 30,
                    "input_cache_creation": 40,
                },
            )
        ]
        totals = agent._summarize_wire_steps(steps)
        assert totals["input_tokens"] == 170
        assert totals["output_tokens"] == 20
        assert totals["cached_input_tokens"] == 30
        assert totals["cached_write_tokens"] == 40
        assert totals["reasoning_tokens"] == 0

    def test_parse_line_reads_reasoning_tokens_when_available(
        self, mock_pricing: APIPricing
    ) -> None:
        status_line = (
            '{"jsonrpc":"2.0","method":"event","params":{"type":"StatusUpdate",'
            '"payload":{"token_usage":{"input_other":10,"output":2,'
            '"input_cache_read":3,"input_cache_creation":4,'
            '"output_reasoning_tokens":11}}}}'
        )
        _cost, tokens, _payload = KimiCliAgent.parse_line(
            status_line, pricing=mock_pricing
        )
        assert tokens is not None
        assert tokens.reasoning == 11

    def test_prepare_runtime_execution_has_wire_flags_and_id_termination(
        self,
        mock_cost_limits: AgentCostLimits,
        mock_pricing: APIPricing,
        moonshot_credential: ProviderCredential,
    ) -> None:
        agent = KimiCliAgent(
            problem_name="demo-problem",
            verbose=False,
            image="kimi-image",
            cost_limits=mock_cost_limits,
            pricing=mock_pricing,
            credential=moonshot_credential,
            binary="kimi",
            provider="moonshot",
            model="kimi-k2-5",
            timeout=120,
            extra_args=[],
            env={},
            base_url=None,
            max_context_size=None,
        )
        command, env = agent._prepare_runtime_execution("solve task")
        command_text = " ".join(command)
        assert "--config-file /tmp/kimi-config.json" in command_text
        assert "--wire" in command_text
        assert "--yolo" in command_text
        assert '"id":"1"' in command_text
        assert env["MOONSHOT_API_KEY"] == "moonshot-key"

    def test_prepare_runtime_execution_enables_thinking_for_high_preset(
        self,
        mock_cost_limits: AgentCostLimits,
        mock_pricing: APIPricing,
        moonshot_credential: ProviderCredential,
    ) -> None:
        agent = KimiCliAgent(
            problem_name="demo-problem",
            verbose=False,
            image="kimi-image",
            cost_limits=mock_cost_limits,
            pricing=mock_pricing,
            credential=moonshot_credential,
            binary="kimi",
            provider="moonshot",
            model="kimi-k2-5",
            timeout=120,
            extra_args=[],
            env={},
            base_url=None,
            max_context_size=None,
            thinking="high",
        )
        command, _ = agent._prepare_runtime_execution("solve task")
        command_text = " ".join(command)
        assert " --thinking " in command_text
        assert "--no-thinking" not in command_text

    def test_prepare_runtime_execution_disables_thinking_for_none(
        self,
        mock_cost_limits: AgentCostLimits,
        mock_pricing: APIPricing,
        moonshot_credential: ProviderCredential,
    ) -> None:
        agent = KimiCliAgent(
            problem_name="demo-problem",
            verbose=False,
            image="kimi-image",
            cost_limits=mock_cost_limits,
            pricing=mock_pricing,
            credential=moonshot_credential,
            binary="kimi",
            provider="moonshot",
            model="kimi-k2-5",
            timeout=120,
            extra_args=[],
            env={},
            base_url=None,
            max_context_size=None,
            thinking="none",
        )
        command, _ = agent._prepare_runtime_execution("solve task")
        command_text = " ".join(command)
        assert "--no-thinking" in command_text
        assert " --thinking " not in command_text

    def test_prepare_runtime_execution_enables_thinking_for_token_budget(
        self,
        mock_cost_limits: AgentCostLimits,
        mock_pricing: APIPricing,
        moonshot_credential: ProviderCredential,
    ) -> None:
        agent = KimiCliAgent(
            problem_name="demo-problem",
            verbose=False,
            image="kimi-image",
            cost_limits=mock_cost_limits,
            pricing=mock_pricing,
            credential=moonshot_credential,
            binary="kimi",
            provider="moonshot",
            model="kimi-k2-5",
            timeout=120,
            extra_args=[],
            env={},
            base_url=None,
            max_context_size=None,
            thinking=None,
            max_thinking_tokens=1024,
        )
        command, _ = agent._prepare_runtime_execution("solve task")
        command_text = " ".join(command)
        assert " --thinking " in command_text
        assert "--no-thinking" not in command_text

    def test_run_invocation_increments_live_steps_during_stream(
        self,
        tmp_path: Path,
        mock_cost_limits: AgentCostLimits,
        mock_pricing: APIPricing,
        moonshot_credential: ProviderCredential,
    ) -> None:
        runtime = FakeRuntime()
        runtime.events = [
            RuntimeEvent(
                kind="stdout",
                text=(
                    '{"jsonrpc":"2.0","method":"event","params":{"type":"StepBegin",'
                    '"payload":{"n":1}}}\n'
                    '{"jsonrpc":"2.0","method":"event","params":{"type":"TurnEnd",'
                    '"payload":{}}}\n'
                    '{"jsonrpc":"2.0","id":"1","result":{"status":"finished"}}\n'
                ),
            ),
            _finished_event(exit_code=0),
        ]
        session = FakeSession(
            runtime=runtime,
            working_dir=tmp_path,
            spec=SimpleNamespace(type="docker"),
        )
        agent = KimiCliAgent(
            problem_name="demo-problem",
            verbose=False,
            image="kimi-image",
            cost_limits=mock_cost_limits,
            pricing=mock_pricing,
            credential=moonshot_credential,
            binary="kimi",
            provider="moonshot",
            model="kimi-k2-5",
            timeout=120,
            extra_args=[],
            env={},
            base_url=None,
            max_context_size=None,
        )
        agent.setup(cast("Session", session))
        result = agent._run_invocation("solve task")
        assert agent.usage.steps == 1
        assert result.usage_totals["steps"] == 1
        assert result.usage_totals["live_steps"] == 1

    def test_run_allows_exit_143_after_final_result(
        self,
        tmp_path: Path,
        mock_cost_limits: AgentCostLimits,
        mock_pricing: APIPricing,
        moonshot_credential: ProviderCredential,
    ) -> None:
        runtime = FakeRuntime()
        runtime.events = [
            RuntimeEvent(
                kind="stdout",
                text=(
                    '{"jsonrpc":"2.0","method":"event","params":{"type":"StepBegin",'
                    '"payload":{"n":1}}}\n'
                ),
            ),
            RuntimeEvent(
                kind="stdout",
                text=(
                    '{"jsonrpc":"2.0","method":"event","params":{"type":"StatusUpdate",'
                    '"payload":{"token_usage":{"input_other":10,"output":2,'
                    '"input_cache_read":3,"input_cache_creation":4}}}}\n'
                    '{"jsonrpc":"2.0","method":"event","params":{"type":"TurnEnd",'
                    '"payload":{}}}\n'
                    '{"jsonrpc":"2.0","id":"1","result":{"status":"finished"}}\n'
                ),
            ),
            _finished_event(exit_code=143),
        ]
        session = FakeSession(
            runtime=runtime,
            working_dir=tmp_path,
            spec=SimpleNamespace(type="docker"),
        )
        agent = KimiCliAgent(
            problem_name="demo-problem",
            verbose=False,
            image="kimi-image",
            cost_limits=mock_cost_limits,
            pricing=mock_pricing,
            credential=moonshot_credential,
            binary="kimi",
            provider="moonshot",
            model="kimi-k2-5",
            timeout=120,
            extra_args=[],
            env={},
            base_url=None,
            max_context_size=None,
        )
        agent.setup(cast("Session", session))
        agent.run("solve task")
        assert agent.usage.steps == 1

    def test_run_rejects_exit_143_without_final_result(
        self,
        tmp_path: Path,
        mock_cost_limits: AgentCostLimits,
        mock_pricing: APIPricing,
        moonshot_credential: ProviderCredential,
    ) -> None:
        runtime = FakeRuntime()
        runtime.events = [_finished_event(exit_code=143)]
        session = FakeSession(
            runtime=runtime,
            working_dir=tmp_path,
            spec=SimpleNamespace(type="docker"),
        )
        agent = KimiCliAgent(
            problem_name="demo-problem",
            verbose=False,
            image="kimi-image",
            cost_limits=mock_cost_limits,
            pricing=mock_pricing,
            credential=moonshot_credential,
            binary="kimi",
            provider="moonshot",
            model="kimi-k2-5",
            timeout=120,
            extra_args=[],
            env={},
            base_url=None,
            max_context_size=None,
        )
        agent.setup(cast("Session", session))
        with pytest.raises(AgentError, match="exit code 143"):
            agent.run("solve task")

    def test_registry_exposes_kimi_cli(self) -> None:
        data = yaml.safe_load(Path("configs/agents/kimi_cli.yaml").read_text())
        config = build_agent_config(data)
        assert isinstance(config, KimiCliConfig)
        assert get_agent_cls("kimi_cli") is KimiCliAgent

    def test_save_artifacts_writes_stdout_and_trajectory_jsonl(
        self,
        tmp_path: Path,
        mock_cost_limits: AgentCostLimits,
        mock_pricing: APIPricing,
        moonshot_credential: ProviderCredential,
    ) -> None:
        agent = KimiCliAgent(
            problem_name="demo-problem",
            verbose=False,
            image="kimi-image",
            cost_limits=mock_cost_limits,
            pricing=mock_pricing,
            credential=moonshot_credential,
            binary="kimi",
            provider="moonshot",
            model="kimi-k2-5",
            timeout=120,
            extra_args=[],
            env={},
            base_url=None,
            max_context_size=None,
        )
        agent._last_prompt = "solve task"
        agent._last_command_text = "kimi --wire --yolo"
        agent._last_stdout = (
            '{"jsonrpc":"2.0","method":"event","params":{"type":"StepBegin",'
            '"payload":{"n":1}}}\n'
            '{"jsonrpc":"2.0","method":"event","params":{"type":"ContentPart",'
            '"payload":{"type":"text","text":"done"}}}\n'
            '{"jsonrpc":"2.0","method":"event","params":{"type":"StatusUpdate",'
            '"payload":{"token_usage":{"input_other":10,"output":2,'
            '"input_cache_read":3,"input_cache_creation":4}}}}\n'
            '{"jsonrpc":"2.0","method":"event","params":{"type":"TurnEnd",'
            '"payload":{}}}\n'
            '{"jsonrpc":"2.0","id":"1","result":{"status":"finished"}}\n'
        )
        agent._last_events = parse_wire_events(agent._last_stdout)

        artifact_dir = tmp_path / "agent"
        agent.save_artifacts(artifact_dir)

        assert (artifact_dir / "stdout.log").read_text(encoding="utf-8") == (
            agent._last_stdout
        )

        trajectory_lines = (
            (artifact_dir / "trajectory.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        )
        assert len(trajectory_lines) == 1
        row = json.loads(trajectory_lines[0])
        assert row["step_id"] == 1
        assert row["message"] == "ASSISTANT:\ndone"
        assert "reasoning" not in row
        assert "tool_calls" not in row
        assert "tool_results" not in row
        assert row["metrics"]["prompt_tokens"] == 17
        assert row["metrics"]["completion_tokens"] == 2

        event_lines = (
            (artifact_dir / "events.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        )
        assert len(event_lines) == 1
        event = json.loads(event_lines[0])
        assert event["type"] == "step"
        assert event["step_id"] == 1
        assert event["assistant_chars"] == 4
        assert event["tool_call_count"] == 0

    def test_save_artifacts_compacts_reasoning_and_tool_payloads(
        self,
        tmp_path: Path,
        mock_cost_limits: AgentCostLimits,
        mock_pricing: APIPricing,
        moonshot_credential: ProviderCredential,
    ) -> None:
        agent = KimiCliAgent(
            problem_name="demo-problem",
            verbose=False,
            image="kimi-image",
            cost_limits=mock_cost_limits,
            pricing=mock_pricing,
            credential=moonshot_credential,
            binary="kimi",
            provider="moonshot",
            model="kimi-k2-5",
            timeout=120,
            extra_args=[],
            env={},
            base_url=None,
            max_context_size=None,
        )
        large_content = "x" * 1000
        agent._last_stdout = (
            '{"jsonrpc":"2.0","method":"event","params":{"type":"StepBegin",'
            '"payload":{"n":1}}}\n'
            '{"jsonrpc":"2.0","method":"event","params":{"type":"ContentPart",'
            '"payload":{"type":"think","think":"plan action"}}}\n'
            '{"jsonrpc":"2.0","method":"event","params":{"type":"ToolCall",'
            '"payload":{"id":"WriteFile:0","function":{"name":"WriteFile",'
            '"arguments":""}}}}\n'
            '{"jsonrpc":"2.0","method":"event","params":{"type":"ToolCallPart",'
            f'"payload":{{"arguments_part":"{{\\"path\\":\\"/tmp/a.py\\",\\"content\\":\\"{large_content}\\"}}"}}}}\n'
            '{"jsonrpc":"2.0","method":"event","params":{"type":"ToolResult",'
            '"payload":{"tool_call_id":"WriteFile:0","return_value":{"is_error":false,'
            '"output":"ok","message":"written"}}}}\n'
            '{"jsonrpc":"2.0","method":"event","params":{"type":"TurnEnd",'
            '"payload":{}}}\n'
        )
        agent._last_events = parse_wire_events(agent._last_stdout)

        artifact_dir = tmp_path / "agent"
        agent.save_artifacts(artifact_dir)

        row = json.loads(
            (artifact_dir / "trajectory.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()[0]
        )
        assert "THOUGHT:" in row["message"]
        assert "ACTION:" in row["message"]
        assert "RESULT:" in row["message"]
        assert large_content not in row["message"]
        assert len(row["message"]) < 500

        event = json.loads(
            (artifact_dir / "events.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()[0]
        )
        assert event["tool_call_count"] == 1
        assert event["tool_names"] == ["WriteFile"]
