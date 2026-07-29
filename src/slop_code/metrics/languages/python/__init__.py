"""Python-specific code quality metrics.

This package provides Python-specific implementations for calculating code
quality metrics including line counts, linting, symbol extraction, complexity
analysis, and import tracing using radon, ruff, and tree-sitter.
"""

from __future__ import annotations

from slop_code.metrics.languages.python.constants import EXTENSIONS
from slop_code.metrics.languages.python.imports import extract_imports
from slop_code.metrics.languages.python.imports import trace_source_files
from slop_code.metrics.languages.python.line_metrics import (
    calculate_line_metrics,
)
from slop_code.metrics.languages.python.line_metrics import calculate_mi
from slop_code.metrics.languages.python.lint_metrics import (
    calculate_lint_metrics,
)
from slop_code.metrics.languages.python.symbols import get_symbols
from slop_code.metrics.languages.python.type_check import (
    calculate_type_check_metrics,
)
from slop_code.metrics.languages.python.waste import calculate_waste_metrics
from slop_code.metrics.languages.registry import register_language
from slop_code.metrics.models import LanguageSpec

# Register the Python language
register_language(
    "PYTHON",
    LanguageSpec(
        extensions=EXTENSIONS,
        line=calculate_line_metrics,
        lint=calculate_lint_metrics,
        symbol=get_symbols,
        mi=calculate_mi,
        waste=calculate_waste_metrics,
        type_check=calculate_type_check_metrics,
    ),
)

__all__ = [
    # Constants
    "EXTENSIONS",
    # Line metrics
    "calculate_line_metrics",
    "calculate_mi",
    # Lint metrics
    "calculate_lint_metrics",
    # Symbol extraction
    "get_symbols",
    # Waste detection
    "calculate_waste_metrics",
    # Type check metrics
    "calculate_type_check_metrics",
    # Import extraction and tracing
    "extract_imports",
    "trace_source_files",
]
