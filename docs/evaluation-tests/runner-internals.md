# PytestRunner Internals

Technical reference for how SCBench executes pytest-based evaluations.

## Overview

`PytestRunner` orchestrates test execution with these steps:

1. Copy tests from problem to workspace
2. Generate pytest.ini with markers
3. Execute pytest via uvx
4. Parse reports and categorize results

## Execution Flow

```
PytestRunner.run()
    │
    ├─► Resolve static assets
    │   └─► Materialize problem assets
    │
    ├─► Create session
    │   └─► Set up workspace with submission
    │
    ├─► Copy tests
    │   ├─► test_checkpoint_1.py
    │   ├─► test_checkpoint_2.py (if include_prior_tests)
    │   └─► conftest.py
    │
    ├─► Generate pytest.ini
    │   └─► Register markers
    │
    ├─► Build pytest command
    │   └─► uvx --with=pytest pytest ...
    │
    ├─► Execute pytest
    │   └─► Run in Docker container
    │
    ├─► Parse reports
    │   ├─► CTRF report
    │   └─► pytest-json-report
    │
    └─► Convert to TestResults
        └─► Categorize by GroupType
```

## Test Selection

Tests are selected based on the current checkpoint and `include_prior_tests`:

```python
def _get_test_files(checkpoint_name, include_prior_tests):
    """Determine which test files to copy."""
    files = [f"test_{checkpoint_name}.py"]

    if include_prior_tests:
        # Include all prior checkpoints
        # checkpoint_3 → includes checkpoint_1, checkpoint_2
        checkpoint_num = int(checkpoint_name.split("_")[1])
        for i in range(1, checkpoint_num):
            files.append(f"test_checkpoint_{i}.py")

    files.append("conftest.py")
    return files
```

## pytest.ini Generation

PytestRunner generates pytest.ini with marker registrations:

```ini
[pytest]
markers =
    error: error-handling / edge-case tests
    functionality: non-core / nice-to-have tests
    regression: regression tests from prior checkpoints
    slow: slow-running tests (custom marker)
```

Built-in markers are always included:

```python
BUILTIN_MARKERS = {
    "error": ("error-handling / edge-case tests", GroupType.ERROR),
    "functionality": ("non-core / nice-to-have tests", GroupType.FUNCTIONALITY),
    "regression": ("regression tests from prior checkpoints", GroupType.REGRESSION),
}
```

## Command Construction

The pytest command is built for uvx execution:

```bash
uvx --with=pytest \
    --with=pytest-json-ctrf \
    --with=pytest-json-report \
    --with=pytest-timeout \
    --with=jsonschema \
    --with=deepdiff \
    pytest tests/ \
    --entrypoint="python main.py" \
    --checkpoint=checkpoint_1 \
    --ctrf=.scbench/ctrf-report.json \
    --json-report \
    --json-report-file=.scbench/pytest-report.json \
    --timeout=30 \
    -vv
```

Additional dependencies from `test_dependencies` are added:

```python
for dep in problem.test_dependencies:
    cmd.extend(["--with", dep])
```

## Report Parsing

### CTRF Report Format

```json
{
  "results": {
    "tool": {
      "name": "pytest"
    },
    "tests": [
      {
        "name": "test_basic_case",
        "status": "passed",
        "duration": 500,
        "filePath": "tests/test_checkpoint_1.py",
        "tags": [],
        "message": null
      },
      {
        "name": "test_error_case",
        "status": "passed",
        "duration": 250,
        "filePath": "tests/test_checkpoint_1.py",
        "tags": ["error"],
        "message": null
      }
    ]
  }
}
```

### pytest-json-report Format

```json
{
  "tests": [
    {
      "nodeid": "tests/test_checkpoint_1.py::test_basic_case",
      "outcome": "passed",
      "duration": 0.5,
      "setup": {"outcome": "passed"},
      "call": {"outcome": "passed"},
      "teardown": {"outcome": "passed"}
    }
  ],
  "collectors": [
    {
      "nodeid": "tests/test_checkpoint_1.py::test_parametrized[case1]",
      "outcome": "passed"
    }
  ]
}
```

## GroupType Categorization

Tests are categorized using these rules (in priority order):

```python
def _determine_group_type(test, checkpoint_name, custom_markers):
    markers = test.get("tags", [])
    file_path = test.get("filePath", "")
    is_current = file_path.endswith(f"test_{checkpoint_name}.py")

    # 1. prior checkpoint tests ALWAYS become regression (regardless of markers)
    if not is_current:
        return GroupType.REGRESSION

    # 2. error marker wins for current checkpoint
    if "error" in markers:
        return GroupType.ERROR

    # 3. explicit regression marker
    if "regression" in markers:
        return GroupType.REGRESSION

    # 4. Custom markers from config
    for marker in markers:
        if marker in custom_markers:
            return custom_markers[marker].group

    # 5. functionality marker
    if "functionality" in markers:
        return GroupType.FUNCTIONALITY

    # 6. Default to CORE
    return GroupType.CORE
```

## Environment Variables

PytestRunner sets these environment variables:

| Variable | Description | Example |
|----------|-------------|---------|
| `SCBENCH_ASSETS_DIR` | Path to materialized assets | `/workspace/tests/assets` |
| `SCBENCH_ASSET_{NAME}` | Path to specific asset | `/workspace/tests/assets/files` |
| `SCBENCH_CHECKPOINT` | Current checkpoint name | `checkpoint_1` |

## Test Dependencies

Default dependencies (always available):

- `pytest`
- `pytest-json-ctrf`
- `pytest-json-report`
- `pytest-timeout`
- `jsonschema`
- `deepdiff`

Additional dependencies from `config.yaml`:

```yaml
test_dependencies:
  - pyyaml
  - requests
  - pandas
```

## Timeout Handling

Timeouts are applied at multiple levels:

1. **Session timeout** - Overall pytest execution
2. **Test timeout** - Per-test via pytest-timeout
3. **Subprocess timeout** - For individual command executions

```python
# Session timeout from checkpoint config
timeout = checkpoint.timeout or problem.timeout or 30

# pytest-timeout for per-test limits
cmd.extend(["--timeout", str(timeout)])
```

## Error Detection

PytestRunner detects these failure modes:

### Collection Errors

```python
if report.get("exitcode") == 2:
    # Collection error - tests couldn't be collected
    return TestResults(
        passed=False,
        error="Test collection failed",
        details=report.get("error", ""),
    )
```

### Infrastructure Failures

```python
if not (ctrf_report or pytest_report):
    # No reports generated - infrastructure failure
    return TestResults(
        passed=False,
        error="No test reports generated",
    )
```

### Test Failures

```python
for test in tests:
    if test["status"] in ("failed", "error"):
        results.append(TestResult(
            name=test["name"],
            passed=False,
            message=test.get("message", ""),
            group_type=_determine_group_type(test, ...),
        ))
```

## Result Aggregation

Results are aggregated by GroupType:

```python
results = {
    GroupType.CORE: [],
    GroupType.FUNCTIONALITY: [],
    GroupType.ERROR: [],
    GroupType.REGRESSION: [],
}

for test in tests:
    group_type = _determine_group_type(test, ...)
    results[group_type].append(TestResult(
        name=test["name"],
        passed=test["status"] == "passed",
        duration=test.get("duration", 0),
        group_type=group_type,
    ))
```

## Debugging

### View Raw Reports

Reports are saved to the workspace:

```
.scbench/
├── ctrf-report.json
├── pytest-report.json
└── pytest.log
```

### Run Tests Locally

```bash
cd problems/my_problem
pytest tests/ \
  --entrypoint="python solution/main.py" \
  --checkpoint=checkpoint_1 \
  -v
```

### Enable Verbose Output

Set `verbose=True` in the logger for detailed execution logs.

## Next Steps

- [conftest Patterns](conftest-patterns.md) - Fixture patterns
- [Markers](markers.md) - Test categorization
- [Debugging Workflows](debugging-workflows.md) - Debug test failures
