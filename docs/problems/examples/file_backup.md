# Example: file_backup

Complete walkthrough of the `file_backup` problem, a CLI-based backup scheduler.

## Problem Overview

**What it tests**: A CLI backup scheduler that:
1. Parses YAML schedule files
2. Determines which backup jobs are due
3. Simulates running backups
4. Emits JSON Lines event history

**Key patterns demonstrated**:
- CLI argument parsing
- YAML input, JSONL output
- Parametrized tests from external files
- Static assets for test data

## Directory Structure

```
problems/file_backup/
├── config.yaml              # Problem configuration
├── checkpoint_1.md          # Spec: Basic scheduling
├── checkpoint_2.md          # Spec: Execution modes
├── checkpoint_3.md          # Spec: Verification
├── checkpoint_4.md          # Spec: Incremental backup
├── tests/
│   ├── conftest.py          # Pytest fixtures
│   ├── test_checkpoint_1.py # Tests for checkpoint 1
│   ├── test_checkpoint_2.py # Tests for checkpoint 2
│   ├── test_checkpoint_3.py # Tests for checkpoint 3
│   ├── test_checkpoint_4.py # Tests for checkpoint 4
│   └── data/
│       └── checkpoint_1/
│           ├── core/
│           │   ├── daily_due_simple/
│           │   │   ├── case.yaml
│           │   │   └── expected.jsonl
│           │   └── multiple_jobs/
│           │       ├── case.yaml
│           │       └── expected.jsonl
│           └── errors/
│               └── error_yaml_parse/
│                   ├── case.yaml
│                   └── expected.yaml
├── static_assets/
│   └── files/               # Test data files
│       ├── A/
│       │   └── B/C/D.py
│       └── M.py
└── solutions/
    └── reference/
        └── backup_scheduler.py
```

## Configuration

### config.yaml

```yaml
version: 1
name: file_backup
description: CLI backup scheduler that parses YAML and emits JSONL events
category: scheduling
difficulty: Medium
entry_file: backup_scheduler.py
timeout: 20

tags:
  - cli
  - scheduling
  - jsonl
  - yaml

static_assets:
  files:
    path: static_assets/files

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

  checkpoint_3:
    version: 1
    order: 3
    state: Full Tests
    include_prior_tests: true

  checkpoint_4:
    version: 1
    order: 4
    state: Verified
    include_prior_tests: true
```

## Test Implementation

### conftest.py

```python
"""Pytest configuration for file_backup evaluation."""

import os
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
def assets_dir():
    """Path to test assets."""
    return Path(__file__).parent / "assets"


@pytest.fixture(scope="session")
def files_dir():
    """Path to static files directory."""
    # Use environment variable if set (for evaluation)
    env_path = os.environ.get("SCBENCH_ASSET_FILES")
    if env_path:
        return Path(env_path)
    # Fallback for local testing
    return Path(__file__).parent.parent / "static_assets" / "files"
```

### test_checkpoint_1.py

```python
"""Tests for checkpoint_1: Basic scheduling."""

import json
import subprocess
from pathlib import Path

import pytest
import yaml

CHECKPOINT_DIR = Path(__file__).parent / "data" / "checkpoint_1"


def parse_jsonl(text):
    """Parse JSONL output."""
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def load_cases(group_dir):
    """Load test cases from directory."""
    if not group_dir.exists():
        return []

    cases = []
    for case_dir in sorted(group_dir.iterdir()):
        if not case_dir.is_dir():
            continue

        case = yaml.safe_load((case_dir / "case.yaml").read_text())

        # Load expected output
        expected_jsonl = case_dir / "expected.jsonl"
        expected_yaml = case_dir / "expected.yaml"

        if expected_jsonl.exists():
            expected = {
                "exit_code": 0,
                "events": parse_jsonl(expected_jsonl.read_text()),
            }
        else:
            expected = yaml.safe_load(expected_yaml.read_text())

        cases.append({
            "id": case_dir.name,
            "case": case,
            "expected": expected,
        })

    return cases


def run_backup(entrypoint_argv, case, files_dir, tmp_path):
    """Run backup scheduler with case input."""
    # Create input files
    for file_spec in case.get("input_files", []):
        file_path = tmp_path / file_spec["path"]
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(file_spec["content"])

    # Build arguments
    args = case["arguments"]
    # Replace {{static:files}} placeholder
    args = args.replace("{{static:files}}", str(files_dir))

    cmd = entrypoint_argv + shlex.split(args)

    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=tmp_path,
        timeout=30,
    )


def strip_regression_fields(events):
    """Remove fields added in later checkpoints."""
    stripped = []
    for event in events:
        e = event.copy()
        # Fields added in checkpoint_2+
        for field in ["checksum", "size", "mode"]:
            e.pop(field, None)
        stripped.append(e)
    return stripped


CORE_CASES = load_cases(CHECKPOINT_DIR / "core")
ERROR_CASES = load_cases(CHECKPOINT_DIR / "errors")


@pytest.mark.parametrize("case", CORE_CASES, ids=[c["id"] for c in CORE_CASES])
def test_core_cases(entrypoint_argv, files_dir, tmp_path, case, checkpoint_name):
    """Core cases: Valid inputs, expected outputs."""
    result = run_backup(entrypoint_argv, case["case"], files_dir, tmp_path)

    assert result.returncode == 0, f"Failed: {result.stderr}"

    events = parse_jsonl(result.stdout)
    expected_events = case["expected"]["events"]

    # Strip regression fields for comparison when running as regression
    if checkpoint_name != "checkpoint_1":
        events = strip_regression_fields(events)

    assert events == expected_events


@pytest.mark.error
@pytest.mark.parametrize("case", ERROR_CASES, ids=[c["id"] for c in ERROR_CASES])
def test_error_cases(entrypoint_argv, files_dir, tmp_path, case):
    """Error cases: Invalid inputs, error handling."""
    result = run_backup(entrypoint_argv, case["case"], files_dir, tmp_path)

    expected = case["expected"]
    assert result.returncode == expected.get("exit_code", 1)

    if "stderr_contains" in expected:
        assert expected["stderr_contains"] in result.stderr
```

## Test Data Structure

### Core Case: daily_due_simple

**case.yaml:**
```yaml
arguments: >-
  --schedule schedule.yaml
  --now 2025-09-10T03:30:00Z
  --duration 24
  --mount {{static:files}}

input_files:
  - path: schedule.yaml
    file_type: yaml
    content: |
      version: 1
      timezone: "UTC"
      jobs:
        - id: "daily-home"
          enabled: true
          when:
            kind: "daily"
            at: "03:30"
          source: mount://
          exclude: []
```

**expected.jsonl:**
```jsonl
{"event":"job_start","job_id":"daily-home","timestamp":"2025-09-10T03:30:00+00:00"}
{"event":"file_backed_up","job_id":"daily-home","file":"A/B/C/D.py","timestamp":"2025-09-10T03:30:00+00:00"}
{"event":"file_backed_up","job_id":"daily-home","file":"A/I.py","timestamp":"2025-09-10T03:30:00+00:00"}
{"event":"file_backed_up","job_id":"daily-home","file":"M.py","timestamp":"2025-09-10T03:30:00+00:00"}
{"event":"job_end","job_id":"daily-home","timestamp":"2025-09-10T03:30:00+00:00"}
```

### Error Case: error_yaml_parse

**case.yaml:**
```yaml
arguments: --schedule bad.yaml --now 2025-09-10T03:30:00Z

input_files:
  - path: bad.yaml
    file_type: yaml
    content: |
      invalid yaml {{{
```

**expected.yaml:**
```yaml
exit_code: 3
stderr_contains: "ERROR"
```

## Key Patterns

### Pattern 1: Parametrized Tests from Files

```python
CORE_CASES = load_cases(CHECKPOINT_DIR / "core")

@pytest.mark.parametrize("case", CORE_CASES, ids=[c["id"] for c in CORE_CASES])
def test_core_cases(entrypoint_argv, case):
    ...
```

### Pattern 2: Static Asset Placeholder

```yaml
# In case.yaml
arguments: --mount {{static:files}}

# Replaced at runtime with actual path
```

### Pattern 3: Regression Field Stripping

```python
def strip_regression_fields(events):
    """Remove fields added in later checkpoints."""
    stripped = []
    for event in events:
        e = event.copy()
        for field in ["checksum", "size", "mode"]:
            e.pop(field, None)
        stripped.append(e)
    return stripped
```

### Pattern 4: JSONL Output Parsing

```python
def parse_jsonl(text):
    return [json.loads(line) for line in text.splitlines() if line.strip()]
```

## Checkpoint Progression

| Checkpoint | Focus | Tests |
|------------|-------|-------|
| 1 | Parse YAML, emit events | 10 core, 3 error |
| 2 | Actual backup execution | 5 core |
| 3 | Verification mode | 4 core |
| 4 | Incremental backup | 4 functionality |

## Running Locally

```bash
cd problems/file_backup

# Run tests against reference solution
pytest tests/ \
  --entrypoint="python solutions/reference/backup_scheduler.py" \
  --checkpoint=checkpoint_1 \
  -v

# Run with SCBench
slop-code run \
  --agent claude_code \
  --model anthropic/opus-4.5 \
  --environment configs/environments/docker-python3.12-uv.yaml \
  --prompt configs/prompts/just-solve.jinja \
  --problem file_backup
```

## Next Steps

- [etl_pipeline Example](etl_pipeline.md) - Stream-based testing
- [CLI Testing Patterns](../patterns/cli-testing.md) - More CLI patterns
- [Parametrized Cases](../patterns/parametrized-cases.md) - Loading external data
