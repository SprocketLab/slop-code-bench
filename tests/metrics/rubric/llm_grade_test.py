"""Tests for LLM grading utilities."""

from __future__ import annotations

from slop_code.metrics.rubric.llm_grade import _parse_multi_file_response


class TestParseMultiFileResponse:
    """Tests for _parse_multi_file_response function."""

    def test_parses_single_file_block(self) -> None:
        """Parse a single file block."""
        response = """
=== FILE: src/main.py ===
```json
[
  {"criteria": "spelling", "start": 1, "end": 1, "explanation": "test", "confidence": 5}
]
```
=== END FILE ===
"""
        result = _parse_multi_file_response(response)

        assert len(result) == 1
        assert result[0]["file_name"] == "src/main.py"
        assert result[0]["criteria"] == "spelling"
        assert result[0]["start"] == 1

    def test_parses_multiple_file_blocks(self) -> None:
        """Parse multiple file blocks."""
        response = """
=== FILE: src/main.py ===
```json
[
  {"criteria": "spelling", "start": 1, "end": 1, "explanation": "typo", "confidence": 5}
]
```
=== END FILE ===

=== FILE: src/utils.py ===
```json
[
  {"criteria": "too_long", "start": 10, "end": 100, "explanation": "long", "confidence": 4}
]
```
=== END FILE ===
"""
        result = _parse_multi_file_response(response)

        assert len(result) == 2
        assert result[0]["file_name"] == "src/main.py"
        assert result[0]["criteria"] == "spelling"
        assert result[1]["file_name"] == "src/utils.py"
        assert result[1]["criteria"] == "too_long"

    def test_handles_empty_json_array(self) -> None:
        """Handle files with no issues (empty array)."""
        response = """
=== FILE: src/clean.py ===
```json
[]
```
=== END FILE ===
"""
        result = _parse_multi_file_response(response)

        assert len(result) == 0

    def test_handles_multiple_grades_per_file(self) -> None:
        """Handle multiple grades in one file block."""
        response = """
=== FILE: src/main.py ===
```json
[
  {"criteria": "spelling", "start": 1, "end": 1, "explanation": "a", "confidence": 5},
  {"criteria": "too_long", "start": 10, "end": 50, "explanation": "b", "confidence": 4}
]
```
=== END FILE ===
"""
        result = _parse_multi_file_response(response)

        assert len(result) == 2
        assert all(g["file_name"] == "src/main.py" for g in result)
        assert result[0]["criteria"] == "spelling"
        assert result[1]["criteria"] == "too_long"

    def test_handles_occurrences_format(self) -> None:
        """Handle nested occurrences format (not flattened by parser)."""
        response = """
=== FILE: src/main.py ===
```json
[
  {
    "criteria": "spelling",
    "occurrences": [
      {"start": 1, "end": 1, "explanation": "a", "confidence": 5},
      {"start": 5, "end": 5, "explanation": "b", "confidence": 4}
    ]
  }
]
```
=== END FILE ===
"""
        result = _parse_multi_file_response(response)

        # Parser doesn't flatten occurrences - returns the structure as-is
        assert len(result) == 1
        assert result[0]["file_name"] == "src/main.py"
        assert result[0]["criteria"] == "spelling"
        assert "occurrences" in result[0]
        assert len(result[0]["occurrences"]) == 2

    def test_handles_whitespace_in_markers(self) -> None:
        """Handle whitespace variations in markers."""
        response = """
===  FILE:  src/main.py  ===
```json
[{"criteria": "test", "start": 1, "end": 1, "explanation": "x", "confidence": 5}]
```
===  END FILE  ===
"""
        result = _parse_multi_file_response(response)

        assert len(result) == 1
        assert result[0]["file_name"] == "src/main.py"

    def test_returns_none_for_no_blocks(self) -> None:
        """Return None when no file blocks found."""
        response = "Just some text without any file blocks"

        result = _parse_multi_file_response(response)

        assert result is None

    def test_skips_invalid_json_blocks(self) -> None:
        """Skip blocks with invalid JSON."""
        response = """
=== FILE: src/valid.py ===
```json
[{"criteria": "test", "start": 1, "end": 1, "explanation": "x", "confidence": 5}]
```
=== END FILE ===

=== FILE: src/invalid.py ===
```json
[invalid json here
```
=== END FILE ===
"""
        result = _parse_multi_file_response(response)

        assert len(result) == 1
        assert result[0]["file_name"] == "src/valid.py"
