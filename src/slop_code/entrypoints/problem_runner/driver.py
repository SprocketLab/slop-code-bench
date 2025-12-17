"""Main orchestration for running problems.

This module provides the entry points for running multiple problems in
parallel with progress tracking.
"""

from __future__ import annotations

import concurrent.futures
import multiprocessing as mp
import queue
import traceback
from collections.abc import Sequence
from datetime import datetime

from rich.console import Console

from slop_code import evaluation
from slop_code.agent_runner import AgentStateEnum
from slop_code.entrypoints.live_progress import LiveProgressDisplay
from slop_code.entrypoints.live_progress import maybe_live_progress
from slop_code.entrypoints.problem_runner.models import RunTaskConfig
from slop_code.entrypoints.problem_runner.models import TaskResult
from slop_code.entrypoints.problem_runner.one_shot import apply_one_shot_mode
from slop_code.entrypoints.problem_runner.renderer import (
    ProblemProgressRenderer,
)
from slop_code.entrypoints.problem_runner.state import ProblemStateTracker
from slop_code.entrypoints.problem_runner.worker import run_agent_on_problem
from slop_code.logging import get_logger
from slop_code.logging import setup_problem_logging

logger = get_logger(__name__)


def _run_problem_worker(
    problem_name: str,
    config: RunTaskConfig,
    progress_queue: queue.Queue,
) -> TaskResult:
    """Worker function to run a single problem with isolated logging.

    This function is designed to be run in a separate process. It sets up
    isolated logging, orchestrates the agent runner pipeline, and executes
    the problem.

    Args:
        problem_name: Name of the problem
        config: Shared execution configuration
        progress_queue: Queue for sending progress updates

    Returns:
        TaskResult with problem execution outcome
    """
    prob_save_dir = config.run_dir / problem_name
    prob_save_dir.mkdir(parents=True, exist_ok=True)

    if config.live_progress or not config.debug:
        setup_problem_logging(
            prob_save_dir, problem_name, log_file_name="infer.log"
        )

    problem_logger = get_logger()
    problem_path = config.problem_base_path / problem_name
    problem_logger.info(
        "Running agent for problem",
        problem=problem_name,
        problem_path=str(problem_path),
    )

    problem_config = evaluation.ProblemConfig.from_yaml(problem_path)
    try:
        results = run_agent_on_problem(
            problem_config=problem_config,
            problem_name=problem_name,
            config=config,
            progress_queue=progress_queue,
            output_path=prob_save_dir,
        )

        # Check the actual run outcome from results summary
        summary = results.get("summary", {})
        passed_policy = summary.get("passed_policy", False)
        state = summary.get("state", "UNKNOWN")

        if state.lower() == "completed":
            logger.info("Successfully completed problem", problem=problem_name)
            return TaskResult(problem_name=problem_name, success=True)

        # Problem failed tests or had error state
        error_msg = summary.get("error_message")
        if not error_msg:
            error_msg = f"state={state}, passed_policy={passed_policy}"
        logger.warning(
            "Problem did not complete successfully",
            problem=problem_name,
            state=state,
            passed_policy=passed_policy,
            error_message=error_msg,
        )
        return TaskResult(
            problem_name=problem_name,
            success=False,
            error_message=error_msg,
            error_type=summary.get("error_type") or state,
            error_traceback=summary.get("error_traceback"),
        )
    except Exception as e:
        error_type = type(e).__name__
        error_msg = str(e)
        traceback_text = traceback.format_exc()

        logger.error(
            "Error running problem",
            problem=problem_name,
            error_type=error_type,
            error_message=error_msg,
            traceback=traceback_text,
            exc_info=True,
        )
        return TaskResult(
            problem_name=problem_name,
            success=False,
            error_message=error_msg,
            error_type=error_type,
            error_traceback=traceback_text,
        )


def _run_problems(
    problem_names: Sequence[str],
    config: RunTaskConfig,
    num_workers: int,
    progress_queue: queue.Queue,
    progress_display: LiveProgressDisplay | None,
    problem_states: ProblemStateTracker,
) -> list[TaskResult]:
    """Run problems in parallel with progress monitoring.

    Args:
        problem_names: List of problem names to run
        config: Shared execution configuration
        num_workers: Number of parallel workers
        progress_queue: Queue for progress updates
        progress_display: Optional live display for progress
        problem_states: State tracker for all problems

    Returns:
        List of TaskResult objects
    """
    logger.info(
        "Starting run problems queue monitor", problem_names=problem_names
    )
    with concurrent.futures.ProcessPoolExecutor(
        max_workers=num_workers
    ) as executor:
        futures = [
            executor.submit(
                _run_problem_worker, problem_name, config, progress_queue
            )
            for problem_name in problem_names
        ]
        while not all(future.done() for future in futures):
            try:
                problem_name, agent_usage, metrics_tracker = progress_queue.get(
                    timeout=0.1
                )
            except queue.Empty:
                if progress_display is not None:
                    progress_display.update()
                continue
            problem_states.handle_update(
                problem_name, agent_usage, metrics_tracker
            )
            net_cost = metrics_tracker.usage.cost + (agent_usage.cost or 0.0)

            logger.info(
                f"'{problem_name}': progress update",
                state=metrics_tracker.state.value,
                checkpoint=metrics_tracker.current_checkpoint,
                elapsed=(
                    datetime.now() - metrics_tracker.started
                ).total_seconds(),
                cost=float(f"{net_cost:.5f}"),
            )

            if problem_states[problem_name].state == AgentStateEnum.ERROR:
                logger.error(
                    f"{problem_name} state",
                    **problem_states[problem_name].get_simple_state(),
                )
            else:
                logger.debug(
                    f"{problem_name} state",
                    **problem_states[problem_name].get_simple_state(),
                )

            logger.debug(
                f"{sum(not future.done() for future in futures)} problem(s) "
                "alive"
            )
            if progress_display is not None:
                progress_display.update()

        return [future.result() for future in futures]


def run_problems(
    problem_names: Sequence[str],
    config: RunTaskConfig,
    num_workers: int = 1,
    console: Console = Console(),
) -> list[TaskResult]:
    """Run problems either sequentially or in parallel.

    This is the main entry point for running multiple problems. It sets up
    the multiprocessing infrastructure, progress tracking, and live display.

    Args:
        problem_names: List of problem names to run
        config: Shared execution configuration for all problems
        num_workers: Number of parallel workers (1 for sequential)
        console: Rich console for output

    Returns:
        List of TaskResult objects
    """
    manager = mp.Manager()
    progress_queue = manager.Queue()

    checkpoint_map: dict[str, Sequence[str]] = {}
    for problem_name in problem_names:
        problem_path = config.problem_base_path / problem_name
        try:
            problem_config = evaluation.ProblemConfig.from_yaml(problem_path)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Unable to load problem config for progress tracking",
                problem=problem_name,
                path=str(problem_path),
                error=str(exc),
            )
            continue
        problem_config = apply_one_shot_mode(
            problem_config=problem_config, one_shot=config.one_shot
        )
        checkpoint_names = [
            name for name, _ in problem_config.iterate_checkpoint_items()
        ]
        checkpoint_map[problem_name] = checkpoint_names

    states = ProblemStateTracker(problem_names, checkpoint_map)
    renderer = ProblemProgressRenderer(states)

    with maybe_live_progress(
        enabled=config.live_progress,
        renderable_factory=renderer.render,
        console=console,
        placeholder=renderer.placeholder,
    ) as progress_display:
        return _run_problems(
            problem_names,
            config,
            num_workers,
            progress_queue,
            progress_display,
            states,
        )
