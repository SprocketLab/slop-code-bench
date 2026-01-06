import dash
import dash_bootstrap_components as dbc
from dash import Input
from dash import Output
from dash import callback
from dash import html

from slop_code.dashboard.components import loading_graph
from slop_code.dashboard.graphs.bar import build_efficiency_bars
from slop_code.dashboard.page_context import build_context
from slop_code.dashboard.page_context import empty_figure

dash.register_page(__name__, path='/efficiency')

layout = dbc.Container(
    [
        dbc.Row(dbc.Col(html.H3("Efficiency Comparison", className="display-6 fw-bold text-primary mb-4"))),
        dbc.Card(
            [
                dbc.CardHeader("Resource Usage (Average across runs)", className="fw-bold"),
                dbc.CardBody(loading_graph("efficiency-graph", height="500px"), className="p-0"),
            ],
            className="shadow-sm border-0",
        ),
    ],
    fluid=True,
    className="py-3",
)

@callback(
    Output("efficiency-graph", "figure"),
    [
        Input("selected-runs-store", "data"),
        Input("filter-settings-store", "data"),
    ]
)
def update_graph(selected_paths, filter_settings):
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
        return empty_figure()
    return build_efficiency_bars(context)
