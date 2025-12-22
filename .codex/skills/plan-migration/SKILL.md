---
name: plan-migration
description: Analyze SCBench problems before migration and create a migrate.md plan. Use BEFORE migrate-tests to understand the problem structure, map groups to types, identify regression handling, and document special cases. Invoke with /plan-migration <problem>.
---

# Plan Migration for SCBench Problems

Analyze a problem's existing loader/verifier/adapter structure and create a `migrate.md` file documenting the migration plan. **Run this BEFORE using migrate-tests.**

## Usage

```
/plan-migration <problem_name>
```

---

## Step-by-Step Execution

### Step 1: Read the core files (in this order)

```bash
# 1. Config - understand structure, checkpoints, static assets
cat problems/<problem>/config.yaml

# 2. Loader - understand how test cases are loaded
cat problems/<problem>/loader.py

# 3. Verifier - understand validation logic
cat problems/<problem>/verifier.py
```

### Step 2: Explore checkpoint directories

```bash
# List all checkpoints
ls -la problems/<problem>/checkpoint_*/

# For each checkpoint, examine:
# - spec.md (what's being tested)
# - solution/ (reference implementation)
# - case directories (core/, hidden/, errors/, etc.)
ls -la problems/<problem>/checkpoint_1/
cat problems/<problem>/checkpoint_1/spec.md
ls -la problems/<problem>/checkpoint_1/solution/
```

### Step 3: Examine case file structure

```bash
# Look at a sample case file to understand format
cat problems/<problem>/checkpoint_1/core/case_1.yaml
cat problems/<problem>/checkpoint_1/core/expected_1.jsonl  # if exists
```

### Step 4: Check for static assets

```bash
# Look for static_assets in config.yaml
# Look for assets/ or files/ directories
ls -la problems/<problem>/assets/
ls -la problems/<problem>/files/
```

### Step 5: Create migrate.md and present to user

Write `problems/<problem>/migrate.md` with your findings, then show the user and ask for confirmation.

---

## What to Analyze

### 1. Adapter Type
- CLI (command line), API (HTTP server), or Playwright (browser)
- How arguments are constructed
- Input file handling (static assets, dynamic files)

### 2. Group Mappings
For each checkpoint, identify:
- **Core** tests - Must pass, unmarked in pytest
- **Functionality/Hidden** tests - Optional, use `@pytest.mark.functionality`
- **Error** tests - Expected failures, use `@pytest.mark.error`

### 3. Regression Configuration
From `config.yaml`, note:
- Which checkpoints include regressions from prior checkpoints
- Any `include_prior_tests: false` scenarios (breaking changes)

### 4. Verifier Logic
From `verifier.py`, document:
- Custom verification logic that needs to be translated
- Field stripping for regression tests
- Tolerance checks (approximate matching)
- Partial/subset verification

### 5. Loader Complexity
From `loader.py`, identify:
- Static asset references (`{{static:name}}`)
- Dynamic file generation
- CaseStore usage (stateful tests)
- Template rendering
- Special input file processing

### 6. Case Inventory (CRITICAL)
**Every case loaded by the loader MUST become a test in the new pytest suite.**

Understand how the loader discovers cases:
- Does it glob for files? What pattern?
- Does it read a manifest or index file?
- Does it generate cases programmatically?
- How many cases does each group yield?

Document the exact case count per checkpoint/group. During migration, each case becomes either:
- An explicit test function (`def test_case_name(...)`)
- A parametrized test (`@pytest.mark.parametrize(...)`)

**No cases can be lost in migration.**

### 7. Solution Files
From `checkpoint_N/solution/`, examine:
- The reference implementation for each checkpoint
- How the solution evolves across checkpoints
- Edge case handling patterns
- Output format (JSON, JSONL, plain text, etc.)

### 8. Breaking Changes
Identify checkpoints that fundamentally change behavior:
- Prior tests should NOT run as regressions
- Need `include_prior_tests: false` in new config
- May require manual regression tests with modified expectations

---

## migrate.md Template

Create `problems/<problem>/migrate.md` with this structure:

```markdown
# Migration Plan: <problem_name>

## Overview
- **Adapter type**: CLI | API | Playwright
- **Checkpoints**: N
- **Has loader.py**: Yes/No
- **Has verifier.py**: Yes/No
- **Static assets**: List any in config.yaml

## Checkpoint Summary

| Checkpoint | Core | Functionality | Error | Regressions From |
|------------|------|---------------|-------|------------------|
| 1          | N    | N             | N     | -                |
| 2          | N    | N             | N     | 1                |
| ...        |      |               |       |                  |

## Group to Type Mapping

### checkpoint_1
- `core/` → Core (unmarked)
- `hidden/` → Functionality (`@pytest.mark.functionality`)
- `errors/` → Error (`@pytest.mark.error`)

### checkpoint_2
...

## Case Inventory

**Every case MUST become a test. No cases can be lost.**

| Checkpoint | Group | Case Count | Test Strategy |
|------------|-------|------------|---------------|
| 1          | core  | N          | parametrized / explicit |
| 1          | hidden| N          | parametrized / explicit |
| ...        |       |            |               |

### How Cases Are Discovered
<describe the loader's case discovery mechanism>

## Loader Analysis

### Input File Handling
<describe how input files are loaded and processed>

### Static Assets
<list static assets and how they're referenced>

### Special Processing
<any dynamic file generation, template rendering, etc.>

## Solution Analysis

### Reference Implementation
<location of solution files for each checkpoint>

### Key Implementation Details
<notable patterns in how the solution handles cases>

## Verifier Analysis

### Verification Logic
<describe the main verification approach>

### Regression Handling
<any special handling for regression tests, field stripping, etc.>

### Tolerance/Approximate Matching
<any fuzzy matching or tolerance checks>

## Breaking Changes

<list any checkpoints that break prior functionality>

- **checkpoint_N**: <description of breaking change>
  - Prior tests affected: <list>
  - Recommendation: `include_prior_tests: false` OR manual regression tests

## Migration Notes

### Fixtures Needed
- `entrypoint_argv` (standard)
- `checkpoint_name` (standard)
- <any problem-specific fixtures>

### Test Data
<how to translate case.yaml + expected.jsonl to inline test data>

### Edge Cases
<any tricky cases to watch for during migration>
```

---

## Example Analysis

For `file_backup`:

```markdown
# Migration Plan: file_backup

## Overview
- **Adapter type**: CLI
- **Checkpoints**: 4
- **Has loader.py**: Yes (complex)
- **Has verifier.py**: Yes (JSONL + regression field handling)
- **Static assets**: `files` directory

## Checkpoint Summary

| Checkpoint | Core | Functionality | Error | Regressions From |
|------------|------|---------------|-------|------------------|
| 1          | Y    | Y             | Y     | -                |
| 2          | Y    | Y             | -     | 1                |
| 3          | Y    | Y             | -     | 1, 2             |
| 4          | Y    | Y             | -     | 1, 2, 3          |

## Verifier Analysis

### Regression Handling
Verifier strips fields from checkpoint 1/2 regression tests:
- `files_skipped_unchanged`
- `dest_state_files`

These fields were added in checkpoint 3. When running checkpoint_1 tests
as regressions for checkpoint_3+, these fields must be ignored.

**Migration approach**: Use checkpoint-aware assertions:
```python
def test_job_completion(entrypoint_argv, checkpoint_name):
    # ... run command ...
    if checkpoint_name >= "checkpoint_3":
        assert "files_skipped_unchanged" in event
    # Don't assert on these fields for checkpoint_1/2 regressions
```
```

---

## After Creating migrate.md

1. **Show the user** the plan and ask for confirmation
2. **Get clarification** on any ambiguous areas
3. **Proceed to migrate-tests** once approved

The migrate.md file serves as documentation during and after the migration.

---

## Verification Checklist

**DO NOT CONSIDER COMPLETE UNTIL:**

- [ ] `config.yaml` fully analyzed (checkpoints, static_assets, adapter type)
- [ ] All checkpoint directories examined
- [ ] `loader.py` logic fully understood (how cases are discovered)
- [ ] `verifier.py` logic documented
- [ ] Solution files in `checkpoint_N/solution/` reviewed
- [ ] Group-to-type mappings confirmed for all checkpoints
- [ ] **Case inventory complete** - exact count per checkpoint/group documented
- [ ] Regression configuration documented
- [ ] Breaking changes identified (if any)
- [ ] `migrate.md` created with all sections filled
- [ ] Plan presented to user for confirmation

---

## Optional: Validate Understanding

Run eval-snapshot on an existing checkpoint to see the current behavior:

```bash
slop-code -v eval-snapshot problems/<problem>/checkpoint_1/solution \
    -p <problem> -o /tmp/plan-check -c 1 \
    -e configs/environments/docker-python3.12-uv.yaml --json

# Check results
jq '.results.summary' /tmp/plan-check/evaluation/report.json
```

