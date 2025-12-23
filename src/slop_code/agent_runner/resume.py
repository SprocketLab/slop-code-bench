"""Resume functionality for checkpoint-based execution.

This module provides utilities for detecting and resuming from the last
successful checkpoint when a run is interrupted or fails mid-execution.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from dataclasses import field
from enum import Enum
from pathlib import Path

import yaml

from slop_code.agent_runner.models import UsageTracker
from slop_code.agent_runner.reporting import CheckpointState
from slop_code.common import INFERENCE_RESULT_FILENAME
from slop_code.common import PROMPT_FILENAME
from slop_code.common import RUN_INFO_FILENAME
from slop_code.common import SNAPSHOT_DIR_NAME
from slop_code.common import render_prompt
from slop_code.common.llms import TokenUsage
from slop_code.evaluation.config import CheckpointConfig
from slop_code.evaluation.config import ProblemConfig
from slop_code.execution.models import EnvironmentSpec
from slop_code.logging import get_logger

logger = get_logger(__name__)


class InvalidationReason(Enum):
    """Reasons why a checkpoint needs to be re-run."""

    SPEC_CHANGED = "spec_changed"
    HAD_ERROR = "had_error"
    MISSING_SNAPSHOT = "missing_snapshot"
    MISSING_RESULT = "missing_result"
    MISSING_DIR = "missing_directory"
    UNREADABLE_RESULT = "unreadable_result"
    DEPENDS_ON_INVALID = "depends_on_invalid"


@dataclass
class CheckpointStatus:
    """Status of a single checkpoint for resume detection."""

    name: str
    is_valid: bool
    reason: InvalidationReason | None = None


@dataclass
class ResumeInfo:
    """Information needed to resume a run from a checkpoint.

    Attributes:
        resume_from_checkpoint: Name of the checkpoint to resume from
        completed_checkpoints: Names of checkpoints that completed successfully
        last_snapshot_dir: Path to the last successful snapshot directory
        prior_usage: Aggregated usage from completed checkpoints
        checkpoint_statuses: Detailed status for each checkpoint examined
        invalidated_checkpoints: List of checkpoint names that will be re-run
    """

    resume_from_checkpoint: str
    completed_checkpoints: list[str]
    last_snapshot_dir: Path | None
    prior_usage: UsageTracker
    checkpoint_statuses: list[CheckpointStatus] = field(default_factory=list)
    invalidated_checkpoints: list[str] = field(default_factory=list)


def _generate_expected_prompt(
    problem_config: ProblemConfig,
    checkpoint: CheckpointConfig,
    prompt_template: str,
    environment: EnvironmentSpec,
    entry_file: str,
    *,
    is_first_checkpoint: bool,
) -> str:
    """Generate what the prompt SHOULD be for a checkpoint.

    Args:
        checkpoint: Checkpoint configuration
        prompt_template: Jinja2 template string for prompts
        environment: Environment specification
        entry_file: Entry file path
        is_first_checkpoint: Whether this is the first checkpoint

    Returns:
        Rendered prompt string
    """
    return render_prompt(
        spec_text=problem_config.get_checkpoint_spec(checkpoint.name),
        context={"is_continuation": not is_first_checkpoint},
        prompt_template=prompt_template,
        entry_file=environment.format_entry_file(entry_file),
        entry_command=environment.get_command(entry_file, is_agent_run=True),
    )


def _prompts_match(saved_prompt: str, expected_prompt: str) -> bool:
    """Compare prompts with whitespace normalization.

    Args:
        saved_prompt: The prompt that was saved to disk
        expected_prompt: The prompt generated from current config

    Returns:
        True if prompts match, False otherwise
    """
    return saved_prompt.strip() == expected_prompt.strip()


def _check_prompt_mismatch(
    problem_config: ProblemConfig,
    checkpoint_dir: Path,
    checkpoint_name: str,
    checkpoint_names: list[str],
    prompt_template: str,
    environment: EnvironmentSpec,
    entry_file: str,
    checkpoints: list[CheckpointConfig],
) -> bool:
    """Check if saved prompt matches expected prompt for a checkpoint.

    Args:
        checkpoint_dir: Directory containing checkpoint files
        checkpoint_name: Name of the checkpoint
        checkpoint_names: Ordered list of all checkpoint names
        prompt_template: Jinja2 template string
        environment: Environment specification
        entry_file: Entry file path
        checkpoints: List of checkpoint configurations

    Returns:
        True if there's a mismatch (should invalidate), False if prompts match
    """
    prompt_path = checkpoint_dir / PROMPT_FILENAME
    if not prompt_path.exists():
        # No saved prompt - checkpoint incomplete anyway
        return False

    try:
        saved_prompt = prompt_path.read_text()
    except OSError:
        # Can't read prompt - treat as incomplete
        return False

    checkpoint_config = next(
        (c for c in checkpoints if c.name == checkpoint_name), None
    )
    if checkpoint_config is None:
        # Can't find config - shouldn't happen, but don't invalidate
        return False

    is_first = checkpoint_name == checkpoint_names[0]
    expected = _generate_expected_prompt(
        problem_config,
        checkpoint_config,
        prompt_template,
        environment,
        entry_file,
        is_first_checkpoint=is_first,
    )

    if not _prompts_match(saved_prompt, expected):
        logger.info(
            "Prompt mismatch detected",
            checkpoint=checkpoint_name,
        )
        return True

    return False


def _detect_resume_from_artifacts(
    output_path: Path,
    checkpoint_names: list[str],
    problem_config: ProblemConfig | None = None,
    prompt_template: str | None = None,
    environment: EnvironmentSpec | None = None,
    entry_file: str | None = None,
    checkpoints: list[CheckpointConfig] | None = None,
) -> ResumeInfo | None:
    """Fallback resume detection when run_info.yaml is missing.

    Checks checkpoint directories for snapshots and inference results
    to determine resume point. Optionally validates prompts if parameters
    are provided.

    Args:
        output_path: Path to the problem's output directory
        checkpoint_names: Ordered list of checkpoint names from problem config
        prompt_template: Optional Jinja2 template for prompt validation
        environment: Optional environment spec for prompt validation
        entry_file: Optional entry file for prompt validation
        checkpoints: Optional checkpoint configs for prompt validation

    Returns:
        ResumeInfo if resumable state found, None if should start fresh
    """
    completed: list[str] = []
    statuses: list[CheckpointStatus] = []
    can_validate_prompts = all(
        [problem_config, prompt_template, environment, entry_file, checkpoints]
    )
    first_invalid_reason: InvalidationReason | None = None

    for name in checkpoint_names:
        # If we've already found an invalid checkpoint, mark rest as dependent
        if first_invalid_reason is not None:
            statuses.append(
                CheckpointStatus(
                    name=name,
                    is_valid=False,
                    reason=InvalidationReason.DEPENDS_ON_INVALID,
                )
            )
            continue

        checkpoint_dir = output_path / name
        snapshot_dir = checkpoint_dir / SNAPSHOT_DIR_NAME

        # Force re-run if checkpoint directory is missing
        if not checkpoint_dir.exists():
            first_invalid_reason = InvalidationReason.MISSING_DIR
            statuses.append(
                CheckpointStatus(
                    name=name,
                    is_valid=False,
                    reason=InvalidationReason.MISSING_DIR,
                )
            )
            continue

        if not snapshot_dir.exists():
            first_invalid_reason = InvalidationReason.MISSING_SNAPSHOT
            statuses.append(
                CheckpointStatus(
                    name=name,
                    is_valid=False,
                    reason=InvalidationReason.MISSING_SNAPSHOT,
                )
            )
            continue

        # Snapshot exists - check inference result for errors
        result_path = checkpoint_dir / INFERENCE_RESULT_FILENAME
        if not result_path.exists():
            first_invalid_reason = InvalidationReason.MISSING_RESULT
            statuses.append(
                CheckpointStatus(
                    name=name,
                    is_valid=False,
                    reason=InvalidationReason.MISSING_RESULT,
                )
            )
            continue

        try:
            with result_path.open() as f:
                result = json.load(f)
        except (OSError, json.JSONDecodeError):
            first_invalid_reason = InvalidationReason.UNREADABLE_RESULT
            statuses.append(
                CheckpointStatus(
                    name=name,
                    is_valid=False,
                    reason=InvalidationReason.UNREADABLE_RESULT,
                )
            )
            continue

        if result.get("had_error", False):
            first_invalid_reason = InvalidationReason.HAD_ERROR
            statuses.append(
                CheckpointStatus(
                    name=name,
                    is_valid=False,
                    reason=InvalidationReason.HAD_ERROR,
                )
            )
            continue

        # Check prompt matches if validation is enabled
        if can_validate_prompts and _check_prompt_mismatch(
            problem_config,
            checkpoint_dir,
            name,
            checkpoint_names,
            prompt_template,  # type: ignore[arg-type]
            environment,  # type: ignore[arg-type]
            entry_file,  # type: ignore[arg-type]
            checkpoints,  # type: ignore[arg-type]
        ):
            first_invalid_reason = InvalidationReason.SPEC_CHANGED
            statuses.append(
                CheckpointStatus(
                    name=name,
                    is_valid=False,
                    reason=InvalidationReason.SPEC_CHANGED,
                )
            )
            continue

        # Checkpoint completed successfully
        completed.append(name)
        statuses.append(CheckpointStatus(name=name, is_valid=True))

    # Find checkpoint to resume from and build invalidated list
    completed_set = set(completed)
    resume_from = None
    invalidated: list[str] = []
    for name in checkpoint_names:
        if name not in completed_set:
            if resume_from is None:
                resume_from = name
            invalidated.append(name)

    if not completed and not invalidated:
        # No checkpoint directories exist at all, start fresh
        return None

    if not resume_from:
        # All checkpoints completed - return ResumeInfo with empty resume_from
        prior_usage = _aggregate_prior_usage(output_path, completed)
        last_snapshot_dir = output_path / completed[-1] / SNAPSHOT_DIR_NAME
        return ResumeInfo(
            resume_from_checkpoint="",  # Empty string = nothing to resume
            completed_checkpoints=completed,
            last_snapshot_dir=last_snapshot_dir,
            prior_usage=prior_usage,
            checkpoint_statuses=statuses,
            invalidated_checkpoints=[],
        )

    # Aggregate usage and build ResumeInfo
    prior_usage = _aggregate_prior_usage(output_path, completed)
    last_snapshot_dir = (
        output_path / completed[-1] / SNAPSHOT_DIR_NAME if completed else None
    )

    logger.info(
        "Detected resume point from artifacts (no run_info.yaml)",
        resume_from=resume_from,
        completed_count=len(completed),
        invalidated_count=len(invalidated),
    )

    return ResumeInfo(
        resume_from_checkpoint=resume_from,
        completed_checkpoints=completed,
        last_snapshot_dir=last_snapshot_dir,
        prior_usage=prior_usage,
        checkpoint_statuses=statuses,
        invalidated_checkpoints=invalidated,
    )


def detect_resume_point(
    output_path: Path,
    checkpoint_names: list[str],
    problem_config: ProblemConfig | None = None,
    prompt_template: str | None = None,
    environment: EnvironmentSpec | None = None,
    entry_file: str | None = None,
    checkpoints: list[CheckpointConfig] | None = None,
) -> ResumeInfo | None:
    """Detect where to resume from based on existing output.

    Analyzes the output directory to find completed checkpoints and determine
    where to resume execution. Optionally validates prompts if parameters
    are provided.

    Args:
        output_path: Path to the problem's output directory
        checkpoint_names: Ordered list of checkpoint names from problem config
        prompt_template: Optional Jinja2 template for prompt validation
        environment: Optional environment spec for prompt validation
        entry_file: Optional entry file for prompt validation
        checkpoints: Optional checkpoint configs for prompt validation

    Returns:
        ResumeInfo if resumable state found, None if should start fresh
    """
    run_info_path = output_path / RUN_INFO_FILENAME
    if not run_info_path.exists():
        logger.debug(
            "No run_info.yaml found, checking for artifacts",
            output_path=str(output_path),
        )
        return _detect_resume_from_artifacts(
            output_path,
            checkpoint_names,
            problem_config=problem_config,
            prompt_template=prompt_template,
            environment=environment,
            entry_file=entry_file,
            checkpoints=checkpoints,
        )

    try:
        with run_info_path.open() as f:
            run_info = yaml.safe_load(f)
    except (OSError, yaml.YAMLError) as e:
        logger.warning(
            "Failed to read run_info.yaml, starting fresh",
            error=str(e),
        )
        return None

    if not isinstance(run_info, dict):
        logger.warning("Invalid run_info.yaml format, starting fresh")
        return None

    summary = run_info.get("summary", {})
    checkpoint_states = summary.get("checkpoints", {})
    can_validate_prompts = all(
        [problem_config, prompt_template, environment, entry_file, checkpoints]
    )

    # Find completed checkpoints and first incomplete one
    completed: list[str] = []
    statuses: list[CheckpointStatus] = []
    first_invalid_reason: InvalidationReason | None = None

    for name in checkpoint_names:
        # If we've already found an invalid checkpoint, mark rest as dependent
        if first_invalid_reason is not None:
            statuses.append(
                CheckpointStatus(
                    name=name,
                    is_valid=False,
                    reason=InvalidationReason.DEPENDS_ON_INVALID,
                )
            )
            continue

        state = checkpoint_states.get(name)
        checkpoint_dir = output_path / name
        snapshot_dir = checkpoint_dir / SNAPSHOT_DIR_NAME

        # Force re-run if checkpoint directory is missing
        if not checkpoint_dir.exists():
            logger.debug(
                "Checkpoint directory missing, forcing re-run",
                checkpoint=name,
            )
            first_invalid_reason = InvalidationReason.MISSING_DIR
            statuses.append(
                CheckpointStatus(
                    name=name,
                    is_valid=False,
                    reason=InvalidationReason.MISSING_DIR,
                )
            )
            continue

        if state == CheckpointState.RAN and snapshot_dir.exists():
            # Check prompt matches if validation is enabled
            if can_validate_prompts and _check_prompt_mismatch(
                problem_config,
                checkpoint_dir,
                name,
                checkpoint_names,
                prompt_template,  # type: ignore[arg-type]
                environment,  # type: ignore[arg-type]
                entry_file,  # type: ignore[arg-type]
                checkpoints,  # type: ignore[arg-type]
            ):
                # Prompt mismatch - invalidate this and all subsequent
                logger.debug(
                    "Checkpoint has prompt mismatch",
                    checkpoint=name,
                )
                first_invalid_reason = InvalidationReason.SPEC_CHANGED
                statuses.append(
                    CheckpointStatus(
                        name=name,
                        is_valid=False,
                        reason=InvalidationReason.SPEC_CHANGED,
                    )
                )
                continue

            logger.debug(
                "Checkpoint completed",
                checkpoint=name,
            )
            completed.append(name)
            statuses.append(CheckpointStatus(name=name, is_valid=True))
        else:
            logger.debug(
                "Checkpoint not completed",
                checkpoint=name,
                state=state,
                snapshot_exists=snapshot_dir.exists(),
            )
            # Determine the specific reason
            if not snapshot_dir.exists():
                reason = InvalidationReason.MISSING_SNAPSHOT
            elif state == CheckpointState.ERROR:
                reason = InvalidationReason.HAD_ERROR
            else:
                reason = InvalidationReason.MISSING_RESULT
            first_invalid_reason = reason
            statuses.append(
                CheckpointStatus(
                    name=name,
                    is_valid=False,
                    reason=reason,
                )
            )

    # Build invalidated list from statuses
    invalidated = [s.name for s in statuses if not s.is_valid]

    if not invalidated:
        # All checkpoints completed - return ResumeInfo with empty resume_from
        logger.debug(
            "All checkpoints completed, no resume needed",
            completed_count=len(completed),
        )
        prior_usage = _aggregate_prior_usage(output_path, completed)
        last_snapshot_dir = output_path / completed[-1] / SNAPSHOT_DIR_NAME
        return ResumeInfo(
            resume_from_checkpoint="",  # Empty string = nothing to resume
            completed_checkpoints=completed,
            last_snapshot_dir=last_snapshot_dir,
            prior_usage=prior_usage,
            checkpoint_statuses=statuses,
            invalidated_checkpoints=[],
        )

    if not completed and not invalidated:
        # No checkpoint directories exist at all, start fresh
        logger.debug("No checkpoint directories found, starting fresh")
        return None

    resume_from = invalidated[0] if invalidated else ""

    # Calculate prior usage from completed checkpoints
    prior_usage = _aggregate_prior_usage(output_path, completed)

    # Get the snapshot from the last completed checkpoint (if any)
    last_snapshot_dir = (
        output_path / completed[-1] / SNAPSHOT_DIR_NAME if completed else None
    )

    logger.info(
        "Detected resume point",
        resume_from=resume_from,
        completed_count=len(completed),
        invalidated_count=len(invalidated),
        last_completed=completed[-1] if completed else None,
        prior_cost=prior_usage.cost,
        prior_steps=prior_usage.steps,
    )

    return ResumeInfo(
        resume_from_checkpoint=resume_from,
        completed_checkpoints=completed,
        last_snapshot_dir=last_snapshot_dir,
        prior_usage=prior_usage,
        checkpoint_statuses=statuses,
        invalidated_checkpoints=invalidated,
    )


def _aggregate_prior_usage(
    output_path: Path,
    completed: list[str],
) -> UsageTracker:
    """Aggregate usage from completed checkpoint inference results.

    Args:
        output_path: Path to the problem's output directory
        completed: List of completed checkpoint names

    Returns:
        UsageTracker with aggregated usage from all completed checkpoints
    """
    total_cost = 0.0
    total_steps = 0
    total_net_tokens = TokenUsage()

    for checkpoint_name in completed:
        result_path = output_path / checkpoint_name / INFERENCE_RESULT_FILENAME
        if not result_path.exists():
            logger.debug(
                "No inference_result.json for checkpoint",
                checkpoint=checkpoint_name,
            )
            continue

        try:
            with result_path.open() as f:
                result = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            logger.warning(
                "Failed to read inference_result.json",
                checkpoint=checkpoint_name,
                error=str(e),
            )
            continue

        usage = result.get("usage", {})
        total_cost += usage.get("cost", 0.0)
        total_steps += usage.get("steps", 0)

        net_tokens_data = usage.get("net_tokens", {})
        if net_tokens_data:
            total_net_tokens += TokenUsage(**net_tokens_data)

    return UsageTracker(
        cost=total_cost,
        steps=total_steps,
        net_tokens=total_net_tokens,
    )


def format_resume_summary(
    info: ResumeInfo, problem_name: str | None = None
) -> str:
    """Format a human-readable summary of resume detection results.

    Args:
        info: ResumeInfo from detect_resume_point
        problem_name: Optional problem name for the header

    Returns:
        Formatted string summarizing the resume state
    """
    reason_descriptions = {
        InvalidationReason.SPEC_CHANGED: "specification changed",
        InvalidationReason.HAD_ERROR: "previous run had error",
        InvalidationReason.MISSING_SNAPSHOT: "missing snapshot",
        InvalidationReason.MISSING_RESULT: "missing results",
        InvalidationReason.MISSING_DIR: "directory missing",
        InvalidationReason.UNREADABLE_RESULT: "unreadable results",
        InvalidationReason.DEPENDS_ON_INVALID: "depends on invalid checkpoint",
    }

    lines = []
    if problem_name:
        lines.append(f"{problem_name}:")
    lines.append(f"  Resume from: {info.resume_from_checkpoint}")
    lines.append(f"  Completed: {', '.join(info.completed_checkpoints)}")

    if info.invalidated_checkpoints:
        lines.append("  Will re-run:")
        for status in info.checkpoint_statuses:
            if not status.is_valid and status.reason:
                desc = reason_descriptions.get(status.reason, "unknown reason")
                lines.append(f"    - {status.name} ({desc})")

    return "\n".join(lines)
