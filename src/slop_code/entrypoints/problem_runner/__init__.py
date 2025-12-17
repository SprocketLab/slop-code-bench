"""Task runner for executing agent problems with multiprocessing support.

This module provides functionality for running agent problems in parallel with
isolated logging and real-time progress tracking.
"""

from slop_code.entrypoints.problem_runner.driver import run_problems
from slop_code.entrypoints.problem_runner.models import RunTaskConfig
from slop_code.entrypoints.problem_runner.models import TaskResult

__all__ = [
    "RunTaskConfig",
    "TaskResult",
    "run_problems",
]
