"""Erosion-focused graphs for analyzing code quality degradation patterns.

Key erosion indicators:
- Mass concentration: Is added mass going to few functions or spread out?
- High CC trajectory: Is the % of mass in complex functions growing?
- Modification vs sprawl: Are they refactoring or just adding new code?
- Churn efficiency: How much code change per unit of progress?
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from slop_code.dashboard.data import ChartContext
from slop_code.dashboard.data import analyze_model_variations
from slop_code.dashboard.graphs.common import GROUPED_VERTICAL_LEGEND
from slop_code.dashboard.graphs.common import LegendGroupTracker
from slop_code.dashboard.graphs.common import get_base_layout


def _get_delta_df(context: ChartContext):
    """Filter to checkpoints with delta columns (idx > 1)."""
    df = context.checkpoints
    if df.empty:
        return None

    # Delta columns only exist for checkpoint 2+
    if "idx" in df.columns:
        df = df[df["idx"] > 1].copy()
    else:
        return None

    if df.empty:
        return None

    return df


def _compute_erosion_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """Compute derived erosion metrics from raw data."""
    df = df.copy()

    # Mass concentration ratio: what fraction of functions hold 90% of added mass?
    # Lower = more concentrated = worse
    added_count_col = "delta.mass.complexity_added_count"
    top90_count_col = "delta.mass.complexity_added_top90_count"
    if added_count_col in df.columns and top90_count_col in df.columns:
        df["top90_ratio"] = df[top90_count_col] / df[added_count_col].replace(
            0, np.nan
        )
    else:
        df["top90_ratio"] = np.nan

    # Modification ratio: modified / (added + modified)
    # Higher = more refactoring vs sprawl
    if (
        "delta.symbols_modified" in df.columns
        and "delta.symbols_added" in df.columns
    ):
        total_changes = df["delta.symbols_modified"] + df["delta.symbols_added"]
        df["modification_ratio"] = df[
            "delta.symbols_modified"
        ] / total_changes.replace(0, np.nan)
    else:
        df["modification_ratio"] = np.nan

    return df


def _prepare_erosion_data(context: ChartContext):
    """Prepare data for erosion graphs."""
    delta_df = _get_delta_df(context)
    if delta_df is None:
        return None, None, None

    delta_df = _compute_erosion_metrics(delta_df)

    variation_info = analyze_model_variations(delta_df)
    tracker = LegendGroupTracker(
        context.color_map, context.base_color_map, variation_info
    )

    # Sort runs consistently
    sorted_unique_runs = (
        delta_df[
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

    return delta_df, sorted_unique_runs, tracker


def build_mass_delta_bars(context: ChartContext) -> go.Figure:
    """Build bar chart showing where mass is going.

    Metrics:
    - Top90 Ratio: top90_count / added_count (higher = spread, lower = concentrated)
    - Added Concentration (Gini): inequality of added mass distribution
    - Δ Top90 Mass: how much mass is going to the top 90% tier
    """
    delta_df, sorted_unique_runs, tracker = _prepare_erosion_data(context)
    if delta_df is None:
        return go.Figure()

    num_runs = len(sorted_unique_runs)
    use_horizontal = num_runs > 8

    fig = make_subplots(
        rows=1 if not use_horizontal else 3,
        cols=3 if not use_horizontal else 1,
        subplot_titles=[
            "Top90 Ratio (higher=spread)",
            "Added Concentration (Gini)",
            "Δ Top90 Mass (mean)",
        ],
        horizontal_spacing=0.12 if not use_horizontal else 0.05,
        vertical_spacing=0.15 if use_horizontal else 0.08,
    )

    for display_name in sorted_unique_runs["display_name"]:
        run_df = delta_df[delta_df["display_name"] == display_name]
        info = tracker.get_info(display_name, run_df.iloc[0])

        # Top90 ratio (how spread is added mass)
        mean_top90_ratio = run_df["top90_ratio"].mean()
        if pd.isna(mean_top90_ratio):
            mean_top90_ratio = 0

        # Added concentration (Gini)
        conc_col = "delta.mass.complexity_added_concentration"
        mean_concentration = (
            run_df[conc_col].mean() if conc_col in run_df.columns else 0
        )

        # Delta top90 mass
        top90_mass_col = "delta.mass.top90_mass"
        mean_top90_mass = (
            run_df[top90_mass_col].mean()
            if top90_mass_col in run_df.columns
            else 0
        )

        bar_kwargs = {
            "name": info.variant,
            "legendgroup": info.model_name,
            "legendgrouptitle_text": info.group_title,
            "legendgrouptitle_font": {"color": info.model_base_color},
            "marker": {"color": info.color},
            "showlegend": True,
        }

        if use_horizontal:
            fig.add_trace(
                go.Bar(
                    x=[mean_top90_ratio],
                    y=[info.variant],
                    orientation="h",
                    text=[f"{mean_top90_ratio:.2f}"],
                    textposition="outside",
                    **bar_kwargs,
                ),
                row=1,
                col=1,
            )
            fig.add_trace(
                go.Bar(
                    x=[mean_concentration],
                    y=[info.variant],
                    orientation="h",
                    text=[f"{mean_concentration:.2f}"],
                    textposition="outside",
                    **{**bar_kwargs, "showlegend": False},
                ),
                row=2,
                col=1,
            )
            fig.add_trace(
                go.Bar(
                    x=[mean_top90_mass],
                    y=[info.variant],
                    orientation="h",
                    text=[f"{mean_top90_mass:.1f}"],
                    textposition="outside",
                    **{**bar_kwargs, "showlegend": False},
                ),
                row=3,
                col=1,
            )
        else:
            fig.add_trace(
                go.Bar(
                    y=[mean_top90_ratio],
                    text=[f"{mean_top90_ratio:.2f}"],
                    textposition="outside",
                    **bar_kwargs,
                ),
                row=1,
                col=1,
            )
            fig.add_trace(
                go.Bar(
                    y=[mean_concentration],
                    text=[f"{mean_concentration:.2f}"],
                    textposition="outside",
                    **{**bar_kwargs, "showlegend": False},
                ),
                row=1,
                col=2,
            )
            fig.add_trace(
                go.Bar(
                    y=[mean_top90_mass],
                    text=[f"{mean_top90_mass:.1f}"],
                    textposition="outside",
                    **{**bar_kwargs, "showlegend": False},
                ),
                row=1,
                col=3,
            )

    if use_horizontal:
        fig.update_xaxes(
            title_text="Ratio (0-1)",
            row=1,
            col=1,
            gridcolor="lightgray",
            range=[0, 1],
        )
        fig.update_xaxes(
            title_text="Gini (0-1)",
            row=2,
            col=1,
            gridcolor="lightgray",
            range=[0, 1],
        )
        fig.update_xaxes(title_text="Mass", row=3, col=1, gridcolor="lightgray")
        for r in [1, 2, 3]:
            fig.update_yaxes(row=r, col=1, showticklabels=False)
        fig_height = max(500, num_runs * 25 + 150)
    else:
        fig.update_yaxes(
            title_text="Ratio",
            row=1,
            col=1,
            gridcolor="lightgray",
            range=[0, 1],
        )
        fig.update_yaxes(
            title_text="Gini", row=1, col=2, gridcolor="lightgray", range=[0, 1]
        )
        fig.update_yaxes(title_text="Mass", row=1, col=3, gridcolor="lightgray")
        for i in range(1, 4):
            fig.update_xaxes(row=1, col=i, showticklabels=False)
        fig_height = 400

    fig.update_layout(
        **get_base_layout(None, fig_height, 1.0, "Mass Distribution Overview")
    )
    fig.update_layout(legend=GROUPED_VERTICAL_LEGEND)
    return fig


def build_mass_delta_heatmap(context: ChartContext) -> go.Figure:
    """Build heatmap of high_cc_pct per run × problem.

    Shows what % of mass is in high-complexity functions.
    Higher = worse (more mass in complex code).
    """
    df = context.checkpoints
    if df.empty:
        return go.Figure()

    high_cc_col = "mass.high_cc_pct"
    if high_cc_col not in df.columns:
        return go.Figure()

    # Use the LAST checkpoint's high_cc_pct per problem (final state)
    last_checkpoints = df.loc[
        df.groupby(["display_name", "problem"])["idx"].idxmax()
    ]

    heatmap_data = last_checkpoints[
        ["display_name", "problem", high_cc_col]
    ].copy()

    # Pivot to matrix form
    pivot_df = heatmap_data.pivot(
        index="display_name", columns="problem", values=high_cc_col
    )

    # Sort
    pivot_df = pivot_df.sort_index(axis=0).sort_index(axis=1)

    z_data = pivot_df.values
    x_labels = pivot_df.columns.tolist()
    y_labels = pivot_df.index.tolist()

    fig_height = max(300, len(y_labels) * 25 + 100)
    fig = go.Figure(
        data=go.Heatmap(
            z=z_data,
            x=x_labels,
            y=y_labels,
            colorscale=[
                [0.0, "#2e8540"],  # Green (low = good)
                [0.5, "#fff3cd"],  # Yellow
                [1.0, "#d62728"],  # Red (high = bad)
            ],
            zmin=0,
            zmax=100,
            hovertemplate=(
                "<b>Run:</b> %{y}<br>"
                "<b>Problem:</b> %{x}<br>"
                "<b>High CC %:</b> %{z:.1f}%"
                "<extra></extra>"
            ),
            showscale=True,
            colorbar={"title": "High CC %"},
            xgap=2,
            ygap=2,
        )
    )

    fig.update_layout(
        **get_base_layout(
            None, fig_height, 1.0, "Mass in High-Complexity Functions (%)"
        )
    )

    fig.update_xaxes(
        showticklabels=False,
        ticks="",
        title_text="Problems (hover for details)",
        side="bottom",
    )
    fig.update_yaxes(
        title_text="",
        autorange="reversed",
    )

    return fig


def build_delta_vs_solve_scatter(context: ChartContext) -> go.Figure:
    """Build scatter plot of mass concentration vs solve rate.

    X-axis: Mean added concentration (Gini) - how concentrated is added mass
    Y-axis: Solve rate

    Lower concentration + high solve = good (spread mass, solving problems)
    High concentration + low solve = bad (mass piling up, not solving)
    """
    delta_df = _get_delta_df(context)
    run_summaries = context.run_summaries

    if delta_df is None or run_summaries.empty:
        return go.Figure()

    conc_col = "delta.mass.complexity_added_concentration"
    if conc_col not in delta_df.columns:
        return go.Figure()

    # Compute mean concentration per run
    run_metrics = (
        delta_df.groupby("display_name")[conc_col]
        .mean()
        .reset_index()
        .rename(columns={conc_col: "mean_concentration"})
    )

    # Join with run summaries for solve rate
    merged = run_metrics.merge(
        run_summaries[["display_name", "pct_checkpoints_solved", "model_name"]],
        on="display_name",
        how="inner",
    )

    if merged.empty:
        return go.Figure()

    fig = go.Figure()
    seen_models: set[str] = set()

    for _, row in merged.iterrows():
        display_name = row["display_name"]
        model_name = row["model_name"]
        is_first_for_model = model_name not in seen_models

        if is_first_for_model:
            seen_models.add(model_name)

        color = context.base_color_map.get(display_name, "#888")

        fig.add_trace(
            go.Scatter(
                x=[row["mean_concentration"]],
                y=[row["pct_checkpoints_solved"]],
                mode="markers",
                name=f"<b>{model_name}</b>",
                legendgroup=model_name,
                marker={"color": color, "size": 12},
                showlegend=is_first_for_model,
                hovertemplate=(
                    f"<b>{display_name}</b><br>"
                    "Concentration: %{x:.2f}<br>"
                    "Solved: %{y:.1f}%<extra></extra>"
                ),
            )
        )

    fig.update_layout(
        **get_base_layout(None, 400, 1.0, "Mass Concentration vs Solve Rate")
    )
    fig.update_layout(legend=GROUPED_VERTICAL_LEGEND)
    fig.update_xaxes(
        title_text="Mean Added Concentration (Gini)",
        gridcolor="lightgray",
    )
    fig.update_yaxes(title_text="Checkpoints Solved (%)", gridcolor="lightgray")

    return fig


def build_mass_delta_boxplots(context: ChartContext) -> go.Figure:
    """Build box plots showing mass distribution metrics per run.

    Metrics showing where mass is going:
    - Top90 Ratio: spread of added mass (top90_count / added_count)
    - Added Concentration: Gini coefficient of added mass
    - Δ Top90 Mass: change in top 90% tier mass
    - High CC %: % of mass in high-complexity functions
    - Δ Top75 Mass: change in top 75% tier mass
    - Δ Top50 Mass: change in top 50% tier mass
    """
    delta_df, sorted_unique_runs, tracker = _prepare_erosion_data(context)
    if delta_df is None:
        return go.Figure()

    # Get full df for high_cc_pct
    full_df = context.checkpoints
    if "mass.high_cc_pct" in full_df.columns:
        # Merge high_cc_pct from full df
        high_cc_data = full_df[
            ["display_name", "problem", "idx", "mass.high_cc_pct"]
        ].copy()
        delta_df = delta_df.merge(
            high_cc_data,
            on=["display_name", "problem", "idx"],
            how="left",
            suffixes=("", "_dup"),
        )

    # Replace inf values with NaN
    delta_df = delta_df.replace([float("inf"), float("-inf")], np.nan)

    fig = make_subplots(
        rows=2,
        cols=3,
        vertical_spacing=0.12,
        horizontal_spacing=0.06,
        subplot_titles=[
            "Top90 Ratio",
            "Added Concentration",
            "Δ Top90 Mass",
            "High CC %",
            "Δ Top75 Mass",
            "Δ Top50 Mass",
        ],
    )

    metrics = [
        ("top90_ratio", 1, 1),
        ("delta.mass.complexity_added_concentration", 1, 2),
        ("delta.mass.top90_mass", 1, 3),
        ("mass.high_cc_pct", 2, 1),
        ("delta.mass.top75_mass", 2, 2),
        ("delta.mass.top50_mass", 2, 3),
    ]

    for display_name in sorted_unique_runs["display_name"]:
        run_df = delta_df[delta_df["display_name"] == display_name]
        info = tracker.get_info(display_name, run_df.iloc[0])

        for metric, r, c in metrics:
            if metric not in run_df.columns:
                continue

            values = run_df[metric].dropna()
            if values.empty:
                continue

            show_legend = r == 1 and c == 1

            fig.add_trace(
                go.Box(
                    x=[info.variant] * len(values),
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

    # Update axes
    fig.update_yaxes(
        title_text="Ratio", row=1, col=1, gridcolor="lightgray", range=[0, 1]
    )
    fig.update_yaxes(
        title_text="Gini", row=1, col=2, gridcolor="lightgray", range=[0, 1]
    )
    fig.update_yaxes(title_text="Mass", row=1, col=3, gridcolor="lightgray")
    fig.update_yaxes(
        title_text="%", row=2, col=1, gridcolor="lightgray", range=[0, 100]
    )
    fig.update_yaxes(title_text="Mass", row=2, col=2, gridcolor="lightgray")
    fig.update_yaxes(title_text="Mass", row=2, col=3, gridcolor="lightgray")

    for r in [1, 2]:
        for c in [1, 2, 3]:
            fig.update_xaxes(row=r, col=c, showticklabels=False)

    # Adjust subplot titles
    for annotation in fig.layout.annotations:
        annotation.y = annotation.y + 0.03

    fig.update_layout(
        **get_base_layout(None, 600, 1.0, "Mass Distribution Metrics")
    )
    fig.update_layout(legend=GROUPED_VERTICAL_LEGEND)
    return fig


def build_other_mass_metrics(context: ChartContext) -> go.Figure:
    """Build bar chart showing median % change for mass metrics.

    Shows median relative change (%) for:
    - Branches: control flow branching mass
    - Comparisons: comparison operators mass
    - Vars Used: variables referenced mass
    - Vars Defined: variables declared mass
    - Try Scaffold: exception handling mass
    - Complexity: overall complexity mass
    """
    delta_df, sorted_unique_runs, tracker = _prepare_erosion_data(context)
    if delta_df is None:
        return go.Figure()

    # Compute relative changes: delta / previous_value * 100
    # previous_value = current - delta
    metrics_info = [
        ("branches", "Branches"),
        ("comparisons", "Comparisons"),
        ("vars_used", "Vars Used"),
        ("vars_defined", "Vars Defined"),
        ("try_scaffold", "Try Scaffold"),
        ("complexity", "Complexity"),
    ]

    for metric, _ in metrics_info:
        mass_col = f"mass.{metric}"
        delta_col = f"delta.mass.{metric}"
        rel_col = f"rel.mass.{metric}"

        if mass_col in delta_df.columns and delta_col in delta_df.columns:
            # Previous value = current - delta
            prev_value = delta_df[mass_col] - delta_df[delta_col]
            # Relative change as percentage, avoid division by zero
            delta_df[rel_col] = (
                delta_df[delta_col] / prev_value.replace(0, np.nan) * 100
            )

    # Replace inf values with NaN and clip extreme outliers for display
    delta_df = delta_df.replace([float("inf"), float("-inf")], np.nan)

    num_runs = len(sorted_unique_runs)
    use_horizontal = num_runs > 8

    fig = make_subplots(
        rows=2 if not use_horizontal else 6,
        cols=3 if not use_horizontal else 1,
        subplot_titles=[label for _, label in metrics_info],
        horizontal_spacing=0.10 if not use_horizontal else 0.05,
        vertical_spacing=0.15 if use_horizontal else 0.12,
    )

    for display_name in sorted_unique_runs["display_name"]:
        run_df = delta_df[delta_df["display_name"] == display_name]
        info = tracker.get_info(display_name, run_df.iloc[0])

        for idx, (metric, _) in enumerate(metrics_info):
            rel_col = f"rel.mass.{metric}"
            if rel_col not in run_df.columns:
                continue

            values = run_df[rel_col].dropna()
            median_val = 0 if values.empty else values.median()

            show_legend = idx == 0
            if use_horizontal:
                row = idx + 1
                col = 1
            else:
                row = idx // 3 + 1
                col = idx % 3 + 1

            bar_kwargs = {
                "name": info.variant,
                "legendgroup": info.model_name,
                "legendgrouptitle_text": info.group_title
                if show_legend
                else None,
                "legendgrouptitle_font": {"color": info.model_base_color},
                "marker": {"color": info.color},
                "showlegend": show_legend,
            }

            if use_horizontal:
                fig.add_trace(
                    go.Bar(
                        x=[median_val],
                        y=[info.variant],
                        orientation="h",
                        text=[f"{median_val:.0f}%"],
                        textposition="outside",
                        **bar_kwargs,
                    ),
                    row=row,
                    col=col,
                )
            else:
                fig.add_trace(
                    go.Bar(
                        y=[median_val],
                        text=[f"{median_val:.0f}%"],
                        textposition="outside",
                        **bar_kwargs,
                    ),
                    row=row,
                    col=col,
                )

    # Add zero reference lines and update axes
    if use_horizontal:
        for r in range(1, 7):
            fig.add_vline(
                x=0,
                line={"color": "#999", "width": 1, "dash": "dash"},
                row=r,
                col=1,
            )
            fig.update_xaxes(
                title_text="Median % Δ", row=r, col=1, gridcolor="lightgray"
            )
            fig.update_yaxes(row=r, col=1, showticklabels=False)
        fig_height = max(600, num_runs * 20 + 200)
    else:
        for r in range(1, 3):
            for c in range(1, 4):
                fig.add_hline(
                    y=0,
                    line={"color": "#999", "width": 1, "dash": "dash"},
                    row=r,
                    col=c,
                )
                fig.update_yaxes(
                    title_text="% Δ" if c == 1 else "",
                    row=r,
                    col=c,
                    gridcolor="lightgray",
                )
                fig.update_xaxes(row=r, col=c, showticklabels=False)
        fig_height = 450

    fig.update_layout(
        **get_base_layout(
            None, fig_height, 1.0, "Mass Metrics (Median % Change)"
        )
    )
    fig.update_layout(legend=GROUPED_VERTICAL_LEGEND)
    return fig


def build_velocity_metrics(context: ChartContext) -> go.Figure:
    """Build horizontal bar chart showing velocity metrics.

    Metrics:
    - Mean Δ Mass: average mass.complexity added per checkpoint
    - Mean Lines Added: average lines added per checkpoint
    - Mean Lines Removed: average lines removed per checkpoint
    """
    delta_df, sorted_unique_runs, tracker = _prepare_erosion_data(context)
    if delta_df is None:
        return go.Figure()

    num_runs = len(sorted_unique_runs)

    fig = make_subplots(
        rows=1,
        cols=3,
        subplot_titles=[
            "Mean Δ Mass",
            "Mean Lines Added",
            "Mean Lines Removed",
        ],
        horizontal_spacing=0.08,
    )

    for display_name in sorted_unique_runs["display_name"]:
        run_df = delta_df[delta_df["display_name"] == display_name]
        info = tracker.get_info(display_name, run_df.iloc[0])

        # Mean delta mass per checkpoint
        delta_mass_col = "delta.mass.complexity"
        mean_delta_mass = (
            run_df[delta_mass_col].mean()
            if delta_mass_col in run_df.columns
            else 0
        )

        # Mean lines added per checkpoint
        lines_added_col = "lines_added"
        mean_lines_added = (
            run_df[lines_added_col].mean()
            if lines_added_col in run_df.columns
            else 0
        )

        # Mean lines removed per checkpoint
        lines_removed_col = "lines_removed"
        mean_lines_removed = (
            run_df[lines_removed_col].mean()
            if lines_removed_col in run_df.columns
            else 0
        )

        bar_kwargs = {
            "name": info.variant,
            "legendgroup": info.model_name,
            "legendgrouptitle_text": info.group_title,
            "legendgrouptitle_font": {"color": info.model_base_color},
            "marker": {"color": info.color},
        }

        fig.add_trace(
            go.Bar(
                x=[mean_delta_mass],
                y=[info.variant],
                orientation="h",
                text=[f"{mean_delta_mass:.0f}"],
                textposition="outside",
                showlegend=True,
                **bar_kwargs,
            ),
            row=1,
            col=1,
        )
        fig.add_trace(
            go.Bar(
                x=[mean_lines_added],
                y=[info.variant],
                orientation="h",
                text=[f"{mean_lines_added:.0f}"],
                textposition="outside",
                showlegend=False,
                **bar_kwargs,
            ),
            row=1,
            col=2,
        )
        fig.add_trace(
            go.Bar(
                x=[mean_lines_removed],
                y=[info.variant],
                orientation="h",
                text=[f"{mean_lines_removed:.0f}"],
                textposition="outside",
                showlegend=False,
                **bar_kwargs,
            ),
            row=1,
            col=3,
        )

    fig.update_xaxes(title_text="Mass", row=1, col=1, gridcolor="lightgray")
    fig.update_xaxes(title_text="Lines", row=1, col=2, gridcolor="lightgray")
    fig.update_xaxes(title_text="Lines", row=1, col=3, gridcolor="lightgray")
    for c in [1, 2, 3]:
        fig.update_yaxes(row=1, col=c, showticklabels=False)

    fig_height = max(300, num_runs * 30 + 100)
    fig.update_layout(
        **get_base_layout(None, fig_height, 1.0, "Velocity Metrics")
    )
    fig.update_layout(legend=GROUPED_VERTICAL_LEGEND)
    return fig


def build_symbol_sprawl(context: ChartContext) -> go.Figure:
    """Build horizontal bar visualization of symbol sprawl vs refactoring.

    Shows ratio of symbols_added to symbols_modified.
    High added / low modified = sprawl (just adding new code)
    Low added / high modified = refactoring (improving existing code)
    """
    delta_df = _get_delta_df(context)
    if delta_df is None:
        return go.Figure()

    added_col = "delta.symbols_added"
    modified_col = "delta.symbols_modified"

    if (
        added_col not in delta_df.columns
        or modified_col not in delta_df.columns
    ):
        return go.Figure()

    variation_info = analyze_model_variations(delta_df)
    tracker = LegendGroupTracker(
        context.color_map, context.base_color_map, variation_info
    )

    # Sort runs consistently
    sorted_unique_runs = (
        delta_df[
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

    num_runs = len(sorted_unique_runs)

    fig = make_subplots(
        rows=1,
        cols=2,
        subplot_titles=["Symbols Added (mean)", "Symbols Modified (mean)"],
        horizontal_spacing=0.12,
    )

    for display_name in sorted_unique_runs["display_name"]:
        run_df = delta_df[delta_df["display_name"] == display_name]
        info = tracker.get_info(display_name, run_df.iloc[0])

        mean_added = run_df[added_col].mean()
        mean_modified = run_df[modified_col].mean()

        bar_kwargs = {
            "name": info.variant,
            "legendgroup": info.model_name,
            "legendgrouptitle_text": info.group_title,
            "legendgrouptitle_font": {"color": info.model_base_color},
            "marker": {"color": info.color},
        }

        fig.add_trace(
            go.Bar(
                x=[mean_added],
                y=[info.variant],
                orientation="h",
                text=[f"{mean_added:.1f}"],
                textposition="outside",
                showlegend=True,
                **bar_kwargs,
            ),
            row=1,
            col=1,
        )
        fig.add_trace(
            go.Bar(
                x=[mean_modified],
                y=[info.variant],
                orientation="h",
                text=[f"{mean_modified:.1f}"],
                textposition="outside",
                showlegend=False,
                **bar_kwargs,
            ),
            row=1,
            col=2,
        )

    fig.update_xaxes(title_text="Count", row=1, col=1, gridcolor="lightgray")
    fig.update_xaxes(title_text="Count", row=1, col=2, gridcolor="lightgray")
    fig.update_yaxes(row=1, col=1, showticklabels=False)
    fig.update_yaxes(row=1, col=2, showticklabels=False)

    fig_height = max(300, num_runs * 30 + 100)
    fig.update_layout(
        **get_base_layout(None, fig_height, 1.0, "Symbol Sprawl vs Refactoring")
    )
    fig.update_layout(legend=GROUPED_VERTICAL_LEGEND)
    return fig
