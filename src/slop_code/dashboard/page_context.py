"""Shared helpers for building page callback inputs.

The dashboard pages all read `selected-runs-store` (a list of run paths as
strings) and then build a `ChartContext`. Centralizing that logic keeps page
modules small and consistent.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import plotly.graph_objects as go

from slop_code.dashboard.data import ChartContext
from slop_code.dashboard.data import build_chart_context


def empty_figure() -> go.Figure:
    """Return an empty Plotly figure for "no selection" states."""

    return go.Figure()


def build_context(
    selected_paths: Sequence[str] | None,
    use_generic_colors: bool = False,
    group_runs: bool = False,
    common_problems_only: bool = False,
) -> ChartContext | None:
    """Build a `ChartContext` from `selected-runs-store` paths.

    Returns `None` when no runs are selected.
    """

    if not selected_paths:
        return None
    paths = [Path(path_str) for path_str in selected_paths]
    return build_chart_context(
        paths,
        use_generic_colors=use_generic_colors,
        group_runs=group_runs,
        common_problems_only=common_problems_only,
    )
