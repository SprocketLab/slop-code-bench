"""Parser utilities for normalizing and converting verification result data.

This module provides a comprehensive set of parsers for handling various data
formats commonly encountered in verification scenarios, including JSON, YAML,
CSV, markdown tables, and binary data. It ensures consistent data normalization
across different adapter outputs and verification requirements.
"""

from __future__ import annotations

import csv
import io
import json
from typing import Any

import numpy as np
import pandas as pd
import yaml
from pydantic import JsonValue

from slop_code.evaluation.adapters import CaseResult
from slop_code.evaluation.verifiers.loader import VerifierError

ResultAttributeValue = JsonValue | bytes


def convert_to_io(val: str | bytes) -> io.StringIO | io.BytesIO:
    """Convert a string or bytes value to the appropriate IO object.

    Args:
        val: The value to convert (string or bytes)

    Returns:
        StringIO for string values, BytesIO for bytes values

    Raises:
        ValueError: If val is neither string nor bytes
    """
    if isinstance(val, str):
        return io.StringIO(val)
    if isinstance(val, bytes):
        return io.BytesIO(val)
    raise ValueError(f"Invalid value type: {type(val)}")


def ensure_non_null_string(
    val: ResultAttributeValue, allow_empty: bool = False
) -> str:
    if val is None:
        out = ""
    elif isinstance(val, bytes):
        out = val.decode("utf-8")
    else:
        out = str(val)
    if not allow_empty and not out.strip():
        raise VerifierError(f"Required string is empty: {val}")
    return out


def extract_actual_output(
    actual: CaseResult,
    split_output_on: str | None = None,
    split_output_index: int = -1,
    output_key: str = "output",
    decode: str = "utf-8",
    *,
    strip: bool = False,
) -> str | None:
    if not hasattr(actual, output_key):
        raise VerifierError(
            f"Actual output key '{output_key}' not found in {type(actual).__name__}"
        )
    actual_output = getattr(actual, output_key, None)
    if actual_output is None:
        return None
    if isinstance(actual_output, bytes):
        try:
            actual_output = actual_output.decode(decode)
        except UnicodeDecodeError as e:
            raise VerifierError(
                f"Actual output key '{output_key}' is not a valid string: {e}"
            ) from e
    actual_output = maybe_split_string(
        actual_output, split_output_on, split_output_index
    )
    if strip:
        actual_output = actual_output.strip()
    return actual_output


def maybe_split_string(
    content: str | None,
    split_output_on: str | None = None,
    split_output_index: int = -1,
) -> str:
    if content is None:
        return ""
    if split_output_on is None:
        return content
    return content.split(split_output_on)[split_output_index]


def ensure_expected_is_not_none(
    expected: ResultAttributeValue, decode: str = "utf-8"
) -> str:
    if expected is None:
        raise VerifierError(
            "Expected output is required for markdown verification"
        )
    if isinstance(expected, bytes):
        expected = expected.decode(decode)
    else:
        expected = str(expected)
    return expected


def parse_markdown_table(
    content: str | None, allow_errors: bool = False
) -> list[dict[str, Any]]:
    """Parse a markdown table into a list of dictionaries.

    Args:
        content: The markdown table content as string
        split_output_on: The string to split the output on.
        split_output_index: The index of the split output to use

    Returns:
        List of dictionaries representing table rows
    """
    if content is None:
        return []

    lines = content.split("\n")
    if len(lines) == 0:
        return []
    try:
        lines = [line for line in lines if line.strip()]
        dict_reader = csv.DictReader(lines, delimiter="|")
        res = [
            {k.strip(): v.strip() for k, v in row.items() if k.strip()}
            for row in list(dict_reader)[1:]
        ]
        return res
    except Exception as e:
        if not allow_errors:
            raise VerifierError("Could not load markdown table") from e
        return [{"error": "Invalid markdown table"}]


def drop_keys_from_dicts(
    dicts: list[dict[str, Any]], keys: set[str] | None = None
) -> list[dict[str, Any]]:
    if not keys:
        return dicts
    return [{k: v for k, v in d.items() if k not in keys} for d in dicts]


def parse_csv_content(
    content: ResultAttributeValue, allows_error: bool = True
) -> list[dict[str, Any]]:
    """Parse CSV content into a list of dictionaries.

    Args:
        content: The CSV content as string or bytes

    Returns:
        List of dictionaries representing CSV rows, or error dict if parsing fails
    """
    if content is None:
        return []
    if isinstance(content, (list, dict)):
        return content if isinstance(content, list) else [content]
    if not isinstance(content, (str, bytes)):
        raise VerifierError(f"Invalid content type: {type(content)}")
    if isinstance(content, bytes):
        content = content.decode("utf-8")
    try:
        df = pd.read_csv(convert_to_io(content))
        df.replace({np.nan: None}, inplace=True)
        return df.to_dict(orient="records")
    except (pd.errors.EmptyDataError, csv.Error, pd.errors.ParserError) as e:
        if not allows_error:
            raise VerifierError("Could not load csv") from e
        return []


def parse_yaml_file(
    result: CaseResult,
    file_name: str,
    decode: str = "utf-8",
    allow_missing: bool = False,
) -> dict[str, Any]:
    if file_name not in result.files:
        if not allow_missing:
            raise VerifierError(
                f"File '{file_name}' not found in {type(result).__name__}"
            )
        return {}

    return parse_yaml(result.files[file_name], decode)


def parse_yaml(
    content: JsonValue | bytes, decode: str = "utf-8"
) -> dict[str, Any]:
    if content is None:
        return {}
    if isinstance(content, dict):
        return content
    if not isinstance(content, (str, bytes)):
        raise VerifierError(f"Invalid content type: {type(content)}")
    if isinstance(content, bytes):
        content = content.decode(decode)
    if not content.strip():
        return {}
    try:
        return yaml.safe_load(convert_to_io(content))
    except yaml.YAMLError:
        return {}


def parse_jsonl(
    content: ResultAttributeValue, decode: str = "utf-8"
) -> list[dict[str, Any]]:
    if content is None:
        return []
    if isinstance(content, (dict, list)):
        return content if isinstance(content, list) else [content]
    if not isinstance(content, (str, bytes)):
        raise VerifierError(f"Invalid content type: {type(content)}")
    if isinstance(content, bytes):
        content = content.decode(decode)

    out = []
    for line in content.splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def parse_json(
    content: JsonValue | bytes,
    decode: str = "utf-8",
    *,
    allow_invalid: bool = False,
) -> dict[str, Any]:
    if content is None:
        return {}
    if isinstance(content, dict):
        return content
    if not isinstance(content, (str, bytes)):
        if allow_invalid:
            return {"error": "Invalid JSON"}
        raise VerifierError(f"Invalid content type: {type(content)}")
    if isinstance(content, bytes):
        content = content.decode(decode)
    if not content.strip() and content is not None:
        return {}
    try:
        return json.loads(content)
    except json.JSONDecodeError as e:
        if allow_invalid:
            return {"error": "Invalid JSON"}
        raise VerifierError(f"Invalid JSON: {content}") from e
