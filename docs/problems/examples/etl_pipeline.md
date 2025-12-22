# Example: etl_pipeline

Complete walkthrough of the `etl_pipeline` problem, a stream-based data transformation tool.

## Problem Overview

**What it tests**: A CLI ETL (Extract, Transform, Load) tool that:
1. Reads JSON from stdin
2. Applies transformations
3. Outputs JSON to stdout
4. Handles errors gracefully

**Key patterns demonstrated**:
- Stream-based stdin/stdout testing
- Inline test definitions (no external files)
- All marker types in one file
- Simple, focused tests

## Directory Structure

```
problems/etl_pipeline/
├── config.yaml
├── checkpoint_1.md
├── checkpoint_2.md
└── tests/
    ├── conftest.py
    ├── test_checkpoint_1.py
    └── test_checkpoint_2.py
```

## Configuration

### config.yaml

```yaml
version: 1
name: etl_pipeline
description: CLI ETL tool for JSON data transformation
category: data-transformation
difficulty: Easy
entry_file: etl.py
timeout: 10

tags:
  - cli
  - json
  - stream
  - data-transformation

checkpoints:
  checkpoint_1:
    version: 1
    order: 1
    state: Core Tests

  checkpoint_2:
    version: 1
    order: 2
    state: Core Tests
    include_prior_tests: true
```

## Test Implementation

### conftest.py (Minimal)

```python
"""Pytest configuration for etl_pipeline evaluation."""

import shlex

import pytest


def pytest_addoption(parser):
    parser.addoption("--entrypoint", required=True)
    parser.addoption("--checkpoint", required=True)


@pytest.fixture(scope="session")
def entrypoint_argv(request):
    return shlex.split(request.config.getoption("--entrypoint"))


@pytest.fixture(scope="session")
def checkpoint_name(request):
    return request.config.getoption("--checkpoint")
```

### test_checkpoint_1.py (Inline Tests)

```python
"""Tests for checkpoint_1: Basic ETL operations."""

import json
import subprocess

import pytest


def run_etl(entrypoint_argv, input_data, args=None):
    """Run ETL pipeline with input."""
    cmd = entrypoint_argv.copy()
    if args:
        cmd.extend(args)

    input_str = json.dumps(input_data) if isinstance(input_data, dict) else input_data

    return subprocess.run(
        cmd,
        input=input_str,
        capture_output=True,
        text=True,
        timeout=10,
    )


# =============================================================================
# Core Tests (unmarked - must pass)
# =============================================================================


def test_passthrough(entrypoint_argv):
    """Core: Data passes through unchanged."""
    input_data = {"name": "Alice", "age": 30}

    result = run_etl(entrypoint_argv, input_data)

    assert result.returncode == 0, f"Failed: {result.stderr}"
    output = json.loads(result.stdout)
    assert output == input_data


def test_nested_object(entrypoint_argv):
    """Core: Nested objects preserved."""
    input_data = {
        "user": {
            "name": "Bob",
            "address": {
                "city": "NYC",
                "zip": "10001"
            }
        }
    }

    result = run_etl(entrypoint_argv, input_data)

    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert output == input_data


def test_array_values(entrypoint_argv):
    """Core: Array values preserved."""
    input_data = {"items": [1, 2, 3], "tags": ["a", "b"]}

    result = run_etl(entrypoint_argv, input_data)

    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert output == input_data


def test_empty_object(entrypoint_argv):
    """Core: Empty object handled."""
    result = run_etl(entrypoint_argv, {})

    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert output == {}


def test_rename_field(entrypoint_argv):
    """Core: Rename field with --rename."""
    input_data = {"old_name": "value"}

    result = run_etl(entrypoint_argv, input_data, ["--rename", "old_name", "new_name"])

    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert output == {"new_name": "value"}


# =============================================================================
# Functionality Tests (nice to have)
# =============================================================================


@pytest.mark.functionality
def test_filter_fields(entrypoint_argv):
    """Functionality: Filter to specific fields."""
    input_data = {"keep": "yes", "remove": "no", "also_remove": "maybe"}

    result = run_etl(entrypoint_argv, input_data, ["--only", "keep"])

    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert output == {"keep": "yes"}


@pytest.mark.functionality
def test_exclude_fields(entrypoint_argv):
    """Functionality: Exclude specific fields."""
    input_data = {"keep1": 1, "keep2": 2, "remove": 3}

    result = run_etl(entrypoint_argv, input_data, ["--exclude", "remove"])

    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert output == {"keep1": 1, "keep2": 2}


@pytest.mark.functionality
def test_add_field(entrypoint_argv):
    """Functionality: Add new field."""
    input_data = {"existing": "value"}

    result = run_etl(entrypoint_argv, input_data, ["--add", "new_field", "new_value"])

    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert output == {"existing": "value", "new_field": "new_value"}


# =============================================================================
# Error Tests (error handling)
# =============================================================================


@pytest.mark.error
def test_invalid_json(entrypoint_argv):
    """Error: Invalid JSON input returns error."""
    result = subprocess.run(
        entrypoint_argv,
        input="not valid json",
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1


@pytest.mark.error
def test_empty_input(entrypoint_argv):
    """Error: Empty input returns error."""
    result = subprocess.run(
        entrypoint_argv,
        input="",
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1


@pytest.mark.error
def test_rename_missing_field(entrypoint_argv):
    """Error: Rename non-existent field."""
    input_data = {"exists": "value"}

    result = run_etl(entrypoint_argv, input_data, ["--rename", "missing", "new"])

    # Should either error or pass through unchanged
    assert result.returncode in (0, 1)
```

## Key Patterns

### Pattern 1: Inline Test Data

All test data is defined directly in Python:

```python
def test_passthrough(entrypoint_argv):
    input_data = {"name": "Alice", "age": 30}  # Inline data
    result = run_etl(entrypoint_argv, input_data)
    output = json.loads(result.stdout)
    assert output == input_data  # Inline expected
```

**When to use**: Small test suites, simple data structures.

### Pattern 2: Simple Helper Function

```python
def run_etl(entrypoint_argv, input_data, args=None):
    """Run ETL pipeline with input."""
    cmd = entrypoint_argv.copy()
    if args:
        cmd.extend(args)

    input_str = json.dumps(input_data) if isinstance(input_data, dict) else input_data

    return subprocess.run(
        cmd,
        input=input_str,
        capture_output=True,
        text=True,
        timeout=10,
    )
```

### Pattern 3: All Marker Types

```python
# Core (unmarked) - must pass
def test_passthrough(entrypoint_argv):
    ...

# Functionality - nice to have
@pytest.mark.functionality
def test_filter_fields(entrypoint_argv):
    ...

# Error - error handling
@pytest.mark.error
def test_invalid_json(entrypoint_argv):
    ...
```

### Pattern 4: Organized Test Sections

```python
# =============================================================================
# Core Tests (unmarked - must pass)
# =============================================================================

def test_core_1(): ...
def test_core_2(): ...

# =============================================================================
# Functionality Tests (nice to have)
# =============================================================================

@pytest.mark.functionality
def test_feature_1(): ...

# =============================================================================
# Error Tests (error handling)
# =============================================================================

@pytest.mark.error
def test_error_1(): ...
```

## Test Distribution

| Type | Count | Purpose |
|------|-------|---------|
| Core (unmarked) | 5 | Essential functionality |
| Functionality | 3 | Advanced features |
| Error | 3 | Error handling |

## Comparison with file_backup

| Aspect | etl_pipeline | file_backup |
|--------|--------------|-------------|
| Test data | Inline | External files |
| Input | stdin JSON | Files + args |
| Output | stdout JSON | JSONL file |
| Complexity | Simple | Complex |
| Cases per checkpoint | ~11 | ~13 |

## When to Use This Pattern

**Use inline tests when**:
- Test data is simple (few fields)
- Few test cases per checkpoint
- Data doesn't need to be reused
- Quick iteration during development

**Use external files when**:
- Many test cases
- Complex input data
- Data shared across tests
- Non-developers maintaining tests

## Running Locally

```bash
cd problems/etl_pipeline

# Run tests
pytest tests/ \
  --entrypoint="python solutions/reference/etl.py" \
  --checkpoint=checkpoint_1 \
  -v

# Run with SCBench
slop-code run \
  --agent claude_code \
  --model anthropic/opus-4.5 \
  --environment configs/environments/docker-python3.12-uv.yaml \
  --prompt configs/prompts/just-solve.jinja \
  --problem etl_pipeline
```

## Next Steps

- [file_backup Example](file_backup.md) - Parametrized tests pattern
- [Stream Testing](../patterns/stream-testing.md) - More stream patterns
- [CLI Testing](../patterns/cli-testing.md) - CLI patterns
