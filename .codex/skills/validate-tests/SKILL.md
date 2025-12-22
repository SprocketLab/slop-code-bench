---
name: validate-tests
description: >
  Validate new-style pytest checkpoint tests against the checkpoint spec for
  SCBench problems. Use when comparing
  problems/<problem>/tests/checkpoint_N.py to
  problems/<problem>/checkpoint_N.md (or when verifying any checkpoint test
  expectations against the spec). Flag contradictions, out-of-scope tests,
  missing coverage, and ambiguous spec assumptions.
---

# Validate Checkpoint Tests vs Spec

## Overview

Compare a checkpoint's pytest file against its spec and produce a list of
fixes/errors. Flag everything: contradictions, assumptions, gaps, and
ambiguity.

## Workflow

1. **Open the inputs**
   - Read the checkpoint spec:
     `problems/<problem>/checkpoint_N.md`.
   - Read the tests:
     `problems/<problem>/tests/checkpoint_N.py`.
   - If either path is missing, search for likely alternatives
     (`checkpoint_N/spec.md`, `tests/test_checkpoint_N.py`) and ask the user
     which file is authoritative.

2. **Extract spec requirements**
   - List the explicit requirements (inputs, outputs, formats, ordering,
     constraints, and error handling).
   - Note any optional or undefined behavior (words like "may", "should",
     "optional", or vague phrases).
   - Record example behaviors in the spec and treat them as authoritative when
     resolving ambiguities unless the spec explicitly says otherwise.

3. **Inventory test expectations**
   - Enumerate each test case and the core assertions it makes.
   - Note any setup/fixtures that imply requirements (e.g., working directory,
     static files, CLI flags, environment variables).
   - If tests reference assets or case data, open only the referenced files
     needed to understand the expectations.

4. **Map tests to spec**
   - For each test assertion, identify the exact spec clause that authorizes
     it.
   - If no clause exists, mark it as an assumption or out-of-scope test.
   - If the test contradicts the spec, mark it as an error.

5. **Find missing coverage**
   - For each spec requirement, check that at least one test validates it.
   - Flag untested requirements as missing coverage.

6. **Report issues**
   - Go one problem at a time (each issue is its own entry).
   - For each problem, include category, evidence, and a proposed solution.
   - Quote the relevant spec and test lines with file paths and line numbers.
   - Do not edit tests or spec without user approval. If something is unclear,
     ask for clarification.
7. **Run eval-snapshot**
   - After reporting issues, run this command with the current problem and
     checkpoint values:
     ```bash
     # `--quiet` is a global flag and must come before `eval-snapshot`.
     uv run slop-code --quiet eval-snapshot \
         problems/{problem}/solutions/checkpoint_N \
         -p {problem} -o /tmp/eval -c N \
         -e configs/environments/docker-python3.12-uv.yaml --json
     ```

## Output Format

Produce a list of fixes/errors in this order:

1. **Errors**: test expectations that contradict the spec.
2. **Out-of-scope/Assumptions**: tests asserting behavior not specified.
3. **Missing coverage**: spec requirements without tests.
4. **Ambiguities**: spec text unclear but tests assume a specific behavior.

Use concise bullets with file references and short quotes. Go one problem at a
time and include a proposed solution per problem.

Example:

```
Problem 1 (Error)
- Evidence: problems/foo/tests/checkpoint_2.py:41 expects sorted output, but
  problems/foo/checkpoint_2.md:87 says "preserve input order".
- Proposed solution: update the test to preserve input order, or clarify the
  spec if sorted output is intended.

Problem 2 (Out-of-scope/Assumption)
- Evidence: problems/foo/tests/checkpoint_2.py:73 asserts empty input returns
  "[]", but problems/foo/checkpoint_2.md has no empty-input behavior.
- Proposed solution: add spec language for empty input or relax the test.

Problem 3 (Missing coverage)
- Evidence: problems/foo/checkpoint_2.md:112 requires error on duplicate IDs
  with non-zero exit code, but no test asserts the error path.
- Proposed solution: add a test that triggers the duplicate-ID error path.

Problem 4 (Ambiguity)
- Evidence: problems/foo/tests/checkpoint_2.py:95 assumes floats are rounded to
  2 decimals; spec only says "format as decimal" with no precision defined.
- Proposed solution: clarify precision in the spec or loosen the test to accept
  multiple precisions.
```

## Notes
- **CRITICAL** The spec and examples are always the source of truth.
- Treat spec language ("must", "shall") as authoritative.
- Examples in the spec are illustrative, but use them as authoritative when
  resolving ambiguous spec language unless the spec explicitly says otherwise.
- If the spec and tests disagree, stop and ask the user how to proceed.
- For a quick pass, use `references/validation-checklist.md`.
