from __future__ import annotations

from pathlib import Path

from slop_code.execution.file_ops.models import Compression
from slop_code.execution.file_ops.models import FileContent
from slop_code.execution.file_ops.models import FileHandler
from slop_code.execution.file_ops.models import FileType
from slop_code.execution.file_ops.models import InputFileReadError
from slop_code.execution.file_ops.models import InputFileWriteError
from slop_code.execution.file_ops.models import open_stream


class YAMLHandler(FileHandler):
    """Handler for YAML files."""

    def read(self, path: Path) -> FileContent:
        """Read YAML file content."""
        import yaml

        try:
            with path.open(encoding="utf-8") as f:
                return yaml.safe_load(f)
        except Exception as e:
            raise InputFileReadError(
                f"Failed to read YAML file {path}: {e}"
            ) from e

    def write(self, path: Path, content: FileContent) -> None:
        """Write content to YAML file."""
        import yaml

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("w", encoding="utf-8") as f:
                yaml.dump(content, f)
        except Exception as e:
            raise InputFileWriteError(
                f"Failed to write YAML file {path}: {e}"
            ) from e


class ParquetHandler(FileHandler):
    """Handler for Parquet files."""

    def read(self, path: Path) -> FileContent:
        """Read Parquet file content."""
        import pyarrow.parquet as pq

        try:
            return pq.read_table(path).to_pylist()
        except Exception as e:
            raise InputFileReadError(
                f"Failed to read Parquet file {path}: {e}"
            ) from e

    def write(self, path: Path, content: FileContent) -> None:
        """Write content to Parquet file."""
        # Strict type checking: Parquet content must be list or
        # dict for pandas DataFrame
        import pyarrow as pa
        import pyarrow.parquet as pq

        if not isinstance(content, list):
            raise InputFileWriteError(
                f"Parquet files require list or dict content for "
                f"got {type(content).__name__}"
            )

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            table = pa.Table.from_pylist(content)
            pq.write_table(
                table, path, compression="zstd", compression_level=10
            )
        except Exception as e:
            raise InputFileWriteError(
                f"Failed to write Parquet file {path}: {e}"
            ) from e


class TextHandler(FileHandler):
    """Handler for text files."""

    def read(self, path: Path) -> FileContent:
        """Read text file content."""
        try:
            with open_stream(
                path, "r", compression=self.compression, encoding="utf-8"
            ) as f:
                result = f.read()
            if self.compression != Compression.NONE and isinstance(
                result, bytes
            ):
                result = result.decode("utf-8")
            return result
        except FileNotFoundError as e:
            raise InputFileReadError(f"File not found: {path}") from e

    def write(self, path: Path, content: FileContent) -> None:
        """Write content to text file."""
        # Strict type checking: text files should contain string content
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            if self.compression != Compression.NONE:
                content = content.decode("utf-8")
        elif self.compression != Compression.NONE:
            if not isinstance(content, str):
                content = str(content).encode("utf-8")
        else:
            content = str(content)
        write_mode = "w" if self.compression == Compression.NONE else "wt"
        with open_stream(path, write_mode, compression=self.compression) as f:
            f.write(content)


class BinaryHandler(FileHandler):
    """Handler for binary files."""

    def read(self, path: Path) -> FileContent:
        """Read binary file content as base64."""
        with open_stream(path, "rb", compression=self.compression) as f:
            return f.read()

    def write(self, path: Path, content: FileContent) -> None:
        """Write content to binary file."""
        import base64

        if not isinstance(content, bytes):
            content = base64.b64encode(str(content).encode("utf-8"))
        with path.open("wb") as f:
            f.write(content)


SETUPS = {
    (YAMLHandler, FileType.YAML): {
        Compression.NONE: {".yaml", ".yml"},
    },
    (ParquetHandler, FileType.PARQUET): {
        Compression.NONE: {".parquet"},
    },
    (TextHandler, FileType.TEXT): {
        Compression.NONE: {
            ".txt",
            ".md",
            ".py",
            ".js",
            ".html",
            ".css",
            ".xml",
        },
        Compression.GZIP: {
            ".txt.gz",
            ".md.gz",
            ".py.gz",
            ".js.gz",
            ".html.gz",
            ".css.gz",
            ".xml.gz",
        },
        Compression.BZIP2: {
            ".txt.bz2",
            ".md.bz2",
            ".py.bz2",
            ".js.bz2",
            ".html.bz2",
            ".css.bz2",
            ".xml.bz2",
        },
    },
    (BinaryHandler, FileType.BINARY): {
        Compression.NONE: {
            ".bin",
            ".tar",
            ".tar.gz",
            ".tgz",
            ".tar.bz2",
            ".tbz2",
        },
    },
}
