---
name: test-ambiguity-detector
description: Analyze test cases against specifications to find ambiguous assumptions. Use when tests might be making assumptions not explicitly defined in the spec. Invoke with /test-ambiguity-detector <problem> <checkpoint>.
---

# Test Ambiguity Detector

Compare a test file against its specification to identify where tests assume behavior that the spec doesn't explicitly define.

**Usage**: `/test-ambiguity-detector file_backup checkpoint_1`

## Purpose

Tests should verify spec-defined behavior, not invent requirements. This skill finds cases where:
- Tests assert specific behavior the spec is silent about
- Tests assume implementation details not mandated by spec
- Tests expect particular error messages/codes not specified
- Tests require specific ordering/formatting beyond spec requirements

---

## Step 1: Gather Context

Read the spec and test files for the specified problem/checkpoint:

```
problems/{problem}/checkpoint_N.md
problems/{problem}/tests/test_checkpoint_N.py
problems/{problem}/tests/conftest.py        # Fixtures and test setup
```

Also check for test data:
```
problems/{problem}/tests/data/checkpoint_N/  # Test case data (if present)
```

---

## Step 2: Catalog Spec Requirements

For each section of the spec, extract:

1. **Explicit requirements** - "MUST", "SHALL", specific values, exact formats
2. **Implicit requirements** - Reasonable inferences from context
3. **Undefined behaviors** - What the spec does NOT address

Create a mental checklist:
- Input validation rules (if any specified)
- Output format requirements (exact vs flexible)
- Error handling expectations (if any specified)
- Edge cases addressed (explicitly or by example)
- Processing order requirements
- Default values specified

---

## Step 3: Analyze Each Test

For each test function or test case:

### A. Identify the Assertion
What specific behavior does this test check?
- Return values
- Output format/content
- Side effects
- Error conditions
- State changes

### B. Find Spec Support
Can you point to a specific spec line that mandates this behavior?

**SUPPORTED**: Spec says "must return error code 1" → test checks `returncode == 1`
**UNSUPPORTED**: Spec says "must return non-zero on error" → test checks `returncode == 1`

### C. Classify the Assumption

| Category | Example | Risk Level |
|----------|---------|------------|
| Explicit | Spec says X, test checks X | None |
| Reasonable Inference | Spec implies X, test checks X | Low |
| Implementation Choice | Spec silent, test assumes X | **HIGH** |
| Contradiction | Spec says X, test checks Y | **CRITICAL** |

---

## Step 4: Report Findings

Generate a report in this format:

```markdown
# Ambiguity Report: {problem} {checkpoint}

## Summary
- Total tests analyzed: N
- Potentially ambiguous: N
- Likely spec issues: N

## Ambiguous Test Assumptions

### 1. `test_function_name` (line X)

**Assertion**: [What the test checks]

**Spec says**: [Quote or "NOTHING - spec is silent"]

**Risk**: [HIGH/MEDIUM/LOW]

**Analysis**: [Why this is problematic]

**Recommendation**:
- [ ] Clarify in spec: [suggested text]
- [ ] OR relax test: [how to make less specific]
- [ ] OR remove test: [if testing undefined behavior]

---

### 2. `test_another_function` (line Y)
...

## Spec Gaps Identified

List behaviors tested but not defined in spec:
1. [Behavior] - should spec define this?
2. ...

## Recommendations

### For Spec Authors
- [Suggested clarifications]

### For Test Authors
- [Suggested test modifications]
```

---

## Common Ambiguity Patterns

### Error Handling
- **Ambiguous**: Spec says "return error" but test expects specific code/message
- **Check**: Does spec define error codes? Error message format?

### Ordering
- **Ambiguous**: Spec says "process items" but test expects specific order
- **Check**: Does spec mandate sorting? Stable ordering?

### Whitespace/Formatting
- **Ambiguous**: Spec shows example output, test requires exact formatting
- **Check**: Does spec say "must match exactly" or just "must contain"?

### Empty/Null Inputs
- **Ambiguous**: Test expects specific behavior for empty input
- **Check**: Does spec address empty/null cases?

### Boundary Values
- **Ambiguous**: Test checks behavior at 0, max, or edge values
- **Check**: Does spec define boundary behavior?

### Field Ordering in JSON/YAML
- **Ambiguous**: Test expects fields in specific order
- **Check**: Does spec mandate field ordering?

### Case Sensitivity
- **Ambiguous**: Test expects case-sensitive/insensitive matching
- **Check**: Does spec specify case handling?

---

## Red Flags in Tests

Watch for these patterns that often indicate ambiguity:

```python
# Specific error code not in spec
assert result.returncode == 42

# Exact error message not in spec
assert "invalid format" in result.stderr

# Specific field ordering
assert json.dumps(output) == '{"a":1,"b":2}'

# Implicit sorting expectations
assert results == sorted(results)

# Default value assumptions
assert config.get("timeout") == 30

# Specific exception types
with pytest.raises(ValueError):
```

---

## Example Analysis

Given spec text:
```markdown
Return non-zero exit code on invalid input.
```

And test:
```python
def test_invalid_input():
    result = subprocess.run(...)
    assert result.returncode == 1  # <-- AMBIGUOUS!
```

**Finding**: Test expects exit code 1, but spec only says "non-zero". Valid implementations could return 2, 127, or any non-zero value.

**Recommendation**: Either:
- Clarify spec: "Return exit code 1 on invalid input"
- Relax test: `assert result.returncode != 0`

---

## Recommended Tools for Lenient Tests

**Fix preference: Make tests lenient > Remove tests >> Update spec**

Many ambiguity issues can be solved by using flexible comparison tools instead of exact matching.

### deepdiff - Flexible Object Comparison
```python
from deepdiff import DeepDiff

# Instead of exact matching:
assert actual == expected  # FAILS on order, float precision, extra fields

# Use deepdiff to ignore irrelevant differences:
diff = DeepDiff(expected, actual,
    ignore_order=True,           # List/dict order doesn't matter
    significant_digits=5,         # Float precision tolerance
    exclude_paths=["root['id']"]  # Ignore fields not in spec
)
assert not diff, f"Meaningful differences: {diff}"
```

### jsonschema - Structure Validation
```python
from jsonschema import validate

# Instead of checking exact values:
assert output == {"status": "ok", "count": 5}  # Too strict!

# Validate structure matches spec requirements:
schema = {
    "type": "object",
    "required": ["status", "count"],  # Only what spec requires
    "properties": {
        "status": {"enum": ["ok", "error"]},
        "count": {"type": "integer", "minimum": 0}
    }
}
validate(instance=output, schema=schema)  # Accepts any valid structure
```

### Normalization - Handle Formatting Differences
```python
import json

def normalize(obj):
    """Normalize for comparison: sort keys, strip whitespace, lowercase strings."""
    if isinstance(obj, dict):
        return {k: normalize(v) for k, v in sorted(obj.items())}
    if isinstance(obj, list):
        return sorted([normalize(x) for x in obj], key=lambda x: json.dumps(x, sort_keys=True))
    if isinstance(obj, str):
        return obj.strip().lower()
    return obj

# Instead of exact string/JSON comparison:
assert json.dumps(actual) == json.dumps(expected)  # Fails on key order!

# Normalize first:
assert normalize(actual) == normalize(expected)
```

### Combined Approach
```python
def flexible_assert(actual, expected, ignore_fields=None):
    """Compare with maximum leniency for spec compliance."""
    diff = DeepDiff(
        normalize(expected),
        normalize(actual),
        ignore_order=True,
        exclude_paths=ignore_fields or [],
        significant_digits=5,
        ignore_string_case=True
    )
    assert not diff, f"Spec-relevant differences: {diff}"

# Usage: Only fails on meaningful differences
flexible_assert(actual, expected, ignore_fields=["root['timestamp']"])
```

### When to Use Each Tool

| Problem | Solution |
|---------|----------|
| Order doesn't match | `deepdiff` with `ignore_order=True` |
| Float precision differs | `deepdiff` with `significant_digits=N` |
| Extra fields in output | `deepdiff` with `exclude_paths` |
| Only structure matters | `jsonschema` validation |
| Whitespace/case differs | `normalize()` before comparing |
| Multiple issues | Combine all techniques |

---

## After Analysis

Summarize findings to the user with:
1. High-risk ambiguities that likely cause false failures
2. Spec gaps that should be addressed
3. Test modifications to reduce brittleness
4. Questions for spec authors to clarify intent
