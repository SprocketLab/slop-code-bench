"""Pydantic models for unified run configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import model_validator

from slop_code.evaluation import PassPolicy

ThinkingPresetType = Literal["none", "disabled", "low", "medium", "high"]


class OneShotConfig(BaseModel):
    """Configuration for one-shot mode."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    prefix: str = ""
    include_first_prefix: bool = False


class ModelConfig(BaseModel):
    """Model configuration - object format only.

    Attributes:
        provider: The credential provider (e.g., "anthropic", "openai")
        name: The model name from the catalog (e.g., "sonnet-4.5")
    """

    model_config = ConfigDict(extra="forbid")

    provider: str
    name: str


class ThinkingConfig(BaseModel):
    """Thinking configuration - either preset or max_tokens, not both.

    Attributes:
        preset: Named thinking budget (none, disabled, low, medium, high)
        max_tokens: Explicit maximum thinking tokens
    """

    model_config = ConfigDict(extra="forbid")

    preset: ThinkingPresetType | None = None
    max_tokens: int | None = None

    @model_validator(mode="after")
    def validate_mutual_exclusion(self) -> ThinkingConfig:
        """Ensure preset and max_tokens are mutually exclusive."""
        if self.preset is not None and self.max_tokens is not None:
            raise ValueError(
                "Cannot specify both 'preset' and 'max_tokens' for thinking. "
                "Use one or the other."
            )
        return self


class RunConfig(BaseModel):
    """Unified run configuration for the agent runner.

    This is the raw configuration as loaded from YAML/CLI before resolution.
    Fields like `agent`, `environment`, and `prompt` can be:
    - A bare name (e.g., "claude_code") that gets resolved via two-tier lookup
    - An explicit path (e.g., "./my_agent.yaml", "/abs/path/agent.yaml")
    - An inline dict with the full configuration

    Attributes:
        agent: Agent config reference (bare name, path, or inline dict)
        environment: Environment config reference (bare name, path, or inline dict)
        prompt: Prompt template reference (bare name or path, stem only for bare names)
        model: Model configuration with provider and name
        thinking: Thinking budget as preset string or ThinkingConfig object
        pass_policy: Policy for determining checkpoint pass/fail
        problems: Optional list of specific problems to run
        save_dir: Base directory for run outputs
        save_template: Output path template with OmegaConf interpolation support
        one_shot: Whether to run the problem as a single checkpoint with a
            combined specification.
    """

    model_config = ConfigDict(extra="forbid")

    # Can be: bare name, path string, or inline dict
    agent: str | dict[str, Any] = "claude_code-2.0.51"
    environment: str | dict[str, Any] = "docker-python3.12-uv"
    prompt: str = "just-solve"

    # Model is required but has a sensible default
    model: ModelConfig = Field(
        default_factory=lambda: ModelConfig(provider="anthropic", name="sonnet-4.5")
    )

    # Thinking - either preset string or ThinkingConfig object
    thinking: ThinkingPresetType | ThinkingConfig = "none"

    pass_policy: PassPolicy = PassPolicy.ANY

    # Optional list of specific problems to run (otherwise auto-discover)
    problems: list[str] = Field(default_factory=list)

    one_shot: OneShotConfig = Field(default_factory=OneShotConfig)

    # Output path configuration with interpolation support
    # Available variables: ${model.name}, ${model.provider}, ${agent.type},
    # ${agent.version}, ${prompt}, ${thinking}, ${env.name}, ${now:FORMAT}
    # Note: ${agent.version} is cleanly omitted if the agent has no version
    save_dir: str = "outputs"
    save_template: str = (
        "${model.name}/${agent.type}-${agent.version}_${prompt}_${thinking}_${now:%Y%m%dT%H%M}"
    )

    def get_thinking_preset(self) -> ThinkingPresetType | None:
        """Get the thinking preset value, handling both string and object forms."""
        if isinstance(self.thinking, str):
            return self.thinking
        return self.thinking.preset

    def get_thinking_max_tokens(self) -> int | None:
        """Get max_thinking_tokens if specified via ThinkingConfig."""
        if isinstance(self.thinking, ThinkingConfig):
            return self.thinking.max_tokens
        return None


class ResolvedRunConfig(BaseModel):
    """Fully resolved run configuration with all paths and configs loaded.

    This is the result of resolving a RunConfig - all references have been
    loaded from files, interpolations have been resolved, and the config
    is ready for execution.

    Attributes:
        agent_config_path: Resolved path to agent config file (if not inline)
        agent: The loaded agent config data as a dict
        environment_config_path: Resolved path to environment config file
        environment: The loaded environment config data as a dict
        prompt_path: Resolved path to prompt template file
        prompt_content: The loaded prompt template content
        model: Model configuration
        thinking: Resolved thinking preset (or None)
        thinking_max_tokens: Resolved max thinking tokens (or None)
        pass_policy: Policy for checkpoint evaluation
        problems: List of specific problems to run (empty -> auto-discover)
        save_dir: Base directory for run outputs
        save_template: Resolved output path template (interpolations applied)
        output_path: Full output path (save_dir/save_template)
        one_shot: One-shot execution configuration.
    """

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    agent_config_path: Path | None
    agent: dict[str, Any]
    environment_config_path: Path | None
    environment: dict[str, Any]
    prompt_path: Path
    prompt_content: str
    model: ModelConfig
    thinking: ThinkingPresetType | None
    thinking_max_tokens: int | None
    pass_policy: PassPolicy
    problems: list[str]
    save_dir: str
    save_template: str
    output_path: str
    one_shot: OneShotConfig
