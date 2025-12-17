"""Dynamic test case loading and discovery system for evaluation checkpoints.

This module provides utilities for loading test cases from various sources
including script-based loaders, directory discovery, and file pattern matching.
It supports both static case definitions and dynamic case generation through
user-defined loader scripts.
"""

from __future__ import annotations

from collections.abc import Generator
from typing import (
    TYPE_CHECKING,
    Protocol,
    runtime_checkable,
)

from slop_code.evaluation.adapters.models import BaseCase
from slop_code.evaluation.adapters.models import CaseResult
from slop_code.logging import get_logger

if TYPE_CHECKING:
    from slop_code.evaluation.config import CheckpointConfig
    from slop_code.evaluation.config import GroupConfig
    from slop_code.evaluation.config import ProblemConfig

logger = get_logger(__name__)

GROUP_LOADER_ENTRY = "GroupLoader"

LoaderYieldType = Generator[tuple[BaseCase, CaseResult], None, None]


class LoaderError(Exception):
    """Raised when a group loader function cannot be loaded or executed."""


@runtime_checkable
class CaseStore(Protocol):
    """Base class for case stores. Must be subclassed to be used."""

    def update(
        self, case: BaseCase, result: CaseResult, expected: CaseResult
    ) -> None:
        """Update the store with a result and return the stored attributes.

        We want to be able to see the attributes that were stored for each case
        so we can debug the loader/verifier later.
        """
        ...


class NoOpStore(CaseStore):
    """No-op case store."""

    def update(
        self, case: BaseCase, result: CaseResult, expected: CaseResult
    ) -> None:
        """No operation performs on the result."""
        _ = case
        _ = result
        _ = expected
        return {}


@runtime_checkable
class GroupLoader(Protocol):
    """Group loader interface."""

    def __init__(
        self,
        checkpoint: CheckpointConfig,
        *,
        use_placeholders: bool = False,
    ): ...

    def initialize_store(self) -> CaseStore:
        """Initialize the case store."""
        ...

    def __call__(self, group: GroupConfig, store: CaseStore) -> LoaderYieldType:
        """Loads the list of test cases for each group in the checkpoint.

        Note that the order of the cases yielded per group is respected during
        evaluation. This is useful for stateful scenarios where the order of the
        cases matters.

        Args:
            group: The group configuration.
            store: The case store.
        Returns:
            A generator of tuples of (BaseCase, CaseResult) for each case in the group.
        """
        ...


class BaseLoader:
    def __init__(
        self,
        problem: ProblemConfig,
        checkpoint: CheckpointConfig,
        *,
        use_placeholders: bool = False,
    ):
        self.problem = problem
        self.checkpoint = checkpoint
        self.use_placeholders = use_placeholders

    def initialize_store(self) -> CaseStore:
        """Initialize the case store."""
        return NoOpStore()  # Default implementation

    def __call__(self, group: GroupConfig, store: CaseStore) -> LoaderYieldType:
        """Loads the list of test cases for each group in the checkpoint."""
        raise NotImplementedError("Subclasses must implement this method.")
