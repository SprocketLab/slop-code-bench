# Complex Parametrization Patterns

Reference for advanced test parametrization strategies for loading and organizing test cases.

## Overview

Complex parametrization handles scenarios with:
- **Hundreds of test cases** stored externally
- **Multiple case formats** (JSON, YAML, directories)
- **Dynamic case discovery** from the filesystem
- **Case grouping** by type (core, errors, functionality)
- **Checkpoint-specific** case variants

## Pattern 1: Directory-Based Case Discovery

Discover test cases from a directory structure where each case is a subdirectory.

### Directory Structure

```
tests/data/checkpoint_1/
├── core/
│   ├── basic_case/
│   │   ├── case.yaml
│   │   ├── expected.json
│   │   └── files/
│   ├── nested_objects/
│   │   ├── case.yaml
│   │   └── expected.json
│   └── edge_cases/
│       ├── case.yaml
│       └── expected.json
├── errors/
│   ├── invalid_input/
│   │   ├── case.yaml
│   │   └── expected.yaml
│   └── timeout/
│       ├── case.yaml
│       └── expected.yaml
└── functionality/
    ├── pretty_print/
    │   ├── case.yaml
    │   └── expected.json
    └── custom_format/
        ├── case.yaml
        └── expected.json
```

### Discovery Implementation

**Real example from `layered_config_synthesizer`:**

```python
from pathlib import Path

CHECKPOINT_DIR = Path(__file__).parent / "data" / "checkpoint_1"


def discover_cases(group_dir: Path) -> list[Path]:
    """Discover case directories from a group.

    Each case is a directory with case.yaml and expected output.
    """
    cases: list[Path] = []

    if not group_dir.exists():
        return cases

    for entry in sorted(group_dir.iterdir()):
        if entry.is_dir() and (entry / "case.yaml").exists():
            cases.append(entry)

    return cases


# Load cases at module level for parametrization
CORE_CASES = discover_cases(CHECKPOINT_DIR / "core")
ERROR_CASES = discover_cases(CHECKPOINT_DIR / "errors")
FUNCTIONALITY_CASES = discover_cases(CHECKPOINT_DIR / "functionality")


def case_id(case_dir: Path) -> str:
    """Generate test ID from case directory name."""
    return case_dir.name


@pytest.mark.parametrize("case_dir", CORE_CASES, ids=case_id)
def test_checkpoint_1_core(entrypoint_argv, case_dir, tmp_path):
    """Test core cases loaded from directories."""
    case = yaml.safe_load((case_dir / "case.yaml").read_text())
    expected = json.loads((case_dir / "expected.json").read_text())

    # Run the test...
    result = subprocess.run(
        entrypoint_argv + case.get("args", []),
        input=json.dumps(case.get("input")),
        capture_output=True,
        text=True,
    )

    output = json.loads(result.stdout)
    assert output == expected


@pytest.mark.error
@pytest.mark.parametrize("case_dir", ERROR_CASES, ids=case_id)
def test_checkpoint_1_errors(entrypoint_argv, case_dir):
    """Test error handling."""
    case = yaml.safe_load((case_dir / "case.yaml").read_text())
    expected = yaml.safe_load((case_dir / "expected.yaml").read_text())

    result = subprocess.run(
        entrypoint_argv + case.get("args", []),
        input=json.dumps(case.get("input")),
        capture_output=True,
        text=True,
    )

    assert result.returncode == expected.get("exit_code", 1)


@pytest.mark.functionality
@pytest.mark.parametrize("case_dir", FUNCTIONALITY_CASES, ids=case_id)
def test_checkpoint_1_functionality(entrypoint_argv, case_dir):
    """Test optional features."""
    case = yaml.safe_load((case_dir / "case.yaml").read_text())
    expected = json.loads((case_dir / "expected.json").read_text())

    result = subprocess.run(
        entrypoint_argv + case.get("args", []),
        capture_output=True,
        text=True,
    )

    output = json.loads(result.stdout)
    assert output == expected
```

**Key Advantages:**
- One case = one directory = easy to navigate
- Self-documenting case names (directory name)
- Can organize cases in subdirectories (core, errors, functionality)
- Input files coexist with case definition

## Pattern 2: JSON File Case Loading

Load all test cases from a single JSON file with hundreds of cases.

### File Format

**tests/data/checkpoint_2_group_agg.json:**
```json
{
  "simple_sum": {
    "input": {
      "values": [1, 2, 3],
      "operation": "sum"
    },
    "expected": {
      "result": 6,
      "count": 3
    }
  },
  "average": {
    "input": {
      "values": [10, 20, 30],
      "operation": "average"
    },
    "expected": {
      "result": 20,
      "count": 3
    }
  },
  "empty_input": {
    "input": {
      "values": [],
      "operation": "sum"
    },
    "expected": {
      "result": 0,
      "count": 0
    }
  }
}
```

### Loading Implementation

**Real example from `log_query`:**

```python
from pathlib import Path
import json

CHECKPOINT_DIR = Path(__file__).parent / "data"


def load_cases(json_file: Path) -> dict[str, dict]:
    """Load test cases from JSON file.

    File format:
    {
      "case_name": {"input": {...}, "expected": {...}},
      ...
    }
    """
    with open(json_file) as f:
        return json.load(f)


# Load at module level
CORE_CASES = load_cases(CHECKPOINT_DIR / "checkpoint_2_group_agg.json")
ERROR_CASES = load_cases(CHECKPOINT_DIR / "checkpoint_2_errors.json")
HIDDEN_CASES = load_cases(CHECKPOINT_DIR / "checkpoint_2_hidden.json")


@pytest.mark.parametrize(
    "case_name,case",
    list(CORE_CASES.items()),
    ids=list(CORE_CASES.keys()),
)
def test_checkpoint_2_core(entrypoint_argv, case_name, case, tmp_path):
    """Test core cases from JSON file."""
    input_data = case["input"]
    expected_output = case["expected"]

    result = subprocess.run(
        entrypoint_argv,
        input=json.dumps(input_data),
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert output == expected_output
```

**Key Advantages:**
- Hundreds of cases in one file
- Compact and easy to maintain
- Simple structure for programmatic generation
- Clear case IDs from dictionary keys

## Pattern 3: YAML Manifest with Flexible Structure

Use YAML manifests where each case directory contains both input and expected output definitions.

### Directory Structure

```
tests/data/checkpoint_3/
├── core/
│   ├── case_1/
│   │   └── case.yaml          # Contains both input and expected
│   ├── case_2/
│   │   ├── case.yaml
│   │   └── files/             # Optional: input files
│   │       └── data.csv
│   └── case_3/
│       └── case.yaml
└── errors/
    └── error_case_1/
        └── case.yaml
```

### case.yaml Format

```yaml
description: |
  Tests aggregation with numeric data and custom operations.
  The aggregator should support sum, average, min, max operations.

input:
  format: json
  data:
    values: [1, 2, 3, 4, 5]
    operation: sum

args:
  - --verbose
  - --format
  - json

expected:
  exit_code: 0
  stdout: |
    {
      "result": 15,
      "operation": "sum",
      "count": 5
    }
  stderr_contains: null
```

### Loading Implementation

**Real pattern from `layered_config_synthesizer`:**

```python
def load_case_manifest(case_dir: Path) -> tuple[dict, dict]:
    """Load case.yaml and extract case and expected sections."""
    manifest = yaml.safe_load((case_dir / "case.yaml").read_text())

    case = manifest.get("input", {})
    expected = manifest.get("expected", {})

    return case, expected


def run_case(
    entrypoint_argv: list[str],
    case_dir: Path,
    tmp_path: Path,
    case_data: dict,
) -> tuple[int, str, str]:
    """Run a case and return (exit_code, stdout, stderr)."""
    args = case_data.get("args", [])
    input_text = case_data.get("input")

    cmd = entrypoint_argv + args

    result = subprocess.run(
        cmd,
        input=json.dumps(input_text) if isinstance(input_text, dict) else input_text,
        capture_output=True,
        text=True,
    )

    return result.returncode, result.stdout, result.stderr


def assert_file_matches(actual_file: Path, expected_content: str):
    """Compare file content with expected, allowing partial matches."""
    actual = actual_file.read_text()
    if actual.strip() != expected_content.strip():
        raise AssertionError(
            f"Content mismatch:\nExpected:\n{expected_content}\n\nActual:\n{actual}"
        )


@pytest.mark.parametrize("case_dir", CORE_CASES, ids=lambda d: d.name)
def test_checkpoint_3_core(entrypoint_argv, case_dir, tmp_path):
    """Test core cases with flexible YAML structure."""
    case, expected = load_case_manifest(case_dir)
    exit_code, stdout, stderr = run_case(entrypoint_argv, case_dir, tmp_path, case)

    assert exit_code == expected.get("exit_code", 0)
    assert expected.get("stdout", stdout.strip()).strip() == stdout.strip()
```

## Pattern 4: Dataclass-Based Test Cases

Use dataclasses for type-safe, structured test case definitions.

**Real example from `execution_server`:**

```python
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ExecuteCase:
    """Immutable test case for execute endpoint."""
    name: str
    body: dict[str, Any]
    expected_stdout: str
    expected_stderr: str
    expected_exit_code: int
    expected_timed_out: bool = False
    expected_duration: float = 10.0


# Define test cases with type safety
CORE_EXECUTE_CASES = [
    ExecuteCase(
        name="echo",
        body={
            "command": "echo 'Hello, world!'",
            "env": {},
            "files": {},
            "stdin": [],
            "timeout": 10,
        },
        expected_stdout="Hello, world!\n",
        expected_stderr="",
        expected_exit_code=0,
    ),
    ExecuteCase(
        name="stderr_capture",
        body={
            "command": "echo 'error' >&2",
            "env": {},
            "files": {},
            "stdin": [],
            "timeout": 10,
        },
        expected_stdout="",
        expected_stderr="error\n",
        expected_exit_code=0,
    ),
    ExecuteCase(
        name="timeout",
        body={
            "command": "sleep 100",
            "env": {},
            "files": {},
            "stdin": [],
            "timeout": 1,
        },
        expected_stdout="",
        expected_stderr="",
        expected_exit_code=-1,
        expected_timed_out=True,
    ),
]


@pytest.mark.parametrize("case", CORE_EXECUTE_CASES, ids=lambda c: c.name)
def test_execute_core(client, case: ExecuteCase):
    """Test execute endpoint with dataclass cases."""
    response = client.post("/execute", json=case.body)

    assert response.status_code == 200
    data = response.json()

    assert data["stdout"] == case.expected_stdout
    assert data["stderr"] == case.expected_stderr
    assert data["exit_code"] == case.expected_exit_code
    assert data["timed_out"] == case.expected_timed_out
```

**Key Advantages:**
- Type-safe case definitions
- IDE autocomplete and validation
- Frozen (immutable) for thread safety
- Self-documenting

## Pattern 5: Helper Module Organization

Extract complex case loading and execution logic into helper modules.

### Directory Structure

```
tests/
├── conftest.py
├── test_checkpoint_1.py
├── case_utils.py           # Helper module
├── data/
│   └── checkpoint_1/
└── assets/
```

### Helper Module Implementation

**Real example - 1000+ lines from `layered_config_synthesizer/tests/case_utils.py`:**

```python
"""Utilities for loading and executing test cases."""

from pathlib import Path
import json
import subprocess
import yaml


def discover_cases(group_dir: Path) -> list[Path]:
    """Discover case directories."""
    cases: list[Path] = []
    if not group_dir.exists():
        return cases

    for entry in sorted(group_dir.iterdir()):
        if entry.is_dir() and (entry / "case.yaml").exists():
            cases.append(entry)

    return cases


def load_case_manifest(case_dir: Path) -> tuple[dict, dict]:
    """Load case.yaml and extract sections."""
    manifest = yaml.safe_load((case_dir / "case.yaml").read_text())
    return manifest.get("input", {}), manifest.get("expected", {})


def copy_tree(source: Path, destination: Path):
    """Recursively copy directory tree."""
    destination.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        if item.is_dir():
            copy_tree(item, destination / item.name)
        else:
            (destination / item.name).write_bytes(item.read_bytes())


def write_inline_content(path: Path, content, file_type: str):
    """Write various file formats."""
    path.parent.mkdir(parents=True, exist_ok=True)

    if file_type == "json":
        path.write_text(json.dumps(content, indent=2))
    elif file_type == "yaml":
        path.write_text(yaml.dump(content))
    elif file_type == "text":
        path.write_text(content)
    elif file_type == "binary":
        path.write_bytes(content)
    else:
        raise ValueError(f"Unknown file type: {file_type}")


def assert_file_matches(actual: Path, expected: Path, partial: bool = False):
    """Compare file contents."""
    actual_text = actual.read_text()
    expected_text = expected.read_text()

    if partial:
        # Partial match: expected must be subset of actual
        assert expected_text.strip() in actual_text
    else:
        # Exact match
        assert actual_text.strip() == expected_text.strip()


def run_case(
    entrypoint_argv: list[str],
    case_dir: Path,
    tmp_path: Path,
    case_data: dict,
) -> subprocess.CompletedProcess:
    """Run a single test case."""
    args = case_data.get("args", [])
    input_data = case_data.get("input")

    cmd = entrypoint_argv + args

    input_text = json.dumps(input_data) if isinstance(input_data, dict) else input_data

    return subprocess.run(
        cmd,
        input=input_text,
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )


# In test file:
from case_utils import discover_cases, load_case_manifest, run_case, assert_file_matches

CORE_CASES = discover_cases(CHECKPOINT_DIR / "core")

@pytest.mark.parametrize("case_dir", CORE_CASES, ids=lambda d: d.name)
def test_core(entrypoint_argv, case_dir, tmp_path):
    case, expected = load_case_manifest(case_dir)
    result = run_case(entrypoint_argv, case_dir, tmp_path, case)
    assert_file_matches(tmp_path / "output.yaml", case_dir / "expected.yaml")
```

**Benefits:**
- Reusable across multiple test files
- Complex logic centralized and tested
- Clear separation of concerns
- Easy to maintain and extend

## Performance Considerations

### 1. Lazy vs Eager Loading

```python
# Bad: Load all cases immediately (slow startup)
ALL_CASES = load_cases()  # May take seconds for 1000s of cases

@pytest.mark.parametrize("case", ALL_CASES)
def test_all(case):
    pass


# Good: Load cases via factory fixture (lazy loading)
@pytest.fixture(scope="session")
def all_cases():
    return load_cases()  # Still loaded, but once per session

@pytest.fixture(params=load_cases())  # Parametrize with factory
def case(request):
    return request.param
```

### 2. Collection Time

```bash
# Check how long test collection takes
pytest --collect-only -q

# Slow? Reduce discovery scope:
# - Avoid scanning all files
# - Use explicit case lists instead of discovery
# - Load cases lazily where possible
```

### 3. Filtering Cases

```bash
# Run only core cases
pytest -k "core" tests/

# Run cases matching pattern
pytest -k "case_1 or case_2" tests/

# Run specific parametrized test
pytest tests/test_checkpoint_1.py::test_core[case_1]
```

## Edge Cases and Gotchas

### 1. Case Ordering

```python
# Good: Deterministic ordering (sorted)
for case_dir in sorted(group_dir.iterdir()):
    cases.append(case_dir)

# Bad: Filesystem order is inconsistent
for case_dir in group_dir.iterdir():
    cases.append(case_dir)
```

### 2. Unicode and Encoding

```python
# Handle special characters
case_dir_names = []
for case_dir in sorted(group_dir.iterdir()):
    # Normalize unicode for consistent IDs
    name = case_dir.name.encode('utf-8').decode('utf-8')
    case_dir_names.append(name)
```

### 3. Long Test Names

```python
# Long names get truncated by pytest
# Use clear but concise IDs
ids = [case_dir.name for case_dir in case_dirs]

# pytest truncates to ~200 chars
# Make sure important info is at the beginning
"my_problem_checkpoint_1_core_case_001_with_special_chars"
#^ Start with problem/checkpoint for filtering
```

### 4. Duplicate Test IDs

```python
# Bad: Duplicate IDs cause errors
@pytest.mark.parametrize("case", [case1, case2, case3], ids=["test", "test", "test"])

# Good: Unique IDs
@pytest.mark.parametrize("case", cases, ids=[c.name for c in cases])
```

## Best Practices Summary

1. **Use discovery** for filesystem-based cases
2. **Use JSON** for hundreds of similar cases
3. **Use YAML manifests** for flexible, self-documenting cases
4. **Use dataclasses** for type-safe cases
5. **Use helper modules** for complex case handling
6. **Keep IDs short** but descriptive
7. **Sort cases deterministically** for consistent ordering
8. **Avoid test interdependencies** with parametrization

## Next Steps

- [Test Data](test-data.md) - Basic test data organization
- [Advanced Fixtures](fixtures-advanced.md) - Factory fixtures
- [Debugging Workflows](debugging-workflows.md) - Debugging parametrized tests
