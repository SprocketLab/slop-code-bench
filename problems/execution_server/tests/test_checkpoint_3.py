"""Tests for checkpoint_3: Structured file I/O (JSON, YAML, CSV, compression)."""

import json

import pytest

from .assertions import check
from .models import ExecuteRequest


class TestStructuredFiles:
    """Core tests for structured file formats."""

    def test_json_file_object(self, client):
        """JSON file with object value."""
        resp = client.execute(
            ExecuteRequest(
                command="cat doc.json",
                files={"doc.json": {"foo": [1, 2, 3], "bar": {"a": 1}}},
            )
        )
        check(resp).success().exit_code(0)
        output = json.loads(resp.stdout)
        assert output == {"foo": [1, 2, 3], "bar": {"a": 1}}

    def test_json_file_array(self, client):
        """JSON file with array value."""
        resp = client.execute(
            ExecuteRequest(
                command="cat data.json",
                files={"data.json": [1, 2, 3, "four"]},
            )
        )
        check(resp).success()
        output = json.loads(resp.stdout)
        assert output == [1, 2, 3, "four"]

    def test_yaml_file(self, client):
        """YAML file with object value."""
        resp = client.execute(
            ExecuteRequest(
                command="cat config.yaml",
                files={"config.yaml": {"dsn": "sqlite:///db.sqlite", "mode": "full"}},
            )
        )
        check(resp).success()
        assert "dsn:" in resp.stdout or "dsn: " in resp.stdout

    def test_yml_extension(self, client):
        """YAML with .yml extension."""
        resp = client.execute(
            ExecuteRequest(
                command="cat config.yml",
                files={"config.yml": {"key": "value"}},
            )
        )
        check(resp).success()
        assert "key:" in resp.stdout or "key: " in resp.stdout

    def test_jsonl_file(self, client):
        """JSONL file with array of objects."""
        resp = client.execute(
            ExecuteRequest(
                command="wc -l events.jsonl",
                files={"events.jsonl": [{"id": 1, "ok": True}, {"id": 2, "ok": False}]},
            )
        )
        check(resp).success()
        assert "2" in resp.stdout

    def test_ndjson_extension(self, client):
        """NDJSON with .ndjson extension."""
        resp = client.execute(
            ExecuteRequest(
                command="wc -l data.ndjson",
                files={"data.ndjson": [{"a": 1}, {"b": 2}, {"c": 3}]},
            )
        )
        check(resp).success()
        assert "3" in resp.stdout

    def test_csv_file_list_of_dicts(self, client):
        """CSV file from list of dicts."""
        resp = client.execute(
            ExecuteRequest(
                command="cat table.csv",
                files={"table.csv": [{"id": 1}, {"name": "x"}]},
            )
        )
        check(resp).success()
        assert "id" in resp.stdout
        assert "name" in resp.stdout

    def test_csv_file_dict_of_columns(self, client):
        """CSV file from dict of columns."""
        resp = client.execute(
            ExecuteRequest(
                command="cat data.csv",
                files={"data.csv": {"a": [1, 2], "b": [3, 4]}},
            )
        )
        check(resp).success()
        assert "a" in resp.stdout and "b" in resp.stdout

    def test_tsv_file(self, client):
        """TSV file with tab separators."""
        resp = client.execute(
            ExecuteRequest(
                command="cat data.tsv",
                files={"data.tsv": [{"col1": "a", "col2": "b"}]},
            )
        )
        check(resp).success()
        lines = resp.stdout.strip().split("\n")
        assert len(lines) >= 1
        assert "\t" in lines[0] or "col1" in lines[0]

    def test_raw_string_file(self, client):
        """Non-structured extension treated as raw text."""
        resp = client.execute(
            ExecuteRequest(
                command="cat data.txt",
                files={"data.txt": "raw text content"},
            )
        )
        check(resp).success().stdout("raw text content")

    def test_empty_string_file(self, client):
        """Empty string file."""
        resp = client.execute(
            ExecuteRequest(
                command="cat empty.csv",
                files={"empty.csv": ""},
            )
        )
        check(resp).success()


@pytest.mark.functionality
class TestCompression:
    """Tests for compressed file handling."""

    def test_gzip_json(self, client):
        """Gzip-compressed JSON file."""
        resp = client.execute(
            ExecuteRequest(
                command="zcat data.json.gz | head -1",
                files={"data.json.gz": {"compressed": True}},
            )
        )
        check(resp).success()
        output = json.loads(resp.stdout)
        assert output == {"compressed": True}

    def test_gzip_csv(self, client):
        """Gzip-compressed CSV file."""
        resp = client.execute(
            ExecuteRequest(
                command="zcat table.csv.gz",
                files={"table.csv.gz": {"a": [1, 2], "b": [3, 4]}},
            )
        )
        check(resp).success()
        assert "a" in resp.stdout and "b" in resp.stdout

    def test_bzip2_json(self, client):
        """Bzip2-compressed JSON file."""
        resp = client.execute(
            ExecuteRequest(
                command="bzcat data.json.bz2",
                files={"data.json.bz2": {"bz2": True}},
            )
        )
        check(resp).success()
        output = json.loads(resp.stdout)
        assert output == {"bz2": True}


@pytest.mark.error
class TestStructuredFileErrors:
    """Error handling for structured files."""

    def test_double_compression_extension(self, client):
        """Multiple compression extensions should return 400."""
        resp = client.execute_raw(
            {"command": "cat file.gz.bz2", "files": {"file.gz.bz2": {"data": 1}}}
        )
        check(resp).status(400)
