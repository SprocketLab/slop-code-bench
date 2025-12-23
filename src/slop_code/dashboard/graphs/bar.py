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

        fig.add_trace(
            go.Bar(
                y=run_df["pct_checkpoints_solved"],
                name=info.variant,
                legendgroup=info.model_name,
                legendgrouptitle_text=info.group_title,
                legendgrouptitle_font={"color": info.model_base_color},
                marker={"color": info.color},
                text=[f"{v:.1f}" for v in run_df["pct_checkpoints_solved"]],
                textposition="inside",
                textangle=0,
                showlegend=True,
            ),
            row=1,
            col=1,
        )
        fig.add_trace(
            go.Bar(
                y=run_df["pct_checkpoints_iso_solved"],
                name=info.variant,
                legendgroup=info.model_name,
                marker={"color": info.color},
                text=[f"{v:.1f}" for v in run_df["pct_checkpoints_iso_solved"]],
                textposition="inside",
                textangle=0,
                showlegend=False,
            ),
            row=1,
            col=2,
        )
        fig.add_trace(
            go.Bar(
                y=run_df["pct_problems_partial"],
                name=info.variant,
                legendgroup=info.model_name,
                marker={"color": info.color},
                text=[f"{v:.1f}" for v in run_df["pct_problems_partial"]],
                textposition="inside",
                textangle=0,
                showlegend=False,
            ),
            row=1,
            col=3,
        )
        fig.add_trace(
            go.Bar(
                y=run_df["costs.total"],
                name=info.variant,
                legendgroup=info.model_name,
                marker={"color": info.color},
                text=[f"${v:.2f}" for v in run_df["costs.total"]],
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

        if "output" in checkpoint_run.columns:
            total_output_tokens = checkpoint_run["output"].sum()
        else:
            total_output_tokens = 0

        if total_output_tokens >= 1_000_000:
            tokens_text = f"{total_output_tokens / 1_000_000:.1f}M"
        elif total_output_tokens >= 1_000:
            tokens_text = f"{total_output_tokens / 1_000:.0f}K"
        else:
            tokens_text = f"{total_output_tokens:.0f}"

        fig.add_trace(
            go.Bar(
                y=[total_output_tokens],
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

        def get_mean(col):
            if col in checkpoint_run.columns:
                return checkpoint_run[col].mean()
            return 0

        # Compute normalized metrics on the fly
        mean_func_loc = get_mean("mean_func_loc")

        # Compute comparisons per LOC
        if (
            "comparisons" in checkpoint_run.columns
            and "loc" in checkpoint_run.columns
        ):
            cmp_per_loc = checkpoint_run["comparisons"] / checkpoint_run[
                "loc"
            ].replace(0, 1)
            mean_cmp_loc = cmp_per_loc.mean()
        else:
            mean_cmp_loc = 0

        # Compute try/except per LOC
        if (
            "try_scaffold" in checkpoint_run.columns
            and "loc" in checkpoint_run.columns
        ):
            try_per_loc = checkpoint_run["try_scaffold"] / checkpoint_run[
                "loc"
            ].replace(0, 1)
            mean_try_loc = try_per_loc.mean()
        else:
            mean_try_loc = 0

        fig.add_trace(
            go.Bar(
                y=[mean_func_loc],
                name=info.variant,
                legendgroup=info.model_name,
                legendgrouptitle_text=info.group_title,
                legendgrouptitle_font={"color": info.model_base_color},
                marker={"color": info.color},
                text=[f"{mean_func_loc:.1f}"],
                textposition="inside",
                textangle=0,
                showlegend=True,
            ),
            row=1,
            col=1,
        )
        fig.add_trace(
            go.Bar(
                y=[mean_cmp_loc],
                name=info.variant,
                legendgroup=info.model_name,
                marker={"color": info.color},
                text=[f"{mean_cmp_loc:.3f}"],
                textposition="inside",
                textangle=0,
                showlegend=False,
            ),
            row=1,
            col=2,
        )
        fig.add_trace(
            go.Bar(
                y=[mean_try_loc],
                name=info.variant,
                legendgroup=info.model_name,
                marker={"color": info.color},
                text=[f"{mean_try_loc:.3f}"],
                textposition="inside",
                textangle=0,
                showlegend=False,
            ),
            row=1,
            col=3,
        )

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

        def get_mean(col):
            if col in checkpoint_run.columns:
                return checkpoint_run[col].mean()
            return 0

        mean_cy = get_mean("graph_cyclic_dependency_mass")
        mean_pc = get_mean("graph_propagation_cost")
        mean_ent = get_mean("graph_dependency_entropy")

        fig.add_trace(
            go.Bar(
                y=[mean_cy],
                name=info.variant,
                legendgroup=info.model_name,
                legendgrouptitle_text=info.group_title,
                legendgrouptitle_font={"color": info.model_base_color},
                marker={"color": info.color},
                text=[f"{mean_cy:.3f}"],
                textposition="inside",
                textangle=0,
                showlegend=True,
            ),
            row=1,
            col=1,
        )
        fig.add_trace(
            go.Bar(
                y=[mean_pc],
                name=info.variant,
                legendgroup=info.model_name,
                marker={"color": info.color},
                text=[f"{mean_pc:.3f}"],
                textposition="inside",
                textangle=0,
                showlegend=False,
            ),
            row=1,
            col=2,
        )
        fig.add_trace(
            go.Bar(
                y=[mean_ent],
                name=info.variant,
                legendgroup=info.model_name,
                marker={"color": info.color},
                text=[f"{mean_ent:.3f}"],
                textposition="inside",
                textangle=0,
                showlegend=False,
            ),
            row=1,
            col=3,
        )

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
