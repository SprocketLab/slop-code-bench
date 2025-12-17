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

dash.register_page(__name__, path="/head-to-head")


def make_scatter_checkpoint_level(
    df_chk, col, title, axis_label, name_a, name_b, run_a_path, run_b_path
):
    """
    Generates a scatter plot comparing a metric between two runs at the checkpoint level.
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
                    "Head to Head: Overview",
                    className="display-6 fw-bold text-primary mb-4",
                )
            )
        ),
        html.Div(id="h2h-overview-summary"),
        dbc.Row(
            [
                dbc.Col(
                    dbc.Card(
                        [
                            dbc.CardHeader(
                                "Checkpoint Pass Overlap", className="fw-bold"
                            ),
                            dbc.CardBody(
                                loading_graph(
                                    "h2h-overlap-graph", height="400px"
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
                                "Cost per Checkpoint Comparison",
                                className="fw-bold",
                            ),
                            dbc.CardBody(
                                loading_graph(
                                    "h2h-cost-scatter", height="400px"
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
                                "Token Usage per Checkpoint Comparison",
                                className="fw-bold",
                            ),
                            dbc.CardBody(
                                loading_graph(
                                    "h2h-token-scatter", height="400px"
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
                                "Lines of Code per Checkpoint Comparison",
                                className="fw-bold",
                            ),
                            dbc.CardBody(
                                loading_graph("h2h-loc-scatter", height="400px")
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


def build_summary_card(title, val_a, val_b, unit="", invert_better=False):
    delta = val_b - val_a
    if val_a == 0:
        pct = 0 if val_b == 0 else 100
    else:
        pct = (delta / val_a) * 100

    is_good = delta > 0 if not invert_better else delta < 0
    is_neutral = delta == 0

    if is_neutral:
        color = "text-muted"
        icon = "fa-minus"
    elif is_good:
        color = "text-success"
        icon = "fa-arrow-up" if delta > 0 else "fa-arrow-down"
    else:
        color = "text-danger"
        icon = "fa-arrow-down" if delta < 0 else "fa-arrow-up"

    return dbc.Card(
        dbc.CardBody(
            [
                html.H6(
                    title, className="text-muted text-uppercase small fw-bold"
                ),
                html.Div(
                    [
                        html.Span(
                            f"{val_a:.1f}{unit}", className="fw-bold me-2"
                        ),
                        html.Span("vs", className="text-muted small mx-2"),
                        html.Span(f"{val_b:.1f}{unit}", className="fw-bold"),
                    ],
                    className="d-flex align-items-baseline mb-2",
                ),
                html.Div(
                    [
                        html.I(className=f"fas {icon} me-1"),
                        html.Span(f"{abs(delta):.1f}{unit} ({pct:+.1f}%)"),
                    ],
                    className=f"small fw-bold {color}",
                ),
            ]
        ),
        className="h-100 shadow-sm border-0",
    )


@callback(
    [
        Output("h2h-overview-summary", "children"),
        Output("h2h-overlap-graph", "figure"),
        Output("h2h-cost-scatter", "figure"),
        Output("h2h-token-scatter", "figure"),
        Output("h2h-loc-scatter", "figure"),
    ],
    [Input("h2h-run-a", "value"), Input("h2h-run-b", "value")],
)
def update_overview(run_a_path, run_b_path):
    default_outs = [empty_figure()] * 4
    if not run_a_path or not run_b_path:
        return html.Div(
            "Select two runs to compare in the Settings (cog icon).",
            className="text-muted text-center py-5",
        ), *default_outs

    context = build_context([run_a_path, run_b_path])
    if context is None:
        return html.Div(
            "Error loading run data.", className="text-danger"
        ), *default_outs

    df_sum = context.run_summaries
    df_chk = context.checkpoints

    if df_chk.empty:
        return html.Div(
            "No checkpoint data found for selected runs.",
            className="text-warning",
        ), *default_outs

    def get_run_info(r_path):
        if not df_sum.empty and r_path in df_sum["run_path"].values:
            return df_sum[df_sum["run_path"] == r_path].iloc[0]
        if not df_chk.empty and r_path in df_chk["run_path"].values:
            return df_chk[df_chk["run_path"] == r_path].iloc[0]
        return pd.Series()

    row_a = get_run_info(run_a_path)
    row_b = get_run_info(run_b_path)

    if row_a.empty or row_b.empty:
        return html.Div(
            "Could not load metadata for one of the runs.",
            className="text-danger",
        ), *default_outs

    name_a = get_display_annotation(row_a).split(" - ")[0]
    name_b = get_display_annotation(row_b).split(" - ")[0]

    def get_val(row, key, default=0):
        val = row.get(key, default)
        return val if not pd.isna(val) else default

    def get_tokens(run_path, row):
        val = get_val(row, "output_tokens", 0)
        if val == 0 and not df_chk.empty:
            val = df_chk[df_chk["run_path"] == run_path]["output"].sum()
        return val

    tokens_a = get_tokens(run_a_path, row_a)
    tokens_b = get_tokens(run_b_path, row_b)

    cards = dbc.Row(
        [
            dbc.Col(
                build_summary_card(
                    "Solved %",
                    get_val(row_a, "pct_checkpoints_solved"),
                    get_val(row_b, "pct_checkpoints_solved"),
                    "%",
                ),
                md=3,
            ),
            dbc.Col(
                build_summary_card(
                    "Cost ($)",
                    get_val(row_a, "costs.total"),
                    get_val(row_b, "costs.total"),
                    "",
                    invert_better=True,
                ),
                md=3,
            ),
            dbc.Col(
                build_summary_card(
                    "Output Tokens (M)",
                    tokens_a / 1e6,
                    tokens_b / 1e6,
                    "M",
                    invert_better=True,
                ),
                md=3,
            ),
            dbc.Col(
                build_summary_card(
                    "Duration (min)",
                    get_val(row_a, "duration") / 60,
                    get_val(row_b, "duration") / 60,
                    "m",
                    invert_better=True,
                ),
                md=3,
            ),
        ],
        className="mb-4",
    )

    def get_checkpoint_sets(run_path):
        run_data = df_chk[df_chk["run_path"] == run_path]
        if run_data.empty:
            return set(), set()
        passed_checkpoints = set()
        all_attempts = set()
        checkpoint_id_col = "idx" if "idx" in run_data.columns else "checkpoint"
        for _, row in run_data.iterrows():
            chk_tuple = (row["problem"], row[checkpoint_id_col])
            all_attempts.add(chk_tuple)
            if row["passed_chkpt"]:
                passed_checkpoints.add(chk_tuple)
        return passed_checkpoints, all_attempts

    passed_a, attempts_a = get_checkpoint_sets(run_a_path)
    passed_b, attempts_b = get_checkpoint_sets(run_b_path)
    all_checkpoints = attempts_a.union(attempts_b)
    both = len(passed_a.intersection(passed_b))
    only_a = len(passed_a - passed_b)
    only_b = len(passed_b - passed_a)
    passed_any = passed_a.union(passed_b)
    neither = len(all_checkpoints - passed_any)

    overlap_fig = go.Figure()
    overlap_fig.add_trace(
        go.Bar(
            y=["Checkpoints"],
            x=[only_a],
            name="Only Run A",
            orientation="h",
            marker_color="#1f77b4",
        )
    )
    overlap_fig.add_trace(
        go.Bar(
            y=["Checkpoints"],
            x=[both],
            name="Both Passed",
            orientation="h",
            marker_color="#2ca02c",
        )
    )
    overlap_fig.add_trace(
        go.Bar(
            y=["Checkpoints"],
            x=[only_b],
            name="Only Run B",
            orientation="h",
            marker_color="#d62728",
        )
    )
    overlap_fig.add_trace(
        go.Bar(
            y=["Checkpoints"],
            x=[neither],
            name="Neither Passed",
            orientation="h",
            marker_color="#7f7f7f",
        )
    )
    overlap_fig.update_layout(
        barmode="stack",
        title="Checkpoint Pass Overlap",
        xaxis_title="Count",
        yaxis_showticklabels=False,
        legend=dict(
            orientation="h", yanchor="bottom", y=1.1, xanchor="center", x=0.5
        ),
        height=300,
        margin=dict(l=20, r=20, t=80, b=20),
    )

    def short_label(name):
        return (name[:20] + "..") if len(name) > 20 else name

    label_a = short_label(name_a)
    label_b = short_label(name_b)

    cost_fig = make_scatter_checkpoint_level(
        df_chk,
        "cost",
        "Cost per Checkpoint Comparison",
        "$",
        name_a,
        name_b,
        run_a_path,
        run_b_path,
    )
    token_fig = make_scatter_checkpoint_level(
        df_chk,
        "output",
        "Token Usage per Checkpoint Comparison",
        "Tokens",
        name_a,
        name_b,
        run_a_path,
        run_b_path,
    )
    loc_fig = make_scatter_checkpoint_level(
        df_chk,
        "loc",
        "Lines of Code per Checkpoint Comparison",
        "LOC",
        name_a,
        name_b,
        run_a_path,
        run_b_path,
    )

    return cards, overlap_fig, cost_fig, token_fig, loc_fig
