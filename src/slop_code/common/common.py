from typing import Any

_SENSITIVE_ENV_MARKERS = (
    "token",
    "secret",
    "key",
    "password",
    "credential",
    "OPENROUTER_API_KEY",
    "ANTHROPIC_API_KEY",
    "authorization",
)


def mask_sensitive_values(values: dict[str, str]) -> dict[str, str]:
    """Hide sensitive values before logging."""
    masked: dict[str, str] = {}
    for key, value in values.items():
        if any(marker in key.lower() for marker in _SENSITIVE_ENV_MARKERS):
            masked[key] = "***redacted***"
        else:
            masked[key] = value
    return masked


def deep_merge(
    base: dict[str, Any], override: dict[str, Any]
) -> dict[str, Any]:
    """Deep merge two dictionaries, with override values taking precedence.

    For nested dicts, recursively merge. For all other types (including lists),
    override completely replaces base.

    Args:
        base: Base dictionary (e.g., from model catalog)
        override: Override dictionary (e.g., from agent YAML config)

    Returns:
        New merged dictionary with override values taking precedence
    """
    result = base.copy()
    for key, override_value in override.items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(override_value, dict)
        ):
            result[key] = _deep_merge(result[key], override_value)
        else:
            result[key] = override_value
    return result
