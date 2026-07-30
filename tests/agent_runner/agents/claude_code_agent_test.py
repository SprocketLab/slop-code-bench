"""Unit tests for the Claude Code agent configuration."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import pytest

from slop_code.agent_runner.agents.claude_code import ClaudeCodeConfig
from slop_code.agent_runner.agents.claude_code.agent import ClaudeCodeAgent
from slop_code.agent_runner.agents.utils import HOME_PATH
from slop_code.agent_runner.credentials import CredentialType
from slop_code.agent_runner.credentials import ProviderCredential
from slop_code.agent_runner.models import AgentCostLimits
from slop_code.agent_runner.models import AgentError
from slop_code.common.llms import APIPricing
from slop_code.common.llms import ModelCatalog
from slop_code.common.llms import ModelDefinition
from slop_code.common.llms import TokenUsage
from slop_code.execution import DockerConfig
from slop_code.execution import DockerEnvironmentSpec
from slop_code.execution import Session
from slop_code.execution import StreamingRuntime
from slop_code.execution.runtime import RuntimeResult


@pytest.fixture
def mock_cost_limits():
    """Standard cost limits for tests."""
    return AgentCostLimits(
        step_limit=10,
        cost_limit=100.0,
        net_cost_limit=200.0,
    )


@pytest.fixture
def mock_pricing():
    """Standard pricing for tests."""
    return APIPricing(
        input=0.5,
        output=2.0,
        cache_read=0.1,
    )


@pytest.fixture
def mock_credential():
    """Standard credential for tests."""
    return ProviderCredential(
        provider="anthropic",
        value="test-api-key",
        source="ANTHROPIC_API_KEY",
        destination_key="ANTHROPIC_API_KEY",
        credential_type=CredentialType.ENV_VAR,
    )


@pytest.fixture
def openrouter_credential():
    """Credential for OpenRouter-backed Claude Code runs."""
    return ProviderCredential(
        provider="openrouter",
        value="test-openrouter-key",
        source="OPENROUTER_API_KEY",
        destination_key="OPENROUTER_API_KEY",
        credential_type=CredentialType.ENV_VAR,
    )


class FakeRuntime:
    """Minimal runtime stub for testing."""

    def __init__(self) -> None:
        self.cleaned = False

    def cleanup(self) -> None:
        self.cleaned = True


class FakeLogger:
    """Capture debug and warning logs for assertions."""

    def __init__(self) -> None:
        self.debug_calls: list[tuple[str, dict]] = []
        self.warning_calls: list[tuple[str, dict]] = []

    def debug(self, event: str, **kwargs: object) -> None:
        self.debug_calls.append((event, kwargs))

    def warning(self, event: str, **kwargs: object) -> None:
        self.warning_calls.append((event, kwargs))


@dataclass
class FakeSession:
    """Fake session for testing."""

    runtime: FakeRuntime
    working_dir: Path
    spec: object | None = None
    last_spawn_env_vars: dict[str, str] | None = None
    last_spawn_mounts: dict[str, dict[str, str] | str] | None = None

    def spawn(self, **_: object) -> FakeRuntime:
        env_vars = cast("dict[str, str] | None", _.get("env_vars"))
        mounts = cast(
            "dict[str, dict[str, str] | str] | None",
            _.get("mounts"),
        )
        self.last_spawn_env_vars = dict(env_vars or {})
        self.last_spawn_mounts = dict(mounts or {})
        return self.runtime


class TestClaudeCodeConfig:
    """Tests for ClaudeCodeConfig."""

    def test_version_is_required(self, mock_cost_limits):
        """Version field is required for docker template."""
        with pytest.raises(Exception):  # Pydantic validation error
            ClaudeCodeConfig(  # type: ignore[missing-argument]
                type="claude_code",
                cost_limits=mock_cost_limits,
                # Missing version
            )

    def test_config_with_version(self, mock_cost_limits):
        """Config can be created with version."""
        config = ClaudeCodeConfig(
            type="claude_code",
            version="2.0.51",
            cost_limits=mock_cost_limits,
        )
        assert config.version == "2.0.51"
        assert config.binary == "claude"

    def test_get_docker_file_renders_version(self, mock_cost_limits):
        """get_docker_file renders version into template."""
        config = ClaudeCodeConfig(
            type="claude_code",
            version="2.0.51",
            cost_limits=mock_cost_limits,
        )
        dockerfile = config.get_docker_file("base-image:latest")
        assert dockerfile is not None
        assert "base-image:latest" in dockerfile
        assert "@anthropic-ai/claude-code@2.0.51" in dockerfile


class TestClaudeCodeAgent:
    """Tests for ClaudeCodeAgent."""

    def test_save_artifacts_copies_claude_traces(
        self,
        tmp_path,
        mock_cost_limits,
        mock_pricing,
        mock_credential,
    ):
        """save_artifacts copies only Claude's mounted workspace project."""
        runtime = FakeRuntime()
        spec = DockerEnvironmentSpec(
            name="test",
            docker=DockerConfig(image="test-image"),
        )
        session = FakeSession(
            runtime=runtime,
            working_dir=tmp_path,
            spec=spec,
        )

        agent = ClaudeCodeAgent(
            problem_name="test-problem",
            image="test-image",
            verbose=False,
            cost_limits=mock_cost_limits,
            pricing=mock_pricing,
            credential=mock_credential,
            binary="claude",
            model="claude-test",
            timeout=None,
            settings={},
            env={},
            extra_args=[],
            append_system_prompt=None,
            allowed_tools=[],
            disallowed_tools=[],
            permission_mode=None,
            base_url=None,
            thinking=None,
            max_thinking_tokens=None,
            max_output_tokens=None,
        )

        agent.setup(cast("Session", session))
        assert agent._trace_dir is not None
        trace_dir = agent._trace_dir
        trace_dir.mkdir(parents=True, exist_ok=True)
        nested = trace_dir / "projects" / "-workspace" / "trace.jsonl"
        nested.parent.mkdir(parents=True, exist_ok=True)
        nested.write_text('{"type":"system","subtype":"init"}\n')
        root_file = trace_dir / "settings.json"
        root_file.write_text("{}")
        other_project = trace_dir / "projects" / "other" / "trace.jsonl"
        other_project.parent.mkdir(parents=True, exist_ok=True)
        other_project.write_text('{"type":"system","subtype":"other"}\n')

        output_dir = tmp_path / "artifacts"
        agent.save_artifacts(output_dir)

        saved_trace = (
            output_dir / "workspace" / "projects" / "-workspace" / "trace.jsonl"
        )
        assert saved_trace.exists()
        assert saved_trace.read_text() == nested.read_text()
        assert not (output_dir / "workspace" / "settings.json").exists()
        assert not (
            output_dir / "workspace" / "projects" / "other" / "trace.jsonl"
        ).exists()

    def test_setup_uses_default_home_for_docker(
        self,
        tmp_path,
        mock_cost_limits,
        mock_pricing,
        mock_credential,
    ):
        """setup keeps HOME at agent home and mounts claude project dir."""
        runtime = FakeRuntime()
        spec = DockerEnvironmentSpec(
            name="test",
            docker=DockerConfig(image="test-image"),
        )
        session = FakeSession(
            runtime=runtime,
            working_dir=tmp_path,
            spec=spec,
        )

        agent = ClaudeCodeAgent(
            problem_name="test-problem",
            image="test-image",
            verbose=False,
            cost_limits=mock_cost_limits,
            pricing=mock_pricing,
            credential=mock_credential,
            binary="claude",
            model="claude-test",
            timeout=None,
            settings={},
            env={},
            extra_args=[],
            append_system_prompt=None,
            allowed_tools=[],
            disallowed_tools=[],
            permission_mode=None,
            base_url=None,
            thinking=None,
            max_thinking_tokens=None,
            max_output_tokens=None,
        )

        agent.setup(cast("Session", session))

        assert session.last_spawn_env_vars is not None
        assert session.last_spawn_env_vars.get("HOME") == HOME_PATH
        assert session.last_spawn_mounts is not None
        assert any(
            isinstance(value, dict)
            and value.get("bind") == f"{HOME_PATH}/.claude"
            for value in session.last_spawn_mounts.values()
        )

    def test_save_artifacts_logs_trace_counts(
        self,
        tmp_path,
        mock_cost_limits,
        mock_pricing,
        mock_credential,
    ):
        """_save_claude_traces logs discovered and saved trace counts."""
        agent = ClaudeCodeAgent(
            problem_name="test-problem",
            image="test-image",
            verbose=False,
            cost_limits=mock_cost_limits,
            pricing=mock_pricing,
            credential=mock_credential,
            binary="claude",
            model="claude-test",
            timeout=None,
            settings={},
            env={},
            extra_args=[],
            append_system_prompt=None,
            allowed_tools=[],
            disallowed_tools=[],
            permission_mode=None,
            base_url=None,
            thinking=None,
            max_thinking_tokens=None,
            max_output_tokens=None,
        )
        logger = FakeLogger()
        agent.log = logger

        trace_dir = tmp_path / "claude_home"
        trace_dir.mkdir(parents=True, exist_ok=True)
        nested = trace_dir / "projects" / "-workspace" / "trace.jsonl"
        nested.parent.mkdir(parents=True, exist_ok=True)
        nested.write_text('{"type":"system","subtype":"init"}\n')
        unrelated = trace_dir / "projects" / "other" / "trace.jsonl"
        unrelated.parent.mkdir(parents=True, exist_ok=True)
        unrelated.write_text('{"type":"system","subtype":"other"}\n')
        agent._trace_dir = trace_dir

        output_dir = tmp_path / "artifacts"
        agent._save_claude_traces(output_dir)

        assert any(
            event == "agent.claude_code.traces.saved"
            and kwargs.get("saved") == 1
            for event, kwargs in logger.debug_calls
        )

    def test_save_artifacts_only_copies_new_claude_trace_files_between_checkpoints(
        self,
        tmp_path,
        mock_cost_limits,
        mock_pricing,
        mock_credential,
    ):
        """Later checkpoints should only save newly created Claude trace files."""
        agent = ClaudeCodeAgent(
            problem_name="test-problem",
            image="test-image",
            verbose=False,
            cost_limits=mock_cost_limits,
            pricing=mock_pricing,
            credential=mock_credential,
            binary="claude",
            model="claude-test",
            timeout=None,
            settings={},
            env={},
            extra_args=[],
            append_system_prompt=None,
            allowed_tools=[],
            disallowed_tools=[],
            permission_mode=None,
            base_url=None,
            thinking=None,
            max_thinking_tokens=None,
            max_output_tokens=None,
        )

        trace_dir = tmp_path / "claude_home"
        first_trace = trace_dir / "projects" / "-workspace" / "trace1.jsonl"
        first_trace.parent.mkdir(parents=True, exist_ok=True)
        first_trace.write_text('{"type":"system","subtype":"init"}\n')
        agent._trace_dir = trace_dir

        first_output = tmp_path / "checkpoint_1"
        agent._save_claude_traces(first_output)
        assert (
            first_output
            / "workspace"
            / "projects"
            / "-workspace"
            / "trace1.jsonl"
        ).exists()

        agent.reset()

        second_trace = trace_dir / "projects" / "-workspace" / "trace2.jsonl"
        second_trace.write_text('{"type":"assistant","subtype":"turn"}\n')

        second_output = tmp_path / "checkpoint_2"
        agent._save_claude_traces(second_output)

        assert not (
            second_output
            / "workspace"
            / "projects"
            / "-workspace"
            / "trace1.jsonl"
        ).exists()
        saved_new_trace = (
            second_output
            / "workspace"
            / "projects"
            / "-workspace"
            / "trace2.jsonl"
        )
        assert saved_new_trace.exists()
        assert saved_new_trace.read_text() == second_trace.read_text()

    def test_save_claude_traces_skips_unreadable_subdir(
        self,
        tmp_path,
        mock_cost_limits,
        mock_pricing,
        mock_credential,
    ):
        """Unreadable subdirs under the trace root must not raise."""
        agent = ClaudeCodeAgent(
            problem_name="test-problem",
            image="test-image",
            verbose=False,
            cost_limits=mock_cost_limits,
            pricing=mock_pricing,
            credential=mock_credential,
            binary="claude",
            model="claude-test",
            timeout=None,
            settings={},
            env={},
            extra_args=[],
            append_system_prompt=None,
            allowed_tools=[],
            disallowed_tools=[],
            permission_mode=None,
            base_url=None,
            thinking=None,
            max_thinking_tokens=None,
            max_output_tokens=None,
        )
        logger = FakeLogger()
        agent.log = logger

        trace_dir = tmp_path / "claude_home"
        readable = trace_dir / "projects" / "-workspace" / "trace.jsonl"
        readable.parent.mkdir(parents=True, exist_ok=True)
        readable.write_text('{"type":"system","subtype":"init"}\n')
        locked_dir = trace_dir / "projects" / "-workspace" / "locked"
        locked_dir.mkdir(parents=True, exist_ok=True)
        (locked_dir / "secret.jsonl").write_text("nope")
        agent._trace_dir = trace_dir

        locked_dir.chmod(0o000)
        try:
            output_dir = tmp_path / "artifacts"
            agent._save_claude_traces(output_dir)
        finally:
            locked_dir.chmod(0o700)

        saved_trace = (
            output_dir / "workspace" / "projects" / "-workspace" / "trace.jsonl"
        )
        assert saved_trace.exists()
        assert any(
            event == "agent.claude_code.traces.unreadable"
            for event, _ in logger.warning_calls
        )

    def test_prepare_runtime_execution_traps_claude_home_chmod(
        self,
        tmp_path,
        mock_cost_limits,
        mock_pricing,
        mock_credential,
    ):
        """The shell command must trap EXIT to relax ~/.claude perms."""
        agent = ClaudeCodeAgent(
            problem_name="test-problem",
            image="test-image",
            verbose=False,
            cost_limits=mock_cost_limits,
            pricing=mock_pricing,
            credential=mock_credential,
            binary="claude",
            model="claude-test",
            timeout=None,
            settings={},
            env={},
            extra_args=[],
            append_system_prompt=None,
            allowed_tools=[],
            disallowed_tools=[],
            permission_mode=None,
            base_url=None,
            thinking=None,
            max_thinking_tokens=None,
            max_output_tokens=None,
        )

        command_str, _env = agent._prepare_runtime_execution("hello task")

        assert isinstance(command_str, str)
        assert "trap" in command_str
        assert 'chmod -R u+rwX "$HOME/.claude"' in command_str
        assert command_str.index("trap") < command_str.index("claude")

    def test_prepare_mounts_includes_max_output_tokens_in_settings(
        self,
        tmp_path,
        mock_cost_limits,
        mock_pricing,
        mock_credential,
    ):
        """When max_output_tokens is set, it should be written to settings.json."""
        runtime = FakeRuntime()
        spec = DockerEnvironmentSpec(
            name="test",
            docker=DockerConfig(image="test-image"),
        )
        session = FakeSession(
            runtime=runtime,
            working_dir=tmp_path,
            spec=spec,
        )

        agent = ClaudeCodeAgent(
            problem_name="test-problem",
            image="test-image",
            verbose=False,
            cost_limits=mock_cost_limits,
            pricing=mock_pricing,
            credential=mock_credential,
            binary="claude",
            model="claude-test",
            timeout=None,
            settings={"existingSetting": "value"},
            env={},
            extra_args=[],
            append_system_prompt=None,
            allowed_tools=[],
            disallowed_tools=[],
            permission_mode=None,
            base_url=None,
            thinking=None,
            max_thinking_tokens=None,
            max_output_tokens=64000,
        )

        agent.setup(cast("Session", session))

        # Verify the settings file was written with max_output_tokens
        assert agent._settings_path is not None
        settings_content = json.loads(agent._settings_path.read_text())
        assert settings_content["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] == 64000
        assert settings_content["showThinkingSummaries"] is True
        assert settings_content["alwaysThinkingEnabled"] is True
        # Verify existing settings are preserved
        assert settings_content["existingSetting"] == "value"

    def test_prepare_mounts_excludes_max_output_tokens_when_none(
        self,
        tmp_path,
        mock_cost_limits,
        mock_pricing,
        mock_credential,
    ):
        """When max_output_tokens is None, it should not be in settings.json."""
        runtime = FakeRuntime()
        spec = DockerEnvironmentSpec(
            name="test",
            docker=DockerConfig(image="test-image"),
        )
        session = FakeSession(
            runtime=runtime,
            working_dir=tmp_path,
            spec=spec,
        )

        agent = ClaudeCodeAgent(
            problem_name="test-problem",
            image="test-image",
            verbose=False,
            cost_limits=mock_cost_limits,
            pricing=mock_pricing,
            credential=mock_credential,
            binary="claude",
            model="claude-test",
            timeout=None,
            settings={"existingSetting": "value"},
            env={},
            extra_args=[],
            append_system_prompt=None,
            allowed_tools=[],
            disallowed_tools=[],
            permission_mode=None,
            base_url=None,
            thinking=None,
            max_thinking_tokens=None,
            max_output_tokens=None,
        )

        agent.setup(cast("Session", session))

        # Verify the settings file was written without max_output_tokens
        assert agent._settings_path is not None
        settings_content = json.loads(agent._settings_path.read_text())
        assert "CLAUDE_CODE_MAX_OUTPUT_TOKENS" not in settings_content
        # Verify existing settings are preserved
        assert settings_content["existingSetting"] == "value"

    def test_prepare_mounts_does_not_mutate_original_settings(
        self,
        tmp_path,
        mock_cost_limits,
        mock_pricing,
        mock_credential,
    ):
        """Setting max_output_tokens should not mutate the original settings dict."""
        runtime = FakeRuntime()
        spec = DockerEnvironmentSpec(
            name="test",
            docker=DockerConfig(image="test-image"),
        )
        session = FakeSession(
            runtime=runtime,
            working_dir=tmp_path,
            spec=spec,
        )

        original_settings = {"existingSetting": "value"}
        agent = ClaudeCodeAgent(
            problem_name="test-problem",
            image="test-image",
            verbose=False,
            cost_limits=mock_cost_limits,
            pricing=mock_pricing,
            credential=mock_credential,
            binary="claude",
            model="claude-test",
            timeout=None,
            settings=original_settings,
            env={},
            extra_args=[],
            append_system_prompt=None,
            allowed_tools=[],
            disallowed_tools=[],
            permission_mode=None,
            base_url=None,
            thinking=None,
            max_thinking_tokens=None,
            max_output_tokens=64000,
        )

        agent.setup(cast("Session", session))

        # Original settings should not be mutated
        assert "CLAUDE_CODE_MAX_OUTPUT_TOKENS" not in original_settings
        assert original_settings == {"existingSetting": "value"}

    def test_prepare_mounts_writes_openrouter_env_to_settings(
        self,
        tmp_path,
        mock_cost_limits,
        mock_pricing,
        openrouter_credential,
    ):
        """OpenRouter auth should be written into Claude settings env."""
        runtime = FakeRuntime()
        spec = DockerEnvironmentSpec(
            name="test",
            docker=DockerConfig(image="test-image"),
        )
        session = FakeSession(
            runtime=runtime,
            working_dir=tmp_path,
            spec=spec,
        )

        agent = ClaudeCodeAgent(
            problem_name="test-problem",
            image="test-image",
            verbose=False,
            cost_limits=mock_cost_limits,
            pricing=mock_pricing,
            credential=openrouter_credential,
            binary="claude",
            model="z-ai/glm-4.7",
            timeout=None,
            settings={"existingSetting": "value"},
            env={"ANTHROPIC_DEFAULT_SONNET_MODEL": "z-ai/glm-4.7"},
            extra_args=[],
            append_system_prompt=None,
            allowed_tools=[],
            disallowed_tools=[],
            permission_mode=None,
            base_url="https://openrouter.ai/api",
            thinking=None,
            max_thinking_tokens=None,
            max_output_tokens=None,
        )

        agent.setup(cast("Session", session))

        assert agent._settings_path is not None
        settings_content = json.loads(agent._settings_path.read_text())
        settings_env = settings_content["env"]
        assert settings_env["ANTHROPIC_BASE_URL"] == "https://openrouter.ai/api"
        assert (
            settings_env["ANTHROPIC_AUTH_TOKEN"] == openrouter_credential.value
        )
        assert settings_env["ANTHROPIC_API_KEY"] == ""
        assert settings_env["ANTHROPIC_DEFAULT_SONNET_MODEL"] == "z-ai/glm-4.7"
        assert settings_content["existingSetting"] == "value"

    def test_from_config_resolves_openrouter_endpoint_and_model_defaults(
        self,
        mock_cost_limits,
        openrouter_credential,
    ):
        """OpenRouter provider override should set endpoint and model slugs."""
        config = ClaudeCodeConfig(
            type="claude_code",
            version="2.0.51",
            cost_limits=mock_cost_limits,
        )
        model = ModelCatalog.get("glm-4.7")
        assert model is not None

        agent = ClaudeCodeAgent._from_config(
            config=config,
            model=model,
            credential=openrouter_credential,
            problem_name="test-problem",
            verbose=False,
            image="test-image",
        )

        assert isinstance(agent, ClaudeCodeAgent)
        assert agent.base_url == "https://openrouter.ai/api"
        assert agent.model == "z-ai/glm-4.7"
        assert agent.env["ANTHROPIC_DEFAULT_SONNET_MODEL"] == "z-ai/glm-4.7"
        assert agent.env["ANTHROPIC_DEFAULT_OPUS_MODEL"] == "z-ai/glm-4.7"
        assert (
            agent.env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] == "z-ai/glm-4.7-flash"
        )

    def test_from_config_prefers_provider_specific_env_overrides(
        self,
        mock_cost_limits,
        mock_pricing,
        openrouter_credential,
    ):
        """Provider-specific Claude env overrides should win over defaults."""
        config = ClaudeCodeConfig(
            type="claude_code",
            version="2.0.51",
            cost_limits=mock_cost_limits,
        )
        model = ModelDefinition(
            internal_name="glm-4.7",
            provider="zhipu",
            pricing=mock_pricing,
            provider_slugs={"openrouter": "z-ai/glm-4.7"},
            agent_specific={
                "claude_code": {
                    "endpoint": "anthropic",
                    "env_overrides": {
                        "ANTHROPIC_DEFAULT_OPUS_MODEL": "glm-4.7",
                    },
                    "provider_env_overrides": {
                        "openrouter": {
                            "ANTHROPIC_DEFAULT_OPUS_MODEL": "z-ai/glm-5",
                            "ANTHROPIC_DEFAULT_SONNET_MODEL": "z-ai/glm-4.7",
                        }
                    },
                }
            },
        )

        agent = ClaudeCodeAgent._from_config(
            config=config,
            model=model,
            credential=openrouter_credential,
            problem_name="test-problem",
            verbose=False,
            image="test-image",
        )

        assert isinstance(agent, ClaudeCodeAgent)
        assert agent.env["ANTHROPIC_DEFAULT_OPUS_MODEL"] == "z-ai/glm-5"
        assert agent.env["ANTHROPIC_DEFAULT_SONNET_MODEL"] == "z-ai/glm-4.7"


class TestParseLineErrorHandling:
    """Tests for error payload handling in parse_line and _run."""

    def test_parse_line_identifies_successful_result(self):
        """parse_line returns cost and tokens for successful result."""
        payload = {
            "type": "result",
            "total_cost_usd": 0.5,
            "usage": {
                "input_tokens": 100,
                "output_tokens": 50,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
            },
        }
        line = json.dumps(payload)
        cost, tokens, parsed = ClaudeCodeAgent.parse_line(line)
        assert cost == 0.5
        assert tokens is not None
        assert tokens.input == 100
        assert tokens.output == 50
        assert not parsed.get("is_error", False)

    def test_parse_line_identifies_error_result(self):
        """parse_line returns payload with is_error for error results."""
        payload = {
            "type": "result",
            "subtype": "error_during_execution",
            "is_error": True,
            "total_cost_usd": 0,
            "usage": {
                "input_tokens": 0,
                "output_tokens": 0,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
            },
            "errors": ["some error"],
        }
        line = json.dumps(payload)
        cost, tokens, parsed = ClaudeCodeAgent.parse_line(line)
        assert parsed["is_error"] is True

    def test_parse_line_treats_null_cache_usage_as_zero(self):
        """parse_line should coerce null cache token counts to zero."""
        payload = {
            "type": "result",
            "total_cost_usd": 0.5,
            "usage": {
                "input_tokens": 100,
                "output_tokens": 50,
                "cache_creation_input_tokens": None,
                "cache_read_input_tokens": None,
            },
        }

        cost, tokens, parsed = ClaudeCodeAgent.parse_line(json.dumps(payload))

        assert cost == 0.5
        assert tokens is not None
        assert tokens.cache_read == 0
        assert tokens.cache_write == 0
        assert parsed == payload

    def test_openrouter_result_uses_configured_pricing_over_cli_cost(
        self,
        mock_cost_limits,
        openrouter_credential,
    ):
        """OpenRouter Claude Code runs should use configured model pricing."""
        pricing = APIPricing(
            input=0.3,
            output=1.2,
            cache_read=0.06,
            cache_write=0.375,
        )
        agent = ClaudeCodeAgent(
            problem_name="test-problem",
            image="test-image",
            verbose=False,
            cost_limits=mock_cost_limits,
            pricing=pricing,
            credential=openrouter_credential,
            binary="claude",
            model="minimax-m2.7",
            timeout=None,
            settings={},
            env={},
            extra_args=[],
            append_system_prompt=None,
            allowed_tools=[],
            disallowed_tools=[],
            permission_mode=None,
            base_url=None,
            thinking=None,
            max_thinking_tokens=None,
            max_output_tokens=None,
        )
        payload = {
            "type": "result",
            "total_cost_usd": 5.086003799999994,
            "usage": {
                "input_tokens": 243496,
                "output_tokens": 89876,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 7889303,
            },
            "modelUsage": {
                "minimax/minimax-m2.7": {
                    "inputTokens": 319912,
                    "outputTokens": 117245,
                    "cacheReadInputTokens": 7891976,
                    "cacheCreationInputTokens": 0,
                    "costUSD": 5.086003799999994,
                }
            },
        }

        cost, tokens = agent._resolve_result_usage(
            payload=payload,
            reported_cost=cast("float", payload["total_cost_usd"]),
            reported_tokens=ClaudeCodeAgent.parse_line(json.dumps(payload))[1],
        )

        assert cost == pytest.approx(0.61421256)
        assert tokens is not None
        assert tokens.input == 319912
        assert tokens.output == 117245
        assert tokens.cache_read == 7891976
        assert tokens.cache_write == 0

    def test_final_result_replaces_streamed_net_tokens(
        self,
        monkeypatch,
        mock_cost_limits,
        mock_pricing,
        mock_credential,
    ):
        """Final result usage should not be added on top of streamed usage."""
        agent = ClaudeCodeAgent(
            problem_name="test-problem",
            image="test-image",
            verbose=False,
            cost_limits=mock_cost_limits,
            pricing=mock_pricing,
            credential=mock_credential,
            binary="claude",
            model="claude-test",
            timeout=None,
            settings={},
            env={},
            extra_args=[],
            append_system_prompt=None,
            allowed_tools=[],
            disallowed_tools=[],
            permission_mode=None,
            base_url=None,
            thinking=None,
            max_thinking_tokens=None,
            max_output_tokens=None,
        )
        agent._runtime = cast("StreamingRuntime", FakeRuntime())  # noqa: SLF001

        streamed_tokens = TokenUsage(
            input=1,
            output=10,
            cache_read=100,
            cache_write=20,
        )
        final_tokens = TokenUsage(
            input=2,
            output=30,
            cache_read=300,
            cache_write=40,
        )

        def fake_stream_cli_command(**_: object):
            yield (
                None,
                streamed_tokens,
                {
                    "type": "assistant",
                    "message": {
                        "id": "msg_1",
                        "role": "assistant",
                        "content": [{"type": "text", "text": "working"}],
                    },
                },
            )
            yield (
                0.5,
                final_tokens,
                {
                    "type": "result",
                    "total_cost_usd": 0.5,
                    "usage": {
                        "input_tokens": 2,
                        "output_tokens": 30,
                        "cache_read_input_tokens": 300,
                        "cache_creation_input_tokens": 40,
                    },
                },
            )
            yield RuntimeResult(
                exit_code=0,
                stdout="",
                stderr="",
                setup_stdout="",
                setup_stderr="",
                elapsed=1.0,
                timed_out=False,
            )

        monkeypatch.setattr(
            "slop_code.agent_runner.agents.claude_code.agent.stream_cli_command",
            fake_stream_cli_command,
        )

        agent._run("claude", {})  # noqa: SLF001

        assert agent.usage.cost == 0.5
        assert agent.usage.steps == 1
        assert agent.usage.current_tokens == final_tokens
        assert agent.usage.net_tokens == final_tokens

    def test_error_before_success_should_fail_run(
        self,
        tmp_path,
        mock_cost_limits,
        mock_pricing,
        mock_credential,
    ):
        """Error payload before any successful result should mark run as failed."""
        agent = ClaudeCodeAgent(
            problem_name="test-problem",
            image="test-image",
            verbose=False,
            cost_limits=mock_cost_limits,
            pricing=mock_pricing,
            credential=mock_credential,
            binary="claude",
            model="claude-test",
            timeout=None,
            settings={},
            env={},
            extra_args=[],
            append_system_prompt=None,
            allowed_tools=[],
            disallowed_tools=[],
            permission_mode=None,
            base_url=None,
            thinking=None,
            max_thinking_tokens=None,
            max_output_tokens=None,
        )

        # Simulate processing an error payload before any success
        error_payload = {
            "type": "result",
            "is_error": True,
            "total_cost_usd": 0,
            "usage": {"input_tokens": 0, "output_tokens": 0},
        }

        # Process the error - should set _had_error since no success yet
        agent._process_payload_for_error(error_payload)
        assert agent._had_error is True

    def test_success_result_sets_got_successful_result(
        self,
        tmp_path,
        mock_cost_limits,
        mock_pricing,
        mock_credential,
    ):
        """Successful result payload should set _got_successful_result flag."""
        agent = ClaudeCodeAgent(
            problem_name="test-problem",
            image="test-image",
            verbose=False,
            cost_limits=mock_cost_limits,
            pricing=mock_pricing,
            credential=mock_credential,
            binary="claude",
            model="claude-test",
            timeout=None,
            settings={},
            env={},
            extra_args=[],
            append_system_prompt=None,
            allowed_tools=[],
            disallowed_tools=[],
            permission_mode=None,
            base_url=None,
            thinking=None,
            max_thinking_tokens=None,
            max_output_tokens=None,
        )

        # Simulate processing a successful result payload
        success_payload = {
            "type": "result",
            "total_cost_usd": 0.5,
            "usage": {"input_tokens": 100, "output_tokens": 50},
        }

        agent._process_payload_for_error(success_payload)
        assert agent._got_successful_result is True
        assert agent._had_error is False

    def test_error_after_success_should_not_fail_run(
        self,
        tmp_path,
        mock_cost_limits,
        mock_pricing,
        mock_credential,
    ):
        """Error payload after successful result should not mark run as failed.

        This reproduces the bug where:
        1. Task completes successfully (result payload with is_error=False)
        2. Post-completion error occurs (result payload with is_error=True, 403)
        3. Run incorrectly marked as failed

        The agent should NOT set _had_error when error comes after success.
        """
        agent = ClaudeCodeAgent(
            problem_name="test-problem",
            image="test-image",
            verbose=False,
            cost_limits=mock_cost_limits,
            pricing=mock_pricing,
            credential=mock_credential,
            binary="claude",
            model="claude-test",
            timeout=None,
            settings={},
            env={},
            extra_args=[],
            append_system_prompt=None,
            allowed_tools=[],
            disallowed_tools=[],
            permission_mode=None,
            base_url=None,
            thinking=None,
            max_thinking_tokens=None,
            max_output_tokens=None,
        )

        # First: successful result (task completed)
        success_payload = {
            "type": "result",
            "total_cost_usd": 0.5,
            "usage": {"input_tokens": 100, "output_tokens": 50},
        }
        agent._process_payload_for_error(success_payload)

        # Second: error result (post-completion error like 403 telemetry failure)
        error_payload = {
            "type": "result",
            "is_error": True,
            "subtype": "error_during_execution",
            "total_cost_usd": 0,
            "usage": {"input_tokens": 0, "output_tokens": 0},
            "errors": ["AxiosError: Request failed with status code 403"],
        }
        agent._process_payload_for_error(error_payload)

        # _had_error should remain False because we got a successful result first
        assert agent._got_successful_result is True
        assert agent._had_error is False

    def test_reset_clears_got_successful_result(
        self,
        tmp_path,
        mock_cost_limits,
        mock_pricing,
        mock_credential,
    ):
        """reset() should clear _got_successful_result for next checkpoint."""
        agent = ClaudeCodeAgent(
            problem_name="test-problem",
            image="test-image",
            verbose=False,
            cost_limits=mock_cost_limits,
            pricing=mock_pricing,
            credential=mock_credential,
            binary="claude",
            model="claude-test",
            timeout=None,
            settings={},
            env={},
            extra_args=[],
            append_system_prompt=None,
            allowed_tools=[],
            disallowed_tools=[],
            permission_mode=None,
            base_url=None,
            thinking=None,
            max_thinking_tokens=None,
            max_output_tokens=None,
        )

        # Simulate a successful run
        agent._got_successful_result = True

        # Reset for next checkpoint
        agent.reset()

        # Flag should be cleared
        assert agent._got_successful_result is False


class TestBedrockMode:
    """Tests for Bedrock integration in ClaudeCodeAgent."""

    @pytest.fixture
    def bedrock_credential(self):
        return ProviderCredential(
            provider="bedrock",
            value="test-bedrock-token",
            source="AWS_BEARER_TOKEN_BEDROCK",
            destination_key="AWS_BEARER_TOKEN_BEDROCK",
            credential_type=CredentialType.ENV_VAR,
        )

    def _make_bedrock_agent(
        self, mock_cost_limits, mock_pricing, bedrock_credential
    ):
        return ClaudeCodeAgent(
            problem_name="test-problem",
            image="test-image",
            verbose=False,
            cost_limits=mock_cost_limits,
            pricing=mock_pricing,
            credential=bedrock_credential,
            binary="claude",
            model="us.anthropic.claude-sonnet-4-6",
            timeout=None,
            settings={},
            env={},
            extra_args=[],
            append_system_prompt=None,
            allowed_tools=[],
            disallowed_tools=[],
            permission_mode=None,
            base_url=None,
            thinking=None,
            max_thinking_tokens=None,
            max_output_tokens=None,
            bedrock=True,
        )

    def test_bedrock_flag_set_from_credential(
        self, mock_cost_limits, mock_pricing, bedrock_credential
    ):
        agent = self._make_bedrock_agent(
            mock_cost_limits, mock_pricing, bedrock_credential
        )
        assert agent._bedrock is True

    def test_non_bedrock_agent_has_bedrock_false(
        self, mock_cost_limits, mock_pricing, mock_credential
    ):
        agent = ClaudeCodeAgent(
            problem_name="test-problem",
            image="test-image",
            verbose=False,
            cost_limits=mock_cost_limits,
            pricing=mock_pricing,
            credential=mock_credential,
            binary="claude",
            model="claude-test",
            timeout=None,
            settings={},
            env={},
            extra_args=[],
            append_system_prompt=None,
            allowed_tools=[],
            disallowed_tools=[],
            permission_mode=None,
            base_url=None,
            thinking=None,
            max_thinking_tokens=None,
            max_output_tokens=None,
        )
        assert agent._bedrock is False

    def test_build_cli_args_for_retry_continues_latest_session(
        self, mock_cost_limits, mock_pricing, mock_credential
    ):
        agent = ClaudeCodeAgent(
            problem_name="test-problem",
            image="test-image",
            verbose=False,
            cost_limits=mock_cost_limits,
            pricing=mock_pricing,
            credential=mock_credential,
            binary="claude",
            model="claude-test",
            timeout=None,
            settings={},
            env={},
            extra_args=[],
            append_system_prompt=None,
            allowed_tools=[],
            disallowed_tools=[],
            permission_mode=None,
            base_url=None,
            thinking=None,
            max_thinking_tokens=None,
            max_output_tokens=None,
        )

        args = agent._build_cli_args(resume=True)

        assert "--continue" in args

    def test_bedrock_env_vars_set_in_prepare_runtime(
        self,
        mock_cost_limits,
        mock_pricing,
        bedrock_credential,
        monkeypatch,
    ):
        monkeypatch.setenv("AWS_REGION", "eu-west-1")
        agent = self._make_bedrock_agent(
            mock_cost_limits, mock_pricing, bedrock_credential
        )
        _, env = agent._prepare_runtime_execution("do the thing")

        assert env["CLAUDE_CODE_USE_BEDROCK"] == "1"
        assert env["AWS_BEARER_TOKEN_BEDROCK"] == bedrock_credential.value
        assert env["AWS_REGION"] == "eu-west-1"
        assert "ANTHROPIC_API_KEY" not in env
        assert "ANTHROPIC_AUTH_TOKEN" not in env

    def test_bedrock_defaults_region_to_us_east_1(
        self,
        mock_cost_limits,
        mock_pricing,
        bedrock_credential,
        monkeypatch,
    ):
        monkeypatch.delenv("AWS_REGION", raising=False)
        agent = self._make_bedrock_agent(
            mock_cost_limits, mock_pricing, bedrock_credential
        )
        _, env = agent._prepare_runtime_execution("task")

        assert env["AWS_REGION"] == "us-east-1"

    def test_bedrock_passes_optional_env_vars(
        self,
        mock_cost_limits,
        mock_pricing,
        bedrock_credential,
        monkeypatch,
    ):
        monkeypatch.setenv("ANTHROPIC_SMALL_FAST_MODEL_AWS_REGION", "us-west-2")
        monkeypatch.setenv(
            "ANTHROPIC_BEDROCK_BASE_URL",
            "https://bedrock-runtime.us-east-1.amazonaws.com",
        )
        agent = self._make_bedrock_agent(
            mock_cost_limits, mock_pricing, bedrock_credential
        )
        _, env = agent._prepare_runtime_execution("task")

        assert env["ANTHROPIC_SMALL_FAST_MODEL_AWS_REGION"] == "us-west-2"
        assert (
            env["ANTHROPIC_BEDROCK_BASE_URL"]
            == "https://bedrock-runtime.us-east-1.amazonaws.com"
        )

    def test_bedrock_optional_env_vars_omitted_when_unset(
        self,
        mock_cost_limits,
        mock_pricing,
        bedrock_credential,
        monkeypatch,
    ):
        monkeypatch.delenv(
            "ANTHROPIC_SMALL_FAST_MODEL_AWS_REGION", raising=False
        )
        monkeypatch.delenv("ANTHROPIC_BEDROCK_BASE_URL", raising=False)
        agent = self._make_bedrock_agent(
            mock_cost_limits, mock_pricing, bedrock_credential
        )
        _, env = agent._prepare_runtime_execution("task")

        assert "ANTHROPIC_SMALL_FAST_MODEL_AWS_REGION" not in env
        assert "ANTHROPIC_BEDROCK_BASE_URL" not in env

    def test_bedrock_sets_default_model_versions(
        self,
        mock_cost_limits,
        mock_pricing,
        bedrock_credential,
        monkeypatch,
    ):
        monkeypatch.delenv("ANTHROPIC_DEFAULT_OPUS_MODEL", raising=False)
        monkeypatch.delenv("ANTHROPIC_DEFAULT_SONNET_MODEL", raising=False)
        monkeypatch.delenv("ANTHROPIC_DEFAULT_HAIKU_MODEL", raising=False)
        agent = self._make_bedrock_agent(
            mock_cost_limits, mock_pricing, bedrock_credential
        )
        _, env = agent._prepare_runtime_execution("task")

        assert (
            env["ANTHROPIC_DEFAULT_OPUS_MODEL"]
            == "us.anthropic.claude-opus-4-6-v1"
        )
        assert (
            env["ANTHROPIC_DEFAULT_SONNET_MODEL"]
            == "us.anthropic.claude-sonnet-4-6"
        )
        assert (
            env["ANTHROPIC_DEFAULT_HAIKU_MODEL"]
            == "us.anthropic.claude-haiku-4-5-20251001-v1:0"
        )

    def test_bedrock_model_versions_overridable_from_env(
        self,
        mock_cost_limits,
        mock_pricing,
        bedrock_credential,
        monkeypatch,
    ):
        monkeypatch.setenv("ANTHROPIC_DEFAULT_OPUS_MODEL", "custom-opus-id")
        monkeypatch.setenv("ANTHROPIC_DEFAULT_SONNET_MODEL", "custom-sonnet-id")
        monkeypatch.setenv("ANTHROPIC_DEFAULT_HAIKU_MODEL", "custom-haiku-id")
        agent = self._make_bedrock_agent(
            mock_cost_limits, mock_pricing, bedrock_credential
        )
        _, env = agent._prepare_runtime_execution("task")

        assert env["ANTHROPIC_DEFAULT_OPUS_MODEL"] == "custom-opus-id"
        assert env["ANTHROPIC_DEFAULT_SONNET_MODEL"] == "custom-sonnet-id"
        assert env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] == "custom-haiku-id"

    def test_bedrock_includes_common_env_vars(
        self,
        mock_cost_limits,
        mock_pricing,
        bedrock_credential,
        monkeypatch,
    ):
        monkeypatch.delenv("AWS_REGION", raising=False)
        agent = self._make_bedrock_agent(
            mock_cost_limits, mock_pricing, bedrock_credential
        )
        _, env = agent._prepare_runtime_execution("task")

        assert env["FORCE_AUTO_BACKGROUND_TASKS"] == "1"
        assert env["ENABLE_BACKGROUND_TASKS"] == "1"
        assert env["CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS"] == "1"
        assert env["DISABLE_AUTOUPDATER"] == "1"
        assert env["DISABLE_NON_ESSENTIAL_MODEL_CALLS"] == "1"


class TestFoundryMode:
    """Tests for Microsoft (Azure) Foundry integration in ClaudeCodeAgent."""

    @pytest.fixture
    def foundry_credential(self):
        return ProviderCredential(
            provider="foundry",
            value="test-foundry-key",
            source="ANTHROPIC_FOUNDRY_API_KEY",
            destination_key="ANTHROPIC_FOUNDRY_API_KEY",
            credential_type=CredentialType.ENV_VAR,
        )

    def _make_foundry_agent(
        self, mock_cost_limits, mock_pricing, foundry_credential
    ):
        return ClaudeCodeAgent(
            problem_name="test-problem",
            image="test-image",
            verbose=False,
            cost_limits=mock_cost_limits,
            pricing=mock_pricing,
            credential=foundry_credential,
            binary="claude",
            model="claude-sonnet-4-6",
            timeout=None,
            settings={},
            env={},
            extra_args=[],
            append_system_prompt=None,
            allowed_tools=[],
            disallowed_tools=[],
            permission_mode=None,
            base_url=None,
            thinking=None,
            max_thinking_tokens=None,
            max_output_tokens=None,
            foundry=True,
        )

    def test_foundry_flag_set_from_credential(
        self,
        mock_cost_limits,
        mock_pricing,
        foundry_credential,
        monkeypatch,
    ):
        monkeypatch.setenv("ANTHROPIC_FOUNDRY_RESOURCE", "my-resource")
        agent = self._make_foundry_agent(
            mock_cost_limits, mock_pricing, foundry_credential
        )
        assert agent._foundry is True

    def test_non_foundry_agent_has_foundry_false(
        self, mock_cost_limits, mock_pricing, mock_credential
    ):
        agent = ClaudeCodeAgent(
            problem_name="test-problem",
            image="test-image",
            verbose=False,
            cost_limits=mock_cost_limits,
            pricing=mock_pricing,
            credential=mock_credential,
            binary="claude",
            model="claude-test",
            timeout=None,
            settings={},
            env={},
            extra_args=[],
            append_system_prompt=None,
            allowed_tools=[],
            disallowed_tools=[],
            permission_mode=None,
            base_url=None,
            thinking=None,
            max_thinking_tokens=None,
            max_output_tokens=None,
        )
        assert agent._foundry is False

    def test_foundry_accepts_base_url_instead_of_resource(
        self,
        mock_cost_limits,
        mock_pricing,
        foundry_credential,
        monkeypatch,
    ):
        monkeypatch.delenv("ANTHROPIC_FOUNDRY_RESOURCE", raising=False)
        monkeypatch.setenv(
            "ANTHROPIC_FOUNDRY_BASE_URL",
            "https://my-resource.services.ai.azure.com/anthropic",
        )
        agent = self._make_foundry_agent(
            mock_cost_limits, mock_pricing, foundry_credential
        )
        _, env = agent._prepare_runtime_execution("task")

        assert (
            env["ANTHROPIC_FOUNDRY_BASE_URL"]
            == "https://my-resource.services.ai.azure.com/anthropic"
        )
        assert "ANTHROPIC_FOUNDRY_RESOURCE" not in env

    def test_foundry_uses_agent_base_url_when_env_unset(
        self,
        mock_cost_limits,
        mock_pricing,
        foundry_credential,
        monkeypatch,
    ):
        monkeypatch.delenv("ANTHROPIC_FOUNDRY_BASE_URL", raising=False)
        monkeypatch.delenv("ANTHROPIC_FOUNDRY_RESOURCE", raising=False)
        agent = ClaudeCodeAgent(
            problem_name="test-problem",
            image="test-image",
            verbose=False,
            cost_limits=mock_cost_limits,
            pricing=mock_pricing,
            credential=foundry_credential,
            binary="claude",
            model="claude-sonnet-4-6",
            timeout=None,
            settings={},
            env={},
            extra_args=[],
            append_system_prompt=None,
            allowed_tools=[],
            disallowed_tools=[],
            permission_mode=None,
            base_url="https://cfg-resource.services.ai.azure.com/anthropic",
            thinking=None,
            max_thinking_tokens=None,
            max_output_tokens=None,
            foundry=True,
        )
        _, env = agent._prepare_runtime_execution("task")

        assert (
            env["ANTHROPIC_FOUNDRY_BASE_URL"]
            == "https://cfg-resource.services.ai.azure.com/anthropic"
        )
        assert "ANTHROPIC_FOUNDRY_RESOURCE" not in env
        assert "ANTHROPIC_BASE_URL" not in env

    def test_foundry_env_base_url_wins_over_agent_base_url(
        self,
        mock_cost_limits,
        mock_pricing,
        foundry_credential,
        monkeypatch,
    ):
        monkeypatch.setenv(
            "ANTHROPIC_FOUNDRY_BASE_URL",
            "https://env-resource.services.ai.azure.com/anthropic",
        )
        monkeypatch.delenv("ANTHROPIC_FOUNDRY_RESOURCE", raising=False)
        agent = ClaudeCodeAgent(
            problem_name="test-problem",
            image="test-image",
            verbose=False,
            cost_limits=mock_cost_limits,
            pricing=mock_pricing,
            credential=foundry_credential,
            binary="claude",
            model="claude-sonnet-4-6",
            timeout=None,
            settings={},
            env={},
            extra_args=[],
            append_system_prompt=None,
            allowed_tools=[],
            disallowed_tools=[],
            permission_mode=None,
            base_url="https://cfg-resource.services.ai.azure.com/anthropic",
            thinking=None,
            max_thinking_tokens=None,
            max_output_tokens=None,
            foundry=True,
        )
        _, env = agent._prepare_runtime_execution("task")

        assert (
            env["ANTHROPIC_FOUNDRY_BASE_URL"]
            == "https://env-resource.services.ai.azure.com/anthropic"
        )

    def test_foundry_requires_resource_or_base_url(
        self,
        mock_cost_limits,
        mock_pricing,
        foundry_credential,
        monkeypatch,
    ):
        monkeypatch.delenv("ANTHROPIC_FOUNDRY_RESOURCE", raising=False)
        monkeypatch.delenv("ANTHROPIC_FOUNDRY_BASE_URL", raising=False)
        agent = self._make_foundry_agent(
            mock_cost_limits, mock_pricing, foundry_credential
        )
        with pytest.raises(AgentError, match="ANTHROPIC_FOUNDRY_RESOURCE"):
            agent._prepare_runtime_execution("task")

    def test_foundry_sets_default_sonnet_and_haiku_models(
        self,
        mock_cost_limits,
        mock_pricing,
        foundry_credential,
        monkeypatch,
    ):
        monkeypatch.setenv("ANTHROPIC_FOUNDRY_RESOURCE", "my-resource")
        monkeypatch.delenv("ANTHROPIC_DEFAULT_OPUS_MODEL", raising=False)
        monkeypatch.delenv("ANTHROPIC_DEFAULT_SONNET_MODEL", raising=False)
        monkeypatch.delenv("ANTHROPIC_DEFAULT_HAIKU_MODEL", raising=False)
        agent = self._make_foundry_agent(
            mock_cost_limits, mock_pricing, foundry_credential
        )
        _, env = agent._prepare_runtime_execution("task")

        assert env["ANTHROPIC_DEFAULT_SONNET_MODEL"] == "claude-sonnet-4-6"
        assert env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] == "claude-haiku-4-5"
        assert "ANTHROPIC_DEFAULT_OPUS_MODEL" not in env

    def test_foundry_model_versions_overridable_from_env(
        self,
        mock_cost_limits,
        mock_pricing,
        foundry_credential,
        monkeypatch,
    ):
        monkeypatch.setenv("ANTHROPIC_FOUNDRY_RESOURCE", "my-resource")
        monkeypatch.setenv("ANTHROPIC_DEFAULT_OPUS_MODEL", "custom-opus-id")
        monkeypatch.setenv("ANTHROPIC_DEFAULT_SONNET_MODEL", "custom-sonnet-id")
        monkeypatch.setenv("ANTHROPIC_DEFAULT_HAIKU_MODEL", "custom-haiku-id")
        agent = self._make_foundry_agent(
            mock_cost_limits, mock_pricing, foundry_credential
        )
        _, env = agent._prepare_runtime_execution("task")

        assert env["ANTHROPIC_DEFAULT_OPUS_MODEL"] == "custom-opus-id"
        assert env["ANTHROPIC_DEFAULT_SONNET_MODEL"] == "custom-sonnet-id"
        assert env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] == "custom-haiku-id"


class TestOpenRouterMode:
    """Tests for OpenRouter-backed Claude Code runs."""

    def test_openrouter_prepare_runtime_sets_anthropic_proxy_env_vars(
        self,
        mock_cost_limits,
        mock_pricing,
        openrouter_credential,
    ):
        agent = ClaudeCodeAgent(
            problem_name="test-problem",
            image="test-image",
            verbose=False,
            cost_limits=mock_cost_limits,
            pricing=mock_pricing,
            credential=openrouter_credential,
            binary="claude",
            model="z-ai/glm-5",
            timeout=None,
            settings={},
            env={"ANTHROPIC_DEFAULT_OPUS_MODEL": "z-ai/glm-5"},
            extra_args=[],
            append_system_prompt=None,
            allowed_tools=[],
            disallowed_tools=[],
            permission_mode=None,
            base_url="https://openrouter.ai/api",
            thinking=None,
            max_thinking_tokens=None,
            max_output_tokens=None,
        )

        _, env = agent._prepare_runtime_execution("task")

        assert env["OPENROUTER_API_KEY"] == openrouter_credential.value
        assert env["ANTHROPIC_AUTH_TOKEN"] == openrouter_credential.value
        assert env["ANTHROPIC_API_KEY"] == ""
        assert env["ANTHROPIC_BASE_URL"] == "https://openrouter.ai/api"
        assert env["ANTHROPIC_DEFAULT_OPUS_MODEL"] == "z-ai/glm-5"
