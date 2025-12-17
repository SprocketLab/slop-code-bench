---
version: 1.0
last_updated: 2025-12-17
---

# problems

Commands for inspecting problems and checkpoints.

## Subcommands

| Command | Description |
|---------|-------------|
| [`ls`](#ls) | List all problems |
| [`chkpt`](#chkpt) | Show checkpoint details |
| [`make-registry`](#make-registry) | Generate problem registry |

---

## ls

List all problems with their metadata.

### Usage

```bash
slop-code problems ls [OPTIONS]
```

### Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--include-draft` | flag | false | Include problems with only draft checkpoints |

### Output

Displays a table with:
- Problem name
- Version
- Adapter type
- Category
- Checkpoint count

### Examples

```bash
# List all non-draft problems
slop-code problems ls

# Include draft problems
slop-code problems ls --include-draft
```

---

## chkpt

List groups, cases, and types for a checkpoint of a problem.

### Usage

```bash
slop-code problems chkpt [OPTIONS] PROBLEM_NAME CHECKPOINT_NUM
```

### Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `PROBLEM_NAME` | Yes | Name of the problem |
| `CHECKPOINT_NUM` | Yes | Checkpoint number (1-based) |

### Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--jsonl` | flag | false | Output in JSONL format |
| `--regressions` | flag | false | Show regression information |

### Output

Displays information about all groups:
- Group name
- Group type (Core, Hidden, Regression, etc.)
- Number of test cases

With `--regressions`, also shows:
- Original checkpoint
- Original group

### Examples

```bash
# Show checkpoint 1 details
slop-code problems chkpt file_backup 1

# JSON output for scripting
slop-code problems chkpt file_backup 1 --jsonl

# Show regression info
slop-code problems chkpt file_backup 3 --regressions
```

---

## make-registry

Generate a `registry.jsonl` file describing all non-draft problems.

### Usage

```bash
slop-code problems make-registry [OPTIONS]
```

### Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `-o, --output` | path | `problems/registry.jsonl` | Output path |

### Output Format

Each line is a JSON object containing:

```json
{
  "problem_name": "file_backup",
  "tags": ["filesystem", "backup"],
  "version": "1.0",
  "author": "...",
  "category": "cli",
  "entry_point": "backup.py",
  "adapter_type": "cli",
  "difficulty": "medium",
  "description": "...",
  "checkpoints": [
    {
      "checkpoint_name": "checkpoint_1",
      "spec": "...",
      "version": "1.0",
      "state": "Ready",
      "tests_by_type": {
        "Core": 5,
        "Hidden": 3
      }
    }
  ]
}
```

### Examples

```bash
# Generate default registry
slop-code problems make-registry

# Custom output path
slop-code problems make-registry -o outputs/problem_registry.jsonl
```

## See Also

- [Problem Authoring Guide](../guides/problem-authoring.md)
- [Problem Configuration](../problems/config-schema.md)
- [Checkpoints](../problems/checkpoints.md)
