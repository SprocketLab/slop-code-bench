"""Main entry point for run summary computation.

This module provides the orchestrating function that combines all aggregators
to produce a complete RunSummary.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from slop_code.metrics.models import RunSummary
from slop_code.metrics.summary import aggregators
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

    return RunSummary(
        model=config["model"]["name"],
        thinking=config["thinking"],
        prompt=Path(config["prompt_path"]).stem,
        agent_type=config["agent"]["type"],
        agent_version=config["agent"].get("version"),
        num_problems=len(problems),
        num_checkpoints=len(checkpoints),
        costs=aggregators.compute_costs_stats(checkpoints, problems),
        time=aggregators.compute_time_stats(checkpoints, problems),
        tokens=aggregators.compute_tokens_stats(checkpoints, problems),
        steps=aggregators.compute_steps_stats(checkpoints, problems),
        **aggregators.compute_solve_rates(checkpoints, problems),
        pass_rates=aggregators.compute_pass_rates_stats(checkpoints, problems),
        cc=aggregators.compute_cc_stats(checkpoints),
        ratios=aggregators.compute_ratios_stats(checkpoints),
        delta=aggregators.compute_delta_stats(checkpoints),
        **aggregators.compute_composite_scores(checkpoints),
    )
