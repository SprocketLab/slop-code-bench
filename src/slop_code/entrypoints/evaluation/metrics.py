from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from slop_code.common import PROBLEM_CONFIG_NAME
from slop_code.common import RUN_INFO_FILENAME
from slop_code.common import to_relative_path
from slop_code.evaluation import ProblemConfig
from slop_code.logging import get_logger
from slop_code.metrics import MetricsError
from slop_code.metrics import get_checkpoint_metrics

logger = get_logger(__name__)


def get_run_summary(submission_dir: Path) -> dict[str, Any] | None:
    """Load run summary from run_info.yaml.

    Args:
        submission_dir: Path to the submission directory containing run_info.yaml

    Returns:
        Dict with run-level summary data, or None if file doesn't exist or is invalid.
        Contains keys like: state, total_cost, duration_seconds, checkpoints (dict of states)
    """
    run_info_path = submission_dir / RUN_INFO_FILENAME
    if not run_info_path.exists():
        logger.debug(
            "run_info.yaml not found",
            submission_dir=str(submission_dir),
        )
        return None

    try:
        with run_info_path.open("r") as f:
            run_info = yaml.safe_load(f)
    except yaml.YAMLError as e:
        logger.warning(
            "Failed to parse run_info.yaml",
            submission_dir=str(submission_dir),
            error=str(e),
        )
        return None

    # Extract summary section if present
    summary = run_info.get("summary", {})
    return {
        # Run spec fields
        "seed": run_info.get("seed"),
        "pass_policy": run_info.get("pass_policy"),
        "skip_evaluation": run_info.get("skip_evaluation"),
        # Summary fields
        "state": summary.get("state"),
        "total_cost": summary.get("total_cost"),
        "total_steps": summary.get("total_steps"),
        "duration_seconds": summary.get("duration_seconds"),
        "started": summary.get("started"),
        "ended": summary.get("ended"),
        "passed": summary.get("passed"),
        "passed_policy": summary.get("passed_policy"),
        "overall_pass_rate": summary.get("overall_pass_rate"),
        "checkpoints": summary.get("checkpoints", {}),
        "error_type": summary.get("error_type"),
        "error_message": summary.get("error_message"),
    }


def create_checkpoint_report(
    checkpoint_dir: Path,
    checkpoint_name: str,
    problem: ProblemConfig,
    problem_version: str,
) -> dict[str, Any] | None:
    """Create a report for a single checkpoint.

    Args:
        checkpoint_dir: Path to the checkpoint directory
        checkpoint_name: Name of the checkpoint
        problem: Problem configuration
        problem_version: Version string from problem.yaml

    Returns:
        Report dict with metrics, or None if checkpoint data is incomplete
    """
    if not checkpoint_dir.exists():
        return None

    # Load checkpoint state from parent run_info.yaml
    submission_dir = checkpoint_dir.parent
    run_summary = get_run_summary(submission_dir)
    checkpoint_states = (
        run_summary.get("checkpoints", {}) if run_summary else {}
    )
    checkpoint_state = checkpoint_states.get(checkpoint_name, "unknown")

    try:
        return {
            "problem": problem.name,
            "version": problem_version,
            "checkpoint": checkpoint_name,
            "path": to_relative_path(checkpoint_dir),
            "idx": problem.checkpoints[checkpoint_name].order,
            "state": checkpoint_state,
            **get_checkpoint_metrics(checkpoint_dir),
        }
    except MetricsError as e:
        logger.error(
            "Failed to collect metrics for checkpoint",
            checkpoint_name=checkpoint_name,
            error=str(e),
        )
        return None


def create_problem_reports(
    submission_dir: Path, problem: ProblemConfig
) -> tuple[list[dict[str, Any]], list[tuple[str, str]]]:
    """Create reports for all checkpoints in a problem submission.

    Returns:
        A tuple of (reports list, errors list). Each error is (checkpoint_name, error_msg).
    """
    logger.debug("Creating problem reports", submission_dir=str(submission_dir))
    problem_yaml_path = submission_dir / PROBLEM_CONFIG_NAME
    if not problem_yaml_path.exists():
        logger.error(
            "problem.yaml not found in submission directory",
            submission_dir=str(submission_dir),
        )
        return [], [("problem.yaml", f"File not found: {problem_yaml_path}")]

    with problem_yaml_path.open("r") as f:
        problem_cfg_found = yaml.safe_load(f)

    # Load run summary for checkpoint states and run-level data
    run_summary = get_run_summary(submission_dir)
    checkpoint_states = (
        run_summary.get("checkpoints", {}) if run_summary else {}
    )

    out = []
    errors: list[tuple[str, str]] = []
    prior_metrics = None
    prior_checkpoint_dir = None
    for idx, checkpoint_name in enumerate(
        sorted(
            problem.checkpoints.keys(),
            key=lambda x: problem.checkpoints[x].order,
        )
    ):
        checkpoint_dir = submission_dir / checkpoint_name
        if not checkpoint_dir.exists():
            logger.warning(
                "Checkpoint directory not found",
                checkpoint_dir=str(checkpoint_dir),
            )
            errors.append(
                (checkpoint_name, f"File not found: {checkpoint_dir}")
            )
            continue
        metrics = get_checkpoint_metrics(
            checkpoint_dir,
            prior_metrics=prior_metrics,
            prior_checkpoint_dir=prior_checkpoint_dir,
            is_first=idx == 0,
            is_last=idx == len(problem.checkpoints) - 1,
        )

        out.append(
            {
                "problem": problem.name,
                "version": problem_cfg_found.get("version", "unknown"),
                "checkpoint": checkpoint_name,
                "path": str(submission_dir),
                "idx": problem.checkpoints[checkpoint_name].order,
                "state": checkpoint_states.get(checkpoint_name, "unknown"),
                **metrics,
            }
        )
        prior_metrics = metrics
        prior_checkpoint_dir = checkpoint_dir

    return out, errors


def update_results_jsonl(
    results_file: Path,
    new_reports: list[dict[str, Any]],
) -> None:
    """Update results.jsonl with new reports, preserving unmodified entries.

    Uses (problem, checkpoint) as the unique key for each entry.
    New reports replace existing entries with matching keys.

    Args:
        results_file: Path to the results.jsonl file
        new_reports: List of report dicts to add/update
    """
    existing_entries: dict[tuple[str, str], dict[str, Any]] = {}

    if results_file.exists():
        with results_file.open("r") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    key = (
                        entry.get("problem", ""),
                        entry.get("checkpoint", ""),
                    )
                    existing_entries[key] = entry
                except json.JSONDecodeError as e:
                    logger.warning(
                        "Skipping malformed JSON line in results.jsonl",
                        line_num=line_num,
                        error=str(e),
                    )

    for report in new_reports:
        key = (report.get("problem", ""), report.get("checkpoint", ""))
        existing_entries[key] = report

    with results_file.open("w") as f:
        for entry in existing_entries.values():
            f.write(json.dumps(entry) + "\n")
