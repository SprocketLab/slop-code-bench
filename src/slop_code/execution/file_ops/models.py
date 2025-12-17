from __future__ import annotations

import bz2
import contextlib
import gzip
from abc import ABC
from abc import abstractmethod
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from pydantic import JsonValue

from slop_code.execution.models import ExecutionError
from slop_code.logging import get_logger

logger = get_logger(__name__)


class InputFileReadError(ExecutionError):
    """Raised when an input file cannot be read."""


class InputFileWriteError(ExecutionError):
    """Raised when an input file cannot be written."""


class Compression(Enum):
    """Supported compression codecs."""

    NONE = "none"
    GZIP = "gzip"
    BZIP2 = "bzip2"


class FileType(Enum):
    """Type of file."""

    TEXT = "text"
    BINARY = "binary"
    JSON = "json"
    JSONL = "jsonl"
    CSV = "csv"
    TSV = "tsv"
    SQLITE = "sqlite"
    PARQUET = "parquet"
    YAML = "yaml"


FileContent = JsonValue | bytes


class FileHandler(ABC):
    """Abstract base class for file handlers."""

    def __init__(
        self,
        compression: Compression = Compression.NONE,
        file_type: FileType = FileType.TEXT,
    ):
        self.compression = compression
        self.file_type = file_type

    @abstractmethod
    def read(self, path: Path) -> FileContent:
        """Read file content and return as JSON value."""

    @abstractmethod
    def write(self, path: Path, content: FileContent) -> None:
        """Write content to file."""


@dataclass(frozen=True)
class FileSignature:
    """Format/compression pair used to select handlers."""

    file_type: FileType
    compression: Compression = Compression.NONE


@contextlib.contextmanager
def open_stream(
    path: Path,
    mode: str,
    compression: Compression,
    force_use_tokens: bool = False,
    **kwargs,
):
    """Return an open stream that respects the requested compression."""
    if force_use_tokens and not mode.endswith("t"):
        mode = f"{mode}t"
    if compression is Compression.GZIP:
        opener = lambda: gzip.open(path, mode, **kwargs)
    elif compression is Compression.BZIP2:
        opener = lambda: bz2.open(path, mode, **kwargs)
    else:
        opener = lambda: path.open(mode, **kwargs)
    with opener() as stream:
        yield stream
