# CLI Testing Patterns

Patterns for testing command-line tools with pytest.

## Basic CLI Test

```python
import subprocess


def test_basic(entrypoint_argv):
    """Run CLI and check exit code."""
    result = subprocess.run(
        entrypoint_argv,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
```

## Running with Arguments

### Appending Arguments

```python
def test_with_args(entrypoint_argv):
    """Append arguments to entrypoint."""
    result = subprocess.run(
        entrypoint_argv + ["--verbose", "--format", "json"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
```

### Using tmp_path for Files

```python
def test_with_files(entrypoint_argv, tmp_path):
    """Use temporary files for input/output."""
    # Create input file
    input_file = tmp_path / "input.json"
    input_file.write_text('{"key": "value"}')

    # Create output path
    output_file = tmp_path / "output.json"

    result = subprocess.run(
        entrypoint_argv + [
            "--input", str(input_file),
            "--output", str(output_file),
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert output_file.exists()

    output = json.loads(output_file.read_text())
    assert output["key"] == "value"
```

## Input via stdin

### JSON Input

```python
import json


def test_stdin_json(entrypoint_argv):
    """Send JSON via stdin."""
    input_data = {"name": "Alice", "age": 30}

    result = subprocess.run(
        entrypoint_argv,
        input=json.dumps(input_data),
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert output["name"] == "Alice"
```

### Text Input

```python
def test_stdin_text(entrypoint_argv):
    """Send text via stdin."""
    result = subprocess.run(
        entrypoint_argv,
        input="hello world",
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
```

### Binary Input

```python
def test_stdin_binary(entrypoint_argv):
    """Send binary data via stdin."""
    binary_data = b"\x00\x01\x02\x03"

    result = subprocess.run(
        entrypoint_argv,
        input=binary_data,
        capture_output=True,
    )

    assert result.returncode == 0
```

## Output Validation

### JSON Output

```python
def test_json_output(entrypoint_argv):
    """Validate JSON output."""
    result = subprocess.run(
        entrypoint_argv + ["--format", "json"],
        capture_output=True,
        text=True,
    )

    output = json.loads(result.stdout)
    assert output["status"] == "success"
    assert "data" in output
```

### JSONL Output

```python
def parse_jsonl(text):
    """Parse JSON Lines output."""
    return [
        json.loads(line)
        for line in text.splitlines()
        if line.strip()
    ]


def test_jsonl_output(entrypoint_argv):
    """Validate JSONL output."""
    result = subprocess.run(
        entrypoint_argv,
        capture_output=True,
        text=True,
    )

    events = parse_jsonl(result.stdout)
    assert len(events) == 3
    assert events[0]["type"] == "start"
    assert events[-1]["type"] == "end"
```

### Text Output

```python
def test_text_output(entrypoint_argv):
    """Validate text output."""
    result = subprocess.run(
        entrypoint_argv,
        capture_output=True,
        text=True,
    )

    lines = result.stdout.strip().splitlines()
    assert "Success" in lines[0]
```

### File Output

```python
def test_file_output(entrypoint_argv, tmp_path):
    """Validate file output."""
    output_file = tmp_path / "result.json"

    result = subprocess.run(
        entrypoint_argv + ["--output", str(output_file)],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert output_file.exists()

    data = json.loads(output_file.read_text())
    assert data["status"] == "complete"
```

## Exit Code Validation

### Success Codes

```python
def test_success_exit(entrypoint_argv):
    """Validate success exit code."""
    result = subprocess.run(
        entrypoint_argv,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0


def test_custom_success(entrypoint_argv):
    """Validate custom success codes."""
    result = subprocess.run(
        entrypoint_argv + ["--check"],
        capture_output=True,
        text=True,
    )
    # Some tools use exit code 0 for success, 1 for failure
    assert result.returncode in (0, 1)
```

### Error Codes

```python
@pytest.mark.error
def test_error_exit(entrypoint_argv):
    """Validate error exit code."""
    result = subprocess.run(
        entrypoint_argv + ["--invalid-option"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0


@pytest.mark.error
def test_specific_error_code(entrypoint_argv):
    """Validate specific error code."""
    result = subprocess.run(
        entrypoint_argv,
        input="invalid json",
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1  # Parse error
```

## stderr Validation

```python
@pytest.mark.error
def test_stderr_message(entrypoint_argv):
    """Validate error message in stderr."""
    result = subprocess.run(
        entrypoint_argv,
        input="not valid json",
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "error" in result.stderr.lower()
    assert "json" in result.stderr.lower() or "parse" in result.stderr.lower()
```

## Helper Functions

### Command Runner

```python
def run_cli(entrypoint_argv, input_data=None, args=None, timeout=30):
    """Run CLI with optional input and arguments."""
    cmd = entrypoint_argv.copy()
    if args:
        cmd.extend(args)

    input_str = None
    if input_data is not None:
        if isinstance(input_data, dict):
            input_str = json.dumps(input_data)
        else:
            input_str = str(input_data)

    return subprocess.run(
        cmd,
        input=input_str,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


# Usage
def test_example(entrypoint_argv):
    result = run_cli(entrypoint_argv, {"key": "value"}, ["--verbose"])
    assert result.returncode == 0
```

### Output Parser

```python
def parse_output(result, format="json"):
    """Parse command output."""
    if result.returncode != 0:
        return None

    if format == "json":
        return json.loads(result.stdout)
    elif format == "jsonl":
        return parse_jsonl(result.stdout)
    elif format == "lines":
        return result.stdout.strip().splitlines()
    else:
        return result.stdout


# Usage
def test_with_parser(entrypoint_argv):
    result = run_cli(entrypoint_argv, {"data": "test"})
    output = parse_output(result, "json")
    assert output is not None
    assert output["data"] == "test"
```

## Real Example: file_backup

From the file_backup problem:

```python
"""Tests for file_backup checkpoint_1."""

import json
import subprocess
from pathlib import Path

import pytest
import yaml


def parse_jsonl(text):
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def run_backup(entrypoint_argv, schedule, now, duration, files_dir=None):
    """Run backup scheduler with arguments."""
    args = [
        "--schedule", str(schedule),
        "--now", now,
        "--duration", str(duration),
    ]
    if files_dir:
        args.extend(["--files", str(files_dir)])

    return subprocess.run(
        entrypoint_argv + args,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_daily_schedule(entrypoint_argv, tmp_path):
    """Core: Daily backup schedule works."""
    # Create schedule file
    schedule = tmp_path / "schedule.yaml"
    schedule.write_text(yaml.dump({
        "version": 1,
        "timezone": "UTC",
        "jobs": [{
            "id": "daily-backup",
            "when": {"kind": "daily", "at": "03:00"},
        }]
    }))

    result = run_backup(entrypoint_argv, schedule, "2025-01-01T00:00:00Z", 24)

    assert result.returncode == 0
    events = parse_jsonl(result.stdout)
    assert len(events) == 1
    assert events[0]["job_id"] == "daily-backup"
```

## Best Practices

### Use Timeouts

```python
result = subprocess.run(
    entrypoint_argv,
    capture_output=True,
    text=True,
    timeout=30,  # Always set timeout
)
```

### Capture Both stdout and stderr

```python
result = subprocess.run(
    entrypoint_argv,
    capture_output=True,  # Captures both stdout and stderr
    text=True,
)

# Access both
print(f"stdout: {result.stdout}")
print(f"stderr: {result.stderr}")
```

### Use text=True for String Output

```python
# Good: Get strings
result = subprocess.run(cmd, capture_output=True, text=True)
assert isinstance(result.stdout, str)

# Without text=True: Get bytes
result = subprocess.run(cmd, capture_output=True)
assert isinstance(result.stdout, bytes)
```

### Include Helpful Assertion Messages

```python
def test_example(entrypoint_argv):
    result = run_cli(entrypoint_argv, {"data": "test"})

    assert result.returncode == 0, (
        f"Command failed with exit code {result.returncode}\n"
        f"stderr: {result.stderr}"
    )
```

## Next Steps

- [Stream Testing](stream-testing.md) - stdin/stdout patterns
- [Parametrized Cases](parametrized-cases.md) - External test data
- [conftest Patterns](../pytest/conftest-patterns.md) - Fixtures
