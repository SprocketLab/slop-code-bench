"""Reusable UI components for the dashboard."""

from __future__ import annotations

from collections.abc import Mapping
from collections.abc import Sequence
from typing import Any

import dash_bootstrap_components as dbc
from dash import dcc
from dash import html

# Sidebar styling
SIDEBAR_STYLE = {
    "position": "fixed",
    "top": 0,
    "left": 0,
    "bottom": 0,
    "width": "18rem",
    "padding": "2rem 1rem",
    "background-color": "#ffffff",
    "box-shadow": "2px 0 5px rgba(0,0,0,0.05)",
    "z-index": 100,
    "display": "flex",
    "flex-direction": "column",
}

CONTENT_STYLE = {
    "margin-left": "20rem",
    "margin-right": "2rem",
    "padding": "2rem 1rem",
}


def loading_graph(graph_id: str, *, height: str | None = None) -> dcc.Loading:
    """Create a loading wrapper around a Plotly graph."""

    style: dict[str, Any] = {}
    if height is not None:
        style["height"] = height
    return dcc.Loading(
        dcc.Graph(id=graph_id, style=style),
        color="#32a852",  # A nice green that matches some chart elements
        type="cube",
    )


def build_run_selector_children(
    runs_by_model: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    selected_values: set[str] | None = None,
) -> list[Any]:
    """Build the per-model run selector checklist UI.

    If `selected_values` is `None`, all visible runs are selected.
    """

    run_selectors: list[Any] = []

    for model_name in sorted(runs_by_model.keys()):
        runs = runs_by_model[model_name]
        options = [
            {"label": run["label"], "value": run["value"]} for run in runs
        ]

        if selected_values is None:
            checklist_values = [opt["value"] for opt in options]
        else:
            checklist_values = [
                opt["value"]
                for opt in options
                if opt["value"] in selected_values
            ]

        run_selectors.extend(
            [
                html.H6(
                    model_name,
                    className="mt-3 mb-2 font-weight-bold text-primary",
                ),
                dbc.Checklist(
                    id={"type": "run-selector", "index": model_name},
                    options=options,
                    value=checklist_values,
                    style={"fontSize": "0.9rem"},
                    className="mb-2",
                ),
            ]
        )

    return run_selectors


def sidebar():
    """Create the sidebar component."""

    return html.Div(
        [
            html.Div(
                [
                    html.H2("Slop Code", className="display-6 fw-bold text-primary"),
                    html.Hr(),
                    html.P("Benchmark visualization", className="lead fs-6 text-dark"),
                    dbc.Accordion(
                        [
                            dbc.AccordionItem(
                                dbc.Nav(
                                    [
                                        dbc.NavLink(
                                            [html.I(className="fas fa-home me-2"), "Dashboard"],
                                            href="/",
                                            active="exact"
                                        ),
                                        dbc.NavLink(
                                            [html.I(className="fas fa-chart-scatter me-2"), "Scatter Plots"],
                                            href="/scatter",
                                            active="exact"
                                        ),
                                        dbc.NavLink(
                                            [html.I(className="fas fa-flag-checkered me-2"), "Checkpoints"],
                                            href="/checkpoints",
                                            active="exact"
                                        ),
                                        dbc.NavLink(
                                            [html.I(className="fas fa-vial me-2"), "Test Pass Rates"],
                                            href="/tests",
                                            active="exact"
                                        ),
                                        dbc.NavLink(
                                            [html.I(className="fas fa-scale-balanced me-2"), "Problem Comparison"],
                                            href="/problem_comparison",
                                            active="exact"
                                        ),
                                        dbc.NavLink(
                                            [html.I(className="fas fa-code-branch me-2"), "Code Quality"],
                                            href="/code-quality",
                                            active="exact"
                                        ),
                                        dbc.NavLink(
                                            [html.I(className="fas fa-stopwatch me-2"), "Efficiency"],
                                            href="/efficiency",
                                            active="exact"
                                        ),
                                        dbc.NavLink(
                                            [html.I(className="fas fa-random me-2"), "Quality Deltas"],
                                            href="/quality-deltas",
                                            active="exact"
                                        ),
                                    ],
                                    vertical=True,
                                    pills=True,
                                    className="p-0",
                                ),
                                title="Overview",
                                item_id="overview",
                            ),
                            dbc.AccordionItem(
                                dbc.Nav(
                                    [
                                        dbc.NavLink(
                                            [html.I(className="fas fa-microscope me-2"), "Overview"],
                                            href="/run-analysis",
                                            active="exact"
                                        ),
                                        dbc.NavLink(
                                            [html.I(className="fas fa-cubes me-2"), "Problems"],
                                            href="/run-analysis/problems",
                                            active="exact"
                                        ),
                                        dbc.NavLink(
                                            [html.I(className="fas fa-check-double me-2"), "Quality"],
                                            href="/run-analysis/quality",
                                            active="exact"
                                        ),
                                        dbc.NavLink(
                                            [html.I(className="fas fa-vial-circle-check me-2"), "Tests"],
                                            href="/run-analysis/tests",
                                            active="exact"
                                        ),
                                    ],
                                    vertical=True,
                                    pills=True,
                                    className="p-0",
                                ),
                                title="Run Analysis",
                                item_id="run-analysis",
                            ),
                            dbc.AccordionItem(
                                dbc.Nav(
                                    [
                                        dbc.NavLink(
                                            [html.I(className="fas fa-right-left me-2"), "Overview"],
                                            href="/head-to-head",
                                            active="exact"
                                        ),
                                        dbc.NavLink(
                                            [html.I(className="fas fa-flag-checkered me-2"), "Checkpoints"],
                                            href="/head-to-head/checkpoints",
                                            active="exact"
                                        ),
                                        dbc.NavLink(
                                            [html.I(className="fas fa-code me-2"), "Code Quality"],
                                            href="/head-to-head/quality",
                                            active="exact"
                                        ),
                                        dbc.NavLink(
                                            [html.I(className="fas fa-tachometer-alt me-2"), "Efficiency"],
                                            href="/head-to-head/efficiency",
                                            active="exact"
                                        ),
                                        dbc.NavLink(
                                            [html.I(className="fas fa-history me-2"), "Code Evolution"],
                                            href="/head-to-head/evolution",
                                            active="exact"
                                        ),
                                    ],
                                    vertical=True,
                                    pills=True,
                                    className="p-0",
                                ),
                                title="Head to Head",
                                item_id="head-to-head",
                            ),
                        ],
                        flush=True,
                        always_open=True,
                        active_item=["overview", "run-analysis", "head-to-head"],
                        className="sidebar-accordion",
                    ),
                ],
                style={"flex": "1", "overflowY": "auto", "scrollbarWidth": "thin", "overflowX": "hidden"},
            ),
            html.Div(
                [
                    html.Hr(),
                    dbc.Button(
                        [html.I(className="fas fa-cog me-2"), "Settings"],
                        id="open-settings-modal",
                        color="link",
                        className="text-dark text-decoration-none px-3 w-100 text-start",
                        style={"fontSize": "1rem"},
                    ),
                ],
                className="mt-auto",
            ),
        ],
        style=SIDEBAR_STYLE,
    )
