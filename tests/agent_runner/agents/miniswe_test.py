"""Unit tests for MiniSWE agent implementation."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING
from unittest import mock

import pytest
from minisweagent.agents.default import ExecutionTimeoutError
from minisweagent.agents.default import FormatError
from minisweagent.agents.default import LimitsExceeded
from minisweagent.agents.default import Submitted
from minisweagent.environments.local import LocalEnvironment

from slop_code.agent_runner import Agent
from slop_code.agent_runner import AgentCostLimits
from slop_code.agent_runner.agents.miniswe import MiniSWEAgent
from slop_code.agent_runner.agents.miniswe import MiniSWEAgentConfig
from slop_code.agent_runner.credentials import CredentialType
from slop_code.agent_runner.credentials import ProviderCredential
from slop_code.agent_runner.trajectory import StepRole
from slop_code.agent_runner.trajectory import TrajectoryStep
from slop_code.common.llms import APIPricing
from slop_code.execution import DockerConfig
from slop_code.execution import DockerEnvironmentSpec
from slop_code.execution import LocalEnvironmentSpec
from slop_code.execution.models import CommandConfig
from slop_code.execution.models import EnvironmentConfig

if TYPE_CHECKING:
    from minisweagent import Model


# Default test pricing
TEST_PRICING = APIPricing(input=3, output=15, cache_read=0.30, cache_write=3.75)

# Default test model config (matching litellm settings)
DEFAULT_MODEL_CONFIG = {
    "model_name": "claude-3-5-sonnet-20241022",
    "model_class": "litellm",
}


def create_miniswe_agent(
    config: MiniSWEAgentConfig,
    model: Model,
    problem_name: str = "test",
    verbose: bool = False,
    pricing: APIPricing | None = None,
    resolved_model_config: dict | None = None,
) -> MiniSWEAgent:
    """Helper function to create a MiniSWEAgent from config and model.

    This extracts the necessary parameters from the config to match the
    new constructor signature that no longer accepts a config object.
    """
    return MiniSWEAgent(
        problem_name=problem_name,
        verbose=verbose,
        cost_limits=config.cost_limits,
        pricing=pricing or TEST_PRICING,
        model=model,
        resolved_model_config=resolved_model_config or DEFAULT_MODEL_CONFIG,
        system_template=config.system_template,
        instance_template=config.instance_template,
        timeout_template=config.timeout_template,
        format_error_template=config.format_error_template,
        action_observation_template=config.action_observation_template,
    )


@pytest.fixture
def cost_limits():
    return AgentCostLimits(step_limit=100, cost_limit=5.0, net_cost_limit=10.0)


class TestMiniSWEAgentConfig:
    """Tests for MiniSWEAgentConfig configuration."""

    def test_default_initialization(self, cost_limits):
        """Test creating a config with defaults."""
        config = MiniSWEAgentConfig(
            type="mini_swe",
            cost_limits=cost_limits,
        )
        assert config.type == "mini_swe"
        # Config no longer has model - model comes from ModelDefinition at agent creation
        assert hasattr(config, "system_template")
        assert hasattr(config, "instance_template")

    def test_custom_templates(self, cost_limits):
        """Test creating a config with custom templates."""
        config = MiniSWEAgentConfig(
            type="mini_swe",
            cost_limits=cost_limits,
            system_template="Custom system",
            instance_template="Custom instance",
        )
        assert config.type == "mini_swe"
        assert config.system_template == "Custom system"
        assert config.instance_template == "Custom instance"

    def test_get_template_vars(self, cost_limits):
        """Test get_template_vars returns expected keys."""
        config = MiniSWEAgentConfig(
            type="mini_swe", cost_limits=cost_limits
        )
        vars_dict = config.get_template_vars()

        assert "system_template" in vars_dict
        assert "instance_template" in vars_dict
        assert "timeout_template" in vars_dict
        assert "action_observation_template" in vars_dict

    @mock.patch("slop_code.agent_runner.agents.miniswe.get_model")
    def test_from_config(
        self, mock_get_model, cost_limits, mock_catalog_miniswe
    ):
        """Test Agent.from_config creates MiniSWEAgent instance."""
        config = MiniSWEAgentConfig(
            type="mini_swe",
            cost_limits=cost_limits,
        )

        mock_model = mock.Mock()
        mock_model.get_template_vars = mock.Mock(return_value={})
        mock_get_model.return_value = mock_model

        # Create model and credential for from_config
        model_def = mock_catalog_miniswe
        credential = ProviderCredential(
            provider="anthropic",
            credential_type=CredentialType.ENV_VAR,
            value="test-key",
            source="ANTHROPIC_API_KEY",
            destination_key="ANTHROPIC_API_KEY",
        )

        agent = Agent.from_config(
            config,
            model=model_def,
            credential=credential,
            problem_name="test_problem",
            verbose=False,
            image="python:3.12",
        )

        assert isinstance(agent, MiniSWEAgent)
        assert isinstance(agent, Agent)
        mock_get_model.assert_called_once()

    @mock.patch("slop_code.agent_runner.agents.miniswe.get_model")
    def test_from_config_creates_valid_agent(
        self, mock_get_model, cost_limits, mock_catalog_miniswe
    ):
        """Test Agent.from_config creates a valid Agent instance."""
        config = MiniSWEAgentConfig(
            type="mini_swe",
            cost_limits=cost_limits,
        )

        mock_model = mock.Mock()
        mock_model.get_template_vars.return_value = {}
        mock_get_model.return_value = mock_model

        # Create model and credential for from_config
        model_def = mock_catalog_miniswe
        credential = ProviderCredential(
            provider="anthropic",
            credential_type=CredentialType.ENV_VAR,
            value="test-key",
            source="ANTHROPIC_API_KEY",
            destination_key="ANTHROPIC_API_KEY",
        )

        agent = Agent.from_config(
            config,
            model=model_def,
            credential=credential,
            problem_name="test_problem",
            verbose=False,
            image="python:3.12",
        )

        # Verify it implements the Agent ABC
        assert isinstance(agent, Agent)
        assert hasattr(agent, "setup")
        assert hasattr(agent, "run")
        assert hasattr(agent, "reset")
        assert hasattr(agent, "save_artifacts")
        assert hasattr(agent, "cleanup")


class TestMiniSWEAgentBuildEnvironment:
    """Tests for MiniSWEAgent.build_environment static method."""

    @mock.patch("slop_code.agent_runner.agents.miniswe.LocalEnvironment")
    def test_build_local_environment(self, mock_local_env):
        """Test building a local environment."""
        workspace = Path("/tmp/test")
        env_spec = LocalEnvironmentSpec(
            name="test",
            type="local",
            commands=CommandConfig(command="python", agent_command="python"),
            environment=EnvironmentConfig(env={"TEST_VAR": "test_value"}),
        )

        MiniSWEAgent.build_environment(workspace, env_spec)

        mock_local_env.assert_called_once_with(
            cwd=str(workspace),
            env={"TEST_VAR": "test_value"},
        )

    @mock.patch("slop_code.agent_runner.agents.miniswe.DockerEnvironment")
    def test_build_docker_environment_basic(self, mock_docker_env):
        """Test building a basic docker environment."""
        workspace = Path("/tmp/test")
        env_spec = DockerEnvironmentSpec(
            name="test",
            type="docker",
            docker=DockerConfig(
                image="python:3.11",
                workdir="/workspace",
            ),
            commands=CommandConfig(command="python", agent_command="python"),
            environment=EnvironmentConfig(env={"DOCKER_VAR": "docker_value"}),
        )

        MiniSWEAgent.build_environment(workspace, env_spec)

        # Check that DockerEnvironment was called with expected parameters
        # Note: image uses get_base_image() which returns slop-code:{name}
        call_args = mock_docker_env.call_args
        assert call_args.kwargs["image"] == "slop-code:test"
        assert call_args.kwargs["cwd"] == "/workspace"
        assert call_args.kwargs["env"] == {"DOCKER_VAR": "docker_value"}

    @mock.patch("slop_code.agent_runner.agents.miniswe.DockerEnvironment")
    def test_build_docker_environment_with_mount(self, mock_docker_env):
        """Test building docker environment with workspace mount."""
        workspace = Path("/tmp/test")
        env_spec = DockerEnvironmentSpec(
            name="test",
            type="docker",
            docker=DockerConfig(
                image="python:3.11",
                workdir="/workspace",
                mount_workspace=True,
            ),
            commands=CommandConfig(command="python", agent_command="python"),
        )

        MiniSWEAgent.build_environment(workspace, env_spec)

        # Check that DockerEnvironment was called with run_args containing mount
        call_args = mock_docker_env.call_args
        run_args = call_args.kwargs["run_args"]
        assert any(
            f"{workspace.resolve()}:/workspace" in arg for arg in run_args
        )

    @mock.patch("slop_code.agent_runner.agents.miniswe.DockerEnvironment")
    def test_build_docker_environment_with_network(self, mock_docker_env):
        """Test building docker environment with network."""
        workspace = Path("/tmp/test")
        env_spec = DockerEnvironmentSpec(
            name="test",
            type="docker",
            docker=DockerConfig(
                image="python:3.11",
                workdir="/workspace",
                network="custom_network",
            ),
            commands=CommandConfig(command="python", agent_command="python"),
        )

        MiniSWEAgent.build_environment(workspace, env_spec)

        # Check that DockerEnvironment was called with network in run_args
        call_args = mock_docker_env.call_args
        run_args = call_args.kwargs["run_args"]
        assert "--network" in run_args
        assert "custom_network" in run_args

    @mock.patch("slop_code.agent_runner.agents.miniswe.DockerEnvironment")
    def test_build_docker_environment_defaults_user(self, mock_docker_env):
        """Default docker environment should run as current host user."""
        workspace = Path("/tmp/test")
        env_spec = DockerEnvironmentSpec(
            name="test",
            type="docker",
            docker=DockerConfig(
                image="python:3.11",
                workdir="/workspace",
            ),
            commands=CommandConfig(command="python", agent_command="python"),
        )

        with (
            mock.patch(
                "os.getuid",
                return_value=1000,
            ),
            mock.patch(
                "os.getgid",
                return_value=1000,
            ),
        ):
            MiniSWEAgent.build_environment(workspace, env_spec)

            run_args = mock_docker_env.call_args.kwargs["run_args"]
            # Should have --user with the current uid:gid
            user = env_spec.get_actual_user()
            assert "--user" in run_args
            assert user in run_args

    @mock.patch("slop_code.agent_runner.agents.miniswe.DockerEnvironment")
    def test_build_docker_environment_with_user(self, mock_docker_env):
        """Test building docker environment with user."""
        workspace = Path("/tmp/test")
        env_spec = DockerEnvironmentSpec(
            name="test",
            type="docker",
            docker=DockerConfig(
                image="python:3.11",
                workdir="/workspace",
                user="1000:1000",
            ),
            commands=CommandConfig(command="python", agent_command="python"),
        )

        MiniSWEAgent.build_environment(workspace, env_spec)

        # Check that DockerEnvironment was called with user in run_args
        call_args = mock_docker_env.call_args
        run_args = call_args.kwargs["run_args"]
        assert "--userns" not in run_args
        assert "--user" in run_args
        assert "1000:1000" in run_args

    def test_build_environment_unsupported_type(self):
        """Test building environment with unsupported type raises error."""
        workspace = Path("/tmp/test")

        # Create a mock unsupported environment spec
        mock_spec = mock.Mock()
        mock_spec.type = "unsupported"

        with pytest.raises(
            NotImplementedError, match="Unsupported environment spec"
        ):
            MiniSWEAgent.build_environment(workspace, mock_spec)


class TestMiniSWEAgentInitialization:
    """Tests for MiniSWEAgent initialization."""

    @pytest.fixture
    def mock_config(self, cost_limits, mock_catalog_miniswe):
        """Create a mock config."""
        return MiniSWEAgentConfig(
            type="mini_swe", cost_limits=cost_limits
        )

    @pytest.fixture
    def mock_model(self):
        """Create a mock model."""
        model = mock.Mock()
        model.cost = 0.0
        model.n_calls = 0
        model.get_template_vars.return_value = {}
        return model

    @pytest.fixture
    def mock_environment(self):
        """Create a mock environment."""
        env = mock.Mock(spec=LocalEnvironment)
        env.get_template_vars.return_value = {
            "system": "Linux",
            "release": "5.4.0",
            "version": "1.0",
            "machine": "x86_64",
        }
        return env

    def test_initialization(
        self, mock_config, mock_model, mock_environment, cost_limits
    ):
        """Test MiniSWEAgent initialization."""
        agent = create_miniswe_agent(
            mock_config, mock_model, problem_name="test_problem"
        )

        assert agent.model == mock_model
        assert agent._finished is False
        assert agent._steps == []
        assert agent._messages == []
        assert agent.problem_name == "test_problem"
        assert agent.cost_limits.step_limit == 100
        assert agent.usage.steps == 0
        # Verify config values are extracted as attributes
        assert agent.system_template == mock_config.system_template
        assert agent.instance_template == mock_config.instance_template

    def test_initialization_verbose_mode(
        self, mock_config, mock_model, mock_environment, cost_limits
    ):
        """Test MiniSWEAgent initialization with verbose mode."""
        agent = create_miniswe_agent(
            mock_config, mock_model, problem_name="test_problem", verbose=True
        )

        assert agent.verbose is True


class TestMiniSWEAgentMessageHandling:
    """Tests for MiniSWEAgent message handling."""

    @pytest.fixture
    def agent(self, cost_limits, mock_catalog_miniswe):
        """Create a MiniSWEAgent instance for testing."""
        config = MiniSWEAgentConfig(
            type="mini_swe", cost_limits=cost_limits
        )
        model = mock.Mock()
        model.cost = 0.0
        model.n_calls = 0
        model.get_template_vars.return_value = {}

        agent = create_miniswe_agent(config, model, problem_name="test")

        # Set up a mock environment
        env = mock.Mock(spec=LocalEnvironment)
        env.get_template_vars.return_value = {
            "system": "Linux",
            "release": "5.4.0",
            "version": "1.0",
            "machine": "x86_64",
        }
        agent._env = env

        return agent

    def test_add_message(self, agent):
        """Test adding messages to the agent."""
        agent.add_message("user", "Hello")
        agent.add_message("assistant", "Hi there", reasoning="Some reasoning")

        assert len(agent._messages) == 2
        assert agent._messages[0] == {"role": "user", "content": "Hello"}
        assert agent._messages[1] == {
            "role": "assistant",
            "content": "Hi there",
            "reasoning": "Some reasoning",
        }

    def test_render_template(self, agent):
        """Test template rendering."""
        template = "System: {{system}}, Task: {{task}}"
        agent.extra_template_vars = {"task": "Fix bug"}

        result = agent.render_template(template)

        assert "System: Linux" in result
        assert "Task: Fix bug" in result


class TestMiniSWEAgentActionParsing:
    """Tests for MiniSWEAgent action parsing."""

    @pytest.fixture
    def agent(self, cost_limits, mock_catalog_miniswe):
        """Create a MiniSWEAgent instance for testing."""
        config = MiniSWEAgentConfig(
            type="mini_swe", cost_limits=cost_limits
        )
        model = mock.Mock()
        model.cost = 0.0
        model.n_calls = 0
        model.get_template_vars.return_value = {}

        agent = create_miniswe_agent(config, model, problem_name="test")

        # Set up a mock environment
        env = mock.Mock(spec=LocalEnvironment)
        env.get_template_vars.return_value = {
            "system": "Linux",
            "release": "5.4.0",
            "version": "1.0",
            "machine": "x86_64",
        }
        agent._env = env

        return agent

    def test_parse_action_single_command(self, agent):
        """Test parsing a response with a single bash command."""
        response = {
            "content": "Let me check the files.\n\n```bash\nls -la\n```",
        }

        result = agent.parse_action(response)

        assert result["action"] == "ls -la"
        assert result["content"] == response["content"]

    def test_parse_action_with_thought(self, agent):
        """Test parsing a response with thought section."""
        response = {
            "content": (
                "THOUGHT: I need to check the files first.\n\n```bash\nls -la\n```"
            ),
        }

        result = agent.parse_action(response)

        assert result["action"] == "ls -la"

    def test_parse_action_multiline_command(self, agent):
        """Test parsing a response with multiline command."""
        response = {
            "content": (
                "Let me create a file.\n\n```bash\ncat <<'EOF' > test.txt\n"
                "line 1\nline 2\nEOF\n```"
            ),
        }

        result = agent.parse_action(response)

        assert "cat <<'EOF' > test.txt" in result["action"]
        assert "line 1" in result["action"]

    def test_parse_action_no_commands(self, agent):
        """Test parsing a response with no bash commands raises error."""
        response = {
            "content": "Just some text without commands.",
        }

        with pytest.raises(FormatError):
            agent.parse_action(response)

    def test_parse_action_multiple_commands(self, agent):
        """Test parsing a response with multiple bash commands raises error."""
        response = {
            "content": (
                "First command:\n```bash\nls\n```\n"
                "Second command:\n```bash\npwd\n```"
            ),
        }

        with pytest.raises(FormatError):
            agent.parse_action(response)


class TestMiniSWEAgentExecution:
    """Tests for MiniSWEAgent action execution."""

    @pytest.fixture
    def agent(self, cost_limits, mock_catalog_miniswe):
        """Create a MiniSWEAgent instance for testing."""
        config = MiniSWEAgentConfig(
            type="mini_swe", cost_limits=cost_limits
        )
        model = mock.Mock()
        model.cost = 0.0
        model.n_calls = 0
        model.get_template_vars.return_value = {}

        agent = create_miniswe_agent(config, model, problem_name="test")

        # Set up a mock environment
        env = mock.Mock(spec=LocalEnvironment)
        env.get_template_vars.return_value = {
            "system": "Linux",
            "release": "5.4.0",
            "version": "1.0",
            "machine": "x86_64",
        }
        agent._env = env

        return agent

    def test_execute_action_success(self, agent):
        """Test executing an action successfully."""
        action = {"action": "ls -la"}
        agent.env.execute.return_value = {
            "returncode": 0,
            "output": "file1.txt\nfile2.txt",
        }

        result = agent.execute_action(action)

        assert result["returncode"] == 0
        assert "file1.txt" in result["output"]
        agent.env.execute.assert_called_once_with("ls -la")

    def test_execute_action_timeout_expired(self, agent):
        """Test executing an action that times out (TimeoutExpired)."""
        action = {"action": "sleep 1000"}
        timeout_error = subprocess.TimeoutExpired(
            cmd="sleep 1000",
            timeout=10,
            output=b"Partial output",
        )
        agent.env.execute.side_effect = timeout_error

        with pytest.raises(ExecutionTimeoutError):
            agent.execute_action(action)

    def test_execute_action_timeout_error(self, agent):
        """Test executing an action that raises TimeoutError."""
        action = {"action": "long_running_command"}
        agent.env.execute.side_effect = TimeoutError()

        with pytest.raises(ExecutionTimeoutError):
            agent.execute_action(action)

    def test_has_finished_submit_command(self, agent):
        """Test has_finished detects submit command."""
        output = {
            "output": (
                "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT\nFinal result here"
            ),
        }

        with pytest.raises(Submitted, match="Final result here"):
            agent.has_finished(output)

    def test_has_finished_legacy_submit(self, agent):
        """Test has_finished detects legacy submit command."""
        output = {
            "output": "MINI_SWE_AGENT_FINAL_OUTPUT\nFinal result",
        }

        with pytest.raises(Submitted, match="Final result"):
            agent.has_finished(output)

    def test_has_finished_no_submit(self, agent):
        """Test has_finished does not raise when no submit command."""
        output = {
            "output": "Regular command output",
        }

        # Should not raise
        agent.has_finished(output)


class TestMiniSWEAgentSteps:
    """Tests for MiniSWEAgent step operations."""

    @pytest.fixture
    def agent(self, cost_limits, mock_catalog_miniswe):
        """Create a MiniSWEAgent instance for testing."""
        config = MiniSWEAgentConfig(
            type="mini_swe", cost_limits=cost_limits
        )
        model = mock.Mock()
        model.cost = 0.0
        model.n_calls = 0
        model.get_template_vars.return_value = {}

        agent = create_miniswe_agent(config, model, problem_name="test")

        # Set up a mock environment
        env = mock.Mock(spec=LocalEnvironment)
        env.get_template_vars.return_value = {
            "system": "Linux",
            "release": "5.4.0",
            "version": "1.0",
            "machine": "x86_64",
        }
        agent._env = env

        return agent

    def test_record_non_agent_step(self, agent):
        """Test recording a non-agent step."""
        agent.record_non_agent_step(
            role=StepRole.ENVIRONMENT,
            content="Command output",
            wall_clock_time=0.5,
            meta={"returncode": 0},
        )

        assert len(agent._steps) == 1
        assert len(agent._messages) == 1

        step = agent._steps[0]
        assert step.role == StepRole.ENVIRONMENT
        assert step.content == "Command output"
        assert step.wall_clock_time == 0.5
        assert step.meta == {"returncode": 0}

        message = agent._messages[0]
        assert message["role"] == "user"
        assert message["content"] == "Command output"

    def test_record_system_step(self, agent):
        """Test recording a system step."""
        agent.record_non_agent_step(
            role=StepRole.SYSTEM,
            content="System message",
            wall_clock_time=0.0,
        )

        assert len(agent._steps) == 1
        message = agent._messages[0]
        assert message["role"] == "system"

    def test_agent_step_success(self, agent):
        """Test successful agent step."""
        query_response = {
            "content": "Let me check the files.\n\n```bash\nls -la\n```",
            "extra": {
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 50,
                }
            },
        }
        agent.model.query.return_value = query_response

        result = agent.agent_step()

        assert (
            result["content"]
            == "Let me check the files.\n\n```bash\nls -la\n```"
        )
        assert len(agent._steps) == 1
        assert isinstance(agent._steps[0], TrajectoryStep)
        assert agent._steps[0].role == StepRole.ASSISTANT
        assert agent._steps[0].tokens.input == 100
        assert agent._steps[0].tokens.output == 50
        assert agent._steps[0].tokens.total == 150
        assert agent._steps[0].tokens.output == 50

    def test_agent_step_with_reasoning(self, agent):
        """Test agent step with reasoning."""
        query_response = {
            "content": "Command here",
            "reasoning": "I should check files first",
            "extra": {
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 50,
                    "prompt_tokens_details": {"cached_tokens": 25},
                    "completion_tokens_details": {"reasoning_tokens": 12},
                }
            },
        }
        agent.model.query.return_value = query_response

        result = agent.agent_step()

        assert result["reasoning"] == "I should check files first"
        assert agent._steps[0].tokens.cache_read == 25
        assert agent._steps[0].tokens.reasoning == 12

    def test_agent_step_hits_step_limit(self, agent):
        """Test agent step when step limit is hit."""
        agent.cost_limits.step_limit = 5

        # Manually set the usage to have 5 steps already
        agent.usage.steps = 5

        # Set up mock response to avoid Mock iteration error
        agent.model.query.return_value = {
            "content": "Test response",
            "extra": {"usage": {"prompt_tokens": 10, "completion_tokens": 5}},
        }

        with pytest.raises(LimitsExceeded):
            agent.agent_step()

        assert agent._finished is True

    def test_agent_step_hits_cost_limit(self, agent):
        """Test agent step when cost limit is hit."""
        agent.cost_limits.cost_limit = 1.0

        # Manually set the usage to have cost over the limit
        agent.usage.cost = 1.5

        # Set up mock response to avoid Mock iteration error
        agent.model.query.return_value = {
            "content": "Test response",
            "extra": {"usage": {"prompt_tokens": 10, "completion_tokens": 5}},
        }

        with pytest.raises(LimitsExceeded):
            agent.agent_step()

        assert agent._finished is True


class TestMiniSWEAgentRun:
    """Tests for MiniSWEAgent run method."""

    @pytest.fixture
    def agent(self, cost_limits, mock_catalog_miniswe):
        """Create a MiniSWEAgent instance for testing."""
        config = MiniSWEAgentConfig(
            type="mini_swe", cost_limits=cost_limits
        )
        model = mock.Mock()
        model.cost = 0.0
        model.n_calls = 0
        model.get_template_vars.return_value = {}
        env = mock.Mock(spec=LocalEnvironment)
        env.get_template_vars.return_value = {
            "system": "Linux",
            "release": "5.4.0",
            "version": "1.0",
            "machine": "x86_64",
        }
        env.execute.return_value = {
            "returncode": 0,
            "output": "Success",
        }

        agent = create_miniswe_agent(config, model, problem_name="test")

        # Set up the mock environment
        agent._env = env

        return agent

    def test_run_single_step_submission(self, agent):
        """Test run with single step leading to submission."""
        agent.model.query.return_value = {
            "content": (
                "Done.\n\n```bash\necho COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT\n```"
            ),
            "extra": {
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 50,
                }
            },
        }
        agent.env.execute.return_value = {
            "returncode": 0,
            "output": "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT\n",
        }

        steps = agent.run("Fix the bug")

        # Should have: system, task, agent response, environment response
        assert len(steps) == 4
        assert steps[0].role == StepRole.SYSTEM
        assert steps[1].role == StepRole.USER
        assert steps[2].role == StepRole.ASSISTANT
        assert steps[3].role == StepRole.ENVIRONMENT

    def test_run_hits_step_limit(self, agent):
        """Test run stops when step limit is hit."""
        call_count = 0

        def query_side_effect(_):
            nonlocal call_count
            call_count += 1
            agent.model.n_calls = call_count
            return {
                "content": (
                    f"Step {call_count}.\n\n```bash\necho step{call_count}\n```"
                ),
                "extra": {
                    "usage": {
                        "prompt_tokens": 100,
                        "completion_tokens": 50,
                    }
                },
            }

        agent.model.query.side_effect = query_side_effect

        steps = agent.run("Complex task")

        # Should stop at step limit when counting agent responses only
        assistant_steps = [
            s
            for s in steps
            if isinstance(s, TrajectoryStep) and s.role == StepRole.ASSISTANT
        ]
        assert len(assistant_steps) <= agent.cost_limits.step_limit

    def test_run_with_format_error_recovery(self, agent):
        """Test run handles format errors in responses."""
        responses = [
            {
                "content": "Invalid response with no commands",
                "extra": {
                    "usage": {
                        "prompt_tokens": 100,
                        "completion_tokens": 50,
                    }
                },
            },
            {
                "content": (
                    "Fixed.\n\n```bash\necho "
                    "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT\n```"
                ),
                "extra": {
                    "usage": {
                        "prompt_tokens": 100,
                        "completion_tokens": 50,
                    }
                },
            },
        ]

        call_count = [0]

        def query_side_effect(_):
            response = responses[min(call_count[0], len(responses) - 1)]
            call_count[0] += 1
            agent.model.n_calls = call_count[0]
            return response

        agent.model.query.side_effect = query_side_effect
        agent.env.execute.return_value = {
            "returncode": 0,
            "output": "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT\n",
        }

        steps = agent.run("Task")

        # Should have recovered from format error
        assert any(isinstance(s, TrajectoryStep) for s in steps)

    def test_run_validates_initial_state(self, agent):
        """Test run validates agent is in initial state."""
        agent._steps.append(
            TrajectoryStep(
                role=StepRole.USER,
                content="Previous step",
                wall_clock_time=0.0,
            )
        )

        with pytest.raises(
            ValueError, match="No messages but steps is not empty"
        ):
            agent.run("Task")


class TestMiniSWEAgentProgress:
    """Tests for MiniSWEAgent progress reporting."""

    @pytest.fixture
    def agent_with_progress(self, cost_limits, mock_catalog_miniswe):
        """Create an agent configured to finish after a single step."""
        config = MiniSWEAgentConfig(
            type="mini_swe", cost_limits=cost_limits
        )

        env = mock.Mock(spec=LocalEnvironment)
        env.get_template_vars.return_value = {
            "system": "Linux",
            "release": "5.4.0",
            "version": "1.0",
            "machine": "x86_64",
        }
        env.execute.return_value = {
            "returncode": 0,
            "output": "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT\nAll done\n",
        }

        model = mock.Mock()
        model.cost = 0.0
        model.n_calls = 0
        model.get_template_vars.return_value = {}

        def _query(messages):
            model.n_calls += 1
            model.cost += 0.25
            return {
                "content": (
                    "THOUGHT: finishing up\n\n"
                    "```bash\n"
                    "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT\n"
                    "```"
                ),
                "extra": {
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 5,
                        "prompt_tokens_details": {"cached_tokens": 2},
                        "completion_tokens_details": {"reasoning_tokens": 3},
                    }
                },
            }

        model.query.side_effect = _query

        agent = create_miniswe_agent(config, model, problem_name="test_problem")

        # Set up the mock environment
        agent._env = env

        return agent, model, env

    def test_progress_callback_called_during_run(self, agent_with_progress):
        """The agent should run successfully and complete the task."""
        agent, model, env = agent_with_progress

        trajectory = agent.run("Finish the task")

        roles = [step.role for step in trajectory]
        assert StepRole.ASSISTANT in roles
        assert StepRole.ENVIRONMENT in roles
        env.execute.assert_called_once_with(
            "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"
        )
        # Check the last agent step for output tokens
        last_agent_step = next(
            (
                s
                for s in reversed(trajectory)
                if isinstance(s, TrajectoryStep)
                and s.role == StepRole.ASSISTANT
            ),
            None,
        )
        assert last_agent_step is not None
        assert agent.usage.current_tokens.output == 5
        if last_agent_step.tokens is not None:
            assert last_agent_step.tokens.reasoning == 3
            assert last_agent_step.tokens.cache_read == 2
        else:
            assert agent.usage.current_tokens.reasoning == 3
            assert agent.usage.current_tokens.cache_read == 2
        assert model.n_calls == 1

    def test_get_progress_returns_expected_values(self, agent_with_progress):
        """Test that agent run completes successfully and tracks metrics."""
        agent, model, env = agent_with_progress

        trajectory = agent.run("Finish the task")

        # Check that the run completed and has the expected steps
        assert len(trajectory) > 0
        assistant_steps = [
            s
            for s in trajectory
            if isinstance(s, TrajectoryStep) and s.role == StepRole.ASSISTANT
        ]
        assert len(assistant_steps) == 1

        # Check the agent step has the expected token counts
        agent_step = assistant_steps[0]
        if agent_step.tokens is not None:
            assert agent_step.tokens.input == 10
            assert agent_step.tokens.output == 5
            assert agent_step.tokens.total == 15
        else:
            assert agent.usage.current_tokens.input == 10
            assert agent.usage.current_tokens.output == 5
            assert agent.usage.current_tokens.total == 15


class TestMiniSWEAgentReset:
    """Tests for MiniSWEAgent reset method."""

    @pytest.fixture
    def agent(self, cost_limits, mock_catalog_miniswe):
        """Create a MiniSWEAgent instance for testing."""
        config = MiniSWEAgentConfig(
            type="mini_swe", cost_limits=cost_limits
        )
        model = mock.Mock()
        model.cost = 0.0
        model.n_calls = 0
        model.get_template_vars.return_value = {}

        return create_miniswe_agent(config, model, problem_name="test")

    @mock.patch("slop_code.agent_runner.agents.miniswe.get_model")
    def test_reset_clears_state(self, mock_get_model, agent):
        """Test reset clears agent state."""
        # Setup agent with some state
        agent._steps.append(
            TrajectoryStep(
                role=StepRole.USER,
                content="Step",
                wall_clock_time=0.0,
            )
        )
        agent._messages.append({"role": "user", "content": "Message"})
        agent._finished = True

        new_model = mock.Mock()
        new_model.cost = 0.0
        new_model.n_calls = 0
        new_model.get_template_vars.return_value = {}
        mock_get_model.return_value = new_model

        agent.reset()

        assert agent._finished is False
        assert agent._steps == []
        assert agent._messages == []
        assert agent.model == new_model
        mock_get_model.assert_called_once()


class TestMiniSWEAgentGetObservation:
    """Tests for MiniSWEAgent get_observation method."""

    @pytest.fixture
    def agent(self, cost_limits, mock_catalog_miniswe):
        """Create a MiniSWEAgent instance for testing."""
        config = MiniSWEAgentConfig(
            type="mini_swe", cost_limits=cost_limits
        )
        model = mock.Mock()
        model.cost = 0.0
        model.n_calls = 0
        model.get_template_vars.return_value = {}

        agent = create_miniswe_agent(config, model, problem_name="test")

        # Set up a mock environment
        env = mock.Mock(spec=LocalEnvironment)
        env.get_template_vars.return_value = {
            "system": "Linux",
            "release": "5.4.0",
            "version": "1.0",
            "machine": "x86_64",
        }
        agent._env = env

        return agent

    def test_get_observation_success(self, agent):
        """Test get_observation with successful execution."""
        response = {
            "content": "Check files.\n\n```bash\nls -la\n```",
        }
        agent.env.execute.return_value = {
            "returncode": 0,
            "output": "file1.txt\nfile2.txt",
        }

        agent.get_observation(response)

        assert len(agent._steps) == 1
        assert agent._steps[0].role == StepRole.ENVIRONMENT
        assert "<returncode>0</returncode>" in agent._steps[0].content
        assert "file1.txt" in agent._steps[0].content

    def test_get_observation_with_terminating_exception(self, agent):
        """Test get_observation with terminating exception."""
        response = {
            "content": (
                "Submit.\n\n```bash\necho COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT\n```"
            ),
        }
        agent.env.execute.return_value = {
            "returncode": 0,
            "output": "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT\n",
        }

        agent.get_observation(response)

        assert agent._finished is True

    def test_get_observation_with_format_error(self, agent):
        """Test get_observation with format error in response."""
        response = {
            "content": "No commands here!",
        }

        agent.get_observation(response)

        assert len(agent._steps) == 1
        assert agent._steps[0].role == StepRole.ENVIRONMENT
        # Should have error message about format
        assert "EXACTLY ONE" in agent._steps[0].content


class TestMiniSWEAgentSaveArtifacts:
    """Tests for MiniSWEAgent save_artifacts method."""

    @pytest.fixture
    def agent(self, cost_limits, mock_catalog_miniswe):
        """Create a MiniSWEAgent instance for testing."""
        config = MiniSWEAgentConfig(
            type="mini_swe", cost_limits=cost_limits
        )
        model = mock.Mock()
        model.cost = 0.0
        model.n_calls = 0
        model.get_template_vars.return_value = {}

        agent = create_miniswe_agent(config, model, problem_name="test")

        # Set up a mock environment
        env = mock.Mock(spec=LocalEnvironment)
        env.get_template_vars.return_value = {
            "system": "Linux",
            "release": "5.4.0",
            "version": "1.0",
            "machine": "x86_64",
        }
        agent._env = env

        return agent

    def test_save_artifacts(self, agent, tmp_path):
        """Test save_artifacts method (currently a no-op)."""
        # This method currently does nothing, but we test it exists
        agent.save_artifacts(tmp_path)
        # Should not raise any errors
