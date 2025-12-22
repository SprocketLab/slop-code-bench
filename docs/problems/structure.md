# Problem Structure Guide

Visual guide to problem directory structure with annotations explaining each file's purpose.

## Overview

Every problem follows this hierarchy:

```
Problem
├── Configuration (config.yaml)
├── Specifications (checkpoint_N.md)
├── Tests (tests/)
│   ├── conftest.py (fixtures)
│   ├── test_checkpoint_N.py (test files)
│   └── data/ (optional test data)
└── Assets (optional shared files)
```

## Complete Structure

```
problems/{problem_name}/
│
├── config.yaml                  ─────────────────────────────
│   version: 1                   │ Problem Configuration     │
│   name: problem_name           │ • Unique identifier       │
│   entry_file: main.py          │ • Entry point            │
│   checkpoints:                 │ • Checkpoint definitions  │
│     checkpoint_1:              │ • Static assets          │
│       version: 1               │ • Test dependencies      │
│       order: 1                 └─────────────────────────────
│       state: Core Tests
│
├── checkpoint_1.md              ─────────────────────────────
│   # Checkpoint 1: Feature      │ Specification            │
│   Build a tool that...         │ • What agents must build │
│                                │ • Requirements           │
│                                │ • Examples               │
│                                └─────────────────────────────
│
├── checkpoint_2.md              (Additional checkpoints)
│
├── tests/                       ═════════════════════════════
│   │                            ║ Pytest Test Directory    ║
│   │                            ═════════════════════════════
│   │
│   ├── conftest.py              ─────────────────────────────
│   │   def pytest_addoption():  │ Pytest Configuration     │
│   │   def entrypoint_argv():   │ • Required fixtures      │
│   │   def checkpoint_name():   │ • Optional helpers       │
│   │                            └─────────────────────────────
│   │
│   ├── test_checkpoint_1.py     ─────────────────────────────
│   │   def test_core():         │ Checkpoint 1 Tests       │
│   │   @pytest.mark.error       │ • Core tests (unmarked)  │
│   │   def test_error():        │ • Functionality tests    │
│   │   @pytest.mark.functionality│ • Error tests           │
│   │   def test_feature():      └─────────────────────────────
│   │
│   ├── test_checkpoint_2.py     (Additional test files)
│   │
│   ├── data/                    ─────────────────────────────
│   │   └── checkpoint_1/        │ External Test Data       │
│   │       ├── core/            │ • Optional               │
│   │       │   ├── case_1/      │ • For parametrized tests │
│   │       │   │   ├── case.yaml│ • Input/expected pairs   │
│   │       │   │   └── expected.json                       │
│   │       │   └── case_2/      └─────────────────────────────
│   │       └── errors/
│   │
│   └── assets/                  ─────────────────────────────
│       └── fixtures.json        │ Test Assets              │
│                                │ • Shared test files      │
│                                │ • Available via fixture  │
│                                └─────────────────────────────
│
├── static_assets/               ─────────────────────────────
│   └── reference_data/          │ Static Assets            │
│       └── data.csv             │ • Shared across tests    │
│                                │ • Defined in config.yaml │
│                                │ • Mounted for all tests  │
│                                └─────────────────────────────
│
└── solutions/                   ─────────────────────────────
    └── reference/               │ Reference Solution       │
        └── main.py              │ • For problem development│
                                 │ • Not used in evaluation │
                                 └─────────────────────────────
```

## File Roles

### config.yaml (Required)

Problem metadata and checkpoint definitions.

```yaml
version: 1
name: my_problem                 # Must match directory name
description: Short description
entry_file: main.py              # Agent creates this file
timeout: 20                      # Default test timeout

tags:
  - cli
  - json

checkpoints:
  checkpoint_1:
    version: 1                   # Increment when tests change
    order: 1                     # Execution order
    state: Core Tests            # Development state

  checkpoint_2:
    version: 1
    order: 2
    state: Core Tests
    include_prior_tests: true    # Run checkpoint_1 tests too

# Optional
static_assets:
  files:
    path: static_assets/files

test_dependencies:
  - pyyaml
  - requests

markers:
  slow:
    description: slow tests
    group: FUNCTIONALITY
```

### checkpoint_N.md (Required)

Specification for each checkpoint. Agents receive this to understand what to build.

```markdown
# Checkpoint N: Feature Name

Brief description of what to build.

## Requirements

1. Requirement one
2. Requirement two

## Interface

How to invoke the tool or API.

## Examples

Input/output examples help agents understand the expected behavior.

## Error Handling

What errors to handle and how.
```

### tests/conftest.py (Required)

Pytest configuration with required fixtures.

```python
"""Pytest configuration for my_problem evaluation."""

import shlex
from pathlib import Path

import pytest


def pytest_addoption(parser):
    """Register required CLI options."""
    parser.addoption("--entrypoint", required=True)
    parser.addoption("--checkpoint", required=True)


@pytest.fixture(scope="session")
def entrypoint_argv(request):
    """Submission command as argv list."""
    return shlex.split(request.config.getoption("--entrypoint"))


@pytest.fixture(scope="session")
def checkpoint_name(request):
    """Current checkpoint name."""
    return request.config.getoption("--checkpoint")


# Optional fixtures
@pytest.fixture(scope="session")
def assets_dir():
    """Path to test assets."""
    return Path(__file__).parent / "assets"
```

### tests/test_checkpoint_N.py (Required)

Test file for each checkpoint. Naming convention: `test_{checkpoint_name}.py`

```python
"""Tests for checkpoint_1."""

import subprocess
import pytest


def test_core_feature(entrypoint_argv):
    """Core: Essential functionality."""
    result = subprocess.run(entrypoint_argv, capture_output=True, text=True)
    assert result.returncode == 0


@pytest.mark.functionality
def test_advanced_feature(entrypoint_argv):
    """Functionality: Nice to have."""
    ...


@pytest.mark.error
def test_error_handling(entrypoint_argv):
    """Error: Handles invalid input."""
    ...
```

### tests/data/ (Optional)

External test case data for parametrized tests.

```
tests/data/
└── checkpoint_1/
    ├── core/
    │   ├── case_name/
    │   │   ├── case.yaml       # Test input
    │   │   └── expected.json   # Expected output
    │   └── another_case/
    │       ├── case.yaml
    │       └── expected.json
    └── errors/
        └── invalid_input/
            ├── case.yaml
            └── expected.yaml   # Error expectations
```

## Test Categories

| Marker | GroupType | Purpose |
|--------|-----------|---------|
| *(none)* | CORE | Must pass - essential functionality |
| `@pytest.mark.functionality` | FUNCTIONALITY | Nice to have - advanced features |
| `@pytest.mark.error` | ERROR | Error handling - edge cases |
| `@pytest.mark.regression` | REGRESSION | Prior checkpoint tests |

## Test Organization Patterns

### Pattern 1: Inline Tests (Simple)

All test data defined in Python. Good for small test suites.

```python
def test_example(entrypoint_argv):
    input_data = {"key": "value"}
    result = subprocess.run(
        entrypoint_argv,
        input=json.dumps(input_data),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
```

### Pattern 2: Parametrized Tests (Complex)

External test data loaded dynamically. Good for many test cases.

```python
CHECKPOINT_DIR = Path(__file__).parent / "data" / "checkpoint_1"

def load_cases(group_dir):
    cases = []
    for case_dir in sorted(group_dir.iterdir()):
        if case_dir.is_dir():
            case = yaml.safe_load((case_dir / "case.yaml").read_text())
            expected = json.loads((case_dir / "expected.json").read_text())
            cases.append({"id": case_dir.name, "case": case, "expected": expected})
    return cases

CORE_CASES = load_cases(CHECKPOINT_DIR / "core")

@pytest.mark.parametrize("case", CORE_CASES, ids=[c["id"] for c in CORE_CASES])
def test_core_cases(entrypoint_argv, case):
    result = run_case(entrypoint_argv, case)
    assert result == case["expected"]
```

### Pattern 3: Shared Utilities

Common utilities in a separate module.

```
tests/
├── conftest.py
├── case_utils.py              # Shared helpers
├── test_checkpoint_1.py
└── test_checkpoint_2.py
```

```python
# case_utils.py
def run_command(entrypoint_argv, input_data):
    return subprocess.run(
        entrypoint_argv,
        input=json.dumps(input_data),
        capture_output=True,
        text=True,
    )

# test_checkpoint_1.py
from case_utils import run_command

def test_example(entrypoint_argv):
    result = run_command(entrypoint_argv, {"key": "value"})
    assert result.returncode == 0
```

## Multi-Checkpoint Example

```
problems/etl_pipeline/
├── config.yaml
│   checkpoints:
│     checkpoint_1:
│       version: 1
│       order: 1
│       state: Core Tests
│     checkpoint_2:
│       version: 1
│       order: 2
│       state: Core Tests
│       include_prior_tests: true
│     checkpoint_3:
│       version: 1
│       order: 3
│       state: Core Tests
│       include_prior_tests: true
│
├── checkpoint_1.md              # Basic parsing
├── checkpoint_2.md              # Add filtering
├── checkpoint_3.md              # Add aggregation
│
└── tests/
    ├── conftest.py
    ├── test_checkpoint_1.py     # Parsing tests
    ├── test_checkpoint_2.py     # Filtering tests
    └── test_checkpoint_3.py     # Aggregation tests
```

When evaluating checkpoint_3:
1. `test_checkpoint_1.py` runs as REGRESSION tests
2. `test_checkpoint_2.py` runs as REGRESSION tests
3. `test_checkpoint_3.py` runs as CORE/FUNCTIONALITY/ERROR tests

## Naming Conventions

### Directories
- Problem: `snake_case` (e.g., `file_backup`, `etl_pipeline`)
- Tests: always `tests/`
- Data: always `data/`

### Files
- Config: always `config.yaml`
- Specs: `checkpoint_N.md` (e.g., `checkpoint_1.md`)
- Tests: `test_checkpoint_N.py` (e.g., `test_checkpoint_1.py`)
- Fixtures: always `conftest.py`

### Test Functions
- Core: `test_*` (no marker)
- Functionality: `test_*` with `@pytest.mark.functionality`
- Error: `test_*` with `@pytest.mark.error`

## Next Steps

- [Quick Reference](quick-reference.md) - Templates and commands
- [Config Schema](config-schema.md) - Full configuration reference
- [Markers](pytest/markers.md) - Test categorization details
- [Examples](examples/) - Real problem walkthroughs
