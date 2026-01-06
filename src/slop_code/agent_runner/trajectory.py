"""Simplified trajectory step types for agent execution tracking."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Discriminator, Field


class UserStep(BaseModel):
    """System/prompt input - typically at beginning of trajectory."""

    step_type: Literal["user"] = "user"
    content: str = Field(description="The user/system message content")
    timestamp: datetime | None = Field(
        default=None, description="When this step occurred"
    )


class AgentStep(BaseModel):
    """Agent text output."""

    step_type: Literal["agent"] = "agent"
    content: str = Field(description="The agent's text output")
    timestamp: datetime | None = Field(
        default=None, description="When this step occurred"
    )


class ThinkingStep(BaseModel):
    """Agent reasoning/thinking content."""

    step_type: Literal["thinking"] = "thinking"
    content: str = Field(description="The thinking/reasoning text")
    timestamp: datetime | None = Field(
        default=None, description="When this step occurred"
    )


class ToolUseStep(BaseModel):
    """Tool invocation with result."""

    step_type: Literal["tool_use"] = "tool_use"
    type: str = Field(description="Tool name (e.g., 'Bash', 'Read', 'edit')")
    arguments: dict[str, Any] = Field(
        default_factory=dict, description="Tool input arguments"
    )
    result: str | None = Field(default=None, description="Tool execution result")
    timestamp: datetime | None = Field(
        default=None, description="When this step occurred"
    )


TrajectoryStep = Annotated[
    Union[UserStep, AgentStep, ThinkingStep, ToolUseStep],
    Discriminator("step_type"),
]


class Trajectory(BaseModel):
    """Container for parsed trajectory steps."""

    agent_type: str = Field(description="Agent identifier (e.g., 'claude_code')")
    steps: list[TrajectoryStep] = Field(
        default_factory=list, description="Chronologically ordered steps"
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Agent-specific metadata"
    )


__all__ = [
    "UserStep",
    "AgentStep",
    "ThinkingStep",
    "ToolUseStep",
    "TrajectoryStep",
    "Trajectory",
]
