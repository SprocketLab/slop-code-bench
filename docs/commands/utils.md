---
version: 1.0
last_updated: 2025-12-26
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
| [`migrate-eval-format`](#migrate-eval-format) | Migrate evaluation.json format |
| [`make-registry`](#make-registry) | Generate problem registry JSONL |

---

## repopulate-diffs

Regenerate `diff.json` files for checkpoint snapshots.

### Usage

```bash
slop-code utils repopulate-diffs [OPTIONS] RUN_DIR
```

### Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `RUN_DIR` | Yes | Path to the run directory |

### Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `-p, --problem-name` | string | - | Filter to a specific problem name |

### Behavior

For each checkpoint, generates a diff comparing to the previous checkpoint's
snapshot directory. The first checkpoint is compared against an empty snapshot
(all files marked as created).

### Output

Displays a summary table with:
- Problem name
- Checkpoint name
- Files created/modified/deleted
- Lines added/removed

### Examples

```bash
# Regenerate diffs for all problems in a run
slop-code utils repopulate-diffs outputs/my_run

# Regenerate diffs for a specific problem
slop-code utils repopulate-diffs outputs/my_run -p file_backup
```

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
slop-code utils backfill-categories [OPTIONS] RESULTS_DIR
```

### Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `RESULTS_DIR` | Yes | Path to run directory or collection directory |

### Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `-r, --rubric` | path | **required** | Path to rubric JSONL file with category definitions |
| `-t, --type` | enum | `run` | Path type: `run` or `collection` |

### Behavior

Reads rubric definitions from the specified JSONL file and adds the `category`
field to each grade in `rubric.jsonl` files based on matching the `criteria`
field to the rubric item `name`. Grades that already have a `category` field
are not modified.

### Examples

```bash
# Backfill categories for a single run
slop-code utils backfill-categories \
  --rubric configs/rubrics/llm_judge.jsonl \
  outputs/my_run

# Backfill categories for a collection of runs
slop-code utils backfill-categories \
  --rubric configs/rubrics/llm_judge.jsonl \
  --type collection \
  outputs/
```

---

## compress-artifacts

Compress agent artifact directories into tar.gz files.

### Usage

```bash
slop-code utils compress-artifacts [OPTIONS] RESULTS_DIR
```

### Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `RESULTS_DIR` | Yes | Path to results directory or collection directory |

### Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `-t, --type` | enum | `run` | Path type: `run` or `collection` |
| `-n, --dry-run` | flag | false | Show what would be compressed without doing it |

### Behavior

Finds all uncompressed agent directories (named `agent`) within checkpoint
directories, compresses them into `agent.tar.gz`, and removes the original
directories.

### Examples

```bash
# Compress artifacts in a single run
slop-code utils compress-artifacts outputs/my_run

# Compress artifacts across all runs in a collection
slop-code utils compress-artifacts outputs --type collection

# Preview what would be compressed
slop-code utils compress-artifacts outputs/my_run --dry-run
```

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
slop-code utils inject-canary [OPTIONS] CANARY GUID
```

### Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `CANARY` | Yes | The canary string to inject |
| `GUID` | Yes | Unique identifier for this canary |

### Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `-n, --dry-run` | flag | false | Preview changes without modifying files |
| `-p, --problem` | string | - | Specific problem name(s) to process (repeatable) |

### Behavior

Injects tracking canary strings into eligible files within the problems
directory. Useful for detecting if problem content appears in training data.

**File types and injection format:**
- Python (`.py`): Triple-quoted docstring after `__future__` imports
- YAML (`.yaml`): Comment as first line
- Markdown (`.md`): HTML comment as first line
- Shell (`.sh`): Comment after shebang
- `requirements.txt`: Comment as first line

**Exclusions:**
- Test case directories (`core/`, `hidden/`, `error/`, etc.)
- Data files (`case.yaml`, `expected.yaml`, `META.yaml`)
- Static asset directories

### Examples

```bash
# Preview what would be modified
slop-code utils inject-canary "CANARY_STRING_123" "abc-123-guid" --dry-run

# Inject canary into all problems
slop-code utils inject-canary "CANARY_STRING_123" "abc-123-guid"

# Inject into specific problems only
slop-code utils inject-canary "CANARY_STRING_123" "abc-123-guid" -p file_backup -p etl_pipeline
```

---

## render-prompts

Render prompt templates for problems to an output directory.

### Usage

```bash
slop-code utils render-prompts [OPTIONS]
```

### Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `-p, --prompt` | string | **required** | Prompt template name or path |
| `-e, --environment` | string | **required** | Environment config name or path |
| `-o, --output-dir` | path | **required** | Output directory for rendered prompts |
| `--problem` | string | - | Problem name(s) to render (repeatable) |

### Behavior

For each problem, iterates through all checkpoints and renders the prompt
template with the checkpoint's spec text and appropriate context.

**Output structure:**
```
output_dir/
    problem_name/
        part_1.md
        part_2.md
        ...
```

### Examples

```bash
# Render prompts for all problems
slop-code utils render-prompts \
  -p just-solve \
  -e docker-python3.12-uv \
  -o outputs/rendered_prompts

# Render for specific problems
slop-code utils render-prompts \
  -p just-solve \
  -e docker-python3.12-uv \
  -o outputs/rendered_prompts \
  --problem file_backup \
  --problem etl_pipeline
```

---

## migrate-eval-format

Migrate `evaluation.json` files from the old list-based tests format to the new grouped format.

### Usage

```bash
slop-code utils migrate-eval-format [OPTIONS] RESULTS_DIR
```

### Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `RESULTS_DIR` | Yes | Path to results directory or collection directory |

### Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `-t, --type` | enum | `run` | Path type: `run` for single run, `collection` for multiple runs |
| `-n, --dry-run` | flag | false | Show what would be migrated without making changes |

### Behavior

Converts the old tests format (list of test objects) to the new grouped format (dict with checkpoint-GroupType keys):

**Old format:**
```json
"tests": [
  {"id": "test_foo", "checkpoint": "checkpoint_1", "group_type": "Core", "status": "passed"},
  {"id": "test_bar", "checkpoint": "checkpoint_1", "group_type": "Core", "status": "failed"}
]
```

**New format:**
```json
"tests": {
  "checkpoint_1-Core": {
    "passed": ["test_foo"],
    "failed": ["test_bar"]
  }
}
```

When run on a collection, processes all discovered run directories in sequence.

### Output

Displays a summary table with:
- Number of files found
- Number of files migrated
- Number of files already migrated
- Number of failed migrations

### Examples

```bash
# Migrate a single run directory
slop-code utils migrate-eval-format outputs/my_run

# Preview migration on a collection (dry run)
slop-code utils migrate-eval-format --type collection --dry-run outputs/

# Migrate all runs in a collection
slop-code utils migrate-eval-format --type collection outputs/
```

---

## make-registry

Generate a registry JSONL file containing metadata for all problems. This is used by the slopcodebench.github.io website.

### Usage

```bash
slop-code utils make-registry [OPTIONS]
```

### Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `-o, --output` | path | **required** | Output JSONL file path |
| `--problem` | string | - | Problem name(s) to include (repeatable) |

### Behavior

Scans the problems directory and generates a registry entry for each problem. Each line in the output file is a complete JSON object containing:
- Problem name, tags, version, author, category
- Difficulty, description, entry point
- List of all checkpoints with their specs

When `--problem` is specified, only those problems are included in the registry. Useful for testing specific problems before full registry generation.

### Output Format

Each line is a JSON object with structure:
```json
{
  "problem_name": "file_backup",
  "tags": ["filesystem", "backup"],
  "version": 1,
  "author": "author_name",
  "category": "category_name",
  "entry_point": "main.py",
  "adapter_type": "cli",
  "difficulty": "medium",
  "description": "Problem description",
  "checkpoints": [
    {
      "checkpoint_name": "checkpoint_1",
      "spec": "Full spec text...",
      "version": 1,
      "state": "Core Tests"
    }
  ]
}
```

### Examples

```bash
# Generate registry for all problems
slop-code utils make-registry -o registry.jsonl

# Generate registry for specific problems only
slop-code utils make-registry -o registry.jsonl --problem file_backup --problem code_search

# Generate to custom location
slop-code utils make-registry --output /path/to/registry.jsonl
```

## See Also

- [metrics](metrics.md) - Calculate metrics on submissions
- [eval](eval.md) - Evaluate agent results
