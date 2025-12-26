---
name: checkpoint-ambiguity-review
description: Review checkpoint specs and tests to identify tests that encode ambiguous interpretations rather than explicit requirements. Use when asked to check checkpoint_N.md against test_checkpoint_N.py, when auditing tests for ambiguity, or when reviewing snapshot eval failures for interpretive issues.
---

# Checkpoint Ambiguity Review

## Overview

Review a checkpoint's spec and tests to find tests that enforce a reasonable but
non-explicit interpretation, and report those cases with rationale and fixes.

## Workflow

### 1) Collect inputs

- Problem name and checkpoint number (N).
- Test file path(s) and checkpoint spec path (if not provided, infer):
  - Spec: `problems/{problem}/checkpoint_{N}.md`
  - Tests: `problems/{problem}/tests/test_checkpoint_{N}.py`
  - Also scan `problems/{problem}/tests/conftest.py` and
    `problems/{problem}/tests/data/` if they influence expectations.
- Optional: snapshot path for ambiguity verification.

### 2) Read the spec and tests

- Extract explicit requirements from the spec.
- Map each test assertion to a specific spec clause or an implied behavior.
- Note any test assumptions that are not spelled out in the spec.

### 3) Flag ambiguous interpretations

Only report tests that enforce an interpretation that could reasonably differ
given the spec wording. Do not report tests that are simply incorrect against
explicit requirements.

Common ambiguity cues:
- Output ordering when the spec does not mandate order.
- Tie-breaking rules that are unstated.
- Whitespace, casing, or formatting details not defined by the spec.
- Rounding or precision requirements not defined.
- Error handling for invalid inputs when not specified.
- Boundary behavior (inclusive/exclusive) not stated.
- Default values or optional fields not defined.
- Determinism or randomness expectations not specified.
- Multiple reasonable data structure representations (list vs set, map order).

### 4) Optional snapshot verification

If a snapshot is provided, run:

```bash
slop-code --quiet eval-snapshot {snapshot} -p {problem} -o /tmp/eval -c {N} -e configs/environments/docker-python3.12-uv.yaml --json
```

Use failures to corroborate ambiguity, not to invent it. A failing test is
ambiguous only if the spec supports multiple reasonable interpretations.

### 5) Report format

Use the following structure for each ambiguous test:

```
## {test name} ({path}::{node_id})

**Why:** {spec language + alternate interpretation that could be valid}
**Fix:** {proposed test relaxation or spec clarification}
```

Keep entries concise and actionable. If no ambiguity is found, state that
clearly (e.g., "No ambiguity issues found.").
