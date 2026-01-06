from __future__ import annotations

import contextlib
import csv
import json
import sqlite3
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from slop_code.execution.file_ops.models import Compression
from slop_code.execution.file_ops.models import FileContent
from slop_code.execution.file_ops.models import FileHandler
from slop_code.execution.file_ops.models import FileType
from slop_code.execution.file_ops.models import InputFileReadError
from slop_code.execution.file_ops.models import InputFileWriteError
from slop_code.execution.file_ops.models import open_stream


class StructuredFileHandler(FileHandler):
    """Base handler that provides shared error handling utilities."""

    requires_tokens: bool = False

    @contextlib.contextmanager
    def open(self, path: Path, mode: str, **kwargs):
        """Open a file stream."""
        try:
            with open_stream(
                path,
                mode,
                compression=self.compression,
                force_use_tokens=self.requires_tokens,
                **kwargs,
            ) as stream:
                yield stream
        except Exception as exc:
            if "w" in mode:
                raise InputFileWriteError(
                    f"Failed to write {path}: {exc}"
                ) from exc
            raise InputFileReadError(f"Failed to open {path}: {exc}") from exc


class JSONHandler(StructuredFileHandler):
    """Shared logic for reading and writing JSON payloads."""

    file_type: FileType = FileType.JSON
    requires_tokens = True

    def read(self, path: Path) -> FileContent:
        with self.open(path, "r", encoding="utf-8") as stream:
            return json.load(stream)

    def write(self, path: Path, content: FileContent) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.open(path, "w", encoding="utf-8") as stream:
            if isinstance(content, str):
                stream.write(content)
            else:
                json.dump(content, stream, indent=2, ensure_ascii=False)


class JSONLinesHandler(StructuredFileHandler):
    """Shared logic for JSON lines formats."""

    requires_tokens = True

    def read(self, path: Path) -> FileContent:
        with self.open(path, "rt", encoding="utf-8") as stream:
            items: list[Any] = []
            for raw_line in stream:
                raw_line = raw_line.strip()
                if raw_line:
                    items.append(json.loads(raw_line))
            return items

    def _prepare_items(self, content: FileContent) -> list[Any]:
        if isinstance(content, list):
            items = content
        else:
            items = [content]

        return [json.dumps(item, ensure_ascii=False) for item in items]

    def write(self, path: Path, content: FileContent) -> None:
        items = self._prepare_items(content)
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.open(path, "w", encoding="utf-8") as stream:
            for item in items:
                stream.write(item + "\n")


class DelimitedHandlerBase(StructuredFileHandler):
    """Shared logic for delimited tabular formats."""

    delimiter: str = ","
    requires_tokens = True

    def read(self, path: Path) -> FileContent:
        with self.open(path, "rt", encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream, delimiter=self.delimiter)
            return list(reader)

    def write(self, path: Path, content: FileContent) -> None:
        if not isinstance(content, (list, dict)):
            raise InputFileWriteError(
                f"DelimitedHandlerBase require list of dicts/lists or string-convertible "
                f"content, got {type(content).__name__}"
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.open(path, "wt", encoding="utf-8", newline="") as stream:
            if isinstance(content, list):
                if content:
                    if isinstance(content[0], dict):
                        fieldnames = content[0].keys()
                        writer = csv.DictWriter(
                            stream,
                            fieldnames=fieldnames,
                            delimiter=self.delimiter,
                        )
                        writer.writeheader()
                        writer.writerows(content)
                    else:
                        writer = csv.writer(stream, delimiter=self.delimiter)
                        writer.writerows(content)
                # else: empty list, write nothing
            else:
                stream.write(str(content))


class TSVHandler(DelimitedHandlerBase):
    """Handler for TSV files."""

    delimiter = "\t"


class SQLiteHandler(StructuredFileHandler):
    """Handler for representing SQLite databases as structured JSON payloads."""

    file_type: FileType = FileType.SQLITE

    def read(self, path: Path) -> FileContent:
        if not path.exists():
            raise InputFileReadError(f"SQLite database does not exist: {path}")

        try:
            tables: dict[str, list[dict[str, Any]]] = {}
            with sqlite3.connect(path) as conn:
                conn.row_factory = sqlite3.Row
                for table_name in self._list_tables(conn):
                    query = (
                        f"SELECT * FROM {self._quote_identifier(table_name)}"
                    )
                    cursor = conn.execute(query)
                    tables[table_name] = [
                        dict(row) for row in cursor.fetchall()
                    ]
            return {"tables": tables}
        except sqlite3.Error as exc:
            raise InputFileReadError(
                f"Failed to read SQLite database {path}: {exc}"
            ) from exc

    def write(self, path: Path, content: FileContent) -> None:
        tables = self._normalize_tables(content)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            path.unlink()

        try:
            with sqlite3.connect(path) as conn:
                for table_name, spec in tables.items():
                    self._create_table(
                        conn, table_name, spec["columns"], spec["rows"]
                    )
                conn.commit()
        except sqlite3.Error as exc:
            raise InputFileWriteError(
                f"Failed to write SQLite database {path}: {exc}"
            ) from exc

    def _normalize_tables(
        self, content: FileContent
    ) -> dict[str, dict[str, Any]]:
        if isinstance(content, list):
            raw_tables: Mapping[str, Any] = {"table": content}
        elif isinstance(content, Mapping):
            maybe_tables = content.get("tables")
            if isinstance(maybe_tables, Mapping):
                raw_tables = maybe_tables
            else:
                raw_tables = content
        else:
            raise InputFileWriteError(
                "SQLiteHandler requires list of rows or a mapping of table definitions"
            )

        normalized: dict[str, dict[str, Any]] = {}
        for table_name, table_payload in raw_tables.items():
            if not isinstance(table_name, str):
                raise InputFileWriteError("Table names must be strings")
            normalized[table_name] = self._normalize_table_payload(
                table_name, table_payload
            )

        return normalized

    def _normalize_table_payload(
        self,
        table_name: str,
        payload: Any,
    ) -> dict[str, Any]:
        if isinstance(payload, list):
            rows = [self._normalize_row(table_name, row) for row in payload]
            columns = self._deduce_columns(rows)
        elif isinstance(payload, Mapping):
            raw_rows = payload.get("rows", [])
            if not isinstance(raw_rows, list):
                raise InputFileWriteError(
                    f"Table '{table_name}' rows must be provided as a list"
                )
            rows = [self._normalize_row(table_name, row) for row in raw_rows]
            columns = payload.get("columns")
            if columns is None:
                columns = self._deduce_columns(rows)
            else:
                columns = self._normalize_columns(table_name, columns)
        else:
            raise InputFileWriteError(
                f"Table '{table_name}' must be defined as a list of rows or mapping"
            )

        if not columns:
            raise InputFileWriteError(
                f"Table '{table_name}' must provide columns or at least one populated row"
            )

        return {"columns": columns, "rows": rows}

    def _normalize_columns(self, table_name: str, columns: Any) -> list[str]:
        if not isinstance(columns, list):
            raise InputFileWriteError(
                f"Columns for table '{table_name}' must be provided as a list of strings"
            )
        seen: set[str] = set()
        normalized: list[str] = []
        for column in columns:
            if not isinstance(column, str):
                raise InputFileWriteError(
                    f"Column names for table '{table_name}' must be strings"
                )
            if column not in seen:
                seen.add(column)
                normalized.append(column)
        if not normalized:
            raise InputFileWriteError(
                f"Table '{table_name}' must contain at least one column"
            )
        return normalized

    def _normalize_row(self, table_name: str, row: Any) -> dict[str, Any]:
        if not isinstance(row, Mapping):
            raise InputFileWriteError(
                f"Rows for table '{table_name}' must be mappings of column names to values"
            )
        normalized: dict[str, Any] = {}
        for key, value in row.items():
            if not isinstance(key, str):
                raise InputFileWriteError(
                    f"Column names for table '{table_name}' must be strings"
                )
            normalized[key] = value
        if not normalized:
            raise InputFileWriteError(
                f"Rows for table '{table_name}' must contain at least one column"
            )
        return normalized

    def _deduce_columns(self, rows: list[dict[str, Any]]) -> list[str]:
        ordered_columns: list[str] = []
        seen: set[str] = set()
        for row in rows:
            for column in row.keys():
                if column not in seen:
                    seen.add(column)
                    ordered_columns.append(column)
        return ordered_columns

    def _create_table(
        self,
        conn: sqlite3.Connection,
        table_name: str,
        columns: list[str],
        rows: list[dict[str, Any]],
    ) -> None:
        column_types = {
            column: self._infer_sql_type([row.get(column) for row in rows])
            for column in columns
        }
        columns_sql = ", ".join(
            f"{self._quote_identifier(column)} {column_types[column]}"
            for column in columns
        )
        conn.execute(
            f"DROP TABLE IF EXISTS {self._quote_identifier(table_name)}"
        )
        conn.execute(
            f"CREATE TABLE {self._quote_identifier(table_name)} ({columns_sql})"
        )
        if rows:
            placeholders = ", ".join(["?"] * len(columns))
            insert_sql = (
                f"INSERT INTO {self._quote_identifier(table_name)} "
                f"({', '.join(self._quote_identifier(column) for column in columns)}) "
                f"VALUES ({placeholders})"
            )
            prepared_rows = [
                [self._prepare_value(row.get(column)) for column in columns]
                for row in rows
            ]
            conn.executemany(insert_sql, prepared_rows)

    def _prepare_value(self, value: Any) -> Any:
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, bytearray):
            return bytes(value)
        if isinstance(value, (int, float, str, bytes)) or value is None:
            return value
        if isinstance(value, (list, dict)):
            return json.dumps(value, ensure_ascii=False)
        return str(value)

    def _infer_sql_type(self, values: list[Any]) -> str:
        for value in values:
            if value is None:
                continue
            if isinstance(value, bool):
                return "INTEGER"
            if isinstance(value, int):
                return "INTEGER"
            if isinstance(value, float):
                return "REAL"
            if isinstance(value, (bytes, bytearray)):
                return "BLOB"
            break
        return "TEXT"

    def _list_tables(self, conn: sqlite3.Connection) -> list[str]:
        query = """
        SELECT name
        FROM sqlite_master
        WHERE type='table' AND name NOT LIKE 'sqlite_%'
        ORDER BY name
        """
        cursor = conn.execute(query)
        return [row[0] for row in cursor.fetchall()]

    @staticmethod
    def _quote_identifier(identifier: str) -> str:
        escaped = identifier.replace('"', '""')
        return f'"{escaped}"'


SETUPS = {
    (JSONHandler, FileType.JSON): {
        Compression.GZIP: {".json.gz"},
        Compression.BZIP2: {".json.bz2"},
        Compression.NONE: {".json"},
    },
    (JSONLinesHandler, FileType.JSONL): {
        Compression.GZIP: {".jsonl.gz", ".ndjson.gz"},
        Compression.BZIP2: {".jsonl.bz2", ".ndjson.bz2"},
        Compression.NONE: {".jsonl", ".ndjson"},
    },
    (DelimitedHandlerBase, FileType.CSV): {
        Compression.GZIP: {".csv.gz"},
        Compression.BZIP2: {".csv.bz2"},
        Compression.NONE: {".csv"},
    },
    (TSVHandler, FileType.TSV): {
        Compression.GZIP: {".tsv.gz"},
        Compression.BZIP2: {".tsv.bz2"},
        Compression.NONE: {".tsv"},
    },
    (SQLiteHandler, FileType.SQLITE): {
        Compression.NONE: {".sqlite", ".sqlite3", ".db"},
    },
}
