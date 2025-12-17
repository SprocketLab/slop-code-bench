---
version: 1.0
last_updated: 2025-12-17
---

# metrics

Commands for calculating metrics on agent submissions.

## Subcommands

| Command | Description |
|---------|-------------|
| [`static`](#static) | Calculate static code quality metrics |
| [`judge`](#judge) | Run LLM judge evaluation |
| [`carry-forward`](#carry-forward) | Carry forward rubric grades from previous checkpoints |
| [`variance`](#variance) | Compute variance across multiple runs |

---

## static

Calculate and save static code quality metrics for all problems in a run.

### Quick Start

```bash
# Process a single run
slop-code metrics static outputs/my_run

# Process a collection of runs
slop-code metrics static outputs/all_runs --type collection --workers 4
```

### Usage

```bash
slop-code metrics static [OPTIONS] RUN_DIR
```

### Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `RUN_DIR` | Yes | Path to run directory or collection directory |

### Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `-t, --type` | enum | `run` | Path type: `run` or `collection` |
| `-p, --problem-name` | string | - | Filter to a specific problem |
| `--just-static` | string | - | Scan directory as single snapshot with extension |
| `-w, --workers` | int | 4 | Number of parallel workers (collection mode) |

### Behavior

Calculates for each checkpoint:
- Lines of code (LOC), total lines
- Cyclomatic complexity (mean, max, high count)
- Maintainability index
- AST-grep "slop" violations
- Lint errors

Results saved to:
- `overall_quality.json` in each checkpoint
- `checkpoint_results.jsonl` at run level
- `result.json` summary

### Examples

```bash
# Single run
slop-code metrics static outputs/my_run

# Collection with parallel processing
slop-code metrics static outputs/runs --type collection --workers 8

# Scan arbitrary directory as snapshot
slop-code metrics static ./some_code --just-static py
```

---

## judge

Run LLM judge evaluation on a run directory.

### Quick Start

```bash
slop-code metrics judge outputs/my_run \
  --rubric configs/rubrics/slop.jsonl \
  --model claude-sonnet-4-20250514
```

### Usage

```bash
slop-code metrics judge [OPTIONS] RUN_DIR
```

### Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `RUN_DIR` | Yes | Path to the agent run directory |

### Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `-r, --rubric` | path | **required** | Path to rubric JSONL file |
| `-m, --model` | string | **required** | Model ID for grading |
| `--temperature` | float | 0.0 | Sampling temperature |
| `-k, --key` | string | `OPENROUTER_API_KEY` | Environment variable for API key |
| `--provider` | enum | `OPENROUTER` | LLM provider |
| `-p, --problem` | string | - | Filter to specific problems (repeatable) |
| `-t, --thinking-tokens` | int | - | Extended thinking token budget |
| `-e, --env-config` | path | `<run>/environment.yaml` | Environment config path |
| `--prefix-template` | path | - | Custom prefix template (Jinja2) |
| `--criteria-template` | path | - | Custom criteria template (Jinja2) |
| `-w, --overwrite` | flag | false | Re-grade existing checkpoints |
| `--max-items` | int | - | Max items per batch |
| `--max-batch-lines` | int | 1000 | Max lines per file batch |
| `--max-batch-files` | int | 5 | Max files per batch |
| `-c, --max-concurrency` | int | 30 | Max concurrent checkpoint evaluations |
| `--max-parallel-checkpoints` | int | - | Limit checkpoints launched at once |

### Provider Values

| Value | Description |
|-------|-------------|
| `OPENROUTER` | OpenRouter API (default) |
| `ANTHROPIC` | Anthropic API directly |

### Examples

```bash
# Basic judge evaluation
slop-code metrics judge outputs/my_run \
  -r configs/rubrics/slop.jsonl \
  -m claude-sonnet-4-20250514

# With Anthropic directly
slop-code metrics judge outputs/my_run \
  -r configs/rubrics/slop.jsonl \
  -m claude-sonnet-4-20250514 \
  --provider ANTHROPIC

# With extended thinking
slop-code metrics judge outputs/my_run \
  -r configs/rubrics/slop.jsonl \
  -m claude-sonnet-4-20250514 \
  --thinking-tokens 10000

# Filter to specific problems
slop-code metrics judge outputs/my_run \
  -r configs/rubrics/slop.jsonl \
  -m claude-sonnet-4-20250514 \
  -p file_backup -p trajectory_api
```

---

## carry-forward

Carry forward rubric grades from previous checkpoints.

### Quick Start

```bash
slop-code metrics carry-forward outputs/my_run
```

### Usage

```bash
slop-code metrics carry-forward [OPTIONS] RUN_DIR
```

### Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `RUN_DIR` | Yes | Path to the run directory |

### Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `-p, --problem` | string | - | Filter to a specific problem |

### Behavior

For each checkpoint N > 1:
1. Loads previous checkpoint's `rubric.jsonl` and `diff.json`
2. Identifies grades for unchanged code regions
3. Carries forward grades that weren't re-flagged
4. Augments current checkpoint's `rubric.jsonl`

### Output

Displays summary table showing:
- Original grade count per checkpoint
- Number of grades carried forward
- Final total grades

### Examples

```bash
# Process all problems
slop-code metrics carry-forward outputs/my_run

# Process specific problem
slop-code metrics carry-forward outputs/my_run -p file_backup
```

---

## variance

Compute variance metrics across multiple runs.

### Quick Start

```bash
slop-code metrics variance base outputs/runs -o outputs/variance
```

### Usage

```bash
slop-code metrics variance [OPTIONS] PRESET RUNS_DIR
```

### Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `PRESET` | Yes | Metric preset: `base`, `tests`, or `quality` |
| `RUNS_DIR` | Yes | Directory containing multiple run directories |

### Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `-o, --output-dir` | path | `outputs/variance` | Directory for output files |
| `--ci-width-threshold` | float | 0.25 | Minimum 95% CI width to display |
| `--top-n` | int | 12 | Max confidence interval rows to display |

### Presets

| Preset | Metrics Included |
|--------|------------------|
| `base` | Pass rate, cost, duration, LOC, lint, slop, CC |
| `tests` | Pass rates by test bucket (core, error, functionality) |
| `quality` | All quality metrics (slop, rubric, CC, branches, etc.) |

### Behavior

1. Discovers all runs in directory
2. Groups runs by model/prompt/thinking/agent configuration
3. Requires at least 2 runs per group
4. Computes statistics (mean, stddev, CV, 95% CI)
5. Writes JSONL reports

### Output Files

- `checkpoint_var.jsonl` - Per-checkpoint variance data
- `problem_var.jsonl` - Per-problem aggregated variance

### Examples

```bash
# Base metrics variance
slop-code metrics variance base outputs/runs

# Quality metrics with custom output
slop-code metrics variance quality outputs/runs -o outputs/quality_variance

# Show more results
slop-code metrics variance base outputs/runs --top-n 20 --ci-width-threshold 0.1
```

## See Also

- [eval](eval.md) - Run evaluation on agent results
- [utils backfill-reports](utils.md#backfill-reports) - Regenerate reports
