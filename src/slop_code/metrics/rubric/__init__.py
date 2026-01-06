"""Rubric grading utilities for LLM-based code evaluation.

This package provides pure functions for LLM-based rubric grading,
template rendering, and grade carry-forward logic.
"""

from __future__ import annotations

from enum import Enum


class RubricProvider(str, Enum):
    """Supported LLM providers for rubric grading."""

    OPENROUTER = "openrouter"
    BEDROCK = "bedrock"


from slop_code.metrics.rubric.carry_forward import carry_forward_all_files
from slop_code.metrics.rubric.carry_forward import carry_forward_grades
from slop_code.metrics.rubric.carry_forward import load_diff_text
from slop_code.metrics.rubric.carry_forward import process_problem_carry_forward
from slop_code.metrics.rubric.llm_grade import OPENROUTER_API_KEY_ENV
from slop_code.metrics.rubric.llm_grade import grade_file
from slop_code.metrics.rubric.llm_grade import grade_file_async

__all__ = [
    "carry_forward_all_files",
    "carry_forward_grades",
    "grade_file",
    "grade_file_async",
    "OPENROUTER_API_KEY_ENV",
    "load_diff_text",
    "process_problem_carry_forward",
    "RubricProvider",
]
