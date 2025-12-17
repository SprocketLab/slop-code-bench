"""Common verification utilities and helper functions.

This module provides a collection of reusable verification functions that can be
used in custom verifier implementations. It includes utilities for deep diff
comparisons, JSON schema validation, regex matching, and status code verification.
All functions return standardized VerificationResult objects with proper scoring.
"""

from __future__ import annotations

import re
from functools import reduce
from typing import Any

import deepdiff
import jsonschema

from slop_code.evaluation.verifiers.models import VerificationResult
from slop_code.evaluation.verifiers.parsers import ResultAttributeValue
from slop_code.evaluation.verifiers.parsers import ensure_non_null_string

# Default configuration for DeepDiff comparisons
DEFAULT_DEEPDIFF_KWARGS: dict[str, Any] = {
    "ignore_string_type_changes": True,
    "ignore_numeric_type_changes": True,
    "ignore_nan_inequality": True,
    "math_epsilon": 1e-6,
}


def deepdiff_verify(
    actual: Any,
    expected: Any,
    weight: float = 1.0,
    **kwargs: Any,
) -> VerificationResult:
    diff = deepdiff.DeepDiff(expected, actual, **{**DEFAULT_DEEPDIFF_KWARGS, **kwargs})
    if isinstance(actual, str) and isinstance(expected, str) and "root" in diff:
        diff = diff["root"]["diff"]
    return VerificationResult.create(diff, is_correct=not diff, weight=weight)


def jsonschema_verify(
    actual: ResultAttributeValue,
    expected: dict[str, Any],
    weight: float = 1.0,
) -> VerificationResult:
    validator = jsonschema.Draft7Validator(expected)
    errors = list(validator.iter_errors(actual))
    if not errors:
        return VerificationResult.create(
            "Schema validation passed", is_correct=True, weight=weight
        )
    diff = {e.json_path: str(e.message) for e in errors}
    return VerificationResult.create(diff, is_correct=not errors, weight=weight)


def matches_status_code(actual: int, expected: int, weight=1.0) -> VerificationResult:
    return VerificationResult(
        diff=f"{actual} == {expected} -> {actual == expected}",
        is_correct=actual == expected,
        weight=weight,
    )


def matches_regex(
    actual: ResultAttributeValue,
    expected: ResultAttributeValue,
    weight=1.0,
    flags: list[re.RegexFlag] | None = None,
    *,
    lstrip: bool = True,
) -> VerificationResult:
    flags = flags or [
        re.IGNORECASE,
    ]
    reduced_flags = reduce(lambda x, y: x | y, flags)
    expected = ensure_non_null_string(expected, allow_empty=False)
    actual = ensure_non_null_string(actual, allow_empty=True)
    if lstrip:
        actual = actual.lstrip()
    is_correct = re.match(expected, actual, flags=reduced_flags) is not None
    return VerificationResult(
        diff=f"Pattern={expected} matches {actual} -> {is_correct}",
        is_correct=is_correct,
        weight=weight,
    )
