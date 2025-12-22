# Regression Testing

Patterns for ensuring prior checkpoint functionality continues to work.

## Overview

Regression testing ensures that:
1. Features from prior checkpoints still work
2. New changes don't break existing functionality
3. Tests are reused efficiently across checkpoints

## Automatic Regression

By default, prior checkpoint tests become regression tests.

### Configuration

```yaml
# config.yaml
checkpoints:
  checkpoint_1:
    version: 1
    order: 1
    state: Core Tests

  checkpoint_2:
    version: 1
    order: 2
    state: Core Tests
    include_prior_tests: true  # Default: true

  checkpoint_3:
    version: 1
    order: 3
    state: Core Tests
    include_prior_tests: true
```

### How It Works

When evaluating `checkpoint_2`:
- `test_checkpoint_1.py` → REGRESSION tests
- `test_checkpoint_2.py` → CORE/FUNCTIONALITY/ERROR tests

When evaluating `checkpoint_3`:
- `test_checkpoint_1.py` → REGRESSION tests
- `test_checkpoint_2.py` → REGRESSION tests
- `test_checkpoint_3.py` → CORE/FUNCTIONALITY/ERROR tests

## Disabling Regression

Set `include_prior_tests: false` to skip prior tests:

```yaml
checkpoints:
  checkpoint_2:
    version: 1
    order: 2
    include_prior_tests: false  # Only run checkpoint_2 tests
```

Use this when:
- Prior tests are incompatible with new API
- Complete rewrite of functionality
- Performance testing (fewer tests)

## Explicit Regression Marker

Mark tests as regression explicitly:

```python
@pytest.mark.regression
def test_legacy_format(entrypoint_argv):
    """Regression: Old input format still works."""
    # Format from checkpoint_1 that should still work
    result = run_command(entrypoint_argv, {"old_key": "value"})
    assert result.returncode == 0
```

## Checkpoint-Aware Tests

Use the `checkpoint_name` fixture for conditional logic:

### Feature Detection

```python
def test_basic_feature(entrypoint_argv, checkpoint_name):
    """Test basic feature, handles variations."""
    result = run_command(entrypoint_argv, {"data": "test"})
    output = json.loads(result.stdout)

    # Basic assertion works for all checkpoints
    assert output["status"] == "success"

    # New field added in checkpoint_2
    if checkpoint_name in {"checkpoint_2", "checkpoint_3"}:
        assert "version" in output
```

### Output Variations

```python
def test_output_format(entrypoint_argv, checkpoint_name):
    """Handle different output formats by checkpoint."""
    result = run_command(entrypoint_argv, {"data": "test"})
    output = json.loads(result.stdout)

    if checkpoint_name == "checkpoint_1":
        assert output == {"result": "TEST"}
    else:
        # checkpoint_2+ adds metadata
        assert output["result"] == "TEST"
        assert "metadata" in output
```

## Stripping Regression Fields

When fields are added in later checkpoints, strip them for comparison:

```python
@pytest.fixture(scope="session")
def strip_regression_fields():
    """Remove fields added in later checkpoints."""
    def _strip(data):
        data = data.copy()
        # Fields added in checkpoint_2+
        for field in ["version", "timestamp", "checkpoint"]:
            data.pop(field, None)
        return data
    return _strip


def test_core_output(entrypoint_argv, strip_regression_fields, checkpoint_name):
    """Core output matches expected (ignoring new fields)."""
    result = run_command(entrypoint_argv, {"data": "test"})
    output = json.loads(result.stdout)

    # For regression tests, strip new fields
    if checkpoint_name != "checkpoint_1":
        output = strip_regression_fields(output)

    expected = {"result": "TEST", "data": "test"}
    assert output == expected
```

## Parametrized Regression Cases

Load cases from prior checkpoints:

```python
def load_all_prior_cases(current_checkpoint):
    """Load cases from all prior checkpoints."""
    all_cases = []
    checkpoint_num = int(current_checkpoint.split("_")[1])

    for i in range(1, checkpoint_num):
        prior = f"checkpoint_{i}"
        cases = load_cases(DATA_DIR / prior / "core")
        for case in cases:
            case["source_checkpoint"] = prior
        all_cases.extend(cases)

    return all_cases


# Only run regression cases when not on checkpoint_1
@pytest.fixture(scope="module")
def regression_cases(checkpoint_name):
    if checkpoint_name == "checkpoint_1":
        return []
    return load_all_prior_cases(checkpoint_name)


def test_regression_cases(entrypoint_argv, regression_cases, checkpoint_name):
    """Run all prior checkpoint cases."""
    if not regression_cases:
        pytest.skip("No regression cases for checkpoint_1")

    for case in regression_cases:
        result = run_case(entrypoint_argv, case["case"])
        # May need to adjust expectations
        assert result.returncode == 0
```

## Backward Compatibility Testing

### API Version Testing

```python
def test_api_v1_compatibility(entrypoint_argv, checkpoint_name):
    """V1 API format still works in later checkpoints."""
    if checkpoint_name == "checkpoint_1":
        pytest.skip("V1 is the current version")

    # Old V1 format
    v1_input = {"type": "v1", "data": "test"}
    result = run_command(entrypoint_argv, v1_input)

    assert result.returncode == 0
```

### Deprecation Testing

```python
@pytest.mark.functionality
def test_deprecated_option(entrypoint_argv, checkpoint_name):
    """Deprecated option still works with warning."""
    if checkpoint_name == "checkpoint_1":
        pytest.skip("Option not deprecated yet")

    result = subprocess.run(
        entrypoint_argv + ["--old-option"],  # Deprecated
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "deprecated" in result.stderr.lower()
```

## Test Organization

### Separate Regression File

```
tests/
├── conftest.py
├── test_checkpoint_1.py     # Core tests
├── test_checkpoint_2.py     # Core tests
├── test_checkpoint_3.py     # Core tests
└── test_regression.py       # Explicit regression tests
```

```python
# test_regression.py
"""Explicit regression tests for backward compatibility."""

import pytest


@pytest.mark.regression
def test_v1_input_format(entrypoint_argv):
    """Old V1 input format still works."""
    ...


@pytest.mark.regression
def test_legacy_output_option(entrypoint_argv):
    """--legacy-output option still works."""
    ...
```

### Inline Regression Tests

```python
# test_checkpoint_2.py
"""Tests for checkpoint_2."""


# Core tests for checkpoint_2
def test_new_feature(entrypoint_argv):
    ...


# Regression tests (checking checkpoint_1 still works)
@pytest.mark.regression
def test_checkpoint_1_basic_still_works(entrypoint_argv):
    """Regression: Basic parsing from checkpoint_1."""
    ...
```

## Best Practices

### Document What Regresses

```python
@pytest.mark.regression
def test_json_parsing(entrypoint_argv):
    """Regression: JSON parsing from checkpoint_1.

    In checkpoint_1, we introduced basic JSON parsing.
    This must continue to work in all future checkpoints.
    """
    ...
```

### Test Critical Paths

Focus regression tests on:
- Core functionality that must not break
- Public API contracts
- Common user workflows

### Keep Regression Tests Fast

```python
@pytest.mark.regression
def test_regression_suite(entrypoint_argv):
    """Quick regression check."""
    # Test multiple scenarios in one test if they're simple
    for case in CRITICAL_CASES:
        result = run_case(entrypoint_argv, case)
        assert result.returncode == 0
```

### Version-Lock Expected Outputs

```yaml
# tests/data/regression/basic_case/expected.yaml
# LOCKED: Do not modify - regression baseline
checkpoint_1:
  result: value

checkpoint_2:
  result: value
  version: 2  # New field
```

## Next Steps

- [Markers](../pytest/markers.md) - Test categorization
- [Config Schema](../config-schema.md) - include_prior_tests setting
- [Examples](../examples/) - Real problem examples
