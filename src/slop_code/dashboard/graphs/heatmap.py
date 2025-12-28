from __future__ import annotations

import plotly.graph_objects as go

from slop_code.dashboard.data import ChartContext
from slop_code.dashboard.graphs.common import get_base_layout


def build_pass_rate_heatmap(context: ChartContext) -> go.Figure:
    df = context.checkpoints
    if df.empty:
        return go.Figure()

    # Calculate pass rate per (run, problem)
    # This represents the percentage of checkpoints where all tests passed.
    # Metric = (Number of fully passing checkpoints / Total number of checkpoints) * 100
    def calculate_checkpoint_pass_percentage(group):
        fully_passing_checkpoints = (
            group["passed_tests"] == group["total_tests"]
        ) & (group["total_tests"] > 0)
        return (fully_passing_checkpoints.sum() / len(group)) * 100

    heatmap_data = (
        df.groupby(["display_name", "problem"])
        .apply(calculate_checkpoint_pass_percentage)
        .rename("passed_chkpt")
        .reset_index()
    )

    # Pivot to matrix form: rows=runs, cols=problems
    pivot_df = heatmap_data.pivot(
        index="display_name", columns="problem", values="passed_chkpt"
    )

    # Sort runs (y-axis) consistently with other charts (usually alphabetical)
    # Sort problems (x-axis) alphabetically
    pivot_df = pivot_df.sort_index(axis=0).sort_index(axis=1)

    # Fill NaN with 0 (unattempted problems assumed 0% pass)
    pivot_df = pivot_df.fillna(0)

    # Prepare data for Plotly
    z_data = pivot_df.values
    x_labels = pivot_df.columns.tolist()
    y_labels = pivot_df.index.tolist()

    # Height calculation: 20px per run + 100px buffer, minimum 300px
    fig_height = max(300, len(y_labels) * 20 + 100)
    fig = go.Figure(
        data=go.Heatmap(
            z=z_data,
            x=x_labels,
            y=y_labels,
            colorscale=[
                [0.0, "#ebedf0"],  # Grey for 0%
                [1.0, "#40c463"],  # Light green for 100%
            ],
            zmin=0,
            zmax=100,
            hovertemplate=(
                "<b>Run:</b> %{y}<br>"
                "<b>Problem:</b> %{x}<br>"
                "<b>Passed:</b> %{z:.1f}%"
                "<extra></extra>"
            ),
            showscale=True,
            colorbar={"title": "Pass %"},
            xgap=2,  # Small gap between squares like GitHub
            ygap=2,
        )
    )

    fig.update_layout(
        **get_base_layout(None, fig_height, 1.0, "Problem Pass Rate Heatmap")
    )

    fig.update_xaxes(
        showticklabels=False,
        ticks="",
        title_text="Problems (hover for details)",
        side="bottom",
    )
    fig.update_yaxes(
        title_text="",
        autorange="reversed",  # Top-down list of runs
    )

    return fig


def build_single_run_heatmap(context: ChartContext) -> go.Figure:
    """Build a heatmap showing Pass/Fail status for each checkpoint of each problem."""
    df = context.checkpoints
    if df.empty:
        return go.Figure()

    # We expect a single run in context, but if multiple, we'll just take the first one?
    # Or maybe the context builder handles filtering.
    # Ideally, we iterate over (problem, checkpoint_idx)

    # Identify checkpoint identifier
    chkpt_col = "idx" if "idx" in df.columns else "checkpoint"

    # Pivot: Index=problem, Columns=chkpt_col, Values=passed_chkpt
    # passed_chkpt is boolean, convert to int (1=Pass, 0=Fail)
    pivot_df = df.pivot_table(
        index="problem",
        columns=chkpt_col,
        values="checkpoint_pass_rate",
        aggfunc="max",  # If duplicates, taking max (True > False) is safe
    )

    # Sort problems alphabetically
    pivot_df = pivot_df.sort_index(axis=0).sort_index(axis=1)

    z_data = pivot_df.values
    x_labels = pivot_df.columns.tolist()
    y_labels = pivot_df.index.tolist()

    fig_height = max(400, len(y_labels) * 20 + 100)

    import numpy as np

    # Mask nan to use a specific color (grey). We'll use zmin just below 0, e.g., -0.1 or -1.
    masked_z_data = np.where(np.isnan(z_data), -1, z_data)

    fig = go.Figure(
        data=go.Heatmap(
            z=masked_z_data,
            x=x_labels,
            y=y_labels,
            colorscale=[
                [0.0, "#aaaaaa"],  # Grey for NaN (masked as -1)
                [0.0001, "#d62728"],  # Red for Fail (0)
                [0.90, "#ff7575"],  # Pink for Partial (0.9)
                [1.0, "#2ca02c"],  # Green for Pass (1)
            ],
            zmin=-1,
            zmax=1,
            hovertemplate=(
                "<b>Problem:</b> %{y}<br>"
                "<b>Checkpoint:</b> %{x}<br>"
                "<b>Status:</b> %{z}<extra></extra>"
            ),
            showscale=False,
            xgap=1,
            ygap=1,
            zauto=False,
        )
    )

    fig.update_layout(
        **get_base_layout(None, fig_height, 1.0, "Checkpoint Pass/Fail Status")
    )

    fig.update_xaxes(title_text="Checkpoint Index")
    fig.update_yaxes(autorange="reversed")

    return fig
