"""LLM catalog for centralized model definitions."""

from __future__ import annotations

import typing as tp
from pathlib import Path
from typing import Any, ClassVar

import yaml
from pydantic import BaseModel
from pydantic import Field
from pydantic import ValidationError
from pydantic import model_validator

from slop_code.logging import get_logger

ThinkingPreset = tp.Literal["none", "disabled", "low", "medium", "high"]

log = get_logger(__name__)


class TokenUsage(BaseModel):
    """Token usage tracking for LLM calls.

    Attributes:
        input: Number of input tokens consumed
        output: Number of output tokens generated
        cache_read: Number of tokens read from cache (cheaper)
        cache_write: Number of tokens written to cache (more expensive)
        reasoning: Number of reasoning tokens used
    """

    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_write: int = 0
    reasoning: int = 0

    def __add__(self, other: TokenUsage) -> TokenUsage:
        """Add two TokenUsage instances together."""
        return TokenUsage(
            input=self.input + other.input,
            output=self.output + other.output,
            cache_read=self.cache_read + other.cache_read,
            cache_write=self.cache_write + other.cache_write,
            reasoning=self.reasoning + other.reasoning,
        )

    def get_summary_metrics(self) -> dict[str, int | float]:
        return {
            "prompt": self.input,
            "output": self.output,
            "cache_read": self.cache_read,
            "cache_write": self.cache_write,
            "reasoning": self.reasoning,
        }

    @property
    def total(self) -> int:
        return self.input + self.output


class APIPricing(BaseModel):
    """Costs for API calls. These are per million tokens."""

    input: float = 0
    output: float = 0
    cache_read: float = 0
    cache_write: float = 0

    def get_cost(self, tokens: TokenUsage) -> float:
        mil_input = tokens.input / 1_000_000
        mil_output = tokens.output / 1_000_000
        mil_cache_read = tokens.cache_read / 1_000_000
        mil_cache_write = tokens.cache_write / 1_000_000
        return (
            self.input * mil_input
            + self.output * mil_output
            + self.cache_read * mil_cache_read
            + self.cache_write * mil_cache_write
        )


class ModelDefinition(BaseModel):
    """Definition of a model in the catalog.

    Attributes:
        name: Registered name derived from the config filename (set during registration)
        internal_name: Model identifier used for API calls (e.g., "claude-sonnet-4-5-20250929")
        provider: Credential provider name (must match APIKeyStore providers)
        pricing: API pricing per million tokens
        aliases: Alternative names that resolve to this model
        agent_specific: Agent-type to settings map for agent-specific configuration
        provider_slugs: Provider to model slug mapping. When resolving the model
            identifier for a specific provider via get_model_slug(), this takes
            precedence over internal_name. Example: {"openrouter": "z-ai/glm-4.6"}

    agent_specific Schema by Agent Type:

        mini_swe:
            model_name: str (required) - Model identifier, e.g., "openai/glm-4.6"
            model_class: str - "litellm" | "openrouter" (default: "litellm")
            api_base: str - API endpoint URL override
            model_kwargs: dict - Additional kwargs for model constructor

        claude_code:
            base_url: str - Override ANTHROPIC_BASE_URL
            env_overrides: dict[str, str] - Environment variable overrides

        codex:
            reasoning_effort: str - "low" | "medium" | "high"
            env_overrides: dict[str, str] - Environment variable overrides

        opencode:
            provider_name: str - Provider identifier for opencode config

    Thinking Configuration:
        thinking: Preset for thinking budget (none/low/medium/high)
        max_thinking_tokens: Explicit token limit (mutually exclusive with thinking)

        Can also be specified per-agent in agent_specific:
            agent_specific:
                claude_code:
                    thinking: high
    """

    internal_name: str
    provider: str
    pricing: APIPricing
    # name is set during registration from the config filename
    name: str = ""
    aliases: list[str] = Field(default_factory=list)
    agent_specific: dict[str, dict[str, Any]] = Field(default_factory=dict)
    provider_slugs: dict[str, str] = Field(default_factory=dict)

    # Thinking configuration (top-level defaults)
    thinking: ThinkingPreset | None = None
    max_thinking_tokens: int | None = None

    @model_validator(mode="after")
    def validate_thinking_config(self) -> ModelDefinition:
        """Ensure thinking and max_thinking_tokens are mutually exclusive."""
        if self.thinking is not None and self.max_thinking_tokens is not None:
            raise ValueError(
                "Cannot specify both 'thinking' and 'max_thinking_tokens'. "
                "Use 'thinking' for presets or 'max_thinking_tokens' for "
                "fine-grained control."
            )
        return self

    def get_thinking_config(
        self,
        agent_type: str | None = None,
    ) -> tuple[ThinkingPreset | None, int | None]:
        """Get thinking configuration with agent_specific override.

        Resolution order: agent_specific.{agent_type} > top-level

        Args:
            agent_type: Agent type to check for overrides (e.g., "claude_code")

        Returns:
            Tuple of (thinking_preset, max_thinking_tokens). At most one will
            be set (they are mutually exclusive).
        """
        if agent_type:
            agent_settings = self.get_agent_settings(agent_type)
            if agent_settings:
                thinking = agent_settings.get("thinking")
                max_tokens = agent_settings.get("max_thinking_tokens")
                if thinking is not None or max_tokens is not None:
                    return (thinking, max_tokens)
        return (self.thinking, self.max_thinking_tokens)

    def get_model_slug(self, provider: str | None = None) -> str:
        """Get model slug for a specific provider.

        Resolution: provider_slugs[provider] > internal_name

        Args:
            provider: Provider name to resolve slug for (e.g., "openrouter")

        Returns:
            Provider-specific slug if defined, otherwise internal_name
        """
        if provider and provider in self.provider_slugs:
            return self.provider_slugs[provider]
        return self.internal_name

    def get_agent_settings(
        self, agent_type: str | None = None
    ) -> dict[str, Any] | None:
        """Get agent-specific settings.

        Args:
            agent_type: Agent type key (e.g., "mini_swe", "opencode")

        Returns:
            Settings dict if found, None otherwise
        """
        if agent_type is None:
            return None
        return self.agent_specific.get(agent_type)


class ModelCatalog:
    """Registry of models loaded from YAML files.

    This class provides a central registry for model definitions, allowing
    agent configs to reference models by name and automatically resolve
    their provider and pricing information. Models are loaded from YAML
    files in the configs/models/ directory.

    Example:
        >>> model = ModelCatalog.get("claude-sonnet-4.5")
        >>> print(model.provider)  # "anthropic"
        >>> print(model.pricing.input)  # 3.0
        >>> settings = model.get_agent_settings("mini_swe")
    """

    _models: ClassVar[dict[str, ModelDefinition]] = {}
    _aliases: ClassVar[dict[str, str]] = {}  # alias -> canonical name
    _provider_slugs: ClassVar[dict[str, str]] = {}  # provider-specific slug -> canonical name
    _loaded: ClassVar[bool] = False

    @classmethod
    def register(
        cls, model: ModelDefinition, config_name: str | None = None
    ) -> None:
        """Register a model definition.

        Args:
            model: The model definition to register
            config_name: The registration name (typically the config filename without
                extension). If not provided, uses model.name if already set,
                falling back to internal_name.
        """
        if config_name is not None:
            model.name = config_name
        elif not model.name:
            # Fallback for manual registration without config_name
            model.name = model.internal_name
        cls._models[model.name] = model
        cls._aliases[model.internal_name] = model.name
        for alias in model.aliases:
            cls._aliases[alias] = model.name
        for slug in model.provider_slugs.values():
            cls._provider_slugs[slug] = model.name

    @classmethod
    def get(cls, name: str) -> ModelDefinition | None:
        """Get model by name, alias, or provider slug.

        Args:
            name: Model name or alias to look up

        Returns:
            ModelDefinition if found, None otherwise
        """
        cls.ensure_loaded()
        canonical = cls._aliases.get(name) or cls._provider_slugs.get(name)
        canonical = canonical or name
        return cls._models.get(canonical)

    @classmethod
    def resolve_canonical(cls, name: str) -> str:
        """Resolve alias or provider slug to canonical name.

        Args:
            name: Model name or alias

        Returns:
            Canonical model name (returns input if not an alias)
        """
        cls.ensure_loaded()
        return cls._aliases.get(name) or cls._provider_slugs.get(name) or name

    @classmethod
    def list_models(cls) -> list[str]:
        """List all registered model names.

        Returns:
            Sorted list of canonical model names
        """
        cls.ensure_loaded()
        return sorted(cls._models.keys())

    @classmethod
    def clear(cls) -> None:
        """Clear all registered models. Useful for testing."""
        cls._models.clear()
        cls._aliases.clear()
        cls._provider_slugs.clear()
        cls._loaded = False

    @classmethod
    def load_from_directory(cls, models_dir: Path) -> None:
        """Load model definitions from YAML files in a directory.

        Args:
            models_dir: Path to directory containing model YAML files

        Raises:
            ValueError: If a model references an unknown provider
        """
        # Import here to avoid circular imports
        from slop_code.agent_runner.credentials import ProviderCatalog

        if not models_dir.exists():
            log.warning("Models directory not found", path=str(models_dir))
            return

        for yaml_file in sorted(models_dir.glob("*.yaml")):
            try:
                data = yaml.safe_load(yaml_file.read_text())
                if data:
                    model = ModelDefinition.model_validate(data)
                    # Use the filename (without extension) as the registered name
                    config_name = yaml_file.stem
                    # Strict validation: fail if provider unknown
                    if ProviderCatalog.get(model.provider) is None:
                        raise ValueError(
                            f"Model config '{config_name}' references unknown provider "
                            f"'{model.provider}'. Add it to configs/providers.yaml"
                        )
                    cls.register(model, config_name=config_name)
            except (yaml.YAMLError, ValidationError, ValueError) as e:
                log.error(
                    "Failed to load model definition",
                    file=yaml_file.name,
                    error=str(e),
                )
                raise

    @classmethod
    def ensure_loaded(cls, models_dir: Path | None = None) -> None:
        """Ensure models are loaded from YAML files (idempotent).

        Args:
            models_dir: Optional path to models directory. If None, uses
                the default configs/models/ relative to project root.
        """
        if cls._loaded:
            return

        if models_dir is None:
            # Default: configs/models/ relative to project root
            models_dir = Path(__file__).parents[3] / "configs" / "models"

        cls.load_from_directory(models_dir)
        cls._loaded = True
