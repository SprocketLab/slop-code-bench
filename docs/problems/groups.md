---
version: 1.0
last_updated: 2025-11-06
---

# Test Group Organization Guide

This guide explains how to organize test cases into groups, with patterns for effective test suite design.

## Table of Contents

- [What is a Test Group?](#what-is-a-test-group)
- [Standard Group Types](#standard-group-types)
- [Group Organization Patterns](#group-organization-patterns)
- [Group Configuration](#group-configuration)
- [When to Create Custom Groups](#when-to-create-custom-groups)
- [Group Interaction](#group-interaction)
- [Common Mistakes](#common-mistakes)
- [Examples from Real Problems](#examples-from-real-problems)

## What is a Test Group?

A **test group** is a collection of related test cases within a checkpoint. Groups help organize tests by:

- **Purpose**: What aspect is being tested
- **Type**: Success vs error vs edge cases
- **Feature**: Which feature is being validated
- **Priority**: Critical vs optional functionality

**Key characteristics:**
- All cases in a group share configuration (timeout, type)
- Groups can have different execution orders (for APIs)
- Groups are evaluated independently
- Group types affect scoring and reporting

## Standard Group Types

The framework provides standard group types with semantic meaning:

### Core

**Purpose**: Primary functionality, happy path scenarios

**What to test:**
- Basic features working correctly
- Standard use cases
- Expected inputs and outputs
- Critical functionality

**Example cases:**
```
core/
├── basic_create/              # Simple creation
├── basic_read/                # Simple retrieval
├── basic_update/              # Simple modification
└── basic_delete/              # Simple deletion
```

**Configuration:**
```yaml
groups:
  core:
    type: Core
    timeout: 30
```

**When to use**: Most problems should have a `core` group with fundamental functionality.

### Error

**Purpose**: Error handling and validation

**What to test:**
- Invalid inputs
- Missing required fields
- Wrong data types
- Constraint violations
- Error message format
- Correct status codes

**Example cases:**
```
errors/
├── missing_required_field/
├── invalid_type/
├── out_of_range_value/
├── malformed_input/
└── constraint_violation/
```

**Configuration:**
```yaml
groups:
  errors:
    type: Error
    timeout: 20      # Usually faster than core tests
```

**When to use**: Every problem should have error cases (~30% of total tests).

### Functionality

**Purpose**: Advanced features, optional capabilities, feature variations

**What to test:**
- Optional features
- Different modes/flags
- Feature combinations
- Edge cases
- Alternative workflows

**Example cases:**
```
functionality/
├── feature_with_option_a/
├── feature_with_option_b/
├── combined_features/
├── alternative_workflow/
└── uncommon_scenario/
```

**Configuration:**
```yaml
groups:
  functionality:
    type: Functionality
    timeout: 40      # May be more complex
```

**When to use**: For features beyond basic CRUD, optional capabilities, or variations.

### Hidden

**Purpose**: Test cases not shown to agents (prevent overfitting)

**What to test:**
- Variations of visible tests
- Slightly different inputs
- Same logic, different data
- Integration scenarios
- Real-world complexity

**Example cases:**
```
hidden/
├── variant_of_core_test_1/
├── uncommon_combination/
└── realistic_scenario/
```

**Configuration:**
```yaml
groups:
  hidden:
    type: Hidden
    timeout: 30
```

**When to use**: Add 10-20% hidden tests to prevent agents from hardcoding solutions to visible tests.

**Important**: Hidden tests are NOT included in specs or shown during problem-solving.

### Regression

**Purpose**: Prevent previously fixed bugs from reappearing and ensure backward compatibility across checkpoints.

For detailed instructions on manual regression tests and automated test importing, see the **[Regression Testing Guide](regression.md)**.

### Custom Types

You can define custom group types for domain-specific organization:

**Examples:**
- `Performance`: Performance-critical scenarios
- `Integration`: Multi-component interactions
- `Security`: Security-focused tests
- `Compliance`: Regulatory requirements
- `Compatibility`: Backwards compatibility

```yaml
groups:
  performance:
    type: Performance
    timeout: 60      # Longer for performance tests

  security:
    type: Security
    timeout: 30
```

## Group Organization Patterns

### Pattern 1: Standard Three-Group Setup

**Most common** for straightforward problems:

```yaml
groups:
  core:                        # Happy path (60%)
    type: Core
    timeout: 30

  errors:                      # Error handling (30%)
    type: Error
    timeout: 20

  functionality:               # Advanced features (10%)
    type: Functionality
    timeout: 40
```

**Example cases:**
```
checkpoint_1/
├── core/
│   ├── basic_operation_1/
│   ├── basic_operation_2/
│   └── basic_operation_3/
├── errors/
│   ├── invalid_input_1/
│   ├── invalid_input_2/
│   └── missing_field/
└── functionality/
    ├── optional_feature/
    └── advanced_mode/
```

**Use when:**
- Standard CRUD operations
- Clear success/error division
- Few advanced features

### Pattern 2: Feature-Based Groups

Organize by feature area:

```yaml
groups:
  user_management:
    type: Core

  data_operations:
    type: Core

  authentication:
    type: Core

  errors:
    type: Error
```

**Example cases:**
```
checkpoint_1/
├── user_management/
│   ├── create_user/
│   ├── update_user/
│   └── delete_user/
├── data_operations/
│   ├── import_data/
│   └── export_data/
├── authentication/
│   ├── login/
│   └── logout/
└── errors/
    ├── user_not_found/
    └── invalid_credentials/
```

**Use when:**
- Multiple distinct features
- Features are independent
- Want to measure per-feature success

### Pattern 3: Spec Compliance Split

Separate spec compliance from advanced functionality:

```yaml
groups:
  spec_cases:                  # Basic spec requirements
    type: Core
    case_order:
      - create_item
      - get_item
      - list_items

  spec_errors:                 # Spec-defined errors
    type: Error
    case_order:
      - not_found
      - bad_request

  functionality:               # Beyond the spec
    type: Functionality
    case_order:
      - pagination
      - filtering
      - sorting
```

**Use when:**
- Following a formal specification
- Want to distinguish spec vs extras
- Clear separation of requirements

### Pattern 4: Progressive Complexity

Groups increase in complexity:

```yaml
groups:
  basic:
    type: Core
    timeout: 20              # Simple, fast

  intermediate:
    type: Core
    timeout: 40              # More complex

  advanced:
    type: Core
    timeout: 60              # Complex scenarios

  errors:
    type: Error
    timeout: 20
```

**Example cases:**
```
checkpoint_1/
├── basic/
│   ├── single_item/
│   └── two_items/
├── intermediate/
│   ├── ten_items/
│   └── with_filtering/
├── advanced/
│   ├── hundred_items/
│   ├── complex_query/
│   └── edge_cases/
└── errors/
    └── invalid_input/
```

**Use when:**
- Testing scalability
- Gradual difficulty increase
- Want to see where agents struggle

### Pattern 5: Workflow-Based Groups

Organize by user workflows:

```yaml
groups:
  onboarding_workflow:
    type: Core
    case_order:
      - signup
      - verify_email
      - complete_profile

  daily_workflow:
    type: Core
    case_order:
      - login
      - create_post
      - logout

  admin_workflow:
    type: Functionality
    case_order:
      - admin_login
      - ban_user
      - view_logs
```

**Use when:**
- Testing end-to-end scenarios
- Workflows are distinct
- Integration testing

## Group Configuration

### Basic Configuration

```yaml
groups:
  group_name:
    type: Core | Error | Functionality | Hidden | Regression | Custom
    timeout: 30              # Optional: Override default timeout
```

### Advanced Configuration

#### Case Order (API Only)

**Required for stateful API tests:**

```yaml
groups:
  core:
    type: Core
    case_order:              # Explicit execution order
      - create_resource
      - get_resource
      - update_resource
      - delete_resource
```

**Rules:**
- Must list ALL test case files
- Cases run in exact order listed
- Later cases can depend on earlier state

#### Group Files

Share fixtures across all cases in group:

```yaml
groups:
  functionality:
    type: Functionality
    group_files:
      - shared/base_config.json     # Copied to workspace
      - fixtures/test_data.csv      # Available to all cases
```

**Use when:**
- Multiple cases need same setup data
- Reduces duplication in case definitions
- Shared configurations

**Path resolution**: Relative to `checkpoint_N/<group_name>/`

#### Timeout Hierarchy

```yaml
# Root config.yaml
timeout: 30                  # Default for all groups

checkpoints:
  checkpoint_1:
    timeout: 25              # Override for this checkpoint
    groups:
      core:
        timeout: 20          # Override for this group
      performance:
        timeout: 120         # Much longer for performance tests
```

**Priority**: Group > Checkpoint > Problem > Default (30s)

## When to Create Custom Groups

### Create a New Group When:

#### 1. Tests Have Different Configuration Needs

```yaml
groups:
  quick_tests:
    type: Core
    timeout: 10              # Fast tests

  slow_tests:
    type: Core
    timeout: 120             # Slow integration tests
```

#### 2. Organizing by Feature Area

```yaml
groups:
  parsing:
    type: Core

  validation:
    type: Core

  formatting:
    type: Core
```

Better than one huge `core` group.

#### 3. Different Execution Orders (API)

```yaml
groups:
  crud_workflow:
    type: Core
    case_order: [create, read, update, delete]

  search_workflow:
    type: Functionality
    case_order: [setup, search_by_name, search_by_tag]
```

Independent workflows need separate groups.

#### 4. Testing Optional Features

```yaml
groups:
  core:
    type: Core               # Required features

  optional_exports:
    type: Functionality      # CSV export (optional)

  optional_imports:
    type: Functionality      # JSON import (optional)
```

### Don't Create Groups When:

#### 1. Only 1-2 Cases

```yaml
# Bad: Too granular
groups:
  create_user:
    type: Core               # Just 1 case

  update_user:
    type: Core               # Just 1 case

# Better: Combine
groups:
  user_management:
    type: Core               # All user operations
```

#### 2. All Tests Are Similar

```yaml
# Bad: Unnecessary split
groups:
  core_a:
    type: Core
  core_b:
    type: Core
  core_c:
    type: Core

# Better: One group
groups:
  core:
    type: Core
```

## Group Interaction

### Independent Groups

**Most common**: Groups don't affect each other

```yaml
groups:
  core:                      # Independent
    type: Core

  functionality:             # Independent
    type: Functionality

  errors:                    # Independent
    type: Error
```

**Execution**: Order doesn't matter, groups can run in parallel.

### Sequential Groups (API)

**Less common**: Later groups depend on earlier ones

```yaml
groups:
  setup:
    type: Core
    case_order:
      - initialize_database
      - load_seed_data

  operations:                # Depends on setup
    type: Core
    case_order:
      - create_item
      - get_item

  cleanup:                   # Depends on operations
    type: Functionality
    case_order:
      - delete_all_items
```

**Warning**: This is complex and fragile. Prefer independent groups.

## Common Mistakes

### ❌ Mistake 1: Too Many Groups

**Bad:**
```yaml
groups:
  create:
    type: Core
  read:
    type: Core
  update:
    type: Core
  delete:
    type: Core
  list:
    type: Core
  search:
    type: Core
  # 6 groups for one feature!
```

**Better:**
```yaml
groups:
  core:
    type: Core
    # All CRUD operations together
```

**Rule of thumb**: 2-5 groups per checkpoint is ideal.

### ❌ Mistake 2: Unclear Group Purpose

**Bad:**
```yaml
groups:
  group_a:                   # What is this?
    type: Core
  group_b:                   # What is this?
    type: Core
```

**Better:**
```yaml
groups:
  basic_operations:          # Clear purpose
    type: Core
  advanced_features:         # Clear purpose
    type: Functionality
```

### ❌ Mistake 3: Mixing Success and Error Cases

**Bad:**
```
core/
├── valid_input_1/
├── invalid_input/           # ← Error case in core group!
└── valid_input_2/
```

**Better:**
```
core/
├── valid_input_1/
└── valid_input_2/

errors/
└── invalid_input/
```

### ❌ Mistake 4: Wrong Group Type

**Bad:**
```yaml
groups:
  errors:
    type: Core               # ← Should be Error
```

**Why bad**: Affects scoring, reporting, and semantics.

**Better:**
```yaml
groups:
  errors:
    type: Error
```

### ❌ Mistake 5: Not Using Hidden Tests

**Bad:**
```yaml
groups:
  core:
    type: Core
  errors:
    type: Error
  # No hidden tests - agents can overfit!
```

**Better:**
```yaml
groups:
  core:
    type: Core
  errors:
    type: Error
  hidden:                    # Prevent overfitting
    type: Hidden
```

## Examples from Real Problems

### Example 1: `file_backup` (Standard Pattern)

```yaml
# config.yaml → checkpoints.checkpoint_1.groups
checkpoints:
  checkpoint_1:
    groups:
      core:
        type: Core
        timeout: 20
        # 6 cases: daily jobs, weekly jobs, exclusions, etc.

      errors:
        type: Error
        timeout: 20
        # 6 cases: YAML parse errors, schema validation, etc.
```

**Pattern**: Classic core + errors split

**Why it works**: Clear separation of success vs error scenarios

### Example 2: `dynamic_config_service_api` (Feature + Compliance)

```yaml
# config.yaml → checkpoints.checkpoint_1.groups
checkpoints:
  checkpoint_1:
    groups:
      spec_cases:
        type: Core
        case_order:
          - create_base_v1
          - create_billing_v1_including_base
          # ... 10 cases testing spec compliance

      spec_errors:
        type: Error
        case_order:
          - missing_pair_get_active
          - invalid_input_create_missing_scope
          # ... 14 error cases from spec

      functionality:
        type: Functionality
        case_order:
          - setup_array_base
          - activate_specific_version
          # ... feature-specific cases
```

**Pattern**: Spec compliance + advanced features + errors

**Why it works**:
- Clear distinction between required (spec) and optional (functionality)
- Separate error group for validation
- Each group has independent state (different `case_order`)

### Example 3: `code_search` (Progressive Complexity)

```yaml
# In root config.yaml under checkpoints.checkpoint_3
groups:
  core:
    type: Core
    # Basic search patterns

  functionality:
    type: Functionality
    # Complex nested searches

  errors:
    type: Error
    # Invalid patterns, malformed code
```

**Pattern**: Standard three-group with increasing complexity

**Why it works**: Clear progression from simple to advanced

### Example 4: `eve_industry` (Hidden Tests)

```yaml
# In root config.yaml under checkpoints.checkpoint_5
groups:
  core:
    type: Core
    # 3 visible test cases

  hidden:
    type: Hidden
    # 3 hidden test cases
```

**Pattern**: Core + hidden (final checkpoint)

**Why it works**:
- Hidden tests prevent hardcoding solutions
- Tests realistic scenarios not shown to agents
- Validates generalization

## Group Design Checklist

When designing groups, ensure:

- [ ] **2-5 groups per checkpoint** (not too many)
- [ ] **Clear group names** (describe purpose)
- [ ] **Appropriate types** (Core, Error, Functionality, etc.)
- [ ] **Success/error separated** (different groups)
- [ ] **Balanced case counts** (no group with 1 case)
- [ ] **Appropriate timeouts** (longer for complex groups)
- [ ] **case_order for APIs** (when stateful)
- [ ] **Include hidden tests** (prevent overfitting)
- [ ] **Regression tests** (when applicable)
- [ ] **Independent groups** (avoid inter-group dependencies)

## Summary

**Key principles:**

1. **Standard types** - Use Core, Error, Functionality, Hidden, Regression
2. **Clear purpose** - Each group has distinct role
3. **Balanced organization** - 2-5 groups per checkpoint
4. **Appropriate types** - Match group content to type
5. **Independent execution** - Avoid inter-group dependencies

**Common patterns:**

- Standard: Core + Errors + Functionality
- Feature-based: Group by feature area
- Spec compliance: Spec cases + Spec errors + Extras
- Progressive: Basic + Intermediate + Advanced
- Workflow: Organize by user scenarios

**Avoid:**

- Too many groups (over-granular)
- Unclear names (group_a, group_b)
- Wrong types (errors in Core group)
- Missing hidden tests (allows overfitting)
- Inter-group dependencies (fragile)

**Configuration essentials:**

- Set appropriate timeouts
- Use `case_order` for APIs
- Share fixtures with `group_files`
- Choose meaningful group names
- Document group purpose

## Next Steps

- **[Test Cases Guide](test-cases.md)** - Write tests for groups
- **[Checkpoint Design](checkpoints.md)** - Organize groups into checkpoints
- **[Config Schema](config-schema.md)** - Group configuration reference
- **[Examples](examples/)** - See group organization in action
