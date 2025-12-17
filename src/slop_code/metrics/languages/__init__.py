"""Language-specific metric implementations.

This package contains language-specific implementations for calculating
code quality metrics like line counts, linting, symbol extraction, and
maintainability index.

Importing this package will register all available language specs.
"""

from __future__ import annotations

# Import language modules to trigger registration
from slop_code.metrics.languages import python  # noqa: F401

# Re-export registry functions and constants
from slop_code.metrics.languages.registry import EXT_TO_LANGUAGE
from slop_code.metrics.languages.registry import LANGUAGE_REGISTRY
from slop_code.metrics.languages.registry import get_language
from slop_code.metrics.languages.registry import get_language_by_extension
from slop_code.metrics.languages.registry import get_language_for_extension
from slop_code.metrics.languages.registry import register_language

__all__ = [
    "EXT_TO_LANGUAGE",
    "LANGUAGE_REGISTRY",
    "get_language",
    "get_language_by_extension",
    "get_language_for_extension",
    "register_language",
]
