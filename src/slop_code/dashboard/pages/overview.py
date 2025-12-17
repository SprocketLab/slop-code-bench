import dash
import dash_bootstrap_components as dbc
from dash import Input
from dash import Output
from dash import callback
from dash import dash_table
from dash import dcc
from dash import html

from slop_code.dashboard.components import loading_graph
from slop_code.dashboard.data import get_summary_table_data
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
        dbc.Card(
            [
                dbc.CardHeader("Run Details", className="fw-bold"),
                dbc.CardBody(dcc.Loading(html.Div(id="overview-table-container"))),
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
        Output("overview-table-container", "children"),
    ],
    [
        Input("selected-runs-store", "data"),
        Input("filter-settings-store", "data"),
    ]
)
def update_view(selected_paths, filter_settings):
    disable_colors = False
    if filter_settings:
        disable_colors = bool(filter_settings.get("disable_colors", []))

    context = build_context(selected_paths, use_generic_colors=disable_colors)
    if context is None:
        return empty_figure(), empty_figure(), None

    heatmap_fig = build_pass_rate_heatmap(context)
    bar_fig = build_bar_comparison(context)
    data = get_summary_table_data(context)

    if not data:
        return heatmap_fig, bar_fig, html.P("No data available.")

    # Define columns with specific formatting if needed
    columns = [
        {"name": "Model", "id": "Model"},
        {"name": "Solved (%)", "id": "Solved (%)", "type": "numeric"},
        {"name": "Partial (%)", "id": "Partial (%)", "type": "numeric"},
        {"name": "Wins", "id": "Wins", "type": "numeric"},
        {
            "name": "Tokens",
            "id": "Tokens",
            "type": "numeric",
            "format": {"specifier": ","},
        },
        {
            "name": "Cost ($)",
            "id": "Cost ($)",
            "type": "numeric",
            "format": {"specifier": "$.2f"},
        },
        {"name": "Time (min)", "id": "Time (min)", "type": "numeric"},
    ]

    table = dash_table.DataTable(
        data=data,
        columns=columns,
        sort_action="native",
        filter_action="native",
        style_cell={
            "textAlign": "left",
            "fontFamily": "Inter, Arial, sans-serif",
            "padding": "10px",
        },
        style_header={
            "backgroundColor": "rgb(230, 230, 230)",
            "fontWeight": "bold",
            "border": "1px solid #ddd",
        },
        style_data={
            "border": "1px solid #ddd",
        },
        style_data_conditional=[
            {
                "if": {"row_index": "odd"},
                "backgroundColor": "rgb(248, 248, 248)",
            }
        ],
        page_size=20,
    )

    return heatmap_fig, bar_fig, table
