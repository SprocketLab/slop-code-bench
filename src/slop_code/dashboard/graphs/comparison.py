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
        rows=4,
        cols=4,
        subplot_titles=(
            "LOC",
            "Lint Errors",
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
            "Mass: CC",
            "Δ LOC (%)",
            "Δ Churn Ratio",
            "CC Concentration",
        ),
        shared_xaxes=True,
        vertical_spacing=0.06,
    )

    variation_info = analyze_model_variations(context.run_summaries)
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

        # Use first row for legend info
        info = tracker.get_info(display_name, run_df.iloc[0])

        is_grouped = context.group_runs

        # Pre-calculate derived metrics
        # Total Rubric Flags
        run_df = run_df.copy()
        if "rubric_total_flags" in run_df.columns:
            run_df["_total_flags"] = run_df["rubric_total_flags"].fillna(0)
        else:
            run_df["_total_flags"] = 0

        # New Rubric Flags
        total_flags = run_df.get(
            "rubric_total_flags", pd.Series([0] * len(run_df))
        ).fillna(0)
        carried_over = run_df.get(
            "rubric_carried_over", pd.Series([0] * len(run_df))
        ).fillna(0)
        run_df["_new_flags"] = total_flags - carried_over

        # Test Pass Rates
        def add_pass_rate_col(prefix):
            p_col = f"{prefix}_passed"
            t_col = f"{prefix}_total"

            if p_col in run_df.columns:
                passed = run_df[p_col].fillna(0)
            else:
                passed = 0

            if t_col in run_df.columns:
                total = run_df[t_col].fillna(1).replace(0, 1)
            else:
                total = 1

            run_df[f"_pr_{prefix}"] = (passed / total) * 100

        run_df["_pr_all"] = (
            run_df["passed_tests"] / run_df["total_tests"].replace(0, 1)
        ) * 100
        add_pass_rate_col("core")
        add_pass_rate_col("functionality")
        add_pass_rate_col("regression")
        add_pass_rate_col("error")

        zeroes = pd.Series([0.0] * len(run_df), index=run_df.index)
        run_df["_mass_cc"] = run_df.get("mass.cc", zeroes)
        run_df["_delta_loc"] = run_df.get("delta.loc", zeroes)
        run_df["_delta_churn_ratio"] = run_df.get("delta.churn_ratio", zeroes)
        run_df["_cc_concentration"] = run_df.get("cc_concentration", zeroes)

        # Helper to add trace with potential aggregation
        def add_trace(col, row, col_idx, show_legend=False):
            if is_grouped:
                # Group by checkpoint (idx)
                stats = (
                    run_df.groupby(sort_col)[col]
                    .agg(["mean", "std"])
                    .reset_index()
                )
                x = stats[sort_col]
                y = stats["mean"]
                error_y = dict(type="data", array=stats["std"], visible=True)
            else:
                x = run_df[sort_col]
                y = run_df[col]
                error_y = None

            fig.add_trace(
                go.Scatter(
                    x=x,
                    y=y,
                    error_y=error_y,
                    mode="lines+markers",
                    name=info.variant,
                    legendgroup=info.model_name,
                    legendgrouptitle_text=info.group_title
                    if show_legend
                    else None,
                    legendgrouptitle_font={"color": info.model_base_color}
                    if show_legend
                    else None,
                    line=dict(color=info.color),
                    showlegend=show_legend,
                ),
                row=row,
                col=col_idx,
            )

        # Row 1
        add_trace("loc", 1, 1, show_legend=True)
        add_trace("lint_errors", 1, 2)
        add_trace("cc_high_count", 1, 3)
        add_trace("_total_flags", 1, 4)

        # Row 2
        add_trace("_new_flags", 2, 1)
        add_trace("output", 2, 2)
        add_trace("cost", 2, 3)
        add_trace("_pr_all", 2, 4)

        # Row 3
        add_trace("_pr_core", 3, 1)
        add_trace("_pr_functionality", 3, 2)
        add_trace("_pr_regression", 3, 3)
        add_trace("_pr_error", 3, 4)

        # Row 4
        add_trace("_mass_cc", 4, 1)
        add_trace("_delta_loc", 4, 2)
        add_trace("_delta_churn_ratio", 4, 3)
        add_trace("_cc_concentration", 4, 4)

    # Update y-axes titles
    fig.update_yaxes(title_text="Lines", row=1, col=1, gridcolor="lightgray")
    fig.update_yaxes(title_text="Errors", row=1, col=2, gridcolor="lightgray")
    fig.update_yaxes(title_text="Count", row=1, col=3, gridcolor="lightgray")
    fig.update_yaxes(title_text="Flags", row=1, col=4, gridcolor="lightgray")
    fig.update_yaxes(
        title_text="New Flags", row=2, col=1, gridcolor="lightgray"
    )
    fig.update_yaxes(title_text="Tokens", row=2, col=2, gridcolor="lightgray")
    fig.update_yaxes(title_text="Cost ($)", row=2, col=3, gridcolor="lightgray")
    fig.update_yaxes(
        title_text="%", row=2, col=4, gridcolor="lightgray", range=[0, 105]
    )

    for col in range(1, 5):
        fig.update_yaxes(
            title_text="%",
            row=3,
            col=col,
            gridcolor="lightgray",
            range=[0, 105],
        )
    fig.update_yaxes(title_text="Mass", row=4, col=1, gridcolor="lightgray")
    fig.update_yaxes(title_text="%", row=4, col=2, gridcolor="lightgray")
    fig.update_yaxes(title_text="Ratio", row=4, col=3, gridcolor="lightgray")
    fig.update_yaxes(
        title_text="Ratio", row=4, col=4, gridcolor="lightgray", range=[0, 1]
    )

    # Update x-axes titles (only bottom row needs labels)
    for col in range(1, 5):
        fig.update_xaxes(
            title_text="Checkpoint", row=4, col=col, gridcolor="lightgray"
        )

    fig.update_layout(**get_base_layout(None, 1100, 1.0, f"Problem: {problem}"))
    fig.update_layout(legend=GROUPED_VERTICAL_LEGEND)

    return fig
