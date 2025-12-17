"""Centralized tree-sitter parser for Python."""

from __future__ import annotations

from tree_sitter_language_pack import get_parser

_PARSER = None


def get_python_parser():
    """Return a cached Python parser instance."""
    global _PARSER  # noqa: PLW0603
    if _PARSER is None:
        _PARSER = get_parser("python")
    return _PARSER
