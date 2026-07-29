from __future__ import annotations

import pandas as pd

from slop_code.dashboard.data import compute_problem_deltas
from slop_code.dashboard.data import process_checkpoint_row


def test_process_checkpoint_row_uses_new_pass_rate_names() -> None:
    processed = process_checkpoint_row(
        {
            "strict_pass_rate": 1.0,
            "isolated_pass_rate": 0.0,
            "total_tests": 10,
            "passed_tests": 5,
        }
    )

    assert processed["passed_chkpt"] is True


def test_problem_deltas_need_no_scb_metrics() -> None:
    deltas = compute_problem_deltas(
        pd.DataFrame(
            [
                {
                    "display_name": "Run A",
                    "problem": "prob1",
                    "idx": 1,
                    "loc": 10,
                    "lint_errors": 2,
                    "cc_high_count": 1,
                    "cc_max": 3,
                },
                {
                    "display_name": "Run A",
                    "problem": "prob1",
                    "idx": 2,
                    "loc": 20,
                    "lint_errors": 1,
                    "cc_high_count": 2,
                    "cc_max": 4,
                },
            ]
        )
    )

    assert deltas["lines_delta_pct"].item() == 100
    assert "verbosity_delta_pct" not in deltas
