"""Shared constants for visualization: colors, dimensions, display names."""

from __future__ import annotations

# -----------------------------------------------------------------------------
# Provider Colors
# -----------------------------------------------------------------------------

PROVIDER_BASE_COLORS = {
    "anthropic": "#DE7356",
    "openai": "#C4A35A",
    "zhipu": "#475DC3",
}

PROVIDER_GRADS = {
    "anthropic": ["#DE7356", "#a8543d"],
    "openai": ["#02ad99", "#15cfb8", "#017e6f"],
    "zhipu": ["#475DC3", "#3347a3"],
}

# -----------------------------------------------------------------------------
# Version Colors (Claude Code agent versions)
# -----------------------------------------------------------------------------

VERSION_COLORS = {
    "2.0.51": "#7eb0d5",  # Light blue (oldest)
    "2.0.62": "#b2e061",  # Green (middle)
    "2.0.75": "#fd7f6f",  # Coral (newest)
}

# -----------------------------------------------------------------------------
# Model Colors and Display Names
# -----------------------------------------------------------------------------

MODEL_COLORS = {
    # Anthropic (coral)
    "opus-4.5": "#DE7356",
    # OpenAI (teal-green shades, more distinct)
    "gpt-5.1-codex-max": "#48d1cc",  # Medium turquoise (light)
    "gpt-5.2": "#008b8b",  # Dark cyan (medium)
    "gpt-5.2-codex": "#004d4d",  # Deep teal (dark)
    # Zhipu (blue)
    "glm-4.7": "#475DC3",
}

MODEL_DISPLAY_NAMES = {
    "opus-4.5": "Opus 4.5",
    "gpt-5.1-codex-max": "GPT-5.1 Codex Max",
    "gpt-5.2": "GPT-5.2",
    "gpt-5.2-codex": "GPT-5.2 Codex",
    "glm-4.7": "GLM-4.7",
}

# -----------------------------------------------------------------------------
# Standard Dimensions
# -----------------------------------------------------------------------------

GRAPH_WIDTH = 900
GRAPH_HEIGHT = 500
SUBPLOT_WIDTH = 1100
SUBPLOT_HEIGHT = 450
