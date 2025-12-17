---
version: 1.0
last_updated: 2025-12-08
---

# Regression Testing Guide

This guide explains how to implement regression testing in Slop Code problems, covering both manual regression tests and automated test importing.

## Purpose

Regression groups serve two distinct purposes:

1. **Manual Regression Tests**: Tests you write for specific bugs
2. **Automated Regression Import**: Tests imported from previous checkpoints

**Goal**: Prevent previously fixed bugs from reappearing and ensure backward compatibility across checkpoints.

## Manual Regression Tests

Create explicit regression groups to test specific bugs or edge cases that have caused issues in the past.

**What to test:**
- Specific bug scenarios
- Edge cases that broke before
- Interactions that failed
- Performance regressions

**Example cases:**
```
regression/
├── issue_42_timezone_handling/
├── issue_73_null_merge/
├── issue_105_race_condition/
└── issue_120_memory_leak/
```

**Configuration:**
```yaml
groups:
  regression:
    type: Regression
    timeout: 30
```

## Automated Regression Import

The framework can automatically import tests from previous checkpoints as regression groups. This ensures that as an agent progresses through checkpoints, it doesn't break functionality it built earlier.

**How it works:**
1. Define `regressions` field in checkpoint config
2. System imports specified groups from earlier checkpoints
3. Creates new groups with `type: Regression`
4. Tracks origin via `original_checkpoint` and `original_group` fields

### Import from Previous Checkpoint

```yaml
# In root config.yaml under checkpoints.checkpoint_3
regressions:
  - checkpoint: checkpoint_1
    groups: [core]
  - checkpoint: checkpoint_2
    type_filter: Core
```

This creates:
- `checkpoint_1_core` - Core tests from checkpoint 1
- All Core groups from checkpoint 2

### Advanced Import Pattern

```yaml
# In root config.yaml under checkpoints.checkpoint_5
regressions:
  # Import all core tests from all prior checkpoints
  - checkpoints: "*"
    type_filter: Core
    name_template: "must_work_{checkpoint}_{group}"

  # Import specific bug fixes
  - checkpoint: checkpoint_3
    groups: [security_fixes]
    exclude: [experimental]
```

### Regression Group Metadata

When tests are imported, the framework generates a group configuration like this:

```yaml
# Auto-generated regression group
groups:
  checkpoint_1_core:
    type: Regression              # Always set to Regression
    original_checkpoint: checkpoint_1  # Source checkpoint
    original_group: core              # Source group name
    timeout: 30                       # Inherited from source
    # Other fields from source group
```

### Key Differences from Regular Groups

- Test cases remain in their original location on disk
- Loader uses `original_checkpoint` and `original_group` to find test files
- Group name follows a generated pattern (customizable via `name_template`)
- Group type is always `Regression` regardless of the source group's type

## When to Use

- **Manual**: Add tests when bugs are discovered and fixed during development or evaluation.
- **Automated**: Import core functionality from earlier checkpoints to ensure the solution remains backward compatible as it evolves.
