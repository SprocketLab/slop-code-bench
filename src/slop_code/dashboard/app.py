"""Main entry point for the Slop Code Dashboard."""

import argparse
import sys
from collections import defaultdict
from pathlib import Path

import dash
import dash_bootstrap_components as dbc
from dash import Input
from dash import Output
from dash import dcc
from dash import html

from slop_code.dashboard.components import CONTENT_STYLE
from slop_code.dashboard.components import sidebar
from slop_code.dashboard.data import get_available_runs
from slop_code.dashboard.data import get_display_annotation
from slop_code.dashboard.data import load_config_metadata
from slop_code.dashboard.settings_callbacks import register_settings_callbacks
from slop_code.dashboard.settings_content import (
    build_configuration_modal_content,
)
from slop_code.dashboard.settings_content import build_h2h_modal_content
from slop_code.dashboard.settings_content import (
    build_run_analysis_modal_content,
)

# We need to parse args before Dash touches them
# But if we run via `python -m slop_code.dashboard.app`, sys.argv[0] is the script
# dash.Dash might interfere if we just let it run.
# So we parse known args.

parser = argparse.ArgumentParser(description="Slop Code Dashboard")
parser.add_argument("runs_dir", type=str, help="Path to the runs directory")
# Dash adds its own arguments if we aren't careful, so use parse_known_args
args, unknown = parser.parse_known_args()

runs_dir = Path(args.runs_dir)
if not runs_dir.exists():
    print(f"Error: Directory {runs_dir} does not exist.")
    sys.exit(1)


def get_thinking_display_str(thinking: str) -> str:
    """Get display string for thinking mode."""
    if not thinking or thinking.lower() in ["false", "none", "disabled"]:
        return "disabled"
    if thinking.lower() == "true":
        return "enabled"
    return thinking.lower()


# Find runs

print(f"Scanning for runs in {runs_dir}...")

available_run_paths = get_available_runs(runs_dir)

run_options = []
runs_by_model = defaultdict(list)
all_run_values = []
all_metadata_list = []
thinking_modes_seen = set()
all_dates = []
max_problems_found = 0

for run_path in available_run_paths:
    try:
        metadata = load_config_metadata(run_path)

        # Use get_display_annotation for consistent formatting
        display_label = get_display_annotation(metadata)
        model_name = metadata.get("model_name", "Unknown Model")

        # Get thinking display for grouping
        thinking = str(metadata.get("thinking", ""))
        thinking_display = get_thinking_display_str(thinking)
        thinking_modes_seen.add(thinking_display)

        date = metadata.get("run_date", "")
        if date:
            all_dates.append(date)

        num_problems = metadata.get("num_problems", 0)
        if num_problems > max_problems_found:
            max_problems_found = num_problems

        val = str(run_path.absolute())

        run_info = {
            "label": display_label,
            "value": val,
            "model_name": model_name,
            "agent_type": metadata.get("agent_type", "Unknown Agent"),
            "agent_version": metadata.get("agent_version", ""),
            "prompt_template": metadata.get(
                "prompt_template", "Unknown Prompt"
            ),
            "thinking_display": thinking_display,
            "run_date": date,
            "num_problems": num_problems,
        }

        # Group by model + thinking mode
        group_key = f"{model_name} ({thinking_display})"
        runs_by_model[group_key].append(run_info)
        all_run_values.append(val)
        all_metadata_list.append(run_info)

    except Exception as e:
        print(
            f"Warning: Could not load metadata for run {run_path.name}: {e}. Skipping."
        )


if not all_run_values:
    print(
        f"No runs found in {runs_dir} (looking for {runs_dir}/*/checkpoints.jsonl and valid config.yaml)"
    )
else:
    print(
        f"Found {len(all_run_values)} runs across {len(runs_by_model)} models."
    )

# Compute filter ranges
thinking_options = sorted(list(thinking_modes_seen))
if all_dates:
    min_date = min(all_dates)
    max_date = max(all_dates)
else:
    min_date = "2024-01-01"
    max_date = "2025-12-31"

# Initialize Dash app
app = dash.Dash(
    __name__,
    use_pages=True,
    external_stylesheets=[dbc.themes.ZEPHYR, dbc.icons.FONT_AWESOME],
    suppress_callback_exceptions=True,
)

app_config = {
    "min_date": min_date,
    "max_date": max_date,
    "thinking_options": thinking_options,
    "max_problems_found": max_problems_found,
}

# Register global callbacks for settings
register_settings_callbacks(app)

app.layout = html.Div(
    [
        # Store for client-side filtering (optional, but good practice if list is large)
        # Here we use a server-side callback with global data for simplicity or pass data in store
        dcc.Store(id="all-runs-metadata", data=all_metadata_list),
        dcc.Store(id="app-config-store", data=app_config),
        # Store for persisting filter settings across page navigations
        dcc.Store(id="filter-settings-store", storage_type="session"),
        # Store for persisting Head-to-Head run selections
        dcc.Store(id="h2h-store", storage_type="session"),
        # Store for persisting Run Analysis selection
        dcc.Store(id="run-analysis-store", storage_type="session"),
        # Store for persisting Accordion state (expanded items)
        dcc.Store(id="accordion-state-store", storage_type="session"),
        # Default to selecting all runs initially
        dcc.Store(
            id="selected-runs-store",
            data=all_run_values,
            storage_type="session",
        ),
        dcc.Location(id="url", refresh=False),
        sidebar(),
        html.Div(dash.page_container, style=CONTENT_STYLE),
        # Redefine Modal here with pre-populated content
        dbc.Modal(
            [
                dbc.ModalHeader(
                    dbc.ModalTitle("Configuration"), id="settings-modal-header"
                ),
                dbc.ModalBody(
                    [
                        html.Div(
                            build_configuration_modal_content(),
                            id="settings-content-global",
                            style={"display": "none"},
                        ),
                        html.Div(
                            build_h2h_modal_content(),
                            id="settings-content-h2h",
                            style={"display": "none"},
                        ),
                        html.Div(
                            build_run_analysis_modal_content(),
                            id="settings-content-ra",
                            style={"display": "none"},
                        ),
                    ],
                    id="settings-modal-body",
                ),
                dbc.ModalFooter(
                    dbc.Button(
                        "Close",
                        id="close-settings-modal",
                        className="ms-auto",
                        n_clicks=0,
                    )
                ),
            ],
            id="settings-modal",
            is_open=False,
            size="xl",
            centered=True,
        ),
    ]
)


@app.callback(
    Output("settings-modal", "is_open"),
    Output("settings-content-global", "style"),
    Output("settings-content-h2h", "style"),
    Output("settings-content-ra", "style"),
    Output("settings-modal-header", "children"),
    Input("open-settings-modal", "n_clicks"),
    Input("close-settings-modal", "n_clicks"),
    dash.State("settings-modal", "is_open"),
    dash.State("url", "pathname"),
)
def toggle_settings_modal(n_open, n_close, is_open, pathname):
    if n_open or n_close:
        if dash.ctx.triggered_id == "open-settings-modal":
            # Determine content based on the current page (pathname)

            style_g = {"display": "none"}
            style_h = {"display": "none"}
            style_r = {"display": "none"}
            title_text = "Configuration"

            if pathname and pathname.startswith("/head-to-head"):
                title_text = "Head to Head Configuration"
                style_h = {"display": "block"}
            elif pathname and pathname.startswith("/run-analysis"):
                title_text = "Run Analysis Configuration"
                style_r = {"display": "block"}
            else:
                # Default for Overview, Scatter, Checkpoints, Tests, Problem Comparison
                title_text = "Global Configuration"
                style_g = {"display": "block"}

            return True, style_g, style_h, style_r, dbc.ModalTitle(title_text)

        return (
            False,
            dash.no_update,
            dash.no_update,
            dash.no_update,
            dash.no_update,
        )

    return (
        is_open,
        dash.no_update,
        dash.no_update,
        dash.no_update,
        dash.no_update,
    )


if __name__ == "__main__":
    app.run(debug=True)
