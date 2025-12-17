from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from slop_code.dashboard.data import ChartContext
from slop_code.dashboard.data import analyze_model_variations
from slop_code.dashboard.data import get_dynamic_variant_annotation
from slop_code.dashboard.graphs.common import GROUPED_VERTICAL_LEGEND
from slop_code.dashboard.graphs.common import get_base_layout


@dataclass
class ScatterMetrics:
    """Data structure for scatter plot metrics (separates data from rendering)."""

    display_name: str
    model_name: str
    variant: str  # Dynamic variant label (for legend)
    annotation: str  # Annotation text (empty string = no annotation)
    x_value: float
    y_value: float
    color: str


@dataclass
class AxisConfig:
    """Declarative axis configuration for scatter charts."""

    title: str
    type: Literal["linear", "log"] = "linear"
    gridcolor: str = "lightgray"

    def to_dict(self) -> dict[str, str]:
        """Convert to Plotly axis configuration dict."""
        return {
            "title_text": self.title,
            "type": self.type,
            "gridcolor": self.gridcolor,
        }


def _data_to_pixel(
    x: float,
    y: float,
    x_range: tuple[float, float],
    y_range: tuple[float, float],
    fig_width: int,
    fig_height: int,
    log_x: bool = False,
    margin_left: int = 80,
    margin_right: int = 60,
    margin_top: int = 40,
    margin_bottom: int = 60,
) -> tuple[float, float]:
    plot_width = fig_width - margin_left - margin_right
    plot_height = fig_height - margin_top - margin_bottom

    if log_x and x > 0:
        x_log = math.log10(x)
        x_norm = (x_log - x_range[0]) / (x_range[1] - x_range[0])
    else:
        x_norm = (x - x_range[0]) / (x_range[1] - x_range[0])

    y_norm = (y - y_range[0]) / (y_range[1] - y_range[0])

    px_x = margin_left + x_norm * plot_width
    px_y = margin_top + (1 - y_norm) * plot_height

    return px_x, px_y


def add_smart_annotations(
    fig: go.Figure,
    points: list[tuple[float, float, str, str]],
    log_x: bool = False,
    fig_width: int = 1024,
    fig_height: int = 500,
    xref: str = "x",
    yref: str = "y",
) -> None:
    if not points:
        return

    sorted_points = sorted(points, key=lambda p: -p[1])
    offset_options = [
        (30, -20),
        (30, 20),
        (0, -35),
        (0, 35),
        (-30, -20),
        (-30, 20),
        (50, -30),
        (50, 30),
        (-50, -30),
        (-50, 30),
        (0, -55),
        (0, 55),
        (70, -40),
        (70, 40),
    ]

    x_vals = [p[0] for p in points]
    y_vals = [p[1] for p in points]

    if log_x:
        x_vals_positive = [x for x in x_vals if x > 0]
        if x_vals_positive:
            x_range_data = (
                math.log10(min(x_vals_positive)),
                math.log10(max(x_vals_positive)),
            )
        else:
            x_range_data = (0, 1)
    else:
        x_range_data = (min(x_vals), max(x_vals)) if x_vals else (0, 1)

    x_span = x_range_data[1] - x_range_data[0]
    x_padding = max(x_span * 0.1, 0.1)
    x_range_padded = (x_range_data[0] - x_padding, x_range_data[1] + x_padding)

    y_range_data = (min(y_vals), max(y_vals)) if y_vals else (0, 100)
    y_span = y_range_data[1] - y_range_data[0]
    y_padding = max(y_span * 0.05, 1)
    y_range_padded = (y_range_data[0] - y_padding, y_range_data[1] + y_padding)

    placed: list[tuple[float, float, int, int, float]] = []
    label_height_px = 14

    for x, y, text, color in sorted_points:
        px_x, px_y = _data_to_pixel(
            x, y, x_range_padded, y_range_padded, fig_width, fig_height, log_x
        )
        text_width_px = len(text) * 6.5

        best_ax, best_ay = offset_options[0]
        min_collision = float("inf")

        for ax, ay in offset_options:
            collision_score = 0
            label_cx = px_x + ax
            label_cy = px_y + ay

            for (
                placed_px_x,
                placed_px_y,
                placed_ax,
                placed_ay,
                placed_w,
            ) in placed:
                placed_cx = placed_px_x + placed_ax
                placed_cy = placed_px_y + placed_ay

                dy = abs(label_cy - placed_cy)
                if dy > label_height_px + 5:
                    continue

                dx = abs(label_cx - placed_cx)
                min_h_dist = (text_width_px + placed_w) / 2 + 8

                if dx < min_h_dist:
                    overlap_area = (min_h_dist - dx) * (
                        label_height_px + 5 - dy
                    )
                    collision_score += max(overlap_area, 1)

            if collision_score < min_collision:
                min_collision = collision_score
                best_ax, best_ay = ax, ay
            if collision_score == 0:
                break

        placed.append((px_x, px_y, best_ax, best_ay, text_width_px))

        x_display = math.log10(x) if log_x and x > 0 else x
        fig.add_annotation(
            x=x_display,
            y=y,
            xref=xref,
            yref=yref,
            text=f"<b>{text}</b>",
            showarrow=True,
            arrowhead=0,
            arrowwidth=1,
            arrowcolor=color,
            ax=best_ax,
            ay=best_ay,
            font={"size": 10, "color": color},
            borderpad=2,
        )


def _aggregate_scatter_metrics(
    context: ChartContext,
    x_value_fn: Callable[[pd.DataFrame], float],
    y_value_fn: Callable[[pd.DataFrame], float] | None = None,
    solve_type: Literal["all", "iso", "core"] = "all",
) -> list[ScatterMetrics]:
    df = context.run_summaries
    if df.empty:
        return []

    variation_info = analyze_model_variations(df)
    metrics = []
    solve_key = "pct_checkpoints_solved"
    if solve_type == "core":
        solve_key = "pct_checkpoints_core_solved"
    elif solve_type == "iso":
        solve_key = "pct_checkpoints_iso_solved"
    if y_value_fn is None:
        y_value_fn = lambda df: df[solve_key].mean()

    for display_name in sorted(df["display_name"].unique()):
        run_df = df[df["display_name"] == display_name]
        row = run_df.iloc[0]
        model_name = row["model_name"]
        model_variation = variation_info.get(model_name)
        variant = get_dynamic_variant_annotation(row, model_variation)
        annotation = "" if variant == "Base" else variant

        metrics.append(
            ScatterMetrics(
                display_name=display_name,
                model_name=model_name,
                variant=variant,
                annotation=annotation,
                x_value=x_value_fn(run_df),
                y_value=y_value_fn(run_df),
                color=context.base_color_map.get(display_name, "#888"),
            )
        )
    return metrics


def aggregate_erosion_vs_solve(
    context: ChartContext,
    solve_type: Literal["all", "iso", "core"] = "all",
    include_lint: bool = True,
    include_rubric: bool = True,
    include_ast_grep: bool = True,
) -> list[ScatterMetrics]:
    verbosity_keys = []
    if include_lint:
        verbosity_keys.append("ratios.lint.mean")
    if include_rubric:
        verbosity_keys.append("ratios.rubric.mean")
    if include_ast_grep:
        verbosity_keys.append("ratios.ast_grep.mean")

    return _aggregate_scatter_metrics(
        context,
        lambda df: df[verbosity_keys].fillna(0).sum(axis=1).mean(),
        solve_type=solve_type,
    )


def aggregate_lint_ast_grep_vs_solve(
    context: ChartContext,
) -> list[ScatterMetrics]:
    return _aggregate_scatter_metrics(
        context,
        lambda df: (
            df[
                [
                    "ratios.ast_grep.mean",
                    "ratios.lint.mean",
                ]
            ]
            .fillna(0)
            .sum(axis=1)
            .mean()
        ),
    )


def aggregate_high_complexity_vs_solve(
    context: ChartContext,
) -> list[ScatterMetrics]:
    return _aggregate_scatter_metrics(
        context,
        lambda df: df["cc.max.mean"].fillna(0).mean(),
    )


def aggregate_cost_vs_solve(context: ChartContext) -> list[ScatterMetrics]:
    return _aggregate_scatter_metrics(
        context,
        lambda df: df["costs.checkpoint.mean"].fillna(0).mean(),
    )


def aggregate_time_vs_solve(context: ChartContext) -> list[ScatterMetrics]:
    return _aggregate_scatter_metrics(
        context,
        lambda df: df["time.checkpoint.mean"].fillna(0).mean() / 60,
    )


def aggregate_cost_per_problem(context: ChartContext) -> list[ScatterMetrics]:
    def compute_cost_per_problem(df: pd.DataFrame) -> float:
        total_cost = df["costs.total"].fillna(0).mean()
        num_problems = df["num_problems"].fillna(1).mean()
        return total_cost / num_problems if num_problems > 0 else 0

    return _aggregate_scatter_metrics(context, compute_cost_per_problem)


def aggregate_ast_grep_vs_solve(context: ChartContext) -> list[ScatterMetrics]:
    return _aggregate_scatter_metrics(
        context, lambda df: df["ratios.ast_grep.mean"].fillna(0).mean()
    )


def aggregate_lint_vs_solve(context: ChartContext) -> list[ScatterMetrics]:
    return _aggregate_scatter_metrics(
        context, lambda df: df["ratios.lint.mean"].fillna(0).mean()
    )


def aggregate_rubric_vs_solve(context: ChartContext) -> list[ScatterMetrics]:
    return _aggregate_scatter_metrics(
        context, lambda df: df["ratios.rubric.mean"].fillna(0).mean()
    )


def aggregate_erosion_vs_problem_test_pass_rate(
    context: ChartContext,
) -> list[ScatterMetrics]:
    return _aggregate_scatter_metrics(
        context,
        x_value_fn=lambda df: (
            df[
                [
                    "ratios.ast_grep.mean",
                    "ratios.lint.mean",
                    "ratios.rubric.mean",
                ]
            ]
            .fillna(0)
            .sum(axis=1)
            .mean()
        ),
        y_value_fn=lambda df: df["pass_rates.problem.total"].fillna(0).mean()
        * 100,
    )


def aggregate_erosion_vs_checkpoint_test_pass_rate(
    context: ChartContext,
) -> list[ScatterMetrics]:
    return _aggregate_scatter_metrics(
        context,
        x_value_fn=lambda df: (
            df[
                [
                    "ratios.ast_grep.mean",
                    "ratios.lint.mean",
                    "ratios.rubric.mean",
                ]
            ]
            .fillna(0)
            .sum(axis=1)
            .mean()
        ),
        y_value_fn=lambda df: df["pass_rates.checkpoint.total"].fillna(0).mean()
        * 100,
    )


class ScatterChartRenderer:
    def __init__(self, x_axis: AxisConfig, y_axis: AxisConfig):
        self.x_axis = x_axis
        self.y_axis = y_axis

    def add_traces(
        self,
        fig: go.Figure,
        metrics: list[ScatterMetrics],
        row: int | None = None,
        col: int | None = None,
        show_annotations: bool = True,
        seen_models: set[str] | None = None,
        subplot_width: int = 1024,
        subplot_height: int = 500,
        xref: str = "x",
        yref: str = "y",
    ) -> None:
        """Add traces to a specific subplot (or the main figure)."""
        annotation_points: list[tuple[float, float, str, str]] = []

        if seen_models is None:
            # If not provided, track locally for this call only
            # (standard single-plot behavior)
            seen_models = set()
            track_globally = False
        else:
            track_globally = True

        for m in metrics:
            is_first_for_model = m.model_name not in seen_models
            if is_first_for_model:
                seen_models.add(m.model_name)

            fig.add_scatter(
                x=[m.x_value],
                y=[m.y_value],
                name=f"<b>{m.model_name}</b>",
                legendgroup=m.model_name,
                mode="markers",
                marker={"color": m.color, "size": 15},
                showlegend=is_first_for_model,
                row=row,
                col=col,
            )

            if m.annotation:
                annotation_points.append(
                    (m.x_value, m.y_value, m.annotation, m.color)
                )

        if show_annotations:
            add_smart_annotations(
                fig,
                annotation_points,
                log_x=self.x_axis.type == "log",
                fig_width=subplot_width,
                fig_height=subplot_height,
                xref=xref,
                yref=yref,
            )

        # Update axes for this subplot
        if row is not None and col is not None:
            fig.update_xaxes(
                **self.x_axis.to_dict(),
                row=row,
                col=col,
            )
            fig.update_yaxes(
                **self.y_axis.to_dict(),
                row=row,
                col=col,
            )

    def render(
        self, metrics: list[ScatterMetrics], show_annotations: bool = True
    ) -> go.Figure:
        fig = go.Figure()
        self.add_traces(
            fig,
            metrics,
            show_annotations=show_annotations,
            subplot_width=1024,
            subplot_height=500,
        )

        fig.update_xaxes(**self.x_axis.to_dict())
        fig.update_yaxes(**self.y_axis.to_dict())
        fig.update_layout(**get_base_layout(None, 500, 1.0))
        fig.update_layout(
            legend=GROUPED_VERTICAL_LEGEND,
            margin={"t": 20, "b": 50, "l": 60, "r": 150},
        )
        return fig


@dataclass
class ScatterChartConfig:
    aggregator: Callable[[ChartContext], list[ScatterMetrics]]
    x_axis: AxisConfig
    y_axis: AxisConfig


SCATTER_CHARTS: dict[str, ScatterChartConfig] = {
    "verbosity_vs_solve": ScatterChartConfig(
        aggregator=lambda context: aggregate_erosion_vs_solve(
            context,
            include_lint=False,
            include_ast_grep=True,
            include_rubric=True,
        ),
        x_axis=AxisConfig("Rubric + AST Grep Errors"),
        y_axis=AxisConfig("% Checkpoints Solved"),
    ),
    "verbosity_vs_core_solve": ScatterChartConfig(
        aggregator=lambda context: aggregate_erosion_vs_solve(
            context, "core", include_lint=False
        ),
        x_axis=AxisConfig("Verbosity:LOC Ratio", "log"),
        y_axis=AxisConfig("% Checkpoints Core Solved"),
    ),
    "verbosity_vs_iso_solve": ScatterChartConfig(
        aggregator=lambda context: aggregate_erosion_vs_solve(
            context, "iso", include_lint=False
        ),
        x_axis=AxisConfig("Verbosity:LOC Ratio", "log"),
        y_axis=AxisConfig("% Checkpoints ISO Solved"),
    ),
    "high_complexity_vs_solve": ScatterChartConfig(
        aggregator=aggregate_high_complexity_vs_solve,
        x_axis=AxisConfig("High Complexity", "log"),
        y_axis=AxisConfig("% Checkpoints Solved"),
    ),
    "erosion_vs_problem_test_pass_rate": ScatterChartConfig(
        aggregator=aggregate_erosion_vs_problem_test_pass_rate,
        x_axis=AxisConfig("Erosion:LOC Ratio", "log"),
        y_axis=AxisConfig("% Problem Test Pass Rate"),
    ),
    "erosion_vs_checkpoint_test_pass_rate": ScatterChartConfig(
        aggregator=aggregate_erosion_vs_checkpoint_test_pass_rate,
        x_axis=AxisConfig("Erosion:LOC Ratio", "log"),
        y_axis=AxisConfig("% Checkpoint Test Pass Rate"),
    ),
    "cost_vs_solve": ScatterChartConfig(
        aggregator=aggregate_cost_vs_solve,
        x_axis=AxisConfig("$ / CHKPT", "log"),
        y_axis=AxisConfig("% Checkpoints Solved"),
    ),
    "time_vs_solve": ScatterChartConfig(
        aggregator=aggregate_time_vs_solve,
        x_axis=AxisConfig("Minutes / CHKPT", "log"),
        y_axis=AxisConfig("% Checkpoints Solved"),
    ),
    "cost_per_problem": ScatterChartConfig(
        aggregator=aggregate_cost_per_problem,
        x_axis=AxisConfig("$ / Problem", "log"),
        y_axis=AxisConfig("% Checkpoints Solved"),
    ),
    "lint_vs_solve": ScatterChartConfig(
        aggregator=aggregate_lint_vs_solve,
        x_axis=AxisConfig("Lint Errors", "log"),
        y_axis=AxisConfig("% Checkpoints Solved"),
    ),
    "ast_grep_vs_solve": ScatterChartConfig(
        aggregator=aggregate_ast_grep_vs_solve,
        x_axis=AxisConfig("AST Grep Errors", "log"),
        y_axis=AxisConfig("% Checkpoints Solved"),
    ),
    "rubric_vs_solve": ScatterChartConfig(
        aggregator=aggregate_rubric_vs_solve,
        x_axis=AxisConfig("Rubric Flags", "log"),
        y_axis=AxisConfig("% Checkpoints Solved"),
    ),
}


def build_scatter_chart(
    context: ChartContext, chart_type: str, show_annotations: bool = True
) -> go.Figure:
    if chart_type not in SCATTER_CHARTS:
        return go.Figure()
    config = SCATTER_CHARTS[chart_type]
    metrics = config.aggregator(context)
    renderer = ScatterChartRenderer(config.x_axis, config.y_axis)
    return renderer.render(metrics, show_annotations=show_annotations)


def build_multi_scatter_chart(
    context: ChartContext,
    chart_types: list[str],
    cols: int = 2,
    show_annotations: bool = True,
    subplot_height: int = 400,
) -> go.Figure:
    """Creates a multi-subplot figure for the given scatter charts."""
    valid_charts = [k for k in chart_types if k in SCATTER_CHARTS]
    if not valid_charts:
        return go.Figure()

    rows = math.ceil(len(valid_charts) / cols)

    # Calculate subplot titles
    subplot_titles = [k.replace("_", " ").title() for k in valid_charts]

    fig = make_subplots(
        rows=rows,
        cols=cols,
        subplot_titles=subplot_titles,
        vertical_spacing=0.08,
        horizontal_spacing=0.06,
    )

    seen_models: set[str] = set()

    # Determine individual subplot dimensions (approximate)
    # Total width ~1800px (standard large monitor) or context dependent
    # We'll assume a standard nice width for calculation purposes
    total_width = 1800
    single_plot_width = int((total_width - 100) / cols)

    for i, chart_type in enumerate(valid_charts):
        row = (i // cols) + 1
        col = (i % cols) + 1

        config = SCATTER_CHARTS[chart_type]
        metrics = config.aggregator(context)
        renderer = ScatterChartRenderer(config.x_axis, config.y_axis)

        # Determine axis names for this subplot
        # make_subplots assigns defaults like x, y for (1,1), x2, y2 for (1,2), etc.
        # But we don't strictly need them unless we are doing something very custom.
        # However, add_smart_annotations needs them.
        # Plotly logic: (row, col) -> (xref, yref)
        # linear index = (row-1)*cols + (col-1) + 1 (1-based)
        # But make_subplots does custom numbering.
        # Simpler: just pass row/col to add_traces and let it handle axes updates,
        # but for annotations we need the actual axis name string.
        # "x" if i==0 else f"x{i+1}"

        # Calculate axis names
        idx = i + 1
        xref = "x" if idx == 1 else f"x{idx}"
        yref = "y" if idx == 1 else f"y{idx}"

        renderer.add_traces(
            fig,
            metrics,
            row=row,
            col=col,
            show_annotations=show_annotations,
            seen_models=seen_models,
            subplot_width=single_plot_width,
            subplot_height=subplot_height,
            xref=xref,
            yref=yref,
        )

    # Global Layout
    total_height = rows * subplot_height + 150  # extra for legend/title
    fig.update_layout(
        height=total_height,
        template="plotly_white",
        margin={"t": 60, "b": 100, "l": 40, "r": 40},
        legend={
            "orientation": "h",
            "yanchor": "bottom",
            "y": -0.1 / rows,  # Adjust based on number of rows to be below
            "xanchor": "center",
            "x": 0.5,
            "bgcolor": "rgba(255,255,255,0.8)",
            "borderwidth": 0,
        },
    )

    # Update all annotations to be smaller in grid view
    fig.update_annotations(font_size=9)

    return fig
