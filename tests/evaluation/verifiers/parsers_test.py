from __future__ import annotations

import textwrap
from pathlib import Path

import pandas as pd
import pytest

from slop_code.evaluation.adapters.models import CaseResult
from slop_code.evaluation.adapters.models import GroupType
from slop_code.evaluation.verifiers import VerifierError
from slop_code.evaluation.verifiers import deepdiff_verify
from slop_code.evaluation.verifiers import matches_regex
from slop_code.evaluation.verifiers.parsers import convert_to_io
from slop_code.evaluation.verifiers.parsers import drop_keys_from_dicts
from slop_code.evaluation.verifiers.parsers import ensure_expected_is_not_none
from slop_code.evaluation.verifiers.parsers import extract_actual_output
from slop_code.evaluation.verifiers.parsers import maybe_split_string
from slop_code.evaluation.verifiers.parsers import parse_csv_content
from slop_code.evaluation.verifiers.parsers import parse_json
from slop_code.evaluation.verifiers.parsers import parse_jsonl
from slop_code.evaluation.verifiers.parsers import parse_markdown_table
from slop_code.evaluation.verifiers.parsers import parse_yaml
from slop_code.evaluation.verifiers.parsers import parse_yaml_file


def make_case_result(
    output: str | None = None,
    id: str = "test_id",
    group_type: GroupType = GroupType.CORE,
    group: str = "core",
    files: dict[str, str | bytes] = {},
) -> CaseResult:
    return CaseResult(
        type="cli",
        status_code=200,
        output=output,
        id=id,
        group_type=group_type,
        group=group,
        files=files,
    )


def test_convert_to_io_handles_text_and_bytes() -> None:
    string_io = convert_to_io("hello")
    assert string_io.getvalue() == "hello"

    bytes_io = convert_to_io(b"bytes")
    assert bytes_io.getvalue() == b"bytes"


def test_convert_to_io_rejects_invalid_type() -> None:
    with pytest.raises(ValueError):
        convert_to_io(123)  # type: ignore[arg-type]


def test_deepdiff_verify_uses_default_configuration() -> None:
    from slop_code.evaluation.verifiers import VerificationResult

    result = deepdiff_verify({"value": 1}, {"value": 1})
    assert isinstance(result, VerificationResult)
    assert result.is_correct


def test_extract_actual_output_splits_and_strips() -> None:
    result = make_case_result(output="header---\nbody\n")
    actual = extract_actual_output(
        result,
        split_output_on="---\n",
        strip=True,
    )
    assert actual == "body"


def test_extract_actual_output_missing_key_raises() -> None:
    result = make_case_result(output="text")
    with pytest.raises(VerifierError):
        extract_actual_output(result, output_key="missing")


def test_extract_actual_output_with_none_returns_none() -> None:
    result = make_case_result(output=None)
    assert extract_actual_output(result) is None


def test_maybe_split_string_supports_delimiter() -> None:
    assert maybe_split_string("a|b|c", split_output_on="|") == "c"


def test_ensure_expected_is_not_none_handles_bytes() -> None:
    assert ensure_expected_is_not_none(b"value") == "value"

    with pytest.raises(VerifierError):
        ensure_expected_is_not_none(None)


def test_parse_markdown_table_returns_dicts() -> None:
    table = textwrap.dedent(
        """
        | Name | Value |
        | ---- | ----- |
        | Foo  | 123   |
        | Bar  | 456   |
        """
    ).strip()
    rows = parse_markdown_table(table)
    assert rows == [
        {"Name": "Foo", "Value": "123"},
        {"Name": "Bar", "Value": "456"},
    ]


def test_drop_keys_from_dicts_filters_requested_keys() -> None:
    data = [{"a": 1, "b": 2}, {"a": 3, "b": 4}]
    assert drop_keys_from_dicts(data, {"b"}) == [{"a": 1}, {"a": 3}]


def test_parse_csv_content_handles_valid_and_invalid_inputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    csv_content = "a,b\n1,2\n3,4\n"
    assert parse_csv_content(csv_content) == [
        {"a": 1, "b": 2},
        {"a": 3, "b": 4},
    ]

    def _raise_empty_data(*_: object, **__: object) -> None:
        raise pd.errors.EmptyDataError("no data")

    monkeypatch.setattr(
        "slop_code.evaluation.verifiers.parsers.pd.read_csv",
        _raise_empty_data,
    )
    assert parse_csv_content("invalid") == []
    assert parse_csv_content(None) == []


def test_parse_yaml_file_reads_from_case_result(tmp_path: Path) -> None:
    content = "key: value"
    case_result = make_case_result(files={"data.yaml": content})
    parsed = parse_yaml_file(case_result, "data.yaml")
    assert parsed == {"key": "value"}

    with pytest.raises(VerifierError):
        parse_yaml_file(case_result, "missing.yaml")

    assert parse_yaml_file(case_result, "missing.yaml", allow_missing=True) == {}


def test_parse_yaml_supports_bytes_and_empty() -> None:
    assert parse_yaml("a: 1") == {"a": 1}
    assert parse_yaml(b"a: 1") == {"a": 1}
    assert parse_yaml("   ") == {}


def test_parse_jsonl_parses_each_line() -> None:
    content = '{"a": 1}\n{"b": 2}\n\n'
    assert parse_jsonl(content) == [{"a": 1}, {"b": 2}]
    assert parse_jsonl(None) == []


def test_parse_json_supports_bytes_and_empty() -> None:
    assert parse_json('{"a": 1}') == {"a": 1}
    assert parse_json(b'{"b": 2}') == {"b": 2}
    assert parse_json("   ") == {}


def test_matches_regex_true_and_false() -> None:
    result_true = matches_regex("hello world", r"hello.*")
    assert result_true.is_correct

    result_false = matches_regex("hello world", r"^world")
    assert not result_false.is_correct
