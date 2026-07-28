from __future__ import annotations

import pandas as pd
import pytest

from slop_code.dashboard.data import ChartContext
from slop_code.dashboard.graphs.scatter import (
    aggregate_erosion_vs_problem_test_pass_rate,
)
from slop_code.dashboard.graphs.scatter import aggregate_erosion_vs_solve
from slop_code.dashboard.graphs.scatter import aggregate_time_vs_solve


def _build_context(run_summaries: pd.DataFrame) -> ChartContext:
    return ChartContext(
        checkpoints=pd.DataFrame(),
        run_summaries=run_summaries,
        color_map={},
        base_color_map={"Run A": "#123456"},
    )


def test_aggregate_erosion_vs_solve_uses_saved_verbosity_mean():
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
                    "verbosity.mean": 0.75,
                    "erosion.mean": 55.0,
                    "ratios.rubric.mean": 10.0,
                    "ratios.lint.mean": 30.0,
                    "pct_checkpoints_solved": 80.0,
                }
            ]
        )
    )

    metrics = aggregate_erosion_vs_solve(context)

    assert len(metrics) == 1
    assert metrics[0].x_value == pytest.approx(0.75)
    assert metrics[0].y_value == pytest.approx(80.0)


def test_aggregate_erosion_vs_problem_test_pass_rate_uses_saved_erosion_mean():
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
                    "verbosity.mean": 0.75,
                    "erosion.mean": 55.0,
                    "ratios.rubric.mean": 10.0,
                    "ratios.lint.mean": 30.0,
                    "pass_rates.problem.total": 0.6,
                }
            ]
        )
    )

    metrics = aggregate_erosion_vs_problem_test_pass_rate(context)

    assert len(metrics) == 1
    assert metrics[0].x_value == pytest.approx(55.0)
    assert metrics[0].y_value == pytest.approx(60.0)


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
