from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from slop_code.common.llms import TokenUsage
from slop_code.evaluation import PassPolicy
from slop_code.evaluation import ProblemConfig
from slop_code.execution import EnvironmentSpecType


class AgentError(Exception):
    """Base exception raised when an agent error occurs."""


class UnsupportedEnvironmentError(AgentError):
    """Exception raised when an unsupported environment is provided.

    Raised when the agent cannot operate in the specified environment
    type or configuration.
    """


class AgentSetupError(AgentError):
    """Exception raised when an agent setup error occurs.

    Raised during agent initialization or environment setup when
    configuration or resource issues prevent proper setup.
    """


class AgentStepError(AgentError):
    """Exception raised when an agent step error occurs.

    Raised during individual execution steps when the agent
    encounters an error that prevents step completion.
    """


class UsageTracker(BaseModel):
    """Tracks usage metrics for agent execution.

    Attributes:
        cost: Total cost incurred in dollars
        steps: Number of execution steps taken
        tokens: Token usage breakdown
    """

    cost: float = 0
    steps: int = 0
    net_tokens: Annotated[TokenUsage, Field(default_factory=TokenUsage)]
    current_tokens: Annotated[TokenUsage, Field(default_factory=TokenUsage)]

    def get_summary_metrics(self) -> dict[str, int | float]:
        net_summary = {
            f"{key}_net": value
            for key, value in self.net_tokens.get_summary_metrics().items()
        }
        final_summary = {
            f"{key}_final": value
            for key, value in self.current_tokens.get_summary_metrics().items()
        }
        return {
            "cost": self.cost,
            "steps": self.steps,
            **net_summary,
            **final_summary,
        }

    def step(
        self, cost: float, tokens: TokenUsage, *, add_cost: bool = True
    ) -> None:
        if add_cost:
            self.cost += cost
        else:
            self.cost = cost
        self.steps += 1
        self.net_tokens += tokens
        self.current_tokens = tokens


class AgentCostLimits(BaseModel):
    """Cost and step limits for agent execution.

    Attributes:
        step_limit: Maximum number of steps per checkpoint (0 = no limit)
        cost_limit: Maximum cost per checkpoint in dollars
        net_cost_limit: Maximum net cost per checkpoint including prior costs
    """

    step_limit: Annotated[
        int, Field(description="Maximum number of steps per checkpoint")
    ] = 0
    cost_limit: Annotated[
        float, Field(description="Maximum cost per checkpoint")
    ]
    net_cost_limit: Annotated[
        float, Field(description="Maximum net cost per checkpoint")
    ]

    def is_above_limits(
        self, usage: UsageTracker, prior_cost: float | None
    ) -> bool:
        """Check if usage exceeds any of the defined limits.

        Args:
            usage: Current usage tracker to check
            prior_cost: Previous cost for net limit calculation

        Returns:
            True if any limit is exceeded, False otherwise
        """
        if self.step_limit > 0 and usage.steps >= self.step_limit:
            return True
        if self.cost_limit > 0 and usage.cost >= self.cost_limit:
            return True

        return (
            self.net_cost_limit > 0
            and prior_cost is not None
            and usage.cost + prior_cost >= self.net_cost_limit
        )


class AgentRunSpec(BaseModel):
    """Complete specification for running an agent on a problem.

    Attributes:
        seed: Random seed for reproducible execution
        template: Jinja template for generating prompts
        problem: Problem configuration with checkpoints
        environment: Environment specification for execution
        pass_policy: Policy for determining checkpoint success
        skip_evaluation: Whether to skip evaluation and run all checkpoints
        verbose: Whether to enable verbose logging output
    """

    model_config = ConfigDict(extra="forbid")

    seed: int
    template: Annotated[str, Field(description="Jinja template for the prompt")]
    problem: Annotated[
        ProblemConfig, Field(description="Problem configuration")
    ]
    environment: Annotated[
        EnvironmentSpecType, Field(description="Environment specification")
    ]
    image: Annotated[
        str,
        Field(description="Image name to use if running with docker."),
    ]
    pass_policy: Annotated[
        PassPolicy,
        Field(description="Policy to determine if the checkpoint passed"),
    ]
    skip_evaluation: Annotated[
        bool,
        Field(
            description="Whether to skip evaluation and force all checkpoints to run."
        ),
    ] = False
    verbose: Annotated[
        bool, Field(description="Whether to print verbose output")
    ] = False
    debug: Annotated[
        bool, Field(description="Whether to print verbose output")
    ] = False
    compress_artifacts: Annotated[
        bool,
        Field(description="Whether to compress agent artifacts into a tar.gz"),
    ] = False
    agent_type: Annotated[
        str | None,
        Field(
            default=None,
            description="Agent type identifier for prompt templates",
        ),
    ] = None
    agent_version: Annotated[
        str | None,
        Field(default=None, description="Agent version for prompt templates"),
    ] = None
    model_name: Annotated[
        str | None,
        Field(default=None, description="Model name for prompt templates"),
    ] = None
