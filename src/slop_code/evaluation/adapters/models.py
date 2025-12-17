"""Shared Pydantic models used across adapter implementations."""

from __future__ import annotations

import functools
from collections.abc import Mapping
from enum import Enum
from pathlib import Path

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import JsonValue

from slop_code.execution.file_ops import InputFile
from slop_code.logging import get_logger

logger = get_logger(__name__)


class CaseResultError(Exception):
    """Raised for invalid attribute access or type mismatches on results."""


class GroupType(str, Enum):
    ERROR = "Error"
    FUNCTIONALITY = "Functionality"
    REGRESSION = "Regression"
    CORE = "Core"


DEFAULT_GROUP_TYPE: GroupType = GroupType.FUNCTIONALITY


class _CaseInfo(BaseModel):
    """Information about a case."""

    id: str
    group_type: GroupType
    group: str


class CaseResult(_CaseInfo):
    """Outcome of executing a submission for a single case.

    Attributes:
        type: The type of the adapter.
        resource_path: Adapter-specific path reference (e.g., CLI entrypoint,
            HTTP URL). Adapters document their interpretation.
        elapsed: Execution duration in seconds.
        status_code: Process exit status or HTTP status code.
        adapter_error: True when the adapter encountered an error.
        output: Primary output (stdout or HTTP body).
        timed_out: True if the run exceeded its timeout.
        files: JSON-serializable files collected from execution.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)
    type: str = "base"
    elapsed: float = 0
    status_code: int = 0
    resource_path: str | Path | None = None
    adapter_error: bool = False
    output: JsonValue = None
    stderr: JsonValue = None
    timed_out: bool = False
    files: dict[str, JsonValue | bytes] = Field(default_factory=dict)


class BaseCase(_CaseInfo):
    """Base case model shared by adapters.

    Adapter implementations typically subclass this to add fields such as
    CLI arguments, stdin, HTTP request details, etc.

    Attributes:
        id: Stable identifier for the case.
        timeout_s: Optional per-case timeout override (seconds).
        input_files: Mapping of relative paths to file contents that
            should be written before executing the case.
        tracked_files: Relative file paths or glob patterns to collect after
            execution.
    """

    model_config = ConfigDict(extra="allow")
    original_group: str | None = None
    original_checkpoint: str | None = None
    checkpoint: str
    order: int = -1
    arguments: list[str] = Field(default_factory=list)
    timeout_s: float | None = None
    input_files: list[InputFile] = Field(default_factory=list)
    tracked_files: list[str] = Field(
        default_factory=list,
        description="Relative file paths or glob patterns to pull into results.",
    )
    reset: bool = Field(
        default=False,
        description=(
            "Reset workspace before running this case. When True, the workspace "
            "is reset to its initial state before executing this specific case."
        ),
    )

    def __repr__(self) -> str:
        return f"Case-{self.id}(arguments={self.arguments}, timeout_s={self.timeout_s})"

    def get_attr(
        self, attr_name: str, key_path: list[str] | None = None
    ) -> JsonValue:
        """Return a top-level or nested attribute value.

        Args:
            attr_name: Name of a top-level field on ``BaseCase``.
            key_path: Optional nested path for mapping-typed values.

        Returns:
            The resolved attribute value.

        Raises:
            CaseResultError: If the attribute or nested key is missing or not a mapping.
        """
        try:
            value = getattr(self, attr_name)
        except AttributeError as e:
            raise CaseResultError(
                f"attribute {attr_name} not found: {e}"
            ) from e
        if key_path is None:
            return value
        if not isinstance(value, Mapping):
            raise CaseResultError(
                f"value must be a mapping: {attr_name}={value}"
            )
        try:
            return functools.reduce(lambda dct, key: dct[key], key_path, value)  # type: ignore[arg-type]
        except KeyError as e:
            raise CaseResultError(f"key not found: {e}") from e
