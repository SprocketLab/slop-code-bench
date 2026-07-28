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
                dbc.Col(loading_graph("ra-lint-dist", height="350px"), md=6),
                dbc.Col(loading_graph("ra-complex-dist", height="350px"), md=6),
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
        Output("ra-complex-dist", "figure"),
        Output("ra-func-loc-dist", "figure"),
        Output("ra-cmp-loc-dist", "figure"),
        Output("ra-try-loc-dist", "figure"),
        Output("ra-lint-loc-scatter", "figure"),
    ],
    Input("run-analysis-store", "data"),
)
def update_quality(run_path):
    if not run_path:
        return [empty_figure()] * 6

    context = build_context([run_path])
    if context is None or context.checkpoints.empty:
        return [empty_figure()] * 6

    df = context.checkpoints

    # Histograms
    lint_hist = build_histogram(
        df, "lint_errors", "Lint Errors Distribution", "#d62728"
    )
    comp_hist = build_histogram(
        df, "cc_high_count", "Complexity Distribution", "#9467bd"
    )

    func_loc_hist = build_histogram(
        df, "mean_func_loc", "Mean Func LOC Distribution", "#17becf"
    )

    # Compute normalized metrics on the fly
    df = df.copy()
    df["_mass_cc"] = df.get("mass.cc", 0)
    df["_cc_concentration"] = df.get("cc_concentration", 0)

    cmp_loc_hist = build_histogram(
        df,
        "_mass_cc",
        "CC Mass Distribution",
        "#e377c2",
    )
    try_loc_hist = build_histogram(
        df,
        "_cc_concentration",
        "CC Concentration Distribution",
        "#bcbd22",
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
        comp_hist,
        func_loc_hist,
        cmp_loc_hist,
        try_loc_hist,
        scatter,
    )
