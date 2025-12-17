"""Agent configuration registry helpers."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - avoids circular imports at runtime
    from slop_code.agent_runner.agent import Agent
    from slop_code.agent_runner.agent import AgentConfigBase

_CONFIG_REGISTRY: dict[str, type[AgentConfigBase]] = {}
_AGENT_REGISTRY: dict[str, type[Agent]] = {}


def register_agent_config(
    agent_type: str,
    config_cls: type[AgentConfigBase],
) -> None:
    """Register an AgentConfigBase subclass for the given type name."""
    normalized = agent_type.strip()
    if not normalized:
        raise ValueError("Agent type must be a non-empty string.")

    existing = _CONFIG_REGISTRY.get(normalized)
    if existing is not None and existing is not config_cls:
        raise ValueError(
            f"Agent type '{normalized}' already registered "
            f"by {existing.__qualname__}."
        )
    _CONFIG_REGISTRY[normalized] = config_cls


def get_agent_config_cls(agent_type: str) -> type[AgentConfigBase]:
    """Return the registered config class for ``agent_type``."""
    normalized = agent_type.strip()
    try:
        return _CONFIG_REGISTRY[normalized]
    except KeyError as exc:
        available = ", ".join(sorted(_CONFIG_REGISTRY))
        raise KeyError(
            f"Unknown agent type '{agent_type}'. "
            f"Known types: {available or 'none'}."
        ) from exc


def available_agent_types() -> tuple[str, ...]:
    """List the currently registered agent type names."""
    return tuple(sorted(_CONFIG_REGISTRY))


def iter_agent_config_types() -> Iterable[type[AgentConfigBase]]:
    """Iterate over registered agent configuration classes."""
    # Return a copy to avoid accidental mutation by callers.
    return tuple(_CONFIG_REGISTRY.values())


def build_agent_config(data: dict[str, Any]) -> AgentConfigBase:
    """Instantiate the proper AgentConfigBase subclass for ``data``."""
    if "type" not in data:
        available = ", ".join(sorted(_CONFIG_REGISTRY))
        raise ValueError(
            f"Agent configuration missing 'type'. "
            f"Known types: {available or 'none'}."
        )

    try:
        config_cls = get_agent_config_cls(str(data["type"]))
    except KeyError as exc:
        message = exc.args[0] if exc.args else str(exc)
        raise ValueError(message) from exc
    return config_cls.model_validate(data)


def register_agent(
    agent_type: str,
    agent_cls: type[Agent],
) -> None:
    """Register an Agent subclass for the given type name."""
    normalized = agent_type.strip()
    if not normalized:
        raise ValueError("Agent type must be a non-empty string.")

    existing = _AGENT_REGISTRY.get(normalized)
    if existing is not None and existing is not agent_cls:
        raise ValueError(
            f"Agent type '{normalized}' already registered "
            f"by {existing.__qualname__}."
        )
    _AGENT_REGISTRY[normalized] = agent_cls


def get_agent_cls(agent_type: str) -> type[Agent]:
    """Return the registered agent class for ``agent_type``."""
    normalized = agent_type.strip()
    try:
        return _AGENT_REGISTRY[normalized]
    except KeyError as exc:
        available = ", ".join(sorted(_AGENT_REGISTRY))
        raise KeyError(
            f"Unknown agent type '{agent_type}'. "
            f"Known types: {available or 'none'}."
        ) from exc
