import dash
import dash_bootstrap_components as dbc
from dash import Input
from dash import Output
from dash import callback
from dash import html

from slop_code.dashboard.components import loading_graph
from slop_code.dashboard.graphs.bar import build_bar_comparison
from slop_code.dashboard.graphs.heatmap import build_pass_rate_heatmap
from slop_code.dashboard.page_context import build_context
from slop_code.dashboard.page_context import empty_figure

dash.register_page(__name__, path="/")

layout = dbc.Container(
    [
        dbc.Row(
            dbc.Col(
                html.H3("Dashboard Summary", className="display-6 fw-bold text-primary mb-4"),
            )
        ),
        dbc.Card(
            [
                dbc.CardHeader("Pass Rate Heatmap", className="fw-bold"),
                dbc.CardBody(loading_graph("heatmap-graph"), className="p-0"),
            ],
            className="mb-4 shadow-sm border-0",
        ),
        dbc.Card(
            [
                dbc.CardHeader("Overview Metrics", className="fw-bold"),
                dbc.CardBody(loading_graph("overview-graph", height="500px"), className="p-0"),
            ],
            className="mb-4 shadow-sm border-0",
        ),
    ],
    fluid=True,
    className="py-3",
)


@callback(
    [
        Output("heatmap-graph", "figure"),
        Output("overview-graph", "figure"),
    ],
    [
        Input("selected-runs-store", "data"),
        Input("filter-settings-store", "data"),
    ]
)
def update_view(selected_paths, filter_settings):
    disable_colors = False
    group_runs = False
    common_problems_only = False
    if filter_settings:
        disable_colors = bool(filter_settings.get("disable_colors", []))
        group_runs = bool(filter_settings.get("group_runs", False))
        common_problems_only = bool(filter_settings.get("common_problems_only", False))

    context = build_context(
        selected_paths,
        use_generic_colors=disable_colors,
        group_runs=group_runs,
        common_problems_only=common_problems_only,
    )
    if context is None:
        return empty_figure(), empty_figure()

    heatmap_fig = build_pass_rate_heatmap(context)
    bar_fig = build_bar_comparison(context)

    return heatmap_fig, bar_fig
