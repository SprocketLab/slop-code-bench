# Debugging Test Failures

Quick reference for debugging eval-snapshot failures.

## Output Structure

When `eval-snapshot` runs (with `--json`), it creates:

```
{output_dir}/evaluation/
├── report.json    # Structured test results (MOST USEFUL)
├── stdout.txt     # Full pytest output with diffs
└── stderr.txt     # Package installs, runtime errors
```

And at the output root:

```
{output_dir}/evaluation.json  # Per-test results and group types
```

## Fast Debugging Commands

**1. Quick summary:**
```bash
jq '.results.summary' {output_dir}/evaluation/report.json
# Output: {"tests": 20, "passed": 18, "failed": 2, ...}
```

**2. Quick group summary:**
```bash
jq '.pass_counts' {output_dir}/evaluation.json
```

**3. Find failed tests:**
```bash
jq -r '.results.tests[] | select(.status == "failed") | .name' \
  {output_dir}/evaluation/report.json
```

**4. Get traceback for a failure:**
```bash
jq -r '.results.tests[] | select(.status == "failed") | .trace' \
  {output_dir}/evaluation/report.json | head -50
```

**5. Read stdout.txt for pytest diff:**
```
E       - SSTART: S-U8A4 VI...    # Expected (in test)
E       ? -
E       + START: S-U8A4 VI...     # Actual (from solution)
```

Lines starting with `-` are expected, `+` are actual, `?` marks the diff
position.

## Common Failure Types

| `raw_status` | Meaning | Debug Approach |
|--------------|---------|----------------|
| `call_failed` | Assertion failed | Check `.trace` for the diff |
| `setup_failed` | Fixture/setup error | Check stderr.txt for import errors |
| `error` | Exception during test | Check `.trace` for exception |
| `timeout` | Test exceeded timeout | Increase timeout or check for hangs |

## Example Debug Session

```bash
# 1. Run eval-snapshot
# `--quiet` is a global flag and must come before `eval-snapshot`.
slop-code --quiet eval-snapshot problems/my_problem/checkpoint_1/solution \
  -p my_problem -o /tmp/debug -c 1 \
  -e configs/environments/docker-python3.12-uv.yaml --json

# 2. Check what failed
jq '.results.summary' /tmp/debug/evaluation/report.json

# 3. Get failed test names
jq -r '.results.tests[] | select(.status == "failed") | .name' \
  /tmp/debug/evaluation/report.json

# 4. Read the diff
grep -A 30 "FAILED" /tmp/debug/evaluation/stdout.txt

# 5. Decide: fix test or fix solution based on spec
```

## Pro Tips

- **report.json is structured** - Use `jq` to extract exactly what you need
- **stdout.txt has the visual diff** - Best for understanding assertion failures
- **stderr.txt catches runtime issues** - Check here for import errors, missing
  deps
- **The `.trace` field** contains the full formatted traceback
- **Retried tests** have `"retries": N` - flaky tests may indicate timing issues
