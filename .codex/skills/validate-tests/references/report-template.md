# Validate Tests Report Template

## Context

- Problem: <problem>
- Checkpoint: <N>
- Spec path: problems/<problem>/checkpoint_N/spec.md (or checkpoint_N.md)
- Test paths: <list test files>

## Method

- Compared each test expectation to spec statements and examples.
- Treated the spec as authoritative; only inferred behavior that is directly supported.
- Considered common programming concepts only when implied by the spec.

## Findings (Ambiguous or Out-of-Scope)

For each finding, include evidence and a test-side fix.

### Test: <file::test_id or param case>
- **Expectation**: <what the test asserts>
- **Spec evidence**: <quote/section> or "No supporting spec text"
- **Assessment**: <ambiguous | out-of-scope | contradictory>
- **Rationale**: <why the spec does not support the expectation>

#### Fix
- Potential fixes (test-side): <specific changes>
- Spec change required: <yes/no; only "yes" if no viable test-side fix>

## Non-Issues (Optional)

- <Notable expectations that are clearly supported>

## Proposed Test Changes

- <file path>: <short description>

## Evaluation Run

Command:

```sh
uv run slop-code --quiet eval-snapshot \
    problems/<problem>/solutions/checkpoint_N \
    -p <problem> -o /tmp/eval -c N \
    -e configs/environments/docker-python3.12-uv.yaml --json
```

Results summary (from /tmp/eval):

- evaluation.json: <pytest_exit_code, pass_counts, total_counts>
- report.json: <failed tests summary>
- stdout/stderr: <notable errors>

## Failure Analysis (If Evaluation Fails)

- Likely cause: <solution incorrect | spec issue>
- Evidence: <trace lines or spec conflict>
- Next step: <fix solution | escalate spec issue>
