"""Trajectory parser protocol and auto-detection for agent analysis."""

from __future__ import annotations

from abc import ABC
from abc import abstractmethod
from pathlib import Path

from slop_code.agent_runner.trajectory import Trajectory


class ParseError(Exception):
    """Raised when trajectory parsing fails."""

    pass


class TrajectoryParser(ABC):
    """Abstract base class for parsing agent artifact directories."""

    @abstractmethod
    def can_parse(self, artifact_dir: Path) -> bool:
        """Check if this parser can handle the given artifact directory.

        Args:
            artifact_dir: Path to agent artifacts directory

        Returns:
            True if this parser can handle the directory
        """
        pass

    @abstractmethod
    def parse(self, artifact_dir: Path) -> Trajectory:
        """Parse artifact directory into a Trajectory.

        Args:
            artifact_dir: Path to agent artifacts directory

        Returns:
            Trajectory with chronologically ordered steps

        Raises:
            ParseError: If parsing fails
        """
        pass


def parse_trajectory(artifact_dir: Path) -> Trajectory:
    """Auto-detect agent type and parse trajectory.

    Args:
        artifact_dir: Path to agent artifacts (directory or agent.tar.gz)

    Returns:
        Trajectory with normalized, chronologically ordered steps

    Raises:
        ParseError: If no parser can handle or parsing fails
        ValueError: If artifact path doesn't exist
    """
    # Import parsers here to avoid circular imports
    from slop_code.agent_runner.agents.claude_code.parser import (
        ClaudeCodeParser,
    )
    from slop_code.agent_runner.agents.codex.parser import CodexParser
    from slop_code.agent_runner.agents.gemini.parser import GeminiParser
    from slop_code.agent_runner.agents.miniswe.parser import MinisweParser
    from slop_code.agent_runner.agents.opencode.parser import OpenCodeParser
    from slop_code.agent_runner.agents.openhands.parser import OpenHandsParser

    # Handle compressed artifacts
    if artifact_dir.is_file() and artifact_dir.suffix == ".gz":
        import shutil
        import tarfile
        import tempfile

        temp_dir = Path(tempfile.mkdtemp())
        try:
            with tarfile.open(artifact_dir, "r:gz") as tar:
                tar.extractall(temp_dir)
            return parse_trajectory(temp_dir)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    if not artifact_dir.exists():
        raise ValueError(f"Artifact directory does not exist: {artifact_dir}")

    # Try each parser in order of specificity
    # More specific formats first, broader formats last
    parsers = [
        ClaudeCodeParser,
        CodexParser,
        OpenCodeParser,
        GeminiParser,
        OpenHandsParser,
        MinisweParser,  # Last since it matches any role-based format
    ]

    for parser_cls in parsers:
        parser = parser_cls()
        if parser.can_parse(artifact_dir):
            try:
                return parser.parse(artifact_dir)
            except Exception as e:
                raise ParseError(
                    f"Failed to parse with {parser_cls.__name__}: {e}"
                )

    raise ParseError(f"No trajectory parser found for: {artifact_dir}")


__all__ = [
    "TrajectoryParser",
    "ParseError",
    "parse_trajectory",
]
