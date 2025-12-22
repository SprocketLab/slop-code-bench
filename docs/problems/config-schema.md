# Configuration Schema Reference

Complete field-by-field reference for problem configuration files.

## Problem Configuration (`config.yaml`)

Located at: `problems/<problem_name>/config.yaml`

### Required Fields

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `name` | string | Unique problem identifier (must match directory name) | `file_backup` |
| `entry_file` | string | Entry point file name | `main.py` |
| `checkpoints` | object | Checkpoint definitions (see below) | `{checkpoint_1: ...}` |

### Optional Fields

| Field | Type | Default | Description | Example |
|-------|------|---------|-------------|---------|
| `version` | integer | `1` | Problem schema version | `1` |
| `description` | string | `""` | Human-readable description | `"CLI backup scheduler"` |
| `category` | string | `null` | Problem category | `data-processing` |
| `difficulty` | string | `null` | Difficulty level | `Easy`, `Medium`, `Hard` |
| `author` | string | `null` | Problem author | `"Jane Doe"` |
| `timeout` | integer | `30` | Default timeout in seconds | `60` |
| `tags` | array | `[]` | Searchable tags | `[cli, json, parsing]` |
| `static_assets` | object | `{}` | Static file mappings | See below |
| `test_dependencies` | array | `[]` | Additional pytest packages | `[pyyaml, requests]` |
| `markers` | object | `{}` | Custom pytest markers | See below |

### Checkpoint Configuration

Each checkpoint is defined under `checkpoints`:

```yaml
checkpoints:
  checkpoint_1:
    version: 1                    # Required: Increment when tests change
    order: 1                      # Required: Execution order (1-based)
    state: Core Tests             # Optional: Development state

  checkpoint_2:
    version: 1
    order: 2
    state: Core Tests
    timeout: 60                   # Optional: Override default timeout
    include_prior_tests: true     # Optional: Run prior checkpoint tests
```

#### Checkpoint Fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `version` | integer | Yes | - | Test version (increment on changes) |
| `order` | integer | Yes | - | Execution order (1-based) |
| `state` | string | No | `null` | Development state label |
| `timeout` | integer | No | From problem | Timeout for all tests |
| `include_prior_tests` | boolean | No | `true` | Include prior checkpoint tests |

### Static Assets

Maps directories from problem root to be available during tests.

```yaml
static_assets:
  files:
    path: static_assets/files     # Mount problems/my_problem/static_assets/files
  reference_db:
    path: data/reference.db       # Mount a specific file
```

Static assets are accessible via environment variables:
- `SCBENCH_ASSETS_DIR`: Path to assets directory
- `SCBENCH_ASSET_{NAME}`: Path to specific asset

### Test Dependencies

Additional packages installed for pytest execution:

```yaml
test_dependencies:
  - pyyaml        # For YAML parsing in tests
  - requests      # For HTTP requests in tests
  - deepdiff      # For flexible comparisons
```

Default packages always available:
- `pytest`
- `pytest-json-ctrf`
- `pytest-json-report`
- `pytest-timeout`
- `jsonschema`
- `deepdiff`

### Custom Markers

Define custom pytest markers with GroupType mapping:

```yaml
markers:
  slow:
    description: slow-running tests
    group: FUNCTIONALITY

  integration:
    description: integration tests
    group: FUNCTIONALITY

  critical:
    description: critical path tests
    group: CORE
```

#### Marker Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `description` | string | Yes | Marker description for pytest |
| `group` | string | Yes | GroupType: `CORE`, `FUNCTIONALITY`, `ERROR`, `REGRESSION` |

## Complete Example

### Minimal Configuration

```yaml
version: 1
name: hello_world
entry_file: hello.py
timeout: 10

checkpoints:
  checkpoint_1:
    version: 1
    order: 1
    state: Core Tests
```

### Full Configuration

```yaml
version: 1
name: etl_pipeline
description: |
  CLI tool for ETL (Extract, Transform, Load) data pipelines.
  Supports JSON, CSV, and YAML formats.

category: data-processing
difficulty: Medium
author: Jane Doe
entry_file: etl.py
timeout: 30

tags:
  - cli
  - etl
  - json
  - csv
  - data-transformation

static_assets:
  sample_data:
    path: data/samples
  schemas:
    path: data/schemas

test_dependencies:
  - pyyaml
  - pandas

markers:
  slow:
    description: slow tests (>10s)
    group: FUNCTIONALITY
  integration:
    description: integration tests
    group: FUNCTIONALITY

checkpoints:
  checkpoint_1:
    version: 1
    order: 1
    state: Core Tests

  checkpoint_2:
    version: 2
    order: 2
    state: Core Tests
    timeout: 60
    include_prior_tests: true

  checkpoint_3:
    version: 1
    order: 3
    state: Full Tests
    timeout: 120
    include_prior_tests: true
```

## Checkpoint States

| State | Description |
|-------|-------------|
| `Draft` | Work in progress, tests incomplete |
| `Core Tests` | Core tests written and passing |
| `Full Tests` | All tests written (core, functionality, error) |
| `Verified` | Tests validated with reference solution |

## GroupType Reference

| GroupType | Marker | Purpose |
|-----------|--------|---------|
| `CORE` | *(none)* | Essential functionality - must pass |
| `FUNCTIONALITY` | `@pytest.mark.functionality` | Advanced features - nice to have |
| `ERROR` | `@pytest.mark.error` | Error handling - edge cases |
| `REGRESSION` | `@pytest.mark.regression` | Prior checkpoint tests |

## Validation Rules

### Problem Name
- Must match directory name exactly
- Use `snake_case`
- No spaces or special characters (except underscore)

### Entry File
- Must include file extension (`.py`)
- Agents create this file

### Checkpoint Names
- Must follow pattern: `checkpoint_N` (N = 1, 2, 3, ...)
- Order must be unique and sequential

### Timeouts
- Measured in seconds
- Must be positive integers
- Applied per test, not total

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| `name` doesn't match directory | Ensure exact match |
| Missing `entry_file` extension | Add `.py` suffix |
| Duplicate `order` values | Make orders unique |
| Invalid `group` in markers | Use: CORE, FUNCTIONALITY, ERROR, REGRESSION |
| Missing `version` in checkpoint | Add `version: 1` |

## Next Steps

- [Quick Reference](quick-reference.md) - Templates and commands
- [Structure Guide](structure.md) - Directory layout
- [Markers](pytest/markers.md) - Test categorization
- [Runner Internals](pytest/runner-internals.md) - How tests execute
