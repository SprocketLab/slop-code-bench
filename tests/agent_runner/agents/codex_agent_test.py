"""Unit tests for the Codex agent."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from slop_code.agent_runner.agents.codex import CodexAgent
from slop_code.agent_runner.agents.codex import CodexConfig
from slop_code.agent_runner.credentials import ProviderCredential
from slop_code.agent_runner.models import AgentCostLimits
from slop_code.common.llms import APIPricing
from slop_code.common.llms import ModelDefinition
from slop_code.execution import DockerEnvironmentSpec
from slop_code.execution.runtime import RuntimeEvent


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
        stdin: str | list[str] | None,
        timeout: float | None,
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
        input=0.5,
        output=2.0,
        cache_read=0.1,
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
    """Standard ModelDefinition for tests."""
    return ModelDefinition(
        internal_name="gpt-4-test",
        provider="openai",
        pricing=mock_pricing,
        provider_slugs={"openai": "gpt-4-test"},
    )


@pytest.fixture
def mock_credential():
    """Standard credential for tests."""
    from slop_code.agent_runner.credentials import CredentialType
    return ProviderCredential(
        provider="openai",
        value="test-api-key",
        source="OPENAI_API_KEY",
        destination_key="OPENAI_API_KEY",
        credential_type=CredentialType.ENV_VAR,
    )


class TestCodexConfig:
    """Tests for CodexConfig."""

    def test_version_is_required(self, mock_cost_limits):
        """Version field is required for docker template."""
        with pytest.raises(Exception):  # Pydantic validation error
            CodexConfig(
                type="codex",
                cost_limits=mock_cost_limits,
                # Missing version
            )

    def test_config_with_version(self, mock_cost_limits):
        """Config can be created with version."""
        config = CodexConfig(
            type="codex",
            version="1.0.0",
            cost_limits=mock_cost_limits,
        )
        assert config.version == "1.0.0"
        assert config.binary == "codex"

    def test_get_docker_file_renders_version(self, mock_cost_limits):
        """get_docker_file renders version into template."""
        config = CodexConfig(
            type="codex",
            version="2.5.0",
            cost_limits=mock_cost_limits,
        )
        dockerfile = config.get_docker_file("base-image:latest")
        assert dockerfile is not None
        assert "base-image:latest" in dockerfile
        assert "@openai/codex@2.5.0" in dockerfile

class TestCodexAgent:
    """Tests for CodexAgent."""

    def test_from_config_creates_agent(
        self, mock_cost_limits, mock_model_def, mock_credential
    ):
        """_from_config creates agent from config."""
        config = CodexConfig(
            type="codex",
            version="1.0.0",
            cost_limits=mock_cost_limits,
        )

        agent = CodexAgent._from_config(
            config=config,
            model=mock_model_def,
            credential=mock_credential,
            problem_name="test-problem",
            verbose=False,
            image="test-image",
        )

        assert isinstance(agent, CodexAgent)
        assert agent.binary == "codex"

    def test_from_config_requires_image(
        self, mock_cost_limits, mock_model_def, mock_credential
    ):
        """_from_config requires image."""
        config = CodexConfig(
            type="codex",
            version="1.0.0",
            cost_limits=mock_cost_limits,
        )

        with pytest.raises(ValueError, match="requires an image"):
            CodexAgent._from_config(
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

        agent = CodexAgent(
            problem_name="test-problem",
            verbose=False,
            image="test-image",
            cost_limits=mock_cost_limits,
            pricing=mock_pricing,
            credential=None,
            binary="codex",
            model="gpt-4",
            timeout=60,
            thinking=None,
            max_thinking_tokens=None,
            extra_args=[],
            env={},
        )

        # Before setup, session access should raise
        with pytest.raises(Exception):
            _ = agent.session

        agent.setup(session)

        # After setup, session should be accessible
        assert agent.session == session

        agent.cleanup()

        # After cleanup, session is None
        assert agent._session is None

    def test_reset_clears_state(self, tmp_path, mock_cost_limits, mock_pricing):
        """reset() clears internal state."""
        runtime = FakeRuntime()
        session = FakeSession(runtime=runtime, working_dir=tmp_path)

        agent = CodexAgent(
            problem_name="test-problem",
            verbose=False,
            image="test-image",
            cost_limits=mock_cost_limits,
            pricing=mock_pricing,
            credential=None,
            binary="codex",
            model=None,
            timeout=None,
            thinking=None,
            max_thinking_tokens=None,
            extra_args=[],
            env={},
        )

        agent.setup(session)

        # Set some state
        agent._last_prompt = "some prompt"
        agent._last_command = MagicMock()

        agent.reset()

        assert agent._last_prompt == ""
        assert agent._last_command is None

    def test_build_command_basic(self, tmp_path, mock_cost_limits, mock_pricing):
        """_build_command creates correct base command."""
        agent = CodexAgent(
            problem_name="test-problem",
            verbose=False,
            image="test-image",
            cost_limits=mock_cost_limits,
            pricing=mock_pricing,
            credential=None,
            binary="codex",
            model=None,
            timeout=None,
            thinking=None,
            max_thinking_tokens=None,
            extra_args=[],
            env={},
        )

        command = agent._build_command("do something")

        assert command[0] == "codex"
        assert command[1] == "exec"
        assert "'do something'" in command  # shlex.quote wraps prompt
        assert "--skip-git-repo-check" in command
        assert "--json" in command
        assert "--dangerously-bypass-approvals-and-sandbox" in command

    def test_build_command_with_model(self, mock_cost_limits, mock_pricing):
        """_build_command includes model when specified."""
        agent = CodexAgent(
            problem_name="test-problem",
            verbose=False,
            image="test-image",
            cost_limits=mock_cost_limits,
            pricing=mock_pricing,
            credential=None,
            binary="codex",
            model="gpt-4",
            timeout=None,
            thinking=None,
            max_thinking_tokens=None,
            extra_args=[],
            env={},
        )

        command = agent._build_command("do something")

        assert "--model" in command
        model_idx = command.index("--model")
        assert command[model_idx + 1] == "gpt-4"

    def test_build_command_with_thinking(self, mock_cost_limits, mock_pricing):
        """_build_command includes thinking when specified."""
        agent = CodexAgent(
            problem_name="test-problem",
            verbose=False,
            image="test-image",
            cost_limits=mock_cost_limits,
            pricing=mock_pricing,
            credential=None,
            binary="codex",
            model=None,
            timeout=None,
            thinking="high",
            max_thinking_tokens=None,
            extra_args=[],
            env={},
        )

        command = agent._build_command("do something")

        assert "--config" in command
        config_idx = command.index("--config")
        assert 'model_reasoning_effort="high"' in command[config_idx + 1]

    def test_build_command_with_extra_args(self, mock_cost_limits, mock_pricing):
        """_build_command appends extra_args."""
        agent = CodexAgent(
            problem_name="test-problem",
            verbose=False,
            image="test-image",
            cost_limits=mock_cost_limits,
            pricing=mock_pricing,
            credential=None,
            binary="codex",
            model=None,
            timeout=None,
            thinking=None,
            max_thinking_tokens=None,
            extra_args=["--custom-flag", "value"],
            env={},
        )

        command = agent._build_command("do something")

        assert "--custom-flag" in command
        assert "value" in command

    def test_save_artifacts_writes_files(self, tmp_path, mock_cost_limits, mock_pricing):
        """save_artifacts writes prompt and trajectory files."""
        runtime = FakeRuntime()
        session = FakeSession(runtime=runtime, working_dir=tmp_path)

        agent = CodexAgent(
            problem_name="test-problem",
            verbose=False,
            image="test-image",
            cost_limits=mock_cost_limits,
            pricing=mock_pricing,
            credential=None,
            binary="codex",
            model=None,
            timeout=None,
            thinking=None,
            max_thinking_tokens=None,
            extra_args=[],
            env={},
        )

        agent.setup(session)
        agent._last_prompt = "test prompt"

        output_dir = tmp_path / "artifacts"
        agent.save_artifacts(output_dir)

        prompt_file = output_dir / "prompt.txt"
        assert prompt_file.exists()
        assert prompt_file.read_text() == "test prompt"

    def test_build_command_with_thinking_disabled(
        self, mock_cost_limits, mock_pricing
    ):
        """_build_command sets model_max_output_tokens=0 when thinking is disabled."""
        agent = CodexAgent(
            problem_name="test-problem",
            verbose=False,
            image="test-image",
            cost_limits=mock_cost_limits,
            pricing=mock_pricing,
            credential=None,
            binary="codex",
            model=None,
            timeout=None,
            thinking="disabled",
            max_thinking_tokens=None,
            extra_args=[],
            env={},
        )

        command = agent._build_command("do something")

        assert "--config" in command
        config_idx = command.index("--config")
        assert "model_max_output_tokens=0" in command[config_idx + 1]
        # model_reasoning_effort should NOT be present
        command_str = " ".join(command)
        assert "model_reasoning_effort" not in command_str

    def test_build_command_with_max_thinking_tokens(
        self, mock_cost_limits, mock_pricing
    ):
        """_build_command includes max_thinking_tokens when specified."""
        agent = CodexAgent(
            problem_name="test-problem",
            verbose=False,
            image="test-image",
            cost_limits=mock_cost_limits,
            pricing=mock_pricing,
            credential=None,
            binary="codex",
            model=None,
            timeout=None,
            thinking=None,
            max_thinking_tokens=8192,
            extra_args=[],
            env={},
        )

        command = agent._build_command("do something")

        assert "--config" in command
        config_idx = command.index("--config")
        assert "model_max_output_tokens=8192" in command[config_idx + 1]
