"""Agent implementations for running against checkpoints."""

from __future__ import annotations

import typing as tp

from pydantic import Field

# Import modules for their registration side-effects and public APIs.
from slop_code.agent_runner.agents.claude_code import ClaudeCodeAgent
from slop_code.agent_runner.agents.claude_code import ClaudeCodeConfig
from slop_code.agent_runner.agents.codex import CodexAgent
from slop_code.agent_runner.agents.codex import CodexConfig
from slop_code.agent_runner.agents.gemini import GeminiAgent
from slop_code.agent_runner.agents.gemini import GeminiConfig
from slop_code.agent_runner.agents.opencode import OpenCodeAgentConfig
from slop_code.agent_runner.agents.openhands import OpenHandsAgent
from slop_code.agent_runner.agents.openhands import OpenHandsConfig
from slop_code.agent_runner.registry import iter_agent_config_types


def _build_agent_config_type() -> tp.Any:
    configs = tuple(iter_agent_config_types())
    if not configs:
        raise RuntimeError("No agent configurations have been registered.")
    union_type = tp.Union[*configs]  # type: ignore[arg-type]
    return tp.Annotated[union_type, Field(discriminator="type")]


AgentConfigType = _build_agent_config_type()

__all__ = [
    "AgentConfigType",
    "ClaudeCodeAgent",
    "ClaudeCodeConfig",
    "CodexAgent",
    "CodexConfig",
    "GeminiAgent",
    "GeminiConfig",
    "OpenCodeAgentConfig",
    "OpenHandsAgent",
    "OpenHandsConfig",
]
