---
version: 2.0
last_updated: 2025-12-22
---

# Configuration Guide

This guide covers problem and checkpoint configuration for the pytest-based evaluation system.

## Overview

Configuration is defined in a single `config.yaml` at the problem root. The pytest runner uses:

- **ProblemConfig**: Entry file, static assets, custom markers, test dependencies
- **CheckpointConfig**: Timeout, environment variables, test inclusion settings

Test categorization is handled by pytest markers, not configuration.

## Problem Configuration

### Basic Structure

```yaml
# problems/{problem}/config.yaml
name: file_backup
version: 1
description: "Implement an incremental file backup system"
tags: ["file-system", "cli"]
entry_file: main.py

checkpoints:
  checkpoint_1:
    version: 1
    order: 1
    timeout: 30
  checkpoint_2:
    version: 1
    order: 2
    timeout: 60
```

### ProblemConfig Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Human-friendly problem name |
| `version` | int | Yes | Version number (increment when tests change) |
| `description` | string | Yes | Short problem summary |
| `tags` | list[string] | Yes | Categorization tags (min 1) |
| `entry_file` | string | Yes | Entry point for running submission (e.g., "main.py") |
| `author` | string | No | Problem author |
| `category` | string | No | Problem category |
| `difficulty` | string | No | "Easy", "Medium", or "Hard" |
| `static_assets` | dict | No | Named assets for tests |
| `markers` | dict | No | Custom pytest markers |
| `test_dependencies` | list | No | Additional packages for tests |
| `checkpoints` | dict | Yes | Checkpoint configurations |

### Static Assets

Static assets are files made available to tests during execution:

```yaml
static_assets:
  sample_data:
    path: ./assets/sample.json
  large_file:
    path: ./assets/large_input.txt
```

Assets are materialized to `tests/assets/` in the workspace and accessible via:
- Environment variable: `SCBENCH_ASSET_{NAME}` (e.g., `SCBENCH_ASSET_SAMPLE_DATA`)
- Environment variable: `SCBENCH_ASSETS_DIR` (directory containing all assets)

### Custom Markers

Define custom pytest markers beyond the built-ins (error, functionality, regression):

```yaml
markers:
  performance:
    description: "Performance and load tests"
    group: Functionality
  integration:
    description: "Integration tests with external services"
    group: Core
```

**MarkerConfig Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `description` | string | Marker description for pytest.ini |
| `group` | string | GroupType mapping: "Core", "Functionality", "Error", "Regression" |

### Test Dependencies

Additional packages needed by tests (beyond the standard set):

```yaml
test_dependencies:
  - "requests>=2.28"
  - "httpx"
  - "pyyaml"
```

These are installed via `uvx --with=...` during test execution.

**Standard dependencies** (always available):
- pytest
- pytest-json-ctrf
- pytest-json-report
- pytest-timeout
- jsonschema
- deepdiff

## Checkpoint Configuration

### Basic Structure

```yaml
checkpoints:
  checkpoint_1:
    version: 1
    order: 1
    timeout: 30
    env:
      DEBUG: "true"
    include_prior_tests: true
```

### CheckpointConfig Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `version` | int | Required | Version number (increment when tests change) |
| `order` | int | Auto | Ordering index (1-indexed, auto-increments) |
| `timeout` | float | None | Session-level pytest timeout in seconds |
| `env` | dict | {} | Environment variables for test execution |
| `include_prior_tests` | bool | true | Whether to run tests from prior checkpoints |
| `state` | string | "Draft" | Development state: "Draft", "Core Tests", "Full Tests", "Verified" |

### Environment Variables

Environment variables are merged from problem and checkpoint levels:

```yaml
# Problem level (inherited by all checkpoints)
env:
  PYTHONPATH: "."
  LOG_LEVEL: "INFO"

checkpoints:
  checkpoint_1:
    env:
      DEBUG: "true"  # Adds to problem-level env
```

### Test Inclusion

The `include_prior_tests` setting controls which test files are copied to the workspace:

```yaml
checkpoints:
  checkpoint_1:
    include_prior_tests: true   # Default: runs test_checkpoint_1.py
  checkpoint_2:
    include_prior_tests: true   # Runs test_checkpoint_1.py AND test_checkpoint_2.py
  checkpoint_3:
    include_prior_tests: false  # Only runs test_checkpoint_3.py
```

When `include_prior_tests: true`:
- Test files for checkpoints 0..N are copied
- Tests from prior checkpoints become REGRESSION type automatically
- Ensures solutions don't break earlier functionality

When `include_prior_tests: false`:
- Only the current checkpoint's test file is copied
- Useful for independent checkpoints

## Configuration Inheritance

Child scopes inherit from parent scopes:

```
ProblemConfig
├── env: {"PYTHONPATH": "."}
├── timeout: 60
│
└── CheckpointConfig (inherits env, timeout)
    ├── env: {"DEBUG": "true"}  # Merged: {"PYTHONPATH": ".", "DEBUG": "true"}
    └── timeout: 30             # Overrides problem timeout
```

## Complete Example

```yaml
# problems/file_backup/config.yaml
name: file_backup
version: 2
description: "Build an incremental file backup system with change detection"
tags: ["file-system", "cli", "hashing"]
author: "SCBench Team"
category: "File Processing"
difficulty: "Medium"
entry_file: main.py

env:
  PYTHONPATH: "."

static_assets:
  test_files:
    path: ./tests/assets/files

markers:
  hidden:
    description: "Hidden test cases not shown to agent"
    group: Functionality

test_dependencies:
  - "pyyaml>=6.0"

checkpoints:
  checkpoint_1:
    version: 1
    order: 1
    state: "Full Tests"
    timeout: 30
    env:
      LOG_LEVEL: "DEBUG"

  checkpoint_2:
    version: 1
    order: 2
    state: "Full Tests"
    timeout: 45
    include_prior_tests: true

  checkpoint_3:
    version: 1
    order: 3
    state: "Core Tests"
    timeout: 60

  checkpoint_4:
    version: 1
    order: 4
    state: "Draft"
    timeout: 90
```

## Environment Configuration (Runtime Parameter)

Environment configuration is **NOT** part of ProblemConfig. It is specified at execution time:

```bash
slop-code run \
  --agent configs/agents/claude_code/config.yaml \
  --environment configs/environments/docker-python3.12-uv.yaml \
  --problem file_backup
```

Environment specs live in `configs/environments/` and define Docker/local execution settings.

### Environment Structure

```yaml
# configs/environments/docker-python3.12-uv.yaml
type: docker
name: python3.12
docker:
  image: ghcr.io/astral-sh/uv:python3.12-trixie-slim
  workdir: /workspace
  mount_workspace: true

environment:
  env:
    UV_CACHE_DIR: /tmp/uv-cache
  include_os_env: false

setup:
  commands:
    - apt-get update
  eval_commands:
    - uv init

commands:
  entry_file: "{entry_file}.py"
  command: uv run
  agent_command: python
```

## Validation

Configuration is validated using Pydantic models:

- Required fields must be present
- Types are enforced (string, int, list, dict)
- Enum values are validated (GroupType, difficulty, state)
- Custom markers must specify valid GroupType

Invalid configurations raise `ConfigError` with descriptive messages.

## Loading Configuration

```python
from slop_code.evaluation import ProblemConfig

# Load from directory
problem = ProblemConfig.from_yaml(Path("problems/file_backup"))

# Access problem fields
print(problem.name)           # "file_backup"
print(problem.entry_file)     # "main.py"
print(problem.markers)        # {"hidden": MarkerConfig(...)}

# Access checkpoints
for name, checkpoint in problem.iterate_checkpoint_items():
    print(f"{name}: timeout={checkpoint.timeout}")

# Get specific checkpoint
cp1 = problem.checkpoints["checkpoint_1"]
print(cp1.timeout)            # 30
print(cp1.include_prior_tests)  # True
```

## Next Steps

- **Understand architecture**: [Architecture Guide](architecture.md)
- **Interpret results**: [Reporting Guide](reporting.md)
- **Debug failures**: [Troubleshooting Guide](troubleshooting.md)
