"""Core models and exceptions for execution environments.

This module defines the fundamental data structures and exceptions used throughout
the execution system:

- **EnvironmentSpec**: Base configuration for execution environments
- **ExecutionError**: Base exception hierarchy for execution failures
- **InputFileReadError/WriteError**: Specific file operation errors
- Environment variable management and setup command handling
- Snapshot configuration and archive management
- Entry file formatting and command composition

The models provide the foundation for both Docker and local runtime implementations.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from collections.abc import Mapping
from pathlib import Path

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from slop_code.execution.assets import ResolvedStaticAsset
from slop_code.logging import get_logger

logger = get_logger(__name__)


class EnvironmentConfig(BaseModel):
    """Configuration for environment variables and OS environment inclusion.

    Attributes:
        env: Environment variables for execution context
        include_os_env: Whether to include current OS environment variables
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    env: dict[str, str] = Field(
        default_factory=dict,
        description="Environment variables for execution context.",
    )
    include_os_env: bool = Field(
        default=False,
        description="Whether to include current OS environment variables.",
    )


class SetupConfig(BaseModel):
    """Configuration for setup commands run before execution.

    Attributes:
        commands: Shell commands run once before execution
        eval_commands: Commands run in evaluator execution context
        resume_commands: Commands run when resuming from a checkpoint snapshot
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    commands: list[str] = Field(
        default_factory=list,
        description="Shell commands run once before execution.",
    )
    eval_commands: list[str] = Field(
        default_factory=list,
        description="Commands run in evaluator execution context.",
    )
    resume_commands: list[str] = Field(
        default_factory=list,
        description="Commands run when resuming from a checkpoint snapshot.",
    )


class CommandConfig(BaseModel):
    """Configuration for entry file formatting and command composition.

    Attributes:
        entry_file: Format string describing how to reference the problem entry file
        command: Command to be used for evaluation
        agent_command: Entry command visible to the agent
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    entry_file: str = Field(
        default="{entry_file}",
        description=(
            "Format string describing how to reference the problem entry file."
        ),
    )
    command: str = Field(
        default="python", description="Command to be used for evaluation"
    )
    agent_command: str | None = Field(
        default=None,
        description=("Entry command visible to the agent"),
    )


class SnapshotConfig(BaseModel):
    """Configuration for snapshot creation and archiving.

    Attributes:
        keep_globs: Glob patterns of files to always include in snapshots
        ignore_globs: Glob patterns of files to exclude from snapshots
        compression: Compression algorithm for snapshots (gz, bz2, xz, none)
        archive_save_dir: Directory to save snapshot archives
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    keep_globs: set[str] | None = Field(
        default=None,
        description="Glob patterns of files to always include in snapshots.",
    )
    ignore_globs: set[str] = Field(
        default={"*.pyc", "venv/*", ".venv/*"},
        description="Glob patterns of files to exclude from snapshots.",
    )
    compression: str = Field(
        default="gz",
        description="Compression algorithm for snapshots (gz, bz2, xz, none).",
    )
    archive_save_dir: Path | None = Field(
        default=None,
        description="Directory to save snapshot archives.",
    )


class LocalConfig(BaseModel):
    """Local execution-specific configuration.

    Attributes:
        requires_tty: Hint that processes should be launched with a TTY
        shell: Optional shell executable for setup commands
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    requires_tty: bool = Field(
        default=False,
        description="Hint that processes should be launched with a TTY.",
    )
    shell: str | None = Field(
        default=None,
        description="Optional shell executable for setup commands.",
    )


class ExecutionError(Exception):
    """Raised when execution fails."""


class InputFileReadError(ExecutionError):
    """Raised when an input file cannot be read."""


class InputFileWriteError(ExecutionError):
    """Raised when an input file cannot be written."""


class EnvironmentSpec(BaseModel):
    """Base contract for describing how tasks should execute.

    This class defines the common configuration for all execution environments,
    including environment variables, setup commands, and snapshot settings.

    Attributes:
        type: Runtime type discriminator (docker/local)
        name: Environment name
        environment: Environment variables and OS environment configuration
        setup: Setup commands configuration
        commands: Entry file and command configuration
        snapshot: Snapshot creation and archiving configuration
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: str
    name: str
    environment: EnvironmentConfig = Field(
        default_factory=EnvironmentConfig,
        description="Environment variables and OS environment configuration.",
    )
    setup: SetupConfig = Field(
        default_factory=SetupConfig,
        description="Setup commands configuration.",
    )
    commands: CommandConfig = Field(
        default_factory=CommandConfig,
        description="Entry file and command configuration.",
    )
    snapshot: SnapshotConfig = Field(
        default_factory=SnapshotConfig,
        description="Snapshot creation and archiving configuration.",
    )

    def get_full_env(self, other_env: Mapping[str, str]) -> dict[str, str]:
        """Get the full environment variables for the execution.

        Args:
            other_env: Additional environment variables to merge

        Returns:
            Complete environment dictionary
        """
        env = os.environ.copy() if self.environment.include_os_env else {}
        env.update(self.environment.env)
        env.update(other_env)
        return env

    def get_setup_commands(self, is_evaluation: bool = False) -> list[str]:
        """Get the setup commands for the execution context.

        Args:
            is_evaluation: Whether to include evaluation-specific commands

        Returns:
            List of setup commands to execute
        """
        setup_commands = self.setup.commands.copy()
        if is_evaluation:
            setup_commands.extend(self.setup.eval_commands)
        return setup_commands

    def get_resume_commands(self) -> list[str]:
        """Get commands to run when resuming from a checkpoint snapshot.

        Returns:
            List of resume commands to execute
        """
        return list(self.setup.resume_commands)

    def format_entry_file(self, entry_file: str) -> str:
        """Format the entry file based on the template.

        Args:
            entry_file: Entry file name to format

        Returns:
            Formatted entry file string

        Raises:
            ValueError: If template is invalid or result is empty
        """
        try:
            formatted_entry = self.commands.entry_file.format(
                entry_file=entry_file
            )
        except KeyError as exc:  # pragma: no cover - defensive guard
            msg = (
                "EnvironmentSpec.commands.entry_file must be a format string accepting "
                "'entry_file' as a keyword."
            )
            raise ValueError(msg) from exc
        if not formatted_entry:
            msg = "Formatted entry command must not be empty."
            raise ValueError(msg)
        return formatted_entry

    def get_command(
        self, entry_file: str, *, is_agent_run: bool = False
    ) -> str:
        """Compose the command used for the evaluation context.

        Args:
            entry_file: Entry file declared by the problem configuration.
            is_agent_run: Whether this is an agent run vs evaluation run.

        Returns:
            Full command string executed by adapters or agents.
        """
        formatted_entry = self.format_entry_file(entry_file=entry_file)
        if is_agent_run and self.commands.agent_command is not None:
            command = self.commands.agent_command.strip()
        else:
            command = self.commands.command.strip()

        return f"{command} {formatted_entry}".strip()

    def get_ignore_globs(
        self, static_assets: dict[str, ResolvedStaticAsset] | None = None
    ) -> set[str]:
        """Get glob patterns to ignore when creating snapshots.

        Args:
            static_assets: Optional static assets to also ignore

        Returns:
            Set of glob patterns to ignore
        """
        ignore_globs = set(self.snapshot.ignore_globs)

        # Always ignore tests/assets/ (materialized static assets for tests)
        ignore_globs.update({"tests/assets", "tests/assets/*"})

        for asset in (static_assets or {}).values():
            save_path = asset.save_path.as_posix().rstrip("/")
            if asset.absolute_path.is_dir():
                ignore_globs.update({save_path, f"{save_path}/*"})
            else:
                ignore_globs.add(save_path)
        return ignore_globs

    def get_archive_save_dir(self) -> Path:
        """Get the directory where snapshot archives should be saved.

        Returns:
            Path to archive save directory
        """
        if self.snapshot.archive_save_dir is None:
            return Path(
                tempfile.gettempdir(), f"slop_code_{uuid.uuid4().hex[:8]}"
            )
        return self.snapshot.archive_save_dir
