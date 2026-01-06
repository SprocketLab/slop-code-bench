# Pytest Markers

Reference for test categorization using pytest markers.

## Built-in Markers

SCBench provides three built-in markers that map to GroupTypes:

| Marker | GroupType | Purpose |
|--------|-----------|---------|
| *(none)* | CORE | Must pass - essential functionality |
| `@pytest.mark.functionality` | FUNCTIONALITY | Nice to have - advanced features |
| `@pytest.mark.error` | ERROR | Error handling - edge cases |
| `@pytest.mark.regression` | REGRESSION | Prior checkpoint tests (automatic) |

## Using Markers

### Core Tests (Unmarked)

Tests without any marker are CORE tests. These must pass for the checkpoint to be considered successful.

```python
def test_basic_parsing(entrypoint_argv):
    """Core: Basic JSON parsing works."""
    result = run_command(entrypoint_argv, {"key": "value"})
    assert result.returncode == 0


def test_handles_arrays(entrypoint_argv):
    """Core: Array values are preserved."""
    result = run_command(entrypoint_argv, {"items": [1, 2, 3]})
    assert result.returncode == 0
```

### Functionality Tests

Use `@pytest.mark.functionality` for nice-to-have features:

```python
@pytest.mark.functionality
def test_pretty_print(entrypoint_argv):
    """Functionality: Pretty print option works."""
    result = run_command(entrypoint_argv, {"key": "value"}, ["--pretty"])
    assert "  " in result.stdout  # Indentation present


@pytest.mark.functionality
def test_custom_delimiter(entrypoint_argv):
    """Functionality: Custom delimiter option works."""
    result = run_command(entrypoint_argv, {"a": 1}, ["--delimiter", ";"])
    assert ";" in result.stdout
```

### Error Tests

Use `@pytest.mark.error` for error handling tests:

```python
@pytest.mark.error
def test_invalid_json(entrypoint_argv):
    """Error: Invalid JSON returns error code."""
    result = run_command(entrypoint_argv, "not valid json")
    assert result.returncode == 1


@pytest.mark.error
def test_empty_input(entrypoint_argv):
    """Error: Empty input handled gracefully."""
    result = run_command(entrypoint_argv, "")
    assert result.returncode == 1
    assert "error" in result.stderr.lower()
```

### Regression Tests

The `regression` marker is typically automatic (applied to prior checkpoint tests), but can be used explicitly:

```python
@pytest.mark.regression
def test_legacy_format_still_works(entrypoint_argv):
    """Regression: Old input format still accepted."""
    # Format from checkpoint_1 that should still work
    result = run_command(entrypoint_argv, {"old_key": "value"})
    assert result.returncode == 0
```

## Marker Priority

When multiple markers apply, priority determines GroupType:

1. Prior checkpoint tests - Always REGRESSION (regardless of markers)
2. `error` - Maps to ERROR (current checkpoint only)
3. `regression` - Maps to REGRESSION
4. Custom markers - Checked next
5. `functionality` - Maps to FUNCTIONALITY
6. No marker - Maps to CORE

```python
# This is an ERROR test (error wins)
@pytest.mark.error
@pytest.mark.functionality
def test_example():
    pass

# This is a REGRESSION test (regression over functionality)
@pytest.mark.regression
@pytest.mark.functionality
def test_another():
    pass
```

## Automatic Regression Marking

When `include_prior_tests: true` (default), tests from prior checkpoints automatically become REGRESSION tests:

```yaml
# config.yaml
checkpoints:
  checkpoint_2:
    version: 1
    order: 2
    include_prior_tests: true  # test_checkpoint_1.py becomes REGRESSION
```

During checkpoint_2 evaluation:
- `test_checkpoint_1.py::test_*` → REGRESSION
- `test_checkpoint_2.py::test_*` → CORE/FUNCTIONALITY/ERROR (based on markers)

## Custom Markers

Define custom markers in `config.yaml`:

```yaml
markers:
  slow:
    description: slow-running tests (>10s)
    group: FUNCTIONALITY

  integration:
    description: integration tests
    group: FUNCTIONALITY

  critical:
    description: critical path tests
    group: CORE
```

Use in tests:

```python
@pytest.mark.slow
def test_large_dataset(entrypoint_argv, large_data):
    """Takes a long time to process."""
    result = run_command(entrypoint_argv, large_data)
    assert result.returncode == 0


@pytest.mark.integration
def test_with_external_service(entrypoint_argv):
    """Requires external service."""
    ...
```

## GroupType Categorization Rules

PytestRunner determines GroupType using these rules (in order):

```python
def _determine_group_type(test, checkpoint_name):
    markers = test.get("markers", [])
    is_current = test["file"] == f"test_{checkpoint_name}.py"

    # 1. prior checkpoint tests ALWAYS become regression
    if not is_current:
        return GroupType.REGRESSION

    # 2. error marker wins for current checkpoint
    if "error" in markers:
        return GroupType.ERROR

    # 3. explicit regression marker
    if "regression" in markers:
        return GroupType.REGRESSION

    # 4. custom markers from config
    for marker in markers:
        if marker in custom_markers:
            return custom_markers[marker].group

    # 4. functionality marker
    if "functionality" in markers:
        return GroupType.FUNCTIONALITY

    # 5. default to CORE
    return GroupType.CORE
```

## Combining with Parametrize

Markers work with parametrized tests:

```python
CORE_CASES = load_cases("core")
ERROR_CASES = load_cases("errors")


@pytest.mark.parametrize("case", CORE_CASES, ids=[c["id"] for c in CORE_CASES])
def test_core_cases(entrypoint_argv, case):
    """Core cases from external files."""
    result = run_case(entrypoint_argv, case)
    assert result == case["expected"]


@pytest.mark.error
@pytest.mark.parametrize("case", ERROR_CASES, ids=[c["id"] for c in ERROR_CASES])
def test_error_cases(entrypoint_argv, case):
    """Error cases from external files."""
    result = run_case(entrypoint_argv, case)
    assert result.returncode != 0
```

## Best Practices

### Use Clear Docstrings

```python
def test_basic(entrypoint_argv):
    """Core: Basic functionality works."""  # Clear category
    ...

@pytest.mark.error
def test_invalid(entrypoint_argv):
    """Error: Invalid input returns error code."""  # Explains expectation
    ...
```

### Group Related Tests

```python
# =============================================================================
# Core Tests
# =============================================================================

def test_core_1(entrypoint_argv):
    ...

def test_core_2(entrypoint_argv):
    ...


# =============================================================================
# Functionality Tests
# =============================================================================

@pytest.mark.functionality
def test_feature_1(entrypoint_argv):
    ...


# =============================================================================
# Error Tests
# =============================================================================

@pytest.mark.error
def test_error_1(entrypoint_argv):
    ...
```

### Balance Test Distribution

Aim for this approximate distribution:
- **60%** Core tests - Essential functionality
- **30%** Error tests - Error handling
- **10%** Functionality tests - Advanced features

## Next Steps

- [conftest Patterns](conftest-patterns.md) - Fixture patterns
- [Test Data](test-data.md) - Organizing test data
- [Advanced Fixtures](fixtures-advanced.md) - Advanced fixture patterns
