"""Dynamic verifier loading and initialization system.

This module provides utilities for dynamically loading user-defined verifier
classes from problem directories. It supports protocol-based loading to ensure
type safety and proper initialization of verifier implementations.
"""

from __future__ import annotations

from pathlib import Path

from slop_code.evaluation.config import CheckpointConfig
from slop_code.evaluation.verifiers.models import VerifierProtocol
from slop_code.logging import get_logger
from slop_code.protocol_loader import ProtocolLoadError
from slop_code.protocol_loader import get_source_files
from slop_code.protocol_loader import load_protocol_entrypoint

logger = get_logger(__name__)

VERIFICATION_ENTRY = "Verifier"


class VerifierError(Exception):
    """Raised when a verifier function cannot be loaded or executed."""


def initialize_verifier(
    problem_path: Path, checkpoint_config: CheckpointConfig
) -> VerifierProtocol:
    """Dynamically import a user-defined verifier class.

    The import path should be a dotted module path to the verifier module.
    The class named 'Verifier' will be loaded from the module.

    Args:
        problem_path: Path to the problem directory containing verifier.py

    Returns:
        Class matching the VerifierProtocol

    Raises:
        VerifierError: If the module cannot be imported or the class doesn't
                       exist

    Example:
        >>> verifier_cls = initialize_verifier(Path("problems/example"), checkpoint_config)
        >>> verifier = verifier_cls(checkpoint_config)
        >>> results = verifier(
        "basic", group_config, "case_1", actual_result, expected_result
    )
    """
    verifier_file = problem_path / "verifier.py"

    try:
        verifier_cls = load_protocol_entrypoint(
            protocol=VerifierProtocol,
            module_path=verifier_file,
            entrypoint_name=VERIFICATION_ENTRY,
        )
    except ProtocolLoadError as e:
        raise VerifierError(str(e)) from e

    return verifier_cls(checkpoint_config)


def get_verifier_source_files(
    problem_path: Path, checkpoint_config: CheckpointConfig
) -> dict[str, str]:
    """Return source code for the verifier and any problem-local modules it
    imports.

    This ensures downstream consumers (e.g. reporting or artifact capture)
    can display the exact verification logic that executed for a checkpoint.

    Args:
        problem_path: Filesystem path to the problem directory.

    Returns:
        Mapping of problem-relative file paths to their UTF-8 source contents.

    Raises:
        VerifierError: If the verifier cannot be imported.
    """
    verifier_path = problem_path / "verifier.py"

    try:
        return get_source_files(
            module_path=verifier_path,
            load_function=lambda: initialize_verifier(
                problem_path, checkpoint_config
            ),
        )
    except ProtocolLoadError as e:
        raise VerifierError(str(e)) from e
