from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from slop_code.dashboard.data import PROVIDER_BASE_COLORS
from slop_code.dashboard.data import ModelVariationInfo
from slop_code.dashboard.data import _detect_provider
from slop_code.dashboard.data import _hsl_to_hex
from slop_code.dashboard.data import get_dynamic_variant_annotation

# Grouped vertical legend configuration (shared by multiplot charts)
GROUPED_VERTICAL_LEGEND: dict[str, Any] = {
    "orientation": "v",
    "yanchor": "top",
    "y": 1,
    "xanchor": "left",
    "x": 1.02,
    "groupclick": "togglegroup",
    "tracegroupgap": 10,
    "font": {"size": 12, "family": "Inter, Arial, sans-serif"},
    "bgcolor": "rgba(255,255,255,0.9)",
    "borderwidth": 0,
}


def get_base_layout(
    fig_width: int | None,
    fig_height: int | None,
    legend_y: float,
    title: str | None = None,
) -> dict[str, Any]:
    """Get standard layout configuration for figures."""
    layout = {
        "title": (
            {
                "text": title,
                "font": {
                    "family": "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif",
                    "size": 24,
                    "color": "#333",
                },
                "x": 0.0,  # Left align title
                "y": 0.98,
                "xanchor": "left",
                "yanchor": "top",
            }
            if title
            else None
        ),
        "plot_bgcolor": "#ffffff",
        "paper_bgcolor": "#ffffff",
        "font": {
            "family": "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif",
            "size": 13,
            "color": "#444",
        },
        "legend": {
            "orientation": "h",
            "yanchor": "bottom",
            "y": legend_y,
            "xanchor": "center",
            "x": 0.5,
            "font": {"size": 12},
            "bgcolor": "rgba(255,255,255,0.8)",
            "borderwidth": 0,
        },
        "margin": {"l": 60, "r": 40, "t": 80 if title else 40, "b": 60},
        "hovermode": "closest",
        "modebar": {"remove": ["zoom", "lasso2d", "select2d"]},
    }
    if fig_width:
        layout["width"] = fig_width
    if fig_height:
        layout["height"] = fig_height
    else:
        layout["autosize"] = True
    return layout


@dataclass
class LegendGroupInfo:
    model_name: str
    variant: str
    color: str
    group_title: str | None
    model_base_color: str


class LegendGroupTracker:
    def __init__(
        self,
        color_map: dict[str, str],
        variation_info: dict[str, ModelVariationInfo] | None = None,
    ):
        self._seen: set[str] = set()
        self._color_map = color_map
        self._variation_info = variation_info or {}

    def get_info(
        self,
        display_name: str,
        row: pd.Series | dict[str, Any],
    ) -> LegendGroupInfo:
        model_name = row["model_name"]
        model_variation = self._variation_info.get(model_name)
        variant = get_dynamic_variant_annotation(
            row, model_variation, use_html=True
        )
        color = self._color_map.get(display_name, "#888")

        provider = _detect_provider(model_name)
        base_hsl = PROVIDER_BASE_COLORS.get(
            provider, PROVIDER_BASE_COLORS["other"]
        )
        model_base_color = _hsl_to_hex(*base_hsl)

        group_title = None
        if model_name not in self._seen:
            self._seen.add(model_name)
            group_title = f"<b>{model_name}</b>"

        return LegendGroupInfo(
            model_name=model_name,
            variant=variant,
            color=color,
            group_title=group_title,
            model_base_color=model_base_color,
        )
