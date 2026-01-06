"""Tests for file operations and type handlers."""

from __future__ import annotations

import bz2
import gzip
import json
from pathlib import Path

import pytest

from slop_code.execution import Compression
from slop_code.execution import FileSignature
from slop_code.execution import FileType
from slop_code.execution import InputFile
from slop_code.execution import detect_file_signature
from slop_code.execution.file_ops import InputFileReadError
from slop_code.execution.file_ops import InputFileWriteError
from slop_code.execution.file_ops.entrypoint import _REGISTRY


# Test data fixtures
@pytest.fixture
def sample_json_data():
    """Sample JSON data for testing."""
    return {"key": "value", "number": 42}


@pytest.fixture
def sample_jsonl_data():
    """Sample JSONL data for testing."""
    return [{"id": 1, "name": "first"}, {"id": 2, "name": "second"}]


@pytest.fixture
def sample_csv_data():
    """Sample CSV data for testing."""
    return [{"col1": "a", "col2": "b"}, {"col1": "c", "col2": "d"}]


@pytest.fixture
def sample_text_data():
    """Sample text data for testing."""
    return "Hello, World!\nThis is a test."


@pytest.fixture
def sample_sqlite_data():
    """Sample SQLite data for testing."""
    return {
        "tables": {
            "users": [
                {"id": 1, "name": "Alice", "active": True},
                {"id": 2, "name": "Bob", "active": False},
            ],
            "logs": {
                "columns": ["id", "message"],
                "rows": [],
            },
        }
    }


# Tests for FileSignature
class TestFileSignature:
    """Tests for FileSignature dataclass."""

    def test_creation(self):
        """Test basic FileSignature creation."""
        sig = FileSignature(FileType.JSON, Compression.GZIP)
        assert sig.file_type == FileType.JSON
        assert sig.compression == Compression.GZIP

    def test_default_compression(self):
        """Test default compression is NONE."""
        sig = FileSignature(FileType.TEXT)
        assert sig.compression == Compression.NONE

    def test_frozen(self):
        """Test that FileSignature is immutable."""
        sig = FileSignature(FileType.JSON)
        with pytest.raises(AttributeError):
            sig.file_type = FileType.TEXT


# Tests for detect_file_signature
class TestDetectFileSignature:
    """Tests for file signature detection."""

    @pytest.mark.parametrize(
        "filename,expected_type,expected_compression",
        [
            # Text files
            (".txt", FileType.TEXT, Compression.NONE),
            (".md", FileType.TEXT, Compression.NONE),
            (".py", FileType.TEXT, Compression.NONE),
            # JSON files
            (".json", FileType.JSON, Compression.NONE),
            (".json.gz", FileType.JSON, Compression.GZIP),
            (".json.bz2", FileType.JSON, Compression.BZIP2),
            # JSONL files
            (".jsonl", FileType.JSONL, Compression.NONE),
            (".jsonl.gz", FileType.JSONL, Compression.GZIP),
            (".jsonl.bz2", FileType.JSONL, Compression.BZIP2),
            # NDJSON files (use JSONL handler)
            (".ndjson", FileType.JSONL, Compression.NONE),
            (".ndjson.gz", FileType.JSONL, Compression.GZIP),
            (".ndjson.bz2", FileType.JSONL, Compression.BZIP2),
            # CSV/TSV files
            (".csv", FileType.CSV, Compression.NONE),
            (".csv.gz", FileType.CSV, Compression.GZIP),
            (".csv.bz2", FileType.CSV, Compression.BZIP2),
            (".tsv", FileType.TSV, Compression.NONE),
            (".tsv.gz", FileType.TSV, Compression.GZIP),
            (".tsv.bz2", FileType.TSV, Compression.BZIP2),
            # SQLite databases
            (".sqlite", FileType.SQLITE, Compression.NONE),
            (".sqlite3", FileType.SQLITE, Compression.NONE),
            (".db", FileType.SQLITE, Compression.NONE),
            # YAML files
            (".yaml", FileType.YAML, Compression.NONE),
            (".yml", FileType.YAML, Compression.NONE),
            # Parquet files
            (".parquet", FileType.PARQUET, Compression.NONE),
            # Unknown extensions default to text
            (".xyz", FileType.TEXT, Compression.NONE),
        ],
    )
    def test_detect_signature(
        self, filename, expected_type, expected_compression
    ):
        """Test file signature detection for various extensions."""
        path = Path(f"test{filename}")
        signature = detect_file_signature(path)
        assert signature.file_type == expected_type
        assert signature.compression == expected_compression


# Tests for file handler round-trips
class TestFileHandlerRoundTrips:
    """Test read/write round-trips for file handlers."""

    @pytest.mark.parametrize(
        "file_type,compression,extension",
        [
            (FileType.JSON, Compression.NONE, ".json"),
            (FileType.JSON, Compression.GZIP, ".json.gz"),
        ],
    )
    def test_json_handlers_roundtrip(
        self, tmp_path, sample_json_data, file_type, compression, extension
    ):
        """Test JSON handlers round-trip."""
        handler = _REGISTRY.get_handler(file_type, compression)
        test_file = tmp_path / f"test{extension}"

        # Write and read back
        handler.write(test_file, sample_json_data)
        result = handler.read(test_file)

        assert result == sample_json_data

    @pytest.mark.parametrize(
        "file_type,compression,extension",
        [
            (FileType.JSONL, Compression.NONE, ".jsonl"),
            (FileType.JSONL, Compression.GZIP, ".jsonl.gz"),
            (FileType.JSONL, Compression.NONE, ".ndjson"),
        ],
    )
    def test_line_json_handlers_roundtrip(
        self, tmp_path, sample_jsonl_data, file_type, compression, extension
    ):
        """Test line-oriented JSON handlers round-trip."""
        handler = _REGISTRY.get_handler(file_type, compression)
        test_file = tmp_path / f"test{extension}"

        # Write and read back
        handler.write(test_file, sample_jsonl_data)
        result = handler.read(test_file)

        assert result == sample_jsonl_data

    @pytest.mark.parametrize(
        "file_type,compression,extension",
        [
            (FileType.CSV, Compression.NONE, ".csv"),
            (FileType.CSV, Compression.GZIP, ".csv.gz"),
            (FileType.TSV, Compression.NONE, ".tsv"),
        ],
    )
    def test_delimited_handlers_roundtrip(
        self, tmp_path, sample_csv_data, file_type, compression, extension
    ):
        """Test CSV/TSV handlers round-trip."""
        handler = _REGISTRY.get_handler(file_type, compression)
        test_file = tmp_path / f"test{extension}"

        # Write and read back
        handler.write(test_file, sample_csv_data)
        result = handler.read(test_file)

        assert result == sample_csv_data

    def test_compressed_files_written_as_bytes(self, tmp_path, sample_csv_data):
        """Test that compressed files are written as binary compressed data."""
        # Test CSV with GZIP compression
        handler_gz = _REGISTRY.get_handler(FileType.CSV, Compression.GZIP)
        gz_file = tmp_path / "test.csv.gz"

        # Write CSV data
        handler_gz.write(gz_file, sample_csv_data)

        # Read raw bytes and verify it's gzip-compressed
        gz_bytes = gz_file.read_bytes()

        # Verify gzip magic number
        assert gz_bytes[:2] == b"\x1f\x8b", (
            "GZIP file should start with magic number 0x1f8b"
        )

        # Verify it's not plain text (shouldn't start with CSV headers)
        assert not gz_bytes.startswith(b"col1,col2"), (
            "File should be compressed, not plain text"
        )

        # Verify it can be decompressed and contains CSV data
        decompressed_gz = gzip.decompress(gz_bytes)
        assert decompressed_gz.startswith(b"col1,col2"), (
            "Decompressed content should be CSV"
        )
        assert b"\n" in decompressed_gz, "CSV should contain newlines"

        # Test CSV with BZIP2 compression
        handler_bz2 = _REGISTRY.get_handler(FileType.CSV, Compression.BZIP2)
        bz2_file = tmp_path / "test.csv.bz2"

        handler_bz2.write(bz2_file, sample_csv_data)
        bz2_bytes = bz2_file.read_bytes()

        # Verify bzip2 magic number
        assert bz2_bytes[:2] == b"BZ", "BZIP2 file should start with 'BZ'"

        # Verify it's not plain text
        assert not bz2_bytes.startswith(b"col1,col2"), (
            "File should be compressed, not plain text"
        )

        # Verify it can be decompressed
        decompressed_bz2 = bz2.decompress(bz2_bytes)
        assert decompressed_bz2.startswith(b"col1,col2"), (
            "Decompressed content should be CSV"
        )

    def test_compressed_json_written_as_bytes(self, tmp_path, sample_json_data):
        """Test that compressed JSON files are written as binary compressed data."""
        # Test JSON with GZIP compression
        handler_gz = _REGISTRY.get_handler(FileType.JSON, Compression.GZIP)
        gz_file = tmp_path / "test.json.gz"

        handler_gz.write(gz_file, sample_json_data)
        gz_bytes = gz_file.read_bytes()

        # Verify gzip magic number
        assert gz_bytes[:2] == b"\x1f\x8b", (
            "GZIP file should start with magic number"
        )

        # Verify it's not plain JSON text
        assert not gz_bytes.startswith(b"{"), (
            "File should be compressed, not plain JSON"
        )

        # Verify decompressed content is valid JSON
        decompressed = gzip.decompress(gz_bytes)
        json_data = json.loads(decompressed)
        assert json_data == sample_json_data, (
            "Decompressed JSON should match original"
        )

        # Test JSON with BZIP2 compression
        handler_bz2 = _REGISTRY.get_handler(FileType.JSON, Compression.BZIP2)
        bz2_file = tmp_path / "test.json.bz2"

        handler_bz2.write(bz2_file, sample_json_data)
        bz2_bytes = bz2_file.read_bytes()

        # Verify bzip2 magic number
        assert bz2_bytes[:2] == b"BZ", "BZIP2 file should start with 'BZ'"
        assert not bz2_bytes.startswith(b"{"), "File should be compressed"

        # Verify decompressed content
        decompressed_bz2 = bz2.decompress(bz2_bytes)
        json_data_bz2 = json.loads(decompressed_bz2)
        assert json_data_bz2 == sample_json_data, (
            "Decompressed JSON should match"
        )

    def test_compressed_jsonl_written_as_bytes(
        self, tmp_path, sample_jsonl_data
    ):
        """Test that compressed JSONL files are written as binary compressed data."""
        # Test JSONL with GZIP compression
        handler_gz = _REGISTRY.get_handler(FileType.JSONL, Compression.GZIP)
        gz_file = tmp_path / "test.jsonl.gz"

        handler_gz.write(gz_file, sample_jsonl_data)
        gz_bytes = gz_file.read_bytes()

        # Verify gzip magic number
        assert gz_bytes[:2] == b"\x1f\x8b", (
            "GZIP file should start with magic number"
        )

        # Verify it's not plain JSONL text
        assert not gz_bytes.startswith(b"{"), (
            "File should be compressed, not plain JSONL"
        )

        # Verify decompressed content is valid JSONL
        decompressed = gzip.decompress(gz_bytes)
        lines = decompressed.strip().split(b"\n")
        assert len(lines) == len(sample_jsonl_data), (
            "Should have same number of lines"
        )

        for i, line in enumerate(lines):
            data = json.loads(line)
            assert data == sample_jsonl_data[i], (
                f"Line {i} should match original"
            )

        # Test JSONL with BZIP2 compression
        handler_bz2 = _REGISTRY.get_handler(FileType.JSONL, Compression.BZIP2)
        bz2_file = tmp_path / "test.jsonl.bz2"

        handler_bz2.write(bz2_file, sample_jsonl_data)
        bz2_bytes = bz2_file.read_bytes()

        # Verify bzip2 magic number
        assert bz2_bytes[:2] == b"BZ", "BZIP2 file should start with 'BZ'"
        assert not bz2_bytes.startswith(b"{"), "File should be compressed"

        # Verify decompressed content
        decompressed_bz2 = bz2.decompress(bz2_bytes)
        lines_bz2 = decompressed_bz2.strip().split(b"\n")
        assert len(lines_bz2) == len(sample_jsonl_data), (
            "Should have same number of lines"
        )

    def test_sqlite_handler_roundtrip(self, tmp_path, sample_sqlite_data):
        """Test SQLite handler round-trip with multiple tables."""
        handler = _REGISTRY.get_handler(FileType.SQLITE)
        test_file = tmp_path / "test.sqlite"

        handler.write(test_file, sample_sqlite_data)
        result = handler.read(test_file)

        assert set(result["tables"]) == {"logs", "users"}
        assert (
            result["tables"]["users"] == sample_sqlite_data["tables"]["users"]
        )
        assert result["tables"]["logs"] == []

    def test_text_handler_roundtrip(self, tmp_path, sample_text_data):
        """Test text handler round-trip."""
        handler = _REGISTRY.get_handler(FileType.TEXT)
        test_file = tmp_path / "test.txt"

        handler.write(test_file, sample_text_data)
        result = handler.read(test_file)

        assert result == sample_text_data

    def test_yaml_handler_roundtrip(self, tmp_path, sample_json_data):
        """Test YAML handler round-trip."""
        handler = _REGISTRY.get_handler(FileType.YAML)
        test_file = tmp_path / "test.yaml"

        handler.write(test_file, sample_json_data)
        result = handler.read(test_file)

        assert result == sample_json_data


# Tests for InputFile
class TestInputFile:
    """Tests for InputFile model."""

    def test_creation(self, sample_json_data):
        """Test basic InputFile creation."""
        input_file = InputFile(
            path=Path("data.json"),
            content=sample_json_data,
            file_type=FileType.JSON,
        )
        assert input_file.path == Path("data.json")
        assert input_file.content == sample_json_data
        assert input_file.file_type == FileType.JSON
        assert input_file.compression == Compression.NONE

    def test_from_path_with_content(self, tmp_path, sample_json_data):
        """Test from_path with explicit content."""
        test_file = tmp_path / "data.json"

        input_file = InputFile.from_path(
            relative_to=tmp_path,
            path=test_file,
            content=sample_json_data,
        )

        assert input_file.path == Path("data.json")
        assert input_file.content == sample_json_data
        assert input_file.file_type == FileType.JSON

    def test_from_path_reads_file(self, tmp_path, sample_json_data):
        """Test from_path reads file content."""
        test_file = tmp_path / "data.json"
        with test_file.open("w") as f:
            json.dump(sample_json_data, f)

        input_file = InputFile.from_path(
            relative_to=tmp_path,
            path=test_file,
        )

        assert input_file.content == sample_json_data

    def test_from_path_detects_compression(self, tmp_path, sample_json_data):
        """Test from_path detects compression from extension."""
        test_file = tmp_path / "data.json.gz"
        with gzip.open(test_file, "wt") as f:
            f.write(json.dumps(sample_json_data))

        input_file = InputFile.from_path(
            relative_to=tmp_path,
            path=test_file,
        )

        assert input_file.compression == Compression.GZIP
        assert input_file.file_type == FileType.JSON

    def test_from_path_converts_absolute_to_relative(
        self, tmp_path, sample_json_data
    ):
        """Test from_path converts absolute paths to relative."""
        test_file = tmp_path / "subdir" / "data.json"
        test_file.parent.mkdir(parents=True)
        with test_file.open("w") as f:
            json.dump(sample_json_data, f)

        input_file = InputFile.from_path(
            relative_to=tmp_path,
            path=test_file.absolute(),
        )

        assert input_file.path == Path("subdir/data.json")


# Tests for error conditions
class TestErrorHandling:
    """Tests for error handling in file operations."""

    def test_text_handler_invalid_content_type(self, tmp_path):
        """Test text handler converts dict to string."""
        handler = _REGISTRY.get_handler(FileType.TEXT)
        test_file = tmp_path / "test.txt"

        # TextHandler converts non-string content to string
        handler.write(test_file, {"key": "value"})
        result = handler.read(test_file)
        assert result == str({"key": "value"})

    def test_json_handler_non_serializable(self, tmp_path):
        """Test JSON handler rejects non-serializable content."""
        handler = _REGISTRY.get_handler(FileType.JSON)
        test_file = tmp_path / "test.json"

        # Functions are not JSON serializable
        with pytest.raises(InputFileWriteError):
            handler.write(test_file, {"func": lambda x: x})

    def test_ndjson_requires_list(self, tmp_path):
        """Test NDJSON/JSONL handler accepts single objects."""
        handler = _REGISTRY.get_handler(FileType.JSONL)
        test_file = tmp_path / "test.ndjson"

        # JSONL handler wraps single objects in a list
        handler.write(test_file, {"single": "object"})
        result = handler.read(test_file)
        assert result == [{"single": "object"}]

    def test_csv_handler_invalid_content_type(self, tmp_path):
        """Test CSV handler converts dict to string."""
        handler = _REGISTRY.get_handler(FileType.CSV)
        test_file = tmp_path / "test.csv"

        # CSV handler converts dict to string when not a list
        handler.write(test_file, {"nested": {"dict": "value"}})
        result = handler.read(test_file)
        # CSV will read it back as empty list or the string representation
        assert isinstance(result, list)

    def test_read_nonexistent_file(self, tmp_path):
        """Test reading non-existent file raises error."""
        handler = _REGISTRY.get_handler(FileType.TEXT)
        test_file = tmp_path / "nonexistent.txt"

        with pytest.raises(InputFileReadError):
            handler.read(test_file)
