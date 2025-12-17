from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from slop_code.dashboard.data import ChartContext
from slop_code.dashboard.data import analyze_model_variations
from slop_code.dashboard.graphs.common import GROUPED_VERTICAL_LEGEND
from slop_code.dashboard.graphs.common import LegendGroupTracker
from slop_code.dashboard.graphs.common import get_base_layout


def build_problem_comparison_chart(
    context: ChartContext, problem: str
) -> go.Figure:
    df = context.checkpoints

    if (
        df.empty
        or "problem" not in df.columns
        or problem not in df["problem"].values
    ):
        return go.Figure()

    df = df[df["problem"] == problem]

    # Ensure correct sorting by checkpoint index
    sort_col = "idx" if "idx" in df.columns else "checkpoint"
    df = df.sort_values(sort_col)

    fig = make_subplots(
        rows=5,
        cols=3,
        subplot_titles=(
            "LOC",
            "Lint Errors",
            "AST-grep Violations",
            "High Complexity",
            "Total Rubric Flags",
            "New Rubric Flags",
            "Output Tokens",
            "Cost ($)",
            "Pass Rate: Total (%)",
            "Pass Rate: Core (%)",
            "Pass Rate: Functionality (%)",
            "Pass Rate: Regression (%)",
            "Pass Rate: Error (%)",
        ),
        shared_xaxes=True,
        vertical_spacing=0.06,
    )

    variation_info = analyze_model_variations(context.run_summaries)
    tracker = LegendGroupTracker(context.color_map, variation_info)

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

        # Use first row for legend info
        info = tracker.get_info(display_name, run_df.iloc[0])

        x_vals = run_df[sort_col]

        # Pre-calculate derived metrics
        # New Rubric Flags
        total_flags = run_df.get(
            "rubric_total_flags", pd.Series([0] * len(run_df))
        ).fillna(0)
        carried_over = run_df.get(
            "rubric.carried_over", pd.Series([0] * len(run_df))
        ).fillna(0)
        new_flags = total_flags - carried_over

        # Complexity
        complexity = run_df["cc_high_count"]

        # Helper for test pass rates
        def calc_pass_rate(prefix):
            passed = run_df.get(
                f"{prefix}_passed", pd.Series([0] * len(run_df))
            ).fillna(0)
            total = run_df.get(
                f"{prefix}_total", pd.Series([1] * len(run_df))
            ).fillna(1)
            total = total.replace(0, 1)
            return (passed / total) * 100

        # Test Pass Rates
        pass_rate_total = (run_df["passed_tests"] / run_df["total_tests"]) * 100
        pass_rate_total = calc_pass_rate("total")
        pass_rate_core = calc_pass_rate("core")
        pass_rate_func = calc_pass_rate("functionality")
        pass_rate_regr = calc_pass_rate("regression")
        pass_rate_error = calc_pass_rate("error")

        # Output Tokens
        output_tokens = run_df.get(
            "output", pd.Series([0] * len(run_df))
        ).fillna(0)

        # Cost
        costs = run_df.get("cost", pd.Series([0] * len(run_df))).fillna(0)

        # Helper to add trace
        def add_trace(y_data, row, col, show_legend=False):
            fig.add_trace(
                go.Scatter(
                    x=x_vals,
                    y=y_data,
                    mode="lines+markers",
                    name=info.variant,
                    legendgroup=info.model_name,
                    legendgrouptitle_text=info.group_title
                    if show_legend
                    else None,
                    legendgrouptitle_font={"color": info.model_base_color},
                    line=dict(color=info.color),
                    showlegend=show_legend,
                ),
                row=row,
                col=col,
            )

        # Row 1
        add_trace(
            run_df.get("loc", pd.Series([0] * len(run_df))).fillna(0),
            1,
            1,
            show_legend=True,
        )
        add_trace(
            run_df.get("lint_errors", pd.Series([0] * len(run_df))).fillna(0),
            1,
            2,
        )
        add_trace(
            run_df.get(
                "ast_grep_violations", pd.Series([0] * len(run_df))
            ).fillna(0),
            1,
            3,
        )

        # Row 2
        add_trace(run_df["cc_high_count"], 2, 1)
        add_trace(total_flags, 2, 2)
        add_trace(new_flags, 2, 3)

        # Row 3
        add_trace(output_tokens, 3, 1)
        add_trace(costs, 3, 2)
        add_trace(pass_rate_total, 3, 3)

        # Row 4
        add_trace(pass_rate_core, 4, 1)
        add_trace(pass_rate_func, 4, 2)
        add_trace(pass_rate_regr, 4, 3)

        # Row 5
        add_trace(pass_rate_error, 5, 1)

    # Update y-axes titles
    fig.update_yaxes(title_text="Lines", row=1, col=1, gridcolor="lightgray")
    fig.update_yaxes(title_text="Errors", row=1, col=2, gridcolor="lightgray")
    fig.update_yaxes(
        title_text="Violations", row=1, col=3, gridcolor="lightgray"
    )

    fig.update_yaxes(title_text="Count", row=2, col=1, gridcolor="lightgray")
    fig.update_yaxes(title_text="Flags", row=2, col=2, gridcolor="lightgray")
    fig.update_yaxes(
        title_text="New Flags", row=2, col=3, gridcolor="lightgray"
    )

    fig.update_yaxes(title_text="Tokens", row=3, col=1, gridcolor="lightgray")
    fig.update_yaxes(title_text="Cost ($)", row=3, col=2, gridcolor="lightgray")
    fig.update_yaxes(
        title_text="%", row=3, col=3, gridcolor="lightgray", range=[0, 105]
    )

    for r, c in [(4, 1), (4, 2), (4, 3), (5, 1)]:
        fig.update_yaxes(
            title_text="%", row=r, col=c, gridcolor="lightgray", range=[0, 105]
        )

    # Update x-axes titles (only bottom row needs labels)
    for col in range(1, 4):
        fig.update_xaxes(
            title_text="Checkpoint", row=5, col=col, gridcolor="lightgray"
        )

    fig.update_layout(
        **get_base_layout(
            None, 1400, 1.0, f"Problem: {problem}"
        )  # Increased height for more rows
    )
    fig.update_layout(legend=GROUPED_VERTICAL_LEGEND)

    return fig
