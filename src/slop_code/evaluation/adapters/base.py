"""Base adapter interfaces and shared configuration models."""

from __future__ import annotations

from abc import ABC
from abc import abstractmethod
from typing import (
    Any,
    Generic,
    Literal,
    Protocol,
    Self,
    TypeVar,
    runtime_checkable,
)

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from slop_code.evaluation.adapters.models import BaseCase
from slop_code.evaluation.adapters.models import CaseResult
from slop_code.execution import ExecutionError
from slop_code.execution import Session
from slop_code.logging import get_logger

logger = get_logger(__name__)


class AdapterConfig(BaseModel):
    """Base adapter configuration discriminated by ``type``."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["cli", "api", "playwright"] = "cli"
    setup_script: str | None = None
    teardown_script: str | None = None
    tracked_files: list[str] = Field(
        default_factory=list,
        description="Group-level tracked file paths or glob patterns.",
    )


class AdapterError(Exception):
    """Raised for adapter misuse or irrecoverable adapter-level failures."""


@runtime_checkable
class Adapter(Protocol):
    def __enter__(self) -> Adapter:  # type: ignore
        """Prepare group-scoped resources and return self."""

    def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
        """Tear down group-scoped resources."""

    def run_case(self, case: BaseCase) -> CaseResult:  # type: ignore
        """Execute the case and collect a `CaseResult`."""


# Type variables for generic adapter base class
CaseT = TypeVar("CaseT", bound=BaseCase)
ResultT = TypeVar("ResultT", bound=CaseResult)
ConfigT = TypeVar("ConfigT", bound=AdapterConfig)


class AdapterRegistry:
    """Registry for adapter types, enabling dynamic dispatch by type string."""

    _adapters: dict[str, type[BaseAdapter[Any, Any, Any]]] = {}

    @classmethod
    def register(cls, type_name: str):
        """Decorator to register an adapter class under a type name.

        Example:
            @ADAPTER_REGISTRY.register("cli")
            class CLIAdapter(BaseAdapter[CLICase, CLIResult, CLIAdapterConfig]):
                ...
        """

        def decorator(
            adapter_cls: type[BaseAdapter[Any, Any, Any]],
        ) -> type[BaseAdapter[Any, Any, Any]]:
            if type_name in cls._adapters:
                raise ValueError(
                    f"Adapter type '{type_name}' already registered"
                )
            cls._adapters[type_name] = adapter_cls
            return adapter_cls

        return decorator

    @classmethod
    def get(cls, type_name: str) -> type[BaseAdapter[Any, Any, Any]]:
        """Get adapter class by type name."""
        if type_name not in cls._adapters:
            raise ValueError(
                f"Unknown adapter type: {type_name}. "
                f"Available: {list(cls._adapters.keys())}"
            )
        return cls._adapters[type_name]

    @classmethod
    def make_adapter(
        cls,
        config: AdapterConfig,
        session: Session,
        env: dict[str, str],
        command: str,
        timeout: float | None = None,
        isolated: bool = False,
    ) -> BaseAdapter[Any, Any, Any]:
        """Factory method to create adapter from config."""
        adapter_cls = cls.get(config.type)
        return adapter_cls(
            cfg=config,
            session=session,
            env=env,
            command=command,
            timeout=timeout,
            isolated=isolated,
        )

    @classmethod
    def clear(cls) -> None:
        """Clear all registered adapters. Primarily for testing."""
        cls._adapters.clear()


ADAPTER_REGISTRY = AdapterRegistry()


class BaseAdapter(ABC, Generic[CaseT, ResultT, ConfigT]):
    """Abstract base class providing shared adapter implementation.

    Handles session lifecycle, placeholder resolution, tracked file merging,
    and error result construction. Subclasses implement case execution logic.

    Type Parameters:
        CaseT: The case type this adapter accepts (e.g., CLICase)
        ResultT: The result type this adapter returns (e.g., CLIResult)
        ConfigT: The config type for this adapter (e.g., CLIAdapterConfig)
    """

    # Subclasses must set these class attributes
    case_class: type[CaseT]
    result_class: type[ResultT]
    config_class: type[ConfigT]

    def __init__(
        self,
        cfg: ConfigT,
        session: Session,
        env: dict[str, str],
        command: str,
        timeout: float | None = None,
        isolated: bool = False,
    ) -> None:
        """Initialize the adapter with execution context.

        Args:
            cfg: Adapter configuration.
            session: Execution session managing workspace and runtime lifecycle.
            env: Environment variables for command execution.
            command: Base command string for execution.
            timeout: Default timeout applied when cases do not override.
            isolated: Whether to reset workspace after each case.
        """
        self.cfg = cfg
        self.session = session
        self.env = env
        self.command = command
        self.timeout = timeout
        self.isolated = isolated
        self.tracked_files = list(cfg.tracked_files)
        self.setup_script = cfg.setup_script
        self.teardown_script = cfg.teardown_script

    def __enter__(self) -> Self:
        """Prepare session and adapter-specific resources."""
        self.session.prepare()
        self._on_enter()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        """Clean up adapter-specific resources and session."""
        self._on_exit(exc_type, exc, tb)
        self.session.cleanup()

    def _on_enter(self) -> None:
        """Hook for subclasses to initialize resources after session.prepare().

        Override this instead of __enter__ to add custom setup logic.
        """

    def _on_exit(self, exc_type, exc, tb) -> None:
        """Hook for subclasses to clean up before session.cleanup().

        Override this instead of __exit__ to add custom teardown logic.
        """

    def run_case(self, case: CaseT) -> ResultT:
        """Execute a case with common pre/post processing.

        Handles placeholder resolution, file tracking, and error handling.
        Delegates actual execution to _execute_case().
        """
        resolved_case = self._resolve_case_placeholders(case)
        tracked = self._merge_tracked_files(resolved_case)

        try:
            return self._execute_case(resolved_case, tracked)
        except ExecutionError as exc:
            logger.error(
                "Execution provider failed",
                error=str(exc),
                adapter=self.__class__.__name__,
            )
            return self._make_error_result(case, exc)

    @abstractmethod
    def _execute_case(self, case: CaseT, tracked_files: list[str]) -> ResultT:
        """Subclass-specific case execution logic.

        Args:
            case: The resolved case with placeholders substituted.
            tracked_files: Merged list of files to track from adapter and case.

        Returns:
            The execution result.
        """
        ...

    def _resolve_case_placeholders(self, case: CaseT) -> CaseT:
        """Resolve static asset placeholders in case fields.

        Args:
            case: Original case with potential placeholders.

        Returns:
            New case instance with placeholders resolved.
        """
        case_dict = case.model_dump()
        resolved_dict = self.session.resolve_static_placeholders(case_dict)
        return self.case_class.model_validate(resolved_dict)

    def _merge_tracked_files(self, case: CaseT) -> list[str]:
        """Merge adapter-level and case-level tracked files.

        Args:
            case: The case whose tracked_files to merge with adapter's.

        Returns:
            Deduplicated list of tracked file patterns.
        """
        return list(set(self.tracked_files).union(case.tracked_files))

    def _make_error_result(self, case: CaseT, exc: Exception) -> ResultT:
        """Construct an error result from an exception.

        Args:
            case: The case that failed.
            exc: The exception that occurred.

        Returns:
            A result with adapter_error=True and error details.
        """
        return self.result_class(
            id=case.id,
            group_type=case.group_type,
            group=case.group,
            status_code=-1,
            stderr=str(exc),
            elapsed=0.0,
            adapter_error=True,
            resource_path=None,
        )

    def _get_file_contents(self, tracked: list[str]) -> dict[str, str | bytes]:
        """Get contents of tracked files from session.

        Args:
            tracked: List of file paths or glob patterns.

        Returns:
            Dictionary mapping file paths to their contents.
        """
        return self.session.get_file_contents(tracked)
