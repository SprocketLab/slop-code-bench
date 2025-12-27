from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import dash_bootstrap_components as dbc
from dash import dcc
from dash import html


def group_runs(runs, key_func):
    """Helper to group runs by a key."""
    groups = defaultdict(list)
    for r in runs:
        groups[key_func(r)].append(r)
    return groups


def build_run_checklist(runs, selected_values, id_key):
    """Builds the leaf-node checklist of runs."""
    options = []
    for run in runs:
        thinking = run.get("thinking_display", "disabled").title()
        agent = str(run.get("agent_type", "Default")).replace("_", " ").title()
        version = str(run.get("agent_version", ""))
        if version and version.lower() not in ("none", "", "null"):
            agent = f"{agent} v{version}"

        date = run.get("run_date", "Unknown Date")
        problems = run.get("num_problems", 0)

        # Include agent in label to differentiate
        label = f"{thinking} - {agent} - {date} - {problems} problems"
        options.append({"label": label, "value": run["value"]})

    current_selection = []
    if selected_values is not None:
        current_selection = [v for v in [o["value"] for o in options] if v in selected_values]
    else:
        current_selection = [o["value"] for o in options]

    return dbc.Checklist(
        id={"type": "run-selector", "index": id_key},
        options=options,
        value=current_selection,
        switch=True,
        className="run-selector-checklist",
        style={"lineHeight": "1.5"}
    )


def build_hierarchical_run_selector(runs, selected_values, active_items=None):
    """
    Builds a nested accordion structure:
      - Level 1: Parent Directory (Model)
      - Level 2: Prompt Template
      
    Includes Toggle Switches for bulk selection at both levels.
    """
    if not runs:
        return html.Div(
            [
                html.I(className="bi bi-exclamation-circle display-4 text-muted mb-3"),
                html.H5("No runs match your filters", className="text-muted"),
                html.P("Try adjusting the date range or thinking level.", className="text-muted")
            ],
            className="text-center p-5"
        )

    # Group by Parent Directory (Model)
    runs_by_parent = group_runs(runs, lambda r: Path(r["value"]).parent.name)

    outer_accordion_items = []
    for parent_dir in sorted(runs_by_parent.keys()):
        model_runs = runs_by_parent[parent_dir]

        # Check selection state for the Model Group
        selected_in_model = [r for r in model_runs if r["value"] in selected_values]
        is_model_selected = len(selected_in_model) == len(model_runs) and len(model_runs) > 0

        # Group by Prompt Template (Level 2)
        runs_by_prompt = group_runs(model_runs, lambda r: r.get("prompt_template", "Unknown"))

        inner_accordion_items = []
        for prompt in sorted(runs_by_prompt.keys()):
            prompt_runs = runs_by_prompt[prompt]
            prompt_runs.sort(key=lambda r: r.get("label", "")) # Sort by label

            # Check selection state for the Prompt Group
            selected_in_prompt = [r for r in prompt_runs if r["value"] in selected_values]
            is_prompt_selected = len(selected_in_prompt) == len(prompt_runs) and len(prompt_runs) > 0

            # Unique ID for the checklist
            # We use a composite key to avoid collisions
            checklist_id = f"{parent_dir}|{prompt}"

            checklist = build_run_checklist(prompt_runs, selected_values, checklist_id)

            # Subgroup Switch
            subgroup_switch = dbc.Switch(
                id={"type": "subgroup-select-switch", "index": checklist_id},
                label=f"Select All ({len(selected_in_prompt)}/{len(prompt_runs)})",
                value=is_prompt_selected,
                className="mb-2 text-muted small"
            )

            inner_accordion_items.append(
                dbc.AccordionItem(
                    html.Div([subgroup_switch, checklist]),
                    title=f"{prompt} ({len(prompt_runs)})",
                    item_id=checklist_id
                )
            )

        # Build Inner Accordion
        inner_accordion = dbc.Accordion(
            inner_accordion_items,
            always_open=True,
            flush=True,
            start_collapsed=True, # Default to collapsed to save space
            className="mb-2"
        )

        # Model Group Switch
        model_switch = dbc.Switch(
            id={"type": "group-select-switch", "index": parent_dir},
            label=f"Select Group ({len(selected_in_model)}/{len(model_runs)} selected)",
            value=is_model_selected,
            className="mb-2 fw-bold"
        )

        group_content = html.Div([
            html.Div([model_switch], className="border-bottom pb-2 mb-2"),
            inner_accordion
        ])

        outer_accordion_items.append(
            dbc.AccordionItem(
                group_content,
                title=f"{parent_dir}",
                item_id=parent_dir
            )
        )

    return dbc.Accordion(
        outer_accordion_items,
        always_open=True,
        flush=True,
        active_item=active_items,
        id="run-selector-accordion",
        persistence=True,
        persistence_type="session"
    )


def build_single_run_radio(runs, selected_value, id_key):
    """Builds the leaf-node radio items of runs."""
    options = []
    for run in runs:
        thinking = run.get("thinking_display", "disabled").title()
        agent = str(run.get("agent_type", "Default")).replace("_", " ").title()
        version = str(run.get("agent_version", ""))
        if version and version.lower() not in ("none", "", "null"):
            agent = f"{agent} v{version}"

        date = run.get("run_date", "Unknown Date")
        problems = run.get("num_problems", 0)

        # Include agent in label to differentiate
        label = f"{thinking} - {agent} - {date} - {problems} problems"
        options.append({"label": label, "value": run["value"]})

    # For RadioItems, value is a single scalar
    # Only set the value if it exists in this group's options
    group_values = {o["value"] for o in options}
    current_value = selected_value if selected_value in group_values else None

    return dbc.RadioItems(
        id={"type": "run-analysis-radio", "index": id_key},
        options=options,
        value=current_value,
        className="run-selector-radio",
        style={"lineHeight": "1.5"}
    )


def build_hierarchical_run_selector_single(runs, selected_value, active_items=None):
    """
    Builds a nested accordion structure for single selection:
      - Level 1: Parent Directory (Model)
      - Level 2: Prompt Template
    """
    if not runs:
        return html.Div(
            [
                html.I(className="bi bi-exclamation-circle display-4 text-muted mb-3"),
                html.H5("No runs available", className="text-muted"),
            ],
            className="text-center p-5"
        )

    # Group by Parent Directory (Model)
    runs_by_parent = group_runs(runs, lambda r: Path(r["value"]).parent.name)

    outer_accordion_items = []
    for parent_dir in sorted(runs_by_parent.keys()):
        model_runs = runs_by_parent[parent_dir]
        runs_by_prompt = group_runs(model_runs, lambda r: r.get("prompt_template", "Unknown"))

        inner_accordion_items = []
        for prompt in sorted(runs_by_prompt.keys()):
            prompt_runs = runs_by_prompt[prompt]
            prompt_runs.sort(key=lambda r: r.get("label", "")) # Sort by label

            # Unique ID for the checklist
            checklist_id = f"{parent_dir}|{prompt}"

            radio_group = build_single_run_radio(prompt_runs, selected_value, checklist_id)

            inner_accordion_items.append(
                dbc.AccordionItem(
                    radio_group,
                    title=f"{prompt} ({len(prompt_runs)})",
                    item_id=checklist_id
                )
            )

        # Build Inner Accordion
        inner_accordion = dbc.Accordion(
            inner_accordion_items,
            always_open=True,
            flush=True,
            start_collapsed=True, # Default to collapsed to save space
            className="mb-2"
        )

        outer_accordion_items.append(
            dbc.AccordionItem(
                inner_accordion,
                title=f"{parent_dir}",
                item_id=parent_dir
            )
        )

    return dbc.Accordion(
        outer_accordion_items,
        always_open=True,
        flush=True,
        active_item=active_items,
        id="run-analysis-accordion",
        persistence=True,
        persistence_type="session"
    )


def build_configuration_modal_content():
    """Builds the content for the global configuration modal."""
    return dbc.Container([
        html.Div([
            html.P("Filter and select the experimental runs you want to visualize.", className="text-muted lead fs-6"),
        ], className="mb-4 border-bottom pb-2"),

        dbc.Row([
            # LEFT COLUMN: FILTERS
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader(
                        html.H5("Global Filters", className="mb-0 text-white"),
                        className="bg-primary border-0"
                    ),
                    dbc.CardBody([
                        html.Label("Date Range", className="fw-bold text-secondary small text-uppercase mb-2"),
                        dcc.DatePickerRange(
                            id="date-filter",
                            style={"width": "100%", "fontSize": "0.9rem"},
                            className="mb-4",
                            clearable=True,
                        ),

                        html.Label("Minimum Problems Solved", className="fw-bold text-secondary small text-uppercase mb-2"),
                        dbc.InputGroup([
                            dbc.Input(
                                id="min-problems-filter",
                                type="number",
                                min=0,
                                value=0,
                                placeholder="0",
                            ),
                        ], className="mb-4 shadow-sm"),

                        html.Label("Thinking Level", className="fw-bold text-secondary small text-uppercase mb-2"),
                        dbc.Card(
                            dbc.CardBody(
                                dbc.Checklist(
                                    id="thinking-filter",
                                    switch=True,
                                    input_class_name="me-2",
                                    className="d-flex flex-column gap-2"
                                ),
                                className="p-2"
                            ),
                            className="bg-light border-0 shadow-sm inner-card mb-4"
                        ),

                        html.Label("Appearance", className="fw-bold text-secondary small text-uppercase mb-2"),
                        dbc.Card(
                            dbc.CardBody(
                                dbc.Checklist(
                                    options=[
                                        {"label": "Disable Provider Colors", "value": "disable_colors"},
                                        {"label": "Show Scatter Annotations", "value": "show_annotations"},
                                    ],
                                    value=[],
                                    id="appearance-options",
                                    switch=True,
                                    input_class_name="me-2",
                                    className="d-flex flex-column gap-2"
                                ),
                                className="p-2"
                            ),
                            className="bg-light border-0 shadow-sm inner-card"
                        ),
                    ], className="p-4")
                ], className="shadow-sm border-0 h-100 rounded-3 overflow-hidden"),
            ], width=12, lg=4, className="mb-4"),

            # RIGHT COLUMN: RUN SELECTION
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        dbc.Row([
                            dbc.Col([
                                html.H5("Run Selection", className="mb-0"),
                                html.Small("Toggle switches to include/exclude specific runs.", className="text-muted")
                            ], width=True, className="d-flex flex-column justify-content-center"),
                            dbc.Col([
                                dbc.ButtonGroup([
                                    dbc.Button("Select All", id="select-all-button", color="outline-primary", size="sm"),
                                    dbc.Button("Deselect All", id="deselect-all-button", color="outline-danger", size="sm")
                                ], className="shadow-sm")
                            ], width="auto", className="d-flex align-items-center")
                        ])
                    ], className="bg-white border-bottom pt-3 pb-3"),

                    dbc.CardBody([
                        dcc.Loading(
                            html.Div(id="run-checklist-container"),
                            type="dot",
                            color="#0d6efd"
                        )
                    ], className="p-0 run-list-body", style={"minHeight": "400px", "maxHeight": "60vh", "overflowY": "auto"})

                ], className="shadow-sm border-0 h-100 rounded-3 overflow-hidden")
            ], width=12, lg=8, className="mb-4")
        ])
    ], fluid=True, className="py-3")


def build_h2h_modal_content():
    """Builds the content for the Head-to-Head configuration modal."""
    return dbc.Container([
        html.Div([
            html.P("Select the two runs you want to compare head-to-head.", className="text-muted lead fs-6"),
        ], className="mb-4 border-bottom pb-2"),

        dbc.Card(
            [
                dbc.CardHeader("Run Selection", className="fw-bold bg-light"),
                dbc.CardBody(
                    dbc.Row(
                        [
                            dbc.Col(
                                [
                                    html.Label("Baseline Run (A)", className="fw-bold small text-muted"),
                                    dcc.Dropdown(
                                        id="h2h-run-a",
                                        placeholder="Select Baseline Run...",
                                        style={"fontSize": "0.9rem"},
                                        persistence=True,
                                        persistence_type="session",
                                    ),
                                ],
                                width=12,
                                className="mb-3"
                            ),
                            dbc.Col(
                                [
                                    html.Label("Challenger Run (B)", className="fw-bold small text-muted"),
                                    dcc.Dropdown(
                                        id="h2h-run-b",
                                        placeholder="Select Challenger Run...",
                                        style={"fontSize": "0.9rem"},
                                        persistence=True,
                                        persistence_type="session",
                                    ),
                                ],
                                width=12,
                            ),
                        ]
                    )
                ),
            ],
            className="mb-4 shadow-sm border-0",
        )
    ], fluid=True)


def build_run_analysis_modal_content():
    """Builds the content for the Run Analysis configuration modal."""
    return dbc.Container([
        html.Div([
            html.P("Select the single run you want to analyze in detail.", className="text-muted lead fs-6"),
        ], className="mb-4 border-bottom pb-2"),

        dbc.Card(
            [
                dbc.CardHeader("Run Selection", className="fw-bold bg-light"),
                dbc.CardBody([
                    dcc.Loading(
                        html.Div(id="run-analysis-selector-container"),
                        type="dot",
                        color="#0d6efd"
                    )
                ]),
            ],
            className="mb-4 shadow-sm border-0",
        )
    ], fluid=True)
