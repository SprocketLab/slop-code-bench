"""Shared graph utilities."""

from __future__ import annotations

import colorsys
import json
import math
import re
from collections import defaultdict
from dataclasses import dataclass
from itertools import cycle
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.colors
import plotly.graph_objects as go
import typer
import yaml

from slop_code.common import CHECKPOINT_RESULTS_FILENAME
from slop_code.common import SUMMARY_FILENAME

# Constants
MODEL_TO_READABLE = {
    "opus-4.5": "Opus 4.5",
    "sonnet-4.5": "Sonnet 4.5",
    "gpt-5.1-codex-max": "GPT 5.1 Codex",
    "gpt-5.2": "GPT 5.2",
    "kimi-k2-thinking": "Kimi K2",
    "moonshotai/kimi-k2-thinking": "Kimi K2",
}

DEFAULT_COLOR_PALETTE = plotly.colors.qualitative.Vivid

GROUPED_VERTICAL_LEGEND = {
    "orientation": "v",
    "yanchor": "top",
    "y": 1,
    "xanchor": "left",
    "x": 1.02,
    "groupclick": "togglegroup",
    "tracegroupgap": 20,
    "font": {"size": 13, "family": "Inter, Roboto, Arial, sans-serif"},
    "bgcolor": "rgba(255,255,255,0.9)",
    "borderwidth": 0,
}

LEGEND_VERTICAL_PADDING_PX = 40
LEGEND_MIN_RIGHT_MARGIN = 200
INDIVIDUAL_CHART_WIDTH = 800
INDIVIDUAL_CHART_HEIGHT = 500


@dataclass
class ModelVariationInfo:
    thinking_varies: bool
    prompt_varies: bool


@dataclass(frozen=True)
class LayoutConfig:
    max_cols: int
    tile_width: int
    tile_height: int
    single_width: int
    single_height: int


@dataclass
class ChartContext:
    checkpoints: pd.DataFrame
    run_summaries: pd.DataFrame
    color_map: dict[str, str]
    base_color_map: dict[str, str]
    layout: LayoutConfig


@dataclass
class LegendGroupInfo:
    model_name: str
    variant: str
    color: str
    group_title: str | None
    model_base_color: str


# Helpers
def hsl_to_hex(h: int, s: int, l: int) -> str:
    s = s / 100
    l = l / 100
    c = (1 - abs(2 * l - 1)) * s
    x = c * (1 - abs((h / 60) % 2 - 1))
    m = l - c / 2
    if h < 60:
        r, g, b = c, x, 0
    elif h < 120:
        r, g, b = x, c, 0
    elif h < 180:
        r, g, b = 0, c, x
    elif h < 240:
        r, g, b = 0, x, c
    elif h < 300:
        r, g, b = x, 0, c
    else:
        r, g, b = c, 0, x
    r, g, b = int((r + m) * 255), int((g + m) * 255), int((b + m) * 255)
    return f"#{r:02x}{g:02x}{b:02x}"


def format_prompt_display(prompt_template: str) -> str:
    prompt_stem = Path(prompt_template).stem if prompt_template else ""
    if not prompt_stem:
        return "Default"
    words = re.split(r"[_-]", prompt_stem)
    return "".join(word.title() for word in words)


def is_thinking_enabled(row: pd.Series | dict[str, Any]) -> tuple[bool, str]:
    thinking = str(row.get("thinking", "")).lower()
    enabled = bool(
        thinking and thinking not in ("none", "disabled", "unknown", "null")
    )
    return enabled, thinking.title() if enabled else ""


def thinking_rank(value: Any) -> int:
    text = str(value or "").strip().lower()
    if text in ("", "none", "disabled", "off", "false", "0", "null", "unknown"):
        return 0
    if text == "low":
        return 1
    if text in ("med", "medium"):
        return 2
    if text == "high":
        return 3
    return 99


def normalize_thinking_level(value: Any) -> str:
    """Normalize thinking level strings into a small, known set."""
    text = str(value or "").strip().lower()
    if text in ("", "none", "disabled", "off", "false", "0", "null", "unknown"):
        return "none"
    if text == "low":
        return "low"
    if text in ("med", "medium"):
        return "medium"
    if text == "high":
        return "high"
    return "other"


def sorted_display_names(df: pd.DataFrame) -> list[str]:
    if df.empty or "display_name" not in df.columns:
        return []
    rows = []
    for display_name, group in df.groupby("display_name", sort=False):
        row = group.iloc[0]
        model_name = str(row.get("model_name", ""))
        prompt = str(row.get("prompt_template", ""))
        rows.append(
            (
                model_name,
                thinking_rank(row.get("thinking")),
                prompt,
                display_name,
            )
        )
    rows.sort()
    return [display_name for _, __, ___, display_name in rows]


def parse_to_hsl_tuple(color: str) -> tuple[int, int, int]:
    # Handle rgb(r, g, b)
    if color.startswith("rgb"):
        parts = re.findall(r"\d+", color)
        if len(parts) >= 3:
            r, g, b = map(int, parts[:3])
            h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
            return int(h * 360), int(s * 100), int(l * 100)

    hex_color = color.lstrip("#")
    if len(hex_color) == 3:
        hex_color = "".join(c * 2 for c in hex_color)
    r, g, b = (
        int(hex_color[0:2], 16),
        int(hex_color[2:4], 16),
        int(hex_color[4:6], 16),
    )
    h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    return int(h * 360), int(s * 100), int(l * 100)


def generate_variant_colors(base_color: str, count: int) -> list[str]:
    if count == 0:
        return []
    if count == 1:
        # Ensure output is always hex
        h, s, l = parse_to_hsl_tuple(base_color)
        return [hsl_to_hex(h, s, l)]

    h, s, _ = parse_to_hsl_tuple(base_color)
    light_start, light_end = 75, 35
    step = (light_start - light_end) / (count - 1)
    return [hsl_to_hex(h, s, int(light_start - i * step)) for i in range(count)]


# Thinking level lightness values (None=lightest, High=darkest)
THINKING_LIGHTNESS = {
    "none": 75,
    "low": 60,
    "medium": 45,
    "high": 30,
    "other": 50,
}


def get_thinking_adjusted_color(
    base_hsl: tuple[int, int, int],
    thinking_level: str,
) -> str:
    """Apply thinking-level lightness modifier to a base color.

    Args:
        base_hsl: Base color as (hue, saturation, lightness).
        thinking_level: Normalized thinking level string.

    Returns:
        Hex color string with thinking-adjusted lightness.
    """
    h, s, _ = base_hsl
    lightness = THINKING_LIGHTNESS.get(thinking_level, 50)
    return hsl_to_hex(h, s, lightness)


def get_readable_model(model_id: str) -> str:
    return MODEL_TO_READABLE.get(model_id, model_id)


def get_display_annotation(row: pd.Series | dict[str, Any]) -> str:
    model_name = row["model_name"]
    prompt_template = str(row.get("prompt_template", ""))
    thinking_enabled, thinking_display = is_thinking_enabled(row)
    prompt_display = format_prompt_display(prompt_template)
    annotation = model_name
    if thinking_enabled:
        annotation = f"{annotation} {thinking_display}"
    # Only add prompt suffix if it's meaningful (not "Unknown" or "Default")
    if prompt_display not in ("Unknown", "Default", ""):
        annotation = f"{annotation} ({prompt_display})"
    return annotation


def get_short_annotation(row: pd.Series | dict[str, Any]) -> str:
    prompt_template = str(row.get("prompt_template", ""))
    thinking_enabled, thinking_display = is_thinking_enabled(row)
    prompt_display = format_prompt_display(prompt_template)
    if thinking_enabled:
        return f"{prompt_display} - {thinking_display}"
    return prompt_display


def get_variant_annotation(row: pd.Series | dict[str, Any]) -> str:
    prompt_template = str(row.get("prompt_template", ""))
    thinking_enabled, thinking_display = is_thinking_enabled(row)
    prompt_display = format_prompt_display(prompt_template)
    if thinking_enabled:
        return f"{thinking_display} - {prompt_display}"
    return prompt_display


def analyze_model_variations(df: pd.DataFrame) -> dict[str, ModelVariationInfo]:
    model_variants = defaultdict(set)
    for _, row in df.iterrows():
        model_name = row["model_name"]
        thinking = str(row.get("thinking", "")).lower()
        prompt = str(row.get("prompt_template", ""))
        model_variants[model_name].add((thinking, prompt))
    result = {}
    for model_name, variants in model_variants.items():
        thinkings = {t for t, _ in variants}
        prompts = {p for _, p in variants}
        result[model_name] = ModelVariationInfo(
            thinking_varies=len(thinkings) > 1,
            prompt_varies=len(prompts) > 1,
        )
    return result


def get_dynamic_variant_annotation(
    row: pd.Series | dict[str, Any], variation_info: ModelVariationInfo | None
) -> str:
    thinking_enabled, thinking_display = is_thinking_enabled(row)
    prompt_display = format_prompt_display(str(row.get("prompt_template", "")))
    if variation_info is None:
        if thinking_enabled:
            return f"{thinking_display} - {prompt_display}"
        return prompt_display
    parts = []
    if variation_info.thinking_varies:
        parts.append(thinking_display if thinking_enabled else "No Thinking")
    if variation_info.prompt_varies:
        parts.append(prompt_display)
    if not parts:
        return "Base"
    return " - ".join(parts)


def process_checkpoint_row(row: dict[str, Any]) -> dict[str, Any]:
    duration = row.get("duration")
    if duration is None:
        duration = row.get("elapsed")
    processed = dict(row)
    if "idx" not in processed or processed["idx"] is None:
        chkpt_name = str(processed.get("checkpoint", ""))
        match = re.search(r"checkpoint_(\d+)", chkpt_name)
        processed["idx"] = int(match.group(1)) if match else 999
    if "pass_rate" in row or "checkpoint_pass_rate" in row:
        processed["passed_chkpt"] = math.isclose(row["pass_rate"], 1.0)
    elif "total_tests" in row or "passed_tests" in row:
        tests_total = row.get("total_tests")
        tests_passed = row.get("passed_tests")
        processed["passed_chkpt"] = (
            tests_total == tests_passed
            if tests_total is not None and tests_total > 0
            else None
        )
    else:
        processed["passed_chkpt"] = None
    if duration is not None:
        processed["duration"] = duration
    return processed


def flatten_summary(
    summary: dict[str, Any], prefix: str = ""
) -> dict[str, Any]:
    flattened = {}
    for key, value in summary.items():
        full_key = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            flattened.update(flatten_summary(value, full_key))
        else:
            flattened[full_key] = value
    return flattened


def load_result_summary(run_dir: Path) -> dict[str, Any] | None:
    summary_file = run_dir / SUMMARY_FILENAME
    if not summary_file.exists():
        typer.echo(
            typer.style(
                f"Summary file not found at {summary_file}", fg=typer.colors.RED
            )
        )
        return None
    try:
        return json.loads(summary_file.read_text())
    except json.JSONDecodeError as exc:
        typer.echo(
            typer.style(
                f"Failed to parse {summary_file}: {exc}", fg=typer.colors.RED
            )
        )
        return None


def load_config_metadata(run_dir: Path) -> dict[str, str]:
    config_file = run_dir / "config.yaml"
    with config_file.open() as f:
        config = yaml.unsafe_load(f)
    agent_cfg = config.get("agent", {})

    # Handle model name location variance
    if (
        "model" in config
        and isinstance(config["model"], dict)
        and "name" in config["model"]
    ):
        model = config["model"]["name"]
    elif "model" in agent_cfg:
        model = agent_cfg["model"]
    else:
        model = "unknown"

    # Handle thinking location variance
    thinking = config.get("thinking")
    if thinking is None:
        thinking = agent_cfg.get("thinking", "none")

    return {
        "agent_type": agent_cfg.get("type", "unknown"),
        "model_name": get_readable_model(model),
        "thinking": str(thinking),
        "prompt_template": str(config.get("prompt_template", "unknown")),
    }


def load_run(run_dir: Path) -> tuple[pd.DataFrame, dict[str, Any] | None]:
    results_path = run_dir / CHECKPOINT_RESULTS_FILENAME
    metadata = {
        **load_config_metadata(run_dir),
        "run_name": run_dir.name,
        "run_path": str(run_dir),
    }
    checkpoints = []
    with results_path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            raw_row = json.loads(line)
            checkpoints.append({**metadata, **process_checkpoint_row(raw_row)})
    summary_data = load_result_summary(run_dir)
    summary_row = None
    if summary_data:
        summary_row = {**metadata, **flatten_summary(summary_data)}
    return pd.DataFrame(checkpoints), summary_row


def build_base_color_map(
    display_names: list[str],
    model_groups: dict[str, str],
    group_colors: dict[str, str],
) -> dict[str, str]:
    color_map = {}
    for name in display_names:
        group = model_groups.get(name, name)
        base_color = group_colors.get(group, "#333333")
        # Ensure consistency by converting to hex
        h, s, l = parse_to_hsl_tuple(base_color)
        color_map[name] = hsl_to_hex(h, s, l)
    return color_map


def build_color_map(
    display_names: list[str],
    model_groups: dict[str, str],
    group_colors: dict[str, str],
) -> dict[str, str]:
    grouped_names = defaultdict(list)
    for name in display_names:
        group = model_groups.get(name, name)
        grouped_names[group].append(name)

    for group in grouped_names:
        grouped_names[group].sort()

    color_map = {}
    for group, names in grouped_names.items():
        base_hex = group_colors.get(group, "#333333")
        colors = generate_variant_colors(base_hex, len(names))
        for name, color in zip(names, colors):
            color_map[name] = color
    return color_map


def build_chart_context(runs: list[Path], layout: LayoutConfig) -> ChartContext:
    checkpoint_frames, summary_rows = [], []
    for run_dir in runs:
        checkpoints, summary_row = load_run(run_dir)
        if not checkpoints.empty:
            checkpoint_frames.append(checkpoints)
        if summary_row:
            summary_rows.append(summary_row)
    checkpoints_df = (
        pd.concat(checkpoint_frames, ignore_index=True)
        if checkpoint_frames
        else pd.DataFrame()
    )
    run_summaries = pd.DataFrame(summary_rows)
    if not checkpoints_df.empty:
        checkpoints_df["display_name"] = checkpoints_df.apply(
            get_display_annotation, axis=1
        )
    if not run_summaries.empty:
        run_summaries["display_name"] = run_summaries.apply(
            get_display_annotation, axis=1
        )
    display_names = []
    model_groups = {}

    if not checkpoints_df.empty:
        display_names.extend(checkpoints_df["display_name"].unique().tolist())
        model_groups.update(
            dict(
                zip(
                    checkpoints_df["display_name"], checkpoints_df["model_name"]
                )
            )
        )

    if not run_summaries.empty:
        summary_names = run_summaries["display_name"].unique().tolist()
        display_names.extend(
            [n for n in summary_names if n not in display_names]
        )
        model_groups.update(
            dict(
                zip(run_summaries["display_name"], run_summaries["model_name"])
            )
        )

    sorted_names = sorted(set(filter(None, display_names)))

    unique_groups = sorted(list(set(model_groups.values())))
    palette = cycle(DEFAULT_COLOR_PALETTE)
    group_colors = {group: next(palette) for group in unique_groups}

    color_map = build_color_map(sorted_names, model_groups, group_colors)
    base_color_map = build_base_color_map(
        sorted_names, model_groups, group_colors
    )

    return ChartContext(
        checkpoints=checkpoints_df,
        run_summaries=run_summaries,
        color_map=color_map,
        base_color_map=base_color_map,
        layout=layout,
    )


def get_base_layout(
    fig_width: int, fig_height: int, legend_y: float, title: str | None = None
) -> dict[str, Any]:
    font_family = "Inter, Roboto, Arial, sans-serif"
    return {
        "title": (
            {
                "text": title,
                "font": {"family": font_family, "size": 28, "color": "#111"},
                "x": 0.5,
                "y": 1.0,
                "xanchor": "center",
                "yanchor": "top",
            }
            if title
            else None
        ),
        "plot_bgcolor": "#fff",
        "paper_bgcolor": "#fff",
        "font": {"family": font_family, "size": 15, "color": "#222"},
        "legend": {
            "orientation": "h",
            "yanchor": "bottom",
            "y": legend_y,
            "xanchor": "center",
            "x": 0.5,
            "font": {"size": 14, "family": font_family},
            "bgcolor": "rgba(255,255,255,0)",
            "borderwidth": 0,
        },
        "width": fig_width,
        "height": fig_height,
        "autosize": False,
        "hovermode": "closest",
        "modebar": {"remove": ["zoom", "lasso2d", "select2d"]},
    }


def estimate_vertical_legend_height(fig: go.Figure) -> int:
    legend_traces = [
        trace for trace in fig.data if getattr(trace, "showlegend", False)
    ]
    if not legend_traces:
        return 0
    font_size = GROUPED_VERTICAL_LEGEND.get("font", {}).get("size") or 13
    line_height = int(font_size * 1.4)
    legend_groups = {
        getattr(trace, "legendgroup", None)
        for trace in legend_traces
        if getattr(trace, "legendgroup", None)
    }
    gap_per_group = GROUPED_VERTICAL_LEGEND.get("tracegroupgap", 0) or 0
    group_gap_total = max(len(legend_groups) - 1, 0) * gap_per_group
    return len(legend_traces) * line_height + group_gap_total


def apply_grouped_vertical_legend(fig: go.Figure, base_height: int) -> None:
    fig.update_layout(legend=GROUPED_VERTICAL_LEGEND)
    legend_height = estimate_vertical_legend_height(fig)
    if legend_height == 0:
        return
    margin = fig.layout.margin
    top = 60 if margin is None or margin.t is None else int(margin.t)
    bottom = 60 if margin is None or margin.b is None else int(margin.b)
    left = 60 if margin is None or margin.l is None else int(margin.l)
    right_base = (
        LEGEND_MIN_RIGHT_MARGIN
        if margin is None or margin.r is None
        else int(margin.r)
    )
    right = max(right_base, LEGEND_MIN_RIGHT_MARGIN)
    current_height = fig.layout.height or base_height
    required_height = legend_height + top + bottom + LEGEND_VERTICAL_PADDING_PX
    fig.update_layout(
        height=max(current_height, required_height),
        margin={"t": top, "b": bottom, "l": left, "r": right},
    )


class LegendGroupTracker:
    def __init__(
        self,
        color_map: dict[str, str],
        base_color_map: dict[str, str],
        variation_info: dict[str, ModelVariationInfo] | None = None,
    ):
        self._seen = set()
        self._color_map = color_map
        self._base_color_map = base_color_map
        self._variation_info = variation_info or {}

    def get_info(
        self, display_name: str, row: pd.Series | dict[str, Any]
    ) -> LegendGroupInfo:
        model_name = row["model_name"]
        model_variation = self._variation_info.get(model_name)
        variant = get_dynamic_variant_annotation(row, model_variation)

        color = self._color_map.get(display_name, "#333333")
        model_base_color = self._base_color_map.get(display_name, color)

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


def grid_for_panels(
    panel_count: int, max_cols: int
) -> tuple[int, int, list[tuple[int, int]]]:
    if panel_count <= 0:
        return 0, 0, []
    cols = max(1, min(max_cols, panel_count))
    rows = math.ceil(panel_count / cols)
    positions = [(i // cols + 1, i % cols + 1) for i in range(panel_count)]
    return rows, cols, positions


def format_na(
    values: pd.Series, fmt: str
) -> tuple[list[float | None], list[str]]:
    numeric = pd.to_numeric(values, errors="coerce")
    y = [None if pd.isna(v) else float(v) for v in numeric]
    text = [("N/A" if pd.isna(v) else format(float(v), fmt)) for v in numeric]
    return y, text


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

    return {
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


# -----------------------------------------------------------------------------
# Visual Enhancement Helpers
# -----------------------------------------------------------------------------


def add_trend_line(
    fig: go.Figure,
    x_data: list[float],
    y_data: list[float],
    color: str = "#ff6b6b",
    show_confidence: bool = True,
    confidence_level: float = 0.95,
    row: int | None = None,
    col: int | None = None,
) -> float | None:
    """Add regression line with R² annotation and optional confidence band.

    Args:
        fig: Plotly figure to add to.
        x_data: X values.
        y_data: Y values.
        color: Line color.
        show_confidence: Whether to show confidence band.
        confidence_level: Confidence level for band (0-1).
        row: Subplot row (1-indexed) for subplots.
        col: Subplot column (1-indexed) for subplots.

    Returns:
        R² value, or None if insufficient data.
    """
    import numpy as np

    x = np.array(x_data)
    y = np.array(y_data)

    # Filter out NaN/inf values
    mask = np.isfinite(x) & np.isfinite(y)
    x, y = x[mask], y[mask]

    if len(x) < 3:
        return None

    # Linear regression
    coeffs = np.polyfit(x, y, 1)
    poly = np.poly1d(coeffs)

    # R² calculation
    y_pred = poly(x)
    ss_res = np.sum((y - y_pred) ** 2)
    ss_tot = np.sum((y - np.mean(y)) ** 2)
    r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0

    # Generate smooth line
    x_line = np.linspace(x.min(), x.max(), 100)
    y_line = poly(x_line)

    # Add trend line
    trace_kwargs = {
        "x": x_line.tolist(),
        "y": y_line.tolist(),
        "mode": "lines",
        "line": {"color": color, "width": 3, "dash": "solid"},
        "name": f"Trend (r²={r_squared:.2f})",
        "showlegend": True,
        "hoverinfo": "skip",
    }

    if row is not None and col is not None:
        fig.add_trace(go.Scatter(**trace_kwargs), row=row, col=col)
    else:
        fig.add_trace(go.Scatter(**trace_kwargs))

    # Add confidence band
    if show_confidence and len(x) > 3:
        # Standard error of estimate
        n = len(x)
        se = np.sqrt(ss_res / (n - 2)) if n > 2 else 0

        # Confidence interval (simplified)
        from scipy import stats

        t_val = stats.t.ppf((1 + confidence_level) / 2, n - 2)
        x_mean = np.mean(x)
        x_var = np.sum((x - x_mean) ** 2)

        # Prediction interval
        margin = (
            t_val * se * np.sqrt(1 + 1 / n + (x_line - x_mean) ** 2 / x_var)
        )
        y_upper = y_line + margin
        y_lower = y_line - margin

        band_kwargs = {
            "x": np.concatenate([x_line, x_line[::-1]]).tolist(),
            "y": np.concatenate([y_upper, y_lower[::-1]]).tolist(),
            "fill": "toself",
            "fillcolor": color.replace(")", ",0.15)").replace("rgb", "rgba")
            if "rgb" in color
            else f"rgba({int(color[1:3], 16)},{int(color[3:5], 16)},{int(color[5:7], 16)},0.15)",
            "line": {"color": "rgba(0,0,0,0)"},
            "showlegend": False,
            "hoverinfo": "skip",
        }

        if row is not None and col is not None:
            fig.add_trace(go.Scatter(**band_kwargs), row=row, col=col)
        else:
            fig.add_trace(go.Scatter(**band_kwargs))

    return r_squared


def add_quadrant_zones(
    fig: go.Figure,
    x_threshold: float,
    y_threshold: float,
    x_range: tuple[float, float],
    y_range: tuple[float, float],
    labels: dict[str, str] | None = None,
    colors: dict[str, str] | None = None,
) -> None:
    """Add shaded quadrant zones with optional labels.

    Args:
        fig: Plotly figure to add to.
        x_threshold: X value dividing left/right quadrants.
        y_threshold: Y value dividing top/bottom quadrants.
        x_range: (min, max) for x axis.
        y_range: (min, max) for y axis.
        labels: Dict with keys "top_left", "top_right", "bottom_left", "bottom_right".
        colors: Dict with same keys for zone colors.
    """
    default_colors = {
        "top_left": "rgba(220, 53, 69, 0.08)",  # Red - low quality, high solve (rare)
        "top_right": "rgba(46, 133, 64, 0.08)",  # Green - sweet spot
        "bottom_left": "rgba(253, 126, 20, 0.08)",  # Orange - danger zone
        "bottom_right": "rgba(255, 193, 7, 0.08)",  # Yellow - efficient but low solve
    }
    colors = colors or default_colors

    default_labels = {
        "top_left": "",
        "top_right": "SWEET SPOT",
        "bottom_left": "DANGER ZONE",
        "bottom_right": "",
    }
    labels = labels or default_labels

    zones = [
        ("top_left", x_range[0], x_threshold, y_threshold, y_range[1]),
        ("top_right", x_threshold, x_range[1], y_threshold, y_range[1]),
        ("bottom_left", x_range[0], x_threshold, y_range[0], y_threshold),
        ("bottom_right", x_threshold, x_range[1], y_range[0], y_threshold),
    ]

    for zone_name, x0, x1, y0, y1 in zones:
        fig.add_shape(
            type="rect",
            x0=x0,
            x1=x1,
            y0=y0,
            y1=y1,
            fillcolor=colors.get(zone_name, "rgba(0,0,0,0.05)"),
            line={"width": 0},
            layer="below",
        )

        label = labels.get(zone_name, "")
        if label:
            fig.add_annotation(
                x=(x0 + x1) / 2,
                y=(y0 + y1) / 2,
                text=f"<b>{label}</b>",
                showarrow=False,
                font={"size": 14, "color": "rgba(0,0,0,0.3)"},
                xanchor="center",
                yanchor="middle",
            )


def add_hero_annotation(
    fig: go.Figure,
    text: str,
    x: float,
    y: float,
    arrow_to: tuple[float, float] | None = None,
    bgcolor: str = "#fff3cd",
    bordercolor: str = "#ffc107",
    font_size: int = 14,
) -> None:
    """Add prominent callout annotation.

    Args:
        fig: Plotly figure to add to.
        text: Annotation text.
        x: X position (in data coordinates).
        y: Y position (in data coordinates).
        arrow_to: Optional (x, y) tuple for arrow target.
        bgcolor: Background color.
        bordercolor: Border color.
        font_size: Font size.
    """
    fig.add_annotation(
        x=x,
        y=y,
        text=f"<b>{text}</b>",
        showarrow=arrow_to is not None,
        ax=arrow_to[0] if arrow_to else None,
        ay=arrow_to[1] if arrow_to else None,
        arrowhead=2,
        arrowsize=1.5,
        arrowwidth=2,
        arrowcolor=bordercolor,
        bgcolor=bgcolor,
        bordercolor=bordercolor,
        borderwidth=2,
        borderpad=8,
        font={"size": font_size, "color": "#333"},
        xanchor="center",
        yanchor="bottom",
    )


def highlight_extremes(
    fig: go.Figure,
    x_data: list[float],
    y_data: list[float],
    names: list[str],
    n: int = 3,
    metric: str = "y",
) -> None:
    """Auto-annotate best and worst performers.

    Args:
        fig: Plotly figure to add to.
        x_data: X values.
        y_data: Y values.
        names: Display names for each point.
        n: Number of extremes to highlight (top N and bottom N).
        metric: Which metric to use for ranking ("x", "y", or "combined").
    """
    import numpy as np

    if len(x_data) < 2 * n:
        return

    x = np.array(x_data)
    y = np.array(y_data)

    if metric == "y":
        values = y
    elif metric == "x":
        values = x
    else:
        # Combined: high y and low x is best
        values = y - x

    # Get indices of top and bottom performers
    sorted_indices = np.argsort(values)
    bottom_indices = sorted_indices[:n]
    top_indices = sorted_indices[-n:]

    # Add annotations for top performers (good)
    for idx in top_indices:
        fig.add_annotation(
            x=x[idx],
            y=y[idx],
            text=names[idx],
            showarrow=True,
            arrowhead=0,
            arrowsize=1,
            arrowwidth=1,
            arrowcolor="#2e8540",
            font={"size": 11, "color": "#2e8540"},
            xanchor="left",
            yanchor="bottom",
            ax=20,
            ay=-20,
        )

    # Add annotations for bottom performers (needs work)
    for idx in bottom_indices:
        fig.add_annotation(
            x=x[idx],
            y=y[idx],
            text=names[idx],
            showarrow=True,
            arrowhead=0,
            arrowsize=1,
            arrowwidth=1,
            arrowcolor="#dc3545",
            font={"size": 11, "color": "#dc3545"},
            xanchor="right",
            yanchor="top",
            ax=-20,
            ay=20,
        )
