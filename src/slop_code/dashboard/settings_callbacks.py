from __future__ import annotations

import json
from pathlib import Path

from dash import ALL
from dash import ClientsideFunction
from dash import Input
from dash import Output
from dash import State
from dash import callback_context
from dash import no_update

from slop_code.dashboard.settings_content import build_hierarchical_run_selector
from slop_code.dashboard.settings_content import (
    build_hierarchical_run_selector_single,
)


def _manage_run_selection_logic(
    start_date, end_date, min_problems, selected_thinking,
    appearance_options,
    select_all_n_clicks, deselect_all_n_clicks,
    group_switch_values, subgroup_switch_values, selected_values_groups,
    all_runs, current_selection, saved_settings, accordion_state, ctx
):
    """
    Extracted logic for manage_run_selection to facilitate testing.
    'ctx' is passed explicitly.
    """
    # Use rsplit to only split off the property (e.g. '.value') from the end
    # This preserves dots inside the JSON ID (like "gpt-5.2")
    triggered_id = ctx.triggered[0]["prop_id"].rsplit(".", 1)[0] if ctx.triggered else None

    if not all_runs:
        return [], [], no_update

    min_problems = min_problems or 0
    selected_thinking = set(selected_thinking or [])
    appearance_options = appearance_options or []
    disable_colors = ["disable_colors"] if "disable_colors" in appearance_options else []
    show_annotations = "show_annotations" in appearance_options

    # --- Step 1: Check for "Filters Changed" ---
    current_filters = {
        "start_date": start_date,
        "end_date": end_date,
        "thinking_value": sorted(list(selected_thinking)),
        "min_problems": min_problems,
        "disable_colors": disable_colors,
        "show_annotations": show_annotations
    }

    saved_filters_compare = {}
    if saved_settings:
        saved_filters_compare = {
            "start_date": saved_settings.get("start_date"),
            "end_date": saved_settings.get("end_date"),
            "thinking_value": sorted(saved_settings.get("thinking_value", [])),
            "min_problems": saved_settings.get("min_problems", 0),
            "disable_colors": saved_settings.get("disable_colors", []),
            "show_annotations": saved_settings.get("show_annotations", False)
        }

    filters_changed = current_filters != saved_filters_compare

    # --- Step 2: Apply Filters ---
    visible_runs = []
    visible_run_values = []

    for run in all_runs:
        # Date Filter
        r_date = run.get("run_date", "")
        if start_date and r_date and r_date < start_date:
            continue
        if end_date and r_date and r_date > end_date:
            continue

        # Thinking Filter
        if run.get("thinking_display") not in selected_thinking:
            continue

        # Min Problems Filter
        if run.get("num_problems", 0) < min_problems:
            continue

        visible_runs.append(run)
        visible_run_values.append(run["value"])

    # --- Step 3: Selection Logic ---
    new_selection = []

    if triggered_id == "select-all-button":
        new_selection = visible_run_values

    elif triggered_id == "deselect-all-button":
        new_selection = []

    elif triggered_id and "group-select-switch" in triggered_id:
            # Parse triggered index (parent directory name)
            try:
                triggered_idx = json.loads(triggered_id)["index"]
            except (json.JSONDecodeError, KeyError):
                triggered_idx = None

            # Get the value from the context
            is_selected = ctx.triggered[0]['value']

            if triggered_idx:
                # Find runs in this group
                group_runs = [r for r in visible_runs if Path(r["value"]).parent.name == triggered_idx]
                group_ids = set(r["value"] for r in group_runs)

                current_sel_set = set(current_selection or [])

                if is_selected:
                    new_selection = list(current_sel_set.union(group_ids))
                else:
                    new_selection = list(current_sel_set - group_ids)
            else:
                new_selection = current_selection if current_selection is not None else visible_run_values

    elif triggered_id and "subgroup-select-switch" in triggered_id:
            try:
                triggered_idx = json.loads(triggered_id)["index"] # "Parent|Prompt"
                parts = triggered_idx.split("|")
                parent_part = parts[0]
                prompt_part = parts[1] if len(parts) > 1 else "Unknown"
            except (json.JSONDecodeError, KeyError, IndexError):
                triggered_idx = None

            is_selected = ctx.triggered[0]['value']

            if triggered_idx:
                group_runs = [
                    r for r in visible_runs
                    if Path(r["value"]).parent.name == parent_part
                    and r.get("prompt_template", "Unknown") == prompt_part
                ]
                group_ids = set(r["value"] for r in group_runs)
                current_sel_set = set(current_selection or [])

                if is_selected:
                    new_selection = list(current_sel_set.union(group_ids))
                else:
                    new_selection = list(current_sel_set - group_ids)
            else:
                new_selection = current_selection if current_selection is not None else visible_run_values

    elif triggered_id and triggered_id.startswith('{"index"'):
        # Triggered by run selector (individual checkbox)
        # Flatten list of lists
        new_selection = [val for group in selected_values_groups if group for val in group]

    elif filters_changed:
        # If filters changed, reset to visible (or keep previous intersection?)
        # Usually we reset to all visible matching filters, or keep existing.
        # Here we default to all visible if filters changed.
        new_selection = visible_run_values

    else:
        if current_selection is not None:
                visible_set = set(visible_run_values)
                new_selection = [r for r in current_selection if r in visible_set]
        else:
                new_selection = visible_run_values

    # --- Step 4: Build UI ---
    run_selectors = build_hierarchical_run_selector(
        visible_runs,
        selected_values=set(new_selection),
        active_items=accordion_state,
    )

    new_saved_settings = {
        "start_date": start_date,
        "end_date": end_date,
        "thinking_value": list(selected_thinking),
        "min_problems": min_problems,
        "disable_colors": disable_colors,
        "show_annotations": show_annotations
    }

    return run_selectors, new_selection, new_saved_settings


def register_settings_callbacks(app):

    @app.callback(
        Output("date-filter", "min_date_allowed"),
        Output("date-filter", "max_date_allowed"),
        Output("date-filter", "start_date"),
        Output("date-filter", "end_date"),
        Output("thinking-filter", "options"),
        Output("thinking-filter", "value"),
        Output("min-problems-filter", "value"),
        Output("appearance-options", "value"),
        Input("app-config-store", "data"),
        State("filter-settings-store", "data")
    )
    def init_filters(app_config, saved_settings):
        if not app_config:
            return no_update, no_update, no_update, no_update, [], [], 0, []

        min_date = app_config.get("min_date")
        max_date = app_config.get("max_date")
        thinking_options = app_config.get("thinking_options", [])

        # Default values
        start_date = min_date
        end_date = max_date
        thinking_value = thinking_options
        min_problems = app_config.get("max_problems_found", 0)
        disable_colors = []
        show_annotations = False

        # Override with saved settings if available
        if saved_settings:
            start_date = saved_settings.get("start_date", start_date)
            end_date = saved_settings.get("end_date", end_date)
            thinking_value = saved_settings.get("thinking_value", thinking_value)
            min_problems = saved_settings.get("min_problems", min_problems)
            disable_colors = saved_settings.get("disable_colors", [])
            show_annotations = saved_settings.get("show_annotations", False)

        thinking_opts = [{"label": t, "value": t} for t in thinking_options]

        appearance_val = []
        if disable_colors:
            appearance_val.append("disable_colors")
        if show_annotations:
            appearance_val.append("show_annotations")

        return min_date, max_date, start_date, end_date, thinking_opts, thinking_value, min_problems, appearance_val

    app.clientside_callback(
        ClientsideFunction(
            namespace="settings",
            function_name="updateAccordionStore"
        ),
        Output("accordion-state-store", "data"),
        Input("run-selector-accordion", "active_item"),
        prevent_initial_call=True,
    )

    @app.callback(
        Output("run-checklist-container", "children"),
        Output("selected-runs-store", "data"),
        Output("filter-settings-store", "data"),
        [
            Input("date-filter", "start_date"),
            Input("date-filter", "end_date"),
            Input("min-problems-filter", "value"),
            Input("thinking-filter", "value"),
            Input("appearance-options", "value"),
            Input("select-all-button", "n_clicks"),
            Input("deselect-all-button", "n_clicks"),
            Input({"type": "group-select-switch", "index": ALL}, "value"),
            Input({"type": "subgroup-select-switch", "index": ALL}, "value"),
            Input({"type": "run-selector", "index": ALL}, "value"),
        ],
        [
            State("all-runs-metadata", "data"),
            State("selected-runs-store", "data"),
            State("filter-settings-store", "data"),
            State("accordion-state-store", "data"),
        ]
    )
    def manage_run_selection(
        start_date, end_date, min_problems, selected_thinking,
        appearance_options,
        select_all_n_clicks, deselect_all_n_clicks,
        group_switch_values, subgroup_switch_values, selected_values_groups,
        all_runs, current_selection, saved_settings, accordion_state
    ):
        return _manage_run_selection_logic(
            start_date, end_date, min_problems, selected_thinking,
            appearance_options,
            select_all_n_clicks, deselect_all_n_clicks,
            group_switch_values, subgroup_switch_values, selected_values_groups,
            all_runs, current_selection, saved_settings, accordion_state, callback_context
        )

    # Head-to-Head and Run Analysis Callbacks
    @app.callback(
        [
            Output("h2h-run-a", "options"),
            Output("h2h-run-b", "options")
        ],
        Input("all-runs-metadata", "data"),
    )
    def update_dropdowns(all_runs):
        if not all_runs:
            return [], []

        options = []
        for run in all_runs:
            options.append({"label": run["label"], "value": run["value"]})

        options.sort(key=lambda x: x["label"])
        return options, options

    # Render hierarchical selector for Run Analysis
    @app.callback(
        Output("run-analysis-selector-container", "children"),
        [
            Input("all-runs-metadata", "data"),
            Input("run-analysis-store", "data")
        ]
    )
    def render_run_analysis_selector(all_runs, current_selection):
        return build_hierarchical_run_selector_single(all_runs, current_selection)

    # Handle radio selection (ensure single selection updates store)
    @app.callback(
        Output("run-analysis-store", "data"),
        Input({"type": "run-analysis-radio", "index": ALL}, "value"),
        State("run-analysis-store", "data"),
        prevent_initial_call=True
    )
    def handle_run_analysis_selection(radio_values, current_store):
        ctx = callback_context
        if not ctx.triggered:
            return no_update

        for t in ctx.triggered:
            val = t['value']
            # Update only if value is truthy (selected) and different
            if val and val != current_store:
                return val

        return no_update
