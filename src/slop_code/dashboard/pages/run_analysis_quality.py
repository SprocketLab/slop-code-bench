import dash
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
from dash import Input
from dash import Output
from dash import callback
from dash import html

from slop_code.dashboard.components import loading_graph
from slop_code.dashboard.page_context import build_context
from slop_code.dashboard.page_context import empty_figure

dash.register_page(__name__, path="/run-analysis/quality")

layout = dbc.Container(
    [
        dbc.Row(
            dbc.Col(
                html.H3(
                    "Run Analysis: Code Quality",
                    className="display-6 fw-bold text-primary mb-4",
                )
            )
        ),
        dbc.Row(
            [
                dbc.Col(loading_graph("ra-lint-dist", height="350px"), md=4),
                dbc.Col(loading_graph("ra-ast-grep-dist", height="350px"), md=4),
                dbc.Col(loading_graph("ra-complex-dist", height="350px"), md=4),
            ],
            className="mb-4",
        ),
        dbc.Row(
            [
                dbc.Col(
                    loading_graph("ra-func-loc-dist", height="350px"), md=4
                ),
                dbc.Col(loading_graph("ra-cmp-loc-dist", height="350px"), md=4),
                dbc.Col(loading_graph("ra-try-loc-dist", height="350px"), md=4),
            ],
            className="mb-4",
        ),
        dbc.Card(
            [
                dbc.CardHeader("Lint Errors vs LOC", className="fw-bold"),
                dbc.CardBody(
                    loading_graph("ra-lint-loc-scatter", height="500px")
                ),
            ],
            className="mb-4 shadow-sm border-0",
        ),
    ],
    fluid=True,
    className="py-3",
)


def build_histogram(df, col, title, color):
    if col not in df.columns:
        return empty_figure()
    fig = go.Figure(data=[go.Histogram(x=df[col], marker_color=color)])
    fig.update_layout(
        title=title,
        xaxis_title="Value",
        yaxis_title="Frequency",
        plot_bgcolor="white",
        margin=dict(l=40, r=40, t=50, b=40),
    )
    return fig


@callback(
    [
        Output("ra-lint-dist", "figure"),
        Output("ra-ast-grep-dist", "figure"),
        Output("ra-complex-dist", "figure"),
        Output("ra-func-loc-dist", "figure"),
        Output("ra-cmp-loc-dist", "figure"),
        Output("ra-try-loc-dist", "figure"),
        Output("ra-lint-loc-scatter", "figure"),
    ],
    Input("run-analysis-dropdown", "value"),
)
def update_quality(run_path):
    if not run_path:
        return [empty_figure()] * 7

    context = build_context([run_path])
    if context is None or context.checkpoints.empty:
        return [empty_figure()] * 7

    df = context.checkpoints

    # Histograms
    lint_hist = build_histogram(
        df, "lint_errors", "Lint Errors Distribution", "#d62728"
    )
    ast_grep_hist = build_histogram(
        df, "ast_grep_violations", "AST-grep Violations Distribution", "#ff7f0e"
    )
    comp_hist = build_histogram(
        df, "cc_high_count", "Complexity Distribution", "#9467bd"
    )

    func_loc_hist = build_histogram(
        df, "mean_func_loc", "Mean Func LOC Distribution", "#17becf"
    )

    # Compute normalized metrics on the fly
    if "comparisons" in df.columns and "loc" in df.columns:
        df = df.copy()
        df["_cmp_per_loc"] = df["comparisons"] / df["loc"].replace(0, 1)
        df["_try_per_loc"] = df["try_scaffold"] / df["loc"].replace(0, 1)
    else:
        df = df.copy()
        df["_cmp_per_loc"] = 0
        df["_try_per_loc"] = 0

    cmp_loc_hist = build_histogram(
        df,
        "_cmp_per_loc",
        "Comparisons/LOC Distribution",
        "#e377c2",
    )
    try_loc_hist = build_histogram(
        df, "_try_per_loc", "Try/LOC Distribution", "#bcbd22"
    )

    # Scatter
    scatter = go.Figure()
    scatter.add_trace(
        go.Scatter(
            x=df.get("loc", []),
            y=df.get("lint_errors", []),
            mode="markers",
            text=df.get("problem", []),
            hovertemplate="<b>Problem:</b> %{text}<br><b>LOC:</b> %{x}<br><b>Lint:</b> %{y}<extra></extra>",
            marker=dict(size=8, color="#17becf", opacity=0.6),
        )
    )
    scatter.update_layout(
        title="Lint Errors vs Lines of Code (All Checkpoints)",
        xaxis_title="LOC",
        yaxis_title="Lint Errors",
        plot_bgcolor="white",
    )

    return (
        lint_hist,
        ast_grep_hist,
        comp_hist,
        func_loc_hist,
        cmp_loc_hist,
        try_loc_hist,
        scatter,
    )
