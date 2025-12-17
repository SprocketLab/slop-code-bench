"""Custom OmegaConf resolvers for run configuration interpolation."""

from __future__ import annotations

from datetime import datetime

from omegaconf import OmegaConf

_RESOLVERS_REGISTERED = False


def register_resolvers() -> None:
    """Register custom OmegaConf resolvers for interpolation.

    This function is idempotent - calling it multiple times has no effect
    after the first call.

    Registered resolvers:
        - ${now:FORMAT}: Current timestamp with strftime format
          Example: ${now:%Y%m%dT%H%M} -> "20250610T1430"
          Default format: %Y%m%dT%H%M

    Note: The following variables are resolved via standard OmegaConf
    interpolation after the config is assembled:
        - ${model.name}, ${model.provider}: From model config
        - ${agent.type}: From resolved agent config
        - ${prompt}: Set to prompt file stem during resolution
        - ${thinking}: Set to thinking preset string during resolution
        - ${env.name}: From resolved environment config
    """
    global _RESOLVERS_REGISTERED
    if _RESOLVERS_REGISTERED:
        return

    # ${now:FORMAT} -> timestamp with strftime format
    # Usage: ${now:%Y%m%dT%H%M} or ${now:} for default format
    OmegaConf.register_new_resolver(
        "now",
        lambda fmt="%Y%m%dT%H%M": datetime.now().strftime(fmt),
        replace=True,
    )

    _RESOLVERS_REGISTERED = True


def reset_resolvers() -> None:
    """Reset resolver registration state (for testing only)."""
    global _RESOLVERS_REGISTERED
    _RESOLVERS_REGISTERED = False
