"""Agent execution wrapper for problem runner.

This module provides the function that executes an agent on a single problem.
"""

from __future__ import annotations

import queue
import shutil
from pathlib import Path
from typing import Any

from slop_code import evaluation
from slop_code.agent_runner import AgentRunSpec
from slop_code.agent_runner import runner
from slop_code.agent_runner.agent import Agent
from slop_code.agent_runner.resume import ResumeInfo
from slop_code.agent_runner.resume import detect_resume_point
from slop_code.agent_runner.resume import format_resume_summary
from slop_code.entrypoints.problem_runner.models import RunTaskConfig
from slop_code.entrypoints.problem_runner.one_shot import apply_one_shot_mode
from slop_code.logging import get_logger

logger = get_logger(__name__)


def _delete_invalidated_checkpoints(
    output_path: Path,
    resume_info: ResumeInfo,
) -> None:
    """Delete checkpoint directories that will be re-run.

    When resuming with invalidated checkpoints (e.g., due to spec changes),
    deletes the old checkpoint directories to ensure a clean re-run.

    Args:
        output_path: Base output directory for the problem
        resume_info: Resume information with invalidated checkpoints
    """
    if not resume_info.invalidated_checkpoints:
        return

    logger.info(
        "Deleting invalidated checkpoint directories",
        checkpoints=resume_info.invalidated_checkpoints,
    )

    for checkpoint_name in resume_info.invalidated_checkpoints:
        checkpoint_dir = output_path / checkpoint_name
        if checkpoint_dir.exists():
            shutil.rmtree(checkpoint_dir)
            logger.debug(
                "Deleted checkpoint directory",
                checkpoint=checkpoint_name,
                path=str(checkpoint_dir),
            )


def run_agent_on_problem(
    problem_config: evaluation.ProblemConfig,
    problem_name: str,
    config: RunTaskConfig,
    progress_queue: queue.Queue,
    output_path: Path,
) -> dict[str, Any]:
    """Execute an agent on a problem with progress reporting.

    Creates an AgentRunSpec from the config and runs the agent with
    progress updates sent to the queue.

    Args:
        problem_config: Problem configuration
        problem_name: Name of the problem
        config: Shared execution configuration
        progress_queue: Queue for progress updates
        output_path: Directory for output files

    Returns:
        Dictionary containing the run results including summary with state,
        passed_policy, and any error information.
    """
    problem_config = apply_one_shot_mode(
        problem_config=problem_config, one_shot=config.one_shot
    )

    # Detect resume point if resume mode is enabled
    resume_info: ResumeInfo | None = None
    if config.resume:
        checkpoint_items = list(problem_config.iterate_checkpoint_items())
        checkpoint_names = [name for name, _ in checkpoint_items]
        checkpoints = [cp for _, cp in checkpoint_items]
        resume_info = detect_resume_point(
            output_path,
            checkpoint_names,
            problem_config=problem_config,
            prompt_template=config.prompt_template,
            environment=config.env_spec,
            entry_file=problem_config.entry_file,
            checkpoints=checkpoints,
        )
        if resume_info:
            # Check if all checkpoints are already completed
            if not resume_info.resume_from_checkpoint:
                logger.info(
                    "All checkpoints completed, skipping",
                    problem=problem_name,
                    completed=len(resume_info.completed_checkpoints),
                )
                return {
                    "summary": {
                        "state": "skipped",
                        "passed_policy": True,
                        "usage": resume_info.prior_usage.model_dump()
                        if hasattr(resume_info.prior_usage, "model_dump")
                        else {},
                    }
                }

            # Log detailed resume summary
            summary = format_resume_summary(resume_info, problem_name)
            logger.info(
                "Resuming from checkpoint",
                problem=problem_name,
                checkpoint=resume_info.resume_from_checkpoint,
                completed=len(resume_info.completed_checkpoints),
                invalidated=resume_info.invalidated_checkpoints,
                summary=summary,
            )

            # Delete invalidated checkpoint directories
            _delete_invalidated_checkpoints(output_path, resume_info)

    run_spec = AgentRunSpec(
        seed=config.seed,
        template=config.prompt_template,
        problem=problem_config,
        environment=config.env_spec,
        pass_policy=config.pass_policy,
        skip_evaluation=config.disable_evaluation,
        verbose=config.verbosity > 0,
        image=config.image,
    )

    return runner.run_agent(
        run_spec=run_spec,
        agent=Agent.from_config(
            config.agent_config,
            model=config.model_def,
            credential=config.credential,
            problem_name=problem_name,
            verbose=run_spec.verbose,
            image=config.image,
            thinking_preset=config.thinking_preset,
            thinking_max_tokens=config.thinking_max_tokens,
        ),
        output_path=output_path,
        progress_queue=progress_queue,
        resume_info=resume_info,
    )
