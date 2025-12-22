---
name: validate-tests
description: Analyze problem checkpoint tests against the checkpoint specification to flag ambiguous or out-of-scope expectations, propose test-side fixes, and (after applying fixes) run the required eval-snapshot command to validate changes. Use when reviewing or editing checkpoint tests versus a spec.
---

# Validate Tests

## Report Template

Use `references/report-template.md` as the standard structure for reporting findings and evaluation results.

## Workflow

1. Identify the problem name and checkpoint number.
2. Preflight: confirm `problems/<problem>/checkpoint_N.md` exists. If not, reject running this skill and tell the user.
2. Open the spec and tests:
   - Spec: `problems/<problem>/checkpoint_N.md`. If the spec is not at this path, reject running this skill and tell the user.
   - Tests: `problems/<problem>/tests/` (e.g., `test_checkpoint_N.py`, `checkpoint_N.py`) and any related fixtures.
3. Map each test expectation to the spec:
   - List each test/param case and its assertions.
   - Locate explicit spec statements or examples that justify each expectation.
   - Consider common programming concepts only when clearly implied by the spec (e.g., parsing, ordering, glob/path semantics, numeric bounds), but do not assume behavior the spec does not imply.
4. Classify scope:
   - In-scope: explicitly stated or directly inferable from the spec or its examples.
   - Ambiguous/out-of-scope: not supported by the spec/examples, or in conflict with them.
5. Report ambiguous/out-of-scope tests with evidence:
   - Test id/path and expectation (include file/line references).
   - Spec evidence (quote/section) or state that none exists.
   - Why the expectation is ambiguous/out-of-scope.
   - Potential fixes that change the tests to align with the spec.
   - **Do not suggest modifying the spec unless there is no viable test-side fix.**
6. When the user gives guidance, implement the fixes in the tests.
7. Run evaluation immediately after fixing tests (no user prompt; do not ask):
   ```sh
   uv run slop-code --quiet eval-snapshot \
       problems/{problem}/solutions/checkpoint_N \
       -p {problem} -o /tmp/eval -c N \
       -e configs/environments/docker-python3.12-uv.yaml --json
   ```
   If the sandbox blocks the command, rerun with the required escalated permissions.
8. Interpret `/tmp/eval` results (similar structure to `scratch/attempts`):
   - `/tmp/eval/evaluation.json` for pass/fail counts and `pytest_exit_code`.
   - `/tmp/eval/evaluation/report.json` for per-test status and traces.
   - `/tmp/eval/evaluation/stdout.txt` and `/tmp/eval/evaluation/stderr.txt` for raw output.
9. If evaluation fails:
   - Assume the solution is incorrect first; explain why it conflicts with the spec.
   - If a failure indicates the spec is wrong or contradictory, alert the user immediately.
