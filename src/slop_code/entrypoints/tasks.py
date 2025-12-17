# pip install streamlit
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import TypeAlias

import streamlit as st

from slop_code.entrypoints.streamlit_case_display import render_case
from slop_code.evaluation import CheckpointConfig
from slop_code.evaluation import ProblemConfig
from slop_code.evaluation import initialize_loader
from slop_code.evaluation.adapters import BaseCase
from slop_code.evaluation.adapters import CaseResult
from slop_code.evaluation.loaders import LoaderYieldType
from slop_code.logging import get_logger

logger = get_logger(__name__)

PROBLEM_DIR = Path(__file__).parents[3] / "problems"

CaseBundle: TypeAlias = tuple[BaseCase, CaseResult]


def _ensure_case_list(
    cases: Iterable[CaseBundle] | LoaderYieldType,
) -> list[CaseBundle]:
    """Normalize loader outputs into a concrete list of case/result tuples."""

    if isinstance(cases, list):
        return cases
    return list(cases)


def load_group_case_map(
    problem_config: ProblemConfig,
    checkpoint_config: CheckpointConfig,
    checkpoint_dir: Path,
    groups_to_get: set[str] | None = None,
) -> dict[str, list[CaseBundle]]:
    """Execute the configured loader and collect cases per group."""

    loader = initialize_loader(
        problem_config, checkpoint_config, use_placeholders=True
    )
    store = loader.initialize_store()

    group_cases: dict[str, list[CaseBundle]] = {}
    for group_name, group_config in checkpoint_config.groups.items():
        try:
            group_cases[group_config.name] = _ensure_case_list(
                loader(group_config, store)
            )
        except Exception as exc:  # pragma: no cover - surfaced in UI
            logger.error(
                "Failed to load cases for group",
                checkpoint=str(checkpoint_dir),
                group=group_config.name,
                error=str(exc),
            )
            logger.exception(exc, exec_info=True)
            raise

    if groups_to_get is not None:
        for group in groups_to_get:
            group_cases.setdefault(group, [])

    return group_cases


def get_group_cases(
    checkpoint_config: CheckpointConfig,
    checkpoint_dir: Path,
    group: str,
    *,
    problem_constants: dict[str, bytes] | None = None,
    static_assets: dict[str, Path] | None = None,
) -> list[CaseBundle]:
    """Load cases only for a single group in a checkpoint."""

    _ = problem_constants, static_assets  # Maintained for API compatibility.

    if group not in checkpoint_config.groups:
        raise ValueError(f"Group '{group}' not found in checkpoint config")

    # Load problem config from checkpoint directory's parent
    problem_dir = checkpoint_dir.parent
    problem_config = ProblemConfig.from_yaml(problem_dir)

    group_cases = load_group_case_map(
        problem_config,
        checkpoint_config,
        checkpoint_dir,
        groups_to_get={group},
    ).get(group)

    if group_cases is None:
        raise ValueError(f"Loader did not return group '{group}'")

    return group_cases


# Configure page
st.set_page_config(
    page_title="Task Registry",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# Custom CSS
st.markdown(
    """
    <style>
    .main {
        background-color: #f9fafb;
    }
    .header-container {
        background: white;
        border-bottom: 1px solid #e5e7eb;
        padding: 1.25rem 2.5rem;
        box-shadow: 0 1px 2px 0 rgba(0, 0, 0, 0.05);
        margin-bottom: 2rem;
    }
    /* Limit expander content to viewport height and enable scrolling */
    div.streamlit-expanderContent {
        max-height: 70vh;
        overflow-y: auto;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_data
def load_problems() -> list[tuple[ProblemConfig, list[CheckpointConfig]]]:
    logger.info("Loading cases", problem_dir=str(PROBLEM_DIR.absolute()))
    problem_cases = []
    for problem in sorted(PROBLEM_DIR.iterdir(), key=lambda x: x.name):
        cfg_path = problem / "config.yaml"
        if not cfg_path.exists():
            logger.warning("Problem config not found", problem=problem.name)
            continue
        try:
            cfg = ProblemConfig.from_yaml(problem)
        except Exception as e:
            logger.error(
                "Problem config not valid", problem=problem.name, error=str(e)
            )
            continue

        if cfg.category == "NOT_SET":
            logger.warning("Problem category not set", problem=problem.name)

        logger.info("Loaded problem", problem=problem.name)
        checkpoints = [cp for _, cp in cfg.iterate_checkpoint_items()]
        problem_cases.append((cfg, checkpoints))
    logger.info("Loaded problems", problems=len(problem_cases))
    return problem_cases


def get_state_color(state: str) -> str:
    """Map checkpoint state to a color on red-to-green gradient."""
    color_map = {
        "Not Started": "#dc2626",  # red-600
        "Draft": "#f97316",  # orange-500
        "Core Tests": "#fbbf24",  # amber-400
        "Full Tests": "#84cc16",  # lime-500
        "Verified": "#22c55e",  # green-500
    }
    return color_map.get(state, "#9ca3af")  # gray-400 as fallback


def load_checkpoint_info(
    problem_config: ProblemConfig,
    checkpoint_config: CheckpointConfig,
) -> dict[str, str | dict[str, int | None]]:
    """Load checkpoint info including group statistics."""
    checkpoint_path = Path(checkpoint_config.path)
    with open(
        checkpoint_path / checkpoint_config.specification,
        encoding="utf-8",
    ) as f:
        desc = f.read()

    group_info: dict[str, int | None] = dict.fromkeys(checkpoint_config.groups)

    try:
        group_case_map = load_group_case_map(
            problem_config, checkpoint_config, checkpoint_path
        )
    except Exception as exc:  # pragma: no cover - surfaced in UI
        logger.error(
            "Failed to load checkpoint groups",
            checkpoint=str(checkpoint_path),
            error=str(exc),
        )
    else:
        for group_name, cases in group_case_map.items():
            group_info[group_name] = len(cases)

    return {
        "description": desc,
        "group_info": group_info,
    }


def reload_loader_modules(problem_name: str) -> None:
    """Reload the loader module for a problem by clearing it from sys.modules.

    This allows changes to loader.py to be reflected without restarting the app.

    Args:
        problem_name: Name of the problem whose loader should be reloaded.
    """
    logger.info("Reloading loader modules", problem=problem_name)

    # Clear all modules that start with the problem name from sys.modules
    # This includes the loader and any dependencies it imports
    modules_to_remove = [
        module_name
        for module_name in sys.modules
        if module_name.startswith(f"{problem_name}.")
    ]

    for module_name in modules_to_remove:
        logger.debug("Removing module from cache", module=module_name)
        del sys.modules[module_name]

    # Clear Streamlit's cache to ensure no stale test cases
    st.cache_data.clear()

    logger.info(
        "Reloaded loader modules",
        problem=problem_name,
        modules_cleared=len(modules_to_remove),
    )


def render_task_card(
    name: str,
    description: str,
    version: int,
    checkpoint_states: list[str],
    category: str,
    difficulty: str,
):
    """Render a task card."""
    with st.container(border=True):
        # Task name
        st.markdown(
            f"<h3 style='color: #111827; margin-bottom: 0.75rem; font-weight: bold;'>{name.replace('_', ' ').title()}</h3>",
            unsafe_allow_html=True,
        )

        # Description
        st.markdown(
            f"<p style='color: #4b5563; line-height: 1.5; font-size: 0.875rem; height: 100px; overflow-y: auto;'>{description}</p>",
            unsafe_allow_html=True,
        )

        # Checkpoint state boxes
        checkpoint_html = '<div style="margin: 1rem 0;"><span style="color: #6b7280; font-size: 0.75rem; margin-right: 0.5rem;">Checkpoints:</span>'
        for state in checkpoint_states:
            color = get_state_color(state)
            checkpoint_html += f'<span style="display: inline-block; width: 20px; height: 20px; background-color: {color}; border-radius: 3px; margin-right: 4px; vertical-align: middle;" title="{state}"></span>'
        checkpoint_html += "</div>"
        st.markdown(checkpoint_html, unsafe_allow_html=True)

        # Tags row
        cols = st.columns([1, 1, 1])
        with cols[0]:
            st.markdown(
                f"<span style='display: inline-block; padding: 0.25rem 0.5rem; background: #f3f4f6; color: #374151; border: 1px solid #d1d5db; border-radius: 4px; font-size: 0.75rem;'>v{version}</span>",
                unsafe_allow_html=True,
            )
        with cols[1]:
            st.markdown(
                f"<span style='display: inline-block; padding: 0.25rem 0.5rem; background: #000; color: #fff; border-radius: 4px; font-size: 0.75rem;'>{category}</span>",
                unsafe_allow_html=True,
            )
        with cols[2]:
            st.markdown(
                f"<span style='display: inline-block; padding: 0.25rem 0.5rem; background: #fff; color: #000; border: 1px solid #000; border-radius: 4px; font-size: 0.75rem;'>{difficulty}</span>",
                unsafe_allow_html=True,
            )

        # Button
        st.markdown(
            "<div style='margin-top: 1rem;'></div>", unsafe_allow_html=True
        )
        if st.button(
            "View Details", key=f"btn_{name}", use_container_width=True
        ):
            st.query_params["problem"] = name
            st.rerun()


# Initialize query params
if "problem" not in st.query_params:
    # Show grid page
    st.markdown(
        '<div class="header-container"><h1 style="color: #111827; margin: 0;">Task Registry</h1></div>',
        unsafe_allow_html=True,
    )

    # Draft filter toggle
    show_drafts = st.checkbox(
        "Show draft problems (no category or difficulty set)",
        value=False,
        key="show_drafts",
    )

    problems = load_problems()

    # Filter problems based on draft status
    if not show_drafts:
        # Filter out problems that are drafts (category is "NOT_SET" or difficulty not set)
        problems = [
            (problem, checkpoints)
            for problem, checkpoints in problems
            if problem.category != "NOT_SET"
        ]

    st.markdown(
        f'<p style="color: #6b7280; font-size: 0.875rem; margin-bottom: 1.5rem;">Showing {len(problems)} tasks</p>',
        unsafe_allow_html=True,
    )

    # Create grid layout
    cols_per_row = 3
    for i in range(0, len(problems), cols_per_row):
        cols = st.columns(cols_per_row)
        for j, col in enumerate(cols):
            if i + j < len(problems):
                problem, checkpoints = problems[i + j]
                checkpoint_states = [
                    c.state or "Not Started"
                    for c in checkpoints
                    if c is not None
                ]
                with col:
                    render_task_card(
                        name=problem.name,
                        description=problem.description,
                        category=problem.category,
                        difficulty=problem.difficulty,
                        version=problem.version,
                        checkpoint_states=checkpoint_states,
                    )

else:
    # Show problem detail page with case viewer (no checkpoint in query params yet)
    problem_id = st.query_params["problem"]

    # Back button
    if st.button("← Back to Registry"):
        del st.query_params["problem"]
        st.rerun()

    try:
        problem_config = ProblemConfig.from_yaml(PROBLEM_DIR / problem_id)
    except Exception as e:
        logger.error(
            "Failed to load problem", problem_id=problem_id, error=str(e)
        )
        st.error(f"Failed to load problem: {problem_id}")
        st.stop()

    # Load all checkpoints
    checkpoints = []
    checkpoint_names = []
    for (
        checkpoint_name,
        checkpoint_config,
    ) in problem_config.iterate_checkpoint_items():
        checkpoints.append(checkpoint_config)
        checkpoint_names.append(checkpoint_name)

    if not checkpoints:
        st.error("No valid checkpoints found for this problem.")
        st.stop()

    # Checkpoint selection dropdown in header
    col_title, col_selector = st.columns([2, 1])
    with col_title:
        st.markdown(
            f'<div class="header-container"><h1 style="color: #111827; margin: 0;">{problem_config.name.replace("_", " ").title()}</h1></div>',
            unsafe_allow_html=True,
        )
    with col_selector:
        st.markdown(
            "<div style='margin-top: 1.5rem;'></div>", unsafe_allow_html=True
        )
        selected_checkpoint_name = st.selectbox(
            "Checkpoint",
            options=checkpoint_names,
            index=0,
            key="checkpoint_selector",
        )

    # Get the selected checkpoint config
    if not selected_checkpoint_name:
        st.error("No checkpoints available")
        st.stop()
    selected_checkpoint_idx = checkpoint_names.index(selected_checkpoint_name)
    checkpoint_config = checkpoints[selected_checkpoint_idx]
    checkpoint_dir = PROBLEM_DIR / problem_id / selected_checkpoint_name
    checkpoint_id = selected_checkpoint_name

    # Reload loader button (always visible)
    if st.button(
        "🔄 Reload Loader", help="Reload the loader module to reflect changes"
    ):
        reload_loader_modules(problem_id)
        st.success("Loader reloaded! Refreshing...")
        st.rerun()

    # Load all cases for all groups returned by the loader
    all_cases: list[tuple[str, BaseCase, CaseResult]] = []
    all_group_names: list[str] = []

    try:
        group_case_map = load_group_case_map(
            problem_config, checkpoint_config, checkpoint_dir
        )
    except Exception as exc:  # pragma: no cover - surfaced in UI
        logger.error(
            "Failed to load group cases",
            checkpoint=str(checkpoint_dir),
            error=str(exc),
        )
        group_case_map = {}

    seen_groups: set[str] = set()
    for group_name, group_cases in group_case_map.items():
        all_cases.extend(
            (group_name, case, expected) for case, expected in group_cases
        )
        all_group_names.append(group_name)
        seen_groups.add(group_name)

    for group in checkpoint_config.groups:
        if group in seen_groups:
            continue
        logger.error(
            "Group missing from loader output",
            checkpoint=str(checkpoint_dir),
            group=group,
        )
        all_group_names.append(group)

    if not all_cases:
        st.warning("No cases found in this checkpoint.")
        st.stop()

    # Group selection using multiselect (similar to view_run.py)
    selected_groups = st.multiselect(
        "Filter groups",
        options=all_group_names,
        default=all_group_names,
        key="group_filter",
    )

    # Filter cases by selected groups
    filtered_cases = [
        (g, c, e) for g, c, e in all_cases if g in selected_groups
    ]

    if not filtered_cases:
        st.info("No cases match the current filters.")
        st.stop()

    # Ensure valid case position
    total_cases = len(filtered_cases)
    if "case_position" not in st.session_state:
        st.session_state["case_position"] = 1
    if st.session_state["case_position"] < 1:
        st.session_state["case_position"] = 1
    if st.session_state["case_position"] > total_cases:
        st.session_state["case_position"] = total_cases

    # Get current case
    selected_case_idx = int(st.session_state["case_position"]) - 1
    current_group, current_case, current_expected = filtered_cases[
        selected_case_idx
    ]

    # Header row: left title, middle slider, right dropdown
    header_left, header_middle, header_right = st.columns(
        [1, 0.5, 0.3], gap="small"
    )
    with header_left:
        st.markdown(
            f"###  [{st.session_state['case_position']}/{len(filtered_cases):,}] "
            f"`{current_group}/{current_case.id}`"
        )
    with header_middle:
        if len(filtered_cases) > 1:
            case_pos = st.slider(
                "Case",
                min_value=1,
                max_value=total_cases,
                value=st.session_state["case_position"],
                step=1,
                key="case_slider",
                help="Select which case to view",
            )
            # Update position from slider
            if case_pos != st.session_state["case_position"]:
                st.session_state["case_position"] = case_pos
                st.rerun()
    with header_right:
        if len(filtered_cases) > 1:
            st.markdown(
                "<div style='margin-top: 1.8rem;'></div>",
                unsafe_allow_html=True,
            )
            # Create dropdown options with group/case_id
            case_options = [
                f"{i + 1}: {group}/{case.id}"
                for i, (group, case, _) in enumerate(filtered_cases)
            ]
            selected_case = st.selectbox(
                "Jump to case",
                options=case_options,
                index=st.session_state["case_position"] - 1,
                key="case_dropdown",
                label_visibility="collapsed",
                help="Select case by group/id",
            )
            # Update position from dropdown
            selected_idx = case_options.index(selected_case) + 1
            if selected_idx != st.session_state["case_position"]:
                st.session_state["case_position"] = selected_idx
                st.rerun()

    # Render the case
    render_case((current_case, current_expected))

    # Sidebar: Problem metadata and specification
    st.sidebar.markdown("---")

    # Problem metadata expandable
    with st.sidebar.expander("Problem Metadata", expanded=False):
        st.markdown(f"**Name:** {problem_config.name}")
        st.markdown(f"**Category:** {problem_config.category}")
        st.markdown(f"**Difficulty:** {problem_config.difficulty}")
        st.markdown(f"**Version:** {problem_config.version}")

        if problem_config.tags:
            st.markdown(f"**Tags:** {', '.join(problem_config.tags)}")

        st.markdown("**Description:**")
        st.markdown(problem_config.description)

        st.markdown(f"**Checkpoint:** {checkpoint_id}")
        st.markdown(f"**Checkpoint Version:** {checkpoint_config.version}")
        st.markdown(f"**Checkpoint State:** {checkpoint_config.state}")

        # Adapter info
        st.markdown(f"**Adapter Type:** {problem_config.adapter.type}")
        st.markdown(f"**Entry File:** `{problem_config.entry_file}`")

        # Group counts
        num_regular_groups = len(checkpoint_config.groups)
        num_regression_groups = sum(
            1
            for group in checkpoint_config.groups.values()
            if group.type == "Regression"
        )
        st.markdown(f"**Regular Groups:** {num_regular_groups}")
        if num_regression_groups > 0:
            st.markdown(f"**Regression Groups:** {num_regression_groups}")

    # Specification
    st.sidebar.markdown("#### Specification")
    spec_path = checkpoint_dir / checkpoint_config.specification
    if spec_path.exists():
        st.sidebar.markdown(spec_path.read_text(encoding="utf-8"))
    else:
        st.sidebar.warning(f"Spec not found: `{spec_path}`")
