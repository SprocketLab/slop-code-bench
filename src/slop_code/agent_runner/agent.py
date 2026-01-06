"""Agent interface and configuration models."""

from __future__ import annotations

import collections.abc
import traceback
from abc import ABC
from abc import abstractmethod
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import (
    ClassVar,
    Literal,
    Protocol,
    get_args,
    get_origin,
    get_type_hints,
)

from jinja2 import Template
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import field_validator
from pydantic import model_validator
from pydantic.fields import FieldInfo

from slop_code.agent_runner.credentials import ProviderCredential
from slop_code.agent_runner.models import AgentCostLimits
from slop_code.agent_runner.models import AgentError
from slop_code.agent_runner.models import UsageTracker
from slop_code.agent_runner.registry import register_agent_config
from slop_code.agent_runner.trajectory import TrajectoryStep
from slop_code.common.llms import APIPricing
from slop_code.common.llms import ModelDefinition
from slop_code.common.llms import ThinkingPreset
from slop_code.execution import Session
from slop_code.execution.runtime import RuntimeEvent
from slop_code.logging import get_logger


class AgentConfigBase(BaseModel):
    """Base configuration shared by all agent configs.

    Attributes:
        type: The type of agent (e.g., 'mini_swe', 'codex', 'claude_code')
        cost_limits: Cost and step limits for agent execution
        docker_template: Optional path to Docker template for agent
    """

    model_config = ConfigDict(extra="forbid")

    type: str = Field(frozen=True)
    cost_limits: AgentCostLimits
    docker_template: Path | None = None
    version: str | None = None
    agent_type: ClassVar[str | None] = None

    def __init_subclass__(
        cls,
        *,
        agent_type: str | None = None,
        register: bool = True,
        **kwargs,
    ) -> None:
        super().__init_subclass__(**kwargs)
        if cls is AgentConfigBase or not register:
            return

        resolved_type = agent_type or getattr(cls, "agent_type", None)
        if not resolved_type:
            resolved_type = cls._resolve_agent_type()
        if not resolved_type:
            raise TypeError(
                f"{cls.__qualname__} must declare a non-empty agent 'type'."
            )

        cls.agent_type = resolved_type
        register_agent_config(resolved_type, cls)

    @classmethod
    def _resolve_agent_type(cls) -> str | None:
        """Infer the agent type from the model field default."""
        annotation = get_type_hints(cls, include_extras=True).get("type")
        origin = get_origin(annotation)
        if origin is Literal:
            for literal_value in get_args(annotation):
                if isinstance(literal_value, str):
                    return literal_value

        if not getattr(cls, "__pydantic_complete__", False):
            cls.model_rebuild(force=True)
        type_field = cls.model_fields.get("type")
        if type_field is None:
            raw_field = cls.__dict__.get("type")
            if isinstance(raw_field, FieldInfo):
                default = raw_field.default
                if isinstance(default, str) and default:
                    return default
            return None
        default = type_field.default
        if isinstance(default, str) and default:
            return default
        return None

    @field_validator("type")
    @classmethod
    def _validate_type(cls, value: str) -> str:
        expected = cls.agent_type
        if expected is not None and value != expected:
            raise ValueError(
                f"Agent type mismatch. Expected '{expected}', got '{value}'."
            )
        return value

    @model_validator(mode="after")
    def _validate_version_for_docker_template(self) -> AgentConfigBase:
        """Ensure agents with docker_template have a non-empty version.

        Docker templates use {{ version }} to install the correct version of
        agent CLI tools. Without a version, the template renders incorrectly
        and causes Docker build failures.

        Raises:
            ValueError: If docker_template is set but version is None or empty string
        """
        if self.docker_template is not None:
            if self.version is None or (
                isinstance(self.version, str) and not self.version.strip()
            ):
                raise ValueError(
                    f"Agent '{self.type}' has a docker_template but missing or empty 'version'. "
                    f"Agents with docker templates require a non-empty version string to install "
                    f"the correct CLI tool version. Please set 'version' in the config YAML."
                )
        return self

    def get_image(self, env_name: str) -> str:
        if self.version is not None:
            return f"{self.type}-{self.version}-{env_name}"
        return f"{self.type}-{env_name}"

    def get_docker_file(
        self,
        base_image: str,
    ) -> str | None:
        if self.docker_template is None:
            return None

        template = self.docker_template.read_text()
        template = Template(template).render(base_image=base_image)
        return template


class CheckpointInferenceResult(BaseModel):
    """Result of running an agent on a single checkpoint.

    Attributes:
        started: Timestamp when execution started
        completed: Timestamp when execution completed
        elapsed: Time taken to execute the checkpoint in seconds
        usage: Token usage and cost tracking for this checkpoint
        had_error: Whether an error occurred during execution
        error_message: Detailed error message if an error occurred
        checkpoint_path: Absolute path to the checkpoint output directory
        snapshot_dir: Relative path to snapshot directory (e.g., "snapshot")
        artifacts_dir: Relative path to agent artifacts directory (e.g., "agent")
    """

    started: datetime
    completed: datetime
    elapsed: float
    usage: UsageTracker
    had_error: bool
    error_message: str | None = None
    checkpoint_path: Path | None = None
    snapshot_dir: Path | None = None
    artifacts_dir: Path | None = None


class Agent(ABC):
    """Abstract base class for agent implementations.

    Provides the interface and common functionality for all agent types.
    Agents are responsible for executing tasks and tracking their usage
    within defined cost and step limits.

    Attributes:
        problem_name: Name of the problem being solved
        log: Structured logger for the agent instance
        usage: Tracker for token usage, cost, and steps
        cost_limits: Limits for cost and steps per checkpoint
        pricing: Token pricing configuration for cost calculations
        verbose: Whether verbose logging is enabled
    """

    def __init__(
        self,
        agent_name: str,
        problem_name: str,
        cost_limits: AgentCostLimits,
        pricing: APIPricing | None,
        verbose: bool,
    ) -> None:
        """Initialize the agent wrapper.

        Args:
            agent_name: Name identifier for the agent type
            problem_name: Name of the problem being solved
            cost_limits: Cost and step limits for execution
            pricing: Token pricing configuration for cost calculations
            verbose: Whether to enable verbose logging
        """
        self.problem_name = problem_name
        self.log = get_logger(f"agent_runner.{agent_name}-{problem_name}")

        self.usage = UsageTracker()  # type: ignore[arg-type]
        self.cost_limits = cost_limits
        self.pricing = pricing
        self.verbose = verbose
        self.prior_cost = 0.0

    @classmethod
    def from_config(
        cls,
        config: AgentConfigBase,
        model: ModelDefinition,
        credential: ProviderCredential,
        problem_name: str,
        verbose: bool,
        image: str | None,
        thinking_preset: ThinkingPreset | None = None,
        thinking_max_tokens: int | None = None,
    ) -> Agent:
        """Create an agent instance from a configuration object.

        This method dispatches to the correct agent class based on the config
        type using the agent registry.

        Args:
            config: The agent configuration object
            model: Model definition from catalog (contains pricing, agent_specific)
            credential: Resolved provider credential for API access
            problem_name: Name of the problem the agent will solve
            verbose: Whether to enable verbose logging
            image: The docker image to use if required
            thinking_preset: Optional thinking preset override (default from model)
            thinking_max_tokens: Optional max thinking tokens override

        Returns:
            Configured Agent instance
        """
        from slop_code.agent_runner.registry import get_agent_cls

        agent_cls = get_agent_cls(config.type)
        return agent_cls._from_config(
            config,
            model,
            credential,
            problem_name,
            verbose,
            image,
            thinking_preset,
            thinking_max_tokens,
        )

    @classmethod
    @abstractmethod
    def _from_config(
        cls,
        config: AgentConfigBase,
        model: ModelDefinition,
        credential: ProviderCredential,
        problem_name: str,
        verbose: bool,
        image: str | None,
        thinking_preset: ThinkingPreset | None = None,
        thinking_max_tokens: int | None = None,
    ) -> Agent:
        """Subclass implementation of from_config.

        Override this method in concrete agent classes. Do not override
        from_config directly.

        Args:
            config: The agent configuration object (cast to expected type)
            model: Model definition from catalog
            credential: Resolved provider credential
            problem_name: Name of the problem the agent will solve
            verbose: Whether to enable verbose logging
            image: The docker image to use if required
            thinking_preset: Optional thinking preset override
            thinking_max_tokens: Optional max thinking tokens override

        Returns:
            Configured Agent instance
        """

    @abstractmethod
    def setup(
        self,
        session: Session,
    ) -> None:
        """Sets up the agent with the given environment.

        Args:
            session: Execution session for the agent to work in
        """

    def supports_replay(self) -> bool:
        """Return whether the agent can execute recorded trajectories.

        Returns:
            True if the agent supports replay functionality, False otherwise
        """

        return False

    def run_replay(self, path: Path) -> CheckpointInferenceResult:
        """Load replay steps from a JSONL trajectory file if it exists.

        Args:
            path: Path to the JSONL trajectory file to replay

        Returns:
            CheckpointResult from replaying the trajectory

        Raises:
            AgentError: If the agent does not support replay
        """

        raise AgentError(f"{self.__class__.__name__} does not support replay")

    @abstractmethod
    def run(self, task: str):
        """Starts the agent until completion with the task string as the starting prompt.

        Does NOT reset the context/messages/stats. That is done by `reset`.

        Args:
            task (str): The starting prompt for this run. Is appended as a user message.

        Returns:
            The list of AgentSteps for the run.
        """

    @abstractmethod
    def reset(self) -> None:
        """Resets the state of the agent and the context.

        Args:
            reset_context: Whether to reset the context of the agent.

        Does NOT reset the working directory state. This should clear
        conversation history, internal state, and prepare for a fresh start.
        If reset_context is False, the context will not be reset.
        """

    @abstractmethod
    def save_artifacts(self, path: Path) -> None:
        """Save the native artifacts of the agent.

        Args:
            path: Directory path where artifacts should be saved
        """

    @abstractmethod
    def cleanup(self) -> None:
        """Clean up resources held by the agent.

        This method is called when the agent runner is exiting to ensure
        proper cleanup of any resources (environments, connections, etc.).
        """

    def hit_net_rate_limit(self) -> bool:
        """Check if the agent has hit a rate limit.

        Returns:
            True if a rate limit has been hit, False otherwise.
        """

        if self.cost_limits.net_cost_limit == 0:
            return False
        return (
            self.usage.cost + self.prior_cost >= self.cost_limits.net_cost_limit
        )

    def run_checkpoint(self, task: str) -> CheckpointInferenceResult:
        """Run the agent on a checkpoint task and track execution metrics.

        Args:
            task: The task prompt to execute

        Returns:
            CheckpointResult containing execution metrics and any errors
        """
        started = datetime.now()
        had_error = False
        error = None
        try:
            self.run(task)
        except Exception as e:
            had_error = True
            error = traceback.format_exc()
            self.log.error(
                "Exception raised while running task",
                exception_type=type(e).__qualname__,
                exc_info=True,
            )

        finally:
            completed = datetime.now()
            elapsed = (completed - started).total_seconds()

        return CheckpointInferenceResult(
            started=started,
            completed=completed,
            elapsed=elapsed,
            usage=self.usage,
            had_error=had_error,
            error_message=error,
        )

    def finish_checkpoint(self, reset_context: bool = True) -> None:
        """Reset agent state and usage tracking for a new checkpoint.

        Args:
            reset_context: Whether to reset the context of the agent.
        """
        if reset_context:
            self.reset()
        self.prior_cost += self.usage.cost
        self.usage = UsageTracker()  # type: ignore[arg-type]


class StreamParser(Protocol):
    """Parses streaming RuntimeEvents from `SubmissionRuntime.stream()` into
    usage totals and trajectory steps."""

    @property
    def totals(self) -> Mapping[str, int]: ...

    def consume(self, event: RuntimeEvent) -> None: ...

    def drain_steps(self) -> collections.abc.Iterable[TrajectoryStep]: ...

    def finish(self) -> collections.abc.Iterable[TrajectoryStep]: ...
