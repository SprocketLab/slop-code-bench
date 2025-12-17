---
version: 1.0
last_updated: 2025-11-18
---

# Regression Testing Guide

This guide covers how to use the Slop Code regression testing system to ensure that functionality verified in earlier checkpoints continues to work in later ones.

## Table of Contents

- [Overview](#overview)
- [When to Use Regression Testing](#when-to-use-regression-testing)
- [Basic Usage](#basic-usage)
- [Advanced Patterns](#advanced-patterns)
- [Integration with Loaders and Verifiers](#integration-with-loaders-and-verifiers)
- [Best Practices](#best-practices)
- [Troubleshooting](#troubleshooting)

## Overview

The regression testing system in Slop Code allows you to automatically import test cases from previous checkpoints into later ones. This ensures that:

- **Core functionality doesn't break** as new features are added
- **Bug fixes remain effective** across checkpoint iterations
- **Progressive requirements** are properly tested
- **Test coverage accumulates** through the problem progression

### How It Works

1. **Define regression specs** in a checkpoint's configuration
2. **System expands specs** into regression groups during problem loading
3. **Regression groups reference** the original checkpoint/group for test cases
4. **Loaders resolve paths** to the original test files
5. **Tests execute** as if they were part of the current checkpoint

## When to Use Regression Testing

### Progressive Feature Development

When checkpoints build on each other:
```yaml
# checkpoint_1: Basic CRUD operations
# checkpoint_2: Add filtering and sorting
# checkpoint_3: Add pagination and caching

# In checkpoint_3/config.yaml:
regressions:
  - checkpoints: "*"  # Import all tests from checkpoints 1 and 2
    type_filter: Core  # Only core functionality
```

### Bug Fix Validation

Ensure fixed bugs don't reappear:
```yaml
# checkpoint_2 fixed bugs from checkpoint_1
# checkpoint_3 should verify those fixes still work

# In checkpoint_3/config.yaml:
regressions:
  - checkpoint: checkpoint_2
    groups: [bug_fixes, errors]
```

### API Evolution

When APIs add new endpoints while maintaining backward compatibility:
```yaml
# checkpoint_4 adds v2 endpoints but v1 must still work

# In checkpoint_4/config.yaml:
regressions:
  - checkpoint: checkpoint_3
    groups: [v1_endpoints]
    name_template: "legacy_{group}"
```

## Basic Usage

### Simple Import from Previous Checkpoint

The most common pattern - import specific groups from the immediately prior checkpoint:

```yaml
# problems/my_problem/checkpoint_2/config.yaml
groups:
  core:
    type: Core
    timeout: 20
  new_features:
    type: Functionality

regressions:
  - checkpoint: checkpoint_1
    groups:
      - core
      - errors
```

This creates two additional groups in checkpoint_2:
- `checkpoint_1_core` - All core tests from checkpoint_1
- `checkpoint_1_errors` - All error tests from checkpoint_1

### Import All Groups

To import everything from a checkpoint:

```yaml
regressions:
  - checkpoint: checkpoint_1
    # No groups field means import all
```

### Import from Multiple Checkpoints

Import the same groups from multiple checkpoints:

```yaml
regressions:
  - checkpoints:
      - checkpoint_1
      - checkpoint_2
    groups:
      - core
```

This creates:
- `checkpoint_1_core`
- `checkpoint_2_core`

## Advanced Patterns

### Wildcard Import from All Prior Checkpoints

Import from all checkpoints that come before the current one:

```yaml
# In checkpoint_5/config.yaml
regressions:
  - checkpoints: "*"
    type_filter: Core
```

This automatically imports Core groups from checkpoints 1-4. As you add more checkpoints, they're automatically included.

### Type Filtering

Import only groups of a specific type:

```yaml
regressions:
  - checkpoints: "*"
    type_filter: Error  # Only import Error groups
```

Valid types: `Core`, `Error`, `Functionality`, `Regression`

### Exclusion Lists

Import all except specific groups:

```yaml
regressions:
  - checkpoint: checkpoint_1
    exclude:
      - experimental
      - deprecated
      - slow_tests
```

### Custom Naming Templates

Control how regression groups are named:

```yaml
regressions:
  - checkpoint: checkpoint_1
    groups: [core]
    name_template: "prev_{group}"  # Creates "prev_core"

  - checkpoints: "*"
    type_filter: Error
    name_template: "regression_{idx}_{checkpoint}_{group}"
    # Creates names like "regression_0_checkpoint_1_errors"
```

Template variables:
- `{checkpoint}` - Source checkpoint name
- `{group}` - Source group name
- `{idx}` - Index of the regression spec (0-based)

### Complex Multi-Spec Example

Combine multiple regression strategies:

```yaml
# checkpoint_5/config.yaml
regressions:
  # Import all core tests from all prior checkpoints
  - checkpoints: "*"
    type_filter: Core
    name_template: "legacy_{checkpoint}_{group}"

  # Import specific groups from checkpoint_4
  - checkpoint: checkpoint_4
    groups:
      - performance_tests
      - integration_tests
    name_template: "recent_{group}"

  # Import everything except hidden tests from checkpoints 2 and 3
  - checkpoints:
      - checkpoint_2
      - checkpoint_3
    exclude:
      - hidden
      - draft
```

## Integration with Loaders and Verifiers

### Loader Perspective

Loaders handle regression groups transparently using the `get_group_path` helper:

```python
from slop_code.evaluation.loaders import helpers, BaseLoader
from slop_code.evaluation.config import GroupConfig

class Loader(BaseLoader):
    def __call__(self, group: GroupConfig, store):
        # This automatically resolves regression groups to their source
        # self.problem and self.checkpoint are set in __init__
        group_path = helpers.get_group_path(group, self.problem, self.checkpoint)

        # Load cases from the resolved path
        for case_dir in group_path.iterdir():
            # Process test cases...
            pass
```

The helper checks if it's a regression group and returns the original path:
- Regular group: `/problems/my_problem/checkpoint_2/core/`
- Regression group: `/problems/my_problem/checkpoint_1/core/` (original location)

### Verifier Perspective

Verifiers typically don't need special handling for regression groups. They receive the same case/result data structure regardless of whether it's a regression test.

However, you can check if a case came from a regression group using its attributes:

```python
from slop_code.evaluation.adapters import GroupType

class Verifier:
    def __call__(self, group_name, case_name, actual, expected):
        # Cases have group_type, original_checkpoint, and original_group attributes
        # These are set automatically by the framework for regression groups
        is_regression = actual.group_type == GroupType.REGRESSION
        original_checkpoint = actual.original_checkpoint if is_regression else None
        original_group = actual.original_group if is_regression else None

        # Most verifiers don't need to check this - just verify normally
        # ...
```

## Best Practices

### 1. Progressive Accumulation

Start with core functionality and accumulate tests:

```yaml
# checkpoint_1: Basic features (10 tests)
# checkpoint_2: Imports checkpoint_1 + adds new (10 + 15 = 25 tests)
# checkpoint_3: Imports 1&2 + adds new (25 + 20 = 45 tests)
```

### 2. Selective Import

Don't blindly import everything - be selective:

```yaml
# GOOD: Import only what's relevant
regressions:
  - checkpoint: checkpoint_1
    groups: [core, critical_paths]
    exclude: [experimental]

# AVOID: Importing everything including redundant tests
regressions:
  - checkpoints: "*"  # May include duplicate/redundant tests
```

### 3. Clear Naming

Use descriptive naming templates when defaults aren't clear:

```yaml
# For versioned APIs
name_template: "v1_{group}"

# For backward compatibility
name_template: "compat_{checkpoint}_{group}"

# For accumulated tests
name_template: "accumulated_{group}_from_{checkpoint}"
```

### 4. Document Regression Strategy

Add comments explaining your regression strategy:

```yaml
# Import core functionality from all prior checkpoints to ensure
# backward compatibility as we add new features
regressions:
  - checkpoints: "*"
    type_filter: Core

# Also import specific bug fixes from checkpoint_2 that must not regress
  - checkpoint: checkpoint_2
    groups: [bug_fixes]
```

### 5. Performance Considerations

Large regression imports can slow evaluation. Consider:

- Using `type_filter` to limit imports
- Being specific with `groups` lists
- Using `exclude` for slow/redundant tests
- Setting appropriate timeouts for regression groups

### 6. Checkpoint Design

Design checkpoints with regression testing in mind:

- Keep core functionality in `Core` groups
- Separate new features into `Functionality` groups
- Put bug fixes in dedicated groups for easy import
- Use consistent group naming across checkpoints

## Troubleshooting

### Common Issues

#### "Regression references non-existent checkpoint"

```yaml
# Error: checkpoint_0 doesn't exist
regressions:
  - checkpoint: checkpoint_0  # Wrong checkpoint name
```

**Fix**: Verify checkpoint names match exactly

#### "Regression group not found in source checkpoint"

```yaml
# Error: checkpoint_1 has no group named 'advanced'
regressions:
  - checkpoint: checkpoint_1
    groups: [advanced]  # Group doesn't exist
```

**Fix**: Check available groups in the source checkpoint

#### Wildcard Returns No Groups

```yaml
# In checkpoint_1 (first checkpoint)
regressions:
  - checkpoints: "*"  # No prior checkpoints exist
```

**Fix**: Wildcards only match prior checkpoints (lower order number)

#### Name Collisions

```yaml
# Warning: Regression group name collision, overwriting
regressions:
  - checkpoint: checkpoint_1
    groups: [core]
  - checkpoint: checkpoint_2
    groups: [core]  # Both create "checkpoint_1_core" with default template
```

**Fix**: Use different `name_template` values or import in separate specs

### Debugging Tips

1. **Check generated groups**: Look at evaluation output to see which regression groups were created
2. **Verify paths**: Use logging to confirm regression groups resolve to correct paths
3. **Test incrementally**: Start with simple imports before complex patterns
4. **Review order**: Remember checkpoints are processed in order (can't import from future checkpoints)

## Examples from Real Problems

### trajectory_api Problem

This problem uses regression testing to ensure API compatibility:

```yaml
# checkpoint_5/config.yaml
regressions:
- checkpoints:
  - checkpoint_1
  - checkpoint_2
  - checkpoint_3
  - checkpoint_4
  groups:
  - spec_cases
```

This ensures all specification test cases from previous checkpoints still pass.

### Complex Progressive Problem

A hypothetical problem with extensive regression testing:

```yaml
# checkpoint_4/config.yaml - Final checkpoint
groups:
  core:
    type: Core
  advanced:
    type: Functionality
  performance:
    type: Functionality

regressions:
  # Ensure all core functionality still works
  - checkpoints: "*"
    type_filter: Core
    name_template: "stable_{checkpoint}_{group}"

  # Import critical bug fixes that must not regress
  - checkpoint: checkpoint_2
    groups: [security_fixes]
    name_template: "security_{group}"

  # Import integration tests from checkpoint_3
  - checkpoint: checkpoint_3
    groups: [integration]
    exclude: [slow_integration]  # Skip the slow ones
```

## Summary

The regression testing system is a powerful tool for ensuring problem quality and preventing functionality from breaking as checkpoints evolve. Key takeaways:

- **Use progressively**: Import tests from earlier checkpoints to later ones
- **Be selective**: Don't import everything - use filters and exclusions
- **Name clearly**: Use templates to create meaningful group names
- **Design thoughtfully**: Structure checkpoints with regression testing in mind
- **Document strategy**: Explain your regression approach in comments

With proper regression testing, you can confidently evolve problems while maintaining quality and preventing bugs from reappearing.