"""Shared utilities for Python metrics."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=100)
def read_python_code(source: Path) -> str:
    """Read and cache source file contents."""
    return source.read_text(encoding="utf-8")
