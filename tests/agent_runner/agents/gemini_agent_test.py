"""Unit tests for the Gemini agent."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import cast
from unittest.mock import MagicMock

import pytest

from slop_code.agent_runner.agents.gemini import GeminiAgent
from slop_code.agent_runner.agents.gemini import GeminiConfig
from slop_code.agent_runner.credentials import CredentialType
from slop_code.agent_runner.credentials import ProviderCredential
from slop_code.agent_runner.models import AgentCostLimits
from slop_code.agent_runner.models import AgentError
from slop_code.common.llms import APIPricing
from slop_code.common.llms import APIPricingTier
from slop_code.common.llms import ModelDefinition
from slop_code.execution import DockerEnvironmentSpec
from slop_code.execution.runtime import RuntimeEvent
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
        stdin: str | list[str] | None = None,
        timeout: float | None = None,
    ) -> Iterable[RuntimeEvent]:
        self.last_stream_args = ((command, env, stdin, timeout), {})
        yield from self.events

    def cleanup(self) -> None:
        self.cleaned = True


@dataclass
class FakeDockerSpec:
    """Fake docker spec for testing."""

    workdir: str = "/workspace"
    image: str = "test-image"


@dataclass
class FakeSession:
    """Fake session for testing."""

    runtime: FakeRuntime
    working_dir: Path
    spec: DockerEnvironmentSpec | None = None

    def spawn(self, **_: object) -> FakeRuntime:
        return self.runtime


@pytest.fixture
def mock_pricing():
    """Standard pricing for tests."""
    return APIPricing(
        input=0.15,
        output=0.60,
        cache_read=0.0375,
    )


@pytest.fixture
def mock_cost_limits():
    """Standard cost limits for tests."""
    return AgentCostLimits(
        step_limit=10,
        cost_limit=100.0,
        net_cost_limit=200.0,
    )


@pytest.fixture
def mock_model_def(mock_pricing):
    """ModelDefinition for testing."""
    return ModelDefinition(
        internal_name="gemini-2.5-flash",
        provider="google",
        pricing=mock_pricing,
    )


@pytest.fixture
def mock_credential():
    """ProviderCredential for testing."""
    return ProviderCredential(
        provider="google",
        credential_type=CredentialType.ENV_VAR,
        value="test-api-key",
        source="GEMINI_API_KEY",
        destination_key="GEMINI_API_KEY",
    )


class TestGeminiConfig:
    """Tests for GeminiConfig."""

    def test_version_is_required(self, mock_cost_limits):
        """Version field is required for docker template."""
        with pytest.raises(Exception):  # Pydantic validation error
            GeminiConfig.model_validate(
                {
                    "type": "gemini",
                    "cost_limits": mock_cost_limits,
                    # Missing version
                }
            )

    def test_config_with_version(self, mock_cost_limits):
        """Config can be created with version."""
        config = GeminiConfig(
            type="gemini",
            version="1.0.0",
            cost_limits=mock_cost_limits,
        )
        assert config.version == "1.0.0"
        assert config.binary == "gemini"

    def test_get_docker_file_renders_version(self, mock_cost_limits):
        """get_docker_file renders version into template."""
        config = GeminiConfig(
            type="gemini",
            version="2.5.0",
            cost_limits=mock_cost_limits,
        )
        dockerfile = config.get_docker_file("base-image:latest")
        assert dockerfile is not None
        assert "base-image:latest" in dockerfile
        assert "@google/gemini-cli@2.5.0" in dockerfile

    def test_config_defaults(self, mock_cost_limits):
        """Config has expected defaults."""
        config = GeminiConfig(
            type="gemini",
            version="1.0.0",
            cost_limits=mock_cost_limits,
        )
        assert config.binary == "gemini"
        assert config.extra_args == []
        assert config.env == {}
        assert config.use_vertex is False
        assert config.timeout is None
        # Config no longer has model - it comes from ModelDefinition


class TestGeminiAgent:
    """Tests for GeminiAgent."""

    def test_from_config_creates_agent(
        self, mock_cost_limits, mock_model_def, mock_credential
    ):
        """_from_config creates agent from config."""
        config = GeminiConfig(
            type="gemini",
            version="1.0.0",
            cost_limits=mock_cost_limits,
        )

        agent = GeminiAgent._from_config(
            config=config,
            model=mock_model_def,
            credential=mock_credential,
            problem_name="test-problem",
            verbose=False,
            image="test-image",
        )

        assert isinstance(agent, GeminiAgent)
        assert agent.binary == "gemini"
        assert agent.use_vertex is False

    def test_from_config_passes_vertex_option(
        self, mock_cost_limits, mock_model_def, mock_credential
    ):
        """_from_config forwards the Vertex option to the agent."""
        config = GeminiConfig(
            type="gemini",
            version="1.0.0",
            cost_limits=mock_cost_limits,
            use_vertex=True,
        )

        agent = GeminiAgent._from_config(
            config=config,
            model=mock_model_def,
            credential=mock_credential,
            problem_name="test-problem",
            verbose=False,
            image="test-image",
        )

        assert isinstance(agent, GeminiAgent)
        assert agent.use_vertex is True

    def test_from_config_requires_image(
        self, mock_cost_limits, mock_model_def, mock_credential
    ):
        """_from_config requires image."""
        config = GeminiConfig(
            type="gemini",
            version="1.0.0",
            cost_limits=mock_cost_limits,
        )

        with pytest.raises(ValueError, match="requires an image"):
            GeminiAgent._from_config(
                config=config,
                model=mock_model_def,
                credential=mock_credential,
                problem_name="test-problem",
                verbose=False,
                image=None,
            )

    def test_setup_and_cleanup(self, tmp_path, mock_cost_limits, mock_pricing):
        """setup() and cleanup() manage session lifecycle."""
        runtime = FakeRuntime()
        session = FakeSession(runtime=runtime, working_dir=tmp_path)

        agent = GeminiAgent(
            problem_name="test-problem",
            verbose=False,
            image="test-image",
            cost_limits=mock_cost_limits,
            pricing=mock_pricing,
            credential=None,
            binary="gemini",
            model="gemini-2.5-flash",
            timeout=60,
            extra_args=[],
            env={},
        )

        # Before setup, session access should raise
        with pytest.raises(Exception):
            _ = agent.session

        agent.setup(cast("Session", session))

        # After setup, session should be accessible
        assert agent.session == session

        agent.cleanup()

        # After cleanup, session is None
        assert agent._session is None

    def test_get_volumes_writes_vertex_settings_without_auth(
        self, mock_cost_limits, mock_pricing
    ):
        """Vertex mode mounts a settings.json even without file auth."""
        agent = GeminiAgent(
            problem_name="test-problem",
            verbose=False,
            image="test-image",
            cost_limits=mock_cost_limits,
            pricing=mock_pricing,
            credential=None,
            binary="gemini",
            model="gemini-2.5-flash",
            timeout=60,
            extra_args=[],
            env={},
            use_vertex=True,
        )

        mounts = agent._get_volumes()

        assert len(mounts) == 1
        mount_path = Path(next(iter(mounts)))
        assert (mount_path / "settings.json").read_text() == (
            '{"selectedAuthType": "vertex-ai"}\n'
        )
        agent.cleanup()

    def test_get_volumes_overwrites_stale_settings_for_vertex(
        self, tmp_path, mock_cost_limits, mock_pricing
    ):
        """Vertex mode removes stale settings from the runtime copy."""
        gemini_dir = tmp_path / ".gemini"
        gemini_dir.mkdir()
        auth_file = gemini_dir / "oauth_creds.json"
        settings_file = gemini_dir / "settings.json"
        auth_file.write_text("{}")
        settings_file.write_text(
            '{"selectedAuthType": "oauth-personal", "stale": true}\n'
        )
        credential = ProviderCredential(
            provider="gemini_auth",
            credential_type=CredentialType.FILE,
            value=str(auth_file),
            source=str(auth_file),
            destination_key="GOOGLE_APPLICATION_CREDENTIALS",
        )
        agent = GeminiAgent(
            problem_name="test-problem",
            verbose=False,
            image="test-image",
            cost_limits=mock_cost_limits,
            pricing=mock_pricing,
            credential=credential,
            binary="gemini",
            model="gemini-2.5-flash",
            timeout=60,
            extra_args=[],
            env={},
            use_vertex=True,
        )

        mounts = agent._get_volumes()

        mount_path = Path(next(iter(mounts)))
        assert (mount_path / "settings.json").read_text() == (
            '{"selectedAuthType": "vertex-ai"}\n'
        )
        assert settings_file.read_text() == (
            '{"selectedAuthType": "oauth-personal", "stale": true}\n'
        )
        agent.cleanup()

    def test_run_invocation_preserves_split_model_cost(
        self, tmp_path, mock_cost_limits
    ):
        """Gemini pricing tiers apply to each reported model bucket."""
        pricing = APIPricing(
            input=4.0,
            output=18.0,
            cache_read=0.4,
            prompt_tiers=[
                APIPricingTier(
                    max_input_tokens=200000,
                    input=2.0,
                    output=12.0,
                    cache_read=0.2,
                )
            ],
        )
        result_line = (
            '{"type":"result","status":"success",'
            '"stats":{"input_tokens":300000,"output_tokens":2000,'
            '"cached":100000,"input":200000,"total_tokens":303000,'
            '"models":{'
            '"gemini-3.1-pro-preview":{"input_tokens":150000,'
            '"output_tokens":1000,"cached":50000,"input":100000,'
            '"total_tokens":151500},'
            '"gemini-3-flash-preview":{"input_tokens":150000,'
            '"output_tokens":1000,"cached":50000,"input":100000,'
            '"total_tokens":151500}}}}'
        )
        runtime = FakeRuntime()
        runtime.events = [RuntimeEvent(kind="stdout", text=f"{result_line}\n")]
        session = FakeSession(runtime=runtime, working_dir=tmp_path)
        agent = GeminiAgent(
            problem_name="test-problem",
            verbose=False,
            image="test-image",
            cost_limits=mock_cost_limits,
            pricing=pricing,
            credential=None,
            binary="gemini",
            model="gemini-3.1-pro-preview",
            timeout=60,
            extra_args=[],
            env={},
        )
        agent.setup(cast("Session", session))

        result = agent._run_invocation("solve task")
        agent._sync_usage(result.usage_totals)

        assert result.usage_totals["input_tokens"] == 300000
        assert result.usage_totals["output_tokens"] == 3000
        assert result.usage_totals["reasoning_tokens"] == 1000
        assert result.usage_totals["cost_micros"] == 456000
        assert agent.usage.cost == pytest.approx(0.456)

    def test_reset_clears_state(self, tmp_path, mock_cost_limits, mock_pricing):
        """reset() clears internal state."""
        runtime = FakeRuntime()
        session = FakeSession(runtime=runtime, working_dir=tmp_path)

        agent = GeminiAgent(
            problem_name="test-problem",
            verbose=False,
            image="test-image",
            cost_limits=mock_cost_limits,
            pricing=mock_pricing,
            credential=None,
            binary="gemini",
            model=None,
            timeout=None,
            extra_args=[],
            env={},
        )

        agent.setup(cast("Session", session))

        # Set some state
        agent._last_prompt = "some prompt"
        agent._last_command = MagicMock()
        agent._payloads = [{"type": "test"}]

        agent.reset()

        assert agent._last_prompt == ""
        assert agent._last_command is None
        assert agent._payloads == []

    def test_build_command_basic(self, mock_cost_limits, mock_pricing):
        """_build_command creates correct base command."""
        agent = GeminiAgent(
            problem_name="test-problem",
            verbose=False,
            image="test-image",
            cost_limits=mock_cost_limits,
            pricing=mock_pricing,
            credential=None,
            binary="gemini",
            model=None,
            timeout=None,
            extra_args=[],
            env={},
        )

        command = agent._build_command("do something")

        assert command[0] == "gemini"
        assert any(arg.startswith("--prompt=") for arg in command)
        assert "--yolo" in command  # YOLO mode
        assert "--output-format" in command
        assert "stream-json" in command
        assert "--skip-trust" in command

    def test_build_command_with_model(self, mock_cost_limits, mock_pricing):
        """_build_command includes model when specified."""
        agent = GeminiAgent(
            problem_name="test-problem",
            verbose=False,
            image="test-image",
            cost_limits=mock_cost_limits,
            pricing=mock_pricing,
            credential=None,
            binary="gemini",
            model="gemini-2.5-flash",
            timeout=None,
            extra_args=[],
            env={},
        )

        command = agent._build_command("do something")

        assert "--model=gemini-2.5-flash" in command

    def test_build_command_for_retry_resumes_latest_session(
        self, mock_cost_limits, mock_pricing
    ):
        agent = GeminiAgent(
            problem_name="test-problem",
            verbose=False,
            image="test-image",
            cost_limits=mock_cost_limits,
            pricing=mock_pricing,
            credential=None,
            binary="gemini",
            model=None,
            timeout=None,
            extra_args=[],
            env={},
        )

        command = agent._build_command("continue", resume=True)

        assert "--resume" in command
        resume_idx = command.index("--resume")
        assert command[resume_idx + 1] == "latest"

    def test_build_command_strips_provider_prefix_from_model(
        self, mock_cost_limits, mock_pricing
    ):
        """_build_command strips provider prefix to match Harbor Gemini CLI."""
        agent = GeminiAgent(
            problem_name="test-problem",
            verbose=False,
            image="test-image",
            cost_limits=mock_cost_limits,
            pricing=mock_pricing,
            credential=None,
            binary="gemini",
            model="google/gemini-2.5-flash",
            timeout=None,
            extra_args=[],
            env={},
        )

        command = agent._build_command("do something")

        assert "--model=gemini-2.5-flash" in command
        assert "--model=google/gemini-2.5-flash" not in command

    def test_build_command_with_extra_args(
        self, mock_cost_limits, mock_pricing
    ):
        """_build_command appends extra_args."""
        agent = GeminiAgent(
            problem_name="test-problem",
            verbose=False,
            image="test-image",
            cost_limits=mock_cost_limits,
            pricing=mock_pricing,
            credential=None,
            binary="gemini",
            model=None,
            timeout=None,
            extra_args=["--custom-flag", "value"],
            env={},
        )

        command = agent._build_command("do something")

        assert "--custom-flag" in command
        assert "value" in command

    def test_build_command_does_not_duplicate_skip_trust(
        self, mock_cost_limits, mock_pricing
    ):
        """_build_command keeps the default trust bypass unique."""
        agent = GeminiAgent(
            problem_name="test-problem",
            verbose=False,
            image="test-image",
            cost_limits=mock_cost_limits,
            pricing=mock_pricing,
            credential=None,
            binary="gemini",
            model=None,
            timeout=None,
            extra_args=["--skip-trust"],
            env={},
        )

        command = agent._build_command("do something")

        assert command.count("--skip-trust") == 1

    def test_prepare_runtime_execution_passes_google_auth_env_vars(
        self, mock_cost_limits, mock_pricing, monkeypatch
    ):
        """_prepare_runtime_execution forwards Gemini auth env vars."""
        monkeypatch.setenv("GOOGLE_API_KEY", "google-key")

        agent = GeminiAgent(
            problem_name="test-problem",
            verbose=False,
            image="test-image",
            cost_limits=mock_cost_limits,
            pricing=mock_pricing,
            credential=None,
            binary="gemini",
            model="gemini-2.5-flash",
            timeout=None,
            extra_args=[],
            env={},
        )

        _, env_overrides = agent._prepare_runtime_execution("do something")
        assert env_overrides["GOOGLE_API_KEY"] == "google-key"

    def test_prepare_runtime_execution_does_not_pass_vertex_env_vars_by_default(
        self, mock_cost_limits, mock_pricing, monkeypatch
    ):
        """Vertex env vars are only forwarded when Vertex mode is enabled."""
        monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "true")
        monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")
        monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "us-central1")

        agent = GeminiAgent(
            problem_name="test-problem",
            verbose=False,
            image="test-image",
            cost_limits=mock_cost_limits,
            pricing=mock_pricing,
            credential=None,
            binary="gemini",
            model="gemini-2.5-flash",
            timeout=None,
            extra_args=[],
            env={},
        )

        _, env_overrides = agent._prepare_runtime_execution("do something")
        assert "GOOGLE_GENAI_USE_VERTEXAI" not in env_overrides
        assert "GOOGLE_CLOUD_PROJECT" not in env_overrides
        assert "GOOGLE_CLOUD_LOCATION" not in env_overrides

    def test_prepare_runtime_execution_passes_vertex_env_vars_when_enabled(
        self, mock_cost_limits, mock_pricing, monkeypatch
    ):
        """Vertex mode forwards required Google Cloud env vars."""
        monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")
        monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "us-central1")

        agent = GeminiAgent(
            problem_name="test-problem",
            verbose=False,
            image="test-image",
            cost_limits=mock_cost_limits,
            pricing=mock_pricing,
            credential=None,
            binary="gemini",
            model="gemini-2.5-flash",
            timeout=None,
            extra_args=[],
            env={},
            use_vertex=True,
        )

        _, env_overrides = agent._prepare_runtime_execution("do something")
        assert env_overrides["GOOGLE_GENAI_USE_VERTEXAI"] == "true"
        assert env_overrides["GOOGLE_CLOUD_PROJECT"] == "test-project"
        assert env_overrides["GOOGLE_CLOUD_LOCATION"] == "us-central1"

    def test_prepare_runtime_execution_renames_gemini_key_for_vertex(
        self, mock_cost_limits, mock_pricing, mock_credential, monkeypatch
    ):
        """Vertex mode exports Gemini API key credentials as GOOGLE_API_KEY."""
        monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")
        monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "us-central1")
        monkeypatch.setenv("GEMINI_API_KEY", "host-gemini-key")

        agent = GeminiAgent(
            problem_name="test-problem",
            verbose=False,
            image="test-image",
            cost_limits=mock_cost_limits,
            pricing=mock_pricing,
            credential=mock_credential,
            binary="gemini",
            model="gemini-2.5-flash",
            timeout=None,
            extra_args=[],
            env={},
            use_vertex=True,
        )

        _, env_overrides = agent._prepare_runtime_execution("do something")
        assert env_overrides["GOOGLE_API_KEY"] == "test-api-key"
        assert "GEMINI_API_KEY" not in env_overrides

    def test_prepare_runtime_execution_maps_host_gemini_key_for_vertex(
        self, mock_cost_limits, mock_pricing, monkeypatch
    ):
        """Vertex mode maps host GEMINI_API_KEY to GOOGLE_API_KEY."""
        monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")
        monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "us-central1")
        monkeypatch.setenv("GEMINI_API_KEY", "host-gemini-key")
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

        agent = GeminiAgent(
            problem_name="test-problem",
            verbose=False,
            image="test-image",
            cost_limits=mock_cost_limits,
            pricing=mock_pricing,
            credential=None,
            binary="gemini",
            model="gemini-2.5-flash",
            timeout=None,
            extra_args=[],
            env={},
            use_vertex=True,
        )

        _, env_overrides = agent._prepare_runtime_execution("do something")
        assert env_overrides["GOOGLE_API_KEY"] == "host-gemini-key"
        assert "GEMINI_API_KEY" not in env_overrides

    def test_prepare_runtime_execution_requires_vertex_env_vars(
        self, mock_cost_limits, mock_pricing, monkeypatch
    ):
        """Vertex mode fails early when required env vars are missing."""
        monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
        monkeypatch.delenv("GOOGLE_CLOUD_LOCATION", raising=False)

        agent = GeminiAgent(
            problem_name="test-problem",
            verbose=False,
            image="test-image",
            cost_limits=mock_cost_limits,
            pricing=mock_pricing,
            credential=None,
            binary="gemini",
            model="gemini-2.5-flash",
            timeout=None,
            extra_args=[],
            env={},
            use_vertex=True,
        )

        with pytest.raises(AgentError, match="GOOGLE_CLOUD_PROJECT"):
            agent._prepare_runtime_execution("do something")

    def test_save_artifacts_writes_files(
        self, tmp_path, mock_cost_limits, mock_pricing
    ):
        """save_artifacts writes prompt and trajectory files."""
        runtime = FakeRuntime()
        session = FakeSession(runtime=runtime, working_dir=tmp_path)

        agent = GeminiAgent(
            problem_name="test-problem",
            verbose=False,
            image="test-image",
            cost_limits=mock_cost_limits,
            pricing=mock_pricing,
            credential=None,
            binary="gemini",
            model=None,
            timeout=None,
            extra_args=[],
            env={},
        )

        agent.setup(cast("Session", session))
        agent._last_prompt = "test prompt"
        agent._payloads = [
            {"type": "message", "role": "assistant", "content": "Hello"},
            {"type": "tool_use", "name": "bash", "input": "ls -la"},
        ]

        output_dir = tmp_path / "artifacts"
        agent.save_artifacts(output_dir)

        prompt_file = output_dir / "prompt.txt"
        assert prompt_file.exists()
        assert prompt_file.read_text() == "test prompt"

        # Check messages.jsonl is written
        messages_file = output_dir / "messages.jsonl"
        assert messages_file.exists()
        lines = messages_file.read_text().strip().split("\n")
        assert len(lines) == 2
        import json

        assert json.loads(lines[0]) == agent._payloads[0]
        assert json.loads(lines[1]) == agent._payloads[1]


class TestGeminiAgentParseLine:
    """Tests for GeminiAgent.parse_line static method."""

    def test_parse_line_init_event(self, mock_pricing):
        """parse_line handles init events correctly."""
        line = '{"type":"init","session_id":"abc","model":"gemini-2.5-flash"}'
        cost, tokens, payload = GeminiAgent.parse_line(line, mock_pricing)

        assert cost is None
        assert tokens is None
        assert payload is not None
        assert payload["type"] == "init"
        assert payload["model"] == "gemini-2.5-flash"

    def test_parse_line_message_event(self, mock_pricing):
        """parse_line handles message events correctly."""
        line = '{"type":"message","role":"assistant","content":"Hello"}'
        cost, tokens, payload = GeminiAgent.parse_line(line, mock_pricing)

        assert cost is None
        assert tokens is None
        assert payload is not None
        assert payload["type"] == "message"
        assert payload["role"] == "assistant"

    def test_parse_line_tool_use_event(self, mock_pricing):
        """parse_line handles tool_use events correctly."""
        line = '{"type":"tool_use","tool_name":"write_file","tool_id":"123"}'
        cost, tokens, payload = GeminiAgent.parse_line(line, mock_pricing)

        assert cost is None
        assert tokens is None
        assert payload is not None
        assert payload["type"] == "tool_use"
        assert payload["tool_name"] == "write_file"

    def test_parse_line_tool_result_event(self, mock_pricing):
        """parse_line handles tool_result events correctly."""
        line = '{"type":"tool_result","tool_id":"123","status":"success"}'
        cost, tokens, payload = GeminiAgent.parse_line(line, mock_pricing)

        assert cost is None
        assert tokens is None
        assert payload is not None
        assert payload["type"] == "tool_result"
        assert payload["status"] == "success"

    def test_parse_line_result_event(self, mock_pricing):
        """parse_line extracts usage from result events."""
        line = (
            '{"type":"result","status":"success",'
            '"stats":{"input_tokens":1000,"output_tokens":50}}'
        )
        cost, tokens, payload = GeminiAgent.parse_line(line, mock_pricing)

        assert cost is not None
        assert tokens is not None
        assert payload is not None
        assert payload["type"] == "result"
        assert tokens.input == 1000
        assert tokens.output == 50
        # Cost calculation: (1000 * 0.15 + 50 * 0.60) / 1_000_000
        expected_cost = (1000 * 0.15 + 50 * 0.60) / 1_000_000
        assert abs(cost - expected_cost) < 0.0001

    def test_parse_line_result_keeps_input_tokens_as_reported(
        self, mock_pricing
    ):
        """Gemini input_tokens already includes cached prompt tokens."""
        line = (
            '{"type":"result","status":"success",'
            '"stats":{"input_tokens":729324,"output_tokens":6795,'
            '"cached":499835,"input":229489}}'
        )

        cost, tokens, payload = GeminiAgent.parse_line(line, mock_pricing)

        assert cost is not None
        assert tokens is not None
        assert payload is not None
        assert tokens.input == 729324
        assert tokens.cache_read == 499835
        expected_cost = (
            (229489 * 0.15) + (6795 * 0.60) + (499835 * 0.0375)
        ) / 1_000_000
        assert cost == pytest.approx(expected_cost)

    def test_parse_line_result_counts_total_token_residual_as_reasoning(
        self, mock_pricing
    ):
        """Gemini reports hidden reasoning in total_tokens only."""
        line = (
            '{"type":"result","status":"success",'
            '"stats":{"input_tokens":729324,"output_tokens":6795,'
            '"cached":499835,"input":229489,"total_tokens":748618}}'
        )

        cost, tokens, payload = GeminiAgent.parse_line(line, mock_pricing)

        assert cost is not None
        assert tokens is not None
        assert payload is not None
        assert tokens.input == 729324
        assert tokens.output == 19294
        assert tokens.reasoning == 12499
        assert tokens.cache_read == 499835
        expected_cost = (
            (229489 * 0.15) + (19294 * 0.60) + (499835 * 0.0375)
        ) / 1_000_000
        assert cost == pytest.approx(expected_cost)

    def test_parse_line_result_prices_reported_model_buckets_separately(self):
        """Gemini model buckets get prompt tiers independently."""
        pricing = APIPricing(
            input=4.0,
            output=18.0,
            cache_read=0.4,
            prompt_tiers=[
                APIPricingTier(
                    max_input_tokens=200000,
                    input=2.0,
                    output=12.0,
                    cache_read=0.2,
                )
            ],
        )
        line = (
            '{"type":"result","status":"success",'
            '"stats":{"input_tokens":300000,"output_tokens":2000,'
            '"cached":100000,"input":200000,"total_tokens":303000,'
            '"models":{'
            '"gemini-3.1-pro-preview":{"input_tokens":150000,'
            '"output_tokens":1000,"cached":50000,"input":100000,'
            '"total_tokens":151500},'
            '"gemini-3-flash-preview":{"input_tokens":150000,'
            '"output_tokens":1000,"cached":50000,"input":100000,'
            '"total_tokens":151500}}}}'
        )

        cost, tokens, payload = GeminiAgent.parse_line(line, pricing)

        assert cost == pytest.approx(0.456)
        assert tokens is not None
        assert payload is not None
        assert tokens.input == 300000
        assert tokens.output == 3000
        assert tokens.reasoning == 1000
        assert tokens.cache_read == 100000

    def test_parse_line_result_counts_thought_tool_and_cache_tokens(
        self, mock_pricing
    ):
        """Legacy Gemini usage can report uncached input plus cached tokens."""
        line = (
            '{"type":"result","status":"success",'
            '"stats":{"input":1000,"output":50,"thoughts":25,'
            '"tool":10,"cached":200}}'
        )

        cost, tokens, payload = GeminiAgent.parse_line(line, mock_pricing)

        assert cost is not None
        assert tokens is not None
        assert payload is not None
        assert tokens.input == 1200
        assert tokens.output == 85
        assert tokens.cache_read == 200
        expected_cost = (1000 * 0.15 + 85 * 0.60 + 200 * 0.0375) / 1_000_000
        assert cost == pytest.approx(expected_cost)

    def test_parse_line_result_with_no_stats(self, mock_pricing):
        """parse_line handles result with missing stats."""
        line = '{"type":"result","status":"success"}'
        cost, tokens, payload = GeminiAgent.parse_line(line, mock_pricing)

        assert cost == 0.0
        assert tokens is not None
        assert tokens.input == 0
        assert tokens.output == 0
        assert payload is not None

    def test_parse_line_invalid_json(self, mock_pricing):
        """parse_line handles invalid JSON gracefully."""
        line = "not valid json"
        cost, tokens, payload = GeminiAgent.parse_line(line, mock_pricing)

        assert cost is None
        assert tokens is None
        assert payload is None

    def test_parse_line_empty_line(self, mock_pricing):
        """parse_line handles empty lines gracefully."""
        line = ""
        cost, tokens, payload = GeminiAgent.parse_line(line, mock_pricing)

        assert cost is None
        assert tokens is None
        assert payload is None

    def test_parse_line_without_pricing(self):
        """parse_line works without pricing (cost is 0)."""
        line = (
            '{"type":"result","status":"success",'
            '"stats":{"input_tokens":1000,"output_tokens":50}}'
        )
        cost, tokens, payload = GeminiAgent.parse_line(line, pricing=None)

        assert cost == 0.0
        assert tokens is not None
        assert tokens.input == 1000
        assert tokens.output == 50


class TestGeminiAgentRegistration:
    """Tests for agent registration."""

    def test_agent_is_registered(self):
        """Gemini agent is registered in the agent registry."""
        from slop_code.agent_runner.registry import available_agent_types
        from slop_code.agent_runner.registry import get_agent_cls

        assert "gemini" in available_agent_types()
        assert get_agent_cls("gemini") is GeminiAgent

    def test_config_type_is_correct(self, mock_cost_limits):
        """Config type field is correctly set."""
        config = GeminiConfig(
            type="gemini",
            version="1.0.0",
            cost_limits=mock_cost_limits,
        )
        assert config.type == "gemini"
