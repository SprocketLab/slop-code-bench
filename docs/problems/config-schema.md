---
version: 1.1
last_updated: 2025-11-18
---

# Configuration Schema Reference

Complete field-by-field reference for all configuration files in the Slop Code evaluation framework.

## Table of Contents

- [Root Configuration](#root-configuration-configyaml)
- [Checkpoint Configuration](#checkpoint-configuration-checkpoint_nconfigyaml)
- [Adapter Configurations](#adapter-configurations)
- [Test Case Schemas](#test-case-schemas)
- [Validation Rules](#validation-rules)
- [Examples](#examples)

## Root Configuration (`config.yaml`)

Located at: `problems/<problem_name>/config.yaml`

### Required Fields

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `name` | string | Unique problem identifier (must match directory name) | `file_backup` |
| `adapter` | object | Adapter configuration (see [Adapter Configurations](#adapter-configurations)) | `{type: cli, ...}` |
| `entry_file` | string | Entry point module name (without `.py` extension) | `backup_scheduler` |
| `loader_script` | string | Path to loader file relative to problem root | `loader.py` |
| `loader_entrypoint` | string | Loader class or function name | `Loader` |
| `checkpoints` | array | List of checkpoint directory names | `[checkpoint_1, checkpoint_2]` |

### Optional Fields

| Field | Type | Default | Description | Example |
|-------|------|---------|-------------|---------|
| `description` | string | `""` | Human-readable problem description | `"CLI backup scheduler..."` |
| `category` | string | `null` | Problem category | `data-processing` |
| `difficulty` | string | `null` | Problem difficulty level | `Easy`, `Medium`, `Hard` |
| `tags` | array | `[]` | Searchable tags | `[cli, scheduling, yaml]` |
| `timeout` | integer | `30` | Default timeout in seconds for all tests | `60` |
| `version` | integer | `1` | Problem schema version | `1` |
| `static_assets` | object | `{}` | Static file mappings (see [Static Assets](#static-assets)) | `{files: {path: files}}` |

### Static Assets

Maps directories from the problem root into the execution environment.

**Schema:**
```yaml
static_assets:
  <asset_name>:
    path: <relative_path>    # Path relative to problem root
```

**Example:**
```yaml
static_assets:
  files:                     # Mounted as {{static:files}}
    path: files
  sde_dir:                   # Mounted as {{static:sde_dir}}
    path: data/sde
  reference_db:              # Mounted as {{static:reference_db}}
    path: databases/ref.db
```

**Usage in test cases:**
```yaml
# CLI case
arguments: --data-dir {{static:sde_dir}} --files {{static:files}}

# API case body
case:
  body:
    data_path: "{{static:reference_db}}/users.db"
```

### Legacy Loader Configuration

Some problems use an older `loader` configuration style:

```yaml
loader:
  type: script
  path: loader.py
  entrypoint: load_cases    # Function instead of class
```

**Prefer the newer style:**
```yaml
loader_script: loader.py
loader_entrypoint: Loader   # Class with __call__ method
```

### Complete Example

```yaml
name: file_backup
description: CLI backup scheduler that parses YAML and emits JSONL events
category: scheduling
difficulty: Medium
version: 1

adapter:
  type: cli
  tracked_files:
    - events.jsonl

entry_file: backup_scheduler
loader_script: loader.py
loader_entrypoint: Loader

checkpoints:
  checkpoint_1:
    order: 1
    path: checkpoint_1
    groups:
      core:
        type: Core
      errors:
        type: Error
    specification: spec.md
    state: Core Tests
    version: 1
  checkpoint_2:
    order: 2
    path: checkpoint_2
    groups:
      core:
        type: Core
      regression:
        type: Regression
    specification: spec.md
    state: Core Tests
    version: 1

static_assets:
  files:
    path: files

tags:
  - cli
  - scheduling
  - jsonl
  - yaml

timeout: 20
```

## Environment Configuration

While environments are configured separately from problems, they work together during evaluation. Environment configurations define how code is executed and can include special **evaluation-only setup commands**:

```yaml
# configs/environments/docker-python3.12.yaml
type: docker
name: python3.12
docker:
  image: python:3.12-slim

setup:
  commands:              # Visible to agents
    - apt-get update
    - apt-get install -y gcc

  eval_commands:         # Hidden from agents, evaluation only
    - pip install -r requirements.txt
    - pip install pytest
    - python setup.py develop

commands:
  entry_file: "{entry_file}.py"
  command: python
```

The `eval_commands` are **only executed during evaluation** and are **completely hidden from agents**, allowing you to:
- Pre-install dependencies for consistent testing
- Set up test infrastructure transparently
- Configure evaluation-specific tools

For detailed examples and use cases, see the environment configuration section in your environment YAML files.

## Checkpoint Entries (`config.yaml → checkpoints`)

Each checkpoint is declared inline inside the root problem configuration. The keys
of the `checkpoints` mapping are checkpoint directory names (usually
`checkpoint_1`, `checkpoint_2`, …). This keeps the execution metadata co-located
with the problem definition and eliminates the need for per-checkpoint
`config.yaml` files.

> **Migrating existing problems:** run `uv run python scripts/migrate_checkpoint_configs.py`
> to rewrite legacy per-checkpoint configs into the new inline format. Pass
> `--dry-run` first to preview changes.

### Required Fields

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `order` | integer | Execution order for the checkpoint (1-based) | `1` |
| `path` | string | Directory containing spec and cases (relative to problem root) | `checkpoint_1` |
| `groups` | object | Map of group name → group configuration | See [Group Configuration](#group-configuration) |
| `specification` | string | Spec file name (usually `spec.md`) | `spec.md` |

### Optional Fields

| Field | Type | Default | Description | Example |
|-------|------|---------|-------------|---------|
| `timeout` | number | From problem config | Default timeout for all groups in this checkpoint | `30` |
| `version` | integer | `1` | Checkpoint schema version | `1` |
| `state` | string | `null` | Checkpoint state label used in dashboards | `"Core Tests"` |
| `constant_files` | set[str] | `[]` | Files copied into every case workspace | `["shared/config.json"]` |
| `group_files` | set[str] | `[]` | Files copied into every group workspace | `["shared/base.csv"]` |
| `case_defaults` | object | `{}` | Default metadata merged into each case | `{"memory": "512MB"}` |
| `original_checkpoint` | string | `null` | Source checkpoint for regression groups | `checkpoint_2` |
| `original_group` | string | `null` | Source group for regression groups | `core` |

### Group Configuration

Each group is defined as:

```yaml
groups:
  <group_name>:
    type: <group_type>
    timeout: <seconds>        # Optional, overrides checkpoint default
    case_order: [...]         # Optional, required for stateful API tests
    group_files: [...]        # Optional, files shared by all cases in group
    isolated: <boolean>       # Optional, reset workspace between each case (default: true)
```

#### Group Type

| Type | Purpose | When to Use |
|------|---------|-------------|
| `Core` | Happy path functionality | Primary success scenarios |
| `Error` | Error handling | Invalid inputs, error codes |
| `Functionality` | Feature variations | Optional features, modes, edge cases |
| `Regression` | Prevent regressions | Previously broken scenarios |

#### Case Order (API Only)

**Required for API adapters** to ensure stateful tests run in correct sequence.

```yaml
groups:
  functionality:
    type: Functionality
    case_order:
      - create_user          # Must run first
      - get_user             # Depends on create_user
      - update_user          # Depends on get_user
      - delete_user          # Depends on update_user
```

**Rules:**
- Must list ALL case files (without `.yaml` extension)
- Cases execute in the exact order listed
- For directory-based cases, use directory names

#### Group Files

Files copied into the workspace for all cases in this group.

```yaml
groups:
  functionality:
    group_files:
      - shared/base_config.json     # From checkpoint_N/functionality/shared/
      - fixtures/test_data.csv
```

**Path resolution:**
- Relative to `checkpoint_N/<group_name>/`
- Copied to workspace root before each case
- Available to the submission code

#### Isolated Groups

The `isolated` field controls workspace persistence between cases in a group.

```yaml
groups:
  stateless_tests:
    type: Core
    isolated: true    # Each case starts with a clean workspace

  stateful_tests:
    type: Functionality
    isolated: false   # Explicitly disable isolation: workspace persists between cases
    case_order:
      - setup
      - test_1
      - test_2
      - cleanup
```

**Behavior:**
- `isolated: true` (default) - Workspace is reset to initial state before each case
- `isolated: false` - Workspace persists between cases in the group
- Useful for ensuring test isolation or when cases should not affect each other
- Overrides individual case `reset` flags when set to `true`

### Complete Example

```yaml
version: 1
state: Core Tests

groups:
  core:
    type: Core
    timeout: 20

  errors:
    type: Error
    timeout: 20

  functionality:
    type: Functionality
    timeout: 30
    case_order:
      - setup_base
      - test_feature_a
      - test_feature_b
    group_files:
      - shared/common.json

specification: spec.md
timeout: 20
```

## Regression Testing Configuration

The regression system allows you to automatically import test cases from previous checkpoints, ensuring that functionality verified in earlier checkpoints continues to work in later ones. This is crucial for preventing regressions as problems evolve.

### Regression Specification (`regressions`)

Located in: root `config.yaml` under `checkpoints.checkpoint_N.regressions`

The `regressions` field accepts a list of regression specifications that define which groups to import from previous checkpoints.

**Schema:**
```yaml
regressions:
  - checkpoint: <string>          # Single checkpoint to import from
    # OR
    checkpoints: <array|"*">      # List of checkpoints or "*" for all prior
    groups: [...]                 # Groups to import (empty = all groups)
    type_filter: <GroupType>      # Optional: Only import groups of this type
    exclude: [...]                # Groups to exclude from import
    name_template: <string>       # Template for generated group names
```

**Field Details:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `checkpoint` | string | - | Single checkpoint name to import from (mutually exclusive with `checkpoints`) |
| `checkpoints` | array or `"*"` | - | List of checkpoint names or `"*"` to import from all prior checkpoints |
| `groups` | array | `[]` | Specific group names to import. Empty means import all groups |
| `type_filter` | GroupType | - | Filter to only import groups of a specific type (Core, Error, Functionality) |
| `exclude` | array | `[]` | Group names to exclude even if matched by other criteria |
| `name_template` | string | `"{checkpoint}_{group}"` | Template for naming imported groups. Supports `{checkpoint}`, `{group}`, and `{idx}` placeholders |

### Examples

#### Import Specific Groups from Previous Checkpoint

```yaml
# checkpoint_2/config.yaml
regressions:
  - checkpoint: checkpoint_1
    groups:
      - core
      - errors
```

This imports only the `core` and `errors` groups from `checkpoint_1`. The resulting groups will be named `checkpoint_1_core` and `checkpoint_1_errors`.

#### Import All Core Tests from Multiple Checkpoints

```yaml
# checkpoint_3/config.yaml
regressions:
  - checkpoints:
      - checkpoint_1
      - checkpoint_2
    type_filter: Core
```

This imports only groups with `type: Core` from both previous checkpoints.

#### Import Everything from All Prior Checkpoints

```yaml
# checkpoint_5/config.yaml
regressions:
  - checkpoints: "*"
    exclude:
      - hidden
      - draft_tests
```

This imports all groups from checkpoints 1-4, except for `hidden` and `draft_tests` groups.

#### Custom Naming Template

```yaml
# checkpoint_3/config.yaml
regressions:
  - checkpoint: checkpoint_1
    groups: [core]
    name_template: "regression_{idx}_{group}"
```

This creates a group named `regression_0_core` instead of the default `checkpoint_1_core`.

### How Regression Groups Work

When regression specifications are processed:

1. **Resolution**: The system resolves which checkpoints and groups to import based on the specification
2. **Expansion**: Each matching group becomes a new `GroupConfig` with `type: Regression`
3. **Metadata**: Regression groups store their origin in `original_checkpoint` and `original_group` fields
4. **Path Resolution**: Loaders use the original checkpoint/group path to find test cases
5. **Merging**: Regression groups are added to the checkpoint's groups, with later definitions overriding earlier ones if names collide

### Regression Group Metadata

Regression groups automatically get these additional fields:

```yaml
groups:
  checkpoint_1_core:              # Auto-generated name
    type: Regression              # Always set to Regression
    original_checkpoint: checkpoint_1
    original_group: core
    # Other fields inherited from source group
```

### Best Practices

1. **Progressive Testing**: Import core functionality from early checkpoints to ensure it doesn't break
2. **Selective Import**: Use `type_filter` to import only relevant test types
3. **Avoid Duplication**: Use `exclude` to skip groups that are redundant with new tests
4. **Clear Naming**: Use descriptive `name_template` values when the default isn't clear enough
5. **Order Matters**: Checkpoints are processed in order, so regression imports only work from earlier checkpoints

## Adapter Configurations

### CLI Adapter

For command-line tools and scripts.

**Required fields:**
```yaml
adapter:
  type: cli
  tracked_files: [...]      # List of output files to capture
```

**Optional fields:**
```yaml
adapter:
  type: cli
  tracked_files: [events.jsonl, output.txt]
  timeout: 30               # Default timeout for CLI execution
```

**Example:**
```yaml
adapter:
  type: cli
  tracked_files:
    - events.jsonl
    - summary.txt
```

### API Adapter

For REST APIs and web services.

**Required fields:**
```yaml
adapter:
  type: api
  address: <host>           # Server address (default: 127.0.0.1)
  health_path: <path>       # Health check endpoint
```

**Optional fields:**
```yaml
adapter:
  type: api
  address: 127.0.0.1
  port: 8000                # Server port (default: 8000)
  health_path: /healthz
  startup_timeout_s: 10     # Timeout for server startup
  response_is_json: true    # Parse all responses as JSON
  tracked_files: []         # Output files (usually empty for APIs)
```

**Complete example:**
```yaml
adapter:
  type: api
  address: 127.0.0.1
  port: 8000
  health_path: /healthz
  startup_timeout_s: 10
  response_is_json: true
  tracked_files: []
```

### Playwright Adapter

For browser-based applications.

**Required fields:**
```yaml
adapter:
  type: playwright
  url: <base_url>           # Application URL
```

**Optional fields:**
```yaml
adapter:
  type: playwright
  url: http://localhost:3000
  startup_timeout_s: 30
  headless: true            # Run browser in headless mode
```

**Example:**
```yaml
adapter:
  type: playwright
  url: http://localhost:3000
  startup_timeout_s: 30
  headless: true
```

## Test Case Schemas

### CLI Test Case (`case.yaml`)

Located in: `checkpoint_N/<group>/<case_name>/case.yaml`

**Schema:**
```yaml
arguments: <string>         # CLI arguments (parsed with shlex)
input_files: [...]          # List of input file definitions
reset: <boolean>            # Optional: reset workspace before this case (default: false)
```

**Input File Schema:**
```yaml
- path: <string>            # File path in workspace
  content: <string>         # File content
  file_type: <string>       # Optional: csv, json, yaml, txt, binary
```

**Complete example:**
```yaml
arguments: --schedule schedule.yaml --now 2025-01-10T10:00:00Z --duration 24

input_files:
  - path: schedule.yaml
    file_type: yaml
    content: |
      version: 1
      timezone: UTC
      jobs:
        - id: daily-backup
          when:
            kind: daily
            at: "03:00"

  - path: data.csv
    file_type: csv
    content: |
      id,name,value
      1,foo,100
      2,bar,200
```

### CLI Expected Output

Located in: `checkpoint_N/<group>/<case_name>/expected.<ext>`

**Common formats:**
- `expected.txt` - Plain text output
- `expected.json` - JSON output
- `expected.jsonl` - JSON Lines output
- `expected.yaml` - YAML output
- `expected.csv` - CSV output

**For error cases, use YAML:**
```yaml
# expected.yaml
status_code: 3
stderr_pattern: "ERROR:E_PARSE:.*"
```

### API Test Case (`<case_name>.yaml`)

Located in: `checkpoint_N/<group>/<case_name>.yaml`

**Schema:**
```yaml
case:                       # Request definition
  method: <HTTP_METHOD>     # GET, POST, PUT, PATCH, DELETE, etc.
  path: <url_path>          # URL path (relative to base URL)
  headers: {...}            # Optional: HTTP headers
  body: <any>               # Optional: Request body (JSON object or string)
  query: {...}              # Optional: Query parameters

expected:                   # Expected response
  status_code: <integer>    # Expected HTTP status code
  headers: {...}            # Optional: Expected response headers
  output: <any>             # Expected response body

reset: <boolean>            # Optional: reset workspace before this case (default: false)
```

**Complete example:**
```yaml
case:
  method: POST
  path: /v1/users
  headers:
    content-type: application/json
    x-api-key: test-key-123
  body:
    name: Alice Smith
    email: alice@example.com
    role: admin

expected:
  status_code: 201
  headers:
    content-type: application/json
  output:
    id: "{{dynamic}}"       # Will be generated by server
    name: Alice Smith
    email: alice@example.com
    role: admin
    created_at: "{{dynamic}}"
```

### API Expected Output with JSON Schema

Instead of exact matching, use JSON Schema for flexible validation:

```yaml
case:
  method: GET
  path: /v1/users

expected:
  status_code: 200
  output:
    type: object
    properties:
      users:
        type: array
        items:
          type: object
          properties:
            id: {type: string}
            name: {type: string}
            email: {type: string, format: email}
            role: {type: string, enum: [admin, user, guest]}
          required: [id, name, email, role]
    required: [users]
```

**The verifier automatically detects JSON Schema** when the `output` contains schema keywords (`type`, `properties`, `items`, etc.).

### Dynamic Values

For values that can't be known in advance:

```yaml
expected:
  output:
    id: "{{dynamic}}"           # Any value accepted
    timestamp: "{{dynamic}}"    # Any value accepted
    name: "Alice"               # Must match exactly
```

## Workspace Reset Behavior

The evaluation framework supports two levels of workspace reset control to manage state between test cases:

### Group-Level Reset (`isolated`)

Set on a group to control workspace persistence for all cases in the group:

```yaml
groups:
  independent_tests:
    type: Core
    isolated: true    # Reset workspace before each case
```

**Use cases:**
- Testing independent features that shouldn't affect each other
- Ensuring clean state for each test case
- Debugging test failures caused by state pollution

### Case-Level Reset (`reset`)

Set on individual cases for fine-grained control:

```yaml
# CLI case
arguments: --cleanup
reset: true    # Reset workspace before this specific case

# API case
case:
  method: POST
  path: /reset
reset: true
```

**Use cases:**
- Cleanup cases that need fresh state
- Testing recovery from clean state
- Selective isolation within a stateful test group

### Behavior Priority

1. If `group.isolated = true` (default), workspace resets before **every** case (overrides case-level `reset`)
2. If `group.isolated = false`, only cases with `reset: true` trigger workspace reset
3. When both `isolated` and `reset` are false: workspace persists between cases

### Example: Mixed State Management

```yaml
groups:
  setup_and_test:
    type: Core
    isolated: false      # Maintain state between most cases
    case_order:
      - setup           # Creates initial data
      - test_feature_1  # Uses setup data
      - test_feature_2  # Uses setup data
      - cleanup         # reset: true - starts fresh
      - test_recovery   # Verifies clean state behavior

  independent_validations:
    type: Functionality
    isolated: true       # Each validation starts clean
    # All cases here will have workspace reset
```

## Validation Rules

### Problem Name

- Must match directory name
- Snake_case recommended
- No spaces or special characters (except underscore)
- Example: `file_backup`, `dynamic_config_service_api`

### Checkpoint Names

- Must follow pattern: `checkpoint_N` where N = 1, 2, 3, ...
- Must appear as keys inside the root `config.yaml` checkpoints mapping
- Must have corresponding directories containing specs and cases

### Group Names

- Lowercase, snake_case recommended
- Common: `core`, `errors`, `functionality`, `regression`
- Can use custom names for domain-specific grouping

### File Names

**Fixed names (do not change):**
- `config.yaml` - Always named `config.yaml`
- `spec.md` - Usually `spec.md` (can be configured in checkpoint config)
- `loader.py` - Usually `loader.py` (can be configured in root config)
- `verifier.py` - Usually `verifier.py` (referenced in verifier module)

**Case files:**
- CLI (directories): `<descriptive_name>/` (e.g., `basic_test/`, `error_invalid_input/`)
- API (files): `<descriptive_name>.yaml` (e.g., `create_user.yaml`, `get_user_by_id.yaml`)

### Timeout Values

- Measured in seconds
- Default: 30 seconds
- Can be overridden at problem, checkpoint, or group level
- Hierarchy: group timeout > checkpoint timeout > problem timeout > default

### Static Asset Paths

- Must be relative to problem root
- Can reference directories or files
- Referenced in test cases as `{{static:asset_name}}`

## Examples

### Minimal CLI Problem

```yaml
# config.yaml
name: hello_world
adapter:
  type: cli
  tracked_files: [output.txt]
entry_file: solution
loader_script: loader.py
loader_entrypoint: Loader
checkpoints:
  checkpoint_1:
    order: 1
    path: checkpoint_1
    groups:
      core:
        type: Core
    specification: spec.md
```

### Minimal API Problem

```yaml
# config.yaml
name: simple_api
adapter:
  type: api
  address: 127.0.0.1
  health_path: /health
  response_is_json: true
entry_file: server
loader_script: loader.py
loader_entrypoint: Loader
checkpoints:
  checkpoint_1:
    order: 1
    path: checkpoint_1
    groups:
      core:
        type: Core
        case_order:
          - create_item
          - get_item
    specification: spec.md
```

### Complex Multi-Checkpoint Problem

```yaml
# config.yaml
name: eve_industry
description: CLI tool for EVE Online industry planning
category: data-processing
difficulty: Hard
version: 1

adapter:
  type: cli
  tracked_files:
    - outputs/jobs.csv
    - outputs/materials.csv

entry_file: industry
loader_script: loader.py
loader_entrypoint: Loader

checkpoints:
  checkpoint_1:
    order: 1
    path: checkpoint_1
    groups:
      core:
        type: Core
    specification: spec.md
    state: Core Tests
  checkpoint_2:
    order: 2
    path: checkpoint_2
    groups:
      core:
        type: Core
      regression:
        type: Regression
    specification: spec.md
    state: Core Tests
  checkpoint_3:
    order: 3
    path: checkpoint_3
    groups:
      core:
        type: Core
        timeout: 15
      functionality:
        type: Functionality
        timeout: 20
        group_files:
          - shared/base_blueprints.yaml
      edge_cases:
        type: Functionality
        timeout: 20
    specification: spec.md
    state: Invention Mechanics
    timeout: 15
  checkpoint_4:
    order: 4
    path: checkpoint_4
    groups:
      core:
        type: Core
    specification: spec.md
    state: Verified
  checkpoint_5:
    order: 5
    path: checkpoint_5
    groups:
      regression:
        type: Regression
    specification: spec.md
    state: Verified

static_assets:
  sde_dir:
    path: sde

tags:
  - data-processing
  - planning
  - csv

timeout: 10
```

## Schema Validation

While not enforced by a formal schema validator, problems should follow these conventions:

**Required files checklist:**
- [ ] `config.yaml` (root)
- [ ] `loader.py`
- [ ] `verifier.py`
- [ ] `checkpoint_N/spec.md` (for each checkpoint)
- [ ] At least one test case in each group

**Configuration checklist:**
- [ ] `adapter.type` matches test case structure (CLI = directories, API = YAML files)
- [ ] All checkpoints in root config have corresponding directories
- [ ] All groups in checkpoint config have corresponding directories/files
- [ ] API adapters have `case_order` defined for stateful groups
- [ ] `static_assets` paths exist and are relative to problem root
- [ ] `entry_file` module exists in solution code

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Missing `case_order` for API | Add `case_order` list to group config |
| Wrong `tracked_files` path | Make paths relative to workspace root |
| Mismatched checkpoint names | Ensure checkpoint dirs match keys in `checkpoints` mapping |
| Absolute paths in static_assets | Use paths relative to problem root |
| Wrong loader entrypoint | Use class name (with `__call__`), not function name |
| Missing group directories | Create dir for each group in checkpoint config |

## Next Steps

- **[Quick Reference](quick-reference.md)** - Cheat sheet for quick lookups
- **[Problem Structure](structure.md)** - Visual guide to directory layout
- **[Test Cases Guide](test-cases.md)** - How to write effective test cases
- **[Examples](examples/)** - Annotated examples of real problems
