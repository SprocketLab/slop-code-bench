"""Shared constants and utilities for metrics module."""

from __future__ import annotations

from typing import Any

# File name constants for metrics and evaluation outputs


class MetricsError(Exception):
    """Raised when metrics collection or processing fails.

    Attributes:
        context: Additional context dict for logging
    """

    def __init__(
        self,
        message: str,
        *,
        context: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.context = context or {}
