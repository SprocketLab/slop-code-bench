version: 1.0
last_updated: 2025-11-09
---

# File Operations

`src/slop_code/execution/file_ops/` provides a shared toolkit for reading,
writing, and classifying files that flow through the execution layer. It keeps
adapters, sessions, and runtimes agnostic to individual formats and compression
codecs.

## Core Concepts

- **`FileType` / `Compression`** – Enums describing the logical content type
  (text, json, csv, binary, etc.) and compression codec (none, gzip, bzip2).
- **`FileSignature`** – Pair of `(file_type, compression)` used to look up
  handlers.
- **`FileHandler`** – Abstract base class implementing `read()` and `write()`.
  Concrete handlers live in `raw_files.py` (byte-oriented) and
  `structured_files.py` (JSON/CSV/YAML/etc.).
- **`InputFile`** – Pydantic model representing a file to materialize inside a
  workspace. It stores the destination path, decoded content, type, and
  compression, and exposes helpers for constructing instances from absolute or
  relative paths.

All handlers are registered with a singleton `FileHandlerRegistry`, which maps
extensions such as `.json`, `.csv.gz`, or `.parquet.bz2` to the appropriate
signature.

## Detecting & Reading Files

Use `detect_file_signature(path)` to infer type/compression from filename
suffixes. In most cases you can skip manual reads and let `InputFile.from_path`
handle both detection and decoding:

```python
from pathlib import Path
from slop_code.execution.file_ops import InputFile

file = InputFile.from_path(Path("data/results.jsonl.gz"))
signature = file.file_type, file.compression
payload = file.content  # JSON-compatible structure for structured formats
```

Text files fall back to binary mode if UTF-8 decoding fails, ensuring that
arbitrary files can still be attached to execution requests.

## Materializing Input Files

`Session.materialize_input_files()` delegates to
`materialize_input_files(files, cwd)` which iterates through each `InputFile`
and writes it with the correct handler:

```python
from pathlib import Path
from slop_code.execution.file_ops import InputFile, materialize_input_files

cwd = Path("/tmp/workspace")
files = [
    InputFile.from_path(Path("fixtures/query.sql"), relative_to=Path(".")),
    InputFile.from_absolute(
        path=Path("/data/archive.csv.gz"),
        save_path=Path("incoming/archive.csv.gz"),
    ),
]

materialize_input_files(files, cwd)
```

Handlers create parent directories automatically and preserve compression.

## Structured vs Raw Handlers

- `structured_files.py` targets human-readable formats (JSON, JSONL, CSV, TSV,
  YAML). It round-trips data as JSON-compatible structures, making it easy for
  adapters to inspect inputs or compare outputs in tests.
- `raw_files.py` deals with opaque bytes (binary blobs, SQLite databases,
  archives). Handlers return and accept `bytes` to avoid accidental decoding.

Both modules expose a `SETUPS` mapping used at registry construction time to
associate handlers with file signatures.

## Error Handling

Two custom exceptions help callers distinguish IO failures:

- `InputFileReadError` – raised when reading from disk fails.
- `InputFileWriteError` – raised when writing to the workspace fails.

Runtimes surface these errors via `ExecutionError`, keeping the failure domain
consistent for adapters.

## Extending File Operations

1. Implement a new `FileHandler` subclass that knows how to read/write your
   format. Decide whether it belongs in `structured_files.py` (returns JSON-like
   data) or `raw_files.py` (returns bytes).
2. Add the handler to the module’s `SETUPS` mapping with the appropriate
   `Compression` → `{extensions}` entries.
3. Update documentation/tests if new behaviour requires additional configuration.

Because registration happens at import time, newly declared handlers become
available automatically to `InputFile`, the registry, and session helpers.

