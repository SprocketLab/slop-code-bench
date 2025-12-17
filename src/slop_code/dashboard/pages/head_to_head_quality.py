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

dash.register_page(__name__, path="/head-to-head/quality")


def make_quality_scatter_checkpoint_level(
    df_chk, col, title, axis_label, name_a, name_b, run_a_path, run_b_path
):
    """
    Generates a scatter plot comparing a quality metric between two runs at the checkpoint level.
    Each point represents a (problem, checkpoint) pair.
    """
    idx_col = "idx" if "idx" in df_chk.columns else "checkpoint"

    df_a = df_chk[df_chk["run_path"] == run_a_path][
        ["problem", idx_col, col]
    ].copy()
    df_b = df_chk[df_chk["run_path"] == run_b_path][
        ["problem", idx_col, col]
    ].copy()

    # Merge on problem and checkpoint index to get common checkpoints
    merged_df = pd.merge(
        df_a, df_b, on=["problem", idx_col], suffixes=("_a", "_b"), how="inner"
    )

    if merged_df.empty:
        return empty_figure()

    x_vals = merged_df[f"{col}_a"]
    y_vals = merged_df[f"{col}_b"]

    mx = max(x_vals.max(), y_vals.max()) if not x_vals.empty else 1
    if mx == 0:
        mx = 1

    hover_text = [
        f"Problem: {p}<br>Checkpoint: {c}<br>{name_a}: {x_val}<br>{name_b}: {y_val}"
        for p, c, x_val, y_val in merged_df[
            ["problem", idx_col, f"{col}_a", f"{col}_b"]
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
    fig.update_xaxes(showgrid=True, gridcolor="#f0f0f0")
    fig.update_yaxes(showgrid=True, gridcolor="#f0f0f0")
    return fig


layout = dbc.Container(
    [
        dbc.Row(
            dbc.Col(
                html.H3(
                    "Head to Head: Code Quality",
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
                                "Lint Errors Comparison", className="fw-bold"
                            ),
                            dbc.CardBody(
                                loading_graph(
                                    "h2h-lint-scatter", height="400px"
                                )
                            ),
                        ],
                        className="mb-4 shadow-sm border-0 h-100",
                    ),
                    md=4,
                ),
                dbc.Col(
                    dbc.Card(
                        [
                            dbc.CardHeader(
                                "AST-grep Violations Comparison",
                                className="fw-bold",
                            ),
                            dbc.CardBody(
                                loading_graph(
                                    "h2h-ast-grep-scatter", height="400px"
                                )
                            ),
                        ],
                        className="mb-4 shadow-sm border-0 h-100",
                    ),
                    md=4,
                ),
                dbc.Col(
                    dbc.Card(
                        [
                            dbc.CardHeader(
                                "Complexity Comparison", className="fw-bold"
                            ),
                            dbc.CardBody(
                                loading_graph(
                                    "h2h-complexity-scatter", height="400px"
                                )
                            ),
                        ],
                        className="mb-4 shadow-sm border-0 h-100",
                    ),
                    md=4,
                ),
            ]
        ),
    ],
    fluid=True,
    className="py-3",
)


@callback(
    [
        Output("h2h-lint-scatter", "figure"),
        Output("h2h-ast-grep-scatter", "figure"),
        Output("h2h-complexity-scatter", "figure"),
    ],
    [Input("h2h-run-a", "value"), Input("h2h-run-b", "value")],
)
def update_quality(run_a_path, run_b_path):
    default_outs = [empty_figure()] * 3
    if not run_a_path or not run_b_path:
        return default_outs

    context = build_context([run_a_path, run_b_path])
    if context is None or context.checkpoints.empty:
        return default_outs

    df_chk = context.checkpoints

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

    def short_label(name):
        return (name[:20] + "..") if len(name) > 20 else name

    label_a = short_label(name_a)
    label_b = short_label(name_b)

    # Calculate complexity column on the full df_chk for accurate lookup
    df_chk["_complex"] = df_chk["cc_high_count"]

    lint_fig = make_quality_scatter_checkpoint_level(
        df_chk,
        "lint_errors",
        "Lint Errors per Checkpoint",
        "Errors",
        name_a,
        name_b,
        run_a_path,
        run_b_path,
    )
    ast_grep_fig = make_quality_scatter_checkpoint_level(
        df_chk,
        "ast_grep_violations",
        "AST-grep Violations per Checkpoint",
        "Violations",
        name_a,
        name_b,
        run_a_path,
        run_b_path,
    )
    comp_fig = make_quality_scatter_checkpoint_level(
        df_chk,
        "_complex",
        "Complexity per Checkpoint",
        "Rating",
        name_a,
        name_b,
        run_a_path,
        run_b_path,
    )

    return lint_fig, ast_grep_fig, comp_fig
