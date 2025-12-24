---
name: edge-cases
description: Analyze checkpoint tests and suggest missing edge cases. Use after writing tests or when reviewing test coverage. Invoke with /edge-cases <problem> <checkpoint>.
---

# Edge Case Analyzer

Analyze a checkpoint's spec and existing tests to identify and add missing edge cases.

**Usage**: `/edge-cases execution_server checkpoint_2`

## Workflow

1. **Read the spec** - Understand all requirements, constraints, error conditions
2. **Read existing tests** - See what's already covered
3. **Identify gaps** - Find missing edge cases
4. **Add skeleton tests** - Append to test file with TODOs

---

## Step 1: Gather Context

Read these files for the specified problem/checkpoint:

```
problems/{problem}/checkpoint_N.md
problems/{problem}/tests/conftest.py
problems/{problem}/tests/test_checkpoint_N.py
```

---

## Step 2: Analyze for Gaps

**For each requirement in the spec, ask:**

1. What happens with empty/null input?
2. What happens at boundary values (0, -1, max, min)?
3. What happens with malformed input?
4. What happens with missing required fields?
5. What happens with unexpected types?
6. Are there race conditions or state edge cases?
7. Are there format edge cases (unicode, special chars)?

**Cross-reference with existing tests:**

- Which spec requirements have tests?
- Which error conditions are tested?
- Which boundary conditions are tested?
- What did the spec mention that tests don't cover?

---

## Important: Avoid Ambiguous Cases

**Only add edge cases where the spec is clear about expected behavior.**

If the spec is ambiguous or there are multiple valid interpretations:
- **Don't add a test** - it's not a valid edge case
- The spec should define the expected behavior, not the tests
- Tests should verify spec compliance, not invent requirements

**Good edge case**: Spec says "return error for negative values" → test with -1
**Bad edge case**: Spec doesn't mention negatives → we don't know what should happen

Ask yourself: "Can I point to the spec line that defines this behavior?"
- **Yes** → Valid edge case
- **No** → Skip it or note the spec ambiguity

---

## Step 3: Generate Skeleton Tests

Append to `test_checkpoint_N.py`:

```python
# === EDGE CASES (review and implement) ===

@pytest.mark.functionality
def test_empty_input(entrypoint_argv):
    """Edge case: Empty input should return appropriate error.

    Spec says: [quote relevant spec section]
    """
    # TODO: Implement - call with empty input, verify error handling
    pytest.fail("Not implemented")


@pytest.mark.functionality
def test_negative_value(entrypoint_argv):
    """Edge case: Negative values should be rejected.

    Spec says: [quote relevant spec section]
    """
    # TODO: Implement - test with negative input
    pytest.fail("Not implemented")


@pytest.mark.functionality
def test_unicode_input(entrypoint_argv):
    """Edge case: Unicode characters in input.

    Spec says: [quote relevant spec section]
    """
    # TODO: Implement - test with unicode characters
    pytest.fail("Not implemented")
```

---

## Markers to Use

**All edge cases use `@pytest.mark.functionality`.**

Edge cases are additional coverage beyond the core tests - they should not block a passing submission. Core tests cover the main spec requirements; edge cases catch less common scenarios.

---

## Common Edge Case Categories

See [patterns.md](patterns.md) for detailed patterns by problem type:

**Always check:**
- Empty/null inputs
- Boundary values (0, -1, MAX_INT, empty string)
- Malformed data (invalid JSON, wrong types)
- Missing required fields
- Duplicate handling
- Unicode and special characters
- Very large inputs
- Concurrent operations (if applicable)

---

## After Adding Skeletons

1. Review each TODO and implement the test
2. Run eval-snapshot to verify:
   ```bash
   slop-code -v eval-snapshot problems/{problem}/solutions/checkpoint_N \
       -p {problem} -o /tmp/eval -c N \
       -e configs/environments/docker-python3.12-uv.yaml --json
   ```
3. Remove `pytest.fail("Not implemented")` as you implement each test

---

## Example Output

For `execution_server checkpoint_1`, might generate:

```python
# === EDGE CASES (review and implement) ===

@pytest.mark.functionality
def test_execute_empty_command(client):
    """Edge case: Empty command string.

    Spec says: [quote relevant section about command validation]
    """
    response = client.post("/v1/execute", json={"command": ""})
    # TODO: Verify appropriate error response
    pytest.fail("Not implemented")


@pytest.mark.functionality
def test_execute_missing_command(client):
    """Edge case: Request body missing 'command' field.

    Spec says: [quote relevant section about required fields]
    """
    response = client.post("/v1/execute", json={})
    # TODO: Verify 400/422 response
    pytest.fail("Not implemented")


@pytest.mark.functionality
def test_execute_unicode_output(client):
    """Edge case: Command that outputs unicode characters.

    Spec says: [quote relevant section about output handling]
    """
    response = client.post("/v1/execute", json={"command": "echo '日本語'"})
    # TODO: Verify unicode is preserved in response
    pytest.fail("Not implemented")
```

---

## Reference

- [patterns.md](patterns.md) - Edge case patterns by problem type
