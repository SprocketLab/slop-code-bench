"""Shared graph utilities."""

from __future__ import annotations

from typing import Any

# -----------------------------------------------------------------------------
# Theme System
# -----------------------------------------------------------------------------

FONT_FAMILY_IMPACT = "Space Grotesk, Inter, sans-serif"
FONT_FAMILY_DEFAULT = "Inter, Roboto, Arial, sans-serif"

# Dark theme - GitHub dark inspired, high visual impact
DARK_THEME = {
    "plot_bgcolor": "#0d1117",
    "paper_bgcolor": "#0d1117",
    "font_color": "#c9d1d9",
    "gridcolor": "#30363d",
    "axis_color": "#8b949e",
    "title_color": "#f0f6fc",
    "legend_bg": "rgba(22,27,34,0.9)",
}

# Light theme - subtle off-white, professional
LIGHT_THEME = {
    "plot_bgcolor": "#f8f9fa",
    "paper_bgcolor": "#ffffff",
    "font_color": "#1f2328",
    "gridcolor": "#d0d7de",
    "axis_color": "#57606a",
    "title_color": "#1f2328",
    "legend_bg": "rgba(255,255,255,0.95)",
}

# Erosion severity colors
EROSION_COLORS = {
    "healthy": "#2e8540",
    "moderate": "#ffc107",
    "warning": "#fd7e14",
    "critical": "#dc3545",
}


def get_theme(theme: str) -> dict[str, Any]:
    """Get theme configuration by name."""
    themes = {
        "dark": DARK_THEME,
        "light": LIGHT_THEME,
    }
    return themes.get(theme, LIGHT_THEME)


def get_theme_layout(
    theme: str,
    fig_width: int,
    fig_height: int,
    legend_y: float,
    title: str | None = None,
    subtitle: str | None = None,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Get base layout with theme-specific styling.

    Args:
        theme: Theme name ("dark" or "light").
        fig_width: Figure width in pixels.
        fig_height: Figure height in pixels.
        legend_y: Y position for legend.
        title: Optional main title.
        subtitle: Optional subtitle (displayed smaller, below title).

    Returns:
        Layout configuration dict for Plotly.
    """
    t = get_theme(theme)
    font_family = FONT_FAMILY_IMPACT

    # Build title text with optional subtitle
    title_text = None
    if title:
        title_text = f"<b>{title}</b>"
        if subtitle:
            title_text += f"<br><span style='font-size:16px;color:{t['axis_color']}'>{subtitle}</span>"

    base = {
        "title": (
            {
                "text": title_text,
                "font": {
                    "family": font_family,
                    "size": 32,
                    "color": t["title_color"],
                },
                "x": 0.5,
                "y": 0.95,
                "xanchor": "center",
                "yanchor": "top",
            }
            if title_text
            else None
        ),
        "plot_bgcolor": t["plot_bgcolor"],
        "paper_bgcolor": t["paper_bgcolor"],
        "font": {"family": font_family, "size": 15, "color": t["font_color"]},
        "legend": {
            "orientation": "h",
            "yanchor": "bottom",
            "y": legend_y,
            "xanchor": "center",
            "x": 0.5,
            "font": {
                "size": 14,
                "family": font_family,
                "color": t["font_color"],
            },
            "bgcolor": t["legend_bg"],
            "borderwidth": 0,
        },
        "xaxis": {
            "gridcolor": t["gridcolor"],
            "linecolor": t["axis_color"],
            "tickfont": {"color": t["axis_color"]},
            "title_font": {"color": t["font_color"]},
        },
        "yaxis": {
            "gridcolor": t["gridcolor"],
            "linecolor": t["axis_color"],
            "tickfont": {"color": t["axis_color"]},
            "title_font": {"color": t["font_color"]},
        },
        "width": fig_width,
        "height": fig_height,
        "autosize": False,
        "hovermode": "closest",
        "modebar": {"remove": ["zoom", "lasso2d", "select2d"]},
    }
    return nested_priority_merge(base, overrides or {})
