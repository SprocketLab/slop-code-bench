"""Task runner for executing agent problems with multiprocessing support.

This module provides functionality for running agent problems in parallel with
isolated logging and real-time progress tracking.
"""

from slop_code.entrypoints.problem_runner.driver import run_problems
from slop_code.entrypoints.problem_runner.models import ProblemAttempt
from slop_code.entrypoints.problem_runner.models import RunTaskConfig
from slop_code.entrypoints.problem_runner.models import TaskResult
from slop_code.entrypoints.problem_runner.models import build_problem_attempts
from slop_code.entrypoints.problem_runner.models import (
    resolve_attempt_source_problem,
)

__all__ = [
    "ProblemAttempt",
    "RunTaskConfig",
    "TaskResult",
    "build_problem_attempts",
    "resolve_attempt_source_problem",
    "run_problems",
]
