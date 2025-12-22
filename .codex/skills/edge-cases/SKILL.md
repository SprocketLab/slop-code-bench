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
4. **Implement edge-case tests** - Add fully implemented tests with real assertions

---

## Step 1: Gather Context

Read these files for the specified problem/checkpoint:

```
problems/{problem}/checkpoint_N/spec.md    # or checkpoint_N.md
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
   - Use `\uXXXX` escapes to keep source files ASCII when needed.

**Cross-reference with existing tests:**

- Which spec requirements have tests?
- Which error conditions are tested?
- Which boundary conditions are tested?
- What did the spec mention that tests don't cover?

See [references/edge-case-categories.md](references/edge-case-categories.md) for
the category checklist and [references/patterns.md](references/patterns.md) for
problem-type patterns.

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

## Step 3: Implement Edge Case Tests

Append to `test_checkpoint_N.py` with fully implemented tests. Do not add
TODOs, `pytest.fail`, or placeholder assertions. If you cannot implement an
edge case from the spec, skip it or ask for clarification instead of adding
incomplete tests.

Keep tests readable with tiny helper functions for recurring patterns (CLI
runs, input setup, HTTP JSON requests). Prefer local helpers in the test module
unless the helper is shared across multiple test files. See
[references/helper-patterns.md](references/helper-patterns.md) for helper ideas
and [references/example-patterns.md](references/example-patterns.md) for
CLI/HTTP layouts.

Do not leave placeholder docstrings. Either quote the spec line or remove the
docstring entirely.

---

## Markers to Use

**All edge cases use `@pytest.mark.functionality`.**

Edge cases are additional coverage beyond the core tests - they should not block a passing submission. Core tests cover the main spec requirements; edge cases catch less common scenarios.

---

## After Adding Tests

1. Run eval-snapshot to verify:
   ```bash
   slop-code --quiet eval-snapshot problems/{problem}/checkpoint_N/solution \
       -p {problem} -o /tmp/eval -c N \
       -e configs/environments/docker-python3.12-uv.yaml --json
   ```

---

## Reference

- [references/edge-case-categories.md](references/edge-case-categories.md)
  - Common edge-case categories to scan for gaps
- [references/helper-patterns.md](references/helper-patterns.md)
  - Reusable helpers for normalizing outputs and errors
- [references/example-patterns.md](references/example-patterns.md)
  - CLI and HTTP test layouts
- [references/patterns.md](references/patterns.md)
  - Edge case patterns by problem type
