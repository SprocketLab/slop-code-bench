"""Adapter implementation for command-line style submissions."""

from __future__ import annotations

import shlex
from typing import Literal

from pydantic import ConfigDict
from pydantic import Field
from pydantic import field_validator

from slop_code.evaluation.adapters.base import ADAPTER_REGISTRY
from slop_code.evaluation.adapters.base import AdapterConfig
from slop_code.evaluation.adapters.base import BaseAdapter
from slop_code.evaluation.adapters.models import BaseCase
from slop_code.evaluation.adapters.models import CaseResult
from slop_code.execution import ExecutionError
from slop_code.execution.runtime import RuntimeResult
from slop_code.logging import get_logger

logger = get_logger(__name__)


class CLIAdapterConfig(AdapterConfig):
    """Adapter configuration for running a CLI entrypoint per case."""

    model_config = ConfigDict(extra="forbid")
    type: Literal["cli"] = "cli"  # type: ignore[assignment]


class CLIResult(CaseResult):
    type: Literal["cli"] = Field(default="cli", frozen=True)  # type: ignore[assignment]
    command: str | None = None


class CLICase(BaseCase):
    """Concrete case model for the CLI adapter."""

    arguments: list[str] = Field(default_factory=list)
    stdin: str | None = None

    @field_validator("arguments")
    @classmethod
    def validate_arguments(cls, v: list[str] | str) -> list[str]:
        if isinstance(v, str):
            return shlex.split(v)
        return v


@ADAPTER_REGISTRY.register("cli")
class CLIAdapter(BaseAdapter[CLICase, CLIResult, CLIAdapterConfig]):
    """Adapter that executes the submission's CLI entrypoint per case.

    Spawns a fresh runtime for each case execution and cleans up after.
    """

    case_class = CLICase
    result_class = CLIResult
    config_class = CLIAdapterConfig

    def _execute_case(
        self, case: CLICase, tracked_files: list[str]
    ) -> CLIResult:
        """Run a single CLI command and return the result.

        Args:
            case: The resolved case with arguments and optional stdin.
            tracked_files: File patterns to collect after execution.

        Returns:
            CLIResult with stdout, stderr, exit code, and tracked files.
        """
        cmd = " ".join([self.command, *case.arguments])

        self.session.materialize_input_files(case.input_files)
        runtime = self.session.spawn()
        try:
            exec_result: RuntimeResult = runtime.execute(
                cmd, self.env, case.stdin, self.timeout
            )
        except ExecutionError as exc:
            logger.error(
                "Execution provider failed",
                error=str(exc),
                command=cmd,
            )
            return CLIResult(
                id=case.id,
                group_type=case.group_type,
                group=case.group,
                status_code=-1,
                stderr=str(exc),
                elapsed=0.0,
                adapter_error=True,
                resource_path=None,
                command=cmd,
            )
        finally:
            runtime.cleanup()

        result = CLIResult(
            id=case.id,
            group_type=case.group_type,
            group=case.group,
            status_code=exec_result.exit_code,
            output=exec_result.stdout,
            stderr=exec_result.stderr,
            timed_out=exec_result.timed_out,
            files=self._get_file_contents(tracked_files),
            elapsed=exec_result.elapsed,
            resource_path=None,
            command=cmd,
        )

        if self.isolated:
            self.session.reset()

        logger.debug(
            "Finished executing CLI case",
            case_id=case.id,
            stderr=repr(result.stderr)[-100:] if result.stderr else None,
        )

        return result
