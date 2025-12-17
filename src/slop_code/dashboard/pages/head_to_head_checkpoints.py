import dash
import dash_bootstrap_components as dbc
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

dash.register_page(__name__, path="/head-to-head/checkpoints")


def make_pass_rate_scatter_checkpoint_level(
    df_chk, title, axis_label, name_a, name_b, run_a_path, run_b_path
):
    idx_col = "idx" if "idx" in df_chk.columns else "checkpoint"

    df_a = df_chk[df_chk["run_path"] == run_a_path].copy()
    df_b = df_chk[df_chk["run_path"] == run_b_path].copy()

    df_a["_pr"] = df_a["passed_tests"] / df_a["total_tests"] * 100
    df_b["_pr"] = df_b["passed_tests"] / df_b["total_tests"] * 100

    df_a_plot = df_a[["problem", idx_col, "_pr"]]
    df_b_plot = df_b[["problem", idx_col, "_pr"]]

    merged_df = pd.merge(
        df_a_plot,
        df_b_plot,
        on=["problem", idx_col],
        suffixes=("_a", "_b"),
        how="inner",
    )

    if merged_df.empty:
        return empty_figure()

    x_vals = merged_df["_pr_a"]
    y_vals = merged_df["_pr_b"]

    mx = 100  # Pass rate is 0-100

    hover_text = [
        f"Problem: {p}<br>Checkpoint: {c}<br>{name_a}: {x_val:.1f}%<br>{name_b}: {y_val:.1f}%"
        for p, c, x_val, y_val in merged_df[
            ["problem", idx_col, "_pr_a", "_pr_b"]
        ].values
    ]

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=x_vals,
            y=y_vals,
            mode="markers",
            text=hover_text,
            marker=dict(
                color="#663399",
                size=8,
                opacity=0.7,
                line=dict(width=1, color="white"),
            ),
            hovertemplate="%{text}<extra></extra>",
        )
    )
    fig.add_shape(
        type="line",
        x0=0,
        y0=0,
        x1=mx,
        y1=mx,
        line=dict(color="gray", dash="dash", width=1),
    )
    fig.update_layout(
        title={"text": title, "font": {"size": 16}},
        xaxis={"title": f"{name_a} ({axis_label})"},
        yaxis={"title": f"{name_b} ({axis_label})"},
        plot_bgcolor="white",
        hovermode="closest",
        margin=dict(l=40, r=40, t=50, b=40),
    )
    fig.update_xaxes(showgrid=True, gridcolor="#f0f0f0", range=[-5, 105])
    fig.update_yaxes(showgrid=True, gridcolor="#f0f0f0", range=[-5, 105])
    return fig


layout = dbc.Container(
    [
        dbc.Row(
            dbc.Col(
                html.H3(
                    "Head to Head: Checkpoints",
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
                                "Test Category Pass Rates (Grouped)",
                                className="fw-bold",
                            ),
                            dbc.CardBody(
                                loading_graph(
                                    "h2h-test-cat-bar", height="400px"
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
                                "Problem Pass Rate % Comparison",
                                className="fw-bold",
                            ),
                            dbc.CardBody(
                                loading_graph(
                                    "h2h-pass-rate-scatter", height="400px"
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
        Output("h2h-test-cat-bar", "figure"),
        Output("h2h-pass-rate-scatter", "figure"),
    ],
    [Input("h2h-run-a", "value"), Input("h2h-run-b", "value")],
)
def update_checkpoints(run_a_path, run_b_path):
    default_outs = [empty_figure()] * 2
    if not run_a_path or not run_b_path:
        return default_outs

    context = build_context([run_a_path, run_b_path])
    if context is None or context.checkpoints.empty:
        return default_outs

    df_chk = context.checkpoints

    # Need row metadata for labels
    row_a = (
        df_chk[df_chk["run_path"] == run_a_path].iloc[0]
        if not df_chk[df_chk["run_path"] == run_a_path].empty
        else None
    )
    row_b = (
        df_chk[df_chk["run_path"] == run_b_path].iloc[0]
        if not df_chk[df_chk["run_path"] == run_b_path].empty
        else None
    )

    if row_a is None or row_b is None:
        return default_outs

    name_a = get_display_annotation(row_a).split(" - ")[0]
    name_b = get_display_annotation(row_b).split(" - ")[0]

    # --- Test Category Bar ---
    cats = ["core", "functionality", "regression", "error"]
    cat_data_a = []
    cat_data_b = []

    df_a = df_chk[df_chk["run_path"] == run_a_path]
    df_b = df_chk[df_chk["run_path"] == run_b_path]

    for cat in cats:

        def get_cat_avg(df, c):
            if f"tests.{c}.total" not in df.columns:
                return 0
            passed = df[f"tests.{c}.passed"].sum()
            total = df[f"tests.{c}.total"].sum()
            return (passed / total * 100) if total > 0 else 0

        cat_data_a.append(get_cat_avg(df_a, cat))
        cat_data_b.append(get_cat_avg(df_b, cat))

    bar_fig = go.Figure()
    bar_fig.add_trace(
        go.Bar(x=cats, y=cat_data_a, name="Run A", marker_color="#1f77b4")
    )
    bar_fig.add_trace(
        go.Bar(x=cats, y=cat_data_b, name="Run B", marker_color="#d62728")
    )

    bar_fig.update_layout(
        title="Pass Rate by Test Category",
        yaxis_title="Pass %",
        barmode="group",
        plot_bgcolor="white",
        margin=dict(l=40, r=40, t=50, b=40),
    )
    bar_fig.update_yaxes(range=[0, 105], showgrid=True, gridcolor="#f0f0f0")

    pass_fig = make_pass_rate_scatter_checkpoint_level(
        df_chk,
        "Test Pass Rate % per Checkpoint",
        "Pass %",
        name_a,
        name_b,
        run_a_path,
        run_b_path,
    )

    return bar_fig, pass_fig
