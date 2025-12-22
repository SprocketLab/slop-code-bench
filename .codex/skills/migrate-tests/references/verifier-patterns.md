# Verifier Patterns Reference

This document shows how to migrate custom verifier logic from the old `Verifier` class to pytest assertions.

## Old System vs New System

### Old: Verifier Class
```python
class Verifier:
    def __call__(self, group_name, case_name, actual, expected) -> dict:
        return {
            "status_code": VerificationResult(...),
            "output": VerificationResult(...),
        }
```

### New: Pytest Assertions
```python
def test_case(entrypoint_argv):
    result = run_command(...)
    assert result.returncode == 0
    assert result.stdout == expected_output
```

---

## Common Verification Patterns

### 1. Status Code

**Old:**
```python
verifiers.matches_status_code(actual.status_code, expected.status_code)
```

**New:**
```python
def test_success(entrypoint_argv):
    result = subprocess.run(entrypoint_argv, capture_output=True, text=True)
    assert result.returncode == 0

def test_error(entrypoint_argv):
    result = subprocess.run(entrypoint_argv + ["--invalid"], capture_output=True, text=True)
    assert result.returncode != 0
```

---

### 2. DeepDiff Comparison

**Old:**
```python
verifiers.deepdiff_verify(actual_output, expected_output)
```

**New:**
```python
from deepdiff import DeepDiff

def test_output(entrypoint_argv):
    result = run_command(...)
    actual = json.loads(result.stdout)
    expected = {"key": "value"}

    # Simple comparison
    assert actual == expected

    # Or with detailed diff on failure
    diff = DeepDiff(actual, expected, ignore_order=True)
    assert not diff, f"Mismatch: {diff}"
```

---

### 3. JSONL Parsing

**Old:**
```python
actual_events = parsers.parse_jsonl(actual.output)
verifiers.deepdiff_verify(actual_events, expected_events)
```

**New:**
```python
def parse_jsonl(text):
    return [json.loads(line) for line in text.strip().split("\n") if line]

def test_jsonl_output(entrypoint_argv):
    result = subprocess.run(entrypoint_argv, capture_output=True, text=True)
    events = parse_jsonl(result.stdout)
    expected = [
        {"event": "START"},
        {"event": "END"},
    ]
    assert events == expected
```

---

### 4. JSON Schema Validation

**Old:**
```python
verifiers.jsonschema_verify(actual.output, expected_schema)
```

**New:**
```python
import jsonschema

ERROR_SCHEMA = {
    "type": "object",
    "properties": {
        "error": {"type": "string"},
        "code": {"type": "integer"},
    },
    "required": ["error", "code"],
}

def test_error_response(api_server):
    response = requests.post(f"{api_server}/v1/invalid", json={})
    assert response.status_code == 400
    jsonschema.validate(response.json(), ERROR_SCHEMA)
```

---

### 5. Regex Matching

**Old:**
```python
verifiers.matches_regex(actual.stderr, expected_pattern)
```

**New:**
```python
import re

def test_error_message(entrypoint_argv):
    result = subprocess.run(entrypoint_argv + ["--invalid"], capture_output=True, text=True)
    assert result.returncode != 0
    assert re.search(r"Error: .+ not found", result.stderr)
```

---

### 6. Subset/Partial Match

**Old:**
```python
# Custom logic checking subset of fields
```

**New:**
```python
def assert_subset(actual, expected):
    """Assert expected keys/values exist in actual."""
    for key, value in expected.items():
        assert key in actual, f"Missing: {key}"
        assert actual[key] == value, f"{key}: {actual[key]} != {value}"

def test_api_response(api_server):
    response = requests.get(f"{api_server}/v1/item/1")
    # Only check specific fields (ignore timestamps, etc.)
    assert_subset(response.json(), {
        "id": 1,
        "name": "test",
    })
```

---

### 7. Duration/Timing

**Old:**
```python
def check_duration(actual, expected):
    if actual["duration"] <= expected["duration"]:
        return "Less than or equal to Expected"
```

**New:**
```python
def test_execution_timing(api_server):
    response = requests.post(f"{api_server}/v1/execute", json={"command": "sleep 1"})
    data = response.json()
    # Duration should be approximately 1 second
    assert 0.8 <= data["duration"] <= 1.5
```

---

### 8. UUID Validation

**Old:**
```python
output["id"] = validate_format(output.get("id", ""), "uuid")
```

**New:**
```python
import uuid

def is_valid_uuid(value):
    try:
        uuid.UUID(str(value))
        return True
    except ValueError:
        return False

def test_returns_uuid(api_server):
    response = requests.post(f"{api_server}/v1/create", json={})
    assert is_valid_uuid(response.json()["id"])
```

---

### 9. Float Comparison

**Old:**
```python
verifiers.deepdiff_verify(actual, expected, math_epsilon=1e-2)
```

**New:**
```python
import pytest

def test_float_values(entrypoint_argv):
    result = run_command(...)
    data = json.loads(result.stdout)
    assert data["average"] == pytest.approx(3.14, rel=0.01)
    assert data["stddev"] == pytest.approx(0.5, abs=0.01)
```

---

### 10. Event Ordering

**Old:**
```python
EVENT_ORDER = ["STARTED", "RUNNING", "COMPLETED"]
actual_sorted = sorted(actual, key=lambda x: (x["job_id"], EVENT_ORDER.index(x["event"])))
```

**New:**
```python
EVENT_ORDER = ["STARTED", "RUNNING", "COMPLETED"]

def normalize_events(events):
    def sort_key(e):
        idx = EVENT_ORDER.index(e["event"]) if e["event"] in EVENT_ORDER else 999
        return (e.get("job_id", 0), idx)
    return sorted(events, key=sort_key)

def test_event_order(entrypoint_argv):
    result = run_command(...)
    actual = parse_jsonl(result.stdout)
    expected = [{"event": "STARTED", "job_id": 1}, {"event": "COMPLETED", "job_id": 1}]
    assert normalize_events(actual) == normalize_events(expected)
```

---

### 11. File Content Verification

**Old:**
```python
for path, content in expected.files.items():
    verifiers.deepdiff_verify(actual.files[path], content)
```

**New:**
```python
def test_output_files(entrypoint_argv, tmp_path):
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    result = subprocess.run(
        entrypoint_argv + ["--output", str(output_dir)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0

    result_file = output_dir / "result.json"
    assert result_file.exists()
    assert json.loads(result_file.read_text()) == {"success": True}
```

---

### 12. Whitespace Normalization

**Old:**
```python
actual_stdout = actual.stdout.strip().replace(" ", "").replace("\n", "")
```

**New:**
```python
def normalize_whitespace(text):
    return "".join(text.split())

def test_output_ignoring_whitespace(entrypoint_argv):
    result = run_command(...)
    assert normalize_whitespace(result.stdout) == normalize_whitespace('{"key": "value"}')
```

---

### 13. Regression Field Handling

**Old:**
```python
def _strip_regression_fields(self, stdout):
    for event in stdout:
        if event.get("event") == "JOB_COMPLETED":
            event.pop("files_skipped_unchanged", None)
```

**New:**
```python
def strip_newer_fields(events, checkpoint_name):
    """Remove fields added in later checkpoints."""
    if checkpoint_name not in ("checkpoint_1", "checkpoint_2"):
        return events

    result = []
    for event in events:
        e = dict(event)
        if e.get("event") == "JOB_COMPLETED":
            e.pop("files_skipped_unchanged", None)
        result.append(e)
    return result

def test_regression(entrypoint_argv, checkpoint_name):
    result = run_command(...)
    events = strip_newer_fields(parse_jsonl(result.stdout), checkpoint_name)
    assert events == EXPECTED
```

---

## Assertion Helpers

Create reusable helpers for common patterns:

```python
# In conftest.py or a shared module

def assert_json_equal(actual, expected, ignore_keys=None):
    """Compare JSON, optionally ignoring certain keys."""
    if ignore_keys:
        actual = {k: v for k, v in actual.items() if k not in ignore_keys}
        expected = {k: v for k, v in expected.items() if k not in ignore_keys}
    assert actual == expected


def assert_events_contain(events, expected_types):
    """Assert event stream contains expected event types."""
    actual_types = [e["event"] for e in events]
    for expected in expected_types:
        assert expected in actual_types, f"Missing event: {expected}"


def assert_status_and_body(response, status, body_subset=None):
    """Assert HTTP response status and optionally check body subset."""
    assert response.status_code == status
    if body_subset:
        for key, value in body_subset.items():
            assert response.json()[key] == value
```
