"""Docker build-context inputs supplied alongside generated Dockerfiles."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DockerContextEntry:
    """One host path added to a generated Docker build context."""

    source: Path
    excluded_names: frozenset[str] = frozenset()
