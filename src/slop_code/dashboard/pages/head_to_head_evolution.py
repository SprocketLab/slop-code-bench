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

dash.register_page(__name__, path="/head-to-head/evolution")

layout = dbc.Container(
    [
        dbc.Row(
            dbc.Col(
                html.H3(
                    "Head to Head: Code Evolution",
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
                                "Lines of Code (LOC) Trajectory",
                                className="fw-bold",
                            ),
                            dbc.CardBody(
                                loading_graph(
                                    "h2h-loc-trajectory", height="400px"
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
                                "Complexity Trajectory", className="fw-bold"
                            ),
                            dbc.CardBody(
                                loading_graph(
                                    "h2h-complexity-trajectory", height="400px"
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
                                "Lint Errors Trajectory", className="fw-bold"
                            ),
                            dbc.CardBody(
                                loading_graph(
                                    "h2h-lint-trajectory", height="400px"
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
                                "AST-grep Violations Trajectory",
                                className="fw-bold",
                            ),
                            dbc.CardBody(
                                loading_graph(
                                    "h2h-ast-grep-trajectory", height="400px"
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


@callback(
    [
        Output("h2h-loc-trajectory", "figure"),
        Output("h2h-complexity-trajectory", "figure"),
        Output("h2h-lint-trajectory", "figure"),
        Output("h2h-ast-grep-trajectory", "figure"),
    ],
    [Input("h2h-run-a", "value"), Input("h2h-run-b", "value")],
)
def update_evolution(run_a_path, run_b_path):
    default_outs = [empty_figure()] * 4
    if not run_a_path or not run_b_path:
        return default_outs

    context = build_context([run_a_path, run_b_path])
    if context is None or context.checkpoints.empty:
        return default_outs

    df_chk = context.checkpoints

    # Filter for selected runs
    df_a_raw = df_chk[df_chk["run_path"] == run_a_path].copy()
    df_b_raw = df_chk[df_chk["run_path"] == run_b_path].copy()

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

    # Define state columns (all metrics here are state)
    state_cols = ["loc", "cc_high_count"]
    if "lint_errors" in df_a_raw.columns:
        state_cols.append("lint_errors")
    if "ast_grep_violations" in df_a_raw.columns:
        state_cols.append("ast_grep_violations")

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

        for problem, prob_df in df.groupby("problem"):
            # Mean aggregation for bins having multiple checkpoints
            prob_binned = prob_df.groupby("bin")[state_cols].mean()

            # Reindex to standard bins
            prob_binned = prob_binned.reindex(bins)

            # Forward Fill ALL state metrics
            prob_binned[state_cols] = prob_binned[state_cols].ffill()

            results.append(prob_binned)

        if not results:
            return pd.DataFrame(index=bins, columns=state_cols).fillna(0)

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

    # 1. LOC
    loc_traj = make_trajectory(
        "loc", "Avg Lines of Code per Progress Step", "LOC"
    )

    # 2. Complexity
    comp_traj = make_trajectory(
        "cc_high_count", "Avg Complexity Rating per Progress Step", "Rating Sum"
    )

    # 3. Lint Errors
    lint_traj = make_trajectory(
        "lint_errors", "Avg Lint Errors per Progress Step", "Errors"
    )

    # 4. AST-grep Violations
    ast_grep_traj = make_trajectory(
        "ast_grep_violations",
        "Avg AST-grep Violations per Progress Step",
        "Violations",
    )

    return loc_traj, comp_traj, lint_traj, ast_grep_traj
