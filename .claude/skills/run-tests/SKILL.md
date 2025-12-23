---
name: run-tests
description: Run problem tests using eval-snapshot instead of raw pytest. Use this to evaluate solutions against benchmark tests in Docker. Invoke with /run-tests <snapshot_path> <problem_name> <checkpoint_index>.
---

# Run Tests

Run benchmark problem tests using the `eval-snapshot` command instead of raw pytest. This ensures tests run in the correct Docker environment with proper isolation.

**Usage**: `/run-tests <snapshot_path> <problem_name> <checkpoint_index>`

**Example**: `/run-tests outputs/run_001/submissions/file_backup/checkpoint_2/snapshot file_backup checkpoint_2`

---

## Command

```bash
slop-code --quiet eval-snapshot {snapshot_path} \
  -p {problem_name} \
  -c {checkpoint_index} \
  -e configs/environments/docker-python3.12-uv.yaml \
  -o /tmp/eval-output \
  --json
```

**Parameters:**
- `snapshot_path`: Path to the solution directory to test
- `problem_name`: Name of the problem (e.g., `file_backup`, `execution_server`)
- `checkpoint_index`: Checkpoint to evaluate (e.g., `checkpoint_1`, `checkpoint_2`)

---

## Output Location

Results are saved to the output directory (`/tmp/eval-output` by default):

```
/tmp/eval-output/
├── evaluation.json          # Structured test results
├── evaluation.log           # Detailed execution log
└── quality_analysis/        # Code quality metrics
    ├── ast_grep.jsonl       # AST-grep rule matches
    ├── files.jsonl          # File-level metrics
    ├── overall_quality.json # Aggregated quality scores
    └── symbols.jsonl        # Symbol/function metrics
```

---

## Reading Results

### evaluation.json Structure

```json
{
  "problem_name": "eve_industry",
  "checkpoint_name": "checkpoint_3",
  "duration": 34.71,
  "entrypoint": "uv run industry.py",
  "tests": [
    {
      "id": "test_naga",
      "checkpoint": "checkpoint_1",
      "group_type": "Regression",
      "status": "passed",
      "duration_ms": 1029.27,
      "file_path": ".evaluation_tests/test_checkpoint_1.py"
    }
  ],
  "pass_counts": {
    "Regression": 25,
    "Core": 5,
    "Functionality": 5
  },
  "total_counts": {
    "Regression": 26,
    "Core": 5,
    "Functionality": 5
  },
  "pytest_exit_code": 1,
  "pytest_collected": 36,
  "infrastructure_failure": false
}
```

### Key Fields

| Field | Description |
|-------|-------------|
| `tests` | Array of individual test results |
| `pass_counts` | Passed tests by group type |
| `total_counts` | Total tests by group type |
| `pytest_exit_code` | 0 = all passed, 1 = some failed |
| `infrastructure_failure` | True if environment setup failed |

### Test Group Types

| Group | Description |
|-------|-------------|
| `Core` | Must pass for checkpoint to pass |
| `Functionality` | Additional coverage (optional) |
| `Regression` | Tests from prior checkpoints |
| `Error` | Error handling tests |

---

## Interpreting Results

### Quick Summary

```bash
# Parse with jq to get summary
cat /tmp/eval-output/evaluation.json | jq '{
  passed: .pass_counts,
  total: .total_counts,
  exit_code: .pytest_exit_code
}'
```

### Finding Failed Tests

```bash
# List failed tests
cat /tmp/eval-output/evaluation.json | jq '.tests[] | select(.status == "failed") | .id'
```

### Check Pass/Fail by Group

```bash
# Core tests (must all pass)
cat /tmp/eval-output/evaluation.json | jq '.pass_counts.Core == .total_counts.Core'
```

---

## Common Workflows

### Run and Check Status

```bash
slop-code --quiet eval-snapshot ./snapshot \
  -p file_backup -c checkpoint_1 \
  -e configs/environments/docker-python3.12-uv.yaml \
  -o /tmp/eval-output --json

# Check if passed
if [ $(cat /tmp/eval-output/evaluation.json | jq '.pytest_exit_code') -eq 0 ]; then
  echo "All tests passed!"
else
  echo "Some tests failed"
  cat /tmp/eval-output/evaluation.json | jq '.tests[] | select(.status == "failed")'
fi
```

### Run Multiple Checkpoints

```bash
for checkpoint in checkpoint_1 checkpoint_2 checkpoint_3; do
  echo "=== $checkpoint ==="
  slop-code --quiet eval-snapshot ./submissions/$checkpoint/snapshot \
    -p my_problem -c $checkpoint \
    -e configs/environments/docker-python3.12-uv.yaml \
    -o /tmp/eval-$checkpoint --json
  cat /tmp/eval-$checkpoint/evaluation.json | jq '.pass_counts'
done
```

---

## Troubleshooting

### Infrastructure Failure

If `infrastructure_failure: true`:
- Docker may not be running
- Image build failed
- Check `evaluation.log` for details

### Tests Not Found

If `pytest_collected: 0`:
- Problem name may be wrong
- Checkpoint doesn't exist
- Test files missing from problem directory

### Timeout Issues

Default timeout is 180s per test. For long-running tests, this is controlled in the problem's pytest config.

---

## Notes

- Always use `eval-snapshot` instead of raw pytest for benchmark problems
- Tests run in isolated Docker containers
- Results include both correctness and quality metrics
- Use `--json` flag to get machine-readable output
- The `-o` flag specifies where to save results
