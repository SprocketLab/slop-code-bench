---
version: 1.4
last_updated: 2025-12-10
---

# Configuration Guide

This guide covers all configuration options for problems, checkpoints, and groups in the evaluation system.

## Configuration Hierarchy

The evaluation system uses three levels of configuration:

```
ProblemConfig (config.yaml in problem root)
└── CheckpointConfig (config.yaml in checkpoint directories)
    └── GroupConfig (embedded in checkpoint config)
```

Child configurations inherit from parent configurations, with specific values overriding general ones.

## ProblemConfig

Top-level configuration defining the benchmark and its global settings.

### Location
`<problem_directory>/config.yaml`

### Full Example

```yaml
# Required fields
name: my_benchmark
version: 1  # Integer, not string
description: A comprehensive benchmark for testing agent capabilities

# Required: Entry file for submissions
entry_file: "main.py"

# Required: Adapter configuration (CLI, API, or Playwright)
adapter:
  type: cli  # or "api" or "playwright"

# Required: Checkpoints configuration (dict of checkpoint names to configs)
checkpoints:
  checkpoint_1: {}  # Inline config or loaded from checkpoint_1/config.yaml
  checkpoint_2: {}

# Optional: Loader configuration
loader_script: "loader.py"  # Default: "loader.py"
loader_entrypoint: "Loader"  # Default: "Loader"

# Optional: Static assets to mount into execution environment
static_assets:
  training_data:
    path: data/training_data.csv
    save_path: training_data.csv
  settings:
    path: config/settings.json
    save_path: settings.json

# Optional: Problem metadata
category: "algorithms"  # Default: "NOT_SET"
difficulty: "Medium"  # "Easy", "Medium", or "Hard"
tags:
  - algorithms
  - data-structures

# Optional: Design documentation
design_doc: "design_doc.md"  # Default: "design_doc.md"

# Optional: Author
author: "Your Name"
```

### Field Reference

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `name` | string | Yes | - | Human-friendly benchmark name |
| `version` | int | Yes | - | Version number of the problem tests (integer) |
| `description` | string | Yes | - | Short description of the problem |
| `entry_file` | string | Yes | - | Entry file for submission execution |
| `path` | Path | Yes | - | Path to the problem directory (set automatically) |
| `adapter` | AdapterConfigType | Yes | - | Adapter configuration (CLI, API, or Playwright) |
| `checkpoints` | dict[str, CheckpointConfig] | Yes | - | Mapping of checkpoint names to configurations |
| `tags` | list[str] | Yes | - | Tags to categorize or filter (minimum 1 tag required) |
| `loader_script` | string | No | "loader.py" | Script file to load cases |
| `loader_entrypoint` | string | No | "Loader" | Entrypoint class name in loader script |
| `static_assets` | dict[str, StaticAssetConfig] | No | {} | Named static assets referenced by cases |
| `category` | string | No | "NOT_SET" | Category of the problem |
| `difficulty` | Literal["Easy", "Medium", "Hard"] | No | "Easy" | Difficulty level |
| `author` | string | No | None | Author of the problem |
| `design_doc` | string | No | "design_doc.md" | Filename of design document |

**Note:** Environment configuration is NOT part of ProblemConfig. It is specified separately at execution time. See the [Environment Configuration](#environment-configuration-runtime-parameter) section below.

## CheckpointConfig

Checkpoint-level configuration for test execution and verification.

### Location
`<problem_directory>/<checkpoint_directory>/config.yaml`

### Full Example

```yaml
# Required fields
version: 1
order: 1                    # Set automatically when loading
path: /path/to/checkpoint_1  # Set automatically when loading

# Group definitions (required)
groups:
  basic_tests:
    name: basic_tests
    type: Functionality     # Group type: Error, Functionality, Regression, Core
    timeout: 60             # Optional: group-specific timeout
    case_defaults: {}       # Default values for cases

  edge_cases:
    name: edge_cases
    type: Functionality
    timeout: 120            # Optional: group-specific timeout

# Optional: Files available to all groups
constant_files: []          # Files made available to every case

# Optional: Checkpoint specification document
specification: spec.md      # Default: "spec.md"

# Optional: Checkpoint state
state: Draft                # Draft, Core Tests, Full Tests, Verified

# Optional: Regression tests from prior checkpoints
regressions:
  - checkpoint: checkpoint_1  # Import from prior checkpoint
    groups: [basic_tests]     # Only these groups
```

### Field Reference

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `version` | int | Yes | - | Version number for checkpoint tests |
| `order` | int | Yes | - | Ordering index (set automatically when loading) |
| `path` | Path | Yes | - | Filesystem path to the checkpoint directory |
| `groups` | dict[str, GroupConfig] | Yes | - | Dict mapping group name to group configuration |
| `constant_files` | set[str] | No | set() | Files available to every case across all groups |
| `specification` | string | No | "spec.md" | Filename of checkpoint spec |
| `state` | Literal["Draft", "Core Tests", "Full Tests", "Verified"] | No | "Draft" | Checkpoint state |
| `regressions` | list[RegressionSpec] | No | [] | Import groups from prior checkpoints |

**Inherited from ProblemConfig:**

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `env` | dict[str, str] | No | {} | Environment variables (can override) |
| `timeout` | float | No | None | Timeout in seconds (can override) |

**Note:** The `adapter` field is NOT on CheckpointConfig. It's defined at the problem level (in ProblemConfig) and inherited by all checkpoints. See [Adapters Guide](adapters.md) for adapter-specific configuration options.

## GroupConfig

Group-level configuration embedded in checkpoint config.

### Basic Group

```yaml
groups:
  my_group:
    name: my_group
    type: Functionality     # Group type
    description: Test group description
```

### Group with Custom Loader

```yaml
groups:
  generated_tests:
    name: generated_tests
    type: Functionality
    description: Programmatically generated tests
    loader:
      type: custom
      script: custom_loader.py
```

### Group with Timeout Override

```yaml
groups:
  slow_tests:
    name: slow_tests
    type: Core
    description: Tests that need more time
    timeout: 300  # 5 minutes
```

### IMPORTANT: Default Isolation Behavior

**By default, `isolated: true`**, meaning:
- Workspace is reset before EACH case in the group
- Cases cannot see filesystem changes from previous cases
- This is the SAFE default preventing test interdependence

**To enable stateful tests** (cases building on each other):
- MUST explicitly set `isolated: false`
- Only do this when test design requires it
- Document the stateful dependency clearly

### Isolated Group (Default Behavior)

```yaml
groups:
  # DEFAULT BEHAVIOR: isolated=true (workspace reset before each case)
  default_isolated_tests:
    name: default_tests
    type: Core
    description: Each test starts with clean workspace (default behavior)
    # isolated: true is implicit - can omit
```

### Stateful Group (Must Opt-Out)

```yaml
groups:
  # STATEFUL TESTS: Must explicitly opt-out
  stateful_tests:
    name: stateful_tests
    type: Core
    description: Tests that build on each other
    isolated: false  # REQUIRED to maintain state across cases
```

### Regression Group

```yaml
groups:
  regression_tests:
    name: regression_tests
    type: Regression
    description: Regression tests from previous checkpoint
    original_checkpoint: checkpoint_1
    original_group: basic_tests
```



### Field Reference

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `name` | string | Yes | - | Name of the group |
| `type` | GroupType | No | Functionality | Type of the group (Error, Functionality, Regression, Core) |
| `isolated` | bool | No | **true** | Reset workspace between each case (see IMPORTANT note above) |
| `group_files` | set[str] | No | set() | Files materialized into every case working directory |
| `original_checkpoint` | string | No | None | Original checkpoint name if this group is a regression group |
| `original_group` | string | No | None | Original group name if this group is a regression group |
| `case_order` | list[str] | No | [] | Order of cases in the group |
| `timeout` | float | No | None | Timeout in seconds for the group |
| `case_defaults` | dict | No | {} | Default values for cases in the group |

## RegressionSpec Configuration

Regression specs allow importing test groups from prior checkpoints to ensure new changes don't break existing functionality.

### Basic Structure

```yaml
regressions:
  - checkpoint: checkpoint_1  # Import from specific checkpoint
    groups: [basic_tests]     # Only these groups
    type_filter: Core         # Only Core type groups
    name_template: "{checkpoint}_{group}"  # Custom naming
```

### Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `checkpoint` | string | Conditional* | Source checkpoint name (use OR checkpoints) |
| `checkpoints` | string or list | Conditional* | "*" for all prior, or list of names |
| `groups` | list[str] | No | Specific groups to import (default: all) |
| `exclude` | list[str] | No | Groups to exclude from import |
| `type_filter` | GroupType | No | Only import groups of this type |
| `name_template` | string | No | Template for imported group names |

*One of `checkpoint` or `checkpoints` required

### Examples

```yaml
# Import all groups from checkpoint_1
regressions:
  - checkpoint: checkpoint_1

# Import all prior checkpoints
regressions:
  - checkpoints: "*"

# Import only Core tests from all prior
regressions:
  - checkpoints: "*"
    type_filter: Core
    name_template: "regression_{checkpoint}_{group}"

# Combine multiple strategies
regressions:
  - checkpoint: checkpoint_1
    groups: [critical_tests]
  - checkpoint: checkpoint_2
    exclude: [slow_tests]
```

See [Regression Testing Guide](../guides/regression-testing.md) for patterns and troubleshooting.

## Environment Configuration (Runtime Parameter)

**CRITICAL**: Environment configuration is **NOT** part of ProblemConfig or CheckpointConfig.
Instead, it is specified separately when running evaluations via the `EnvironmentSpec` parameter.

The environment is specified at execution time via CLI:

```bash
slop-code run \
  --agent configs/agents/claude_code/config.yaml \
  --environment configs/environments/docker-python3.12-uv.yaml \
  --problem my_problem
```

OR via run config YAML:

```yaml
# run_config.yaml
environment: configs/environments/docker-python3.12-uv.yaml
agent: configs/agents/claude_code.yaml
problems:
  - my_problem
```

### Why Separate?

- Same problem can be evaluated with different environments
- Environment choice is an execution decision, not problem design
- Allows testing same problem in Docker vs local
- Enables different Python versions without changing problem config

### Environment Files

Environment specs live in `configs/environments/` and define execution settings.

### Environment Structure

```yaml
# configs/environments/docker-python3.12-uv.yaml
type: docker                    # or 'local'
name: python3.12
docker:
  image: ghcr.io/astral-sh/uv:python3.12-trixie-slim
  workdir: /workspace
  mount_workspace: true

environment:
  env:                          # Environment variables
    UV_CACHE_DIR: /tmp/uv-cache
    PIP_CACHE_DIR: /tmp/pip-cache-dir
  include_os_env: false         # Whether to include host OS env vars

setup:
  commands:                     # Always run before execution
    - apt-get update
    - apt-get install -y git
  eval_commands:                # Only run during evaluation (hidden from agents)
    - uv init
    - uv add -r requirements.txt

commands:
  entry_file: "{entry_file}.py"
  command: uv run               # Command shown to evaluator
  agent_command: python         # Command shown to agent
```

### Setup Commands: Key Feature

The **setup commands** feature allows different initialization for evaluation vs agent environments:

#### `setup.commands` - Always Executed
These commands run in both agent and evaluation contexts:
- Installing system packages
- Setting up base environment
- Commands that agents should see

#### `setup.eval_commands` - Evaluation Only
These commands **only** run during evaluation and are **hidden from agents**:
- Installing test dependencies
- Setting up evaluation-specific tools
- Configuring test data or mocks
- Installing requirements that shouldn't be visible to agents

### Practical Examples

#### Example 1: Python with Test Dependencies
```yaml
type: docker
name: python-with-tests
docker:
  image: python:3.11-slim

setup:
  commands:
    # Basic setup visible to agents
    - apt-get update
    - apt-get install -y gcc

  eval_commands:
    # Evaluation-only: Install test dependencies
    - pip install pytest pytest-cov
    - pip install -r requirements.txt
    - python -m pytest --version  # Verify test setup

commands:
  command: python
  agent_command: python
```

**Why?** Agents shouldn't know about or rely on test frameworks being pre-installed.

#### Example 2: Node.js with Package Management
```yaml
type: docker
name: nodejs-pnpm
docker:
  image: node:18-alpine

setup:
  commands:
    # Visible to agents - they can see pnpm is available
    - npm install -g pnpm

  eval_commands:
    # Hidden from agents - auto-install dependencies
    - pnpm install --frozen-lockfile
    - pnpm run build

commands:
  command: node
  agent_command: node
```

**Why?** During evaluation, dependencies are pre-installed for consistent testing, but agents should handle dependency installation themselves.

#### Example 3: Database Setup
```yaml
type: docker
name: python-postgres
docker:
  image: python:3.11

environment:
  env:
    DATABASE_URL: postgresql://test:test@localhost/testdb

setup:
  commands:
    - apt-get update
    - apt-get install -y postgresql-client

  eval_commands:
    # Set up test database with schema and seed data
    - psql $DATABASE_URL < /static/schema.sql
    - psql $DATABASE_URL < /static/test_data.sql
    - pip install -r requirements.txt

commands:
  command: python
```

**Why?** Test data setup should be transparent to agents - they should work with the database as if it already exists.

#### Example 4: Local Environment with Virtual Env
```yaml
type: local
name: python-local

environment:
  env:
    VIRTUAL_ENV: .venv
    PATH: .venv/bin:$PATH

setup:
  commands:
    # Visible to agents
    - python -m venv .venv

  eval_commands:
    # Hidden from agents
    - .venv/bin/pip install --upgrade pip
    - .venv/bin/pip install -r requirements.txt
    - .venv/bin/pip install pytest

commands:
  command: .venv/bin/python
  agent_command: python
```

**Why?** Agents see that a virtual environment exists but don't see the automatic dependency installation.

### When to Use Evaluation Commands

Use `eval_commands` when you need to:

1. **Install Dependencies Transparently**
   - Requirements that agents shouldn't assume are pre-installed
   - Test frameworks and tools

2. **Set Up Test Infrastructure**
   - Database schemas and seed data
   - Mock services or test doubles
   - Configure test-specific environment settings

3. **Prepare Evaluation Context**
   - Download test data files
   - Configure authentication for test services
   - Set up monitoring or logging for evaluation

4. **Ensure Consistency**
   - Lock dependency versions for reproducible evaluation
   - Pre-compile or build assets to avoid timing variations
   - Cache downloads to prevent network failures

### Best Practices

1. **Keep `commands` minimal** - Only include setup that agents should see
2. **Use `eval_commands` for test isolation** - Hide test infrastructure from agents
3. **Document your choices** - Explain why certain commands are evaluation-only
4. **Test both contexts** - Ensure your environment works for both agents and evaluation
5. **Version your environments** - Track changes to environment configs in git

## Configuration Inheritance

Configuration values are inherited and can be overridden at each level:

```
Problem Config (global defaults)
    ↓
Checkpoint Config (can override problem values)
    ↓
Group Config (can override checkpoint values)
    ↓
Case Definition (can override group values)
```

### Example: Timeout Inheritance

```yaml
# Problem config.yaml
timeout: 120  # Global default: 2 minutes

checkpoints:
  checkpoint_1:
    timeout: 60   # Override for checkpoint: 1 minute
    groups:
      fast_tests:
        type: Core    # Inherits 60 seconds
      slow_tests:
        type: Core
        timeout: 300  # Override for group: 5 minutes
```

### Example: Environment Variables

```yaml
# Problem config.yaml
environment_variables:
  LOG_LEVEL: INFO
  DEBUG: "false"

checkpoints:
  checkpoint_1:
    environment_variables:
      DEBUG: "true"        # Override
      CHECKPOINT_ID: "cp1" # Add new variable

# Result: LOG_LEVEL=INFO, DEBUG=true, CHECKPOINT_ID=cp1
```

## Best Practices

### Organization

1. **Use meaningful names**: `checkpoint_1` → `basic_functionality`
2. **Group related tests**: Put similar test types in the same group
3. **Keep configs DRY**: Use inheritance instead of duplication

### Performance

1. **Set appropriate timeouts**: Don't make them too long or too short
2. **Minimize static assets**: Only include necessary files
3. **Use efficient loaders**: Cache expensive computations

### Maintainability

1. **Document your configs**: Use `description` fields
2. **Version your problems**: Update `version` when making changes
3. **Use consistent naming**: Follow a naming convention

### Example: Well-Organized Problem

```
my_problem/
├── config.yaml                    # Global settings
├── verifier.py
├── data/                          # Shared static assets
│   ├── common_data.csv
│   └── config.json
├── basic_functionality/           # Checkpoint 1
│   ├── config.yaml
│   ├── simple_operations/         # Group 1
│   │   ├── case_addition.yaml
│   │   └── case_subtraction.yaml
│   └── complex_operations/        # Group 2
│       ├── case_multiplication.yaml
│       └── case_division.yaml
└── edge_cases/                    # Checkpoint 2
    ├── config.yaml
    └── boundary_conditions/
        ├── case_zero.yaml
        └── case_negative.yaml
```

## Configuration Validation

The system automatically validates configurations using Pydantic models. Common validation errors:

### Missing Required Fields
```
Error: Field 'name' is required in ProblemConfig
```
**Fix**: Add the missing field to your config.

### Invalid Type
```
Error: Field 'timeout' must be an integer
```
**Fix**: Ensure the field has the correct type (e.g., `timeout: 60` not `timeout: "60"`).

### Invalid Environment
```
Error: Unknown environment type 'kubernetes'
```
**Fix**: Use a valid environment type (`docker` or `local`).

## Advanced Configuration

### Multiple Entry Points

For submissions with multiple commands:

```yaml
# Problem config.yaml
entry_point: "bash run.sh"  # Use a shell script

# run.sh handles different modes
# #!/bin/bash
# case "$1" in
#   mode1) python app.py ;;
#   mode2) python other.py ;;
# esac
```

### Conditional Static Assets

Use different assets for different checkpoints:

```yaml
checkpoints:
  checkpoint_1:
    static_assets:
      - source: data/small_dataset.csv
        destination: /app/data.csv

  checkpoint_2:
    static_assets:
      - source: data/large_dataset.csv
        destination: /app/data.csv
```

### Dynamic Environment Variables

Set environment variables based on case data (in verifier or loader):

```python
def load_cases(group_name, checkpoint_config):
    cases = []
    for scenario in ["dev", "prod"]:
        cases.append({
            "name": f"test_{scenario}",
            "input": {"mode": scenario},
            "environment_variables": {
                "ENV": scenario
            }
        })
    return cases
```

## Workspace Reset Control

The evaluation framework provides two levels of control for managing workspace state between test cases:

### Group-Level Control (`isolated` field)

Set `isolated: true` on a group to reset the workspace before each case:

```yaml
groups:
  independent_tests:
    type: Core
    isolated: true  # Each case starts with clean workspace
```

### Case-Level Control (`reset` field)

Individual cases can request workspace reset:

```yaml
# In case.yaml (CLI)
arguments: --command
reset: true  # Reset workspace before this case

# In case_name.yaml (API)
case:
  method: POST
  path: /endpoint
reset: true
```

### Behavior Precedence

1. **Group isolated=true (DEFAULT)**: Resets workspace before every case, ignoring case-level reset flags
2. **Group isolated=false**: Workspace persists across cases unless individual cases have `reset: true`
3. **Case reset=true**: Only takes effect when group is not isolated

### Use Cases

- **Isolated groups**: Testing independent features, ensuring no side effects
- **Case reset**: Cleanup scenarios, recovery testing, selective isolation
- **Default persistence**: Stateful testing, setup/teardown patterns, performance

## Next Steps

- **Choose an adapter**: [Adapters Guide](adapters.md)
- **Implement verification**: [Verification Guide](verification.md)
- **Set up case loading**: [Loaders Guide](loaders.md)
- **Understand reporting**: [Reporting Guide](reporting.md)
