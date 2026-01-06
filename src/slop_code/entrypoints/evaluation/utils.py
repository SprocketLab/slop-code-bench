from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from typing import Any

import yaml

from slop_code.common import PROBLEM_CONFIG_NAME
from slop_code.common import RUN_INFO_FILENAME
from slop_code.entrypoints import utils
from slop_code.evaluation import CorrectnessResults
from slop_code.evaluation import PassPolicy
from slop_code.evaluation import ProblemConfig
from slop_code.logging import get_logger
from slop_code.metrics import SnapshotQualityReport

logger = get_logger(__name__)


class EvaluationError(Exception):
    """Base exception for evaluation errors.

    Captures structured error context for logging and reporting.

    Attributes:
        problem_name: Name of the problem that failed (if applicable)
        checkpoint_name: Name of the checkpoint that failed (if applicable)
        context: Additional context dict for logging
    """

    def __init__(
        self,
        message: str,
        *,
        problem_name: str | None = None,
        checkpoint_name: str | None = None,
        context: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.problem_name = problem_name
        self.checkpoint_name = checkpoint_name
        self.context = context or {}


def resolve_problem(
    submission_dir: Path,
    problem_path: Path,
    problem_name: str | None = None,
) -> ProblemConfig:
    found_name = None
    found_version = None
    found_cfg = None

    if (submission_dir / PROBLEM_CONFIG_NAME).exists():
        logger.info(
            "Loading problem configuration from submission directory",
            path=submission_dir / PROBLEM_CONFIG_NAME,
        )
        with (submission_dir / PROBLEM_CONFIG_NAME).open("r") as f:
            found_cfg = yaml.safe_load(f)
            found_name = found_cfg["name"]
            found_version = found_cfg["version"]
    # Attempt to find the problem name via the parameter or parent file name.
    if found_name is None:
        if problem_name is None:
            logger.info(
                "Using submission directory name as problem name",
                path=submission_dir,
            )
            found_name = submission_dir.name
        else:
            logger.info(
                "Using problem name parameter as problem name",
                problem_name=problem_name,
            )
            found_name = problem_name

    potential_problem_path = problem_path / found_name
    if not potential_problem_path.exists():
        logger.error(
            "Problem path does not exist",
            path=potential_problem_path,
            problem_name=found_name,
            problem_path=str(problem_path),
            submission_dir=str(submission_dir),
        )
        raise utils.CLIError(
            f"Problem path '{potential_problem_path}' does not exist."
        )
    problem_cfg = ProblemConfig.from_yaml(potential_problem_path)
    if found_version is not None and problem_cfg.version != found_version:
        logger.error(
            "Problem version mismatch",
            path=potential_problem_path,
            problem_name=found_name,
            problem_path=str(problem_path),
            submission_dir=str(submission_dir),
        )
        raise utils.CLIError(
            f"Problem version mismatch: {problem_cfg.version} != {found_version}"
        )

    return problem_cfg


def _compute_aggregated_eval_results(
    summaries: dict[str, tuple[CorrectnessResults, SnapshotQualityReport]],
    pass_policy: PassPolicy,
) -> tuple[bool, bool, float | None]:
    """Compute aggregated evaluation results from checkpoint summaries.

    Returns:
        Tuple of (all_passed, all_passed_policy, overall_pass_rate)
    """
    pass_rates = []
    all_passed = True
    all_passed_policy = True

    for checkpoint_name, (report, quality_report) in summaries.items():
        # Calculate pass rate for this checkpoint
        total_passed = sum(report.pass_counts.values())
        total_count = sum(report.total_counts.values())
        if total_count > 0:
            pass_rates.append(total_passed / total_count)

        # Check if this checkpoint passed
        checkpoint_passed_policy = pass_policy.check(
            report.pass_counts, report.total_counts
        )
        if not checkpoint_passed_policy:
            all_passed_policy = False
        if total_passed != total_count:
            all_passed = False

    overall_pass_rate = (
        sum(pass_rates) / len(pass_rates) if pass_rates else None
    )
    return all_passed, all_passed_policy, overall_pass_rate


def maybe_update_problem_report(
    submission_dir: Path,
    summaries: dict[str, tuple[CorrectnessResults, SnapshotQualityReport]],
):
    """Update problem report with evaluation results.

    Updates the summary section of run_info.yaml with aggregated pass/fail status.
    """
    run_info_path = submission_dir / RUN_INFO_FILENAME

    if not run_info_path.exists():
        return

    logger.debug(
        "Loading existing run info",
        path=run_info_path,
    )
    with run_info_path.open("r") as f:
        run_info = yaml.safe_load(f)

    pass_policy = PassPolicy(run_info.get("pass_policy", "any-case"))
    all_passed, all_passed_policy, overall_pass_rate = (
        _compute_aggregated_eval_results(summaries, pass_policy)
    )

    # Update summary section
    if "summary" not in run_info:
        run_info["summary"] = {}
    run_info["summary"]["passed"] = all_passed
    run_info["summary"]["passed_policy"] = all_passed_policy
    if overall_pass_rate is not None:
        run_info["summary"]["overall_pass_rate"] = overall_pass_rate

    with run_info_path.open("w") as f:
        yaml.dump(run_info, f, indent=2, sort_keys=True)


def gather_checkpoint_directories(
    problem: ProblemConfig, submission_dir: Path, snapshot_dir_name: str
) -> Generator[tuple[str, Path, Path], None, None]:
    checkpoint_items = list(problem.iterate_checkpoint_items())
    logger.info(
        "Gathering checkpoint directories",
        submission_dir=str(submission_dir),
        snapshot_dir_name=snapshot_dir_name,
        problem_name=problem.name,
        checkpoints=[name for name, _ in checkpoint_items],
    )

    for checkpoint_name, _ in checkpoint_items:
        try:
            chkpt_submission = utils.ensure_dir_exists(
                submission_dir / checkpoint_name
            )
        except FileNotFoundError:
            logger.warning(
                "Checkpoint submission directory does not exist",
                checkpoint_name=checkpoint_name,
                submission_dir=str(submission_dir),
            )
            continue
        try:
            chkpt_snapshot = utils.ensure_dir_exists(
                chkpt_submission / snapshot_dir_name
            )
        except FileNotFoundError:
            logger.warning(
                "Snapshot directory does not exist",
                checkpoint_name=checkpoint_name,
                submission_dir=str(chkpt_submission),
                snapshot_dir_name=snapshot_dir_name,
                problem_name=problem.name,
            )
            continue
        logger.debug(
            "Found checkpoint directory",
            checkpoint_name=checkpoint_name,
            snapshot=str(chkpt_snapshot),
            problem_name=problem.name,
        )
        yield checkpoint_name, chkpt_submission, chkpt_snapshot
