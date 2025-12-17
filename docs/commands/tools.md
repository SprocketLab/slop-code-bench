---
version: 1.0
last_updated: 2025-12-17
---

# tools

Interactive tools and case runners.

## Subcommands

| Command | Description |
|---------|-------------|
| [`run-case`](#run-case) | Run test cases and output JSON |
| [`snapshot-eval`](#snapshot-eval) | Launch Snapshot Evaluator UI |
| [`report-viewer`](#report-viewer) | Launch Report Viewer UI |

---

## run-case

Run a single test case (or filtered subset) and output JSON results.

### Quick Start

```bash
slop-code tools run-case \
  -s outputs/my_run/file_backup/checkpoint_1/snapshot \
  -p file_backup \
  -c 1 \
  -e configs/environments/docker-python3.12-uv.yaml
```

### Usage

```bash
slop-code tools run-case [OPTIONS]
```

### Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `-s, --snapshot-dir` | path | **required** | Path to snapshot directory |
| `-p, --problem` | string | **required** | Name of the problem |
| `-c, --checkpoint` | int | **required** | Checkpoint number |
| `-e, --env-config` | path | **required** | Path to environment configuration |
| `-g, --group` | string | - | Filter by group name (glob patterns) |
| `--case` | string | - | Filter by case name (glob patterns) |
| `--full` | flag | false | Enable full debug output |

### Output

**Default output** (per case):
```json
{
  "id": "case_001",
  "group": "core",
  "score": 1.0,
  "passed": true,
  "results": {
    "stdout": {"actual": "...", "expected": "...", "is_correct": true}
  }
}
```

**Full output** (`--full`): Complete report with all attributes and debug info.

### Examples

```bash
# Run all cases
slop-code tools run-case \
  -s outputs/snapshot \
  -p file_backup \
  -c 1 \
  -e configs/environments/docker-python3.12-uv.yaml

# Filter to core group
slop-code tools run-case \
  -s outputs/snapshot \
  -p file_backup \
  -c 1 \
  -e configs/environments/docker-python3.12-uv.yaml \
  -g core

# Run specific case
slop-code tools run-case \
  -s outputs/snapshot \
  -p file_backup \
  -c 1 \
  -e configs/environments/docker-python3.12-uv.yaml \
  --case "test_*"

# Full debug output
slop-code tools run-case \
  -s outputs/snapshot \
  -p file_backup \
  -c 1 \
  -e configs/environments/docker-python3.12-uv.yaml \
  --full
```

---

## snapshot-eval

Launch the Snapshot Evaluator Streamlit application.

### Usage

```bash
slop-code tools snapshot-eval
```

### Behavior

Opens an interactive web UI for:
- Selecting problem and checkpoint
- Browsing snapshot code
- Running evaluations
- Viewing detailed results

---

## report-viewer

Launch the Verifier Report Viewer Streamlit application.

### Usage

```bash
slop-code tools report-viewer DIRECTORY
```

### Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `DIRECTORY` | Yes | Path to run directory or snapshots directory |

### Behavior

Opens an interactive web UI for:
- Browsing evaluation reports
- Viewing case-by-case results
- Comparing expected vs actual outputs
- Analyzing failure patterns

### Examples

```bash
# View reports for a run
slop-code tools report-viewer outputs/my_run

# View specific problem's reports
slop-code tools report-viewer outputs/my_run/file_backup
```

## See Also

- [eval-snapshot](eval-snapshot.md) - CLI snapshot evaluation
- [eval](eval.md) - Full run evaluation
