---
name: reclassify-tests
description: Reclassify tests by adding @pytest.mark.functionality to tests not explicitly shown in the spec. Invoke with /reclassify-tests <problem> <checkpoint>.
---

# Reclassify Tests

Analyze a checkpoint's spec and test file to identify tests that are NOT explicitly demonstrated in the spec examples, and add `@pytest.mark.functionality` markers to them.

**Usage**: `/reclassify-tests file_backup checkpoint_1`

## Purpose

Core tests (unmarked) should only cover behaviors that are **explicitly demonstrated in spec examples**. Tests that verify implicit requirements, edge cases, or inferred behaviors should be marked as `@pytest.mark.functionality`.

This skill helps ensure fair evaluation by:
- Keeping core tests limited to explicit spec examples
- Moving implicit/inferred behaviors to functionality tests
- Making test classification consistent and justifiable

---

## Step 1: Gather Context

Read these files for the specified problem/checkpoint:

```
problems/{problem}/checkpoint_N.md              # Spec with examples
problems/{problem}/tests/test_checkpoint_N.py   # Test file to reclassify
problems/{problem}/tests/conftest.py            # Fixtures context
problems/{problem}/tests/data/checkpoint_N/     # Test case data (if present)
```

---

## Step 2: Extract Explicit Spec Behaviors

From the spec, identify behaviors that are **explicitly demonstrated**:

### What Counts as "Explicit"

1. **Direct Examples**: Code blocks showing exact input → output
2. **Explicit Statements**: "MUST", "SHALL", specific values defined
3. **Example Output**: JSON/text showing exact expected format
4. **Stated Requirements**: Numbered/bulleted requirements with specific behavior

### What Does NOT Count as "Explicit"

1. **Implied Behavior**: Reasonable inferences not shown in examples
2. **Edge Cases**: Boundary conditions not demonstrated
3. **Error Handling**: Unless specific errors are shown in examples
4. **Format Details**: Exact formatting beyond what examples show
5. **Ordering**: Unless explicitly stated or shown in all examples

### Create a Checklist

For each spec example, note:
- What input is shown?
- What output is shown?
- What behavior is demonstrated?

---

## Step 3: Analyze Each Test

For each test function or parametrized test case:

### A. Identify What the Test Verifies

- What specific behavior does this test check?
- What input does it use?
- What output does it expect?

### B. Find Spec Support

Ask: **"Can I point to a spec example that explicitly demonstrates this exact behavior?"**

| Spec Support | Classification |
|--------------|----------------|
| Example shows exact scenario | **Keep as core** (no marker) |
| Behavior stated but no example | **Mark as functionality** |
| Inferred from context | **Mark as functionality** |
| Edge case not shown | **Mark as functionality** |
| Error handling not in examples | **Mark as error** |

### C. Document the Decision

For each test, note:
- Spec support (quote or "NONE")
- Classification decision
- Reason

---

## Step 4: Apply Markers

### For Tests to Reclassify

Add `@pytest.mark.functionality` ABOVE the test function or parametrize decorator:

**Before:**
```python
@pytest.mark.parametrize("case", EDGE_CASES, ids=[c["id"] for c in EDGE_CASES])
def test_edge_cases(entrypoint_argv, case, tmp_path):
    ...
```

**After:**
```python
@pytest.mark.functionality
@pytest.mark.parametrize("case", EDGE_CASES, ids=[c["id"] for c in EDGE_CASES])
def test_edge_cases(entrypoint_argv, case, tmp_path):
    ...
```

### For Individual Parametrized Cases

If some cases in a parametrized test are explicit and others aren't, consider:

1. **Split the test**: Separate core cases from functionality cases
2. **Use pytest.param with marks**:

```python
@pytest.mark.parametrize("case", [
    pytest.param(case1, id="explicit-case"),
    pytest.param(case2, marks=pytest.mark.functionality, id="inferred-case"),
])
def test_cases(case):
    ...
```

---

## Step 5: Report Changes

Generate a summary of changes made:

```markdown
# Reclassification Report: {problem} {checkpoint}

## Summary
- Tests analyzed: N
- Tests reclassified: N
- Tests unchanged: N

## Reclassified Tests

### `test_function_name` → @pytest.mark.functionality

**Reason**: Test verifies [behavior] which is not explicitly demonstrated in spec.

**Spec says**: [Quote or "No example shown"]

**Test expects**: [What the test checks]

---

### `test_another_function` → @pytest.mark.functionality
...

## Unchanged Tests (Explicitly in Spec)

| Test | Spec Example Reference |
|------|------------------------|
| `test_core_case_1` | Example 1: shows exact input/output |
| `test_core_case_2` | Example 2: demonstrates this scenario |
```

---

## Classification Guidelines

### KEEP AS CORE (no marker) when:

- Spec example shows exact input and expected output
- Behavior is explicitly stated with specific values
- Test directly validates a demonstrated scenario
- Example output format matches test expectations exactly

### MARK AS FUNCTIONALITY when:

- Behavior is reasonable but not shown in examples
- Test checks edge cases not demonstrated
- Test verifies format details beyond examples
- Test validates inferred requirements
- Test checks ordering not explicitly stated
- Test validates error messages/codes not shown

### MARK AS ERROR when:

- Test validates error handling for invalid input
- Test checks failure modes
- Test expects non-zero exit or exceptions

---

## Common Reclassification Scenarios

### 1. Implicit Ordering
```
Spec: "Process all jobs"
Test: Expects specific alphabetical order
→ Mark as functionality (unless spec explicitly shows ordering)
```

### 2. Edge Values
```
Spec: "Duration in hours"
Test: Checks duration=0, duration=MAX
→ Mark as functionality (unless 0/MAX shown in examples)
```

### 3. Format Details
```
Spec: Shows JSON output example
Test: Checks exact whitespace, key ordering
→ Mark as functionality (unless spec says "must match exactly")
```

### 4. Error Handling
```
Spec: "Return non-zero on error"
Test: Checks specific error code or message
→ Mark as error (and consider relaxing the assertion)
```

### 5. Field Presence
```
Spec: Example shows fields A, B, C
Test: Requires field D not in any example
→ Mark as functionality
```

---

## Data-Driven Test Considerations

Many test files use data directories like:

```
tests/data/checkpoint_N/
├── core/      # Core test cases
├── hidden/    # Functionality test cases
├── errors/    # Error test cases
```

When test data is already organized this way:

1. **Check that markers match data directories**:
   - Tests loading from `core/` should have no marker
   - Tests loading from `hidden/` should have `@pytest.mark.functionality`
   - Tests loading from `errors/` should have `@pytest.mark.error`

2. **Consider moving cases between directories** if:
   - A "core" case tests implicit behavior → move to `hidden/`
   - A "hidden" case tests explicit behavior → move to `core/`

---

## Example Analysis

Given spec excerpt:
```markdown
## Example 1
Input: `--now 2025-09-10T03:30:00Z --duration 1`
Output:
{"event":"SCHEDULE_PARSED","timezone":"UTC","jobs_total":2}
{"event":"JOB_ELIGIBLE","job_id":"job-root","kind":"daily",...}
```

And tests:
```python
def test_schedule_parsed_event():
    """Verify SCHEDULE_PARSED is emitted first."""
    # ✓ KEEP AS CORE - Example 1 shows this event first

def test_schedule_parsed_fields():
    """Verify SCHEDULE_PARSED has timezone and jobs_total."""
    # ✓ KEEP AS CORE - Example 1 shows these exact fields

def test_empty_schedule():
    """Verify empty schedule returns jobs_total=0."""
    # → MARK AS FUNCTIONALITY - No example shows empty schedule

def test_invalid_timezone():
    """Verify invalid timezone returns error."""
    # → MARK AS ERROR - Error handling case
```

---

## After Reclassification

1. **Run tests** to ensure markers are syntactically correct:
   ```bash
   cd problems/{problem} && pytest --collect-only tests/test_checkpoint_N.py
   ```

2. **Verify counts** match expectations:
   ```bash
   pytest --collect-only -m "not functionality and not error" tests/  # Core only
   pytest --collect-only -m functionality tests/  # Functionality only
   pytest --collect-only -m error tests/  # Error only
   ```

3. **Review the changes** - did any truly explicit tests get marked?
