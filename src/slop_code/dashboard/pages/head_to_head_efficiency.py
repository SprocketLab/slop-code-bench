import dash
import dash_bootstrap_components as dbc
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import Input
from dash import Output
from dash import callback
from dash import html

from slop_code.dashboard.components import loading_graph
from slop_code.dashboard.data import get_display_annotation
from slop_code.dashboard.page_context import build_context
from slop_code.dashboard.page_context import empty_figure

dash.register_page(__name__, path="/head-to-head/efficiency")

layout = dbc.Container(
    [
        dbc.Row(
            dbc.Col(
                html.H3(
                    "Head to Head: Efficiency & Resources",
                    className="display-6 fw-bold text-primary mb-4",
                )
            )
        ),
        dbc.Row(
            [
                dbc.Col(
                    dbc.Card(
                        [
                            dbc.CardHeader(
                                "Average Cost per Checkpoint ($)",
                                className="fw-bold",
                            ),
                            dbc.CardBody(
                                loading_graph(
                                    "h2h-cost-trajectory", height="400px"
                                )
                            ),
                        ],
                        className="mb-4 shadow-sm border-0 h-100",
                    ),
                    md=6,
                ),
                dbc.Col(
                    dbc.Card(
                        [
                            dbc.CardHeader(
                                "Cumulative Cost per Problem (Avg)",
                                className="fw-bold",
                            ),
                            dbc.CardBody(
                                loading_graph(
                                    "h2h-cumulative-cost", height="400px"
                                )
                            ),
                        ],
                        className="mb-4 shadow-sm border-0 h-100",
                    ),
                    md=6,
                ),
            ]
        ),
        dbc.Row(
            [
                dbc.Col(
                    dbc.Card(
                        [
                            dbc.CardHeader(
                                "Token Usage per Checkpoint (Avg)",
                                className="fw-bold",
                            ),
                            dbc.CardBody(
                                loading_graph(
                                    "h2h-token-trajectory", height="400px"
                                )
                            ),
                        ],
                        className="mb-4 shadow-sm border-0 h-100",
                    ),
                    md=6,
                ),
                dbc.Col(
                    dbc.Card(
                        [
                            dbc.CardHeader(
                                "Duration per Checkpoint (Minutes)",
                                className="fw-bold",
                            ),
                            dbc.CardBody(
                                loading_graph(
                                    "h2h-duration-trajectory", height="400px"
                                )
                            ),
                        ],
                        className="mb-4 shadow-sm border-0 h-100",
                    ),
                    md=6,
                ),
            ]
        ),
    ],
    fluid=True,
    className="py-3",
)


def normalize_and_bin(df, idx_col, num_bins=20):
    """Normalize checkpoint index to progress % and bin it."""
    # Find max checkpoint index per problem across this dataframe (which contains only 2 runs)
    # Using the global max for that problem ensures comparable progress.
    max_indices = df.groupby("problem")[idx_col].max()

    # Map back to get total checkpoints for each row's problem
    df = df.copy()
    df["total_checkpoints"] = df["problem"].map(max_indices)

    # Calculate progress (0.0 to 1.0)
    # Avoid division by zero if total is 0 (unlikely)
    df["progress"] = df[idx_col] / df["total_checkpoints"].replace(0, 1)

    # Bin into 5% increments (for 20 bins)
    # 0.0 -> 0, 0.05 -> 5, ..., 1.0 -> 100
    df["progress_bin"] = (df["progress"] * 20).round() * 5

    return df


@callback(
    [
        Output("h2h-cost-trajectory", "figure"),
        Output("h2h-cumulative-cost", "figure"),
        Output("h2h-token-trajectory", "figure"),
        Output("h2h-duration-trajectory", "figure"),
    ],
    [Input("h2h-run-a", "value"), Input("h2h-run-b", "value")],
)
def update_efficiency(run_a_path, run_b_path):
    default_outs = [empty_figure()] * 4
    if not run_a_path or not run_b_path:
        return default_outs

    context = build_context([run_a_path, run_b_path])
    if context is None or context.checkpoints.empty:
        return default_outs

    df_chk = context.checkpoints

    # Filter for selected runs
    df_a_raw = df_chk[df_chk["run_path"] == run_a_path]
    df_b_raw = df_chk[df_chk["run_path"] == run_b_path]

    if df_a_raw.empty or df_b_raw.empty:
        return default_outs

    row_a = df_a_raw.iloc[0]
    row_b = df_b_raw.iloc[0]

    name_a = get_display_annotation(row_a).split(" - ")[0]
    name_b = get_display_annotation(row_b).split(" - ")[0]

    # Normalize and Bin Progress
    idx_col = "idx" if "idx" in df_chk.columns else "checkpoint"

    combined_df = pd.concat([df_a_raw, df_b_raw])
    max_indices = combined_df.groupby("problem")[idx_col].max()

    # Pre-calculate cumulative cost per problem
    df_a_raw = df_a_raw.sort_values([idx_col])
    df_a_raw["cumulative_cost"] = df_a_raw.groupby("problem")["cost"].cumsum()

    df_b_raw = df_b_raw.sort_values([idx_col])
    df_b_raw["cumulative_cost"] = df_b_raw.groupby("problem")["cost"].cumsum()

    # Define columns
    token_col = "output" if "output" in df_a_raw.columns else "output_tokens"
    has_tokens = token_col in df_a_raw.columns
    has_duration = "duration" in df_a_raw.columns

    rate_cols = ["cost"]
    if has_tokens:
        rate_cols.append(token_col)
    if has_duration:
        # Convert to minutes upfront
        df_a_raw["_dur_min"] = df_a_raw["duration"] / 60
        df_b_raw["_dur_min"] = df_b_raw["duration"] / 60
        rate_cols.append("_dur_min")

    state_cols = ["cumulative_cost"]

    # 1. Add Progress (Create Scatter Data)
    def add_progress(df):
        df = df.copy()
        df["total"] = df["problem"].map(max_indices)
        df["progress"] = df[idx_col] / df["total"].replace(0, 1) * 100
        return df

    df_a_scatter = add_progress(df_a_raw)
    df_b_scatter = add_progress(df_b_raw)

    # 2. Process for Trend (Bin, Fill, Aggregate)
    def process_for_trend(df):
        df = df.copy()
        df["bin"] = (df["progress"] / 5).round() * 5
        df["bin"] = df["bin"].clip(0, 100)

        bins = np.arange(0, 105, 5)
        results = []

        # Process per problem
        for problem, prob_df in df.groupby("problem"):
            # Mean aggregation for bins having multiple checkpoints
            prob_binned = prob_df.groupby("bin")[state_cols + rate_cols].mean()

            # Reindex to standard bins
            prob_binned = prob_binned.reindex(bins)

            # State metrics: Forward Fill
            prob_binned[state_cols] = prob_binned[state_cols].ffill()

            # Rate metrics: Zero Fill
            prob_binned[rate_cols] = prob_binned[rate_cols].fillna(0)

            results.append(prob_binned)

        if not results:
            return pd.DataFrame(
                index=bins, columns=state_cols + rate_cols
            ).fillna(0)

        # Average across problems
        final = pd.concat(results)
        return final.groupby(level=0).mean()

    df_a_trend = process_for_trend(df_a_scatter)
    df_b_trend = process_for_trend(df_b_scatter)

    # Helper to create trajectory line charts with scatter overlay
    def make_trajectory(col, title, y_axis):
        if col not in df_a_trend.columns:
            return empty_figure()

        fig = go.Figure()

        # Scatter Points (A)
        fig.add_trace(
            go.Scatter(
                x=df_a_scatter["progress"],
                y=df_a_scatter[col],
                mode="markers",
                name=f"{name_a} (Points)",
                marker=dict(color="#1f77b4", size=3, opacity=0.3),
                showlegend=False,
                hoverinfo="skip",
            )
        )

        # Scatter Points (B)
        fig.add_trace(
            go.Scatter(
                x=df_b_scatter["progress"],
                y=df_b_scatter[col],
                mode="markers",
                name=f"{name_b} (Points)",
                marker=dict(color="#d62728", size=3, opacity=0.3),
                showlegend=False,
                hoverinfo="skip",
            )
        )

        # Trend Line (A)
        series_a = df_a_trend[col]
        series_a = series_a.rolling(window=3, min_periods=1, center=True).mean()
        fig.add_trace(
            go.Scatter(
                x=series_a.index,
                y=series_a,
                mode="lines",
                name=name_a,
                line=dict(
                    color="#1f77b4", width=3, shape="spline", smoothing=1.0
                ),
            )
        )

        # Trend Line (B)
        series_b = df_b_trend[col]
        series_b = series_b.rolling(window=3, min_periods=1, center=True).mean()
        fig.add_trace(
            go.Scatter(
                x=series_b.index,
                y=series_b,
                mode="lines",
                name=name_b,
                line=dict(
                    color="#d62728", width=3, shape="spline", smoothing=1.0
                ),
            )
        )

        fig.update_layout(
            title=title,
            xaxis_title="Problem Progress (%)",
            yaxis_title=y_axis,
            plot_bgcolor="white",
            legend=dict(
                orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1
            ),
            margin=dict(l=40, r=40, t=50, b=40),
        )
        fig.update_xaxes(showgrid=True, gridcolor="#f0f0f0", range=[-2, 102])
        fig.update_yaxes(showgrid=True, gridcolor="#f0f0f0")
        return fig

    # 1. Avg Cost per Checkpoint (Rate)
    cost_traj = make_trajectory(
        "cost", "Avg Incremental Cost per Progress Step", "$"
    )

    # 2. Cumulative Cost (State)
    cum_cost = make_trajectory(
        "cumulative_cost", "Avg Cumulative Cost per Problem", "$"
    )

    # 3. Tokens (Rate)
    token_traj = (
        make_trajectory(
            token_col, "Avg Output Tokens per Progress Step", "Tokens"
        )
        if has_tokens
        else empty_figure()
    )

    # 4. Duration (Rate)
    dur_traj = (
        make_trajectory("_dur_min", "Avg Duration per Progress Step", "Minutes")
        if has_duration
        else empty_figure()
    )

    return cost_traj, cum_cost, token_traj, dur_traj
