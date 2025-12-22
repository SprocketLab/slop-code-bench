# Quick Reference: Problem Authoring Cheat Sheet

One-page reference for creating pytest-based evaluation problems in SCBench.

## Minimal Files Required

Every problem needs exactly 4 things:

1. **`config.yaml`** - Problem metadata and checkpoint definitions
2. **`checkpoint_N.md`** - Specification for each checkpoint
3. **`tests/conftest.py`** - Required pytest fixtures
4. **`tests/test_checkpoint_N.py`** - Test files for each checkpoint

## 5-Step Problem Creation

```bash
# 1. Create structure
mkdir -p problems/my_problem/tests

# 2. Create config.yaml
cat > problems/my_problem/config.yaml << 'EOF'
version: 1
name: my_problem
description: My first evaluation problem
entry_file: main.py
timeout: 20
tags:
  - cli

checkpoints:
  checkpoint_1:
    version: 1
    order: 1
    state: Core Tests
EOF

# 3. Create conftest.py
cat > problems/my_problem/tests/conftest.py << 'EOF'
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
EOF

# 4. Write spec
echo "# Checkpoint 1: Build a CLI tool..." > problems/my_problem/checkpoint_1.md

# 5. Write tests
# (see test file template below)
```

## Directory Structure

```
problems/my_problem/
├── config.yaml              # Problem metadata
├── checkpoint_1.md          # Spec for checkpoint 1
├── checkpoint_2.md          # Spec for checkpoint 2
└── tests/
    ├── conftest.py          # Required fixtures
    ├── test_checkpoint_1.py # Tests for checkpoint 1
    ├── test_checkpoint_2.py # Tests for checkpoint 2
    ├── data/                # External test case data (optional)
    │   └── checkpoint_1/
    │       ├── core/
    │       └── errors/
    └── assets/              # Static files for tests (optional)
```

## conftest.py Template

```python
"""Pytest configuration for my_problem evaluation."""

import shlex
from pathlib import Path

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


# Optional: Add fixtures for static assets
@pytest.fixture(scope="session")
def assets_dir():
    """Path to test assets directory."""
    return Path(__file__).parent / "assets"
```

## Test File Templates

### Inline Tests (Simple Problems)

```python
"""Tests for checkpoint_1."""

import json
import subprocess

import pytest


def run_command(entrypoint_argv, input_data):
    """Run submission with JSON input via stdin."""
    return subprocess.run(
        entrypoint_argv,
        input=json.dumps(input_data),
        capture_output=True,
        text=True,
        timeout=10,
    )


# Core tests (unmarked - must pass)
def test_basic_case(entrypoint_argv):
    """Core: Basic functionality works."""
    result = run_command(entrypoint_argv, {"key": "value"})
    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert output["status"] == "ok"


def test_another_core(entrypoint_argv):
    """Core: Another essential test."""
    ...


# Functionality tests (nice to have)
@pytest.mark.functionality
def test_advanced_feature(entrypoint_argv):
    """Functionality: Advanced feature works."""
    ...


# Error tests (error handling)
@pytest.mark.error
def test_invalid_input(entrypoint_argv):
    """Error: Invalid input returns error."""
    result = run_command(entrypoint_argv, {"invalid": True})
    assert result.returncode == 1
    output = json.loads(result.stdout)
    assert output["status"] == "error"
```

### Parametrized Tests (External Case Files)

```python
"""Tests for checkpoint_1 with external case files."""

import json
import subprocess
from pathlib import Path

import pytest
import yaml

CHECKPOINT_DIR = Path(__file__).parent / "data" / "checkpoint_1"


def load_cases(group_dir):
    """Load test cases from a group directory."""
    cases = []
    for case_dir in sorted(group_dir.iterdir()):
        if not case_dir.is_dir():
            continue
        case_yaml = yaml.safe_load((case_dir / "case.yaml").read_text())
        expected = json.loads((case_dir / "expected.json").read_text())
        cases.append({"id": case_dir.name, "case": case_yaml, "expected": expected})
    return cases


CORE_CASES = load_cases(CHECKPOINT_DIR / "core")
ERROR_CASES = load_cases(CHECKPOINT_DIR / "errors")


@pytest.mark.parametrize("case", CORE_CASES, ids=[c["id"] for c in CORE_CASES])
def test_core_cases(entrypoint_argv, case):
    """Core cases from external files."""
    result = subprocess.run(
        entrypoint_argv + case["case"]["args"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
    assert json.loads(result.stdout) == case["expected"]


@pytest.mark.error
@pytest.mark.parametrize("case", ERROR_CASES, ids=[c["id"] for c in ERROR_CASES])
def test_error_cases(entrypoint_argv, case):
    """Error cases from external files."""
    result = subprocess.run(
        entrypoint_argv + case["case"]["args"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode != 0
```

## config.yaml Reference

### Minimal Config

```yaml
version: 1
name: my_problem
description: Short description
entry_file: main.py
timeout: 20
tags:
  - cli

checkpoints:
  checkpoint_1:
    version: 1
    order: 1
    state: Core Tests
```

### Full Config

```yaml
version: 1
name: my_problem
description: |
  Multi-line description of the problem.
  Supports markdown.

category: data-transformation
difficulty: Medium
author: Your Name
entry_file: main.py
timeout: 20

tags:
  - cli
  - json-parsing
  - data-transformation

# Static assets available to tests
static_assets:
  files:
    path: files   # problems/my_problem/files/

# Custom pytest markers (optional)
markers:
  slow:
    description: slow tests
    group: FUNCTIONALITY
  integration:
    description: integration tests
    group: FUNCTIONALITY

# Additional pytest dependencies (optional)
test_dependencies:
  - pyyaml
  - requests

checkpoints:
  checkpoint_1:
    version: 1
    order: 1
    state: Core Tests
    timeout: 30        # Override default
    include_prior_tests: true  # Include tests from prior checkpoints

  checkpoint_2:
    version: 1
    order: 2
    state: Core Tests
    include_prior_tests: true
```

## Test Markers

| Marker | GroupType | Description |
|--------|-----------|-------------|
| *(none)* | CORE | Must pass - essential functionality |
| `@pytest.mark.functionality` | FUNCTIONALITY | Nice to have - advanced features |
| `@pytest.mark.error` | ERROR | Error handling - edge cases |
| `@pytest.mark.regression` | REGRESSION | Prior checkpoint tests |

Prior checkpoint tests automatically become REGRESSION tests.

## Checkpoint State Values

| State | Meaning |
|-------|---------|
| `Draft` | Work in progress |
| `Core Tests` | Core tests written |
| `Full Tests` | All tests written |
| `Verified` | Tests validated with solutions |

## Testing Commands

```bash
# Run agent on problem
slop-code run \
  --agent claude_code \
  --model anthropic/opus-4.5 \
  --environment configs/environments/docker-python3.12-uv.yaml \
  --prompt configs/prompts/just-solve.jinja \
  --problem my_problem

# Evaluate results
slop-code eval outputs/<run-directory>/

# Run tests locally (for development)
cd problems/my_problem
pytest tests/ \
  --entrypoint="python main.py" \
  --checkpoint=checkpoint_1 \
  -v
```

## Common Patterns

### CLI with Arguments

```python
def test_with_args(entrypoint_argv, tmp_path):
    input_file = tmp_path / "input.json"
    input_file.write_text('{"key": "value"}')

    result = subprocess.run(
        entrypoint_argv + ["--input", str(input_file)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
```

### Stream-Based (stdin/stdout)

```python
def test_stream(entrypoint_argv):
    result = subprocess.run(
        entrypoint_argv,
        input='{"data": "value"}',
        capture_output=True,
        text=True,
    )
    output = json.loads(result.stdout)
    assert output["status"] == "ok"
```

### JSONL Output

```python
def parse_jsonl(text):
    return [json.loads(line) for line in text.splitlines() if line.strip()]

def test_jsonl_output(entrypoint_argv):
    result = subprocess.run(entrypoint_argv, capture_output=True, text=True)
    events = parse_jsonl(result.stdout)
    assert len(events) == 3
    assert events[0]["event"] == "START"
```

### Checkpoint-Aware Tests

```python
def test_feature(entrypoint_argv, checkpoint_name):
    result = run_command(entrypoint_argv, {"data": "test"})
    output = json.loads(result.stdout)

    # Feature only available in checkpoint_2+
    if checkpoint_name in {"checkpoint_2", "checkpoint_3"}:
        assert "new_field" in output
    else:
        assert "new_field" not in output
```

## Common Issues

| Issue | Solution |
|-------|----------|
| Tests not discovered | Check file is named `test_checkpoint_N.py` |
| Missing fixtures | Ensure `conftest.py` has `pytest_addoption` and fixtures |
| Import errors | Add `__init__.py` if using shared modules |
| Timeout errors | Increase timeout in config.yaml or test |
| Static assets not found | Check `static_assets` path in config.yaml |

## Next Steps

- **Tutorial:** [Create Your First Problem](tutorial.md)
- **Structure:** [Directory Layout](structure.md)
- **Config Reference:** [Full Schema](config-schema.md)
- **Pytest Details:** [Pytest System Overview](pytest/README.md)
- **Examples:** [file_backup](examples/file_backup.md), [etl_pipeline](examples/etl_pipeline.md)
