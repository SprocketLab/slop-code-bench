"""Reusable chart builder classes for common visualization patterns."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from slop_code.visualization.constants import GRAPH_HEIGHT
from slop_code.visualization.constants import GRAPH_WIDTH
from slop_code.visualization.constants import MODEL_COLORS
from slop_code.visualization.constants import MODEL_DISPLAY_NAMES
from slop_code.visualization.constants import PROVIDER_GRADS
from slop_code.visualization.data_transforms import compute_progress_metric
from slop_code.visualization.data_transforms import (
    filter_high_thinking_checkpoints,
)
from slop_code.visualization.data_transforms import format_model_display_name
from slop_code.visualization.graph_utils import FONT_FAMILY_IMPACT
from slop_code.visualization.graph_utils import get_theme


def apply_graph_style(
    fig: go.Figure,
    title: str,
    width: int = GRAPH_WIDTH,
    height: int = GRAPH_HEIGHT,
) -> None:
    """Apply consistent styling to all graphs.

    Args:
        fig: Plotly figure to style
        title: Chart title (will be bolded)
        width: Figure width in pixels
        height: Figure height in pixels
    """
    theme = get_theme("light")

    # Apply theme to all axes (works for both single and subplots)
    fig.update_xaxes(
        gridcolor=theme["gridcolor"],
        linecolor=theme["axis_color"],
        tickfont=dict(color=theme["axis_color"], family=FONT_FAMILY_IMPACT),
        title_font=dict(color=theme["font_color"], family=FONT_FAMILY_IMPACT),
    )
    fig.update_yaxes(
        gridcolor=theme["gridcolor"],
        linecolor=theme["axis_color"],
        tickfont=dict(color=theme["axis_color"], family=FONT_FAMILY_IMPACT),
        title_font=dict(color=theme["font_color"], family=FONT_FAMILY_IMPACT),
    )

    # Apply layout with consistent legend
    fig.update_layout(
        title=dict(
            text=f"<b>{title}</b>" if title else None,
            font=dict(
                family=FONT_FAMILY_IMPACT, size=24, color=theme["title_color"]
            ),
            x=0.5,
            xanchor="center",
        ),
        plot_bgcolor=theme["plot_bgcolor"],
        paper_bgcolor=theme["paper_bgcolor"],
        font=dict(
            family=FONT_FAMILY_IMPACT, size=14, color=theme["font_color"]
        ),
        legend=dict(
            orientation="h",
            yanchor="top",
            y=-0.12,
            xanchor="center",
            x=0.5,
            bgcolor=theme["legend_bg"],
            font=dict(
                size=14, family=FONT_FAMILY_IMPACT, color=theme["font_color"]
            ),
            borderwidth=0,
        ),
        width=width,
        height=height,
        margin=dict(t=60, b=80, l=60, r=40),
    )


# -----------------------------------------------------------------------------
# Metric Configuration
# -----------------------------------------------------------------------------


@dataclass
class MetricConfig:
    """Configuration for a single metric in a chart.

    Attributes:
        column: DataFrame column name
        title: Display title for the metric
        format_fn: Optional function to transform values (e.g., lambda x: x * 100)
        text_format: Format string for bar text labels (e.g., "{:.1f}")
        y_range: Optional fixed y-axis range as (min, max)
    """

    column: str
    title: str
    format_fn: Callable[[float], float] | None = None
    text_format: str = "{:.1f}"
    y_range: tuple[float, float] | None = None


# -----------------------------------------------------------------------------
# Subplot Bar Chart Builder
# -----------------------------------------------------------------------------


@dataclass
class SubplotBarChartConfig:
    """Configuration for subplot bar charts.

    Attributes:
        metrics: List of MetricConfig for each subplot
        title: Overall chart title
        width: Figure width in pixels
        height: Figure height in pixels
        horizontal_spacing: Space between subplots
        y_title: Optional y-axis title for first subplot
    """

    metrics: list[MetricConfig]
    title: str = ""
    width: int = 1200
    height: int = 400
    horizontal_spacing: float = 0.07
    y_title: str | None = None


class SubplotBarChartBuilder:
    """Builder for grouped bar charts with subplots.

    Creates multi-panel bar charts where each subplot shows a different metric,
    with bars grouped by provider or model.
    """

    def __init__(self, config: SubplotBarChartConfig):
        self.config = config

    def build_by_provider(
        self,
        df: pd.DataFrame,
        provider_grads: dict[str, list[str]] | None = None,
    ) -> go.Figure:
        """Build bar chart grouped by provider.

        Args:
            df: DataFrame with 'provider' and 'model' columns
            provider_grads: Color gradients per provider (defaults to PROVIDER_GRADS)

        Returns:
            Configured Plotly Figure
        """
        if provider_grads is None:
            provider_grads = PROVIDER_GRADS

        fig = make_subplots(
            rows=1,
            cols=len(self.config.metrics),
            subplot_titles=[m.title for m in self.config.metrics],
            shared_yaxes=False,
            horizontal_spacing=self.config.horizontal_spacing,
        )

        for provider, pdf in sorted(df.groupby("provider"), key=lambda x: x[0]):
            colors = provider_grads.get(provider, ["#888"])
            for i, (_, row) in enumerate(pdf.iterrows()):
                color = colors[i % len(colors)]
                for col_idx, metric in enumerate(self.config.metrics, 1):
                    val = row[metric.column]
                    if metric.format_fn:
                        val = metric.format_fn(val)

                    fig.add_trace(
                        go.Bar(
                            y=[val],
                            name=format_model_display_name(row["model"]),
                            marker_color=color,
                            text=[metric.text_format.format(val)],
                            textposition="inside",
                            textangle=0,
                            showlegend=(col_idx == 1),
                        ),
                        row=1,
                        col=col_idx,
                    )

        # Apply y-axis settings
        if self.config.y_title:
            fig.update_yaxes(title_text=self.config.y_title, row=1, col=1)

        for idx, metric in enumerate(self.config.metrics, 1):
            fig.update_xaxes(showticklabels=False, row=1, col=idx)
            if metric.y_range:
                fig.update_yaxes(range=list(metric.y_range), row=1, col=idx)

        apply_graph_style(
            fig, self.config.title, self.config.width, self.config.height
        )
        return fig

    def build_by_model(
        self,
        df: pd.DataFrame,
        color_map: dict[str, str] | None = None,
    ) -> go.Figure:
        """Build bar chart grouped by model.

        Args:
            df: DataFrame with 'model' column
            color_map: Model to color mapping (defaults to MODEL_COLORS)

        Returns:
            Configured Plotly Figure
        """
        if color_map is None:
            color_map = MODEL_COLORS

        fig = make_subplots(
            rows=1,
            cols=len(self.config.metrics),
            subplot_titles=[m.title for m in self.config.metrics],
            shared_yaxes=False,
            horizontal_spacing=self.config.horizontal_spacing,
        )

        for model in sorted(df["model"].unique()):
            model_df = df[df["model"] == model]
            color = color_map.get(model, "#888")
            display_name = format_model_display_name(model)

            for col_idx, metric in enumerate(self.config.metrics, 1):
                val = model_df[metric.column].iloc[0]
                if metric.format_fn:
                    val = metric.format_fn(val)

                fig.add_trace(
                    go.Bar(
                        x=[display_name],
                        y=[val],
                        name=display_name,
                        marker_color=color,
                        text=[metric.text_format.format(val)],
                        textposition="inside",
                        showlegend=(col_idx == 1),
                    ),
                    row=1,
                    col=col_idx,
                )

        # Apply y-axis settings
        if self.config.y_title:
            fig.update_yaxes(title_text=self.config.y_title, row=1, col=1)

        for idx, metric in enumerate(self.config.metrics, 1):
            fig.update_xaxes(showticklabels=False, row=1, col=idx)
            if metric.y_range:
                fig.update_yaxes(range=list(metric.y_range), row=1, col=idx)

        apply_graph_style(
            fig, self.config.title, self.config.width, self.config.height
        )
        return fig


# -----------------------------------------------------------------------------
# Progress Line Chart Builder
# -----------------------------------------------------------------------------


@dataclass
class ProgressLineChartConfig:
    """Configuration for progress-based line charts.

    Attributes:
        metric_col: DataFrame column to plot
        y_title: Y-axis title
        title: Chart title
        width: Figure width
        height: Figure height
    """

    metric_col: str
    y_title: str
    title: str
    width: int = GRAPH_WIDTH
    height: int = GRAPH_HEIGHT


class ProgressLineChartBuilder:
    """Builder for line charts showing metric trajectories across progress bins.

    Creates line charts where x-axis is progress % through problems
    and each line represents a different model.
    """

    def __init__(self, config: ProgressLineChartConfig):
        self.config = config

    def build(
        self,
        checkpoints: pd.DataFrame,
        color_map: dict[str, str] | None = None,
    ) -> go.Figure:
        """Build progress line chart.

        Args:
            checkpoints: Checkpoints DataFrame (will be filtered to high thinking)
            color_map: Model to color mapping (defaults to MODEL_COLORS)

        Returns:
            Configured Plotly Figure
        """
        if color_map is None:
            color_map = MODEL_COLORS

        high = filter_high_thinking_checkpoints(checkpoints)
        progress_data = compute_progress_metric(high, self.config.metric_col)

        fig = go.Figure()

        for model in sorted(progress_data["model"].unique()):
            mdf = progress_data[progress_data["model"] == model].sort_values(
                "progress_bin"
            )

            fig.add_trace(
                go.Scatter(
                    x=mdf["progress_bin"] * 100,
                    y=mdf[self.config.metric_col],
                    mode="lines+markers",
                    name=MODEL_DISPLAY_NAMES.get(model, model),
                    line=dict(
                        color=color_map.get(model, "#888"),
                        width=3,
                        shape="spline",
                    ),
                    marker=dict(size=8),
                )
            )

        fig.update_xaxes(
            title_text="Progress (%)", ticksuffix="%", range=[15, 105]
        )
        fig.update_yaxes(title_text=self.config.y_title)

        apply_graph_style(
            fig, self.config.title, self.config.width, self.config.height
        )
        return fig


# -----------------------------------------------------------------------------
# Violin Distribution Builder
# -----------------------------------------------------------------------------


@dataclass
class ViolinDistributionConfig:
    """Configuration for violin distribution plots.

    Attributes:
        metrics: List of (column, title) tuples
        title: Chart title
        rows: Number of subplot rows
        cols: Number of subplot columns
        width: Figure width
        height: Figure height
    """

    metrics: list[tuple[str, str]]
    title: str
    rows: int = 1
    cols: int = 4
    width: int = 1200
    height: int = 400
    vertical_spacing: float = 0.15
    horizontal_spacing: float = 0.08


class ViolinDistributionBuilder:
    """Builder for violin plot distribution charts.

    Creates violin plots showing distribution of metrics across versions.
    """

    def __init__(self, config: ViolinDistributionConfig):
        self.config = config

    def build(
        self,
        df: pd.DataFrame,
        versions: list[str],
        color_map: dict[str, str],
        version_col: str = "agent_version",
        transform_fn: dict[str, Callable] | None = None,
    ) -> go.Figure:
        """Build violin distribution chart.

        Args:
            df: DataFrame with version data
            versions: List of versions to include
            color_map: Version to color mapping
            version_col: Column containing version info
            transform_fn: Optional dict of column -> transform function

        Returns:
            Configured Plotly Figure
        """
        if transform_fn is None:
            transform_fn = {}

        fig = make_subplots(
            rows=self.config.rows,
            cols=self.config.cols,
            subplot_titles=[m[1] for m in self.config.metrics],
            vertical_spacing=self.config.vertical_spacing,
            horizontal_spacing=self.config.horizontal_spacing,
        )

        for idx, (col, title) in enumerate(self.config.metrics):
            row = idx // self.config.cols + 1
            subplot_col = idx % self.config.cols + 1

            for version in versions:
                vdf = df[df[version_col] == version]
                y_vals = vdf[col]

                # Apply transform if specified
                if col in transform_fn:
                    y_vals = transform_fn[col](y_vals)

                fig.add_trace(
                    go.Violin(
                        y=y_vals,
                        name=version,
                        legendgroup=version,
                        showlegend=(idx == 0),
                        line_color=color_map[version],
                        fillcolor=color_map[version],
                        opacity=0.7,
                        box_visible=True,
                        meanline_visible=True,
                    ),
                    row=row,
                    col=subplot_col,
                )

        # Hide x-axis ticks - versions shown in legend
        fig.update_xaxes(showticklabels=False)

        apply_graph_style(
            fig, self.config.title, self.config.width, self.config.height
        )
        return fig


# -----------------------------------------------------------------------------
# Radar Chart Builder
# -----------------------------------------------------------------------------


@dataclass
class RadarChartConfig:
    """Configuration for radar/polar charts.

    Attributes:
        metrics: Dict of display_name -> column_name
        title: Chart title (can be empty for individual model titles)
        width: Figure width
        height: Figure height
    """

    metrics: dict[str, str]
    title: str = ""
    width: int = 700
    height: int = 700


class RadarChartBuilder:
    """Builder for 2x2 radar chart grids.

    Creates a grid of radar/polar charts, one per model, showing
    concentration or profile metrics.
    """

    def __init__(self, config: RadarChartConfig):
        self.config = config

    def build(
        self,
        checkpoints: pd.DataFrame,
        color_map: dict[str, str] | None = None,
        derived_cols: dict[str, Callable[[pd.DataFrame], pd.Series]]
        | None = None,
    ) -> go.Figure:
        """Build radar chart grid.

        Args:
            checkpoints: Checkpoints DataFrame (will be filtered to high thinking)
            color_map: Model to color mapping (defaults to MODEL_COLORS)
            derived_cols: Optional dict of column_name -> function to compute derived columns

        Returns:
            Configured Plotly Figure
        """
        if color_map is None:
            color_map = MODEL_COLORS

        high = filter_high_thinking_checkpoints(checkpoints)

        # Compute any derived columns
        if derived_cols:
            for col_name, compute_fn in derived_cols.items():
                high[col_name] = compute_fn(high)

        # Get mean per model
        model_data = {}
        for model in high["model"].unique():
            mdf = high[high["model"] == model]
            model_data[model] = {
                name: mdf[col].mean()
                for name, col in self.config.metrics.items()
            }

        models = sorted(model_data.keys())
        categories = list(self.config.metrics.keys())

        # Find max value for consistent scale
        max_val = max(
            val for data in model_data.values() for val in data.values()
        )
        max_range = (
            np.ceil(max_val * 10) / 10 if max_val < 10 else np.ceil(max_val)
        )

        # Calculate grid size based on number of models
        n_models = len(models)
        n_cols = min(3, n_models)  # Max 3 columns
        n_rows = (n_models + n_cols - 1) // n_cols  # Ceiling division

        # Build specs for polar subplots
        specs = [
            [{"type": "polar"} for _ in range(n_cols)] for _ in range(n_rows)
        ]

        fig = make_subplots(
            rows=n_rows,
            cols=n_cols,
            specs=specs,
            subplot_titles=[MODEL_DISPLAY_NAMES.get(m, m) for m in models],
            horizontal_spacing=0.12,
            vertical_spacing=0.15,
        )

        for i, model in enumerate(models):
            row = i // n_cols + 1
            col = i % n_cols + 1
            values = [model_data[model][cat] for cat in categories]
            values.append(values[0])  # Close the polygon

            fig.add_trace(
                go.Scatterpolar(
                    r=values,
                    theta=categories + [categories[0]],
                    fill="toself",
                    name=MODEL_DISPLAY_NAMES.get(model, model),
                    line=dict(color=color_map.get(model, "#888"), width=2),
                    fillcolor=color_map.get(model, "#888"),
                    opacity=0.4,
                    showlegend=False,
                ),
                row=row,
                col=col,
            )

        # Update all polar axes with same scale
        for i in range(1, len(models) + 1):
            polar_key = f"polar{i}" if i > 1 else "polar"
            fig.update_layout(
                **{
                    polar_key: dict(
                        radialaxis=dict(
                            visible=True,
                            range=[0, max_range],
                            tickfont=dict(size=10),
                        ),
                        angularaxis=dict(tickfont=dict(size=10)),
                    )
                }
            )

        apply_graph_style(
            fig, self.config.title, self.config.width, self.config.height
        )
        fig.update_layout(title=None, margin=dict(t=40, b=40, l=40, r=40))
        return fig
