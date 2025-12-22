# Example: layered_config_synthesizer

Advanced example demonstrating shared utilities and complex test infrastructure.

## Problem Overview

**What it tests**: A config synthesis tool that:
1. Reads layered configuration files
2. Merges configurations with inheritance
3. Resolves conflicts and references
4. Outputs synthesized config

**Key patterns demonstrated**:
- Shared `case_utils.py` module
- Complex case loading and validation
- Cross-checkpoint test reuse
- JSON schema validation

## Directory Structure

```
problems/layered_config_synthesizer/
├── config.yaml
├── checkpoint_1.md
├── checkpoint_2.md
├── checkpoint_3.md
└── tests/
    ├── conftest.py
    ├── case_utils.py           # Shared utilities
    ├── test_checkpoint_1.py
    ├── test_checkpoint_2.py
    ├── test_checkpoint_3.py
    └── cases/
        ├── checkpoint_1/
        │   ├── core/
        │   │   └── basic_merge/
        │   │       ├── case.yaml
        │   │       ├── input/
        │   │       │   ├── base.yaml
        │   │       │   └── override.yaml
        │   │       └── expected/
        │   │           └── output.yaml
        │   └── errors/
        └── checkpoint_2/
            └── core/
```

## Shared Utilities: case_utils.py

```python
"""Shared test utilities for layered_config_synthesizer."""

import json
import subprocess
from pathlib import Path
from typing import Any

import yaml


CASES_DIR = Path(__file__).parent / "cases"


def discover_cases(checkpoint_name: str, group_name: str) -> list[dict]:
    """Discover test cases for a checkpoint and group."""
    group_dir = CASES_DIR / checkpoint_name / group_name

    if not group_dir.exists():
        return []

    cases = []
    for case_dir in sorted(group_dir.iterdir()):
        if not case_dir.is_dir():
            continue

        case = load_case(case_dir)
        if case:
            cases.append(case)

    return cases


def load_case(case_dir: Path) -> dict | None:
    """Load a single test case from directory."""
    case_file = case_dir / "case.yaml"
    if not case_file.exists():
        return None

    case_def = yaml.safe_load(case_file.read_text())

    # Load input files
    input_dir = case_dir / "input"
    input_files = {}
    if input_dir.exists():
        for file_path in input_dir.iterdir():
            if file_path.is_file():
                input_files[file_path.name] = file_path.read_text()

    # Load expected output
    expected_dir = case_dir / "expected"
    expected = {}
    if expected_dir.exists():
        for file_path in expected_dir.iterdir():
            if file_path.is_file():
                content = file_path.read_text()
                if file_path.suffix in (".yaml", ".yml"):
                    expected[file_path.name] = yaml.safe_load(content)
                elif file_path.suffix == ".json":
                    expected[file_path.name] = json.loads(content)
                else:
                    expected[file_path.name] = content

    return {
        "id": case_dir.name,
        "case": case_def,
        "input_files": input_files,
        "expected": expected,
        "path": case_dir,
    }


def run_command(entrypoint_argv: list[str], input_files: dict, tmp_path: Path,
                args: list[str] = None) -> subprocess.CompletedProcess:
    """Run synthesizer with input files."""
    # Create input directory
    input_dir = tmp_path / "input"
    input_dir.mkdir(exist_ok=True)

    # Write input files
    for filename, content in input_files.items():
        (input_dir / filename).write_text(content)

    # Build command
    cmd = entrypoint_argv.copy()
    cmd.extend(["--input", str(input_dir)])

    if args:
        cmd.extend(args)

    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=tmp_path,
        timeout=30,
    )


def assert_output_matches(result: subprocess.CompletedProcess,
                          expected: dict,
                          output_path: Path = None) -> None:
    """Assert command output matches expected."""
    assert result.returncode == 0, f"Command failed: {result.stderr}"

    if output_path and output_path.exists():
        actual = yaml.safe_load(output_path.read_text())
    else:
        actual = yaml.safe_load(result.stdout)

    # Get expected output (first file in expected/)
    expected_output = list(expected.values())[0] if expected else {}

    assert actual == expected_output, f"Mismatch:\nActual: {actual}\nExpected: {expected_output}"


def assert_subset_match(actual: dict, expected: dict) -> None:
    """Assert actual contains all keys/values from expected."""
    for key, value in expected.items():
        assert key in actual, f"Missing key: {key}"
        if isinstance(value, dict):
            assert_subset_match(actual[key], value)
        else:
            assert actual[key] == value, f"Mismatch for {key}: {actual[key]} != {value}"
```

## Test Implementation

### conftest.py

```python
"""Pytest configuration for layered_config_synthesizer."""

import shlex
from pathlib import Path

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


@pytest.fixture(scope="session")
def cases_dir():
    return Path(__file__).parent / "cases"
```

### test_checkpoint_1.py

```python
"""Tests for checkpoint_1: Basic config merging."""

import pytest

from case_utils import discover_cases, run_command, assert_output_matches


CORE_CASES = discover_cases("checkpoint_1", "core")
ERROR_CASES = discover_cases("checkpoint_1", "errors")


@pytest.mark.parametrize("case", CORE_CASES, ids=[c["id"] for c in CORE_CASES])
def test_core_cases(entrypoint_argv, tmp_path, case):
    """Core: Config merging works correctly."""
    result = run_command(
        entrypoint_argv,
        case["input_files"],
        tmp_path,
        case["case"].get("args", []),
    )

    assert_output_matches(result, case["expected"])


@pytest.mark.error
@pytest.mark.parametrize("case", ERROR_CASES, ids=[c["id"] for c in ERROR_CASES])
def test_error_cases(entrypoint_argv, tmp_path, case):
    """Error: Invalid configs handled gracefully."""
    result = run_command(
        entrypoint_argv,
        case["input_files"],
        tmp_path,
        case["case"].get("args", []),
    )

    expected = case["expected"]
    assert result.returncode == expected.get("exit_code", 1)
```

### test_checkpoint_2.py

```python
"""Tests for checkpoint_2: Includes and references."""

import pytest

from case_utils import discover_cases, run_command, assert_output_matches


CORE_CASES = discover_cases("checkpoint_2", "core")
FUNCTIONALITY_CASES = discover_cases("checkpoint_2", "functionality")


@pytest.mark.parametrize("case", CORE_CASES, ids=[c["id"] for c in CORE_CASES])
def test_core_cases(entrypoint_argv, tmp_path, case):
    """Core: Include resolution works."""
    result = run_command(
        entrypoint_argv,
        case["input_files"],
        tmp_path,
        case["case"].get("args", []),
    )

    assert_output_matches(result, case["expected"])


@pytest.mark.functionality
@pytest.mark.parametrize("case", FUNCTIONALITY_CASES, ids=[c["id"] for c in FUNCTIONALITY_CASES])
def test_functionality_cases(entrypoint_argv, tmp_path, case):
    """Functionality: Advanced features."""
    result = run_command(
        entrypoint_argv,
        case["input_files"],
        tmp_path,
        case["case"].get("args", []),
    )

    assert_output_matches(result, case["expected"])
```

## Test Case Structure

### case.yaml

```yaml
description: Merge two configs with override
args:
  - --strategy
  - deep-merge
```

### input/ Directory

```
input/
├── base.yaml
└── override.yaml
```

**base.yaml:**
```yaml
database:
  host: localhost
  port: 5432
logging:
  level: info
```

**override.yaml:**
```yaml
database:
  port: 5433
logging:
  level: debug
```

### expected/ Directory

```
expected/
└── output.yaml
```

**output.yaml:**
```yaml
database:
  host: localhost
  port: 5433
logging:
  level: debug
```

## Key Patterns

### Pattern 1: Shared Utilities Module

```python
# case_utils.py - Reused across all test files
from case_utils import discover_cases, run_command, assert_output_matches
```

### Pattern 2: Input Directory Pattern

```python
def run_command(entrypoint_argv, input_files, tmp_path, args=None):
    # Create input directory
    input_dir = tmp_path / "input"
    input_dir.mkdir(exist_ok=True)

    # Write all input files
    for filename, content in input_files.items():
        (input_dir / filename).write_text(content)

    # Pass input directory to command
    cmd.extend(["--input", str(input_dir)])
```

### Pattern 3: Expected Directory Pattern

```python
# Load expected output from expected/ directory
expected_dir = case_dir / "expected"
expected = {}
for file_path in expected_dir.iterdir():
    if file_path.suffix in (".yaml", ".yml"):
        expected[file_path.name] = yaml.safe_load(file_path.read_text())
```

### Pattern 4: Flexible Assertion

```python
def assert_subset_match(actual: dict, expected: dict) -> None:
    """Assert actual contains all keys/values from expected.

    Allows actual to have extra fields not in expected.
    """
    for key, value in expected.items():
        assert key in actual
        if isinstance(value, dict):
            assert_subset_match(actual[key], value)
        else:
            assert actual[key] == value
```

## Benefits of This Pattern

1. **Code reuse** - `case_utils.py` shared across checkpoints
2. **Maintainability** - Test logic separate from test data
3. **Flexibility** - Easy to add new cases (just add directories)
4. **Clarity** - Input and expected in separate directories

## When to Use This Pattern

**Use shared utilities when**:
- Multiple checkpoints with similar test patterns
- Complex input setup required
- Custom validation logic needed
- Team maintains many test cases

**Skip shared utilities when**:
- Single checkpoint
- Simple inline tests sufficient
- Rapid prototyping phase

## Comparison with Other Examples

| Aspect | layered_config | etl_pipeline | file_backup |
|--------|----------------|--------------|-------------|
| Utilities | Shared module | Inline | Inline |
| Input | Directory | stdin | Files + args |
| Expected | Directory | Inline | JSONL file |
| Complexity | High | Low | Medium |

## Running Locally

```bash
cd problems/layered_config_synthesizer

# Run tests
pytest tests/ \
  --entrypoint="python solutions/reference/synthesizer.py" \
  --checkpoint=checkpoint_1 \
  -v

# Run specific checkpoint
pytest tests/test_checkpoint_2.py \
  --entrypoint="python solutions/reference/synthesizer.py" \
  --checkpoint=checkpoint_2 \
  -v
```

## Next Steps

- [file_backup Example](file_backup.md) - Simpler parametrized pattern
- [etl_pipeline Example](etl_pipeline.md) - Inline tests pattern
- [Parametrized Cases](../patterns/parametrized-cases.md) - More patterns
