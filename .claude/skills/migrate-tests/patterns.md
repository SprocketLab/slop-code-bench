# Migration Patterns Reference

This document provides detailed patterns for migrating specific problem types.

## CLI Adapter Migrations

### Pattern: Simple CLI with Arguments

**Old loader.py pattern:**
```python
class Loader(BaseLoader):
    def load_case(self, case_directory, group_config):
        case_yaml = yaml.load((case_directory / "case.yaml").open())
        expected = json.loads((case_directory / "expected.jsonl").read_text())

        case = CLICase(
            id=case_directory.name,
            arguments=case_yaml["arguments"],
            input_files=[...],
        )
        expected = CLIResult(
            id=case_directory.name,
            status_code=0,
            output=expected,
        )
        return case, expected
```

**New pytest pattern:**
```python
import subprocess
import json
import pytest

def run_cli(entrypoint_argv, *args, timeout=30):
    cmd = entrypoint_argv + list(args)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)

# Convert case.yaml content directly into test data
DAILY_BACKUP_CASE = {
    "args": ["--now", "2025-09-10T03:30:00Z", "--schedule", "schedule.yaml"],
    "expected": [
        {"event": "SCHEDULE_PARSED", "timezone": "UTC", "jobs_total": 1},
        {"event": "JOB_STARTED", "job_id": "daily-home"},
        {"event": "JOB_COMPLETED", "job_id": "daily-home", "selected": 3},
    ],
}

def test_daily_backup(entrypoint_argv, tmp_path):
    # Create input file
    schedule = tmp_path / "schedule.yaml"
    schedule.write_text(yaml.dump({
        "version": 1,
        "timezone": "UTC",
        "jobs": [{"id": "daily-home", "when": {"kind": "daily", "at": "03:30"}}]
    }))

    result = run_cli(entrypoint_argv, *DAILY_BACKUP_CASE["args"])
    assert result.returncode == 0

    events = [json.loads(line) for line in result.stdout.strip().split("\n")]
    assert events == DAILY_BACKUP_CASE["expected"]
```

### Pattern: CLI with Input Files

**Old case.yaml:**
```yaml
arguments: --config config.yaml --mount {{static:files}}
input_files:
  - path: config.yaml
    file_type: yaml
    content:
      setting: value
```

**New pytest pattern:**
```python
import yaml
from pathlib import Path

@pytest.fixture
def config_file(tmp_path):
    """Create config file for test."""
    config = tmp_path / "config.yaml"
    config.write_text(yaml.dump({"setting": "value"}))
    return config

def test_with_config(entrypoint_argv, config_file, data_dir):
    result = run_cli(
        entrypoint_argv,
        "--config", str(config_file),
        "--mount", str(data_dir),
    )
    assert result.returncode == 0
```

### Pattern: Static Asset References

**Old pattern ({{static:name}}):**
```yaml
arguments: --mount {{static:files}}
```

**New conftest.py:**
```python
@pytest.fixture(scope="session")
def files_dir():
    """Get files directory from static assets."""
    return Path(__file__).parent / "assets" / "files"
```

**New test:**
```python
def test_with_static_assets(entrypoint_argv, files_dir):
    result = run_cli(entrypoint_argv, "--mount", str(files_dir))
```

## API Adapter Migrations

### Pattern: API with JSON Cases

**Old loader.py (API pattern):**
```python
class Loader(BaseLoader):
    def __call__(self, group, store):
        case_file = group_path / f"{group.name}.json"
        cases = json.load(case_file.open())
        for case_name, case_dict in cases.items():
            yield APICase(**case_dict["input"]), APIResult(**case_dict["expected"])
```

**Old case JSON:**
```json
{
  "create_item": {
    "input": {
      "method": "POST",
      "path": "/v1/items",
      "body": {"name": "test"}
    },
    "expected": {
      "status_code": 201,
      "output": {"id": 1, "name": "test"}
    },
    "order": 1
  }
}
```

**New pytest pattern:**
```python
import pytest
import requests
import subprocess
import time

@pytest.fixture(scope="module")
def api_server(entrypoint_argv):
    """Start API server and yield base URL."""
    process = subprocess.Popen(
        entrypoint_argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    base_url = "http://localhost:8000"

    # Wait for server ready
    for _ in range(50):
        try:
            requests.get(f"{base_url}/health", timeout=0.5)
            break
        except requests.exceptions.RequestException:
            time.sleep(0.1)
    else:
        process.terminate()
        raise RuntimeError("Server failed to start")

    yield base_url

    process.terminate()
    process.wait()


CREATE_ITEM = {
    "method": "POST",
    "path": "/v1/items",
    "body": {"name": "test"},
    "expected_status": 201,
    "expected_body": {"id": 1, "name": "test"},
}


def test_create_item(api_server):
    """Core: Create an item via API."""
    response = requests.request(
        method=CREATE_ITEM["method"],
        url=f"{api_server}{CREATE_ITEM['path']}",
        json=CREATE_ITEM["body"],
    )
    assert response.status_code == CREATE_ITEM["expected_status"]
    assert response.json() == CREATE_ITEM["expected_body"]
```

### Pattern: Stateful API Tests (CaseStore)

**Old ExecutionServerStore pattern:**
```python
class ExecutionServerStore(CaseStore):
    def __init__(self):
        self.execution_ids = {}
        self.cache_hits = 0

    def update(self, case, result, expected):
        self.execution_ids[case.id] = result.output["id"]
        if expected.output.get("cached"):
            self.cache_hits += 1

    def render_template(self, template):
        return template.replace("{{ran}}", str(self.num_ran))
```

**New pytest pattern (use fixtures for state):**
```python
import pytest

@pytest.fixture(scope="module")
def api_state():
    """Track state across API tests."""
    return {
        "execution_ids": {},
        "cache_hits": 0,
        "num_ran": 0,
    }


def test_first_execution(api_server, api_state):
    """Core: First execution creates new entry."""
    response = requests.post(f"{api_server}/v1/execute", json={"cmd": "echo"})
    assert response.status_code == 201

    data = response.json()
    api_state["execution_ids"]["echo"] = data["id"]
    api_state["num_ran"] += 1


def test_cached_execution(api_server, api_state):
    """Core: Second identical execution uses cache."""
    response = requests.post(f"{api_server}/v1/execute", json={"cmd": "echo"})
    assert response.status_code == 200

    data = response.json()
    assert data.get("cached") is True
    api_state["cache_hits"] += 1


def test_stats_endpoint(api_server, api_state):
    """Core: Stats endpoint returns correct counts."""
    response = requests.get(f"{api_server}/v1/stats")
    data = response.json()

    assert data["ran"] == api_state["num_ran"]
    assert data["cache_hits"] == api_state["cache_hits"]
```

## Verifier Migration Patterns

### Pattern: JSONL Event Verification

**Old verifier.py:**
```python
class Verifier:
    def __call__(self, group_name, case_name, actual, expected):
        actual_events = [json.loads(l) for l in actual.output.split("\n")]
        expected_events = expected.output

        results = {}
        for i, (act, exp) in enumerate(zip(actual_events, expected_events)):
            results[f"event_{i}"] = VerificationResult(
                passed=act == exp,
                actual=act,
                expected=exp,
            )
        return results
```

**New pytest pattern:**
```python
def parse_jsonl_events(stdout):
    """Parse JSONL output to list of dicts."""
    return [json.loads(line) for line in stdout.strip().split("\n") if line]


def assert_events_match(actual_events, expected_events):
    """Assert events match with helpful diff on failure."""
    assert len(actual_events) == len(expected_events), (
        f"Event count mismatch: got {len(actual_events)}, expected {len(expected_events)}"
    )

    for i, (actual, expected) in enumerate(zip(actual_events, expected_events)):
        assert actual == expected, (
            f"Event {i} mismatch:\n"
            f"  Got:      {actual}\n"
            f"  Expected: {expected}"
        )


def test_event_output(entrypoint_argv):
    result = run_cli(entrypoint_argv, "--emit-events")
    actual = parse_jsonl_events(result.stdout)
    expected = [
        {"event": "START"},
        {"event": "PROCESS", "count": 5},
        {"event": "END"},
    ]
    assert_events_match(actual, expected)
```

### Pattern: Partial/Subset Verification

**Old verifier pattern:**
```python
def verify_subset(actual, expected):
    """Verify expected keys exist in actual with matching values."""
    for key, value in expected.items():
        if actual.get(key) != value:
            return False
    return True
```

**New pytest pattern:**
```python
def assert_dict_subset(actual, expected):
    """Assert expected is a subset of actual."""
    for key, value in expected.items():
        assert key in actual, f"Missing key: {key}"
        assert actual[key] == value, (
            f"Key '{key}' mismatch: got {actual[key]!r}, expected {value!r}"
        )


def test_api_response_subset(api_server):
    response = requests.get(f"{api_server}/v1/item/1")
    data = response.json()

    # Only verify specific fields, ignore others (like timestamps)
    assert_dict_subset(data, {
        "id": 1,
        "name": "test",
        "status": "active",
    })
```

### Pattern: Flexible Field Verification

**Old verifier with special handling:**
```python
def verify_duration(actual, expected):
    """Duration should be within 10% of expected."""
    return abs(actual - expected) / expected < 0.1
```

**New pytest pattern:**
```python
def test_execution_duration(api_server):
    response = requests.post(f"{api_server}/v1/execute", json={"cmd": "sleep 1"})
    data = response.json()

    # Duration should be approximately 1 second (within 20%)
    assert 0.8 <= data["duration"] <= 1.2, f"Duration {data['duration']} out of range"
```

## Regression Test Patterns

### Old Regressions (config.yaml)

```yaml
checkpoints:
  checkpoint_2:
    regressions:
      - checkpoint: checkpoint_1
        groups: [core, hidden]
```

### New Regressions (automatic)

Regressions are handled automatically by pytest_runner:
- Tests from `test_checkpoint_1.py` become REGRESSION when running checkpoint_2
- No config changes needed
- GroupType determined by `_determine_group_type()` in pytest_runner.py

**If you need checkpoint-aware test logic:**
```python
def test_feature(entrypoint_argv, checkpoint_name):
    result = run_cli(entrypoint_argv, "--feature")

    if checkpoint_name == "checkpoint_1":
        # Original behavior
        assert result.stdout == "basic output"
    else:
        # Extended behavior in later checkpoints
        assert "enhanced" in result.stdout
```

## File Structure Migration

### Old Structure
```
problems/my_problem/
├── config.yaml              # Complex with adapter, loader, groups
├── loader.py                # Custom loader class
├── verifier.py              # Custom verifier class
├── files/                   # Static assets
├── checkpoint_1/
│   ├── spec.md
│   ├── core/
│   │   ├── case_1/
│   │   │   ├── case.yaml
│   │   │   └── expected.jsonl
│   │   └── case_2/
│   │       ├── case.yaml
│   │       └── expected.jsonl
│   └── hidden/              # Functionality tests
│       └── ...
└── checkpoint_2/
    └── ...
```

### New Structure
```
problems/my_problem/
├── config.yaml              # Simplified
├── files/                   # Static assets (unchanged)
├── checkpoint_1.md          # Spec (renamed from checkpoint_1/spec.md)
├── checkpoint_2.md
└── tests/
    ├── conftest.py          # Fixtures
    ├── test_checkpoint_1.py # All checkpoint 1 tests
    └── test_checkpoint_2.py # All checkpoint 2 tests
```

## Checklist for Each Migration

- [ ] Read and understand `loader.py`
- [ ] Read and understand `verifier.py` (if exists)
- [ ] Inventory all test cases in `checkpoint_N/{group}/`
- [ ] Create `tests/conftest.py` with fixtures
- [ ] Create `tests/test_checkpoint_N.py` for each checkpoint
- [ ] Convert each case.yaml + expected.jsonl to pytest test
- [ ] Add `@pytest.mark.functionality` for hidden/functionality tests
- [ ] Add `@pytest.mark.error` for error handling tests
- [ ] Update `config.yaml` to new format
- [ ] Delete old files: `loader.py`, `verifier.py`, case directories
- [ ] Run tests locally to verify: `uv run pytest problems/my_problem/tests/`
