"""Data loading and processing logic for the dashboard.

Adapted from scripts/visualizations/make_graphs.py.
"""

from __future__ import annotations

import colorsys
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from itertools import cycle
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.colors
import yaml

from slop_code.common import CHECKPOINT_RESULTS_FILENAME
from slop_code.common import SUMMARY_FILENAME

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MODEL_TO_READABLE: dict[str, str] = {
    "opus-4.5": "Opus 4.5",
    "sonnet-4.5": "Sonnet 4.5",
    "gpt-5.1-codex": "GPT 5.1 Codex",
    "gpt-5.1-codex-max": "GPT 5.1 Codex Max",
    "gpt-5.2-codex": "GPT 5.2 Codex",
    "gpt-5.2": "GPT 5.2",
    "kimi-k2-thinking": "Kimi K2",
    "moonshotai/kimi-k2-thinking": "Kimi K2",
}

DEFAULT_COLOR_PALETTE = plotly.colors.qualitative.Vivid


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------


@dataclass
class ChartContext:
    """Shared context for chart builders."""

    checkpoints: pd.DataFrame
    run_summaries: pd.DataFrame
    color_map: dict[str, str]  # Gradient colors for bar/box charts
    base_color_map: dict[str, str]  # Provider base colors for scatter plots
    group_runs: bool = False
    common_problems_only: bool = False


@dataclass
class ModelVariationInfo:
    """Tracks what varies within a model's runs."""

    thinking_varies: bool
    prompt_varies: bool
    agent_varies: bool
    version_varies: bool
    date_varies: bool


# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------

THINKING_ORDER = {"none": 0, "low": 1, "medium": 2, "high": 3}


def _get_thinking_sort_value(thinking_str: str | None) -> int:
    return THINKING_ORDER.get(
        thinking_str.lower() if thinking_str else "none", 0
    )


def _extract_date_from_run_name(run_name: str) -> str:
    """Extract date from run directory name (YYYYMMDD format)."""
    match = re.search(r"(202\d{5})", run_name)
    if match:
        date_str = match.group(1)
        # Format as YYYY-MM-DD
        return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
    return ""


def _extract_full_timestamp_from_run_name(run_name: str) -> str:
    """Extract full timestamp from run directory name (YYYYMMDDTHHMM format)."""
    match = re.search(r"(202\d{5}T\d{4})", run_name)
    if match:
        timestamp_str = match.group(1)
        # Format as YYYY-MM-DD HH:MM
        date_part = (
            f"{timestamp_str[:4]}-{timestamp_str[4:6]}-{timestamp_str[6:8]}"
        )
        time_part = f"{timestamp_str[9:11]}:{timestamp_str[11:13]}"
        return f"{date_part} {time_part}"
    return ""


def _hsl_to_hex(h: int, s: int, l: int) -> str:
    """Convert HSL values to hex color string."""
    s = s / 100
    l = l / 100
    c = (1 - abs(2 * l - 1)) * s
    x = c * (1 - abs((h / 60) % 2 - 1))
    m = l - c / 2

    if h < 60:
        r, g, b = c, x, 0
    elif h < 120:
        r, g, b = x, c, 0
    elif h < 180:
        r, g, b = 0, c, x
    elif h < 240:
        r, g, b = 0, x, c
    elif h < 300:
        r, g, b = x, 0, c
    else:
        r, g, b = c, 0, x

    r, g, b = int((r + m) * 255), int((g + m) * 255), int((b + m) * 255)
    return f"#{r:02x}{g:02x}{b:02x}"


def _parse_to_hsl_tuple(color: str) -> tuple[int, int, int]:
    """Convert hex or rgb string to HSL tuple."""
    # Handle rgb(r, g, b)
    if color.startswith("rgb"):
        parts = re.findall(r"\d+", color)
        if len(parts) >= 3:
            r, g, b = map(int, parts[:3])
            h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
            return int(h * 360), int(s * 100), int(l * 100)

    # Handle Hex
    hex_color = color.lstrip("#")
    if len(hex_color) == 3:
        hex_color = "".join(c * 2 for c in hex_color)
    try:
        r, g, b = (
            int(hex_color[0:2], 16),
            int(hex_color[2:4], 16),
            int(hex_color[4:6], 16),
        )
        h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
        return int(h * 360), int(s * 100), int(l * 100)
    except ValueError:
        return 0, 0, 50


def _generate_variant_colors(base_color: str, count: int) -> list[str]:
    """Generate light-to-dark gradient colors for a variant group."""
    if count == 0:
        return []
    if count == 1:
        # Ensure output is always hex
        h, s, l = _parse_to_hsl_tuple(base_color)
        return [_hsl_to_hex(h, s, l)]

    h, s, _ = _parse_to_hsl_tuple(base_color)
    # Generate lightness values from light (75) to dark (35)
    light_start, light_end = 75, 35
    step = (light_start - light_end) / (count - 1)

    return [
        _hsl_to_hex(h, s, int(light_start - i * step)) for i in range(count)
    ]


def _format_prompt_display(prompt_template: str) -> str:
    """Convert prompt template path to display string."""
    prompt_stem = Path(prompt_template).stem if prompt_template else ""
    if not prompt_stem:
        return "Default"
    words = re.split(r"[_-]", prompt_stem)
    return "".join(word.title() for word in words)


def _format_agent_display(agent_type: str, agent_version: str = "") -> str:
    """Convert agent type to display string."""
    if not agent_type:
        return "Default"
    words = re.split(r"[_-]", agent_type)
    display = "".join(word.title() for word in words)
    if agent_version and str(agent_version).lower() not in ("none", "", "null"):
        display += f" v{agent_version}"
    return display


def _is_thinking_enabled(row: pd.Series | dict[str, Any]) -> tuple[bool, str]:
    """Check if thinking is enabled and return (enabled, display_value)."""
    thinking = str(row.get("thinking", "")).lower()
    enabled = bool(
        thinking and thinking not in ("none", "disabled", "unknown", "null")
    )
    return enabled, thinking.title() if enabled else ""


# ---------------------------------------------------------------------------
# Data Loading
# ---------------------------------------------------------------------------


def get_readable_model(model_id: str) -> str:
    """Convert internal model identifiers to readable names."""
    return MODEL_TO_READABLE.get(model_id, model_id)


def get_display_annotation(row: pd.Series | dict[str, Any]) -> str:
    """Construct display annotation from model, thinking, and prompt template."""
    model_name = row["model_name"]
    prompt_template = str(row.get("prompt_template", ""))
    agent_type = str(row.get("agent_type", ""))
    agent_version = str(row.get("agent_version", ""))
    thinking_enabled, thinking_display = _is_thinking_enabled(row)
    prompt_display = _format_prompt_display(prompt_template)
    agent_display = _format_agent_display(agent_type, agent_version)

    # Use full timestamp if available, otherwise fall back to date
    run_timestamp = str(row.get("run_timestamp", ""))
    run_date = str(row.get("run_date", ""))
    time_display = run_timestamp if run_timestamp else run_date

    annotation = model_name
    if thinking_enabled:
        annotation = f"{annotation} {thinking_display}"

    # Include agent if not default/empty, similar to prompt
    extras = []
    if agent_display != "Default":
        extras.append(agent_display)
    if prompt_display != "Default":
        extras.append(prompt_display)

    # If both are default, maybe show nothing? Or keep prompt display?
    # Original logic always showed prompt display even if "Default".
    # Let's keep existing behavior for prompt but add agent.
    if not extras and prompt_display == "Default":
        extras.append(prompt_display)

    # If we have extras, append them
    if extras:
        annotation = f"{annotation} ({', '.join(extras)})"
    elif (
        prompt_display == "Default"
    ):  # Should be covered above but safe fallback
        annotation = f"{annotation} ({prompt_display})"

    if time_display:
        annotation = f"{annotation} [{time_display}]"

    return annotation


def get_short_annotation(
    row: pd.Series | dict[str, Any], use_html: bool = False
) -> str:
    """Get short annotation with just prompt and thinking (no model name)."""
    prompt_template = str(row.get("prompt_template", ""))
    agent_type = str(row.get("agent_type", ""))
    agent_version = str(row.get("agent_version", ""))
    thinking_enabled, thinking_display = _is_thinking_enabled(row)
    prompt_display = _format_prompt_display(prompt_template)
    agent_display = _format_agent_display(agent_type, agent_version)
    run_date = str(row.get("run_date", ""))

    parts = []
    if thinking_enabled:
        parts.append(thinking_display)

    if agent_display != "Default":
        parts.append(agent_display)

    parts.append(prompt_display)

    if run_date:
        if use_html:
            parts.append(
                f'<span style="font-size: 0.8em; color: #555;">[{run_date}]</span>'
            )
        else:
            parts.append(f"[{run_date}]")

    # If parts has multiple items (thinking, agent, prompt), join with " - "
    # Original logic was: "{prompt} - {thinking}" or "{prompt}"
    # New logic: "{thinking} - {agent} - {prompt}" (if present)

    # Reconstruct to match previous ordering preference if possible?
    # Original: thinking first if enabled, then prompt.
    # Let's stick to simple join.
    return " - ".join(parts)


def get_variant_annotation(row: pd.Series | dict[str, Any]) -> str:
    """Get variant annotation without model name (for grouped legends)."""
    prompt_template = str(row.get("prompt_template", ""))
    agent_type = str(row.get("agent_type", ""))
    agent_version = str(row.get("agent_version", ""))
    thinking_enabled, thinking_display = _is_thinking_enabled(row)
    prompt_display = _format_prompt_display(prompt_template)
    agent_display = _format_agent_display(agent_type, agent_version)

    parts = []
    if thinking_enabled:
        parts.append(thinking_display)

    if agent_display != "Default":
        parts.append(agent_display)

    parts.append(prompt_display)

    return " - ".join(parts)


def analyze_model_variations(
    df: pd.DataFrame,
) -> dict[str, ModelVariationInfo]:
    """Analyze what varies within each model's runs."""
    model_variants: dict[str, set[tuple[str, str, str, str, str]]] = (
        defaultdict(set)
    )

    for _, row in df.iterrows():
        model_name = row["model_name"]
        thinking = str(row.get("thinking", "")).lower()
        prompt = str(row.get("prompt_template", ""))
        agent = str(row.get("agent_type", ""))
        version = str(row.get("agent_version", ""))
        run_date = str(row.get("run_date", ""))
        model_variants[model_name].add(
            (thinking, prompt, agent, version, run_date)
        )

    result = {}
    for model_name, variants in model_variants.items():
        thinkings = {t for t, _, _, _, _ in variants}
        prompts = {p for _, p, _, _, _ in variants}
        agents = {a for _, _, a, _, _ in variants}
        versions = {v for _, _, _, v, _ in variants}
        dates = {d for _, _, _, _, d in variants}
        result[model_name] = ModelVariationInfo(
            thinking_varies=len(thinkings) > 1,
            prompt_varies=len(prompts) > 1,
            agent_varies=len(agents) > 1,
            version_varies=len(versions) > 1,
            date_varies=len(dates) > 1,
        )
    return result


def get_dynamic_variant_annotation(
    row: pd.Series | dict[str, Any],
    variation_info: ModelVariationInfo | None,
    use_html: bool = False,
) -> str:
    """Get variant annotation based on what actually varies for this model."""
    thinking_enabled, thinking_display = _is_thinking_enabled(row)
    prompt_display = _format_prompt_display(str(row.get("prompt_template", "")))
    agent_display = _format_agent_display(
        str(row.get("agent_type", "")), str(row.get("agent_version", ""))
    )
    run_date = str(row.get("run_date", ""))

    def _fmt_date(d: str) -> str:
        if use_html:
            return f'<span style="font-size: 0.8em; color: #555;">{d}</span>'
        return d

    # Fallback to showing everything if no variation info
    if variation_info is None:
        parts = []
        if thinking_enabled:
            parts.append(thinking_display)
        if agent_display != "Default":
            parts.append(agent_display)
        parts.append(prompt_display)
        if run_date:
            parts.append(_fmt_date(run_date))
        return " - ".join(parts) if parts else "Base"

    parts = []
    if variation_info.thinking_varies and thinking_enabled:
        parts.append(thinking_display)
    if variation_info.agent_varies or variation_info.version_varies:
        parts.append(agent_display)
    if variation_info.prompt_varies:
        parts.append(prompt_display)
    if variation_info.date_varies and run_date:
        parts.append(_fmt_date(run_date))

    if not parts:
        return "Base"

    return " - ".join(parts)


def process_checkpoint_row(row: dict[str, Any]) -> dict[str, Any]:
    """Pass through raw checkpoint row with minimal processing."""

    def _full_pass(value: Any) -> bool:
        try:
            return float(value) >= 1.0
        except (TypeError, ValueError):
            return False

    tests_total = row.get("total_tests", 0)
    tests_passed = row.get("passed_tests", 0)

    processed = dict(row)
    processed["passed_chkpt"] = (
        _full_pass(row.get("pass_rate"))
        or _full_pass(row.get("checkpoint_pass_rate"))
        or (tests_total == tests_passed)
    )
    return processed


def flatten_summary(
    summary: dict[str, Any], prefix: str = ""
) -> dict[str, Any]:
    """Flatten a result.json summary into a single-level dict."""
    flattened: dict[str, Any] = {}
    for key, value in summary.items():
        full_key = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            flattened.update(flatten_summary(value, full_key))
        else:
            flattened[full_key] = value
    return flattened


def load_result_summary(run_dir: Path) -> dict[str, Any] | None:
    """Load the optional run-level summary from result.json."""
    summary_file = run_dir / SUMMARY_FILENAME
    if not summary_file.exists():
        print(f"Summary file not found at {summary_file}")
        return None

    try:
        return json.loads(summary_file.read_text())
    except json.JSONDecodeError as exc:
        print(f"Failed to parse {summary_file}: {exc}")
        return None


def load_config_metadata(run_dir: Path) -> dict[str, Any]:
    """Load model/prompt metadata from config.yaml and stats from result.json."""
    config_file = run_dir / "config.yaml"
    with config_file.open() as f:
        config = yaml.unsafe_load(f)
    agent_cfg = config["agent"]
    model = config["model"]["name"]
    thinking = config["thinking"]
    run_date = _extract_date_from_run_name(run_dir.name)
    run_timestamp = _extract_full_timestamp_from_run_name(run_dir.name)

    # Try to load num_problems from summary
    num_problems = 0
    summary = load_result_summary(run_dir)
    if summary:
        num_problems = summary.get("num_problems", 0)

    model_display = get_readable_model(model)
    agent_version = str(agent_cfg.get("version", ""))
    if agent_version and agent_version.lower() not in ("none", "", "null"):
        model_display = f"{model_display} v{agent_version}"

    return {
        "agent_type": agent_cfg["type"],
        "agent_version": agent_version,
        "model_name": model_display,
        "thinking": str(thinking),
        "prompt_template": Path(config.get("prompt_path", "unknown")).stem,
        "run_date": run_date,
        "run_timestamp": run_timestamp,
        "num_problems": num_problems,
    }


def load_run(run_dir: Path) -> tuple[pd.DataFrame, dict[str, Any] | None]:
    """Load checkpoint data and run summary for a directory."""
    results_path = run_dir / CHECKPOINT_RESULTS_FILENAME

    if not results_path.exists():
        return pd.DataFrame(), None

    try:
        metadata = {
            **load_config_metadata(run_dir),
            "run_name": run_dir.name,
            "run_path": str(run_dir),
        }
    except Exception as e:
        print(f"Error loading config for {run_dir}: {e}")
        return pd.DataFrame(), None

    checkpoints = []
    try:
        with results_path.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                raw_row = json.loads(line)
                checkpoints.append(
                    {**metadata, **process_checkpoint_row(raw_row)}
                )
    except Exception as e:
        print(f"Error loading checkpoints for {run_dir}: {e}")
        return pd.DataFrame(), None

    summary_data = load_result_summary(run_dir)
    summary_row = None
    if summary_data:
        summary_row = {**metadata, **flatten_summary(summary_data)}

    return pd.DataFrame(checkpoints), summary_row


def get_available_runs(base_dir: Path) -> list[Path]:
    """Find all run directories in the base directory."""
    runs = []
    # Search recursively for the results file
    for path in base_dir.rglob(CHECKPOINT_RESULTS_FILENAME):
        if path.is_file():
            runs.append(path.parent)
    return sorted(runs, key=lambda p: p.name)


def build_base_color_map(
    display_names: list[str],
    model_groups: dict[str, str],
    group_colors: dict[str, str],
) -> dict[str, str]:
    """Assign base group color to each run (no gradient)."""
    color_map = {}
    for name in display_names:
        group = model_groups.get(name, name)
        base_color = group_colors.get(group, "#333333")
        # Ensure consistency by converting to hex
        h, s, l = _parse_to_hsl_tuple(base_color)
        color_map[name] = _hsl_to_hex(h, s, l)
    return color_map


def build_color_map(
    display_names: list[str],
    model_groups: dict[str, str],
    group_colors: dict[str, str],
) -> dict[str, str]:
    """Assign gradient colors based on group (light-to-dark)."""
    grouped_names: dict[str, list[str]] = defaultdict(list)
    for name in display_names:
        group = model_groups.get(name, name)
        grouped_names[group].append(name)

    # Sort names within groups for consistent gradient assignment
    for group in grouped_names:
        grouped_names[group].sort()

    color_map = {}
    for group, names in grouped_names.items():
        base_hex = group_colors.get(group, "#333333")
        colors = _generate_variant_colors(base_hex, len(names))
        for name, color in zip(names, colors):
            color_map[name] = color

    return color_map


def build_generic_color_map(display_names: list[str]) -> dict[str, str]:
    """Assign distinct generic colors to each run from a standard palette."""
    color_map = {}
    num_colors = len(DEFAULT_COLOR_PALETTE)
    for i, name in enumerate(display_names):
        color_map[name] = DEFAULT_COLOR_PALETTE[i % num_colors]
    return color_map


def build_chart_context(
    runs: list[Path],
    use_generic_colors: bool = False,
    group_runs: bool = False,
    common_problems_only: bool = False,
) -> ChartContext:
    """Load all runs and prepare shared plotting context."""
    checkpoint_frames: list[pd.DataFrame] = []
    summary_rows: list[dict[str, Any]] = []

    for run_dir in runs:
        checkpoints, summary_row = load_run(run_dir)
        if not checkpoints.empty:
            checkpoint_frames.append(checkpoints)
        if summary_row:
            summary_rows.append(summary_row)

    checkpoints_df = (
        pd.concat(checkpoint_frames, ignore_index=True)
        if checkpoint_frames
        else pd.DataFrame()
    )
    run_summaries = pd.DataFrame(summary_rows)

    # --- Common Problems Filter ---
    if common_problems_only and not checkpoints_df.empty:
        # Find problems that exist in EVERY run
        problem_sets = []
        unique_run_paths = checkpoints_df["run_path"].unique()
        for run_path in unique_run_paths:
            probs = set(
                checkpoints_df[checkpoints_df["run_path"] == run_path][
                    "problem"
                ].unique()
            )
            problem_sets.append(probs)

        if problem_sets:
            common_probs = set.intersection(*problem_sets)
            checkpoints_df = checkpoints_df[
                checkpoints_df["problem"].isin(common_probs)
            ].copy()

            # Re-calculate summary stats from the filtered checkpoints
            # This ensures Overview bars reflect the subset
            new_summaries = []
            for run_path in unique_run_paths:
                run_chkpts = checkpoints_df[
                    checkpoints_df["run_path"] == run_path
                ]
                if run_chkpts.empty:
                    continue

                # Basic metrics
                total_chkpts = len(run_chkpts)
                passed_chkpts = run_chkpts["passed_chkpt"].sum()

                all_probs = run_chkpts["problem"].unique()
                solved_probs = run_chkpts[run_chkpts["passed_chkpt"]][
                    "problem"
                ].unique()

                # Get metadata from first row
                meta = run_chkpts.iloc[0].to_dict()

                # Construct new summary row
                summary_row = {
                    "run_path": run_path,
                    "model_name": meta["model_name"],
                    "thinking": meta["thinking"],
                    "agent_type": meta["agent_type"],
                    "agent_version": meta["agent_version"],
                    "prompt_template": meta["prompt_template"],
                    "run_date": meta["run_date"],
                    "run_timestamp": meta.get("run_timestamp", ""),
                    "pct_checkpoints_solved": (
                        passed_chkpts / total_chkpts * 100
                    )
                    if total_chkpts > 0
                    else 0,
                    "pct_problems_partial": (
                        len(solved_probs) / len(all_probs) * 100
                    )
                    if len(all_probs) > 0
                    else 0,
                    "costs.total": run_chkpts["cost"].sum()
                    if "cost" in run_chkpts.columns
                    else 0,
                    # We might miss some fields from result.json, but these are the main ones for Overview
                }

                # Try to preserve other fields from original run_summaries if they exist
                if not run_summaries.empty:
                    orig_row = run_summaries[
                        run_summaries["run_path"] == run_path
                    ]
                    if not orig_row.empty:
                        for col in run_summaries.columns:
                            if col not in summary_row:
                                summary_row[col] = orig_row.iloc[0][col]

                new_summaries.append(summary_row)

            run_summaries = pd.DataFrame(new_summaries)

    if not checkpoints_df.empty:
        checkpoints_df["display_name"] = checkpoints_df.apply(
            lambda row: get_display_annotation(row), axis=1
        )
        checkpoints_df["_thinking_sort_key"] = checkpoints_df["thinking"].apply(
            _get_thinking_sort_value
        )
    if not run_summaries.empty:
        run_summaries["display_name"] = run_summaries.apply(
            lambda row: get_display_annotation(row), axis=1
        )
        run_summaries["_thinking_sort_key"] = run_summaries["thinking"].apply(
            _get_thinking_sort_value
        )

    # --- Grouping Logic for display names ---
    if group_runs:
        # When grouping, we want to use a name that represents the group (Model + Thinking)
        def get_group_name(row):
            model_name = row["model_name"]
            thinking_enabled, thinking_display = _is_thinking_enabled(row)
            name = model_name
            if thinking_enabled:
                name = f"{name} {thinking_display}"
            return name

        if not checkpoints_df.empty:
            checkpoints_df["display_name"] = checkpoints_df.apply(
                get_group_name, axis=1
            )
        if not run_summaries.empty:
            run_summaries["display_name"] = run_summaries.apply(
                get_group_name, axis=1
            )

    # Prepare a list of tuples for sorting, then extract display_names in sorted order
    sortable_runs = []
    sort_cols = [
        "model_name",
        "_thinking_sort_key",
        "prompt_template",
        "run_date",
    ]

    if not checkpoints_df.empty:
        unique_runs = checkpoints_df[
            sort_cols + ["display_name"]
        ].drop_duplicates()
        for _, row in unique_runs.iterrows():
            sortable_runs.append(
                tuple(row[col] for col in sort_cols) + (row["display_name"],)
            )

    if not run_summaries.empty:
        unique_sum_runs = run_summaries[
            sort_cols + ["display_name"]
        ].drop_duplicates()
        for _, row in unique_sum_runs.iterrows():
            run_tuple = tuple(row[col] for col in sort_cols) + (
                row["display_name"],
            )
            if run_tuple not in sortable_runs:
                sortable_runs.append(run_tuple)

    # Sort the runs and extract display names
    sortable_runs.sort()
    sorted_names = [run[-1] for run in sortable_runs]

    # Generate model groups and colors
    model_groups = {}
    if not checkpoints_df.empty:
        model_groups.update(
            dict(
                zip(
                    checkpoints_df["display_name"], checkpoints_df["model_name"]
                )
            )
        )
    if not run_summaries.empty:
        model_groups.update(
            dict(
                zip(run_summaries["display_name"], run_summaries["model_name"])
            )
        )

    unique_groups = sorted(list(set(model_groups.values())))
    palette = cycle(DEFAULT_COLOR_PALETTE)
    group_colors = {group: next(palette) for group in unique_groups}

    if use_generic_colors:
        color_map = build_generic_color_map(sorted_names)
        base_color_map = color_map.copy()
    else:
        color_map = build_color_map(sorted_names, model_groups, group_colors)
        base_color_map = build_base_color_map(
            sorted_names, model_groups, group_colors
        )

    return ChartContext(
        checkpoints=checkpoints_df,
        run_summaries=run_summaries,
        color_map=color_map,
        base_color_map=base_color_map,
        group_runs=group_runs,
        common_problems_only=common_problems_only,
    )


# ---------------------------------------------------------------------------
# Data Processing Helpers
# ---------------------------------------------------------------------------


def _safe_delta_pct(prev_val: float | None, curr_val: float | None) -> float:
    prev_val = prev_val or 0
    curr_val = curr_val or 0
    if prev_val > 0:
        return ((curr_val - prev_val) / prev_val) * 100
    return 0 if curr_val == 0 else float("inf")


def compute_problem_deltas(df: pd.DataFrame) -> pd.DataFrame:
    results = []
    for (display_name, problem), group in df.groupby(
        ["display_name", "problem"]
    ):
        sort_col = "idx" if "idx" in group.columns else "checkpoint"
        sorted_group = group.sort_values(sort_col)

        if len(sorted_group) < 2:
            continue

        for i in range(1, len(sorted_group)):
            prev_row = sorted_group.iloc[i - 1]
            curr_row = sorted_group.iloc[i]

            # Non-carryover: total flags minus carried over flags
            total_flags = curr_row.get("rubric_total_flags", 0) or 0
            carried_over = curr_row.get("rubric_carried_over", 0) or 0
            rubric_non_carryover = total_flags - carried_over

            results.append(
                {
                    "display_name": display_name,
                    "model_name": curr_row.get("model_name"),
                    "_thinking_sort_key": curr_row.get("_thinking_sort_key"),
                    "prompt_template": curr_row.get("prompt_template"),
                    "run_date": curr_row.get("run_date"),
                    "problem": problem,
                    "from_idx": prev_row.get(sort_col),
                    "to_idx": curr_row.get(sort_col),
                    "lines_delta_pct": _safe_delta_pct(
                        prev_row.get("loc", 0),
                        curr_row.get("loc", 0),
                    ),
                    "lint_delta_pct": _safe_delta_pct(
                        prev_row.get("lint_errors", 0),
                        curr_row.get("lint_errors", 0),
                    ),
                    "ast_grep_delta_pct": _safe_delta_pct(
                        prev_row.get("ast_grep_violations", 0),
                        curr_row.get("ast_grep_violations", 0),
                    ),
                    "complex_delta_pct": _safe_delta_pct(
                        prev_row["cc_high_count"],
                        curr_row["cc_high_count"],
                    ),
                    "rubric_delta_pct": _safe_delta_pct(
                        prev_row.get("rubric_total_flags", 0),
                        curr_row.get("rubric_total_flags", 0),
                    ),
                    "rubric_non_carryover": rubric_non_carryover,
                    "cc_max_delta_pct": _safe_delta_pct(
                        prev_row["cc_max"],
                        curr_row["cc_max"],
                    ),
                }
            )

    return pd.DataFrame(results)


def compute_model_wins(df: pd.DataFrame) -> dict[str, int]:
    """Calculate the number of 'strict wins' for each model.

    A win is defined as having a strictly higher pass rate on a specific
    (problem, checkpoint) tuple compared to all other models in the dataframe.
    """
    if df.empty:
        return {}

    work_df = df.copy()

    # Calculate pass rate
    passed = work_df.get("passed_tests", 0).fillna(0)
    total = work_df.get("total_tests", 1).fillna(1).replace(0, 1)
    work_df["_pass_rate"] = passed / total

    # Identify checkpoint identifier
    chkpt_col = "idx" if "idx" in work_df.columns else "checkpoint"

    # Pivot: Index=(problem, chkpt_col), Columns=display_name, Values=_pass_rate
    try:
        pivot = work_df.pivot(
            index=["problem", chkpt_col],
            columns="display_name",
            values="_pass_rate",
        )
    except ValueError:
        # Handle duplicates if any
        pivot = work_df.pivot_table(
            index=["problem", chkpt_col],
            columns="display_name",
            values="_pass_rate",
            aggfunc="mean",
        )

    wins = defaultdict(int)

    for _, row in pivot.iterrows():
        # Filter out NaNs
        valid_scores = row.dropna()
        if len(valid_scores) < 2:
            continue

        max_score = valid_scores.max()
        # Find who got the max score
        winners = valid_scores[valid_scores == max_score].index.tolist()

        # Strict win: only 1 winner
        if len(winners) == 1:
            wins[winners[0]] += 1

    return dict(wins)


def get_summary_table_data(context: ChartContext) -> list[dict[str, Any]]:
    """Prepare data for the summary table."""
    df = context.run_summaries
    if df.empty:
        return []

    # Map run_path to output tokens
    token_counts = {}
    if (
        not context.checkpoints.empty
        and "output" in context.checkpoints.columns
    ):
        if "run_path" in context.checkpoints.columns:
            token_counts = (
                context.checkpoints.groupby("run_path")["output"]
                .sum()
                .to_dict()
            )

    # Compute wins
    wins_map = compute_model_wins(context.checkpoints)

    table_data = []
    # Sort by display_name for consistency
    df_sorted = df.sort_values(
        by=[
            "model_name",
            "_thinking_sort_key",
            "prompt_template",
            "run_date",
        ]
    )

    for _, row in df_sorted.iterrows():
        run_path = row.get("run_path")
        display_name = get_display_annotation(row)

        solved = row.get("pct_checkpoints_solved", 0)
        partial = row.get("pct_problems_partial", 0)
        cost = row.get("costs.total", 0)
        duration = row.get("duration", 0)
        if duration:
            duration = duration / 60
        else:
            duration = 0

        tokens = token_counts.get(run_path, 0)
        win_count = wins_map.get(display_name, 0)

        table_data.append(
            {
                "Model": display_name,
                "Solved (%)": round(solved, 1),
                "Partial (%)": round(partial, 1),
                "Wins": win_count,
                "Tokens": tokens,
                "Cost ($)": round(cost, 2),
                "Time (min)": round(duration, 1),
            }
        )
    return table_data
