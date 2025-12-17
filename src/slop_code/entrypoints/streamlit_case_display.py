"""Shared Streamlit rendering utilities for displaying test cases.

This module provides rendering functions for displaying test cases in Streamlit
apps. It supports both CLI and API case types, with specialized rendering for
various file formats (JSON, CSV, TSV, YAML, Markdown, Parquet, NDJSON).

The main entry point is `render_case()`, which dispatches to the appropriate
case-specific renderer based on the case type.
"""

from __future__ import annotations

import bz2
import gzip
import hashlib
import io
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pandas as pd
import streamlit as st

from slop_code.evaluation import adapters
from slop_code.execution import InputFile

if TYPE_CHECKING:
    from pydantic import JsonValue


MAX_DISPLAY_LINES = 100


def _render_dataframe_metadata(
    df: pd.DataFrame, total_rows: int | None = None
) -> None:
    """Render metadata expander for a DataFrame.

    Args:
        df: DataFrame to show metadata for
        total_rows: Optional total row count (if showing truncated data)
    """
    with st.expander("📊 Metadata", expanded=False):
        if total_rows is not None:
            st.markdown(f"**Total Rows:** {total_rows}")
            if total_rows > MAX_DISPLAY_LINES:
                st.warning(
                    f"Showing first {MAX_DISPLAY_LINES} of {total_rows} rows"
                )
        types_df = pd.DataFrame(
            {"Column": df.columns, "Type": df.dtypes.astype(str).values}
        )
        st.dataframe(types_df, hide_index=True, use_container_width=True)


def _render_list_as_dataframe(
    content: list, max_lines: int = MAX_DISPLAY_LINES
) -> bool:
    """Render a list as a DataFrame with metadata.

    Args:
        content: List content to render as DataFrame
        max_lines: Maximum number of rows to display

    Returns:
        True if successfully rendered as DataFrame, False if conversion failed
    """
    try:
        if not content:
            st.markdown("_Empty list_")
            return True

        df = pd.DataFrame(content)
        total_rows = len(df)

        _render_dataframe_metadata(df, total_rows)

        # Truncate DataFrame to max_lines rows
        display_df = df.head(max_lines)
        st.dataframe(display_df, width="stretch")

        if total_rows > max_lines:
            st.caption(f"... ({total_rows - max_lines} more rows omitted)")

        return True
    except (ValueError, TypeError):
        # Fall back to JSON rendering if DataFrame conversion fails
        return False


def _render_expected_output(output: str | list | dict | None) -> None:
    """Render expected output with appropriate formatting.

    Args:
        output: Output to render (string, list, dict, or None)
    """
    if isinstance(output, list):
        if not _render_list_as_dataframe(output):
            # Fallback to JSON if DataFrame conversion failed
            st.json(output)
    elif isinstance(output, dict):
        # Metadata expander for dict output
        with st.expander("📊 Metadata", expanded=False):
            st.markdown(f"**Type:** Object with {len(output)} keys")
            st.markdown(f"**Keys:** {', '.join(output.keys())}")
        st.json(output)
    else:
        st.code(truncate_text(output), language="text")


def _dispatch_file_renderer(
    file_path: Path, content: JsonValue | bytes
) -> None:
    """Dispatch to appropriate renderer based on file extension.

    Args:
        file_path: Path to the file (used for extension detection)
        content: File content to render
    """
    if ".jsonl" in file_path.suffix:
        render_ndjson(file_path, content)
    elif ".json" in file_path.suffix:
        render_json(file_path, content)
    elif ".tsv" in file_path.suffix:
        render_tsv(file_path, content)
    elif ".csv" in file_path.suffix:
        render_csv(file_path, content)
    elif ".yml" in file_path.suffix or ".yaml" in file_path.suffix:
        render_yaml(file_path, content)
    elif ".md" in file_path.suffix or ".markdown" in file_path.suffix:
        render_markdown(file_path, content)
    elif ".parquet" in file_path.suffix:
        render_parquet(file_path, content)
    else:
        st.code(
            truncate_text(maybe_decompress(file_path, content)),
            language=file_path.suffix.removeprefix("."),
            wrap_lines=True,
        )


def _render_single_file(
    file_path: Path, content: JsonValue | bytes, expand: bool
) -> None:
    """Render a single file with appropriate formatting.

    Args:
        file_path: Path to the file
        content: File content
        expand: Whether to expand the file expander by default
    """
    with st.expander(str(file_path), expanded=expand):
        if not content:
            st.markdown("EMPTY_FILE")
            return

        if isinstance(content, list):
            # Try to convert to DataFrame if list of dicts
            if _render_list_as_dataframe(content):
                return

        _dispatch_file_renderer(file_path, content)


def truncate_text(text: str | None, max_lines: int = MAX_DISPLAY_LINES) -> str:
    """Truncate text to maximum number of lines.

    Args:
        text: Text to truncate (can be None, str, or other types)
        max_lines: Maximum number of lines to display (default: 50)

    Returns:
        Truncated text with message if content was truncated
    """
    # Handle None and empty values
    if text is None:
        return ""

    if not isinstance(text, str):
        text = str(text)

    # Handle empty strings
    if not text:
        return ""

    lines = text.splitlines(keepends=True)
    if len(lines) <= max_lines:
        return text

    truncated = "".join(lines[:max_lines])
    omitted_count = len(lines) - max_lines
    return f"{truncated}\n... ({omitted_count} more lines omitted)"


def maybe_decompress(
    file_path: Path,
    content: JsonValue | bytes,
) -> str:
    """Decompress content if it's compressed, otherwise return as string.

    Args:
        file_path: Path to the file (used to detect compression from extension)
        content: File content, may be string, bytes, or other JSON value

    Returns:
        String representation of the content
    """
    if isinstance(content, str):
        return content
    if isinstance(content, bytes):
        if file_path.suffix.endswith(".gz"):
            return gzip.decompress(content).decode("utf-8")
        if file_path.suffix.endswith(".bz2"):
            return bz2.decompress(content).decode("utf-8")
        return f"sha256:{hashlib.sha256(content).hexdigest()}"
    # For other JsonValue types, convert to string
    return str(content)


def _to_json_serializable(value: Any) -> JsonValue:
    """Convert arbitrary YAML-loaded content to JSON-serializable data."""

    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return [_to_json_serializable(item) for item in value]
    if isinstance(value, dict):
        return {
            str(key): _to_json_serializable(val) for key, val in value.items()
        }
    return str(value)


def _render_tabular_data(
    file_path: Path,
    content: JsonValue | bytes,
    reader_func: str,
    **reader_kwargs,
) -> None:
    """Render tabular data with metadata.

    Args:
        file_path: Path to the file
        content: File content (will be decompressed if needed)
        reader_func: Name of pandas reader function (e.g., 'read_csv', 'read_json')
        **reader_kwargs: Additional arguments to pass to the reader function
    """
    # Handle bytes content for parquet
    if reader_func == "read_parquet":
        if not isinstance(content, bytes):
            raise ValueError("Parquet files must be bytes")
        df = pd.read_parquet(io.BytesIO(content), **reader_kwargs)
    else:
        # Decompress and convert to StringIO for text-based formats
        content_str = maybe_decompress(file_path, content)
        reader = getattr(pd, reader_func)
        df = reader(io.StringIO(content_str), **reader_kwargs)

    _render_dataframe_metadata(df)
    st.dataframe(df)


def render_json(file_path: Path, content: JsonValue | bytes) -> None:
    """Render JSON content with metadata expander.

    Args:
        file_path: Path to the JSON file
        content: JSON content to render
    """
    try:
        parsed = json.loads(content) if isinstance(content, str) else content

        # Metadata expander
        with st.expander("📊 Metadata", expanded=False):
            if isinstance(parsed, list):
                st.markdown(f"**Type:** Array with {len(parsed)} items")
                if parsed and isinstance(parsed[0], dict):
                    st.markdown(f"**Keys:** {', '.join(parsed[0].keys())}")
            elif isinstance(parsed, dict):
                st.markdown(f"**Type:** Object with {len(parsed)} keys")
                st.markdown(f"**Keys:** {', '.join(parsed.keys())}")
            else:
                st.markdown(f"**Type:** {type(parsed).__name__}")

        st.json(parsed)
    except json.JSONDecodeError:
        st.code(
            truncate_text("Invalid JSON\n" + content),
            language="text",
            wrap_lines=True,
        )


def render_tsv(file_path: Path, content: JsonValue | bytes) -> None:
    """Render TSV content as a dataframe with metadata.

    Args:
        file_path: Path to the TSV file
        content: TSV content to render
    """
    _render_tabular_data(file_path, content, "read_csv", sep="\t")


def render_csv(file_path: Path, content: JsonValue | bytes) -> None:
    """Render CSV content as a dataframe with metadata.

    Args:
        file_path: Path to the CSV file
        content: CSV content to render
    """
    _render_tabular_data(file_path, content, "read_csv")


def render_ndjson(file_path: Path, content: JsonValue | bytes) -> None:
    """Render NDJSON content as a dataframe with metadata.

    Args:
        file_path: Path to the NDJSON file
        content: NDJSON content to render
    """
    _render_tabular_data(file_path, content, "read_json", lines=True)


def render_parquet(file_path: Path, content: JsonValue | bytes) -> None:
    """Render Parquet content as a dataframe with metadata.

    Args:
        file_path: Path to the Parquet file
        content: Parquet content (must be bytes)

    Raises:
        ValueError: If content is not bytes
    """
    _render_tabular_data(file_path, content, "read_parquet")


def render_markdown(file_path: Path, content: JsonValue | bytes) -> None:
    """Render Markdown content with metadata.

    Args:
        file_path: Path to the Markdown file
        content: Markdown content to render
    """
    content = maybe_decompress(file_path, content)

    # Metadata expander
    with st.expander("📊 Metadata", expanded=False):
        lines = content.split("\n")
        st.markdown(f"**Lines:** {len(lines)}")
        st.markdown(f"**Characters:** {len(content)}")

    st.markdown(content)


def render_yaml(file_path: Path, content: JsonValue | bytes) -> None:
    """Render YAML content with metadata.

    Args:
        file_path: Path to the YAML file
        content: YAML content to render
    """
    import yaml

    parse_error = False
    if isinstance(content, (dict, list)):
        parsed_content: Any = content
        yaml_text = yaml.dump(content, sort_keys=True)
    else:
        yaml_text = maybe_decompress(file_path, content)
        try:
            parsed_content = yaml.safe_load(yaml_text)
        except yaml.YAMLError:
            parse_error = True
            parsed_content = None

    # Metadata expander
    with st.expander("📊 Metadata", expanded=False):
        lines = yaml_text.split("\n")
        st.markdown(f"**Lines:** {len(lines)}")
        if isinstance(parsed_content, dict):
            st.markdown(f"**Top-level keys:** {len(parsed_content)}")
        elif isinstance(parsed_content, list):
            st.markdown(f"**Items:** {len(parsed_content)}")

    if parse_error:
        st.code(truncate_text(yaml_text), language="yaml", wrap_lines=True)
        return

    st.json(_to_json_serializable(parsed_content))


def write_loaded_files(
    files: dict[str, JsonValue | bytes] | list[InputFile],
    *,
    expand_files: bool = False,
    binary_files: dict[str, bytes] | None = None,
) -> None:
    """Render loaded files with appropriate formatting.

    Supports both legacy dict format and new list[InputFile] format.
    Automatically detects file types and uses specialized renderers.

    Args:
        files: Files to render (dict or list of InputFile)
        expand_files: Whether to expand file expanders by default
        binary_files: Optional dict of binary files to render separately
    """
    # Handle both dict (legacy) and list[InputFile] (new) formats
    if isinstance(files, dict):
        # Legacy format - dict[str, JsonValue | bytes]
        for file_name, content in sorted(files.items()):
            _render_single_file(Path(file_name), content, expand_files)
    else:
        # New format - list[InputFile]
        for input_file in sorted(files, key=lambda x: x.path):
            _render_single_file(
                Path(input_file.path), input_file.content, expand_files
            )

    if not binary_files:
        return

    for file_name, blob in sorted(binary_files.items(), key=lambda x: x[0]):
        file = Path(file_name)
        with st.expander(f"{file.name} (binary)", expanded=False):
            st.code(f"{len(blob)} bytes", language="text")


def render_cli_case(
    case: adapters.CLICase, expected: adapters.CLIResult
) -> None:
    """Render a CLI case with inputs and expected outputs.

    Args:
        case: CLI test case with arguments and inputs
        expected: Expected CLI execution result
    """
    with st.container():
        st.header("Meta", divider=True)
        input_col, output_col = st.columns(2, border=True)
        with input_col:
            st.header("Inputs", divider=True)
            with st.expander("Arguments", expanded=True):
                st.code(json.dumps(case.arguments, indent=2), language="bash")

            with st.expander("STDIN", expanded=True):
                st.code(truncate_text(case.stdin), language="text")
            write_loaded_files(case.input_files, expand_files=True)

        with output_col:
            st.header(f"Expected - Code: {expected.status_code}", divider=True)
            with st.expander("Output", expanded=True):
                _render_expected_output(expected.output)
            with st.expander("STDERR", expanded=True):
                st.code(truncate_text(expected.stderr), language="text")

            expected_files = expected.files or {}
            write_loaded_files(
                expected_files,
                expand_files=True,
                binary_files={
                    name: content
                    for name, content in expected_files.items()
                    if isinstance(content, (bytes, bytearray))
                },
            )


def render_api_case(
    case: adapters.APICase, expected: adapters.APIResult
) -> None:
    """Render an API case with request details and expected response.

    Args:
        case: API test case with request details
        expected: Expected API response
    """
    with st.container(width="stretch"):
        st.header("Meta", divider=True)

        url_display = str(expected.resource_path or case.path or "/")
        input_col, output_col = st.columns(2, border=True)
        with input_col:
            st.header("Request", divider=True)
            st.markdown(f"**Endpoint:** `{case.method.upper()} {url_display}`")

            with st.expander("Meta", expanded=False):
                order_display = case.order if case.order >= 0 else "N/A"
                timeout_display = (
                    f"{case.timeout_s}s" if case.timeout_s else "Default"
                )
                st.markdown(f"**Order:** {order_display}")
                st.markdown(f"**Retries:** {case.retries}")
                st.markdown(f"**Timeout:** {timeout_display}")

            # Query parameters
            with st.expander("Query Parameters", expanded=bool(case.query)):
                if case.query:
                    st.json(case.query)
                else:
                    st.markdown("_No query parameters_")

            # Headers
            with st.expander("Headers", expanded=bool(case.headers)):
                if case.headers:
                    st.json(case.headers)
                else:
                    st.markdown("_No headers_")

            # Body
            with st.expander("Body", expanded=bool(case.body)):
                if case.body:
                    if isinstance(case.body, (dict, list)):
                        st.json(case.body)
                    else:
                        st.code(truncate_text(str(case.body)), language="text")
                else:
                    st.markdown("_No body_")

            write_loaded_files(case.input_files, expand_files=True)

        with output_col:
            st.header(f"Expected - Code: {expected.status_code}", divider=True)

            # Expected headers
            if hasattr(expected, "headers") and expected.headers:
                with st.expander("Expected Headers", expanded=False):
                    st.json(expected.headers)

            # Expected output
            with st.expander("Output", expanded=True):
                _render_expected_output(expected.output)

            with st.expander("STDERR", expanded=True):
                st.code(truncate_text(expected.stderr), language="text")

            expected_files = expected.files or {}
            write_loaded_files(
                expected_files,
                expand_files=True,
                binary_files={
                    name: content
                    for name, content in expected_files.items()
                    if isinstance(content, (bytes, bytearray))
                },
            )


def render_case(
    case_bundle: tuple[adapters.BaseCase, adapters.CaseResult],
) -> None:
    """Render a case based on its type.

    Dispatches to the appropriate case-specific renderer.

    Args:
        case_bundle: Tuple of (case, expected_result)

    Raises:
        ValueError: If the case type is unknown
    """
    case, expected = case_bundle
    if isinstance(case, adapters.APICase):
        return render_api_case(case, cast("adapters.APIResult", expected))
    if isinstance(case, adapters.CLICase):
        return render_cli_case(case, cast("adapters.CLIResult", expected))
    raise ValueError(f"Unknown case type: {type(case)}")
