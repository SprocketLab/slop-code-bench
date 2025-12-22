#!/usr/bin/env python3
"""
Data processing module for handling large datasets.
This module provides utilities for reading, processing, and writing
various data formats including CSV, JSON, and binary files.
"""

import csv
import gzip
import hashlib
import json
import logging
import sys
from pathlib import Path
from typing import Any

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class DataProcessor:
    """Main class for processing data files."""

    def __init__(self, config: dict[str, Any] | None = None):
        """Initialize the data processor with optional configuration."""
        self.config = config or {}
        self.supported_formats = [".csv", ".json", ".txt", ".bin"]
        self.chunk_size = self.config.get("chunk_size", 8192)

    def read_file(self, file_path: str | Path) -> list[dict[str, Any]]:
        """
        Read and parse a data file based on its extension.

        Args:
            file_path: Path to the file to read

        Returns:
            List of dictionaries containing the parsed data

        Raises:
            FileNotFoundError: If the file doesn't exist
            ValueError: If the file format is not supported
        """
        file_path = Path(file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        if file_path.suffix not in self.supported_formats:
            raise ValueError(f"Unsupported format: {file_path.suffix}")

        if file_path.suffix == ".csv":
            return self._read_csv(file_path)
        if file_path.suffix == ".json":
            return self._read_json(file_path)
        return self._read_text(file_path)

    def _read_csv(self, file_path: Path) -> list[dict[str, Any]]:
        """Read CSV file and return list of dictionaries."""
        data = []
        with open(file_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                data.append(dict(row))
        return data

    def _read_json(self, file_path: Path) -> list[dict[str, Any]]:
        """Read JSON file and return list of dictionaries."""
        with open(file_path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        return [data]

    def _read_text(self, file_path: Path) -> list[dict[str, Any]]:
        """Read text file and return as list of line dictionaries."""
        data = []
        with open(file_path, encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                data.append({"line_number": line_num, "content": line.strip()})
        return data

    def write_file(
        self,
        data: list[dict[str, Any]],
        file_path: str | Path,
        format_type: str | None = None,
    ) -> None:
        """
        Write data to a file in the specified format.

        Args:
            data: List of dictionaries to write
            file_path: Output file path
            format_type: Output format (csv, json, txt). If None, inferred from extension
        """
        file_path = Path(file_path)

        if format_type is None:
            format_type = file_path.suffix.lstrip(".")

        if format_type == "csv":
            self._write_csv(data, file_path)
        elif format_type == "json":
            self._write_json(data, file_path)
        else:
            self._write_text(data, file_path)

    def _write_csv(self, data: list[dict[str, Any]], file_path: Path) -> None:
        """Write data to CSV file."""
        if not data:
            return

        with open(file_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=data[0].keys())
            writer.writeheader()
            writer.writerows(data)

    def _write_json(self, data: list[dict[str, Any]], file_path: Path) -> None:
        """Write data to JSON file."""
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def _write_text(self, data: list[dict[str, Any]], file_path: Path) -> None:
        """Write data to text file."""
        with open(file_path, "w", encoding="utf-8") as f:
            for item in data:
                if "content" in item:
                    f.write(f"{item['content']}\n")
                else:
                    f.write(f"{json.dumps(item)}\n")

    def calculate_checksum(self, file_path: str | Path) -> str:
        """Calculate SHA-256 checksum of a file."""
        file_path = Path(file_path)
        hash_sha256 = hashlib.sha256()

        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(self.chunk_size), b""):
                hash_sha256.update(chunk)

        return hash_sha256.hexdigest()

    def compress_file(
        self,
        file_path: str | Path,
        output_path: str | Path | None = None,
    ) -> Path:
        """
        Compress a file using gzip.

        Args:
            file_path: Path to file to compress
            output_path: Output path for compressed file. If None, adds .gz extension

        Returns:
            Path to compressed file
        """
        file_path = Path(file_path)

        if output_path is None:
            output_path = file_path.with_suffix(file_path.suffix + ".gz")
        else:
            output_path = Path(output_path)

        with open(file_path, "rb") as f_in:
            with gzip.open(output_path, "wb") as f_out:
                f_out.writelines(f_in)

        return output_path


def main():
    """Example usage of the DataProcessor class."""
    processor = DataProcessor()

    # Example file processing
    try:
        # This would normally process actual files
        logger.info("DataProcessor initialized successfully")
        logger.info(f"Supported formats: {processor.supported_formats}")
        logger.info(f"Chunk size: {processor.chunk_size}")
    except Exception as e:
        logger.error(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
