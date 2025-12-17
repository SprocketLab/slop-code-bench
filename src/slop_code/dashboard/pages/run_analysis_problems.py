import dash
import dash_bootstrap_components as dbc
import pandas as pd
import plotly.graph_objects as go
from dash import Input
from dash import Output
from dash import callback
from dash import dash_table
from dash import html

from slop_code.dashboard.components import loading_graph
from slop_code.dashboard.page_context import build_context
from slop_code.dashboard.page_context import empty_figure

dash.register_page(__name__, path="/run-analysis/problems")

layout = dbc.Container(
    [
        dbc.Row(
            dbc.Col(
                html.H3("Run Analysis: Problem Performance", className="display-6 fw-bold text-primary mb-4")
            )
        ),

        dbc.Row([
            dbc.Col(
                dbc.Card(
                    [
                        dbc.CardHeader("Cost vs Success (Per Problem)", className="fw-bold"),
                        dbc.CardBody(loading_graph("ra-problem-scatter", height="500px")),
                    ],
                    className="mb-4 shadow-sm border-0"
                ),
                md=12
            )
        ]),

        dbc.Card(
            [
                dbc.CardHeader("Problem Details", className="fw-bold"),
                dbc.CardBody(html.Div(id="ra-problem-table")),
            ],
            className="mb-4 shadow-sm border-0",
        ),
    ],
    fluid=True,
    className="py-3",
)

def build_problem_scatter(df):
    # Aggregate per problem
    # Total Cost, Max Checkpoint Index Passed? Or % Passed?

    chkpt_col = "idx" if "idx" in df.columns else "checkpoint"

    def agg_problem(group):
        total_cost = group["cost"].sum() if "cost" in group.columns else 0
        total_tokens = group["output"].sum() if "output" in group.columns else 0

        # Pass rate
        passed_count = group["passed_chkpt"].sum()
        total_count = len(group)
        pass_rate = (passed_count / total_count * 100) if total_count > 0 else 0

        return pd.Series({
            "cost": total_cost,
            "tokens": total_tokens,
            "pass_rate": pass_rate,
            "checkpoints": total_count
        })

    prob_stats = df.groupby("problem").apply(agg_problem).reset_index()

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=prob_stats["pass_rate"],
        y=prob_stats["cost"],
        mode="markers",
        text=prob_stats["problem"],
        hovertemplate="<b>Problem:</b> %{text}<br><b>Pass Rate:</b> %{x:.1f}%<br><b>Cost:</b> $%{y:.2f}<extra></extra>",
        marker=dict(
            size=12,
            color=prob_stats["tokens"], # Color by tokens?
            colorscale="Viridis",
            showscale=True,
            colorbar=dict(title="Tokens")
        )
    ))

    fig.update_layout(
        title="Cost vs Checkpoint Pass Rate",
        xaxis_title="Pass Rate (%)",
        yaxis_title="Total Cost ($)",
        plot_bgcolor="white",
        hovermode="closest"
    )
    fig.update_xaxes(showgrid=True, gridcolor='#f0f0f0')
    fig.update_yaxes(showgrid=True, gridcolor='#f0f0f0')

    return fig

def build_problem_table(df):
    chkpt_col = "idx" if "idx" in df.columns else "checkpoint"

    def agg_problem(group):
        total_cost = group["cost"].sum() if "cost" in group.columns else 0
        total_tokens = group["output"].sum() if "output" in group.columns else 0
        passed_count = group["passed_chkpt"].sum()
        total_count = len(group)
        pass_rate = (passed_count / total_count * 100) if total_count > 0 else 0

        return pd.Series({
            "Cost ($)": round(total_cost, 2),
            "Tokens": int(total_tokens),
            "Pass Rate (%)": round(pass_rate, 1),
            "Checkpoints": total_count
        })

    prob_stats = df.groupby("problem").apply(agg_problem).reset_index()
    prob_stats = prob_stats.sort_values("Cost ($)", ascending=False)

    return dash_table.DataTable(
        data=prob_stats.to_dict("records"),
        columns=[{"name": i, "id": i} for i in prob_stats.columns],
        sort_action="native",
        filter_action="native",
        page_size=15,
        style_cell={'textAlign': 'left', 'padding': '10px'},
        style_header={'fontWeight': 'bold', 'backgroundColor': '#f8f9fa'},
        style_data_conditional=[
            {
                'if': {'row_index': 'odd'},
                'backgroundColor': 'rgb(248, 248, 248)'
            }
        ]
    )

@callback(
    [Output("ra-problem-scatter", "figure"), Output("ra-problem-table", "children")],
    Input("run-analysis-dropdown", "value")
)
def update_problems(run_path):
    if not run_path:
        return empty_figure(), html.Div("Select a run.")

    context = build_context([run_path])
    if context is None or context.checkpoints.empty:
        return empty_figure(), html.Div("No data.")

    scatter = build_problem_scatter(context.checkpoints)
    table = build_problem_table(context.checkpoints)

    return scatter, table
