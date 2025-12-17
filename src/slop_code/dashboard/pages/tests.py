import dash
import dash_bootstrap_components as dbc
from dash import Input
from dash import Output
from dash import callback
from dash import html

from slop_code.dashboard.components import loading_graph
from slop_code.dashboard.graphs.test_pass import build_test_pass_rate_bars
from slop_code.dashboard.page_context import build_context
from slop_code.dashboard.page_context import empty_figure

dash.register_page(__name__, path='/tests')

layout = dbc.Container(
    [
        dbc.Row(dbc.Col(html.H3("Test Pass Rates", className="display-6 fw-bold text-primary mb-4"))),
        dbc.Card(
            dbc.CardBody(loading_graph("tests-graph", height="80vh")),
            className="shadow-sm border-0",
        ),
    ],
    fluid=True,
    className="py-3",
)

@callback(
    Output("tests-graph", "figure"),
    [
        Input("selected-runs-store", "data"),
        Input("filter-settings-store", "data"),
    ]
)
def update_graph(selected_paths, filter_settings):
    disable_colors = False
    if filter_settings:
        disable_colors = bool(filter_settings.get("disable_colors", []))

    context = build_context(selected_paths, use_generic_colors=disable_colors)
    if context is None:
        return empty_figure()
    return build_test_pass_rate_bars(context)
