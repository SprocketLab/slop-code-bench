import dash
import dash_bootstrap_components as dbc
from dash import Input
from dash import Output
from dash import callback
from dash import html

from slop_code.dashboard.components import loading_graph
from slop_code.dashboard.graphs.quality_deltas import build_delta_distribution
from slop_code.dashboard.graphs.quality_deltas import (
    build_delta_improvement_heatmap,
)
from slop_code.dashboard.page_context import build_context
from slop_code.dashboard.page_context import empty_figure

dash.register_page(__name__, path="/quality-deltas")


layout = dbc.Container(
    [
        dbc.Row(
            dbc.Col(
                html.H3(
                    "Quality Deltas",
                    className="display-6 fw-bold text-primary mb-4",
                )
            )
        ),
        dbc.Card(
            [
                dbc.CardHeader(
                    "Delta Distribution per Metric (N -> N+1)",
                    className="fw-bold",
                ),
                dbc.CardBody(
                    loading_graph("quality-deltas-distribution", height="60vh"),
                    className="p-0",
                ),
            ],
            className="shadow-sm border-0 mb-4",
        ),
        dbc.Card(
            [
                dbc.CardHeader(
                    "Improvement Rate by Run",
                    className="fw-bold",
                ),
                dbc.CardBody(
                    loading_graph("quality-deltas-heatmap", height="65vh"),
                    className="p-0",
                ),
            ],
            className="shadow-sm border-0",
        ),
    ],
    fluid=True,
    className="py-3",
)


@callback(
    [
        Output("quality-deltas-distribution", "figure"),
        Output("quality-deltas-heatmap", "figure"),
    ],
    [
        Input("selected-runs-store", "data"),
        Input("filter-settings-store", "data"),
    ],
)
def update_graph(selected_paths, filter_settings):
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
        return empty_figure(), empty_figure()

    direction_fig = build_delta_distribution(context)
    heatmap_fig = build_delta_improvement_heatmap(context)
    return direction_fig, heatmap_fig
