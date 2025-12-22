# Stream Testing Patterns

Patterns for testing stdin/stdout stream-based tools.

## Basic Stream Test

```python
import subprocess


def test_stream(entrypoint_argv):
    """Basic stdin/stdout test."""
    result = subprocess.run(
        entrypoint_argv,
        input="input data",
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert result.stdout == "expected output"
```

## JSON Streams

### Single JSON Object

```python
import json


def test_json_transform(entrypoint_argv):
    """Transform JSON input to output."""
    input_data = {"name": "Alice", "age": 30}

    result = subprocess.run(
        entrypoint_argv,
        input=json.dumps(input_data),
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert output["name"] == "alice"  # Transformed
```

### JSON Lines (JSONL)

```python
def test_jsonl_processing(entrypoint_argv):
    """Process JSONL input."""
    input_lines = [
        {"id": 1, "value": "a"},
        {"id": 2, "value": "b"},
        {"id": 3, "value": "c"},
    ]
    input_str = "\n".join(json.dumps(obj) for obj in input_lines)

    result = subprocess.run(
        entrypoint_argv,
        input=input_str,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0

    output_lines = [
        json.loads(line)
        for line in result.stdout.splitlines()
        if line.strip()
    ]

    assert len(output_lines) == 3
    assert all(line["processed"] for line in output_lines)
```

## Line-Based Processing

### Text Lines

```python
def test_line_processing(entrypoint_argv):
    """Process text line by line."""
    input_lines = ["apple", "banana", "cherry"]

    result = subprocess.run(
        entrypoint_argv,
        input="\n".join(input_lines),
        capture_output=True,
        text=True,
    )

    output_lines = result.stdout.strip().splitlines()
    assert output_lines == ["APPLE", "BANANA", "CHERRY"]
```

### CSV Lines

```python
def test_csv_processing(entrypoint_argv):
    """Process CSV input."""
    csv_input = """name,age,city
Alice,30,NYC
Bob,25,LA
Charlie,35,Chicago"""

    result = subprocess.run(
        entrypoint_argv,
        input=csv_input,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    lines = result.stdout.strip().splitlines()
    assert len(lines) == 4  # Header + 3 data rows
```

## Event Streams

### Processing Events

```python
def parse_jsonl(text):
    """Parse JSONL output."""
    return [
        json.loads(line)
        for line in text.splitlines()
        if line.strip()
    ]


def test_event_stream(entrypoint_argv):
    """Verify event stream output."""
    input_data = {"action": "process", "items": [1, 2, 3]}

    result = subprocess.run(
        entrypoint_argv,
        input=json.dumps(input_data),
        capture_output=True,
        text=True,
    )

    events = parse_jsonl(result.stdout)

    # Verify event sequence
    assert events[0]["type"] == "start"
    assert events[-1]["type"] == "end"

    # Verify progress events
    progress_events = [e for e in events if e["type"] == "progress"]
    assert len(progress_events) == 3
```

### Event Ordering

```python
def test_event_order(entrypoint_argv):
    """Verify events are in correct order."""
    result = subprocess.run(
        entrypoint_argv,
        input='{"data": "test"}',
        capture_output=True,
        text=True,
    )

    events = parse_jsonl(result.stdout)
    types = [e["type"] for e in events]

    # Verify order
    assert types[0] == "init"
    assert types[-1] == "complete"

    # Verify all processing happens between init and complete
    processing_indices = [i for i, t in enumerate(types) if t == "process"]
    assert all(0 < i < len(types) - 1 for i in processing_indices)
```

## Real Example: etl_pipeline

From the etl_pipeline problem:

```python
"""Tests for etl_pipeline."""

import json
import subprocess

import pytest


def run_etl(entrypoint_argv, input_data, args=None):
    """Run ETL pipeline with input."""
    cmd = entrypoint_argv.copy()
    if args:
        cmd.extend(args)

    return subprocess.run(
        cmd,
        input=json.dumps(input_data),
        capture_output=True,
        text=True,
        timeout=30,
    )


# Core tests
def test_passthrough(entrypoint_argv):
    """Core: Data passes through unchanged."""
    input_data = {"key": "value", "number": 42}
    result = run_etl(entrypoint_argv, input_data)

    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert output == input_data


def test_transform(entrypoint_argv):
    """Core: Apply transformation."""
    input_data = {"name": "Alice", "age": 30}
    result = run_etl(entrypoint_argv, input_data, ["--uppercase-keys"])

    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert output == {"NAME": "Alice", "AGE": 30}


# Functionality tests
@pytest.mark.functionality
def test_filter(entrypoint_argv):
    """Functionality: Filter fields."""
    input_data = {"keep": "yes", "remove": "no"}
    result = run_etl(entrypoint_argv, input_data, ["--only", "keep"])

    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert output == {"keep": "yes"}


# Error tests
@pytest.mark.error
def test_invalid_json(entrypoint_argv):
    """Error: Invalid JSON input."""
    result = subprocess.run(
        entrypoint_argv,
        input="not valid json",
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
```

## Helper Functions

### Stream Runner

```python
def run_stream(entrypoint_argv, input_data, timeout=30):
    """Run command with stream input/output."""
    if isinstance(input_data, dict):
        input_str = json.dumps(input_data)
    elif isinstance(input_data, list):
        # Assume list of dicts for JSONL
        input_str = "\n".join(json.dumps(obj) for obj in input_data)
    else:
        input_str = str(input_data)

    return subprocess.run(
        entrypoint_argv,
        input=input_str,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
```

### Output Parsers

```python
def parse_json_output(result):
    """Parse JSON output, return None on error."""
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def parse_jsonl_output(result):
    """Parse JSONL output."""
    if result.returncode != 0:
        return None

    return [
        json.loads(line)
        for line in result.stdout.splitlines()
        if line.strip()
    ]
```

## Validation Patterns

### Exact Match

```python
def test_exact_output(entrypoint_argv):
    """Verify exact output match."""
    result = run_stream(entrypoint_argv, {"in": "data"})
    output = json.loads(result.stdout)
    assert output == {"out": "data"}
```

### Subset Match

```python
def test_contains_fields(entrypoint_argv):
    """Verify output contains required fields."""
    result = run_stream(entrypoint_argv, {"in": "data"})
    output = json.loads(result.stdout)

    # Required fields
    assert "status" in output
    assert "result" in output

    # Check values
    assert output["status"] == "success"
```

### Schema Validation

```python
import jsonschema


def test_output_schema(entrypoint_argv):
    """Verify output matches schema."""
    schema = {
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "count": {"type": "integer", "minimum": 0},
            "items": {"type": "array"},
        },
        "required": ["id", "count"],
    }

    result = run_stream(entrypoint_argv, {"data": "test"})
    output = json.loads(result.stdout)

    jsonschema.validate(output, schema)
```

## Best Practices

### Handle Large Streams

```python
def test_large_stream(entrypoint_argv):
    """Test with large input."""
    # Generate large input
    large_input = [{"id": i, "data": "x" * 1000} for i in range(1000)]

    result = subprocess.run(
        entrypoint_argv,
        input="\n".join(json.dumps(obj) for obj in large_input),
        capture_output=True,
        text=True,
        timeout=60,  # Longer timeout for large data
    )

    assert result.returncode == 0
```

### Test Empty Input

```python
@pytest.mark.error
def test_empty_input(entrypoint_argv):
    """Handle empty input gracefully."""
    result = subprocess.run(
        entrypoint_argv,
        input="",
        capture_output=True,
        text=True,
    )

    # Either error or empty output
    assert result.returncode in (0, 1)
```

### Verify No Extra Output

```python
def test_clean_output(entrypoint_argv):
    """No debug or log output mixed in."""
    result = run_stream(entrypoint_argv, {"data": "test"})

    # Should be valid JSON, no extra lines
    lines = result.stdout.strip().splitlines()
    for line in lines:
        json.loads(line)  # Each line must be valid JSON

    # stderr should be empty for success
    assert result.stderr == "" or result.returncode != 0
```

## Next Steps

- [CLI Testing](cli-testing.md) - CLI patterns
- [Parametrized Cases](parametrized-cases.md) - External test data
- [Examples](../examples/) - Real problem examples
