"""Trajectory and step models for agent execution tracking."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import JsonValue

from slop_code.common.llms import TokenUsage


class StepRole(str, Enum):
    """Enumeration of roles for trajectory steps.

    Roles:
        SYSTEM: System messages or framework actions
        USER: User input or prompts
        ASSISTANT: Agent responses or actions
        ENVIRONMENT: Environment-related messages
    """

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    ENVIRONMENT = "environment"


class TrajectoryStep(BaseModel):
    """Base model for a single step in an agent execution trajectory.

    Represents an individual action or message in the agent's execution
    timeline with metadata and timing information.

    Attributes:
        timestamp: When this step occurred
        role: The role/entity responsible for this step
        content: The message or action content
        had_error: Whether this step encountered a framework error
        wall_clock_time: Time taken for this step in seconds
        meta: Additional metadata from the framework
    """

    model_config = ConfigDict(frozen=True, use_enum_values=True, extra="forbid")
    timestamp: datetime = Field(default_factory=datetime.now)
    role: StepRole = Field(description="The role of this step.")
    content: str = Field(description="The contents of the message")
    had_error: bool = Field(
        default=False,
        description="Was there an error with the agent runner framework.",
    )
    wall_clock_time: float | None = Field(
        default=None, description="Wall clock time for this step."
    )
    meta: dict[str, JsonValue] = Field(
        default_factory=dict,
        description=(
            "Dict for extra fields/details provided by the framework. "
            "This should NOT hold repeat information already stored in the Step."
        ),
    )
    cost: float | None = Field(
        default=None, description="Cost incurred for this step in dollars."
    )
    tokens: TokenUsage | None = Field(
        default=None, description="The token usage for this step."
    )

    def is_assistant(self) -> bool:
        return self.role == StepRole.ASSISTANT
