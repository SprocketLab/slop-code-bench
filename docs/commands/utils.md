---
version: 1.0
last_updated: 2025-12-17
---

# utils

Utility commands for maintenance and data processing.

## Subcommands

| Command | Description |
|---------|-------------|
| [`repopulate-diffs`](#repopulate-diffs) | Regenerate diff.json files |
| [`backfill-reports`](#backfill-reports) | Backfill checkpoint reports |
| [`backfill-categories`](#backfill-categories) | Backfill rubric categories |
| [`compress-artifacts`](#compress-artifacts) | Compress agent artifacts |
| [`combine-results`](#combine-results) | Combine results from multiple runs |
| [`inject-canary`](#inject-canary) | Inject canary strings |
| [`render-prompts`](#render-prompts) | Render prompt templates |

---

## repopulate-diffs

Regenerate `diff.json` files for checkpoint snapshots.

### Usage

```bash
slop-code utils repopulate-diffs [OPTIONS]
```

### Behavior

Scans run directories and regenerates diff files that track changes between checkpoints.

---

## backfill-reports

Generate checkpoint reports for all problems in a results directory.

### Quick Start

```bash
# Single run
slop-code utils backfill-reports outputs/my_run

# Collection of runs
slop-code utils backfill-reports outputs/all_runs --type collection
```

### Usage

```bash
slop-code utils backfill-reports [OPTIONS] RESULTS_DIR
```

### Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `RESULTS_DIR` | Yes | Path to results directory or collection |

### Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `-t, --type` | enum | `run` | Path type: `run` or `collection` |

### Behavior

1. Scans results directory for problem runs
2. Loads problem configuration for each
3. Generates report entries for each checkpoint
4. Updates `checkpoint_results.jsonl`
5. Backfills AST-grep category data
6. Generates `result.json` summary

### Examples

```bash
# Backfill single run
slop-code utils backfill-reports outputs/my_run

# Backfill all runs in collection
slop-code utils backfill-reports outputs/all_runs --type collection
```

---

## backfill-categories

Backfill category information into existing `rubric.jsonl` files.

### Usage

```bash
slop-code utils backfill-categories [OPTIONS]
```

### Behavior

Updates rubric files with category and subcategory metadata from rule definitions.

---

## compress-artifacts

Compress agent artifact directories into tar.gz files.

### Usage

```bash
slop-code utils compress-artifacts [OPTIONS]
```

### Behavior

Finds agent artifact directories and compresses them to save disk space while preserving data.

---

## combine-results

Combine `checkpoint_results.jsonl` from multiple runs into one JSONL file with run metadata.

### Quick Start

```bash
slop-code utils combine-results outputs/runs -o outputs/combined.jsonl
```

### Usage

```bash
slop-code utils combine-results [OPTIONS] RUNS_DIR
```

### Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `RUNS_DIR` | Yes | Path to run directory or parent of runs |

### Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `-o, --output` | path | `<RUNS_DIR>/combined_checkpoint_results.jsonl` | Output file path |
| `-w, --overwrite` | flag | false | Overwrite if output exists |

### Behavior

1. Discovers all run directories
2. Loads `checkpoint_results.jsonl` from each
3. Attaches run-level metadata to each record:
   - `run_name`, `run_dir`, `run_relative_path`
   - `model_name`, `model_provider`
   - `prompt_name`, `thinking_level`
   - `agent_type`, `agent_version`
   - `environment_name`, `environment_type`
4. Writes combined JSONL file

### Examples

```bash
# Combine with default output
slop-code utils combine-results outputs/runs

# Custom output location
slop-code utils combine-results outputs/runs -o analysis/all_results.jsonl

# Overwrite existing
slop-code utils combine-results outputs/runs -o outputs/combined.jsonl --overwrite
```

---

## inject-canary

Inject canary strings into problem files for training data detection.

### Usage

```bash
slop-code utils inject-canary [OPTIONS]
```

### Behavior

Injects unique identifiable strings into problem specifications to detect if they appear in model training data.

---

## render-prompts

Render prompt templates for problems to an output directory.

### Usage

```bash
slop-code utils render-prompts [OPTIONS]
```

### Behavior

Takes Jinja2 prompt templates and renders them with problem-specific variables, useful for reviewing what agents actually see.

## See Also

- [metrics](metrics.md) - Calculate metrics on submissions
- [eval](eval.md) - Evaluate agent results
