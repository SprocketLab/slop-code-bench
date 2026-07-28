from __future__ import annotations

import pandas as pd

from slop_code.dashboard.data import ChartContext
from slop_code.dashboard.graphs.scatter import SCATTER_CHARTS
from slop_code.dashboard.graphs.scatter import aggregate_time_vs_solve


def _build_context(run_summaries: pd.DataFrame) -> ChartContext:
    return ChartContext(
        checkpoints=pd.DataFrame(),
        run_summaries=run_summaries,
        color_map={},
        base_color_map={"Run A": "#123456"},
    )


def test_aggregate_time_vs_solve_skips_missing_time() -> None:
    context = _build_context(
        pd.DataFrame(
            [
                {
                    "display_name": "Run A",
                    "model_name": "model-a",
                    "thinking": "none",
                    "prompt_template": "default",
                    "agent_type": "codex",
                    "agent_version": "1",
                    "run_date": "2026-03-20",
                    "pct_checkpoints_solved": 80.0,
                }
            ]
        )
    )

    metrics = aggregate_time_vs_solve(context)

    assert metrics == []


def test_scatter_catalog_needs_no_scb_metrics() -> None:
    assert all(
        "verbosity" not in chart and "erosion" not in chart
        for chart in SCATTER_CHARTS
    )
