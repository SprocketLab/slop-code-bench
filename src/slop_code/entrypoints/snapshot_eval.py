#!/usr/bin/env python3
"""Interactive Streamlit app for evaluating snapshots against problem checkpoints.

Usage:
    streamlit run src/slop_code/entrypoints/snapshot_eval.py
"""

from __future__ import annotations

import hashlib
import html
import json
import math
import shlex
import sys
import traceback
import uuid
from collections import defaultdict
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
import yaml

from slop_code import evaluation
from slop_code import execution
from slop_code import logging as slop_logging
from slop_code.entrypoints.streamlit_case_display import render_case
from slop_code.entrypoints.streamlit_case_display import truncate_text
from slop_code.evaluation import CorrectnessResults
from slop_code.evaluation import ProblemConfig
from slop_code.evaluation.adapters import APICase
from slop_code.evaluation.adapters import APIResult
from slop_code.evaluation.adapters import CLICase
from slop_code.evaluation.adapters import CLIResult


def resolve_environment_spec_streamlit(env_config_path: Path):
    """Resolve environment spec without typer dependencies.

    This is a streamlit-friendly version of utils.resolve_environment_spec.
    """
    if not env_config_path.exists():
        raise FileNotFoundError(f"Environment config not found: {env_config_path}")

    with env_config_path.open() as f:
        environment_config = yaml.safe_load(f)

    match environment_config["type"]:
        case "docker":
            model_cls = execution.DockerEnvironmentSpec
        case "local":
            model_cls = execution.LocalEnvironmentSpec
        case _:
            raise ValueError(f"Invalid environment type: {environment_config['type']}")
    return model_cls.model_validate(environment_config)


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


def maybe_json_lines(value):
    if isinstance(value, str):
        lines = []
        for l in value.strip().split("\n"):
            try:
                v = json.loads(l)
            except json.JSONDecodeError:
                return value

            if isinstance(v, list):
                lines.extend(v)
            else:
                lines.append(v)
        return lines

    return value


def is_list_of_dicts(value):
    """Check if value is a non-empty list of dictionaries."""

    return (
        isinstance(value, list)
        and len(value) > 0
        and all(isinstance(item, dict) for item in value)
    )


def _raw_value_to_string(value) -> str:
    """Convert the raw value to a plain string for copying."""
    if value is None:
        return "null"
    if isinstance(value, (bytes, bytearray)):
        return f"sha256:{hashlib.sha256(bytes(value)).hexdigest()}"
    if isinstance(value, (dict, list)):
        try:
            return json.dumps(value)
        except TypeError:
            return str(value)
    return str(value)


def render_value_display(value, label: str, allow_copy: bool = False):
    """Render a value, using a table for list of dicts, otherwise JSON."""
    header_id = f"value-header-{uuid.uuid4().hex}"
    copy_hint = (
        '<span class="copy-hint" style="font-size:0.8rem; color:#64748b;">'
        "(click to copy raw)</span>"
        if allow_copy
        else ""
    )
    script_block = ""
    if allow_copy:
        raw_string = json.dumps(_raw_value_to_string(value))
        script_block = f"""
            target.style.cursor = "pointer";
            const hint = target.querySelector(".copy-hint");
            const defaultColor = hint ? hint.style.color : "";
            const defaultText = hint ? hint.textContent : "";
            target.addEventListener("click", async () => {{
                if (!navigator.clipboard) return;
                try {{
                    await navigator.clipboard.writeText({raw_string});
                    if (hint) {{
                        hint.textContent = "Copied!";
                        hint.style.color = "#059669";
                        setTimeout(() => {{
                            hint.textContent = defaultText;
                            hint.style.color = defaultColor;
                        }}, 1500);
                    }}
                }} catch (err) {{
                    if (hint) {{
                        hint.textContent = "Copy failed";
                        hint.style.color = "#dc2626";
                        setTimeout(() => {{
                            hint.textContent = defaultText;
                            hint.style.color = defaultColor;
                        }}, 2000);
                    }}
                }}
            }});
        """

    components.html(
        f"""
        <div id="{header_id}" style="
                display:flex;
                align-items:center;
                gap:0.4rem;
                font-weight:600;
                margin-bottom:0.25rem;">
            <span>{html.escape(label)}</span>
            {copy_hint}
        </div>
        <script>
        (function() {{
            const target = document.getElementById("{header_id}");
            if (!target) return;
            {script_block}
        }})();
        </script>
        """,
        height=40,
    )

    value = maybe_json_lines(value)

    if is_list_of_dicts(value):
        try:
            # Convert to dataframe for table display
            df = pd.DataFrame(value)
            st.dataframe(df, use_container_width=True, hide_index=False)
        except Exception:
            # Fall back to JSON if dataframe conversion fails
            st.code(truncate_text(format_json(value)), language="json")
    else:
        st.code(truncate_text(format_json(value)), language="json")


@st.dialog("Case Data", width="large")
def show_case_modal(report):
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

    if isinstance(case_dict.get("timeout_s"), str):
        case_dict["timeout_s"] = (
            float(case_dict["timeout_s"]) if case_dict["timeout_s"] != "null" else None
        )
    if isinstance(case_dict.get("tracked_files"), str):
        case_dict["tracked_files"] = json.loads(case_dict["tracked_files"])

    if isinstance(case_dict.get("arguments"), str):
        try:
            case_dict["arguments"] = json.loads(case_dict["arguments"])
        except (json.JSONDecodeError, TypeError):
            case_dict["arguments"] = shlex.split(case_dict["arguments"])
    # Reconstruct the typed case object
    if case_type.lower() == "api":
        if "headers" in case_dict and isinstance(case_dict["headers"], str):
            case_dict["headers"] = json.loads(case_dict["headers"])
        if "query" in case_dict and isinstance(case_dict["query"], str):
            case_dict["query"] = json.loads(case_dict["query"])
        case = APICase.model_validate(case_dict)
    else:
        if isinstance(case_dict.get("stdin"), dict):
            case_dict["stdin"] = json.dumps(case_dict["stdin"])
        if isinstance(case_dict.get("input_files"), str):
            case_dict["input_files"] = json.loads(case_dict["input_files"])

        case = CLICase.model_validate(case_dict)

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
        expected = APIResult.model_validate(expected_dict)
    else:
        if isinstance(expected_dict.get("arguments"), str):
            expected_dict["arguments"] = shlex.split(expected_dict["arguments"])
        expected = CLIResult.model_validate(expected_dict)

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
        col1, col2 = st.columns(2)

        with col1:
            render_value_display(attr_result.actual, "Actual", allow_copy=True)

        with col2:
            render_value_display(attr_result.expected, "Expected")

        diff_content = attr_result.diff or "No diff"
        with st.expander("Diff", expanded=False):
            if attr_result.diff:
                st.code(
                    truncate_text(format_json(attr_result.diff)),
                    language="json",
                )
            else:
                st.text(diff_content)


def display_evaluation_logs(log_path: Path):
    """Display evaluation logs from the log file."""
    st.markdown("### Evaluation Logs")

    if not log_path.exists():
        st.warning("No log file found yet.")
        return

    try:
        with open(log_path) as f:
            log_content = f.read()

        if log_content:
            st.code(truncate_text(log_content), language="log", line_numbers=True)
        else:
            st.info("Log file is empty.")
    except Exception as e:
        st.error(f"Error reading log file: {e}")


def run_evaluation(
    snapshot_dir: Path,
    problem_name: str,
    checkpoint_num: int,
    env_config: Path,
    save_dir: Path,
    seed: int = 42,
) -> tuple[CorrectnessResults | None, str | None]:
    """Run evaluation and return the checkpoint report and any error message.

    Returns:
        Tuple of (CheckpointReport or None, error_message or None)
    """
    try:
        # Validate inputs
        if not snapshot_dir.exists():
            return None, f"Snapshot directory does not exist: {snapshot_dir}"

        if not env_config.exists():
            return None, f"Environment config does not exist: {env_config}"

        # Load problem config from problems directory
        # Assume problems are in problems/ directory relative to project root
        project_root = Path(__file__).parent.parent.parent.parent
        problem_path = project_root / "problems" / problem_name

        if not problem_path.exists():
            return None, f"Problem directory does not exist: {problem_path}"

        # Load problem config
        problem = ProblemConfig.from_yaml(problem_path)

        ordered_checkpoints = list(problem.iterate_checkpoint_items())

        # Validate checkpoint number
        if checkpoint_num < 1 or checkpoint_num > len(ordered_checkpoints):
            return (
                None,
                f"Checkpoint number {checkpoint_num} is out of range. "
                f"Must be between 1 and {len(ordered_checkpoints)}.",
            )

        checkpoint_name, checkpoint = ordered_checkpoints[checkpoint_num - 1]

        # Resolve environment spec
        environment = resolve_environment_spec_streamlit(env_config)

        # Create save directory if it doesn't exist
        save_dir.mkdir(parents=True, exist_ok=True)

        # Set up logging to save directory
        slop_logging.setup_logging(
            log_dir=save_dir,
            verbosity=1,  # Default verbosity
            log_file_name="evaluation.log",
        )

        # Run evaluation
        report = evaluation.run_checkpoint(
            submission_path=snapshot_dir,
            problem=problem,
            checkpoint=checkpoint,
            env_spec=environment,
        )

        # Save the report
        report.save(save_dir)

        return report, None

    except Exception:
        error_msg = f"Error during evaluation:\n{traceback.format_exc()}"
        return None, error_msg


def get_available_problems() -> list[str]:
    """Get list of available problems from problems directory."""
    project_root = Path(__file__).parent.parent.parent.parent
    problems_dir = project_root / "problems"

    if not problems_dir.exists():
        return []

    return sorted([p.name for p in problems_dir.iterdir() if p.is_dir()])


def get_problem_checkpoints(problem_name: str) -> list[str]:
    """Get list of checkpoints for a given problem."""
    if not problem_name:
        return []

    project_root = Path(__file__).parent.parent.parent.parent
    problem_path = project_root / "problems" / problem_name

    if not problem_path.exists():
        return []

    try:
        problem = ProblemConfig.from_yaml(problem_path)
        return [name for name, _ in problem.iterate_checkpoint_items()]
    except Exception:
        return []


def get_available_environments() -> list[str]:
    """Get list of available environment configs."""
    project_root = Path(__file__).parent.parent.parent.parent
    env_dir = project_root / "configs" / "environments"

    if not env_dir.exists():
        return []

    env_files = sorted([f.name for f in env_dir.glob("*.yaml")])
    return env_files


def parse_snapshot_path(snapshot_path: Path) -> tuple[str | None, int | None]:
    """Extract problem name and checkpoint number from snapshot path.

    Handles multiple path formats:
    - .../problem_name/checkpoint_N/snapshot
    - .../problem_name/snapshot (no checkpoint number)
    - .../problem_name (snapshot is the problem directory itself)

    Args:
        snapshot_path: Path to the snapshot directory

    Returns:
        Tuple of (problem_name, checkpoint_num) or (None, None) if parsing fails
    """
    try:
        # Convert to Path object if string
        path = Path(snapshot_path) if isinstance(snapshot_path, str) else snapshot_path

        # Normalize path - if it's inside a path containing 'snapshot', extract up to that
        if path.name != "snapshot":
            parts = path.parts
            for i in range(len(parts) - 1, -1, -1):
                if parts[i] == "snapshot":
                    path = Path(*parts[: i + 1])
                    break

        # Case 1: Path ends with 'snapshot'
        if path.name == "snapshot":
            parent_dir = path.parent

            # Check if parent is a checkpoint directory
            if parent_dir.name.startswith("checkpoint_"):
                # Format: .../problem_name/checkpoint_N/snapshot
                try:
                    checkpoint_num = int(parent_dir.name.split("_")[1])
                    problem_name = parent_dir.parent.name

                    if not problem_name or problem_name in [".", "..", ""]:
                        return None, None

                    return problem_name, checkpoint_num
                except (ValueError, IndexError):
                    return None, None
            else:
                # Format: .../problem_name/snapshot
                problem_name = parent_dir.name
                if not problem_name or problem_name in [".", "..", ""]:
                    return None, None
                return problem_name, None

        # Case 2: Path is the problem directory itself
        else:
            # Check if this directory name looks like a checkpoint
            if path.name.startswith("checkpoint_"):
                # Parent is the problem directory
                problem_name = path.parent.name
                try:
                    checkpoint_num = int(path.name.split("_")[1])
                except (ValueError, IndexError):
                    checkpoint_num = None

                if not problem_name or problem_name in [".", "..", ""]:
                    return None, None
                return problem_name, checkpoint_num
            # Assume this is the problem directory
            problem_name = path.name
            if not problem_name or problem_name in [".", "..", ""]:
                return None, None
            return problem_name, None

    except (ValueError, IndexError, AttributeError):
        return None, None


def reload_problem_modules(problem_name: str) -> tuple[bool, str]:
    """Reload loader and verifier modules for a problem.

    This allows changes to loader.py and verifier.py to be picked up without
    restarting the Streamlit app.

    Args:
        problem_name: Name of the problem whose modules should be reloaded

    Returns:
        Tuple of (success: bool, message: str)
    """
    if not problem_name:
        return False, "No problem selected"

    project_root = Path(__file__).parent.parent.parent.parent
    problem_path = project_root / "problems" / problem_name

    if not problem_path.exists():
        return False, f"Problem directory does not exist: {problem_path}"

    reloaded = []
    errors = []

    # Reload loader.py if it exists
    loader_file = problem_path / "loader.py"
    if loader_file.exists():
        module_name = f"{problem_name}.loader"
        try:
            # Remove from sys.modules if present
            modules_to_remove = [
                key for key in sys.modules.keys() if key.startswith(f"{problem_name}.")
            ]
            for key in modules_to_remove:
                del sys.modules[key]
            reloaded.append("loader.py")
        except Exception as e:
            errors.append(f"loader.py: {str(e)}")

    # Reload verifier.py if it exists
    verifier_file = problem_path / "verifier.py"
    if verifier_file.exists():
        module_name = f"{problem_name}.verifier"
        try:
            # Remove from sys.modules if present
            modules_to_remove = [
                key for key in sys.modules.keys() if key.startswith(f"{problem_name}.")
            ]
            for key in modules_to_remove:
                if key not in [k for k in sys.modules.keys()]:  # Already removed
                    continue
                del sys.modules[key]
            if "verifier.py" not in reloaded:
                reloaded.append("verifier.py")
        except Exception as e:
            errors.append(f"verifier.py: {str(e)}")

    if errors:
        return False, f"Errors reloading: {', '.join(errors)}"
    if reloaded:
        return True, f"Successfully reloaded: {', '.join(reloaded)}"
    return False, "No loader.py or verifier.py found to reload"


def main():
    """Main function for the snapshot evaluation app."""
    # Initialize session state first (before set_page_config)
    if "detected_problem" not in st.session_state:
        st.session_state.detected_problem = None
    if "detected_checkpoint" not in st.session_state:
        st.session_state.detected_checkpoint = None

    # Set page title based on detected problem
    page_title = "Snapshot Evaluator"
    if st.session_state.detected_problem:
        page_title = f"{st.session_state.detected_problem} - Snapshot Evaluator"
        if st.session_state.detected_checkpoint:
            page_title = f"{st.session_state.detected_problem} Checkpoint {st.session_state.detected_checkpoint}"

    st.set_page_config(layout="wide", page_title=page_title)

    st.title("Snapshot Evaluation Tool")
    st.markdown("Evaluate code snapshots against problem checkpoints")

    # Initialize remaining session state
    if "report" not in st.session_state:
        st.session_state.report = None
    if "error" not in st.session_state:
        st.session_state.error = None
    if "selected_case_idx" not in st.session_state:
        st.session_state.selected_case_idx = 0
    if "log_path" not in st.session_state:
        st.session_state.log_path = None

    # Get available options
    available_problems = get_available_problems()
    available_environments = get_available_environments()

    # Input form in sidebar
    with st.sidebar:
        st.header("Snapshot Evaluator")

        with st.expander("⚙️ Configuration", expanded=True):
            snapshot_dir = st.text_input(
                "Snapshot Directory",
                value="",
                help="Path to the snapshot directory containing code to evaluate",
            )

            # Auto-detect problem and checkpoint from snapshot path
            if snapshot_dir:
                detected_problem, detected_checkpoint = parse_snapshot_path(
                    Path(snapshot_dir)
                )
                if detected_problem != st.session_state.detected_problem:
                    st.session_state.detected_problem = detected_problem
                if detected_checkpoint != st.session_state.detected_checkpoint:
                    st.session_state.detected_checkpoint = detected_checkpoint

            # Problem dropdown (auto-select detected problem if available)
            detected_problem = st.session_state.detected_problem
            problem_options = [""] + available_problems

            # Determine default index for problem dropdown
            if detected_problem and detected_problem in available_problems:
                default_problem_idx = problem_options.index(detected_problem)
            else:
                default_problem_idx = 0

            problem_name = st.selectbox(
                "Problem Name",
                options=problem_options,
                index=default_problem_idx,
                help="Select the problem to evaluate (auto-detected from path)",
            )

            # Checkpoint dropdown (updates based on selected problem)
            available_checkpoints = (
                get_problem_checkpoints(problem_name) if problem_name else []
            )

            if available_checkpoints:
                # Determine default index for checkpoint dropdown
                detected_checkpoint = st.session_state.detected_checkpoint
                if detected_checkpoint is not None and 1 <= detected_checkpoint <= len(
                    available_checkpoints
                ):
                    default_checkpoint_idx = detected_checkpoint - 1
                else:
                    default_checkpoint_idx = 0

                checkpoint_name = st.selectbox(
                    "Checkpoint",
                    options=available_checkpoints,
                    index=default_checkpoint_idx,
                    help="Select the checkpoint to evaluate (auto-detected from path)",
                )
                # Convert checkpoint name to number (1-based index)
                checkpoint_num = available_checkpoints.index(checkpoint_name) + 1
            else:
                st.selectbox(
                    "Checkpoint",
                    options=["Select a problem first"],
                    disabled=True,
                    help="Select the checkpoint to evaluate",
                )
                checkpoint_num = 1

            # Environment dropdown
            if available_environments:
                env_file = st.selectbox(
                    "Environment Config",
                    options=available_environments,
                    index=(
                        available_environments.index("docker-python3.12-uv.yaml")
                        if "docker-python3.12-uv.yaml" in available_environments
                        else 0
                    ),
                    help="Select the environment configuration",
                )
                project_root = Path(__file__).parent.parent.parent.parent
                env_config = str(project_root / "configs" / "environments" / env_file)
            else:
                env_config = st.text_input(
                    "Environment Config Path",
                    value="configs/environments/docker-python3.12-uv.yaml",
                    help="Path to environment configuration YAML file",
                )

            # Auto-compute default save directory
            default_save_dir = ""
            if problem_name and checkpoint_num:
                default_save_dir = (
                    f"outputs/snapshots/{problem_name}_checkpoint_{checkpoint_num}"
                )

            save_dir = st.text_input(
                "Save Directory",
                value=default_save_dir,
                help="Directory to save evaluation results and logs",
            )

            seed = st.number_input(
                "Random Seed",
                min_value=0,
                value=42,
                help="Random seed for reproducibility",
            )

        st.divider()

        # Run button
        run_button = st.button(
            "🚀 Run Evaluation",
            type="primary",
            use_container_width=True,
        )

        # Re-run button (only show if there's already a report)
        if st.session_state.report is not None:
            if st.button(
                "🔄 Re-run Evaluation",
                use_container_width=True,
            ):
                st.session_state.report = None
                st.session_state.error = None
                st.session_state.selected_case_idx = 0
                run_button = True

    # Handle evaluation execution
    if run_button:
        if not snapshot_dir or not problem_name or not save_dir:
            st.error(
                "Please fill in all required fields: Snapshot Directory, Problem Name, and Save Directory"
            )
        else:
            with st.spinner("Running evaluation..."):
                # Auto-reload problem modules before evaluation
                reload_problem_modules(problem_name)

                report, error = run_evaluation(
                    snapshot_dir=Path(snapshot_dir),
                    problem_name=problem_name,
                    checkpoint_num=checkpoint_num,
                    env_config=Path(env_config),
                    save_dir=Path(save_dir),
                    seed=seed,
                )

                st.session_state.report = report
                st.session_state.error = error
                st.session_state.log_path = Path(save_dir) / "evaluation.log"
                st.session_state.selected_case_idx = 0

                if error:
                    st.error(error)
                else:
                    st.success("Evaluation completed successfully!")

    # Display results if available
    if st.session_state.error:
        st.error(st.session_state.error)

    if st.session_state.report is not None:
        report: CorrectnessResults = st.session_state.report

        # Display overall metrics
        st.header("Evaluation Results")

        # Calculate overall statistics
        total_cases = len(report.reports)
        total_score = sum(r.calculate_score() for r in report.reports) / max(
            total_cases, 1
        )
        passed_cases = sum(
            1 for r in report.reports if math.isclose(r.calculate_score(), 1.0)
        )

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Overall Score", f"{total_score:.2%}")
        with col2:
            st.metric("Duration", f"{report.duration:.2f}s")
        with col3:
            st.metric("Passed Cases", f"{passed_cases}/{total_cases}")
        with col4:
            st.metric("Total Cases", total_cases)

        # Display group-level summary
        st.markdown("### Group Summary")
        group_scores = defaultdict(list)
        for case_report in report.reports:
            group_name = case_report.group
            group_scores[group_name].append(case_report.calculate_score())

        # Create group summary table
        group_data = []
        for group_name, scores in sorted(group_scores.items()):
            mean_score = sum(scores) / len(scores)
            num_passed = sum(1 for s in scores if math.isclose(s, 1.0))
            group_data.append(
                {
                    "Group": group_name,
                    "Passed": num_passed,
                    "Total": len(scores),
                    "Score": f"{mean_score:.2%}",
                }
            )

        st.dataframe(group_data, use_container_width=True, hide_index=True)

        # Tabs for cases and logs
        tab1, tab2 = st.tabs(["📊 Case Details", "📝 Logs"])

        with tab1:
            # Display individual cases
            st.markdown("### Individual Cases")

            # Filters
            filter_columns = st.columns([3, 2])
            with filter_columns[0]:
                selected_groups = st.multiselect(
                    "Filter by Group",
                    options=sorted(group_scores.keys()),
                    default=sorted(group_scores.keys()),
                )
            case_select_container = filter_columns[1].container()

            toggle_columns = st.columns(2)
            with toggle_columns[0]:
                only_failed = st.checkbox("Show only failed cases", value=False)
            with toggle_columns[1]:
                hide_non_verified = st.checkbox(
                    "Hide unverified attributes",
                    value=True,
                    help="Hide attributes that weren't verified (stderr always shown)",
                )

            # Filter cases (maintain execution order from report.reports)
            filtered_cases = [
                r
                for r in report.reports
                if r.group in selected_groups
                and (not only_failed or not math.isclose(r.calculate_score(), 1.0))
            ]

            if not filtered_cases:
                with case_select_container:
                    st.info("No cases available for selection.")
                st.session_state.selected_case_idx = 0
                st.warning("No cases match the current filters.")
            else:
                # Ensure selected index is within bounds
                if st.session_state.selected_case_idx >= len(filtered_cases):
                    st.session_state.selected_case_idx = 0

                case_options = [f"{case.group}/{case.id}" for case in filtered_cases]
                with case_select_container:
                    selected_label = st.selectbox(
                        "Select Case",
                        options=case_options,
                        index=st.session_state.selected_case_idx,
                        key="case_selector",
                    )

                st.session_state.selected_case_idx = case_options.index(selected_label)

                # Display selected case
                selected_case = filtered_cases[st.session_state.selected_case_idx]
                score = selected_case.calculate_score()

                st.subheader(f"Case: {selected_case.group}/{selected_case.id}")

                col1, col2, col3 = st.columns([1, 1, 1])
                with col1:
                    st.metric("Score", f"{score:.2%}")
                with col2:
                    st.metric("Duration", f"{selected_case.duration:.2f}s")
                with col3:
                    if st.button("👁️ View Case Details", use_container_width=True):
                        show_case_modal(selected_case)

                # Display attribute results
                st.markdown("#### Attribute Results")
                for attr_name, attr_result in selected_case.results.items():
                    # Filter logic: hide unverified attributes except stderr
                    if (
                        hide_non_verified
                        and attr_result.is_correct is None
                        and attr_name != "stderr"
                    ):
                        continue
                    display_attribute_result(attr_name, attr_result)

        with tab2:
            # Display logs
            if st.session_state.log_path:
                display_evaluation_logs(st.session_state.log_path)
            else:
                st.info("No log file available yet.")


if __name__ == "__main__":
    main()
