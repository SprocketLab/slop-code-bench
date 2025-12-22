---
version: 1.0
last_updated: 2025-12-22
---

# tools

Test case runner for debugging and development.

## Subcommands

| Command | Description |
|---------|-------------|
| [`run-case`](#run-case) | Run test cases and output pytest stdout |

---

## run-case

Run pytest tests for a snapshot and output raw stdout.

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
| `--case` | string | - | Pytest -k expression to select tests |
| `--pytest-arg` | string | - | Extra args to pass to pytest (repeatable) |
| `--json` | flag | false | Output JSON report instead of raw pytest stdout |
| `--full` | flag | false | Include full JSON report payload (implies `--json`) |

### Output

**Default output**: Raw pytest stdout.

**JSON output** (`--json`): Per-test JSON summaries.

**Full JSON output** (`--full`): Complete report with all attributes and debug
info.

### Examples

```bash
# Run all tests
slop-code tools run-case \
  -s outputs/snapshot \
  -p file_backup \
  -c 1 \
  -e configs/environments/docker-python3.12-uv.yaml

# Run specific tests with -k filter
slop-code tools run-case \
  -s outputs/snapshot \
  -p file_backup \
  -c 1 \
  -e configs/environments/docker-python3.12-uv.yaml \
  --case "test_backup"

# JSON output
slop-code tools run-case \
  -s outputs/snapshot \
  -p file_backup \
  -c 1 \
  -e configs/environments/docker-python3.12-uv.yaml \
  --json

# Full JSON output with debug info
slop-code tools run-case \
  -s outputs/snapshot \
  -p file_backup \
  -c 1 \
  -e configs/environments/docker-python3.12-uv.yaml \
  --full

# Pass extra pytest args
slop-code tools run-case \
  -s outputs/snapshot \
  -p file_backup \
  -c 1 \
  -e configs/environments/docker-python3.12-uv.yaml \
  --pytest-arg "-v" \
  --pytest-arg "--tb=short"
```

## See Also

- [eval-snapshot](eval-snapshot.md) - CLI snapshot evaluation
- [eval](eval.md) - Full run evaluation
