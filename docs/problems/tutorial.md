# Tutorial: Create Your First Problem

This tutorial walks you through creating a complete pytest-based evaluation problem from scratch in 20 minutes.

## What We're Building

**Problem**: A CLI tool that normalizes JSON data

**Features:**
- Read JSON from stdin
- Normalize keys (lowercase, trim)
- Output normalized JSON to stdout
- Handle invalid JSON gracefully

**Why this problem**: Simple enough to complete quickly, demonstrates all key pytest patterns.

## Prerequisites

- SCBench repository cloned
- Python environment set up (`uv sync`)
- Basic understanding of Python and pytest

## Step 1: Create Directory Structure (2 minutes)

```bash
# From repository root
mkdir -p problems/json_normalizer/tests
```

**What we created:**
```
problems/json_normalizer/     # Problem root
└── tests/                    # Pytest tests directory
```

## Step 2: Write config.yaml (2 minutes)

Create `problems/json_normalizer/config.yaml`:

```yaml
version: 1
name: json_normalizer
description: CLI tool that normalizes JSON keys (lowercase, trimmed)
category: data-transformation
difficulty: Easy
author: Your Name
entry_file: normalizer.py
timeout: 10

tags:
  - cli
  - json
  - data-transformation

checkpoints:
  checkpoint_1:
    version: 1
    order: 1
    state: Core Tests
```

**Key fields:**
- `name`: Must match directory name
- `entry_file`: The file agents will create
- `checkpoints`: Defines evaluation milestones

## Step 3: Write Specification (3 minutes)

Create `problems/json_normalizer/checkpoint_1.md`:

```markdown
# Checkpoint 1: JSON Key Normalizer

Build a CLI tool that normalizes JSON keys.

## Interface

The tool reads JSON from stdin and writes normalized JSON to stdout.

## Normalization Rules

1. Convert all keys to lowercase
2. Trim whitespace from keys
3. Preserve values unchanged
4. Handle nested objects recursively

## Exit Codes

- `0`: Success
- `1`: Invalid JSON input

## Examples

Input:
```json
{"  Name  ": "Alice", "AGE": 30}
```

Output:
```json
{"name": "Alice", "age": 30}
```

Error case (exit code 1):
```
not valid json
```
```

## Step 4: Create conftest.py (2 minutes)

Create `problems/json_normalizer/tests/conftest.py`:

```python
"""Pytest configuration for json_normalizer evaluation."""

import shlex

import pytest


def pytest_addoption(parser):
    """Register required CLI options for SCBench evaluation."""
    parser.addoption("--entrypoint", required=True)
    parser.addoption("--checkpoint", required=True)


@pytest.fixture(scope="session")
def entrypoint_argv(request):
    """Get submission entrypoint as argv list."""
    return shlex.split(request.config.getoption("--entrypoint"))


@pytest.fixture(scope="session")
def checkpoint_name(request):
    """Get current checkpoint name."""
    return request.config.getoption("--checkpoint")
```

**These fixtures are required:**
- `entrypoint_argv`: Command to run the submission
- `checkpoint_name`: Current checkpoint being evaluated

## Step 5: Write Test File (5 minutes)

Create `problems/json_normalizer/tests/test_checkpoint_1.py`:

```python
"""Tests for checkpoint_1: JSON Key Normalizer."""

import json
import subprocess

import pytest


def run_normalizer(entrypoint_argv, input_data):
    """Run normalizer with JSON input via stdin."""
    if isinstance(input_data, dict):
        input_str = json.dumps(input_data)
    else:
        input_str = input_data

    return subprocess.run(
        entrypoint_argv,
        input=input_str,
        capture_output=True,
        text=True,
        timeout=10,
    )


# =============================================================================
# Core Tests (unmarked - must pass)
# =============================================================================


def test_lowercase_keys(entrypoint_argv):
    """Core: Convert uppercase keys to lowercase."""
    result = run_normalizer(entrypoint_argv, {"NAME": "Alice", "AGE": 30})
    assert result.returncode == 0, f"Failed: {result.stderr}"

    output = json.loads(result.stdout)
    assert output == {"name": "Alice", "age": 30}


def test_trim_whitespace(entrypoint_argv):
    """Core: Trim whitespace from keys."""
    result = run_normalizer(entrypoint_argv, {"  name  ": "Bob"})
    assert result.returncode == 0, f"Failed: {result.stderr}"

    output = json.loads(result.stdout)
    assert output == {"name": "Bob"}


def test_nested_objects(entrypoint_argv):
    """Core: Handle nested objects recursively."""
    input_data = {
        "USER": {
            "  NAME  ": "Charlie",
            "ADDRESS": {"CITY": "NYC"}
        }
    }
    result = run_normalizer(entrypoint_argv, input_data)
    assert result.returncode == 0, f"Failed: {result.stderr}"

    output = json.loads(result.stdout)
    assert output == {
        "user": {
            "name": "Charlie",
            "address": {"city": "NYC"}
        }
    }


def test_empty_object(entrypoint_argv):
    """Core: Handle empty object."""
    result = run_normalizer(entrypoint_argv, {})
    assert result.returncode == 0, f"Failed: {result.stderr}"

    output = json.loads(result.stdout)
    assert output == {}


# =============================================================================
# Functionality Tests (nice to have)
# =============================================================================


@pytest.mark.functionality
def test_array_values(entrypoint_argv):
    """Functionality: Preserve array values."""
    input_data = {"TAGS": ["Python", "CLI"]}
    result = run_normalizer(entrypoint_argv, input_data)
    assert result.returncode == 0

    output = json.loads(result.stdout)
    assert output == {"tags": ["Python", "CLI"]}


@pytest.mark.functionality
def test_mixed_case_keys(entrypoint_argv):
    """Functionality: Handle camelCase keys."""
    input_data = {"firstName": "Dana", "lastName": "Smith"}
    result = run_normalizer(entrypoint_argv, input_data)
    assert result.returncode == 0

    output = json.loads(result.stdout)
    assert output == {"firstname": "Dana", "lastname": "Smith"}


# =============================================================================
# Error Tests (error handling)
# =============================================================================


@pytest.mark.error
def test_invalid_json(entrypoint_argv):
    """Error: Invalid JSON returns exit code 1."""
    result = run_normalizer(entrypoint_argv, "not valid json")
    assert result.returncode == 1, "Expected exit code 1 for invalid JSON"


@pytest.mark.error
def test_empty_input(entrypoint_argv):
    """Error: Empty input returns exit code 1."""
    result = run_normalizer(entrypoint_argv, "")
    assert result.returncode == 1, "Expected exit code 1 for empty input"
```

**Test organization:**
- **Core tests** (unmarked): Must pass - essential functionality
- **Functionality tests** (`@pytest.mark.functionality`): Nice to have
- **Error tests** (`@pytest.mark.error`): Error handling cases

## Step 6: Verify Structure (1 minute)

```bash
tree problems/json_normalizer
```

Expected:
```
problems/json_normalizer/
├── config.yaml
├── checkpoint_1.md
└── tests/
    ├── conftest.py
    └── test_checkpoint_1.py
```

## Step 7: Run Tests Locally (Optional)

Create a reference solution to test locally:

```bash
mkdir -p problems/json_normalizer/solution

cat > problems/json_normalizer/solution/normalizer.py << 'EOF'
#!/usr/bin/env python3
"""JSON key normalizer."""

import json
import sys


def normalize_keys(obj):
    """Recursively normalize object keys."""
    if isinstance(obj, dict):
        return {k.strip().lower(): normalize_keys(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [normalize_keys(item) for item in obj]
    return obj


def main():
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        sys.exit(1)

    normalized = normalize_keys(data)
    print(json.dumps(normalized))


if __name__ == "__main__":
    main()
EOF
```

Run tests:

```bash
cd problems/json_normalizer/solution
pytest ../tests/ \
  --entrypoint="python normalizer.py" \
  --checkpoint=checkpoint_1 \
  -v
```

Expected output:
```
tests/test_checkpoint_1.py::test_lowercase_keys PASSED
tests/test_checkpoint_1.py::test_trim_whitespace PASSED
tests/test_checkpoint_1.py::test_nested_objects PASSED
tests/test_checkpoint_1.py::test_empty_object PASSED
tests/test_checkpoint_1.py::test_array_values PASSED
tests/test_checkpoint_1.py::test_mixed_case_keys PASSED
tests/test_checkpoint_1.py::test_invalid_json PASSED
tests/test_checkpoint_1.py::test_empty_input PASSED
```

## Step 8: Run with SCBench

```bash
# Run an agent on your problem
slop-code run \
  --agent claude_code \
  --model anthropic/opus-4.5 \
  --environment configs/environments/docker-python3.12-uv.yaml \
  --prompt configs/prompts/just-solve.jinja \
  --problem json_normalizer

# Evaluate results
slop-code eval outputs/<run-directory>/
```

## Success Checklist

Your problem is complete when:

- [ ] `config.yaml` exists with correct fields
- [ ] `checkpoint_1.md` has clear specification
- [ ] `tests/conftest.py` has required fixtures
- [ ] `tests/test_checkpoint_1.py` has core, functionality, and error tests
- [ ] Local tests pass with reference solution
- [ ] Agent can attempt the problem

## What You Learned

1. **Directory structure** - config.yaml, checkpoint_N.md, tests/
2. **Configuration** - Minimal config.yaml with checkpoints inline
3. **Pytest fixtures** - entrypoint_argv, checkpoint_name
4. **Test markers** - Core (unmarked), functionality, error
5. **Testing pattern** - subprocess.run with stdin/stdout

## Adding a Second Checkpoint

To extend the problem:

1. Update `config.yaml`:
```yaml
checkpoints:
  checkpoint_1:
    version: 1
    order: 1
    state: Core Tests

  checkpoint_2:
    version: 1
    order: 2
    state: Core Tests
    include_prior_tests: true  # Run checkpoint_1 tests too
```

2. Create `checkpoint_2.md` with new requirements

3. Create `tests/test_checkpoint_2.py` with new tests

Prior checkpoint tests automatically run as regression tests.

## Next Steps

- [Quick Reference](quick-reference.md) - Templates and commands
- [Structure Guide](structure.md) - Directory layout details
- [Markers](pytest/markers.md) - Test categorization
- [Examples](examples/) - Real problem walkthroughs
