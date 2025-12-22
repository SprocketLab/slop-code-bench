# Parametrized Test Cases

Patterns for loading and running tests from external data files.

## Why Parametrize?

Use parametrized tests when you have:
- Many similar test cases
- Test data that changes independently of test logic
- Cases that are easier to maintain in data files

## Basic Parametrization

```python
import pytest

CASES = [
    {"id": "basic", "input": {"a": 1}, "expected": {"a": 1}},
    {"id": "nested", "input": {"a": {"b": 2}}, "expected": {"a": {"b": 2}}},
    {"id": "array", "input": {"a": [1, 2]}, "expected": {"a": [1, 2]}},
]


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_cases(entrypoint_argv, case):
    result = run_command(entrypoint_argv, case["input"])
    assert json.loads(result.stdout) == case["expected"]
```

## Loading from Files

### Directory-Based Cases

```
tests/data/checkpoint_1/core/
├── basic_case/
│   ├── case.yaml
│   └── expected.json
├── nested_case/
│   ├── case.yaml
│   └── expected.json
└── edge_case/
    ├── case.yaml
    └── expected.json
```

```python
from pathlib import Path
import json
import yaml

CHECKPOINT_DIR = Path(__file__).parent / "data" / "checkpoint_1"


def load_cases(group_dir):
    """Load test cases from directory."""
    cases = []

    for case_dir in sorted(group_dir.iterdir()):
        if not case_dir.is_dir():
            continue

        # Load case definition
        case_yaml = yaml.safe_load((case_dir / "case.yaml").read_text())

        # Load expected output
        expected_file = case_dir / "expected.json"
        expected = json.loads(expected_file.read_text())

        cases.append({
            "id": case_dir.name,
            "case": case_yaml,
            "expected": expected,
        })

    return cases


CORE_CASES = load_cases(CHECKPOINT_DIR / "core")


@pytest.mark.parametrize("case", CORE_CASES, ids=[c["id"] for c in CORE_CASES])
def test_core(entrypoint_argv, case):
    """Core cases from files."""
    result = run_case(entrypoint_argv, case["case"])
    assert result == case["expected"]
```

### Single YAML File

```yaml
# tests/data/cases.yaml
- id: basic
  input:
    name: Alice
  expected:
    name: alice

- id: nested
  input:
    user:
      name: Bob
  expected:
    user:
      name: bob
```

```python
def load_yaml_cases(yaml_path):
    """Load cases from single YAML file."""
    cases = yaml.safe_load(yaml_path.read_text())
    return [{"id": c["id"], **c} for c in cases]


CASES = load_yaml_cases(Path(__file__).parent / "data" / "cases.yaml")


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_from_yaml(entrypoint_argv, case):
    result = run_command(entrypoint_argv, case["input"])
    assert json.loads(result.stdout) == case["expected"]
```

## Case File Formats

### case.yaml Structure

```yaml
# Simple case
input:
  key: value

# With arguments
args:
  - --verbose
  - --format
  - json
input:
  data: value

# With input files
input_files:
  - path: config.json
    content: |
      {"setting": true}
args:
  - --config
  - config.json
```

### expected.json Structure

```json
{
  "status": "success",
  "data": {
    "processed": true
  }
}
```

### expected.yaml for Errors

```yaml
exit_code: 1
stderr_contains: "error"
stderr_pattern: ".*invalid.*"
```

## Running Cases

### Generic Case Runner

```python
def run_case(entrypoint_argv, case):
    """Run a case from loaded data."""
    cmd = entrypoint_argv.copy()

    # Add arguments if present
    if "args" in case:
        cmd.extend(case["args"])

    # Prepare input
    input_data = case.get("input")
    if input_data is not None:
        input_str = json.dumps(input_data)
    else:
        input_str = None

    return subprocess.run(
        cmd,
        input=input_str,
        capture_output=True,
        text=True,
        timeout=30,
    )
```

### With File Setup

```python
def run_case_with_files(entrypoint_argv, case, tmp_path):
    """Run case with input files."""
    # Create input files
    for file_spec in case.get("input_files", []):
        file_path = tmp_path / file_spec["path"]
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(file_spec["content"])

    # Substitute paths in arguments
    args = []
    for arg in case.get("args", []):
        if arg.startswith("{{") and arg.endswith("}}"):
            # Replace placeholders
            filename = arg[2:-2]
            args.append(str(tmp_path / filename))
        else:
            args.append(arg)

    cmd = entrypoint_argv + args

    return subprocess.run(
        cmd,
        input=json.dumps(case.get("input", {})),
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
```

## Multiple Groups

```python
CHECKPOINT_DIR = Path(__file__).parent / "data" / "checkpoint_1"

CORE_CASES = load_cases(CHECKPOINT_DIR / "core")
ERROR_CASES = load_cases(CHECKPOINT_DIR / "errors")
FUNCTIONALITY_CASES = load_cases(CHECKPOINT_DIR / "functionality")


@pytest.mark.parametrize("case", CORE_CASES, ids=[c["id"] for c in CORE_CASES])
def test_core(entrypoint_argv, case):
    """Core cases."""
    result = run_case(entrypoint_argv, case["case"])
    assert result.returncode == 0
    assert json.loads(result.stdout) == case["expected"]


@pytest.mark.error
@pytest.mark.parametrize("case", ERROR_CASES, ids=[c["id"] for c in ERROR_CASES])
def test_errors(entrypoint_argv, case):
    """Error cases."""
    result = run_case(entrypoint_argv, case["case"])
    expected = case["expected"]
    assert result.returncode == expected.get("exit_code", 1)


@pytest.mark.functionality
@pytest.mark.parametrize("case", FUNCTIONALITY_CASES, ids=[c["id"] for c in FUNCTIONALITY_CASES])
def test_functionality(entrypoint_argv, case):
    """Functionality cases."""
    result = run_case(entrypoint_argv, case["case"])
    assert result.returncode == 0
```

## Shared Utilities Module

Create `tests/case_utils.py` for reusable functions:

```python
"""Shared case loading and running utilities."""

import json
import subprocess
from pathlib import Path

import yaml


def load_cases(group_dir):
    """Load test cases from a directory."""
    if not group_dir.exists():
        return []

    cases = []
    for case_dir in sorted(group_dir.iterdir()):
        if not case_dir.is_dir():
            continue

        case = yaml.safe_load((case_dir / "case.yaml").read_text())

        # Try JSON first, then YAML for expected
        expected_json = case_dir / "expected.json"
        expected_yaml = case_dir / "expected.yaml"

        if expected_json.exists():
            expected = json.loads(expected_json.read_text())
        elif expected_yaml.exists():
            expected = yaml.safe_load(expected_yaml.read_text())
        else:
            expected = None

        cases.append({
            "id": case_dir.name,
            "case": case,
            "expected": expected,
            "path": case_dir,
        })

    return cases


def run_case(entrypoint_argv, case, timeout=30):
    """Run a test case."""
    cmd = entrypoint_argv.copy()

    if "args" in case:
        cmd.extend(case["args"])

    input_data = case.get("input")
    input_str = json.dumps(input_data) if input_data else None

    return subprocess.run(
        cmd,
        input=input_str,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def assert_output_matches(result, expected):
    """Assert command output matches expected."""
    if result.returncode != 0:
        if "exit_code" in expected:
            assert result.returncode == expected["exit_code"]
        return

    output = json.loads(result.stdout)
    assert output == expected
```

Use in tests:

```python
from case_utils import load_cases, run_case, assert_output_matches

CORE_CASES = load_cases(CHECKPOINT_DIR / "core")


@pytest.mark.parametrize("case", CORE_CASES, ids=[c["id"] for c in CORE_CASES])
def test_core(entrypoint_argv, case):
    result = run_case(entrypoint_argv, case["case"])
    assert_output_matches(result, case["expected"])
```

## Checkpoint-Aware Loading

```python
def load_checkpoint_cases(checkpoint_name, group_name):
    """Load cases for a specific checkpoint and group."""
    data_dir = Path(__file__).parent / "data"
    group_dir = data_dir / checkpoint_name / group_name

    if not group_dir.exists():
        return []

    return load_cases(group_dir)


# In test file
CORE_CASES = load_checkpoint_cases("checkpoint_1", "core")
```

## Dynamic Case Discovery

For test discovery at collection time:

```python
def pytest_generate_tests(metafunc):
    """Dynamically generate test cases."""
    if "case" in metafunc.fixturenames:
        checkpoint = metafunc.config.getoption("--checkpoint")
        cases = load_checkpoint_cases(checkpoint, "core")
        metafunc.parametrize("case", cases, ids=[c["id"] for c in cases])
```

## Best Practices

### Use Descriptive Case IDs

```python
# Good
cases = [
    {"id": "empty_input_returns_error", ...},
    {"id": "nested_objects_preserved", ...},
]

# Bad
cases = [
    {"id": "case1", ...},
    {"id": "test", ...},
]
```

### Validate Case Files on Load

```python
def load_cases(group_dir):
    cases = []
    for case_dir in sorted(group_dir.iterdir()):
        case_file = case_dir / "case.yaml"
        if not case_file.exists():
            raise ValueError(f"Missing case.yaml in {case_dir}")

        # Validate required fields
        case = yaml.safe_load(case_file.read_text())
        if "input" not in case and "args" not in case:
            raise ValueError(f"Case must have 'input' or 'args': {case_dir}")

        ...
```

### Handle Missing Data Gracefully

```python
def load_cases(group_dir):
    if not group_dir.exists():
        return []  # Return empty list, don't fail

    ...
```

## Next Steps

- [CLI Testing](cli-testing.md) - CLI patterns
- [Test Data](../pytest/test-data.md) - Data organization
- [Examples](../examples/) - Real examples
