from __future__ import annotations

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from slop_code.dashboard.data import ChartContext
from slop_code.dashboard.data import analyze_model_variations
from slop_code.dashboard.data import get_short_annotation
from slop_code.dashboard.graphs.common import GROUPED_VERTICAL_LEGEND
from slop_code.dashboard.graphs.common import LegendGroupTracker
from slop_code.dashboard.graphs.common import get_base_layout


def _prepare_bar_data(context: ChartContext):
    df = context.run_summaries
    chkpt_df = context.checkpoints

    if df.empty:
        return None, None, None, None

    if context.group_runs:
        # Aggregate run_summaries by display_name
        agg_cols = [
            "pct_checkpoints_solved",
            "pct_checkpoints_iso_solved",
            "pct_problems_partial",
            "costs.total",
        ]

        group_df = df.groupby("display_name").agg(
            {col: ["mean", "std"] for col in agg_cols if col in df.columns}
        )
        # Flatten columns
        group_df.columns = [
            "_".join(col).strip() for col in group_df.columns.values
        ]
        group_df = group_df.reset_index()

        # We still need model_name and _thinking_sort_key for the tracker
        metadata = (
            df.groupby("display_name")
            .first()[["model_name", "_thinking_sort_key", "thinking"]]
            .reset_index()
        )
        group_df = group_df.merge(metadata, on="display_name")

        variation_info = analyze_model_variations(group_df)
        tracker = LegendGroupTracker(
            context.color_map, context.base_color_map, variation_info
        )

        sorted_unique_runs = group_df.sort_values(
            by=["model_name", "_thinking_sort_key"]
        )

        return group_df, chkpt_df, sorted_unique_runs, tracker

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
    return df, chkpt_df, sorted_unique_runs, tracker


def build_bar_comparison(context: ChartContext) -> go.Figure:
    df, chkpt_df, sorted_unique_runs, tracker = _prepare_bar_data(context)
    if df is None:
        return go.Figure()

    fig = make_subplots(
        rows=1,
        cols=4,
        subplot_titles=[
            "Checkpoints Solved",
            "Checkpoint Iso Solved",
            "Problems Partial",
            "Net Cost",
        ],
        horizontal_spacing=0.05,
    )

    for display_name in sorted_unique_runs["display_name"]:
        run_df = df[df["display_name"] == display_name]
        info = tracker.get_info(display_name, run_df.iloc[0])

        is_grouped = context.group_runs

        def get_trace_params(col):
            y = run_df[f"{col}_mean"] if is_grouped else run_df[col]
            error_y = None
            if is_grouped:
                error_y = dict(
                    type="data", array=run_df[f"{col}_std"], visible=True
                )
            return y, error_y

        # Subplot 1: Solved
        y, error_y = get_trace_params("pct_checkpoints_solved")
        fig.add_trace(
            go.Bar(
                y=y,
                error_y=error_y,
                name=info.variant,
                legendgroup=info.model_name,
                legendgrouptitle_text=info.group_title,
                legendgrouptitle_font={"color": info.model_base_color},
                marker={"color": info.color},
                text=[f"{v:.1f}" for v in y],
                textposition="inside",
                textangle=0,
                showlegend=True,
            ),
            row=1,
            col=1,
        )

        # Subplot 2: Iso Solved
        y, error_y = get_trace_params("pct_checkpoints_iso_solved")
        fig.add_trace(
            go.Bar(
                y=y,
                error_y=error_y,
                name=info.variant,
                legendgroup=info.model_name,
                marker={"color": info.color},
                text=[f"{v:.1f}" for v in y],
                textposition="inside",
                textangle=0,
                showlegend=False,
            ),
            row=1,
            col=2,
        )

        # Subplot 3: Partial
        y, error_y = get_trace_params("pct_problems_partial")
        fig.add_trace(
            go.Bar(
                y=y,
                error_y=error_y,
                name=info.variant,
                legendgroup=info.model_name,
                marker={"color": info.color},
                text=[f"{v:.1f}" for v in y],
                textposition="inside",
                textangle=0,
                showlegend=False,
            ),
            row=1,
            col=3,
        )

        # Subplot 4: Cost
        y, error_y = get_trace_params("costs.total")
        fig.add_trace(
            go.Bar(
                y=y,
                error_y=error_y,
                name=info.variant,
                legendgroup=info.model_name,
                marker={"color": info.color},
                text=[f"${v:.2f}" for v in y],
                textposition="inside",
                textangle=0,
                showlegend=False,
            ),
            row=1,
            col=4,
        )

    fig.update_yaxes(
        title_text="Solved (%)", row=1, col=1, gridcolor="lightgray"
    )
    fig.update_yaxes(
        title_text="Iso Solved (%)", row=1, col=2, gridcolor="lightgray"
    )
    fig.update_yaxes(
        title_text="Partial (%)", row=1, col=3, gridcolor="lightgray"
    )
    fig.update_yaxes(title_text="Cost ($)", row=1, col=4, gridcolor="lightgray")

    for i in range(1, 4):
        fig.update_xaxes(row=1, col=i, showticklabels=False)

    fig.update_layout(**get_base_layout(None, 400, 1.0, "Overview Performance"))
    fig.update_layout(legend=GROUPED_VERTICAL_LEGEND)
    return fig


def build_efficiency_bars(context: ChartContext) -> go.Figure:
    df, chkpt_df, sorted_unique_runs, tracker = _prepare_bar_data(context)
    if df is None:
        return go.Figure()

    fig = make_subplots(
        rows=1,
        cols=2,
        subplot_titles=["Output Tokens", "Time"],
        horizontal_spacing=0.1,
    )

    for display_name in sorted_unique_runs["display_name"]:
        run_df = df[df["display_name"] == display_name]
        checkpoint_run = chkpt_df[chkpt_df["display_name"] == display_name]
        info = tracker.get_info(display_name, run_df.iloc[0])

        is_grouped = context.group_runs

        if "output" in checkpoint_run.columns:
            if is_grouped:
                run_token_sums = checkpoint_run.groupby("run_path")[
                    "output"
                ].sum()
                total_output_tokens = run_token_sums.mean()
                std_output_tokens = run_token_sums.std()
            else:
                total_output_tokens = checkpoint_run["output"].sum()
                std_output_tokens = 0
        else:
            total_output_tokens = 0
            std_output_tokens = 0

        if total_output_tokens >= 1_000_000:
            tokens_text = f"{total_output_tokens / 1_000_000:.1f}M"
        elif total_output_tokens >= 1_000:
            tokens_text = f"{total_output_tokens / 1_000:.0f}K"
        else:
            tokens_text = f"{total_output_tokens:.0f}"

        error_y = None
        if is_grouped:
            error_y = dict(type="data", array=[std_output_tokens], visible=True)

        fig.add_trace(
            go.Bar(
                y=[total_output_tokens],
                error_y=error_y,
                name=info.variant,
                legendgroup=info.model_name,
                legendgrouptitle_text=info.group_title,
                legendgrouptitle_font={"color": info.model_base_color},
                marker={"color": info.color},
                text=[tokens_text],
                textposition="inside",
                textangle=0,
                showlegend=True,
            ),
            row=1,
            col=1,
        )
        fig.add_trace(
            go.Box(
                x=[display_name] * len(checkpoint_run),
                y=checkpoint_run["duration"] / 60,
                name=get_short_annotation(run_df.iloc[0], use_html=True),
                legendgroup=info.model_name,
                marker={"color": info.color},
                showlegend=False,
            ),
            row=1,
            col=2,
        )

    fig.update_yaxes(title_text="Tokens", row=1, col=1, gridcolor="lightgray")
    fig.update_yaxes(
        title_text="Time (M)",
        row=1,
        col=2,
        gridcolor="lightgray",
        type="log",
        dtick=1,
    )

    fig.update_xaxes(row=1, col=1, showticklabels=False)
    fig.update_xaxes(row=1, col=2, showticklabels=False)

    fig.update_layout(
        **get_base_layout(None, 400, 1.0, "Efficiency Comparison")
    )
    fig.update_layout(legend=GROUPED_VERTICAL_LEGEND)
    return fig


def build_quality_bars(context: ChartContext) -> go.Figure:
    df, chkpt_df, sorted_unique_runs, tracker = _prepare_bar_data(context)
    if df is None:
        return go.Figure()

    fig = make_subplots(
        rows=1,
        cols=3,
        subplot_titles=["Mean Func LOC", "Comparisons/LOC", "Try/LOC"],
        horizontal_spacing=0.05,
    )

    for display_name in sorted_unique_runs["display_name"]:
        run_df = df[df["display_name"] == display_name]
        checkpoint_run = chkpt_df[chkpt_df["display_name"] == display_name]
        info = tracker.get_info(display_name, run_df.iloc[0])

        is_grouped = context.group_runs

        def get_stats(col):
            if col not in checkpoint_run.columns:
                return 0, 0
            if is_grouped:
                run_vals = checkpoint_run.groupby("run_path")[col].mean()
                return run_vals.mean(), run_vals.std()
            return checkpoint_run[col].mean(), 0

        # Compute normalized metrics on the fly
        mean_func_loc, std_func_loc = get_stats("mean_func_loc")

        # Compute comparisons per LOC
        if (
            "comparisons" in checkpoint_run.columns
            and "loc" in checkpoint_run.columns
        ):
            checkpoint_run = checkpoint_run.copy()
            checkpoint_run["_cmp_per_loc"] = checkpoint_run[
                "comparisons"
            ] / checkpoint_run["loc"].replace(0, 1)
            mean_cmp_loc, std_cmp_loc = get_stats("_cmp_per_loc")
        else:
            mean_cmp_loc, std_cmp_loc = 0, 0

        # Compute try/except per LOC
        if (
            "try_scaffold" in checkpoint_run.columns
            and "loc" in checkpoint_run.columns
        ):
            checkpoint_run = checkpoint_run.copy()
            checkpoint_run["_try_per_loc"] = checkpoint_run[
                "try_scaffold"
            ] / checkpoint_run["loc"].replace(0, 1)
            mean_try_loc, std_try_loc = get_stats("_try_per_loc")
        else:
            mean_try_loc, std_try_loc = 0, 0

        def add_bar(
            y_val, std_val, r, c, show_legend=False, format_str="{:.1f}"
        ):
            error_y = None
            if is_grouped:
                error_y = dict(type="data", array=[std_val], visible=True)

            fig.add_trace(
                go.Bar(
                    y=[y_val],
                    error_y=error_y,
                    name=info.variant,
                    legendgroup=info.model_name,
                    legendgrouptitle_text=info.group_title
                    if show_legend
                    else None,
                    legendgrouptitle_font={"color": info.model_base_color}
                    if show_legend
                    else None,
                    marker={"color": info.color},
                    text=[format_str.format(y_val)],
                    textposition="inside",
                    textangle=0,
                    showlegend=show_legend,
                ),
                row=r,
                col=c,
            )

        add_bar(mean_func_loc, std_func_loc, 1, 1, show_legend=True)
        add_bar(mean_cmp_loc, std_cmp_loc, 1, 2, format_str="{:.3f}")
        add_bar(mean_try_loc, std_try_loc, 1, 3, format_str="{:.3f}")

    fig.update_yaxes(title_text="LOC", row=1, col=1, gridcolor="lightgray")
    fig.update_yaxes(title_text="Ratio", row=1, col=2, gridcolor="lightgray")
    fig.update_yaxes(title_text="Ratio", row=1, col=3, gridcolor="lightgray")

    for i in range(1, 4):
        fig.update_xaxes(row=1, col=i, showticklabels=False)

    fig.update_layout(
        **get_base_layout(None, 400, 1.0, "Code Style Comparison")
    )
    fig.update_layout(legend=GROUPED_VERTICAL_LEGEND)
    return fig


def build_graph_metrics_bars(context: ChartContext) -> go.Figure:
    """Build bar chart for program graph metrics (CY, PC, ENT)."""
    df, chkpt_df, sorted_unique_runs, tracker = _prepare_bar_data(context)
    if df is None:
        return go.Figure()

    fig = make_subplots(
        rows=1,
        cols=3,
        subplot_titles=[
            "Cyclic Dependency Mass",
            "Propagation Cost",
            "Dependency Entropy",
        ],
        horizontal_spacing=0.05,
    )

    for display_name in sorted_unique_runs["display_name"]:
        run_df = df[df["display_name"] == display_name]
        checkpoint_run = chkpt_df[chkpt_df["display_name"] == display_name]
        info = tracker.get_info(display_name, run_df.iloc[0])

        is_grouped = context.group_runs

        def get_stats(col):
            if col not in checkpoint_run.columns:
                return 0, 0
            if is_grouped:
                run_vals = checkpoint_run.groupby("run_path")[col].mean()
                return run_vals.mean(), run_vals.std()
            return checkpoint_run[col].mean(), 0

        mean_cy, std_cy = get_stats("graph_cyclic_dependency_mass")
        mean_pc, std_pc = get_stats("graph_propagation_cost")
        mean_ent, std_ent = get_stats("graph_dependency_entropy")

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
                    legendgrouptitle_text=info.group_title
                    if show_legend
                    else None,
                    legendgrouptitle_font={"color": info.model_base_color}
                    if show_legend
                    else None,
                    marker={"color": info.color},
                    text=[f"{y_val:.3f}"],
                    textposition="inside",
                    textangle=0,
                    showlegend=show_legend,
                ),
                row=r,
                col=c,
            )

        add_bar(mean_cy, std_cy, 1, 1, show_legend=True)
        add_bar(mean_pc, std_pc, 1, 2)
        add_bar(mean_ent, std_ent, 1, 3)

    fig.update_yaxes(
        title_text="CY (0-1)", row=1, col=1, gridcolor="lightgray", range=[0, 1]
    )
    fig.update_yaxes(
        title_text="PC (0-1)", row=1, col=2, gridcolor="lightgray", range=[0, 1]
    )
    fig.update_yaxes(
        title_text="ENT (0-1)",
        row=1,
        col=3,
        gridcolor="lightgray",
        range=[0, 1],
    )

    for i in range(1, 4):
        fig.update_xaxes(row=1, col=i, showticklabels=False)

    fig.update_layout(
        **get_base_layout(None, 400, 1.0, "Dependency Graph Metrics")
    )
    fig.update_layout(legend=GROUPED_VERTICAL_LEGEND)
    return fig
