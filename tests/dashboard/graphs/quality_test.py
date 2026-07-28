from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from slop_code.dashboard.data import ChartContext
from slop_code.dashboard.graphs.boxplot import build_checkpoint_delta_boxplot
from slop_code.dashboard.graphs.comparison import (
    build_problem_comparison_chart,
)


def _titles(figure: go.Figure) -> set[str]:
    return {
        annotation.text
        for annotation in figure.layout.annotations
        if annotation.text
    }


def test_quality_charts_need_no_scb_metrics() -> None:
    metadata = {
        "display_name": "Run A",
        "model_name": "model-a",
        "_thinking_sort_key": 0,
        "thinking": "none",
        "prompt_template": "default",
        "agent_type": "codex",
        "agent_version": "1",
        "run_date": "2026-07-28",
    }
    checkpoints = pd.DataFrame(
        [
            {
                **metadata,
                "problem": "prob1",
                "idx": idx,
                "loc": 10 * idx,
                "lint_errors": 3 - idx,
                "cc_high_count": idx,
                "cc_max": idx + 2,
                "rubric_total_flags": idx,
                "rubric_carried_over": idx - 1,
                "output": 100 * idx,
                "cost": 0.1 * idx,
                "passed_tests": idx,
                "total_tests": 2,
                "core_passed": idx,
                "core_total": 2,
                "functionality_passed": idx,
                "functionality_total": 2,
                "regression_passed": idx,
                "regression_total": 2,
                "error_passed": idx,
                "error_total": 2,
                "mass.cc": 0.1 * idx,
                "delta.loc": 0.2 * idx,
                "delta.churn_ratio": 0.3 * idx,
                "cc_concentration": 0.4 * idx,
            }
            for idx in (1, 2)
        ]
    )
    context = ChartContext(
        checkpoints=checkpoints,
        run_summaries=pd.DataFrame([metadata]),
        color_map={"Run A": "#123456"},
        base_color_map={"Run A": "#123456"},
    )

    comparison = build_problem_comparison_chart(context, "prob1")
    deltas = build_checkpoint_delta_boxplot(context)

    assert comparison.data
    assert deltas.data
    assert "Verbosity" not in _titles(comparison)
    assert "Verbosity" not in _titles(deltas)
