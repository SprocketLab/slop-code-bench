"""Resume functionality for checkpoint-based execution.

This module provides utilities for detecting and resuming from the last
successful checkpoint when a run is interrupted or fails mid-execution.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
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
from slop_code.execution.models import EnvironmentSpec
from slop_code.logging import get_logger

logger = get_logger(__name__)


@dataclass
class ResumeInfo:
    """Information needed to resume a run from a checkpoint.

    Attributes:
        resume_from_checkpoint: Name of the checkpoint to resume from
        completed_checkpoints: Names of checkpoints that completed successfully
        last_snapshot_dir: Path to the last successful snapshot directory
        prior_usage: Aggregated usage from completed checkpoints
    """

    resume_from_checkpoint: str
    completed_checkpoints: list[str]
    last_snapshot_dir: Path | None
    prior_usage: UsageTracker


def _generate_expected_prompt(
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
        spec_text=checkpoint.get_spec_text(),
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
    can_validate_prompts = all([
        prompt_template, environment, entry_file, checkpoints
    ])

    for name in checkpoint_names:
        checkpoint_dir = output_path / name
        snapshot_dir = checkpoint_dir / SNAPSHOT_DIR_NAME

        if not snapshot_dir.exists():
            # No snapshot - this is where we resume from
            break

        # Snapshot exists - check inference result for errors
        result_path = checkpoint_dir / INFERENCE_RESULT_FILENAME
        if not result_path.exists():
            # Snapshot but no inference result - resume from here
            break

        try:
            with result_path.open() as f:
                result = json.load(f)
        except (OSError, json.JSONDecodeError):
            # Can't read result - resume from here
            break

        if result.get("had_error", False):
            # Error in this checkpoint - resume from here (re-run it)
            break

        # Check prompt matches if validation is enabled
        if can_validate_prompts and _check_prompt_mismatch(
            checkpoint_dir,
            name,
            checkpoint_names,
            prompt_template,  # type: ignore[arg-type]
            environment,  # type: ignore[arg-type]
            entry_file,  # type: ignore[arg-type]
            checkpoints,  # type: ignore[arg-type]
        ):
            # Prompt mismatch - invalidate this and all subsequent checkpoints
            break

        # Checkpoint completed successfully
        completed.append(name)

    if not completed:
        # No completed checkpoints, start fresh
        return None

    # Find checkpoint to resume from
    completed_set = set(completed)
    resume_from = None
    for name in checkpoint_names:
        if name not in completed_set:
            resume_from = name
            break

    if not resume_from:
        # All checkpoints completed
        return None

    # Aggregate usage and build ResumeInfo
    prior_usage = _aggregate_prior_usage(output_path, completed)
    last_completed = completed[-1]
    last_snapshot_dir = output_path / last_completed / SNAPSHOT_DIR_NAME

    logger.info(
        "Detected resume point from artifacts (no run_info.yaml)",
        resume_from=resume_from,
        completed_count=len(completed),
    )

    return ResumeInfo(
        resume_from_checkpoint=resume_from,
        completed_checkpoints=completed,
        last_snapshot_dir=last_snapshot_dir,
        prior_usage=prior_usage,
    )


def detect_resume_point(
    output_path: Path,
    checkpoint_names: list[str],
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
            prompt_template,
            environment,
            entry_file,
            checkpoints,
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
    can_validate_prompts = all([
        prompt_template, environment, entry_file, checkpoints
    ])

    # Find completed checkpoints and first incomplete one
    completed: list[str] = []
    resume_from: str | None = None

    for name in checkpoint_names:
        state = checkpoint_states.get(name)
        checkpoint_dir = output_path / name
        snapshot_dir = checkpoint_dir / SNAPSHOT_DIR_NAME

        if state == CheckpointState.RAN and snapshot_dir.exists():
            # Check prompt matches if validation is enabled
            if can_validate_prompts and _check_prompt_mismatch(
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
                resume_from = name
                break

            logger.debug(
                "Checkpoint completed",
                checkpoint=name,
            )
            completed.append(name)
        else:
            logger.debug(
                "Checkpoint not completed",
                checkpoint=name,
            )
            resume_from = name
            break

    if not resume_from:
        # All checkpoints completed
        logger.debug(
            "All checkpoints completed, no resume needed",
            completed_count=len(completed),
        )
        return None

    if not completed:
        # No completed checkpoints, start fresh
        logger.debug("No completed checkpoints found, starting fresh")
        return None

    # Calculate prior usage from completed checkpoints
    prior_usage = _aggregate_prior_usage(output_path, completed)

    # Get the snapshot from the last completed checkpoint
    last_completed = completed[-1]
    last_snapshot_dir = output_path / last_completed / SNAPSHOT_DIR_NAME

    logger.info(
        "Detected resume point",
        resume_from=resume_from,
        completed_count=len(completed),
        last_completed=last_completed,
        prior_cost=prior_usage.cost,
        prior_steps=prior_usage.steps,
    )

    return ResumeInfo(
        resume_from_checkpoint=resume_from,
        completed_checkpoints=completed,
        last_snapshot_dir=last_snapshot_dir,
        prior_usage=prior_usage,
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
