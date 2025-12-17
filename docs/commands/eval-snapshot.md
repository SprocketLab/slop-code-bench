---
version: 1.0
last_updated: 2025-12-17
---

# eval-snapshot

Evaluate a single snapshot directory against a specific checkpoint.

## Quick Start

```bash
slop-code eval-snapshot ./my_snapshot \
  -o ./eval_output \
  -p file_backup \
  -c 1 \
  -e configs/environments/docker-python3.12-uv.yaml
```

## Usage

```bash
slop-code eval-snapshot [OPTIONS] SNAPSHOT_DIR
```

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `SNAPSHOT_DIR` | Yes | Path to the snapshot directory containing code |

## Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `-o, --save-dir` | path | **required** | Path to save evaluation results |
| `-p, --problem-name` | string | **required** | Name of the problem |
| `-c, --checkpoint-num` | int | **required** | Checkpoint number (1-based) |
| `-e, --env-config` | path | **required** | Path to environment configuration |
| `--rubric` | path | - | Path to rubric JSONL file |
| `--rubric-model` | string | - | Model ID for rubric grading |
| `--rubric-temperature` | float | 0.0 | Sampling temperature |
| `--rubric-provider` | enum | `OPENROUTER` | LLM provider for grading |

## Behavior

This command evaluates a standalone snapshot directory against a specific checkpoint's test cases. Unlike `eval` and `eval-problem`, this command:

- Takes an arbitrary directory as the code snapshot
- Requires explicit specification of problem name and checkpoint number
- Outputs results to a separate directory (cannot be same as snapshot)
- Displays detailed case results with scores and diffs

### Output

The command displays:
- A table of case results with scores and attribute diffs
- A summary table of scores by group
- Total pass rate across all cases

## Examples

**Basic evaluation:**
```bash
slop-code eval-snapshot outputs/snapshot \
  -o outputs/eval \
  -p file_backup \
  -c 1 \
  -e configs/environments/docker-python3.12-uv.yaml
```

**With rubric grading:**
```bash
slop-code eval-snapshot outputs/snapshot \
  -o outputs/eval \
  -p file_backup \
  -c 2 \
  -e configs/environments/docker-python3.12-uv.yaml \
  --rubric configs/rubrics/slop.jsonl \
  --rubric-model claude-sonnet-4-20250514
```

**Evaluate different checkpoint:**
```bash
# Evaluate checkpoint 3 of a problem
slop-code eval-snapshot outputs/snapshot \
  -o outputs/eval_c3 \
  -p trajectory_api \
  -c 3 \
  -e configs/environments/docker-python3.12-uv.yaml
```

## Error Handling

Common errors:

| Error | Cause | Solution |
|-------|-------|----------|
| "Save directory cannot be the same as snapshot" | `-o` equals `SNAPSHOT_DIR` | Use different output path |
| "Checkpoint number out of range" | Invalid `-c` value | Check problem's checkpoint count |
| "Problem not found" | Invalid `-p` value | Verify problem exists |

## See Also

- [eval](eval.md) - Evaluate a full run directory
- [eval-problem](eval-problem.md) - Evaluate a problem directory
- [tools run-case](tools.md#run-case) - Run individual test cases
