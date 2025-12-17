import dash
import dash_bootstrap_components as dbc
from dash import Input
from dash import Output
from dash import callback
from dash import html

from slop_code.dashboard.components import loading_graph
from slop_code.dashboard.data import get_display_annotation
from slop_code.dashboard.graphs.heatmap import build_single_run_heatmap
from slop_code.dashboard.page_context import build_context
from slop_code.dashboard.page_context import empty_figure

dash.register_page(__name__, path="/run-analysis")

layout = dbc.Container(
    [
        dbc.Row(
            dbc.Col(
                html.H3("Run Analysis: Overview", className="display-6 fw-bold text-primary mb-4")
            )
        ),

        html.Div(id="ra-overview-header", className="mb-4"),

        html.Div(id="ra-scorecard", className="mb-4"),

        dbc.Card(
            [
                dbc.CardHeader("Checkpoint Status Heatmap", className="fw-bold"),
                dbc.CardBody(loading_graph("ra-heatmap", height="80vh"), className="p-0"),
            ],
            className="mb-4 shadow-sm border-0",
        ),
    ],
    fluid=True,
    className="py-3",
)

def build_scorecard(summary_row, checkpoints_df):
    if summary_row is None:
        return html.Div("No summary data found.")

    solved = summary_row.get("pct_checkpoints_solved", 0)
    cost = summary_row.get("costs.total", 0)
    duration = summary_row.get("duration", 0) / 60

    tokens = 0
    if "output" in checkpoints_df.columns:
        tokens = checkpoints_df["output"].sum()

    def card(title, value, unit="", color="text-primary"):
        return dbc.Col(
            dbc.Card(
                dbc.CardBody(
                    [
                        html.H6(title, className="text-muted text-uppercase small fw-bold"),
                        html.H2(f"{value}{unit}", className=f"fw-bold {color}"),
                    ]
                ),
                className="shadow-sm border-0 h-100"
            ),
            md=3
        )

    return dbc.Row([
        card("Solved", f"{solved:.1f}", "%", "text-success"),
        card("Total Cost", f"{cost:.2f}", "$"),
        card("Total Tokens", f"{tokens/1e6:.1f}", "M"),
        card("Duration", f"{duration:.0f}", "m"),
    ])

@callback(
    [
        Output("ra-overview-header", "children"),
        Output("ra-scorecard", "children"),
        Output("ra-heatmap", "figure")
    ],
    Input("run-analysis-dropdown", "value")
)
def update_overview(run_path):
    if not run_path:
        return html.Div("Please select a run in Settings.", className="alert alert-info"), None, empty_figure()

    context = build_context([run_path])
    if context is None or context.checkpoints.empty:
        return html.Div("Error loading run data.", className="alert alert-danger"), None, empty_figure()

    # Get metadata
    row = context.run_summaries.iloc[0] if not context.run_summaries.empty else context.checkpoints.iloc[0]
    display_name = get_display_annotation(row)

    header = html.H4(f"Analyzing: {display_name}", className="text-muted")
    scorecard = build_scorecard(row if not context.run_summaries.empty else None, context.checkpoints)
    heatmap = build_single_run_heatmap(context)

    return header, scorecard, heatmap
