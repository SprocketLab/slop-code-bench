"""Evaluation orchestration package for running benchmark checkpoints.

Exports primary configuration models, adapter/loader registries, and the
checkpoint runner used by the CLI entry points. See the individual modules
for detailed documentation on each component.
"""

from slop_code.evaluation import adapters
from slop_code.evaluation import verifiers
from slop_code.evaluation.adapters import api as api_adapter
from slop_code.evaluation.adapters import cli as cli_adapter
from slop_code.evaluation.config import CheckpointConfig
from slop_code.evaluation.config import ConfigError
from slop_code.evaluation.config import GroupConfig
from slop_code.evaluation.config import GroupType
from slop_code.evaluation.config import ProblemConfig
from slop_code.evaluation.config import get_available_problems
from slop_code.evaluation.report import CorrectnessResults
from slop_code.evaluation.report import GroupReport
from slop_code.evaluation.report import PassPolicy
from slop_code.evaluation.runner import initialize_loader
from slop_code.evaluation.runner import run_checkpoint
from slop_code.evaluation.verifiers import VerifierReport
from slop_code.evaluation.verifiers import initialize_verifier

__all__ = [
    "CheckpointConfig",
    "GroupConfig",
    "ProblemConfig",
    "ConfigError",
    "GroupType",
    "get_available_problems",
    "adapters",
    "PassPolicy",
    "adapters",
    "verifiers",
    "api_adapter",
    "cli_adapter",
    "CorrectnessResults",
    "GroupReport",
    "PassPolicy",
    "initialize_loader",
    "run_checkpoint",
    "VerifierReport",
    "initialize_verifier",
]
