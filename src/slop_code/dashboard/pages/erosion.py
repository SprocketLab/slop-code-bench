"""Erosion metrics page - mass delta analysis across checkpoints."""

import dash
import dash_bootstrap_components as dbc
from dash import Input
from dash import Output
from dash import callback
from dash import html

from slop_code.dashboard.components import loading_graph
from slop_code.dashboard.graphs.erosion import build_delta_vs_solve_scatter
from slop_code.dashboard.graphs.erosion import build_mass_delta_bars
from slop_code.dashboard.graphs.erosion import build_mass_delta_boxplots
from slop_code.dashboard.graphs.erosion import build_mass_delta_heatmap
from slop_code.dashboard.graphs.erosion import build_other_mass_metrics
from slop_code.dashboard.graphs.erosion import build_symbol_sprawl
from slop_code.dashboard.graphs.erosion import build_velocity_metrics
from slop_code.dashboard.page_context import build_context
from slop_code.dashboard.page_context import empty_figure

dash.register_page(__name__, path="/erosion")

layout = dbc.Container(
    [
        dbc.Row(
            dbc.Col(
                html.H3(
                    "Erosion Metrics",
                    className="display-6 fw-bold text-primary mb-4",
                )
            )
        ),
        # Top row: Delta bars and scatter
        dbc.Row(
            [
                dbc.Col(
                    dbc.Card(
                        [
                            dbc.CardHeader(
                                "Mass Delta Overview", className="fw-bold"
                            ),
                            dbc.CardBody(
                                loading_graph(
                                    "erosion-delta-bars", height="400px"
                                ),
                                className="p-0",
                            ),
                        ],
                        className="shadow-sm border-0 h-100",
                    ),
                    md=6,
                ),
                dbc.Col(
                    dbc.Card(
                        [
                            dbc.CardHeader(
                                "Mass Delta vs Solve Rate", className="fw-bold"
                            ),
                            dbc.CardBody(
                                loading_graph(
                                    "erosion-scatter", height="400px"
                                ),
                                className="p-0",
                            ),
                        ],
                        className="shadow-sm border-0 h-100",
                    ),
                    md=6,
                ),
            ],
            className="mb-4",
        ),
        # Velocity metrics
        dbc.Card(
            [
                dbc.CardHeader("Velocity Metrics", className="fw-bold"),
                dbc.CardBody(
                    loading_graph("erosion-velocity", height="400px"),
                    className="p-0",
                ),
            ],
            className="shadow-sm border-0 mb-4",
        ),
        # Symbol sprawl
        dbc.Card(
            [
                dbc.CardHeader(
                    "Symbol Sprawl vs Refactoring", className="fw-bold"
                ),
                dbc.CardBody(
                    loading_graph("erosion-sprawl", height="400px"),
                    className="p-0",
                ),
            ],
            className="shadow-sm border-0 mb-4",
        ),
        # Heatmap - high complexity concentration
        dbc.Card(
            [
                dbc.CardHeader(
                    "High Complexity Mass by Problem", className="fw-bold"
                ),
                dbc.CardBody(
                    loading_graph("erosion-delta-heatmap"),
                    className="p-0",
                ),
            ],
            className="shadow-sm border-0 mb-4",
        ),
        # Box plots - complexity distribution
        dbc.Card(
            [
                dbc.CardHeader("Mass Delta Distributions", className="fw-bold"),
                dbc.CardBody(
                    loading_graph("erosion-delta-boxplots", height="600px"),
                    className="p-0",
                ),
            ],
            className="shadow-sm border-0 mb-4",
        ),
        # Other mass metrics - median relative changes
        dbc.Card(
            [
                dbc.CardHeader(
                    "Mass Metrics (Median % Change)", className="fw-bold"
                ),
                dbc.CardBody(
                    loading_graph("erosion-other-mass", height="450px"),
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
        Output("erosion-delta-bars", "figure"),
        Output("erosion-scatter", "figure"),
        Output("erosion-velocity", "figure"),
        Output("erosion-sprawl", "figure"),
        Output("erosion-delta-heatmap", "figure"),
        Output("erosion-delta-boxplots", "figure"),
        Output("erosion-other-mass", "figure"),
    ],
    [
        Input("selected-runs-store", "data"),
        Input("filter-settings-store", "data"),
    ],
)
def update_erosion_graphs(selected_paths, filter_settings):
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
        return (
            empty_figure(),
            empty_figure(),
            empty_figure(),
            empty_figure(),
            empty_figure(),
            empty_figure(),
            empty_figure(),
        )

    delta_bars = build_mass_delta_bars(context)
    delta_scatter = build_delta_vs_solve_scatter(context)
    velocity = build_velocity_metrics(context)
    sprawl = build_symbol_sprawl(context)
    delta_heatmap = build_mass_delta_heatmap(context)
    delta_boxplots = build_mass_delta_boxplots(context)
    other_mass = build_other_mass_metrics(context)

    return (
        delta_bars,
        delta_scatter,
        velocity,
        sprawl,
        delta_heatmap,
        delta_boxplots,
        other_mass,
    )
