---
version: 1.0
last_updated: 2025-12-17
---

# eval-problem

Evaluate a single problem directory containing multiple checkpoints.

## Quick Start

```bash
# Evaluate a problem directory
slop-code eval-problem outputs/my_run/file_backup

# With custom environment config
slop-code eval-problem outputs/my_run/file_backup -e configs/environments/docker-python3.12-uv.yaml

# With rubric grading
slop-code eval-problem outputs/my_run/file_backup \
  --rubric configs/rubrics/slop.jsonl \
  --rubric-model anthropic/sonnet-4.5
```

## Usage

```bash
slop-code eval-problem [OPTIONS] SUBMISSION_PATH
```

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `SUBMISSION_PATH` | Yes | Path to the problem directory |

## Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `-p, --problem-name` | string | (dir name) | Name of the problem |
| `-e, --env-config` | path | `../environment.yaml` | Path to environment configuration |
| `--snapshot-dir` | string | `snapshot` | Name of snapshot directory in checkpoints |
| `--rubric` | path | - | Path to rubric JSONL file for code quality grading |
| `--rubric-model` | string | - | Model ID for rubric grading (required if --rubric is set) |
| `--rubric-temperature` | float | 0.0 | Sampling temperature for rubric grading |
| `--rubric-provider` | enum | `OPENROUTER` | LLM provider for grading |

### Rubric Provider Values

| Value | Description |
|-------|-------------|
| `OPENROUTER` | Use OpenRouter API |
| `ANTHROPIC` | Use Anthropic API directly |

## Behavior

The command:

1. Loads the problem configuration from the problems directory
2. Iterates through all checkpoint directories (`checkpoint_1`, `checkpoint_2`, etc.)
3. Evaluates each checkpoint's snapshot against test cases
4. Optionally runs rubric-based code quality grading
5. Updates the problem-level report

### Directory Structure Expected

```
SUBMISSION_PATH/
├── checkpoint_1/
│   └── snapshot/
│       └── <agent code>
├── checkpoint_2/
│   └── snapshot/
│       └── <agent code>
└── ...
```

## Examples

**Basic evaluation:**
```bash
slop-code eval-problem outputs/my_run/file_backup
```

**Specify problem name explicitly:**
```bash
slop-code eval-problem outputs/renamed_dir -p file_backup
```

**With rubric grading:**
```bash
slop-code eval-problem outputs/my_run/file_backup \
  --rubric configs/rubrics/code_quality.jsonl \
  --rubric-model claude-sonnet-4-20250514 \
  --rubric-provider ANTHROPIC
```

**Custom snapshot directory:**
```bash
slop-code eval-problem outputs/my_run/file_backup --snapshot-dir code
```

## See Also

- [eval](eval.md) - Evaluate a full run directory
- [eval-snapshot](eval-snapshot.md) - Evaluate a single checkpoint snapshot
- [metrics judge](metrics.md#judge) - Batch rubric grading
