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

        is_grouped = context.group_runs

        def get_test_stats(passed_col, total_col):
            if passed_col not in run_df.columns or total_col not in run_df.columns:
                return 0, 0
            
            # Calculate pass rate per row (checkpoint)
            rates = (run_df[passed_col] / run_df[total_col].replace(0, 1)) * 100
            
            if is_grouped:
                # If grouped, run_df contains checkpoints from multiple runs.
                # We want the mean of means per run.
                run_means = run_df.groupby("run_path").apply(
                    lambda g: (g[passed_col] / g[total_col].replace(0, 1)).mean() * 100
                )
                return run_means.mean(), run_means.std()
            
            return rates.mean(), 0

        total_pass_rate, total_pass_std = get_test_stats("passed_tests", "total_tests")

        def add_bar(y_val, std_val, r, c, show_legend=False):
            error_y = None
            if is_grouped:
                error_y = dict(type="data", array=[std_val], visible=True)
            
            fig.add_trace(
                go.Bar(
                    y=[y_val],
                    error_y=error_y,
                    name=info.variant,
                    legendgroup=info.model_name,
                    legendgrouptitle_text=info.group_title if show_legend else None,
                    legendgrouptitle_font={"color": info.model_base_color} if show_legend else None,
                    marker={"color": info.color},
                    text=[f"{y_val:.1f}"],
                    textposition="inside",
                    textangle=0,
                    showlegend=show_legend,
                ),
                row=r,
                col=c,
            )

        add_bar(total_pass_rate, total_pass_std, 1, 1, show_legend=True)

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
            
            avg_rate, std_rate = get_test_stats(passed_col, total_col)
            add_bar(avg_rate, std_rate, r, c)

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
