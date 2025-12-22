from __future__ import annotations

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from slop_code.dashboard.data import ChartContext
from slop_code.dashboard.data import analyze_model_variations
from slop_code.dashboard.graphs.common import GROUPED_VERTICAL_LEGEND
from slop_code.dashboard.graphs.common import LegendGroupTracker
from slop_code.dashboard.graphs.common import get_base_layout


def build_test_pass_rate_bars(context: ChartContext) -> go.Figure:
    df = context.checkpoints
    if df.empty:
        return go.Figure()

    fig = make_subplots(
        rows=2,
        cols=3,
        vertical_spacing=0.1,
        horizontal_spacing=0.05,
        shared_yaxes=True,
        subplot_titles=[
            "Total",
            "Core",
            "Functionality",
            "Regression",
            "Errors",
        ],
    )

    test_types = ["core", "functionality", "regression", "error"]
    variation_info = analyze_model_variations(df)
    tracker = LegendGroupTracker(
        context.color_map, context.base_color_map, variation_info
    )

    # Sort runs according to the new logic
    sorted_unique_runs = (
        df[
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
        run_df = df[df["display_name"] == display_name]
        info = tracker.get_info(display_name, run_df.iloc[0])

        total_pass_rate = (
            run_df["passed_tests"] / run_df["total_tests"]
        ).mean() * 100

        fig.add_trace(
            go.Bar(
                y=[total_pass_rate],
                name=info.variant,
                legendgroup=info.model_name,
                legendgrouptitle_text=info.group_title,
                legendgrouptitle_font={"color": info.model_base_color},
                marker={"color": info.color},
                text=[f"{total_pass_rate:.1f}"],
                textposition="inside",
                textangle=0,
                showlegend=True,
            ),
            row=1,
            col=1,
        )

        layout_map = {
            "core": (1, 2),
            "functionality": (1, 3),
            "regression": (2, 1),
            "error": (2, 2),
        }

        for test_type in test_types:
            r, c = layout_map[test_type]
            passed_col = f"{test_type}_passed"
            total_col = f"{test_type}_total"

            if passed_col in run_df.columns and total_col in run_df.columns:
                passed = run_df[passed_col].fillna(0)
                total = run_df[total_col]
                avg_pass_rate = (passed / total).mean() * 100
            else:
                avg_pass_rate = 0

            fig.add_trace(
                go.Bar(
                    y=[avg_pass_rate],
                    name=info.variant,
                    legendgroup=info.model_name,
                    marker={"color": info.color},
                    text=[f"{avg_pass_rate:.1f}"],
                    textposition="inside",
                    textangle=0,
                    showlegend=False,
                ),
                row=r,
                col=c,
            )

    fig.update_yaxes(
        title_text="Avg Pass %", row=1, col=1, gridcolor="lightgray"
    )
    for r in [1, 2]:
        for c in [1, 2, 3]:
            if r == 2 and c == 3:
                continue
            fig.update_yaxes(row=r, col=c, gridcolor="lightgray")

    fig.update_yaxes(
        title_text="Total Errors", row=2, col=2, gridcolor="lightgray"
    )

    for r in [1, 2]:
        for c in [1, 2, 3]:
            if r == 2 and c == 3:
                continue
            fig.update_xaxes(row=r, col=c, showticklabels=False)

    for annotation in fig.layout.annotations:
        annotation.y = annotation.y + 0.05

    fig.update_layout(
        **get_base_layout(None, 800, 1.0, "Mean % Tests Passed by Checkpoint")
    )
    fig.update_layout(legend=GROUPED_VERTICAL_LEGEND)
    return fig
