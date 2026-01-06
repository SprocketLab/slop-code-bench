import dash
import dash_bootstrap_components as dbc
from dash import Input
from dash import Output
from dash import callback
from dash import dash_table
from dash import dcc
from dash import html

from slop_code.dashboard.data import get_summary_table_data
from slop_code.dashboard.page_context import build_context

dash.register_page(__name__, path="/tables")

layout = dbc.Container(
    [
        dbc.Row(
            dbc.Col(
                html.H3(
                    "Run Details Table",
                    className="display-6 fw-bold text-primary mb-4",
                ),
            )
        ),
        dbc.Card(
            [
                dbc.CardHeader("Run Details", className="fw-bold"),
                dbc.CardBody(dcc.Loading(html.Div(id="tables-container"))),
            ],
            className="mb-4 shadow-sm border-0",
        ),
    ],
    fluid=True,
    className="py-3",
)


@callback(
    Output("tables-container", "children"),
    [
        Input("selected-runs-store", "data"),
        Input("filter-settings-store", "data"),
    ],
)
def update_table(selected_paths, filter_settings):
    disable_colors = False
    group_runs = False
    common_problems_only = False
    if filter_settings:
        disable_colors = bool(filter_settings.get("disable_colors", []))
        group_runs = bool(filter_settings.get("group_runs", False))
        common_problems_only = bool(
            filter_settings.get("common_problems_only", False)
        )

    context = build_context(
        selected_paths,
        use_generic_colors=disable_colors,
        group_runs=group_runs,
        common_problems_only=common_problems_only,
    )
    if context is None:
        return html.P("No data available.")

    data = get_summary_table_data(context)

    if not data:
        return html.P("No data available.")

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

    return table
