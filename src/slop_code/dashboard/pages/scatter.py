import dash
import dash_bootstrap_components as dbc
from dash import Input
from dash import Output
from dash import callback
from dash import html

from slop_code.dashboard.components import loading_graph
from slop_code.dashboard.graphs.scatter import SCATTER_CHARTS
from slop_code.dashboard.graphs.scatter import build_multi_scatter_chart
from slop_code.dashboard.graphs.scatter import build_scatter_chart
from slop_code.dashboard.page_context import build_context
from slop_code.dashboard.page_context import empty_figure

dash.register_page(__name__, path="/scatter")

# Create tabs for each scatter chart type
tabs = []
for key in SCATTER_CHARTS:
    tabs.append(dbc.Tab(label=key.replace("_", " ").title(), tab_id=key))

layout = dbc.Container(
    [
        dbc.Row(
            [
                dbc.Col(
                    html.H3(
                        "Scatter Plots",
                        className="display-6 fw-bold text-primary mb-4",
                    )
                ),
                dbc.Col(
                    dbc.Switch(
                        id="grid-view-switch",
                        label="Grid View",
                        value=False,
                        className="float-end mt-2",
                    ),
                    width="auto",
                ),
            ],
            className="align-items-center",
        ),
        dbc.Card(
            [
                dbc.CardHeader(
                    dbc.Tabs(
                        tabs,
                        id="scatter-tabs",
                        active_tab="verbosity_vs_solve",
                        className="nav-fill border-0",
                    ),
                    className="bg-light",
                ),
                dbc.CardBody(loading_graph("scatter-graph", height="75vh")),
            ],
            className="shadow-sm border-0",
        ),
    ],
    fluid=True,
    className="py-3",
)


@callback(
    Output("scatter-graph", "figure"),
    [
        Input("selected-runs-store", "data"),
        Input("scatter-tabs", "active_tab"),
        Input("filter-settings-store", "data"),
        Input("grid-view-switch", "value"),
    ],
)
def update_graph(selected_paths, active_tab, filter_settings, grid_view):
    disable_colors = False
    show_annotations = False
    group_runs = False
    common_problems_only = False
    if filter_settings:
        disable_colors = bool(filter_settings.get("disable_colors", []))
        show_annotations = bool(filter_settings.get("show_annotations", False))
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
        return empty_figure()

    if grid_view:
        return build_multi_scatter_chart(
            context,
            list(SCATTER_CHARTS.keys()),
            cols=3,
            show_annotations=show_annotations,
        )

    if not active_tab:
        return empty_figure()

    return build_scatter_chart(
        context, active_tab, show_annotations=show_annotations
    )
