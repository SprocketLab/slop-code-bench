from __future__ import annotations

import functools
import json
import traceback
from collections import defaultdict
from collections.abc import Generator
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures import as_completed
from dataclasses import dataclass
from pathlib import Path

import structlog
from pydantic import BaseModel
from rich.console import Console
from rich.live import Live
from rich.progress import BarColumn
from rich.progress import Progress
from rich.progress import TextColumn
from rich.progress import TimeElapsedColumn
from rich.progress import TimeRemainingColumn

from slop_code import logging as slop_logging
from slop_code.common import SNAPSHOT_DIR_NAME
from slop_code.entrypoints.evaluation.utils import gather_checkpoint_directories
from slop_code.entrypoints.evaluation.utils import maybe_update_problem_report
from slop_code.evaluation import CheckpointConfig
from slop_code.evaluation import CorrectnessResults
from slop_code.evaluation import ProblemConfig
from slop_code.evaluation.pytest_runner import run_checkpoint_pytest
from slop_code.execution import EnvironmentSpec
from slop_code.logging import get_logger
from slop_code.metrics import RUBRIC_GRADES_SAVENAME
from slop_code.metrics import RubricProvider
from slop_code.metrics import SnapshotQualityReport
from slop_code.metrics import llm_judge_snapshot
from slop_code.metrics import measure_snapshot_quality
from slop_code.metrics.quality_io import save_quality_metrics

logger = get_logger(__name__)


class CheckpointEvaluationResult(BaseModel):
    problem_name: str
    checkpoint_name: str
    report: CorrectnessResults
    quality: SnapshotQualityReport
    rubric_grades: list[dict] | None = None


class EvaluationResult(BaseModel):
    """Result of evaluating a single checkpoint, capturing success or failure."""

    problem_name: str
    checkpoint_name: str
    success: bool
    result: CheckpointEvaluationResult | None = None
    error_type: str | None = None
    error_message: str | None = None
    error_traceback: str | None = None


class BatchEvaluationSummary(BaseModel):
    """Summary of batch evaluation run with error tracking."""

    total_checkpoints: int
    successful: int
    failed: int
    errors: list[EvaluationResult]

    def format_summary(self) -> str:
        """Format summary for display at end of run."""
        lines = [
            f"Evaluation completed: {self.successful}/{self.total_checkpoints} "
            f"checkpoints succeeded"
        ]
        if self.failed > 0:
            lines.append(f"\n{self.failed} checkpoint(s) failed:")
            for err in self.errors:
                identifier = f"{err.problem_name}/{err.checkpoint_name}"
                msg = err.error_message or "Unknown error"
                if err.error_type:
                    msg = f"{err.error_type}: {msg}"
                lines.append(f"  - {identifier}: {msg}")
        return "\n".join(lines)


def evaluate_checkpoint(
    snapshot: Path,
    save_dir: Path,
    checkpoint: CheckpointConfig,
    problem: ProblemConfig,
    environment: EnvironmentSpec,
    rubric_path: Path | None = None,
    rubric_model: str | None = None,
    rubric_temperature: float = 0.0,
    rubric_provider: RubricProvider = RubricProvider.OPENROUTER,
) -> CheckpointEvaluationResult:
    logger.debug(
        "Evaluating checkpoint",
        snapshot=str(snapshot),
        checkpoint=checkpoint.name,
        problem=problem.name,
    )

    result = run_checkpoint_pytest(
        submission_path=snapshot,
        problem=problem,
        checkpoint=checkpoint,
        env_spec=environment,
    )
    logger.debug(
        "Saving checkpoint report",
        save_dir=save_dir,
    )
    result.save(save_dir)

    entry_file = environment.format_entry_file(problem.entry_file)
    logger.debug("Calculating overall quality metrics", entry_file=entry_file)
    quality_metrics, file_metrics_list = measure_snapshot_quality(
        entry_file, snapshot
    )
    logger.debug(
        "Calculated quality metrics",
        entry_file=entry_file,
        file_count=quality_metrics.file_count,
    )
    save_quality_metrics(save_dir, quality_metrics, file_metrics_list)

    # Run rubric grading if enabled
    rubric_grades = None
    if rubric_path and rubric_model:
        logger.debug(
            "Running rubric grading",
            rubric_path=str(rubric_path),
            rubric_model=rubric_model,
            rubric_provider=rubric_provider.value,
        )
        grades, raw = llm_judge_snapshot(
            problem=problem,
            checkpoint_name=checkpoint.name,
            snapshot_dir=snapshot,
            rubric_path=rubric_path,
            environment=environment,
            model=rubric_model,
            temperature=rubric_temperature,
            provider=rubric_provider,
        )
        rubric_grades = grades
        with (save_dir / RUBRIC_GRADES_SAVENAME).open("w") as f:
            json.dump({"grades": grades, "raw": raw}, f, indent=2)
        logger.debug(
            "Rubric grading complete",
            grade_count=len(grades),
        )

    return CheckpointEvaluationResult(
        problem_name=problem.name,
        checkpoint_name=checkpoint.name,
        report=result,
        quality=SnapshotQualityReport.from_snapshot_metrics(quality_metrics),
        rubric_grades=rubric_grades,
    )


def _evaluate_checkpoint_worker(
    snapshot: Path,
    save_dir: Path,
    checkpoint: CheckpointConfig,
    problem: ProblemConfig,
    environment: EnvironmentSpec,
    rubric_path: Path | None = None,
    rubric_model: str | None = None,
    rubric_temperature: float = 0.0,
    rubric_provider: RubricProvider = RubricProvider.OPENROUTER,
) -> EvaluationResult:
    """Wrapper for evaluate_checkpoint that sets up logging in worker process.

    This function is meant to be called in ProcessPoolExecutor workers.
    It configures isolated logging for the worker, then calls the actual
    evaluation function. All logs will include problem_name and checkpoint_name.

    Args:
        Same as evaluate_checkpoint

    Returns:
        EvaluationResult capturing success or failure with full context
    """
    # Set up isolated logging for this worker
    # Disable multiproc info since we use context binding for identifiers
    log = slop_logging.setup_problem_logging(
        log_dir=save_dir,  # Go up to run directory
        problem_name="evaluation",
        add_multiproc_info=False,  # Use context binding instead
    )

    # Bind problem and checkpoint names to structlog context
    # This adds these fields to ALL log messages in this worker
    structlog.contextvars.bind_contextvars(
        problem_name=problem.name,
        checkpoint_name=checkpoint.name,
    )
    # Now call the actual evaluation function
    try:
        result = evaluate_checkpoint(
            snapshot=snapshot,
            save_dir=save_dir,
            checkpoint=checkpoint,
            problem=problem,
            environment=environment,
            rubric_path=rubric_path,
            rubric_model=rubric_model,
            rubric_temperature=rubric_temperature,
            rubric_provider=rubric_provider,
        )
        return EvaluationResult(
            problem_name=problem.name,
            checkpoint_name=checkpoint.name,
            success=True,
            result=result,
        )
    except Exception as e:
        tb_str = traceback.format_exc()
        log.error(
            "Error evaluating checkpoint",
            error=str(e),
            error_type=type(e).__name__,
            exc_info=True,
        )

        # Still try to calculate quality metrics even on evaluation failure
        # Quality metrics measure code quality, not test results
        try:
            entry_file = environment.format_entry_file(problem.entry_file)
            quality_metrics, file_metrics_list = measure_snapshot_quality(
                entry_file, snapshot
            )
            save_quality_metrics(save_dir, quality_metrics, file_metrics_list)
            log.debug("Quality metrics calculated despite evaluation failure")
        except Exception as quality_err:
            log.debug(
                "Failed to calculate quality metrics",
                error=str(quality_err),
            )

        return EvaluationResult(
            problem_name=problem.name,
            checkpoint_name=checkpoint.name,
            success=False,
            error_type=type(e).__name__,
            error_message=str(e),
            error_traceback=tb_str,
        )


def maybe_progress_bar(
    description: str, num_tasks: int, enabled: bool, console
):
    """
    Creates a small wrapper object around a Rich progress bar.

    Parameters
    ----------
    description : str
        Description displayed next to the bar.
    num_tasks : int
        Total number of steps in the progress bar.
    enabled : bool
        Whether the progress bar is shown.
    console : rich.console.Console
        Console instance used for rendering.

    Returns
    -------
    object with `update(current: int)` method
    """

    if not enabled:
        # Return a no-op object
        class Dummy:
            def update(self, current: int):
                pass

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                pass

        return Dummy()

    # Build rich progress bar
    progress = Progress(
        TextColumn("{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        console=console,
    )
    live_progress = Live(progress, console=console, refresh_per_second=2.0)
    task_id = progress.add_task(description, total=num_tasks)

    @dataclass
    class Bar:
        progress: Progress
        live: Live
        task_id: int

        def update(self, current: int):
            self.progress.update(self.task_id, completed=current)

        def __enter__(self):
            self.live.__enter__()
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            self.live.__exit__(exc_type, exc_val, exc_tb)

    return Bar(progress, live_progress, task_id)


def evaluate(
    problems: list[tuple[ProblemConfig, Path]],
    environment: EnvironmentSpec,
    num_workers: int,
    snapshot_dir_name: str = SNAPSHOT_DIR_NAME,
    console: Console = Console(),
    *,
    live_progress: bool = False,
    rubric_path: Path | None = None,
    rubric_model: str | None = None,
    rubric_temperature: float = 0.0,
    rubric_provider: RubricProvider = RubricProvider.OPENROUTER,
) -> tuple[
    dict[str, dict[str, tuple[CorrectnessResults, SnapshotQualityReport]]],
    BatchEvaluationSummary,
]:
    """Evaluate checkpoints for a list of problems.

    Returns:
        A tuple of (results dict, BatchEvaluationSummary with error tracking)
    """
    logger.info(
        "Starting checkpoint evaluation",
        problems=[p[0].name for p in problems],
    )
    # Use the worker wrapper to ensure logging is configured in each worker process
    eval_fn = functools.partial(
        _evaluate_checkpoint_worker,
        environment=environment,
        rubric_path=rubric_path,
        rubric_model=rubric_model,
        rubric_temperature=rubric_temperature,
        rubric_provider=rubric_provider,
    )

    def get_eval_args(
        problem: ProblemConfig, problem_submission: Path
    ) -> Generator[
        tuple[Path, Path, CheckpointConfig, ProblemConfig], None, None
    ]:
        for (
            chkpt,
            chkpt_submission,
            snapshot_dir,
        ) in gather_checkpoint_directories(
            problem=problem,
            submission_dir=problem_submission,
            snapshot_dir_name=snapshot_dir_name,
        ):
            checkpoint = problem.load_checkpoint(chkpt)

            yield snapshot_dir, chkpt_submission, checkpoint, problem

    name_to_path = {
        problem.name: problem_submission
        for problem, problem_submission in problems
    }
    results = defaultdict(dict)
    errors: list[EvaluationResult] = []
    successful = 0

    with ProcessPoolExecutor(max_workers=num_workers) as executor:
        futures = [
            executor.submit(eval_fn, *args)
            for p_cfg, p_submission in problems
            for args in get_eval_args(p_cfg, p_submission)
        ]
        total_checkpoints = len(futures)

        with maybe_progress_bar(
            description="Evaluating checkpoints",
            num_tasks=total_checkpoints,
            enabled=live_progress,
            console=console,
        ) as bar:
            completed = 0
            for future in as_completed(futures):
                eval_result = future.result()
                completed += 1
                bar.update(completed)

                if not eval_result.success:
                    logger.error(
                        "Checkpoint evaluation failed",
                        problem_name=eval_result.problem_name,
                        checkpoint_name=eval_result.checkpoint_name,
                        error_type=eval_result.error_type,
                        error_message=eval_result.error_message,
                    )
                    errors.append(eval_result)
                    continue

                successful += 1
                result = eval_result.result
                logger.info(
                    "Evaluated checkpoint",
                    problem_name=result.problem_name,
                    checkpoint_name=result.checkpoint_name,
                )
                results[result.problem_name][result.checkpoint_name] = (
                    result.report,
                    result.quality,
                )

    logger.info(
        "Evaluation complete saving full results",
        total=len(results),
        successful=successful,
        failed=len(errors),
    )
    for problem_name, checkpoints in results.items():
        summaries = {
            checkpoint_name: (report, quality)
            for checkpoint_name, (report, quality) in checkpoints.items()
        }
        maybe_update_problem_report(name_to_path[problem_name], summaries)

    summary = BatchEvaluationSummary(
        total_checkpoints=total_checkpoints,
        successful=successful,
        failed=len(errors),
        errors=errors,
    )

    return results, summary
