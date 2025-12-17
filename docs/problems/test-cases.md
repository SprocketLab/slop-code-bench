---
version: 1.0
last_updated: 2025-11-06
---

# Test Case Authoring Guide

This guide provides best practices for writing effective test cases that validate agent solutions thoroughly while remaining maintainable and debuggable.

## Table of Contents

- [Core Principles](#core-principles)
- [CLI Test Cases](#cli-test-cases)
- [API Test Cases](#api-test-cases)
- [Test Coverage Strategy](#test-coverage-strategy)
- [Common Patterns](#common-patterns)
- [Anti-Patterns to Avoid](#anti-patterns-to-avoid)
- [Debugging Test Cases](#debugging-test-cases)

## Core Principles

### 1. Tests Should Be Self-Documenting

**Good:**
```
checkpoint_1/core/
├── daily_job_due_at_exact_time/
├── daily_job_not_due_yet/
├── weekly_job_monday_only/
└── disabled_job_should_not_run/
```

**Bad:**
```
checkpoint_1/core/
├── test1/
├── test2/
├── test3/
└── test4/
```

**Why**: Directory/file names should explain what is being tested without needing to read the contents.

### 2. Test One Thing at a Time

**Good:**
```yaml
# Case: empty_schedule
input_files:
  - path: schedule.yaml
    content: |
      version: 1
      jobs: []
```

**Bad:**
```yaml
# Case: kitchen_sink
# Tests empty schedule, invalid YAML, missing fields, wrong timezone, disabled jobs...
```

**Why**: When a test fails, you should immediately know what broke. Complex tests hide the root cause.

### 3. Use Realistic Data

**Good:**
```yaml
body:
  user:
    name: Alice Johnson
    email: alice@example.com
    age: 32
```

**Bad:**
```yaml
body:
  user:
    name: asdf
    email: x
    age: 999
```

**Why**: Realistic data catches edge cases (name formatting, email validation, range checks) that synthetic data misses.

### 4. Expected Output Should Be Precise

**Good:**
```yaml
expected:
  output:
    jobs_ran: 2
    jobs_skipped: 1
    errors: []
```

**Bad:**
```yaml
expected:
  output:
    # Check that something ran
```

**Why**: Vague expectations lead to false positives. Be explicit about what success looks like.

### 5. Error Cases Are as Important as Success Cases

**Coverage breakdown:**
- 60% success cases (core functionality)
- 30% error cases (validation, error handling)
- 10% edge cases (boundary conditions)

## CLI Test Cases

### Directory Structure

```
checkpoint_1/core/
└── descriptive_case_name/
    ├── case.yaml              # Arguments and input files
    ├── expected.txt           # Expected output (success case)
    └── expected.jsonl         # Or JSONL, CSV, etc.

checkpoint_1/errors/
└── error_invalid_yaml/
    ├── case.yaml              # Arguments with invalid input
    └── expected.yaml          # Status code + stderr pattern
```

### Success Case Example

```yaml
# case.yaml
arguments: --schedule schedule.yaml --now 2025-01-10T10:00:00Z --duration 24 --mount {{static:files}}

input_files:
  - path: schedule.yaml
    file_type: yaml
    content: |
      version: 1
      timezone: UTC
      jobs:
        - id: backup-daily
          enabled: true
          when:
            kind: daily
            at: "10:00"
          source: mount://documents
          exclude:
            - "*.tmp"
```

```jsonl
# expected.jsonl
{"event":"job_start","job_id":"backup-daily","timestamp":"2025-01-10T10:00:00+00:00"}
{"event":"file_backed_up","job_id":"backup-daily","file":"documents/report.pdf","timestamp":"2025-01-10T10:00:00+00:00"}
{"event":"job_end","job_id":"backup-daily","timestamp":"2025-01-10T10:00:00+00:00"}
```

**Best practices:**

1. **Use placeholders**: `{{static:files}}` for mounted directories
2. **Include context**: Full schedule, not just minimal fields
3. **Precise timestamps**: ISO 8601 with timezone
4. **Realistic IDs**: `backup-daily`, not `job1`

### Error Case Example

```yaml
# case.yaml
arguments: --schedule bad.yaml --now 2025-01-10T10:00:00Z

input_files:
  - path: bad.yaml
    file_type: yaml
    content: |
      this is not valid yaml {{{
      missing: quotes
```

```yaml
# expected.yaml
status_code: 3
stderr: "ERROR:E_PARSE:.*"        # Regex pattern
```

**Best practices:**

1. **Test one error**: Invalid YAML, not invalid YAML + missing fields
2. **Use regex**: Allows variation in error messages
3. **Match spec**: Status code should match specification

### Multiple Input Files

```yaml
# case.yaml
arguments: --merge output.json --files a.json b.json c.json

input_files:
  - path: a.json
    file_type: json
    content: |
      {"users": [{"id": 1, "name": "Alice"}]}

  - path: b.json
    file_type: json
    content: |
      {"users": [{"id": 2, "name": "Bob"}]}

  - path: c.json
    file_type: json
    content: |
      {"users": [{"id": 3, "name": "Charlie"}]}
```

**Best practices:**

1. **Small files**: Keep input files minimal but realistic
2. **Clear differences**: Each file should add unique data
3. **Valid JSON/YAML**: Use proper formatting

### Static Assets

```yaml
# case.yaml
arguments: --data-dir {{static:sde_dir}} --item Tritanium

# The framework mounts problems/my_problem/sde/ to the workspace
# No need to include large files in case.yaml
```

**When to use:**
- Large reference datasets (> 1KB)
- Shared across multiple test cases
- Binary files (images, databases)

**When not to use:**
- Small case-specific inputs
- Files that vary per test

## API Test Cases

### File Structure

```
checkpoint_1/core/
├── create_user.yaml           # POST /users
├── get_user.yaml              # GET /users/{id}
├── update_user.yaml           # PATCH /users/{id}
└── delete_user.yaml           # DELETE /users/{id}
```

### Basic CRUD Example

```yaml
# create_user.yaml
case:
  id: create_user
  method: POST
  path: /v1/users
  headers:
    content-type: application/json
  body:
    name: Alice Johnson
    email: alice@example.com
    role: admin

expected:
  status_code: 201
  headers:
    content-type: application/json
  output:
    id: "{{dynamic}}"           # Will be generated
    name: Alice Johnson
    email: alice@example.com
    role: admin
    created_at: "{{dynamic}}"   # Timestamp
```

**Best practices:**

1. **Descriptive IDs**: `create_user`, not `test1`
2. **Complete bodies**: Include all fields, not just required ones
3. **Check headers**: Verify content-type is correct
4. **Dynamic values**: Use `{{dynamic}}` for generated fields

### Stateful Sequence

```yaml
# config.yaml → checkpoints.checkpoint_1.groups.core.case_order
checkpoints:
  checkpoint_1:
    groups:
      core:
        case_order:
          - create_project
          - add_task_to_project
          - get_project_with_tasks
          - complete_task
          - get_project_after_completion
```

```yaml
# create_project.yaml
case:
  id: create_project
  method: POST
  path: /v1/projects
  body:
    name: Website Redesign
    status: active

expected:
  status_code: 201
  output:
    id: "{{dynamic}}"
    name: Website Redesign
    status: active
```

```yaml
# add_task_to_project.yaml (depends on create_project)
case:
  id: add_task_to_project
  method: POST
  path: /v1/projects/{{project_id}}/tasks  # ID from create_project
  body:
    title: Design homepage mockup
    priority: high

expected:
  status_code: 201
  output:
    id: "{{dynamic}}"
    title: Design homepage mockup
    priority: high
    status: pending
```

**Best practices:**

1. **Explicit ordering**: Use `case_order` to define sequence
2. **Build incrementally**: Each case adds to previous state
3. **Verify state**: Later cases check earlier modifications worked
4. **Independent groups**: Different features use different sequences

### JSON Schema Validation

When exact values can't be predicted:

```yaml
# Instead of:
expected:
  output:
    id: "c4ca4238-a0b9-3382-8dcc-509a6f75849b"  # Wrong: won't match

# Use JSON Schema:
expected:
  status_code: 200
  output:
    type: object
    properties:
      id:
        type: string
        pattern: "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
      name: {type: string, minLength: 1}
      created_at: {type: string, format: date-time}
      items:
        type: array
        items:
          type: object
          properties:
            id: {type: string}
            value: {type: number}
          required: [id, value]
    required: [id, name, created_at, items]
```

**When to use JSON Schema:**
- Auto-generated IDs (UUIDs, auto-increment)
- Timestamps
- Order-independent arrays
- Variable-length lists
- Flexible field presence

### Error Responses

```yaml
# get_nonexistent_user.yaml
case:
  id: get_nonexistent_user
  method: GET
  path: /v1/users/99999

expected:
  status_code: 404
  output:
    error:
      code: not_found
      message: User not found
      details:
        user_id: 99999
```

**Best practices:**

1. **Correct status codes**: 400 (bad input), 404 (not found), 409 (conflict), etc.
2. **Structured errors**: Follow your spec's error format
3. **Machine-readable codes**: `not_found`, not just messages
4. **Include details**: Help debug what went wrong

## Test Coverage Strategy

### Coverage Matrix

| Area | Success Cases | Error Cases | Edge Cases |
|------|---------------|-------------|------------|
| **Input Validation** | Valid inputs | Invalid types, missing fields, bad formats | Boundary values, empty strings |
| **Business Logic** | Happy paths | Conflicts, precondition failures | Rare combinations |
| **State Management** | CRUD operations | Duplicate creates, invalid deletes | Race conditions |
| **Error Handling** | Graceful degradation | Timeouts, external failures | Partial failures |

### Success Cases (Core Group)

**What to test:**

1. **Basic functionality**
   - Simplest valid input
   - Typical usage scenarios
   - All primary features

2. **Feature variations**
   - Different modes/options
   - Multiple valid inputs
   - Various combinations

3. **Data types**
   - Strings, numbers, booleans
   - Arrays, objects
   - Null values where allowed

**Example for a backup scheduler:**

```
core/
├── daily_job_due_now/              # Basic: Job runs at scheduled time
├── daily_job_not_due/              # Basic: Job doesn't run when not due
├── weekly_job_correct_day/         # Feature: Weekly scheduling
├── multiple_jobs_sorted/           # Feature: Multiple jobs in order
├── job_with_exclusion_rules/       # Feature: File exclusions
├── empty_schedule/                 # Edge: No jobs
└── relative_mount_path/            # Feature: Path handling
```

### Error Cases (Errors Group)

**What to test:**

1. **Input validation**
   - Missing required fields
   - Invalid types
   - Bad formats

2. **Business logic errors**
   - Duplicate resources
   - Invalid state transitions
   - Constraint violations

3. **External failures**
   - File not found
   - Network errors
   - Permission denied

**Example for a backup scheduler:**

```
errors/
├── error_yaml_parse/               # Parse error
├── error_schema_missing_version/   # Missing required field
├── error_schema_invalid_timezone/  # Invalid value
├── error_schema_daily_missing_at/  # Conditional field missing
└── error_invalid_mount_path/       # File system error
```

### Edge Cases (Functionality Group)

**What to test:**

1. **Boundary values**
   - Empty collections
   - Maximum sizes
   - Zero/negative numbers

2. **Rare combinations**
   - Multiple flags together
   - Unusual but valid inputs
   - Optional fields present

3. **Performance/scale**
   - Large inputs
   - Many operations
   - Deep nesting

**Example:**

```
functionality/
├── extremely_long_job_id/          # Boundary: Max string length
├── job_due_at_exact_boundary/      # Boundary: Inclusive duration
├── nested_exclusion_patterns/      # Complex: Deep glob patterns
└── all_optional_fields_present/    # Edge: Every optional field
```

### Hidden Cases (Hidden Group)

**What to test:**

Prevent overfitting to visible test cases:

1. **Variations of visible tests**
   - Similar but slightly different inputs
   - Same logic, different data

2. **Uncommon scenarios**
   - Rarely used features
   - Edge cases not in core

3. **Integration scenarios**
   - Multiple features combined
   - Real-world complexity

**Hidden tests are NOT shown to agents** during problem-solving.

## Common Patterns

### Pattern 1: Parametric Variation

Test the same logic with different parameters:

```
core/
├── daily_job_at_midnight/
├── daily_job_at_noon/
├── daily_job_at_end_of_day/
```

Each tests daily scheduling, but at different times of day.

### Pattern 2: Progressive Complexity

Start simple, add complexity:

```
core/
├── single_file_backup/              # 1 file
├── directory_with_files/            # 5 files
├── nested_directory_structure/      # 20 files, 3 levels deep
```

### Pattern 3: Feature Interaction

Test features working together:

```
functionality/
├── weekly_job_with_exclusions/      # Weekly + exclusions
├── disabled_job_still_listed/       # Disabled + list operation
├── rollback_with_verification/      # Rollback + verify mode
```

### Pattern 4: Error Recovery

Test error handling doesn't break state:

```
spec_errors/
├── create_duplicate_user/           # Conflict error
├── create_valid_user_after_error/   # Recovery: Can create different user
```

### Pattern 5: Regression Prevention

When bugs are fixed, add test cases:

```
regression/
├── issue_42_timezone_parse/         # Bug: Timezone parsing broke
├── issue_73_empty_array_merge/      # Bug: Empty arrays merged wrong
```

## Anti-Patterns to Avoid

### ❌ Anti-Pattern 1: Kitchen Sink Tests

**Bad:**
```yaml
# mega_test.yaml - tests everything!
# - Daily jobs
# - Weekly jobs
# - Exclusions
# - Multiple mounts
# - Error handling
# - Edge cases
```

**Why bad**: When it fails, you don't know which feature broke.

**Fix**: Break into separate focused tests.

### ❌ Anti-Pattern 2: Implicit Dependencies

**Bad:**
```yaml
# API case order
case_order:
  - create_user
  - update_project        # ← Depends on create_project (not in list!)
  - delete_user
```

**Why bad**: `update_project` will fail with 404.

**Fix**: Include all dependencies in sequence.

### ❌ Anti-Pattern 3: Brittle Expectations

**Bad:**
```yaml
expected:
  output: |
    Job started at 2025-01-10 10:00:00.123456 UTC
    File backed up: /tmp/workspace/12345/files/doc.pdf
    Job completed successfully!
```

**Why bad**: Breaks on timestamp precision, absolute paths, message wording changes.

**Fix**: Parse structured output (JSON/JSONL) or use regex patterns.

### ❌ Anti-Pattern 4: Missing Negative Tests

**Bad:**
```
core/
├── valid_input_1/
├── valid_input_2/
└── valid_input_3/
# No error cases!
```

**Why bad**: Doesn't test error handling, validation, edge cases.

**Fix**: Add error cases (30% of tests).

### ❌ Anti-Pattern 5: Copy-Paste Test Cases

**Bad:**
```
core/
├── test_a/
│   └── case.yaml    # 100 lines, 95% same as test_b
└── test_b/
    └── case.yaml    # 100 lines, 95% same as test_a
```

**Why bad**: Hard to maintain, easy to introduce inconsistencies.

**Fix**: Use shared fixtures via `group_files` or static assets.

### ❌ Anti-Pattern 6: Vague Error Patterns

**Bad:**
```yaml
expected:
  stderr: ".*error.*"    # Matches any error!
```

**Why bad**: False positives (matches wrong errors).

**Fix**: Be specific: `"ERROR:E_PARSE:.*"`

## Debugging Test Cases

### Step 1: Verify Case Loads

```bash
# Check if loader finds your cases
# Note: Ensure repository root is in PYTHONPATH
export PYTHONPATH=$PYTHONPATH:.
uv run python -c "
from problems.my_problem.loader import Loader
from slop_code.evaluation import ProblemConfig, CheckpointConfig

loader = Loader(problem, checkpoint)
for case, expected in loader(group, store):
    print(f'Loaded: {case.id}')
"
```

### Step 2: Check Expected Output Format

```bash
# Verify expected output parses correctly
cat checkpoint_1/core/my_case/expected.jsonl | python -m json.tool
```

### Step 3: Run Case Manually

```bash
# Execute the CLI command from case.yaml
cd /tmp/test_workspace
echo '<input_files content>' > input.yaml
python -m solution --schedule input.yaml --now 2025-01-10T10:00:00Z
```

### Step 4: Compare Outputs

```bash
# Use the same comparison logic as verifier
python -c "
import json
from slop_code.evaluation.verifiers import verifiers

actual = json.loads(open('actual_output.json').read())
expected = json.loads(open('expected_output.json').read())

result = verifiers.deepdiff_verify(actual, expected, weight=1.0)
print(f'Score: {result.score}')
print(f'Diff: {result.message}')
"
```

### Step 5: Use Dashboard

```bash
# View detailed test results
uv run python -m slop_code.visualization.app outputs/
```

Navigate to failed test to see:
- Input that was provided
- Expected output
- Actual output
- Diff between them

## Test Case Checklist

Before committing test cases, verify:

- [ ] **Naming**: Case names are descriptive
- [ ] **Documentation**: Comments explain what's being tested
- [ ] **Minimal**: No unnecessary data
- [ ] **Realistic**: Data looks like production
- [ ] **Precise**: Expected output is exact (or uses JSON Schema)
- [ ] **Independent**: CLI tests don't depend on order
- [ ] **Ordered**: API tests use `case_order`
- [ ] **Complete**: Success + error + edge cases
- [ ] **Parseable**: All YAML/JSON is valid
- [ ] **Verifiable**: Can manually verify expected output is correct

## Summary

**Key principles:**

1. **One test, one purpose** - Test a single thing clearly
2. **Self-documenting names** - Explain what's tested without reading code
3. **Realistic data** - Use production-like inputs
4. **Precise expectations** - Be explicit about success criteria
5. **Comprehensive coverage** - 60% success, 30% errors, 10% edge
6. **Maintainable structure** - Easy to add/modify cases

**Common mistakes:**

- Kitchen sink tests (test too much at once)
- Implicit dependencies (missing setup steps)
- Brittle expectations (hardcoded paths/timestamps)
- Missing error cases (only test happy paths)
- Vague patterns (overly broad regex)

**Best practices:**

- Use JSON Schema for dynamic values
- Normalize timestamps in verifier
- Break complex tests into simple ones
- Test error handling thoroughly
- Use `case_order` for stateful APIs
- Share common data via static assets

## Next Steps

- **[Checkpoint Design](checkpoints.md)** - When to split into checkpoints
- **[Groups Guide](groups.md)** - How to organize test cases
- **[Simple CLI Example](examples/simple-cli.md)** - See CLI tests in action
- **[Stateful API Example](examples/stateful-api.md)** - See API tests in action
- **[Troubleshooting](troubleshooting.md)** - Debug failing tests
