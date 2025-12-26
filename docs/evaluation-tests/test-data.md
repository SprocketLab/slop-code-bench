# Test Data Organization

Patterns for organizing test data in pytest-based problems.

## Overview

Test data can be organized in two main ways:

1. **Inline** - Data defined directly in Python test files
2. **External** - Data stored in files, loaded at test time

## Inline Test Data

Define test data directly in test functions. Good for:
- Small test suites
- Simple data structures
- Self-contained tests

```python
def test_basic_case(entrypoint_argv):
    """Inline test data."""
    input_data = {"name": "Alice", "age": 30}
    expected = {"name": "alice", "age": 30}

    result = subprocess.run(
        entrypoint_argv,
        input=json.dumps(input_data),
        capture_output=True,
        text=True,
    )

    assert json.loads(result.stdout) == expected
```

## External Test Data

Store test data in files. Good for:
- Many test cases
- Complex data structures
- Reusable test data

### Directory Structure

```
tests/
├── conftest.py
├── test_checkpoint_1.py
├── data/
│   └── checkpoint_1/
│       ├── core/
│       │   ├── basic_case/
│       │   │   ├── case.yaml      # Input definition
│       │   │   └── expected.json  # Expected output
│       │   └── complex_case/
│       │       ├── case.yaml
│       │       └── expected.json
│       └── errors/
│           ├── invalid_input/
│           │   ├── case.yaml
│           │   └── expected.yaml  # Error expectations
│           └── empty_input/
│               ├── case.yaml
│               └── expected.yaml
└── assets/
    └── fixtures.json              # Shared static data
```

### Case File Format

**case.yaml** - Input definition:

```yaml
# Simple case
input:
  name: Alice
  age: 30

# Or with arguments
args:
  - --format
  - json
input:
  data: value
```

**expected.json** - Expected output:

```json
{
  "name": "alice",
  "age": 30
}
```

**expected.yaml** - Error expectations:

```yaml
exit_code: 1
stderr_contains: "error"
```

### Loading External Cases

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
        case = yaml.safe_load((case_dir / "case.yaml").read_text())

        # Load expected output
        expected_json = case_dir / "expected.json"
        expected_yaml = case_dir / "expected.yaml"

        if expected_json.exists():
            expected = json.loads(expected_json.read_text())
        else:
            expected = yaml.safe_load(expected_yaml.read_text())

        cases.append({
            "id": case_dir.name,
            "case": case,
            "expected": expected,
        })

    return cases


# Load at module level for parametrization
CORE_CASES = load_cases(CHECKPOINT_DIR / "core")
ERROR_CASES = load_cases(CHECKPOINT_DIR / "errors")
```

### Parametrized Tests

```python
@pytest.mark.parametrize("case", CORE_CASES, ids=[c["id"] for c in CORE_CASES])
def test_core_cases(entrypoint_argv, case):
    """Core cases from external files."""
    result = run_case(entrypoint_argv, case["case"])

    output = json.loads(result.stdout)
    assert output == case["expected"]


@pytest.mark.error
@pytest.mark.parametrize("case", ERROR_CASES, ids=[c["id"] for c in ERROR_CASES])
def test_error_cases(entrypoint_argv, case):
    """Error cases from external files."""
    result = run_case(entrypoint_argv, case["case"])

    expected = case["expected"]
    assert result.returncode == expected.get("exit_code", 1)
```

## Static Assets

For shared files that don't change between tests.

### Directory Structure

```
tests/
├── assets/
│   ├── schemas/
│   │   └── output.schema.json
│   ├── fixtures/
│   │   └── sample_data.json
│   └── reference/
│       └── expected_output.json
```

### Accessing Assets

```python
@pytest.fixture(scope="session")
def assets_dir():
    return Path(__file__).parent / "assets"


@pytest.fixture(scope="session")
def schema(assets_dir):
    with open(assets_dir / "schemas" / "output.schema.json") as f:
        return json.load(f)


def test_output_matches_schema(entrypoint_argv, schema):
    result = run_command(entrypoint_argv, {"data": "test"})
    output = json.loads(result.stdout)

    import jsonschema
    jsonschema.validate(output, schema)
```

## Environment Variables

Static assets from `config.yaml` are available via environment variables:

```yaml
# config.yaml
static_assets:
  reference_data:
    path: data/reference
```

```python
import os

@pytest.fixture(scope="session")
def reference_data_dir():
    """Get reference data directory from environment."""
    path = os.environ.get("SCBENCH_ASSET_REFERENCE_DATA")
    if path:
        return Path(path)
    # Fallback for local testing
    return Path(__file__).parent.parent / "data" / "reference"
```

## Test Data Patterns

### Pattern 1: Input/Output Pairs

```
data/checkpoint_1/core/
├── case_1/
│   ├── input.json
│   └── output.json
└── case_2/
    ├── input.json
    └── output.json
```

```python
def load_io_cases(group_dir):
    cases = []
    for case_dir in sorted(group_dir.iterdir()):
        if case_dir.is_dir():
            input_data = json.loads((case_dir / "input.json").read_text())
            output_data = json.loads((case_dir / "output.json").read_text())
            cases.append({
                "id": case_dir.name,
                "input": input_data,
                "output": output_data,
            })
    return cases
```

### Pattern 2: YAML Manifest

```
data/checkpoint_1/core/
├── case_1/
│   ├── case.yaml          # Contains both input and expected
│   └── files/             # Optional: input files
│       └── data.csv
└── case_2/
    └── case.yaml
```

**case.yaml:**
```yaml
description: Basic test case
input:
  format: json
  data:
    key: value
args:
  - --verbose
expected:
  exit_code: 0
  output:
    key: VALUE
```

### Pattern 3: Single File Cases

For simple cases, use one YAML file per case:

```
data/checkpoint_1/
├── core.yaml              # All core cases in one file
├── errors.yaml            # All error cases in one file
└── functionality.yaml     # All functionality cases
```

**core.yaml:**
```yaml
- id: basic
  input: {"key": "value"}
  expected: {"key": "VALUE"}

- id: nested
  input: {"outer": {"inner": "value"}}
  expected: {"outer": {"inner": "VALUE"}}
```

```python
def load_yaml_cases(yaml_file):
    cases = yaml.safe_load(yaml_file.read_text())
    return [{"id": c["id"], **c} for c in cases]

CORE_CASES = load_yaml_cases(CHECKPOINT_DIR / "core.yaml")
```

## Checkpoint-Specific Data

Organize data by checkpoint for multi-checkpoint problems:

```
data/
├── checkpoint_1/
│   ├── core/
│   └── errors/
├── checkpoint_2/
│   ├── core/              # New tests for checkpoint_2
│   ├── errors/
│   └── functionality/     # Additional feature tests
└── checkpoint_3/
    └── core/
```

```python
def load_checkpoint_cases(checkpoint_name, group_name):
    group_dir = TESTS_DIR / "data" / checkpoint_name / group_name
    if not group_dir.exists():
        return []
    return load_cases(group_dir)
```

## Best Practices

### Use Descriptive Case Names

```
core/
├── basic_json_object/     # Good: Describes what's tested
├── nested_arrays/         # Good: Specific
├── test_1/                # Bad: Not descriptive
└── case/                  # Bad: Generic
```

### Include Expected Output with Input

```yaml
# case.yaml - Keep input and expected together
input:
  data: value

expected:
  transformed_data: VALUE

# Not in separate files for simple cases
```

### Document Edge Cases

```yaml
# edge_case.yaml
description: |
  Tests empty string handling.
  Empty strings should be converted to null.

input:
  field: ""

expected:
  field: null
```

### Version Test Data

When checkpoints change expectations, version your test data:

```yaml
# case.yaml
input:
  data: value

expected:
  checkpoint_1:
    result: value
  checkpoint_2:
    result: value
    version: 2  # New field in checkpoint_2
```

## Next Steps

- [conftest Patterns](conftest-patterns.md) - Fixture patterns
- [Complex Parametrization](complex-parametrization.md) - Advanced data loading patterns
- [CLI Testing](../problems/patterns/cli-testing.md) - CLI-specific patterns
