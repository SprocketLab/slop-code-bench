---
version: 1.0
last_updated: 2025-12-17
---

# eval

Evaluate a directory of agent inference results.

## Quick Start

```bash
# Evaluate all problems in a run directory
slop-code eval outputs/my_run

# Evaluate specific problems
slop-code eval outputs/my_run --problem file_backup --problem trajectory_api

# Evaluate with parallel workers
slop-code eval outputs/my_run --num-workers 4
```

## Usage

```bash
slop-code eval [OPTIONS] AGENT_RUN_DIR
```

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `AGENT_RUN_DIR` | Yes | Path to the inference directory |

## Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--problem` | string | (all) | Name of specific problems to evaluate (repeatable) |
| `--pass-policy` | enum | `ALL_CASES` | Policy to determine if checkpoint passed |
| `-e, --env-config` | path | `<run>/environment.yaml` | Path to environment configuration |
| `--live-progress/--no-live-progress` | flag | false | Enable live progress display |
| `-proc, --num-workers` | int | 1 | Number of parallel evaluation workers |
| `--overwrite` | flag | false | Re-evaluate problems with existing results |

### Pass Policy Values

| Value | Description |
|-------|-------------|
| `ALL_CASES` | Pass only if all test cases pass |
| `ANY_CASE` | Pass if at least one case passes |
| `MAJORITY` | Pass if majority of cases pass |

## Behavior

The `eval` command:

1. Discovers all problem directories within `AGENT_RUN_DIR`
2. Skips problems that already have `evaluation.json` files (unless `--overwrite`)
3. Re-evaluates if problem configuration has changed since last evaluation
4. Writes evaluation results to each checkpoint directory
5. Generates `checkpoint_results.jsonl` report at run level

### Auto-Skip Logic

When no `--problem` flags are specified and `--overwrite` is not set, the command automatically skips problems where:
- All checkpoints have `evaluation.json` files
- The problem configuration hasn't changed since evaluation

To force re-evaluation, use `--overwrite` or specify the problem explicitly with `--problem`.

## Output Files

After evaluation, each checkpoint directory contains:
- `evaluation.json` - Detailed evaluation results
- Test case reports

At the run level:
- `checkpoint_results.jsonl` - Consolidated report with one line per checkpoint

## Examples

**Basic evaluation:**
```bash
slop-code eval outputs/claude_code_run_20251217
```

**Evaluate with custom environment:**
```bash
slop-code eval outputs/my_run -e configs/environments/docker-python3.12-uv.yaml
```

**Force re-evaluation of all problems:**
```bash
slop-code eval outputs/my_run --overwrite
```

**Parallel evaluation with progress:**
```bash
slop-code eval outputs/my_run --num-workers 8 --live-progress
```

## See Also

- [eval-problem](eval-problem.md) - Evaluate a single problem
- [eval-snapshot](eval-snapshot.md) - Evaluate a single snapshot
- [run](run.md) - Run agents (includes automatic evaluation)
