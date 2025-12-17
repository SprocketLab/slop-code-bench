#!/usr/bin/env python3
"""Streamlit viewer for VerifierReport parquet files.

Usage:
    uv run streamlit run src/slop_code/entrypoints/report_viewer.py -- /path/to/run_dir

The viewer expects a directory and then provides Problem/Checkpoint dropdowns
to select the `reports.parquet` file to browse.
"""

import hashlib
import json
import sys
from pathlib import Path

import pyarrow.parquet as pq
import streamlit as st

from slop_code.entrypoints.streamlit_case_display import render_case
from slop_code.entrypoints.streamlit_case_display import truncate_text
from slop_code.evaluation import VerifierReport
from slop_code.evaluation import api_adapter
from slop_code.evaluation import cli_adapter

RUN_DIR_LAYOUT_REPORT = "reports.parquet"


def format_json(value):
    """Format a value as pretty-printed JSON if possible, otherwise as string."""
    if value is None:
        return "null"
    if isinstance(value, (bytes, bytearray)):
        return f"sha256:{hashlib.sha256(bytes(value)).hexdigest()}"
    if isinstance(value, (dict, list)):
        return json.dumps(value, indent=2)
    if isinstance(value, str):
        return value
    return str(value)


@st.dialog("Case Data", width="large")
def show_case_modal(report: VerifierReport):
    """Display case data in a modal dialog using shared rendering."""
    # Reconstruct the case object from the dict
    case_type = report.case.get("type", "CLI")

    # Parse input_files if they're stored as JSON string
    case_dict = dict(report.case)
    if "input_files" in case_dict and isinstance(case_dict["input_files"], str):
        try:
            case_dict["input_files"] = json.loads(case_dict["input_files"])
        except (json.JSONDecodeError, TypeError):
            case_dict["input_files"] = []

    # Reconstruct the typed case object
    if case_type.lower() == "api":
        if "headers" in case_dict and isinstance(case_dict["headers"], str):
            try:
                case_dict["headers"] = json.loads(case_dict["headers"])
            except (json.JSONDecodeError, TypeError):
                pass
        if "query" in case_dict and isinstance(case_dict["query"], str):
            try:
                case_dict["query"] = json.loads(case_dict["query"])
            except (json.JSONDecodeError, TypeError):
                pass
        case = api_adapter.APICase.model_validate(case_dict)
    else:
        if isinstance(case_dict.get("stdin"), dict):
            case_dict["stdin"] = json.dumps(case_dict["stdin"])
        case = cli_adapter.CLICase.model_validate(case_dict)

    # Reconstruct the expected result from AttributeResults
    expected_dict = {
        "id": report.id,
        "group": report.group,
        "group_type": report.type,
        "type": case_type,
        "files": {},
    }

    # Extract expected values from results
    for attr_name, attr_result in report.results.items():
        if attr_name.startswith("files-"):
            file_name = attr_name[6:]  # Remove "files-" prefix
            expected_dict["files"][file_name] = attr_result.expected
        else:
            expected_dict[attr_name] = attr_result.expected

    # Create the typed expected result
    if case_type.lower() == "api":
        expected = api_adapter.APIResult.model_validate(expected_dict)
    else:
        expected = cli_adapter.CLIResult.model_validate(expected_dict)

    # Use the shared rendering function
    render_case((case, expected))


def display_attribute_result(attr_name, attr_result):
    """Display a single attribute result with actual, expected, and diff."""
    weight_info = (
        f" (weight: {attr_result.weight})" if attr_result.weight != 1.0 else ""
    )

    # Determine status and color
    if attr_result.is_correct is True:
        status = " ✓"
    elif attr_result.is_correct is False:
        status = " ✗"
    else:
        status = ""

    label = f"{attr_name}{status}{weight_info}"

    with st.expander(label, expanded=False):
        col1, col2, col3 = st.columns(3)

        with col1:
            st.markdown("**Actual**")
            st.code(
                truncate_text(format_json(attr_result.actual)), language="json"
            )

        with col2:
            st.markdown("**Expected**")
            st.code(
                truncate_text(format_json(attr_result.expected)),
                language="json",
            )

        with col3:
            st.markdown("**Diff**")
            if attr_result.diff:
                st.code(
                    truncate_text(format_json(attr_result.diff)),
                    language="json",
                )
            else:
                st.text("No diff")


def _default_directory() -> Path:
    # Prefer something that exists in most checkouts.
    for candidate in [Path("outputs/snapshots"), Path("outputs"), Path()]:
        if candidate.exists() and candidate.is_dir():
            return candidate
    return Path()


def _get_initial_directory_arg() -> Path | None:
    if len(sys.argv) <= 1:
        return None
    raw = sys.argv[1]
    if not raw.strip():
        return None
    p = Path(raw)
    if p.is_file() and p.suffix == ".parquet":
        # Backwards-ish compatibility: treat file input as "browse its parent".
        return p.parent
    return p


def _discover_reports_by_problem_checkpoint(
    base_dir: Path,
) -> dict[str, dict[str, Path]]:
    """Discover available reports.parquet files under a directory.

    Supports two layouts:
    - Run dir: base_dir/<problem>/checkpoint_<n>/reports.parquet
    - Snapshots dir: base_dir/<problem>_checkpoint_<n>/reports.parquet
    """
    results: dict[str, dict[str, Path]] = {}

    if not base_dir.exists() or not base_dir.is_dir():
        return results

    # Layout A: run dir with problem/checkpoint nesting
    for problem_dir in base_dir.iterdir():
        if not problem_dir.is_dir():
            continue
        # Common run dir contains config/environment/logs/etc; skip obvious noise
        if problem_dir.name in {"agent", "logs"}:
            continue

        for checkpoint_dir in problem_dir.iterdir():
            if not checkpoint_dir.is_dir():
                continue
            if not checkpoint_dir.name.startswith("checkpoint_"):
                continue
            report_path = checkpoint_dir / RUN_DIR_LAYOUT_REPORT
            if not report_path.exists():
                continue
            results.setdefault(problem_dir.name, {})[checkpoint_dir.name] = (
                report_path
            )

    # Layout B: flat snapshots dir: <problem>_checkpoint_<n>/
    for child in base_dir.iterdir():
        if not child.is_dir():
            continue
        if "_checkpoint_" not in child.name:
            continue
        report_path = child / RUN_DIR_LAYOUT_REPORT
        if not report_path.exists():
            continue
        problem, _, checkpoint_num = child.name.rpartition("_checkpoint_")
        if not problem or not checkpoint_num:
            continue
        checkpoint_name = f"checkpoint_{checkpoint_num}"
        results.setdefault(problem, {})[checkpoint_name] = report_path

    # Deterministic ordering (for stable dropdowns)
    return {k: results[k] for k in sorted(results)}


@st.cache_data(show_spinner=False)
def _load_reports(report_path: str) -> list[VerifierReport]:
    rows = pq.read_table(Path(report_path)).to_pylist()
    return [
        VerifierReport.from_parquet_row(
            {
                k: v
                for k, v in r.items()
                if k
                not in {
                    "problem",
                    "checkpoint",
                    "version",
                    "problem_version",
                }
            }
        )
        for r in rows
    ]


def main():
    """Main function to display verifier reports."""
    st.set_page_config(layout="wide")

    st.title("Verifier Reports")

    initial_dir = _get_initial_directory_arg() or _default_directory()

    with st.sidebar:
        st.header("Report Viewer")
        base_dir_raw = st.text_input(
            "Directory",
            value=str(initial_dir),
            help=(
                "Path to a run directory (contains <problem>/checkpoint_*/reports.parquet) "
                "or a snapshots directory (contains <problem>_checkpoint_<n>/reports.parquet)."
            ),
        )

    base_dir = Path(base_dir_raw).expanduser() if base_dir_raw else None
    if base_dir is None or not base_dir.exists() or not base_dir.is_dir():
        st.warning("Enter an existing directory to browse reports.")
        return

    discovered = _discover_reports_by_problem_checkpoint(base_dir)
    if not discovered:
        st.warning(f"No `{RUN_DIR_LAYOUT_REPORT}` files found under {base_dir}")
        return

    problems = list(discovered.keys())
    with st.sidebar:
        problem = st.selectbox("Problem", options=problems, index=0)

        checkpoints_map = discovered.get(problem, {})
        checkpoints = sorted(checkpoints_map.keys())
        checkpoint = st.selectbox("Checkpoint", options=checkpoints, index=0)
        report_path = checkpoints_map[checkpoint]
        st.caption(f"Using: `{report_path}`")

    reports = _load_reports(str(report_path))
    if not reports:
        st.warning("No reports found in selected parquet.")
        return

    # Sidebar for navigation
    st.sidebar.header("Navigation")
    st.sidebar.metric("Total Reports", len(reports))

    # Filter options
    st.sidebar.header("Filters")

    # Group filter
    all_groups = sorted(set(r.group for r in reports))
    selected_groups = st.sidebar.multiselect(
        "Groups", options=all_groups, default=all_groups
    )

    # Score filter
    max_score = st.sidebar.slider(
        "Maximum Score", min_value=0.0, max_value=1.0, value=1.0, step=0.05
    )

    # Search filter
    search_term = st.sidebar.text_input("Search ID", "")

    # Apply filters
    filtered_reports = [
        r
        for r in reports
        if r.group in selected_groups
        and r.calculate_score() <= max_score
        and (not search_term or search_term.lower() in r.id.lower())
    ]

    st.sidebar.metric("Filtered Reports", len(filtered_reports))

    if not filtered_reports:
        st.warning("No reports match the current filters.")
        return

    # Report selector with buttons
    st.sidebar.header("Select Report")

    # Initialize selected index in session state
    if "selected_idx" not in st.session_state:
        st.session_state.selected_idx = 0

    selected = st.session_state.selected_idx

    # Ensure selected is within bounds
    if selected >= len(filtered_reports):
        selected = 0
        st.session_state.selected_idx = 0

    # Render buttons for each report
    for idx, r in enumerate(filtered_reports):
        score = r.calculate_score()
        button_label = f"{r.id} ({score:.0%})"
        button_type = "primary" if idx == selected else "secondary"

        if st.sidebar.button(
            button_label,
            key=f"report_{idx}",
            type=button_type,
            use_container_width=True,
        ):
            st.session_state.selected_idx = idx
            st.rerun()

    # Display options
    st.sidebar.header("Display Options")
    only_verified = st.sidebar.checkbox(
        "Only show verified attributes", value=True
    )

    # Get the selected report
    report = filtered_reports[selected]
    score = report.calculate_score()

    # Report header
    st.header(f"{report.id}")
    col1, col2, col3 = st.columns([1, 1, 1])
    with col1:
        st.metric("Score", f"{score:.2%}")
    with col2:
        st.metric("Duration", f"{report.duration:.2f}s")
    with col3:
        if st.button("View Case", use_container_width=True):
            show_case_modal(report)

    # Report metadata
    st.text(f"Group: {report.group} | Type: {report.type}")
    st.text(f"Timestamp: {report.timestamp}")

    # Display results for each attribute
    st.markdown("### Results")
    for attr_name, attr_result in report.results.items():
        # Filter based on verification status
        if only_verified and attr_result.is_correct is None:
            continue
        display_attribute_result(attr_name, attr_result)


if __name__ == "__main__":
    main()
