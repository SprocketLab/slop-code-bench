---
version: 1.0
last_updated: 2025-11-06
---

# Problem Structure Visual Guide

This guide provides detailed visual diagrams of problem directory structures with annotations explaining the purpose of each file and directory.

## Table of Contents

- [Overview](#overview)
- [CLI Problem Structure](#cli-problem-structure)
- [API Problem Structure](#api-problem-structure)
- [Multi-Checkpoint Problem](#multi-checkpoint-problem)
- [File Roles Explained](#file-roles-explained)
- [Naming Conventions](#naming-conventions)

## Overview

Every problem follows a hierarchical structure:

```
Problem
├── Configuration (config.yaml, loader.py, verifier.py)
├── Checkpoints (milestone 1, 2, 3...)
│   └── Groups (core, errors, functionality...)
│       └── Cases (individual tests)
└── Assets (optional shared files)
```

**Key Principle**: Each level has a clear responsibility and can be understood independently.

## CLI Problem Structure

### Complete Annotated Example

```
problems/file_backup/                      # Problem root directory
│
├── config.yaml                            # ┌─────────────────────────────┐
│                                          # │ Problem Configuration       │
│   name: file_backup                      # │ • Unique identifier         │
│   adapter:                               # │ • Adapter type & settings   │
│     type: cli                            # │ • Entry point               │
│     tracked_files: ["events.jsonl"]      # │ • Loader references         │
│   entry_file: backup_scheduler           # │ • Checkpoint list           │
│   loader_script: loader.py               # │ • Static assets             │
│   loader_entrypoint: Loader              # └─────────────────────────────┘
│   checkpoints:
│     checkpoint_1:
│       order: 1
│       path: checkpoint_1
│       groups: { core: { type: Core }, errors: { type: Error } }
│       specification: spec.md
│   static_assets:
│     files: {path: files}
│
├── loader.py                              # ┌─────────────────────────────┐
│                                          # │ Test Case Discovery         │
│   class Loader(BaseLoader):              # │ • Finds test cases          │
│       def __call__(self, group, store):  # │ • Reads case files          │
│           # Discover and yield cases     # │ • Creates Case objects      │
│                                          # │ • Returns Expected results  │
│                                          # └─────────────────────────────┘
│
├── verifier.py                            # ┌─────────────────────────────┐
│                                          # │ Output Validation           │
│   class Verifier:                        # │ • Compares actual/expected  │
│       def __call__(self, ...):           # │ • Scores each field         │
│           # Verify outputs               # │ • Returns VerificationResult│
│                                          # └─────────────────────────────┘
│
├── checkpoint_1/                          # ═══════════════════════════════
│   │                                      # ║ CHECKPOINT 1: Basic Parsing ║
│   │                                      # ═══════════════════════════════
│   │                                      # Config defined inline in root
│   │                                      # `config.yaml` under `checkpoints`
│   │
│   ├── spec.md                            # ┌─────────────────────────────┐
│   │   # Checkpoint 1: CLI Parser         # │ Agent Instructions          │
│   │   Build a CLI that parses YAML...    # │ • What to build             │
│   │                                      # │ • Requirements              │
│   │                                      # │ • Exit codes                │
│   │                                      # │ • Output format             │
│   │                                      # └─────────────────────────────┘
│   │
│   ├── core/                              # ─────────────────────────────
│   │   │                                  # Test Group: Core Functionality
│   │   ├── daily_due_simple/              # ─────────────────────────────
│   │   │   │                              # ┌─────────────────────────────┐
│   │   │   ├── case.yaml                  # │ Test Case: daily_due_simple │
│   │   │   │   arguments: --schedule ...  # │ • CLI arguments             │
│   │   │   │   input_files:               # │ • Input files               │
│   │   │   │     - path: schedule.yaml    # │ • Expected in workspace     │
│   │   │   │       content: "..."         # └─────────────────────────────┘
│   │   │   │
│   │   │   └── expected.jsonl             # ┌─────────────────────────────┐
│   │   │       {"event": "job_start"...}  # │ Expected Output             │
│   │   │       {"event": "job_end"...}    # │ • What should be produced   │
│   │   │                                  # │ • Verifier compares against │
│   │   │                                  # └─────────────────────────────┘
│   │   │
│   │   ├── multiple_jobs_sorting/         # Another test case...
│   │   │   ├── case.yaml
│   │   │   └── expected.jsonl
│   │   │
│   │   └── rel_mount/                     # Test with static assets...
│   │       ├── case.yaml
│   │       └── expected.jsonl
│   │
│   ├── errors/                            # ─────────────────────────────
│   │   │                                  # Test Group: Error Handling
│   │   ├── error_yaml_parse/              # ─────────────────────────────
│   │   │   ├── case.yaml                  # ┌─────────────────────────────┐
│   │   │   │   arguments: --schedule ...  # │ Error Test Case             │
│   │   │   │   input_files:               # │ • Invalid input             │
│   │   │   │     - path: bad.yaml         # │ • Expected error code       │
│   │   │   │       content: "invalid{"    # │ • Expected stderr pattern   │
│   │   │   └── expected.yaml              # └─────────────────────────────┘
│   │   │       status_code: 3
│   │   │       stderr_pattern: "ERROR:E_PARSE"
│   │   │
│   │   └── error_schema_version/          # Another error case...
│   │       ├── case.yaml
│   │       └── expected.yaml
│   │
│   └── solution/                          # ┌─────────────────────────────┐
│       └── backup_scheduler.py            # │ Reference Solution (Optional)│
│                                          # │ • For problem development   │
│                                          # │ • Not used in evaluation    │
│                                          # └─────────────────────────────┘
│
├── checkpoint_2/                          # ═══════════════════════════════
│   ├── spec.md                            # ║ CHECKPOINT 2: Add Execution ║
│   │                                      # ═══════════════════════════════
│   ├── core/
│   │   ├── full_backup/
│   │   │   ├── case.yaml
│   │   │   └── expected.jsonl
│   │   └── verify_mode/
│   │       ├── case.yaml
│   │       │   arguments: --mode verify ...
│   │       │   input_files:
│   │       │     - path: backup/...
│   │       └── expected.jsonl
│   └── solution/
│
├── files/                                 # ┌─────────────────────────────┐
│   ├── A/                                 # │ Static Assets               │
│   │   ├── B/                             # │ • Shared across all tests   │
│   │   │   └── C/                         # │ • Mounted via static_assets │
│   │   │       └── D.py                   # │ • Referenced as {{static:}} │
│   │   └── I.py                           # │ • Example: test data files  │
│   ├── M.py                               # └─────────────────────────────┘
│   └── O.md
│
└── solution/                              # ┌─────────────────────────────┐
    ├── backup_scheduler.py                # │ Full Reference Solution     │
    ├── requirements.txt                   # │ • Complete implementation   │
    └── plan.md                            # │ • For testing the problem   │
                                           # └─────────────────────────────┘
```

### Directory vs File-Based Cases

CLI problems can structure test cases in two ways:

#### Directory-Based (Recommended for Complex Cases)

```
checkpoint_1/core/
├── test_with_multiple_inputs/     # Case directory
│   ├── case.yaml                  # Arguments + input files
│   ├── input1.csv                 # Additional input file
│   ├── input2.json                # Additional input file
│   └── expected.txt               # Expected output
└── simple_test/                   # Case directory
    ├── case.yaml
    └── expected.txt
```

**Use when:**
- Test cases need multiple input files
- Input files are complex (CSV, JSON, binary)
- You want clear separation between tests

#### File-Based (Simpler Cases)

```
checkpoint_1/core/
├── basic_parse.yaml               # Contains: case + expected
├── advanced_parse.yaml
└── edge_case.yaml
```

**Use when:**
- Test cases are simple (few inputs)
- All test data fits in YAML
- You want compact organization

## API Problem Structure

### Complete Annotated Example

```
problems/dynamic_config_service_api/       # Problem root directory
│
├── config.yaml                            # ┌─────────────────────────────┐
│   name: dynamic_config_service_api       # │ API Problem Configuration   │
│   adapter:                                # │ • adapter.type: api         │
│     type: api                             # │ • Server address/port       │
│     address: 127.0.0.1                    # │ • Health check endpoint     │
│     health_path: /healthz                 # │ • Startup timeout           │
│     startup_timeout_s: 10                 # │ • Response format           │
│     response_is_json: true                # └─────────────────────────────┘
│   entry_file: config_server
│   loader_script: loader.py
│   loader_entrypoint: Loader
│   checkpoints:
│     checkpoint_1:
│       order: 1
│       path: checkpoint_1
│       groups: { core: { type: Core, case_order: [...] } }
│       specification: spec.md
│
├── loader.py                              # ┌─────────────────────────────┐
│   class Loader(BaseLoader):              # │ API Test Case Discovery     │
│     def __call__(self, group, store):    # │ • Reads YAML case files     │
│       # Read cases in order              # │ • Respects case_order       │
│       for case_id in group.case_order:   # │ • Creates APICase objects   │
│         # Load request + expected        # │ • Manages stateful store    │
│                                           # └─────────────────────────────┘
│
├── verifier.py                            # ┌─────────────────────────────┐
│   class Verifier:                         # │ API Response Validation     │
│     def __call__(self, ...):              # │ • Status code check         │
│       # Verify status, headers, body     # │ • Header validation         │
│                                           # │ • JSON/Schema verification  │
│                                           # └─────────────────────────────┘
│
└── checkpoint_1/                          # ═══════════════════════════════
    │                                      # ║ CHECKPOINT 1: Core API      ║
    │                                      # ═══════════════════════════════
    │                                      # Config declared inline under
    │                                      # `checkpoints` in root config
    │
    ├── spec.md                            # ┌─────────────────────────────┐
    │   # Checkpoint 1: Versioned Config  # │ API Specification           │
    │   Build a REST API that...          # │ • Endpoints to implement    │
    │   ## Endpoints                       # │ • Request/response schemas  │
    │   POST /scopes/{name}                # │ • Versioning behavior       │
    │   GET /scopes/{name}                 # │ • Error codes               │
    │                                      # └─────────────────────────────┘
    │
    ├── spec_cases/                        # ─────────────────────────────
    │   │                                  # Test Group: Spec Compliance
    │   ├── create_base_v1.yaml            # ─────────────────────────────
    │   │   case:                          # ┌─────────────────────────────┐
    │   │     method: POST                 # │ API Test Case               │
    │   │     path: /scopes/billing        # │ • HTTP method               │
    │   │     headers:                     # │ • URL path                  │
    │   │       content-type: application/json  # │ • Headers          │
    │   │     body:                        # │ • Request body (JSON)       │
    │   │       config:                    # │ • Expected response         │
    │   │         max_users: 100           # └─────────────────────────────┘
    │   │   expected:
    │   │     status_code: 201
    │   │     output:
    │   │       scope: billing
    │   │       version: 1
    │   │       config: {max_users: 100}
    │   │
    │   └── get_base.yaml                  # ┌─────────────────────────────┐
    │       case:                          # │ Stateful API Test           │
    │         method: GET                  # │ • Depends on create_base_v1 │
    │         path: /scopes/billing        # │ • Retrieves created resource│
    │       expected:                      # │ • case_order ensures this   │
    │         status_code: 200             # │   runs after creation       │
    │         output:                      # └─────────────────────────────┘
    │           scope: billing
    │           version: 1
    │
    ├── functionality/                     # ─────────────────────────────
    │   │                                  # Test Group: Advanced Features
    │   ├── setup_array_base.yaml          # ─────────────────────────────
    │   │   case:                          # ┌─────────────────────────────┐
    │   │     method: POST                 # │ Test Sequence               │
    │   │     path: /scopes/features       # │ 1. Setup base state         │
    │   │     body: {tags: ["a", "b"]}     # │ 2. Test array merging       │
    │   │   expected:                      # │ 3. Test version activation  │
    │   │     status_code: 201             # │ 4. Verify retrieval         │
    │   │                                  # │                             │
    │   ├── resolve_array_merge.yaml       # │ Each case builds on the     │
    │   │   case:                          # │ previous one's state.       │
    │   │     method: POST                 # │                             │
    │   │     path: /scopes/features       # │ case_order guarantees this. │
    │   │     body: {tags: ["c"]}          # └─────────────────────────────┘
    │   │   expected:
    │   │     status_code: 201
    │   │     output:
    │   │       version: 2
    │   │       config: {tags: ["a","b","c"]}
    │   │
    │   ├── activate_specific_version.yaml
    │   └── get_specific_version.yaml
    │
    ├── spec_errors/                       # ─────────────────────────────
    │   │                                  # Test Group: Error Cases
    │   ├── scope_not_found.yaml           # ─────────────────────────────
    │   │   case:                          # ┌─────────────────────────────┐
    │   │     method: GET                  # │ Error Test Case             │
    │   │     path: /scopes/nonexistent    # │ • Invalid request           │
    │   │   expected:                      # │ • Expected error status     │
    │   │     status_code: 404             # │ • Expected error message    │
    │   │     output:                      # │ • Can use JSON schema       │
    │   │       error: "Scope not found"   # └─────────────────────────────┘
    │   │
    │   └── invalid_json.yaml
    │       case:
    │         method: POST
    │         path: /scopes/test
    │         body: "not valid json"
    │       expected:
    │         status_code: 400
    │
    └── solution/                          # Reference implementation
        └── config_server.py
```

### API-Specific Features

#### Case Order (Required for Stateful APIs)

```yaml
# config.yaml → checkpoints.checkpoint_1.groups.functionality
checkpoints:
  checkpoint_1:
    groups:
      functionality:
        type: Functionality
        case_order:                # MUST list cases in execution order
          - setup_base             # 1. Create resource
          - update_resource        # 2. Modify it
          - get_updated            # 3. Verify changes
          - rollback               # 4. Revert changes
          - verify_rollback        # 5. Confirm rollback
```

**Why it matters:**
- API tests often depend on previous requests
- Creating a resource before retrieving it
- Ensuring predictable state for each test

#### Dynamic Values in Expectations

```yaml
# Some values aren't known in advance
expected:
  status_code: 201
  output:
    id: "{{dynamic}}"              # Will be generated by server
    created_at: "{{dynamic}}"      # Timestamp
    name: "billing"                # Known value
```

**Or use JSON Schema for flexible validation:**

```yaml
expected:
  status_code: 200
  output:
    type: object
    properties:
      id: {type: string}
      version: {type: integer, minimum: 1}
      config: {type: object}
    required: [id, version, config]
```

## Multi-Checkpoint Problem

### Checkpoint Progression Example

```
problems/eve_industry/                     # Complex multi-checkpoint problem
│
├── config.yaml
│   checkpoints:
│     - checkpoint_1                       # Basic recipe lookup
│     - checkpoint_2                       # Material calculation
│     - checkpoint_3                       # Invention system
│     - checkpoint_4                       # Build planning
│     - checkpoint_5                       # Optimization
│   static_assets:                         # ┌─────────────────────────────┐
│     sde: {path: sde}                     # │ Static Assets Mapping       │
│                                          # └─────────────────────────────┘
│
├── checkpoint_1/                          # ═══════════════════════════════
│   ├── spec.md                            # ║ CHECKPOINT 1: Recipe Lookup ║
│   │   Build a CLI that loads SDE...     # ═══════════════════════════════
│   └── core/                              # Test: Basic lookups
│       ├── lookup_single_item/
│       └── lookup_with_materials/
│
├── checkpoint_2/                          # ═══════════════════════════════
│   ├── spec.md                            # ║ CHECKPOINT 2: Material Calc ║
│   │   Extend checkpoint_1 to            # ═══════════════════════════════
│   │   calculate materials recursively   # Builds on checkpoint_1 code
│   └── core/                              # Tests: Recursive calculation
│       ├── simple_build/
│       └── complex_build_tree/
│
├── checkpoint_3/                          # ═══════════════════════════════
│   ├── spec.md                            # ║ CHECKPOINT 3: Invention     ║
│   │   Add invention mechanics...        # ═══════════════════════════════
│   └── functionality/                     # New feature on top of 1+2
│       ├── invent_t2_blueprint/
│       └── invention_probability/
│
├── checkpoint_4/                          # ═══════════════════════════════
│   ├── spec.md                            # ║ CHECKPOINT 4: Planning      ║
│   │   Add build planning from YAML...   # ═══════════════════════════════
│   └── core/                              # Combines all previous features
│       ├── simple_build_plan/
│       └── multi_item_plan/
│
├── checkpoint_5/                          # ═══════════════════════════════
│   ├── spec.md                            # ║ CHECKPOINT 5: Optimization  ║
│   │   Optimize material purchasing...   # ═══════════════════════════════
│   ├── core/
│   │   └── cost_optimization/
│   └── hidden/                            # ┌─────────────────────────────┐
│       └── complex_scenario/              # │ Hidden Test Cases           │
│                                          # │ • Not shown to agent        │
│                                          # │ • Prevent overfitting       │
│                                          # └─────────────────────────────┘
│
└── sde/                                   # ┌─────────────────────────────┐
    ├── blueprints.yaml                    # │ Large Static Assets         │
    ├── materials.yaml                     # │ • Game data files           │
    └── ship_volumes.yaml                  # │ • Mounted for all tests     │
                                           # └─────────────────────────────┘
```

### Checkpoint Design Patterns

#### Pattern 1: Linear Progression
Each checkpoint adds features to the previous one.

```
checkpoint_1: Core functionality
checkpoint_2: + Persistence
checkpoint_3: + Error handling
checkpoint_4: + Performance optimization
```

#### Pattern 2: Independent Features
Each checkpoint tests a different aspect.

```
checkpoint_1: Data parsing
checkpoint_2: Data transformation
checkpoint_3: Data validation
checkpoint_4: Data export
```

#### Pattern 3: Increasing Complexity
Same functionality, harder requirements.

```
checkpoint_1: Handle simple cases
checkpoint_2: Handle edge cases
checkpoint_3: Handle error cases
checkpoint_4: Handle production scale
```

## File Roles Explained

### Root Configuration (`config.yaml`)

**Purpose**: Defines problem metadata and global settings.

**Required Fields:**
```yaml
name: problem_identifier              # Unique name
adapter:
  type: cli | api | playwright        # Execution environment
entry_file: module_name               # Entry point
loader_script: loader.py              # Loader file
loader_entrypoint: Loader             # Loader class
checkpoints:                          # Inline checkpoint definitions
  checkpoint_1:
    order: 1
    path: checkpoint_1
    groups:
      core:
        type: Core
    specification: spec.md
```

**Optional Fields:**
```yaml
description: "What this problem tests"
category: data-processing             # Problem category
difficulty: Easy | Medium | Hard
tags: [cli, parsing, json]            # Search tags
timeout: 30                           # Default timeout (seconds)
static_assets:                        # Shared files
  files: {path: files}
  data: {path: data}
```

### Checkpoint Entries (`config.yaml → checkpoints`)

**Purpose**: Describe each checkpoint inline without a separate `checkpoint_N/config.yaml`.

**Required Fields (per checkpoint):**
```yaml
checkpoints:
  checkpoint_1:
    order: 1                          # Execution order
    path: checkpoint_1                # Directory containing spec & cases
    groups:                           # At least one group
      core:
        type: Core | Error | Functionality | Regression
    specification: spec.md            # Spec file name
```

**Optional Fields:**
```yaml
checkpoints:
  checkpoint_1:
    timeout: 30                       # Default timeout for groups
    state: Core Tests                 # Dashboard label
    case_defaults: {memory: 512}      # Metadata merged into each case
    constant_files: [shared/config.json]
    groups:
      core:
        timeout: 20                   # Group-level override
        case_order: [case1, case2]    # Required for stateful API groups
        group_files: [shared/data.json]  # Copied into each case workspace
```

### Specification (`spec.md`)

**Purpose**: Tells the agent what to build for this checkpoint.

**Typical Structure:**
```markdown
# Checkpoint N: Feature Name

Brief description of what to build.

## Deliverables

What files/functionality to create.

## Requirements

- Requirement 1
- Requirement 2

## Examples

Input/output examples.

## Notes

Additional context, edge cases, etc.
```

### Loader (`loader.py`)

**Purpose**: Discovers test cases and transforms them into Case objects.

**Responsibilities:**
1. Find test case files/directories
2. Read and parse case definitions
3. Create `Case` objects (CLICase, APICase, etc.)
4. Create `Expected` objects (CLIResult, APIResult, etc.)
5. Yield `(case, expected)` tuples

### Verifier (`verifier.py`)

**Purpose**: Validates agent outputs against expected results.

**Responsibilities:**
1. Compare actual vs expected outputs
2. Score each comparison (0.0 to 1.0)
3. Provide detailed diff information
4. Return `VerificationResult` dict

### Test Case Files

**CLI Case (`case.yaml` in directory):**
```yaml
arguments: --input data.csv --output result.txt
input_files:
  - path: data.csv
    content: "col1,col2\n1,2"
    file_type: csv
```

**API Case (`case_name.yaml`):**
```yaml
case:
  method: POST
  path: /v1/users
  headers:
    content-type: application/json
  body:
    name: Alice
expected:
  status_code: 201
  output:
    id: "{{dynamic}}"
    name: Alice
```

## Naming Conventions

### Directory Names

```
problems/                          # Always plural
├── my_problem/                    # Snake_case, descriptive
│   ├── checkpoint_1/              # Always checkpoint_N (N = 1, 2, 3...)
│   │   ├── core/                  # Lowercase group names
│   │   ├── errors/
│   │   └── functionality/
│   └── checkpoint_2/
└── another_problem/
```

### File Names

```
config.yaml                        # Always config.yaml
spec.md                            # Always spec.md
loader.py                          # Always loader.py
verifier.py                        # Always verifier.py
```

### Test Case Names

**CLI (directories):**
```
core/
├── basic_test/                    # Snake_case, descriptive
├── edge_case_empty_input/         # Explain what's being tested
└── error_invalid_format/
```

**API (files):**
```
functionality/
├── create_user.yaml               # Verb + noun
├── get_user_by_id.yaml            # Action being tested
├── update_user_email.yaml         # Specific feature
└── delete_user.yaml
```

### Group Names (Standard)

```yaml
groups:
  core:                            # Happy path tests
  errors:                          # Error handling
  functionality:                   # Feature variations
  spec_cases:                      # Spec compliance
  regression:                      # Regression tests
  hidden:                          # Hidden from agents
  edge_cases:                      # Edge cases
```

## Common Patterns

### Pattern: Shared Test Setup (group_files)

```yaml
# config.yaml → checkpoints.checkpoint_1.groups.functionality
checkpoints:
  checkpoint_1:
    groups:
      functionality:
        group_files:
          - shared/base_config.json  # Copied to workspace for every case
          - shared/test_data.csv     # All cases in this group get these files
```

### Pattern: Static Assets for All Tests

```yaml
# config.yaml (root)
static_assets:
  reference_db:
    path: data/reference.db        # Mount problems/my_problem/data/reference.db

# In test case, reference as:
arguments: --database {{static:reference_db}}/users.db
```

### Pattern: Multiple Input Files (CLI)

```
core/
└── multi_file_merge/
    ├── case.yaml                  # Lists all inputs
    │   arguments: --merge a.json b.json c.json
    │   input_files:
    │     - {path: a.json, content: "..."}
    │     - {path: b.json, content: "..."}
    │     - {path: c.json, content: "..."}
    └── expected.json              # Expected merged output
```

### Pattern: Hidden Test Cases

```
checkpoint_3/
├── core/                          # Shown to agent
│   ├── basic_test/
│   └── advanced_test/
└── hidden/                        # NOT shown to agent
    └── holdout_test/              # Prevents overfitting to visible cases
```

## Visual Summary

```
┌─────────────────────────────────────────────────────────────┐
│ PROBLEM (problems/my_problem/)                              │
│                                                              │
│  ┌──────────────┐  ┌───────────┐  ┌───────────┐            │
│  │ config.yaml  │  │ loader.py │  │verifier.py│            │
│  └──────────────┘  └───────────┘  └───────────┘            │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ CHECKPOINT 1 (checkpoint_1/)                        │   │
│  │                                                      │   │
│  │  ┌────────────┐                                     │   │
│  │  │  spec.md   │                                     │   │
│  │  └────────────┘                                     │   │
│  │                                                      │   │
│  │  ┌──────────────────┐  ┌──────────────────┐         │   │
│  │  │ GROUP: core      │  │ GROUP: errors    │         │   │
│  │  │                  │  │                  │         │   │
│  │  │  ┌────────────┐  │  │  ┌────────────┐ │         │   │
│  │  │  │ Case 1     │  │  │  │ Error 1    │ │         │   │
│  │  │  │ - case.yaml│  │  │  │ - case.yaml│ │         │   │
│  │  │  │ - expected │  │  │  │ - expected │ │         │   │
│  │  │  └────────────┘  │  │  └────────────┘ │         │   │
│  │  │                  │  │                  │         │   │
│  │  │  ┌────────────┐  │  │  ┌────────────┐ │         │   │
│  │  │  │ Case 2     │  │  │  │ Error 2    │ │         │   │
│  │  │  └────────────┘  │  │  └────────────┘ │         │   │
│  │  └──────────────────┘  └──────────────────┘         │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ CHECKPOINT 2 (checkpoint_2/)                        │   │
│  │   ... same structure ...                            │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ STATIC ASSETS (files/)                              │   │
│  │   - shared_data.csv                                 │   │
│  │   - reference.db                                    │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

## Next Steps

- **[Quick Reference](quick-reference.md)** - Cheat sheet for common tasks
- **[Config Schema](config-schema.md)** - Complete field reference
- **[Test Cases Guide](test-cases.md)** - How to write effective tests
- **[Examples](examples/)** - Annotated walkthroughs of real problems
