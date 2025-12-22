---
version: 2.0
last_updated: 2025-12-22
---

# Reporting Guide

This guide covers the reporting system for pytest-based evaluation, including result models, pass policies, and export formats.

## Overview

The reporting system aggregates pytest results into structured reports:

- **TestResult**: Individual test outcome with categorization
- **CorrectnessResults**: Aggregated checkpoint results with pass/fail counts
- **PassPolicy**: Configurable criteria for checkpoint success
- **Export formats**: JSON for storage and analysis

## Result Models

### TestResult

Individual test outcome from pytest execution:

```python
class TestResult(BaseModel):
    id: str                    # Pytest nodeid (e.g., "test_basic[case1]")
    checkpoint: str            # Checkpoint name (e.g., "checkpoint_1")
    group_type: GroupType      # CORE, FUNCTIONALITY, REGRESSION, or ERROR
    status: Literal["passed", "failed", "skipped", "error"]
    duration_ms: float         # Execution time in milliseconds
    file_path: str             # Test file path
    markers: list[str]         # Pytest markers (e.g., ["functionality"])
    failure_message: str | None  # Failure details if failed/errored
```

**Status Values:**
- `passed`: Test passed all assertions
- `failed`: Test failed one or more assertions
- `skipped`: Test was skipped (e.g., `pytest.skip()`)
- `error`: Test had an error during setup/teardown

### CorrectnessResults

Aggregated results for a checkpoint evaluation:

```python
class CorrectnessResults(BaseModel):
    # Metadata
    problem_name: str          # Problem identifier
    problem_version: int       # Problem version number
    checkpoint_name: str       # Checkpoint name
    checkpoint_version: int    # Checkpoint version number
    duration: float            # Total evaluation time (seconds)
    entrypoint: str            # Command used to run submission

    # Test results
    tests: list[TestResult]    # All individual test results

    # Aggregated counts
    pass_counts: dict[GroupType, int]   # Passed tests by type
    total_counts: dict[GroupType, int]  # Total tests by type

    # Pytest metadata
    pytest_exit_code: int      # Pytest exit code (0=success, 1=failures)
    pytest_collected: int      # Number of tests collected
    infrastructure_failure: bool  # True if pytest itself failed
```

### GroupType

Test categorization enum:

```python
class GroupType(str, Enum):
    CORE = "Core"              # Must-pass tests
    FUNCTIONALITY = "Functionality"  # Nice-to-have tests
    REGRESSION = "Regression"  # Tests from prior checkpoints
    ERROR = "Error"            # Error-handling tests
```

## Accessing Results

### Basic Access

```python
from slop_code.evaluation import run_checkpoint_pytest

# Run evaluation
results = run_checkpoint_pytest(...)

# Check if checkpoint passed
if results.passes_policy("core-cases"):
    print("Checkpoint passed!")

# Get pass rates
core_passed = results.pass_counts.get(GroupType.CORE, 0)
core_total = results.total_counts.get(GroupType.CORE, 0)
print(f"Core: {core_passed}/{core_total}")
```

### Iterate Over Tests

```python
# All tests
for test in results.tests:
    status = "PASS" if test.status == "passed" else "FAIL"
    print(f"{status} {test.id} ({test.group_type})")

# Failed tests only
failed = [t for t in results.tests if t.status == "failed"]
for test in failed:
    print(f"FAILED: {test.id}")
    if test.failure_message:
        print(f"  {test.failure_message[:200]}")
```

### Filter by GroupType

```python
# Get only core tests
core_tests = [t for t in results.tests if t.group_type == GroupType.CORE]

# Get only regression tests
regression_tests = [t for t in results.tests if t.group_type == GroupType.REGRESSION]

# Count by group type
from collections import Counter
type_counts = Counter(t.group_type for t in results.tests)
```

### Check Infrastructure Failures

```python
if results.infrastructure_failure:
    print("Pytest failed to run properly!")
    print(f"Exit code: {results.pytest_exit_code}")
    print(f"Collected: {results.pytest_collected} tests")
```

## Pass Policies

Pass policies determine whether a checkpoint succeeds based on test results.

### Available Policies

| Policy | Description |
|--------|-------------|
| `core-cases` | All CORE tests must pass (default) |
| `all-non-error-cases` | All CORE, FUNCTIONALITY, and REGRESSION tests pass |
| `any-case` | At least one test passes |
| `all-cases` | All tests must pass |

### Using Pass Policies

```python
# Check specific policy
if results.passes_policy("core-cases"):
    print("Core tests passed!")

# Check multiple policies
for policy in ["core-cases", "all-non-error-cases"]:
    status = "PASS" if results.passes_policy(policy) else "FAIL"
    print(f"{policy}: {status}")
```

### Policy Behavior

**`core-cases`** (default):
- Only tests with `GroupType.CORE` must pass
- FUNCTIONALITY, REGRESSION, and ERROR tests can fail
- Use for: Essential functionality validation

**`all-non-error-cases`**:
- CORE, FUNCTIONALITY, and REGRESSION tests must all pass
- Only ERROR tests can fail
- Use for: Comprehensive validation

**Infrastructure failures** always cause policy failure regardless of policy type.

### PassPolicy Enum

```python
from slop_code.evaluation.report import PassPolicy

class PassPolicy(str, Enum):
    ANY = "any"
    ANY_CASE = "any-case"
    ALL_CASES = "all-cases"
    ALL_NON_ERROR_CASES = "all-non-error-cases"
    CORE_CASES = "core-cases"
    ANY_CORE_CASES = "any-core-cases"
    ALL_CORE_CASES = "all-core-cases"

# Use enum directly
passed = PassPolicy.CORE_CASES.check(
    results.pass_counts,
    results.total_counts
)
```

## Export Formats

### Saving Results

```python
# Save to directory
results.save(Path("outputs/checkpoint_1"))

# Creates:
#   outputs/checkpoint_1/evaluation.json    # Main results
#   outputs/checkpoint_1/evaluation/stdout.txt   # Pytest stdout
#   outputs/checkpoint_1/evaluation/stderr.txt   # Pytest stderr
#   outputs/checkpoint_1/evaluation/report.json  # Raw CTRF report
```

### JSON Structure (evaluation.json)

```json
{
  "problem_name": "file_backup",
  "problem_version": 1,
  "checkpoint_name": "checkpoint_1",
  "checkpoint_version": 1,
  "duration": 12.34,
  "entrypoint": "python main.py",
  "tests": [
    {
      "id": "test_core_cases[basic]",
      "checkpoint": "checkpoint_1",
      "group_type": "Core",
      "status": "passed",
      "duration_ms": 123.45,
      "file_path": "tests/test_checkpoint_1.py"
    },
    {
      "id": "test_error_cases[invalid_input]",
      "checkpoint": "checkpoint_1",
      "group_type": "Error",
      "status": "failed",
      "duration_ms": 45.67,
      "file_path": "tests/test_checkpoint_1.py"
    }
  ],
  "pass_counts": {
    "Core": 5,
    "Functionality": 3,
    "Error": 1
  },
  "total_counts": {
    "Core": 5,
    "Functionality": 4,
    "Error": 2
  },
  "pytest_exit_code": 1,
  "pytest_collected": 11,
  "infrastructure_failure": false
}
```

### Loading Results

```python
import json
from pathlib import Path

# Load from JSON
with open("outputs/checkpoint_1/evaluation.json") as f:
    data = json.load(f)

# Access fields
print(f"Problem: {data['problem_name']}")
print(f"Passed core: {data['pass_counts'].get('Core', 0)}")
print(f"Total core: {data['total_counts'].get('Core', 0)}")
```

## Diagnostic Information

### Pytest Output

Stdout and stderr are saved separately (not in evaluation.json):

```python
# Read pytest output
stdout = Path("outputs/checkpoint_1/evaluation/stdout.txt").read_text()
stderr = Path("outputs/checkpoint_1/evaluation/stderr.txt").read_text()

# Look for collection info
if "collected" in stdout:
    print("Tests were collected successfully")
```

### Failure Messages

```python
# Print failure details
for test in results.tests:
    if test.status in ("failed", "error") and test.failure_message:
        print(f"\n{test.id}:")
        print(test.failure_message)
```

### CTRF Report

The raw CTRF (Common Test Report Format) report is saved for detailed analysis:

```python
import json

with open("outputs/checkpoint_1/evaluation/report.json") as f:
    ctrf = json.load(f)

# Access raw test data
for test in ctrf.get("results", {}).get("tests", []):
    print(f"{test['name']}: {test['status']}")
```

## Analytics Examples

### Summary Report

```python
def print_summary(results):
    total_passed = sum(results.pass_counts.values())
    total_count = sum(results.total_counts.values())
    passed = results.passes_policy("core-cases")

    print(f"{'='*50}")
    print(f"Problem: {results.problem_name}")
    print(f"Checkpoint: {results.checkpoint_name}")
    print(f"{'='*50}")
    print(f"Status: {'PASS' if passed else 'FAIL'}")
    print(f"Tests: {total_passed}/{total_count} passed")
    print(f"Duration: {results.duration:.2f}s")
    print(f"{'='*50}")

    for group_type in GroupType:
        passed = results.pass_counts.get(group_type, 0)
        total = results.total_counts.get(group_type, 0)
        if total > 0:
            print(f"{group_type.value}: {passed}/{total}")
```

### Failure Analysis

```python
from collections import defaultdict

def analyze_failures(results):
    failures_by_type = defaultdict(list)

    for test in results.tests:
        if test.status != "passed":
            failures_by_type[test.group_type].append(test)

    print("Failures by group type:")
    for group_type, tests in failures_by_type.items():
        print(f"\n{group_type.value}: {len(tests)} failures")
        for test in tests[:5]:  # Show first 5
            print(f"  - {test.id}: {test.status}")
```

### Compare Runs

```python
import json
from pathlib import Path

def compare_runs(dir1: Path, dir2: Path):
    with open(dir1 / "evaluation.json") as f:
        run1 = json.load(f)
    with open(dir2 / "evaluation.json") as f:
        run2 = json.load(f)

    for group_type in ["Core", "Functionality", "Regression", "Error"]:
        p1 = run1["pass_counts"].get(group_type, 0)
        t1 = run1["total_counts"].get(group_type, 0)
        p2 = run2["pass_counts"].get(group_type, 0)
        t2 = run2["total_counts"].get(group_type, 0)

        if t1 > 0 or t2 > 0:
            print(f"{group_type}: {p1}/{t1} -> {p2}/{t2}")
```

## Next Steps

- **Debug failures**: [Troubleshooting Guide](troubleshooting.md)
- **Understand architecture**: [Architecture Guide](architecture.md)
- **Configure problems**: [Configuration Guide](configuration.md)
