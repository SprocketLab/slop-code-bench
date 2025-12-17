from __future__ import annotations

import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from slop_code.dashboard.data import ChartContext
from slop_code.dashboard.data import analyze_model_variations
from slop_code.dashboard.data import compute_problem_deltas
from slop_code.dashboard.graphs.common import GROUPED_VERTICAL_LEGEND
from slop_code.dashboard.graphs.common import LegendGroupTracker
from slop_code.dashboard.graphs.common import get_base_layout


def build_checkpoint_delta_boxplot(context: ChartContext) -> go.Figure:
    df = context.checkpoints
    if df.empty:
        return go.Figure()

    deltas = compute_problem_deltas(df)
    if deltas.empty:
        return go.Figure()

    deltas = deltas.replace([float("inf"), float("-inf")], np.nan)

    fig = make_subplots(
        rows=2,
        cols=3,
        vertical_spacing=0.1,
        horizontal_spacing=0.05,
        subplot_titles=[
            "LOC",
            "Lint",
            "AST Grep Rules",
            "Rubric",
            "Novel Flags",
            "High Complexity Symbols",
        ],
    )

    metrics = [
        ("lines_delta_pct", 1, 1),
        ("lint_delta_pct", 1, 2),
        ("ast_grep_delta_pct", 1, 3),
        ("rubric_delta_pct", 2, 1),
        ("rubric_non_carryover", 2, 2),
        ("complex_delta_pct", 2, 3),
    ]

    variation_info = analyze_model_variations(df)
    tracker = LegendGroupTracker(context.color_map, variation_info)

    # Sort runs according to the new logic
    sorted_unique_runs = (
        deltas[
            [
                "display_name",
                "model_name",
                "_thinking_sort_key",
                "prompt_template",
                "run_date",
            ]
        ]
        .drop_duplicates()
        .sort_values(
            by=[
                "model_name",
                "_thinking_sort_key",
                "prompt_template",
                "run_date",
            ]
        )
    )
    for display_name in sorted_unique_runs["display_name"]:
        run_data = deltas[deltas["display_name"] == display_name]
        orig_row = df[df["display_name"] == display_name].iloc[0]
        info = tracker.get_info(display_name, orig_row)

        for metric, r, c in metrics:
            values = run_data[metric].dropna()
            show_legend = r == 1 and c == 1

            fig.add_trace(
                go.Box(
                    x=[display_name] * len(values),
                    y=values,
                    name=info.variant,
                    legendgroup=info.model_name,
                    legendgrouptitle_text=info.group_title
                    if show_legend
                    else None,
                    legendgrouptitle_font={"color": info.model_base_color},
                    marker={"color": info.color},
                    showlegend=show_legend,
                    boxpoints="outliers",
                ),
                row=r,
                col=c,
            )

    fig.update_yaxes(title_text="%", row=1, col=1, gridcolor="lightgray")
    fig.update_yaxes(row=1, col=2, gridcolor="lightgray")
    fig.update_yaxes(row=1, col=3, gridcolor="lightgray")
    fig.update_yaxes(row=2, col=1, gridcolor="lightgray")
    fig.update_yaxes(row=2, col=2, gridcolor="lightgray")
    fig.update_yaxes(row=2, col=3, gridcolor="lightgray")

    for r in [1, 2]:
        for c in [1, 2, 3]:
            fig.update_xaxes(row=r, col=c, showticklabels=False)

    for annotation in fig.layout.annotations:
        annotation.y = annotation.y + 0.05

    fig.update_layout(
        **get_base_layout(
            None, 800, 1.0, "% Delta Between Consecutive Checkpoints"
        )
    )
    fig.update_layout(legend=GROUPED_VERTICAL_LEGEND)
    return fig
