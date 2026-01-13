"""Data filtering and transformation utilities for visualization."""

from __future__ import annotations

import numpy as np
import pandas as pd
from plotly.colors import qualitative

from slop_code.visualization.constants import MODEL_DISPLAY_NAMES
from slop_code.visualization.constants import VERSION_COLORS


def get_provider(model_name: str) -> str:
    """Infer provider from model name.

    Args:
        model_name: Model identifier (e.g., 'opus-4.5', 'gpt-5.1-codex-max', 'glm-4.7')

    Returns:
        Provider name: 'anthropic', 'openai', or 'zhipu'

    Raises:
        ValueError: If provider cannot be determined
    """
    if "opus" in model_name or "sonnet" in model_name:
        return "anthropic"
    if "gpt" in model_name:
        return "openai"
    if "glm" in model_name:
        return "zhipu"
    raise ValueError(f"Unknown model: {model_name}")


def filter_version_data(
    df: pd.DataFrame,
    versions: list[str],
    model: str | None = None,
    thinking: str | None = None,
    version_col: str = "agent_version",
) -> pd.DataFrame:
    """Filter dataframe to specific versions/model/thinking.

    Args:
        df: DataFrame with version data
        versions: List of versions to include
        model: Optional model name filter (e.g., 'opus-4.5')
        thinking: Optional thinking level filter (e.g., 'high')
        version_col: Column containing version info (default: 'agent_version')

    Returns:
        Filtered DataFrame copy
    """
    mask = df[version_col].isin(versions)
    if model is not None:
        mask &= df["model"] == model
    if thinking is not None:
        mask &= df["thinking"] == thinking
    return df[mask].copy()


def filter_high_thinking_checkpoints(df: pd.DataFrame) -> pd.DataFrame:
    """Filter to high thinking runs, using v2.0.51 for opus-4.5.

    This applies the standard filtering for checkpoint analysis:
    - Only 'high' thinking level
    - For opus-4.5, only version 2.0.51 (for consistency)
    - Extracts checkpoint number from 'checkpoint_N' format

    Args:
        df: Checkpoints DataFrame

    Returns:
        Filtered DataFrame with 'cp_num' column added
    """
    high = df[df["thinking"] == "high"].copy()
    high = high[
        (high["model"] != "opus-4.5") | (high["agent_version"] == "2.0.51")
    ]
    high["cp_num"] = (
        high["checkpoint"].str.extract(r"checkpoint_(\d+)").astype(int)
    )
    return high


def get_version_colors(versions: list[str]) -> dict[str, str]:
    """Return consistent color mapping for versions.

    Uses predefined VERSION_COLORS when available, falls back to
    Plotly's Pastel palette for unknown versions.

    Args:
        versions: List of version strings

    Returns:
        Dict mapping version to hex color
    """
    colors = {}
    fallback_palette = qualitative.Pastel
    fallback_idx = 0

    for v in versions:
        if v in VERSION_COLORS:
            colors[v] = VERSION_COLORS[v]
        else:
            colors[v] = fallback_palette[fallback_idx % len(fallback_palette)]
            fallback_idx += 1
    return colors


def normalize_per_1k_loc(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """Normalize columns by LOC * 1000.

    Creates new columns named '{col}_per_1k' for each input column.

    Args:
        df: DataFrame with 'loc' column
        cols: Columns to normalize

    Returns:
        DataFrame with new normalized columns added
    """
    df = df.copy()
    for col in cols:
        df[f"{col}_per_1k"] = df[col] / df["loc"] * 1000
    return df


def compute_progress_bins(df: pd.DataFrame) -> pd.DataFrame:
    """Add progress % column to checkpoint data.

    Progress = checkpoint_index / max_checkpoint for that problem.
    Bins into 5 buckets (0.2, 0.4, 0.6, 0.8, 1.0).

    Args:
        df: Checkpoints DataFrame with 'checkpoint' and 'problem' columns

    Returns:
        DataFrame with 'cp_num', 'progress', and 'progress_bin' columns added
    """
    df = df.copy()
    df["cp_num"] = df["checkpoint"].str.extract(r"checkpoint_(\d+)").astype(int)
    max_cp = df.groupby("problem")["cp_num"].transform("max")
    df["progress"] = df["cp_num"] / max_cp
    df["progress_bin"] = np.ceil(df["progress"] * 5) / 5
    df.loc[df["progress_bin"] == 0, "progress_bin"] = 0.2
    return df


def compute_progress_metric(
    df: pd.DataFrame, metric_col: str, num_bins: int = 5
) -> pd.DataFrame:
    """Compute progress % and aggregate metric by model.

    Progress = checkpoint_idx / total_checkpoints for that problem.
    Bins into buckets and averages.
    If multiple checkpoints from same problem fall in same bin, take the later one.

    Args:
        df: Filtered checkpoints DataFrame with 'cp_num' column
        metric_col: Column name to aggregate
        num_bins: Number of progress bins (default 5 = 20% bins, use 10 for 10% bins)

    Returns:
        DataFrame with columns: model, progress_bin, {metric_col}
    """
    max_cp = df.groupby("problem")["cp_num"].max()
    df = df.copy()
    df["max_cp"] = df["problem"].map(max_cp)
    df["progress"] = df["cp_num"] / df["max_cp"]
    bin_size = 1.0 / num_bins
    df["progress_bin"] = np.ceil(df["progress"] * num_bins) / num_bins
    df.loc[df["progress_bin"] == 0, "progress_bin"] = (
        bin_size  # Move 0 to first bin
    )

    # If multiple checkpoints from same problem in same bin, take the later one
    df = df.sort_values("cp_num", ascending=False)
    df = df.drop_duplicates(
        subset=["model", "problem", "progress_bin"], keep="first"
    )

    return (
        df.groupby(["model", "progress_bin"])[metric_col].mean().reset_index()
    )


def format_model_display_name(model: str) -> str:
    """Format model name for display.

    Uses MODEL_DISPLAY_NAMES lookup, falls back to title-casing with
    GPT capitalization fix.

    Args:
        model: Raw model name (e.g., 'opus-4.5', 'gpt-5.1-codex-max')

    Returns:
        Display-friendly name (e.g., 'Opus 4.5', 'GPT-5.1 Codex Max')
    """
    if model in MODEL_DISPLAY_NAMES:
        return MODEL_DISPLAY_NAMES[model]
    return model.replace("-", " ").title().replace("Gpt", "GPT")


def select_best_version_per_model(
    df: pd.DataFrame,
    opus_version: str = "2.0.51",
) -> pd.DataFrame:
    """Select best version for each model.

    For opus-4.5, uses a specific version (default 2.0.51) for consistency.
    For other models, uses the highest version.

    Args:
        df: DataFrame with 'model' and 'agent_version' columns
        opus_version: Specific version to use for opus-4.5

    Returns:
        DataFrame with one row per model
    """

    def select_version(group, model):
        if model == "opus-4.5":
            matching = group[group["agent_version"] == opus_version]
            if len(matching) > 0:
                return matching.iloc[0]
        return group.sort_values(by="agent_version", ascending=False).iloc[0]

    return (
        df.groupby("model")
        .apply(lambda x: select_version(x, x.name), include_groups=False)
        .reset_index()
    )
