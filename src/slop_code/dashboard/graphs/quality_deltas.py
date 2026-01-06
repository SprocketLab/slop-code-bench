from __future__ import annotations

import numpy as np
import plotly.graph_objects as go

from slop_code.dashboard.data import ChartContext
from slop_code.dashboard.data import compute_problem_deltas
from slop_code.dashboard.graphs.common import get_base_layout

METRICS = [
    ("lint_delta_pct", "Lint Δ%"),
    ("ast_grep_delta_pct", "AST-grep Δ%"),
    ("rubric_delta_pct", "Rubric Δ%"),
    ("complex_delta_pct", "Complexity Δ%"),
    ("rubric_non_carryover", "Novel Flags (count)"),
    ("cc_max_delta_pct", "Max CC Δ%"),
]


def _empty_chart(title: str) -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(
        text="No quality delta data",
        x=0.5,
        y=0.5,
        showarrow=False,
        font={"size": 14},
    )
    fig.update_layout(**get_base_layout(None, 420, -0.2, title))
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    return fig


def build_delta_distribution(context: ChartContext) -> go.Figure:
    """Distribution of N->N+1 deltas per metric (box plot)."""
    deltas = compute_problem_deltas(context.checkpoints)
    if deltas.empty:
        return _empty_chart("Delta Distribution by Metric")

    fig = go.Figure()
    has_data = False

    for metric_key, label in METRICS:
        series = deltas.get(metric_key, [])
        series = series.replace([np.inf, -np.inf], np.nan).dropna()
        if series.empty:
            continue

        has_data = True
        fig.add_trace(
            go.Box(
                x=[label] * len(series),
                y=series,
                name=label,
                boxpoints="outliers",
                marker_color="#4f6bed",
                line={"color": "#4f6bed"},
                showlegend=False,
            )
        )

    if not has_data:
        return _empty_chart("Delta Distribution by Metric")

    fig.add_hline(y=0, line={"color": "#999", "width": 1, "dash": "dash"})
    fig.update_layout(
        **get_base_layout(None, 520, -0.2, "Delta Distribution by Metric"),
        yaxis_title="Delta (percent or count)",
    )
    fig.update_yaxes(gridcolor="#f1f3f5")
    return fig


def build_delta_improvement_heatmap(context: ChartContext) -> go.Figure:
    """Improvement rate (share of negative deltas) by run and metric."""
    deltas = compute_problem_deltas(context.checkpoints)
    if deltas.empty:
        return _empty_chart("Improvement Rate by Run")

    run_names = sorted(deltas["display_name"].unique())
    metric_labels = [label for _, label in METRICS]

    z: list[list[float | None]] = []
    text: list[list[str]] = []
    for run in run_names:
        run_row: list[float | None] = []
        run_text: list[str] = []
        run_data = deltas[deltas["display_name"] == run]
        for metric_key, _ in METRICS:
            series = run_data.get(metric_key, [])
            series = series.replace([np.inf, -np.inf], np.nan).dropna()
            if series.empty:
                run_row.append(None)
                run_text.append("—")
                continue

            if metric_key == "rubric_non_carryover":
                improvement_mask = series == 0  # No new flags introduced
            else:
                improvement_mask = series <= 0  # Held steady or improved

            rate = improvement_mask.mean() * 100
            run_row.append(rate)
            run_text.append(f"{rate:.0f}%")
        z.append(run_row)
        text.append(run_text)

    fig = go.Figure(
        data=go.Heatmap(
            z=z,
            x=metric_labels,
            y=run_names,
            text=text,
            texttemplate="%{text}",
            colorscale=[
                [0, "#f8d7da"],  # light red
                [0.5, "#fff3cd"],  # light yellow
                [1, "#2e8540"],  # green
            ],
            zmin=0,
            zmax=100,
            colorbar={"title": "Improvement rate"},
        )
    )

    fig.update_layout(
        **get_base_layout(None, 520, -0.15, "Improvement Rate by Run"),
    )
    fig.update_xaxes(side="top")
    return fig
