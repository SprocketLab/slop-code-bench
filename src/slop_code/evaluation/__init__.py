"""Evaluation orchestration package for running benchmark checkpoints."""

from slop_code.evaluation.config import CheckpointConfig
from slop_code.evaluation.config import ConfigError
from slop_code.evaluation.config import GroupConfig
from slop_code.evaluation.config import ProblemConfig
from slop_code.evaluation.config import get_available_problems
from slop_code.evaluation.pytest_runner import run_checkpoint_pytest
from slop_code.evaluation.report import CorrectnessResults
from slop_code.evaluation.report import GroupReport
from slop_code.evaluation.report import GroupType
from slop_code.evaluation.report import PassPolicy
from slop_code.evaluation.report import TestResult

# Backwards compatibility alias
run_checkpoint = run_checkpoint_pytest

__all__ = [
    "CheckpointConfig",
    "ConfigError",
    "CorrectnessResults",
    "GroupConfig",
    "GroupReport",
    "GroupType",
    "PassPolicy",
    "ProblemConfig",
    "TestResult",
    "get_available_problems",
    "run_checkpoint",
    "run_checkpoint_pytest",
]
