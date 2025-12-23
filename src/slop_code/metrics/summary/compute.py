"""Main entry point for run summary computation.

This module provides the orchestrating function that combines all aggregators
to produce a complete RunSummary.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from slop_code.metrics.models import RunSummary
from slop_code.metrics.summary.aggregators import compute_cc_stats
from slop_code.metrics.summary.aggregators import compute_composite_scores
from slop_code.metrics.summary.aggregators import compute_costs_stats
from slop_code.metrics.summary.aggregators import compute_delta_stats
from slop_code.metrics.summary.aggregators import compute_pass_rates_stats
from slop_code.metrics.summary.aggregators import compute_ratios_stats
from slop_code.metrics.summary.aggregators import compute_solve_rates
from slop_code.metrics.summary.aggregators import compute_steps_stats
from slop_code.metrics.summary.aggregators import compute_time_stats
from slop_code.metrics.summary.aggregators import compute_tokens_stats
from slop_code.metrics.summary.stats import group_by_problem


def compute_run_summary(
    config: dict, checkpoints: list[dict[str, Any]]
) -> RunSummary:
    """Compute complete summary statistics from checkpoint data.

    Args:
        config: Run configuration dictionary.
        checkpoints: List of checkpoint data dictionaries.

    Returns:
        RunSummary with all computed statistics.
    """
    problems = group_by_problem(checkpoints)
    solve_rates = compute_solve_rates(checkpoints, problems)
    composite = compute_composite_scores(checkpoints)

    return RunSummary(
        model=config["model"]["name"],
        thinking=config["thinking"],
        prompt=Path(config["prompt_path"]).stem,
        agent_type=config["agent"]["type"],
        agent_version=config["agent"].get("version"),
        num_problems=len(problems),
        num_checkpoints=len(checkpoints),
        costs=compute_costs_stats(checkpoints, problems),
        time=compute_time_stats(checkpoints, problems),
        tokens=compute_tokens_stats(checkpoints, problems),
        steps=compute_steps_stats(checkpoints, problems),
        **solve_rates,
        pass_rates=compute_pass_rates_stats(checkpoints, problems),
        cc=compute_cc_stats(checkpoints),
        ratios=compute_ratios_stats(checkpoints),
        delta=compute_delta_stats(checkpoints),
        **composite,
    )
