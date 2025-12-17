---
version: 1.0
last_updated: 2025-11-06
---

# Quick Reference: Problem Authoring Cheat Sheet

One-page reference for creating evaluation problems in Slop Code.

## Minimal Files Required

Every problem needs exactly 4 things:

1. **`config.yaml`** - Problem metadata & adapter configuration
2. **`loader.py`** - Discovers test cases (can copy from examples)
3. **`verifier.py`** - Validates outputs (can copy from examples)
4. **`checkpoint_N/`** - At least one checkpoint with spec & test cases

## 5-Step Problem Creation

```bash
# 1. Create structure
mkdir -p problems/my_problem/checkpoint_1/core

# 2. Root config (CLI example)
cat > problems/my_problem/config.yaml << 'EOF'
name: my_problem
adapter:
  type: cli                      # or: api, playwright
  tracked_files: ["output.txt"]  # Files to capture
entry_file: solution             # Entry point module
loader_script: loader.py
loader_entrypoint: Loader
checkpoints:
  checkpoint_1:
    order: 1
    path: checkpoint_1
    groups:
      core:
        type: Core
        timeout: 30
    specification: spec.md
    state: Core Tests
EOF

# 3. Copy templates
cp examples/yaml_joiner/problem/loader.py problems/my_problem/
cp examples/yaml_joiner/problem/verifier.py problems/my_problem/

# 4. Write spec and test cases
```

## Directory Tree Templates

### CLI Problem (Directory-Based Cases)

```
problems/your_problem/
├── config.yaml              # name, adapter, loader, checkpoints
├── loader.py                # Load cases from directories
├── verifier.py              # Compare actual vs expected
├── checkpoint_1/
│   ├── spec.md              # What to build
│   └── core/                # Test group
│       ├── basic_test/      # One directory per case
│       │   ├── case.yaml    # arguments + input_files
│       │   └── expected.txt # Expected output
│       └── advanced_test/
│           ├── case.yaml
│           └── expected.jsonl
└── files/                   # Optional: static assets
    └── reference_data.csv
```

**Case Structure (case.yaml):**
```yaml
arguments: --input data.csv --output result.txt
input_files:
  - content: "col1,col2\n1,2\n3,4"
    file_type: csv
    path: data.csv
```

### API Problem (YAML-Based Cases)

```
problems/your_problem/
├── config.yaml              # name, adapter, loader, checkpoints
├── loader.py                # Load cases from YAML files
├── verifier.py              # Validate API responses
└── checkpoint_1/
    ├── spec.md              # What to build
    ├── core/                # Test group
    │   ├── create.yaml      # POST request + expected
    │   ├── get.yaml         # GET request + expected
    │   └── update.yaml      # PATCH request + expected
    └── errors/              # Error handling
        ├── invalid.yaml
        └── not_found.yaml
```

**Case Structure (create.yaml):**
```yaml
case:
  method: POST
  path: /v1/users
  headers:
    content-type: application/json
  body:
    name: Alice
    email: alice@example.com
expected:
  status_code: 201
  output:
    id: "{{dynamic}}"        # Or use JSON schema
    name: Alice
```

## Common Config Fields

### Root config.yaml

| Field | Required | Description | Example |
|-------|----------|-------------|---------|
| `name` | ✅ | Problem identifier | `file_backup` |
| `adapter.type` | ✅ | `cli`, `api`, `playwright` | `cli` |
| `adapter.tracked_files` | CLI | Files to capture | `["output.jsonl"]` |
| `adapter.address` | API | Server host | `127.0.0.1` |
| `adapter.health_path` | API | Health check endpoint | `/healthz` |
| `entry_file` | ✅ | Entry point module | `backup_scheduler` |
| `loader_script` | ✅ | Loader file | `loader.py` |
| `loader_entrypoint` | ✅ | Loader class | `Loader` |
| `checkpoints` | ✅ | List of checkpoints | `[checkpoint_1, checkpoint_2]` |
| `static_assets` |  | Shared files | `{files: {path: files}}` |
| `timeout` |  | Default timeout (s) | `30` |

### Checkpoint Configuration (Inline)

*Note: Checkpoints are configured inline in the root `config.yaml` under `checkpoints.checkpoint_N`*

| Field | Required | Description | Example |
|-------|----------|-------------|---------|
| `groups` | ✅ | Test groups | See below |
| `specification` | ✅ | Spec file | `spec.md` |
| `timeout` |  | Default timeout | `20` |

**Group Definition:**
```yaml
groups:
  core:
    type: Core              # Core, Error, Functionality, Regression
    timeout: 30             # Override default
    case_order:             # For API: explicit ordering
      - create_resource
      - get_resource
      - update_resource
    group_files:            # Shared fixtures
      - shared/common.json
```

## Adapter Types Quick Guide

| Type | Use For | Test Cases | Entry Point |
|------|---------|------------|-------------|
| **CLI** | Command-line tools | Directories with `case.yaml` + expected files | Python module or script |
| **API** | REST APIs | YAML files with request/response | Server module with startup |
| **Playwright** | Web UIs | Playwright scripts | Web server |

## Group Types

| Type | Purpose | Example Cases |
|------|---------|---------------|
| `Core` | Happy path functionality | Valid inputs, basic features |
| `Error` | Error handling | Invalid inputs, edge cases |
| `Functionality` | Feature variations | Optional features, modes |
| `Regression` | Prevent regressions | Previously broken cases |
| `Hidden` | Not shown to agents | Held-out test cases |

## Static Assets vs Group Files

```yaml
# Root config.yaml - Static Assets (large shared data)
static_assets:
  files:
    path: files             # Mount problems/my_problem/files/
  sde_dir:
    path: data/sde          # Mount problems/my_problem/data/sde/

# Checkpoint config.yaml - Group Files (small fixtures)
groups:
  core:
    group_files:
      - shared/base.json    # checkpoint_1/core/shared/base.json
```

**In test cases, reference as:**
```yaml
# Static asset placeholder
arguments: --data-dir {{static:sde_dir}}

# Group file is just copied into workspace
# (no special syntax needed)
```

## Regression Testing

Automatically import test cases from previous checkpoints:

### Basic Import
```yaml
# checkpoint_2/config.yaml
regressions:
  - checkpoint: checkpoint_1
    groups: [core, errors]     # Import specific groups
```

### Import All Prior Checkpoints
```yaml
# checkpoint_5/config.yaml
regressions:
  - checkpoints: "*"           # All checkpoints before this one
    type_filter: Core          # Only Core groups
```

### Multiple Sources with Filters
```yaml
regressions:
  # Import all Core tests
  - checkpoints: "*"
    type_filter: Core

  # Import specific groups from checkpoint_2
  - checkpoint: checkpoint_2
    groups: [bug_fixes]
    name_template: "critical_{group}"

  # Import everything except slow tests
  - checkpoint: checkpoint_3
    exclude: [slow_tests, experimental]
```

### Regression Fields

| Field | Description | Example |
|-------|-------------|---------|
| `checkpoint` | Single checkpoint | `checkpoint_1` |
| `checkpoints` | Multiple/wildcard | `["checkpoint_1", "checkpoint_2"]` or `"*"` |
| `groups` | Groups to import | `[core, errors]` (empty = all) |
| `type_filter` | Filter by type | `Core`, `Error`, `Functionality` |
| `exclude` | Skip these groups | `[hidden, slow]` |
| `name_template` | Custom naming | `"v{idx}_{group}"` |

### How It Works

1. Regression specs expand into groups with `type: Regression`
2. Groups reference original via `original_checkpoint` and `original_group`
3. Loaders automatically resolve to original test location
4. No special handling needed in loader or verifier

## Loader Template (Copy & Modify)

```python
from slop_code.evaluation.loaders import BaseLoader, CaseStore, helpers
from slop_code.evaluation.adapters import CLICase, CLIResult

class Loader(BaseLoader):
    def initialize_store(self):
        return {}  # Or custom store for stateful API tests

    def __call__(self, group, store):
        group_dir = helpers.get_group_path(group, self.problem, self.checkpoint)

        # Directory-based cases
        for case_dir in helpers.discover_dir_cases(group, group_dir):
            case, expected = self.load_case_dir(case_dir, group)
            yield case, expected

        # OR: File-based cases
        for case_file in sorted(group_dir.glob("*.yaml")):
            case, expected = self.load_case_file(case_file, group)
            yield case, expected
```

## Verifier Template (Copy & Modify)

```python
from slop_code.evaluation.verifiers import verifiers, parsers

class Verifier:
    def __init__(self, checkpoint_config):
        self.checkpoint_config = checkpoint_config

    def __call__(self, group_name, case_name, actual, expected):
        # Status code (always verify)
        results = {
            "status_code": verifiers.matches_status_code(
                actual.status_code, expected.status_code, weight=0.2
            )
        }

        # Output comparison (use deepdiff for everything!)
        results["output"] = verifiers.deepdiff_verify(
            actual.output, expected.output, weight=0.8
        )

        return results
```

## Testing Commands

```bash
# Run agent on problem
slop-code run \
  --agent configs/agents/haiku-4.5-claude-code.yaml \
  --environment configs/environments/docker-python3.12-uv.yaml \
  --problem my_problem

# Evaluate single checkpoint snapshot
uv run python -m slop_code.entrypoints.cli eval-snapshot \
  --problem-name my_problem \
  --checkpoint-num 1 \
  --env-config configs/environments/docker-python3.12-uv.yaml \
  --save-dir outputs/my_problem_eval \
  outputs/my_problem/checkpoint_1/snapshot

# Launch dashboard
uv run python -m slop_code.visualization.app outputs/
```

### Debug Individual Test Cases

Use `tools run-case` for rapid iteration when developing loaders and verifiers:

```bash
# Run all cases in a checkpoint
slop-code tools run-case \
  -s outputs/my_problem/checkpoint_1/snapshot \
  -p my_problem \
  -c 1 \
  -e configs/environments/docker-python3.12-uv.yaml

# Run only a specific group
slop-code tools run-case \
  -s outputs/my_problem/checkpoint_1/snapshot \
  -p my_problem -c 1 \
  -e configs/environments/docker-python3.12-uv.yaml \
  --group core

# Run a single case with full debug output
slop-code tools run-case \
  -s outputs/my_problem/checkpoint_1/snapshot \
  -p my_problem -c 1 \
  -e configs/environments/docker-python3.12-uv.yaml \
  --case my_test_case \
  --full

# Combine with jq for filtering
slop-code tools run-case ... | jq '.[] | select(.passed == false)'
```

**Tips:**
- Much faster than running the full evaluation pipeline
- Use `--full` to see detailed diffs when debugging verification failures
- Glob patterns work: `--group "error*"` or `--case "test_*"`
- JSON output enables scripting and CI integration

## Common Issues

| Issue | Solution |
|-------|----------|
| Cases not loading | Check `case_order` matches filenames (API) or directory names (CLI) |
| Wrong adapter type | CLI = directories/files, API = HTTP, Playwright = browser |
| Verification fails | Use `verifiers.deepdiff_verify()` instead of custom comparison |
| Static assets missing | Check `static_assets` path is relative to problem root |
| Case order wrong | Add `case_order` list to group config (required for stateful APIs) |

## Essential Helper Functions

```python
# Loaders
helpers.get_group_path(group, problem, checkpoint)  # Get group directory
helpers.discover_dir_cases(group, group_dir)        # Find case directories
helpers.get_files_from_globs(dir, ["*.yaml"])       # Get files by pattern

# Verifiers
verifiers.deepdiff_verify(actual, expected, weight=0.8)  # Use for ALL comparisons
verifiers.matches_status_code(actual, expected, weight=0.2)
verifiers.jsonschema_verify(actual, schema)
parsers.parse_json(content)                          # Parse JSON safely
parsers.parse_yaml_file(result, "file.yaml")         # Parse YAML from result
```

## Next Steps

- **Detailed guide:** [Problem Authoring](../guides/problem-authoring.md)
- **Loader/Verifier details:** [Creating Loaders and Verifiers](../guides/creating-loaders-and-verifiers.md)
- **Visual structure:** [Problem Structure Guide](structure.md)
- **Complete reference:** [Config Schema](config-schema.md)
