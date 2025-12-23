---
name: fix-solution
description: Continually test and repair solutions to benchmark problems until they pass. Use when a solution has failing tests. Invoke with /fix-solution <snapshot_path> <problem_name> <checkpoint_index>.
---

# Fix Solution

Iteratively test and repair a solution until all tests pass.

**Usage**: `/fix-solution /path/to/snapshot problem_name checkpoint_N`

**Example**: `/fix-solution outputs/run_001/submissions/file_backup/checkpoint_2/snapshot file_backup checkpoint_2`

---

## Core Principle

**Solutions are likely wrong - focus on fixing the solution code, not the tests.**

Tests should generally be trusted. However, the MOMENT there is any doubt whether the tests themselves are correct (not the solution), **immediately bring this up to the user for clarification**. Do not silently assume tests are wrong.

---

## Step 1: Run Initial Evaluation

Run the eval-snapshot command to see current test status:

```bash
slop-code --quiet eval-snapshot {snapshot_path} \
  -p {problem_name} \
  -c {checkpoint_index} \
  -e configs/environments/docker-python3.12-uv.yaml \
  -o /tmp/eval-output \
  --json
```

Parse the JSON output to identify:
- Total tests passed/failed
- Which specific tests are failing
- Error messages and stack traces

---

## Step 2: Analyze Failures

For each failing test:

1. **Read the test code** - Understand what behavior is expected
2. **Read the spec** - Verify the test aligns with requirements (`problems/{problem}/checkpoint_{N}.md`)
3. **Read the solution code** - Find the bug causing the failure
4. **Identify the fix** - Determine what change will make the test pass

**If a test seems incorrect:**
- Stop and ask the user before proceeding
- Explain why you think the test might be wrong
- Wait for user guidance before continuing

---

## Step 3: Fix the Solution

Edit the solution files in the snapshot directory to fix the failing tests.

**Keep fixes minimal:**
- Only change what's necessary to pass the test
- Don't refactor or "improve" unrelated code
- Preserve existing working functionality

---

## Step 4: Re-run Evaluation

After making fixes, run the evaluation again:

```bash
slop-code --quiet eval-snapshot {snapshot_path} \
  -p {problem_name} \
  -c {checkpoint_index} \
  -e configs/environments/docker-python3.12-uv.yaml \
  -o /tmp/eval-output \
  --json
```

**Loop until all tests pass** or you determine a test is genuinely incorrect.

---

## Step 5: Propagate to Future Checkpoints

If the fix needs to be applied to later checkpoints (checkpoint_3, checkpoint_4, etc.):

1. **Identify which files were changed** in the current checkpoint
2. **Check if those files exist** in future checkpoint snapshots
3. **Apply the same fix** to each future checkpoint
4. **Re-run evaluation** on each updated checkpoint to verify

```bash
# Example: Fix was in main.py, propagate to checkpoint_3
# First, check if checkpoint_3 has the same issue
slop-code --quiet eval-snapshot {base_path}/checkpoint_3/snapshot \
  -p {problem_name} \
  -c checkpoint_3 \
  -e configs/environments/docker-python3.12-uv.yaml \
  -o /tmp/eval-output \
  --json

# If same test fails, apply the fix there too
```

**Only propagate fixes that are relevant** - later checkpoints may have different implementations.

---

## Iteration Flow

```
┌─────────────────────────┐
│   Run Evaluation        │
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│   All Tests Pass?       │──── Yes ───► Done!
└───────────┬─────────────┘
            │ No
            ▼
┌─────────────────────────┐
│   Analyze Failures      │
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│   Test Seems Wrong?     │──── Yes ───► Ask User
└───────────┬─────────────┘
            │ No
            ▼
┌─────────────────────────┐
│   Fix Solution Code     │
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│   Propagate to Future   │
│   Checkpoints           │
└───────────┬─────────────┘
            │
            └──────────────────► (loop back to Run Evaluation)
```

---

## Common Fix Patterns

### Missing Error Handling
```python
# Solution missing try/except that spec requires
try:
    result = process(data)
except ValueError as e:
    return {"error": str(e)}
```

### Wrong Return Format
```python
# Test expects list, solution returns dict
# Fix: Return the correct format
return [item for item in results]  # not {"items": results}
```

### Off-by-One Errors
```python
# Test expects 0-indexed, solution uses 1-indexed
return index  # not index + 1
```

### Missing Edge Case Handling
```python
# Test passes empty input, solution crashes
if not data:
    return []
```

---

## Important Notes

- **Trust the tests first** - Assume solution bugs until proven otherwise
- **Ask about suspicious tests** - Don't silently decide tests are wrong
- **Keep fixes minimal** - Change only what's needed to pass
- **Always re-verify** - Run evaluation after every fix
- **Propagate consistently** - Apply fixes to all affected checkpoints
- **Track your changes** - Use git diff or similar to review what changed
