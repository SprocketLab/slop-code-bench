---
name: validate-run
description: Validate all checkpoints from an agent run directory in parallel. Spawns test-validator agents for each checkpoint and summarizes results. Invoke with /validate-run <run_path> [problem].
---

# Validate Run

Analyze all checkpoints from an agent's run directory, spawning test-validator agents in parallel to validate each checkpoint against its specification.

**Usage**:
- `/validate-run /path/to/run/directory` - Validate all problems/checkpoints
- `/validate-run /path/to/run/directory file_backup` - Validate specific problem only

---

## IMPORTANT: You Must Verify Sub-Agent Results

**Sub-agents (Sonnet) make mistakes.** After collecting their reports, you MUST:

1. Read the actual spec and test files yourself
2. Verify each TEST_BUG classification is correct
3. Check that proposed fixes are actually valid
4. Correct any errors before presenting to the user

**See Step 4 for detailed verification process.**

---

## Step 1: Discover Checkpoints

The run directory structure varies. Look for checkpoints in these patterns:

```
# Agent run output structure
{run_path}/submissions/{problem}/checkpoint_N/

# Or direct problem solutions
{run_path}/checkpoint_N/

# Or solutions directory
{run_path}/solutions/checkpoint_N/
```

**Use this command to discover checkpoints:**

```bash
find {run_path} -type d -name "checkpoint_*" | sort
```

For each checkpoint found, extract:
- **problem_name**: The problem being tested (from path or user input)
- **checkpoint**: The checkpoint number (e.g., `checkpoint_1`, `checkpoint_2`)
- **snapshot_path**: Full path to the checkpoint directory

---

## Step 2: Launch Validators in Parallel

**CRITICAL: Launch ALL test-validator agents in a SINGLE message with multiple Task tool calls.**

For each checkpoint discovered, spawn a test-validator agent:

```
Task tool call 1: test-validator for {problem} checkpoint_1
Task tool call 2: test-validator for {problem} checkpoint_2
Task tool call 3: test-validator for {problem} checkpoint_3
...
```

**Prompt template for each agent:**

```
Validate the following checkpoint:

Problem: {problem_name}
Checkpoint: checkpoint_{N}
Snapshot Path: {snapshot_path}

Run the evaluation, analyze all test results against the specification, and save your report to:
problems/{problem_name}/checkpoint_{N}_report.md

Focus on determining whether any test failures indicate:
1. Solution bugs (code doesn't match spec)
2. Test bugs (tests expect behavior not in spec)
3. Spec ambiguity (unclear requirements)
```

---

## Step 3: Collect Results

After all validators complete, read each report:

```
problems/{problem}/checkpoint_1_report.md
problems/{problem}/checkpoint_2_report.md
...
```

Extract from each report:
- **VERDICT** line (the overall conclusion)
- **SUMMARY** table (counts)
- **ACTION ITEMS** (what needs fixing)

---

## Step 4: VERIFY SUB-AGENT RESULTS (CRITICAL)

**WARNING: Sub-agents (Sonnet) can and do make mistakes. You MUST verify their findings.**

### DO NOT blindly trust sub-agent reports. For each finding:

1. **Read the spec quote** - Does it actually support the sub-agent's conclusion?
2. **Read the test assertion** - Is the sub-agent's interpretation correct?
3. **Check the classification** - Does TEST_BUG vs SOLUTION_BUG make sense?
4. **Verify the proposed fix** - Is it actually more lenient, or just different?

### Common Sub-Agent Mistakes to Catch:

| Mistake | How to Spot It |
|---------|----------------|
| Wrong classification | Spec clearly requires X, but agent says TEST_BUG |
| Invented spec requirements | Agent quotes spec but adds interpretation not present |
| Missed spec text | Agent says "spec silent" but spec does address it |
| Bad fix proposal | "Fix" changes behavior instead of relaxing constraint |
| Inconsistent verdicts | SUMMARY counts don't match FINDINGS |

### Verification Process:

```
For each report with TESTS_HAVE_BUGS or MIXED verdict:

1. Open the spec file: problems/{problem}/checkpoint_N.md
2. Open the test file: problems/{problem}/tests/test_checkpoint_N.py
3. For each TEST_BUG finding:
   a. Find the spec quote - is it accurate and complete?
   b. Find the test assertion - does it really expect what agent claims?
   c. Is the classification correct?
   d. Is the proposed fix actually valid?
4. Correct any errors before including in final summary
```

### If You Find Sub-Agent Errors:

- **Override the classification** in your summary
- **Note the correction** so user knows agent was wrong
- **Provide correct fix** if agent's fix was wrong
- **Adjust counts** in the summary table

**Example correction note:**
```markdown
### Corrections to Sub-Agent Reports

- checkpoint_2 FINDING-003: Reclassified from TEST_BUG → SOLUTION_BUG
  (Agent missed spec requirement on line 45: "MUST return exactly 1")
```

---

## Step 5: Generate Summary Report

Present a consolidated summary to the user:

```markdown
# Run Validation Summary

**Run Path**: {run_path}
**Date**: {date}

## Overall Results

| Problem | Checkpoint | Verdict | Failing | Solution Bugs | Test Bugs |
|---------|------------|---------|---------|---------------|-----------|
| file_backup | 1 | SOLUTION_CORRECT | 0 | 0 | 0 |
| file_backup | 2 | TESTS_HAVE_BUGS | 3 | 0 | 3 |
| file_backup | 3 | MIXED | 5 | 2 | 3 |

## Verdicts by Type

- SOLUTION_CORRECT: N checkpoints
- SOLUTION_HAS_BUGS: N checkpoints
- TESTS_HAVE_BUGS: N checkpoints
- MIXED: N checkpoints
- SPEC_AMBIGUOUS: N checkpoints

## Action Items Required

<!-- Fix preference: MAKE_LENIENT > REMOVE_TEST >> UPDATE_SPEC -->

### Test Fixes: MAKE_LENIENT (Preferred)
- [ ] file_backup checkpoint_2 `test_error_code`: Change `assert rc == 1` → `assert rc != 0`
- [ ] file_backup checkpoint_3 `test_output_order`: Change `assert x == [a,b]` → `assert set(x) == {a,b}`

### Test Fixes: REMOVE_TEST
- [ ] file_backup checkpoint_2 `test_undefined_edge`: DELETE (tests undefined behavior)

### Solution Fixes
- [ ] file_backup checkpoint_3: {specific fix from report}

### Spec Clarifications (LAST RESORT)
- [ ] {only if test cannot be made lenient or removed}

## Corrections to Sub-Agent Reports

<!-- Include this section if you found any errors in sub-agent analysis -->

- checkpoint_2 FINDING-003: Reclassified TEST_BUG → SOLUTION_BUG
  - Agent claimed: "spec is silent on error codes"
  - Actually: spec line 45 says "MUST return exit code 1"
  - Correct fix: Solution must return 1, not test change needed

## Detailed Reports

Reports saved to:
- problems/file_backup/checkpoint_1_report.md
- problems/file_backup/checkpoint_2_report.md
- problems/file_backup/checkpoint_3_report.md
```

---

## Quick Verdicts Reference

| Verdict | Meaning | Action |
|---------|---------|--------|
| `SOLUTION_CORRECT` | All good, solution passes | None |
| `SOLUTION_HAS_BUGS` | Solution needs fixes | Fix solution code |
| `TESTS_HAVE_BUGS` | Tests are wrong | Fix test assertions |
| `MIXED` | Both have issues | Fix both |
| `SPEC_AMBIGUOUS` | Spec unclear | Clarify spec first |

## Fix Preference Hierarchy

**When tests have bugs, prefer fixes in this order:**

```
1. MAKE_LENIENT  ← STRONGLY PREFERRED (relax assertion)
2. REMOVE_TEST   ← If test is fundamentally flawed
3. UPDATE_SPEC   ← LAST RESORT ONLY
```

- Making tests lenient keeps coverage while accepting valid implementations
- Removing tests is better than keeping broken ones
- Changing specs is dangerous and affects all documentation

## Recommended Tools for Lenient Tests

Many strict tests can be fixed using these tools:

| Tool | Use Case | Example |
|------|----------|---------|
| `deepdiff` | Ignore order, precision, extra fields | `DeepDiff(a, b, ignore_order=True)` |
| `jsonschema` | Validate structure not exact values | `validate(output, schema)` |
| `normalize()` | Handle whitespace, case, key order | `normalize(actual) == normalize(expected)` |

```python
# Common fix pattern:
from deepdiff import DeepDiff

# BEFORE (too strict):
assert actual == expected

# AFTER (lenient):
diff = DeepDiff(expected, actual, ignore_order=True, significant_digits=5)
assert not diff
```

---

## Example

```
User: /validate-run problems/file_backup/solutions file_backup

Assistant: [discovers checkpoints, launches test-validator agents in parallel]

Assistant: All validators complete. Here is the summary:

# Run Validation Summary
...
```
