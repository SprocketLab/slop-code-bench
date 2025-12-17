"""Verifier sub-module for evaluation functionality.

This module provides utilities for loading, parsing, and verifying
case results in the evaluation system.
"""

# Core models and protocols
# Parsing utilities
from slop_code.evaluation.verifiers import parsers
from slop_code.evaluation.verifiers.format_validators import validate_format

# Loading utilities
from slop_code.evaluation.verifiers.loader import VerifierError
from slop_code.evaluation.verifiers.loader import get_verifier_source_files
from slop_code.evaluation.verifiers.loader import initialize_verifier
from slop_code.evaluation.verifiers.models import AttributeResult
from slop_code.evaluation.verifiers.models import VerificationResult
from slop_code.evaluation.verifiers.models import VerifierProtocol
from slop_code.evaluation.verifiers.models import VerifierReport
from slop_code.evaluation.verifiers.models import VerifierReturnType

# Verification helpers
from slop_code.evaluation.verifiers.verifiers import DEFAULT_DEEPDIFF_KWARGS
from slop_code.evaluation.verifiers.verifiers import deepdiff_verify
from slop_code.evaluation.verifiers.verifiers import jsonschema_verify
from slop_code.evaluation.verifiers.verifiers import matches_regex
from slop_code.evaluation.verifiers.verifiers import matches_status_code

__all__ = [
    # Core models and protocols
    "AttributeResult",
    "VerifierProtocol",
    "VerifierReport",
    "VerifierReturnType",
    "VerificationResult",
    # Loading utilities
    "VerifierError",
    "get_verifier_source_files",
    "initialize_verifier",
    # Verification helpers
    "DEFAULT_DEEPDIFF_KWARGS",
    "deepdiff_verify",
    "matches_regex",
    "matches_status_code",
    "jsonschema_verify",
    "validate_format",
]
