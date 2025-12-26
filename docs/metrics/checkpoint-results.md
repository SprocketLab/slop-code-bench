---
version: 1.0
last_updated: 2025-12-26
---

# Checkpoint Results

This guide explains the metrics produced for each checkpoint, covering both test correctness results and code quality measurements.

## Introduction

Each checkpoint produces two main categories of metrics:

1. **Correctness Results**: Did the code pass the tests? (stored in `evaluation.json`)
2. **Quality Metrics**: What is the code quality? (stored in `quality_analysis/`)

Together, these provide a complete picture of checkpoint performance:
- **Correctness** tells you if requirements are met
- **Quality** tells you how well they're implemented

## Test Results (Correctness)

Test results are saved to `evaluation.json` in each checkpoint directory.

### Test Categorization

Tests are grouped into categories based on pytest markers. The **GroupType** determines what tests are required for checkpoint success.

| GroupType | Marker | Purpose | Required? |
|-----------|--------|---------|-----------|
| **CORE** | Unmarked tests | Must-pass requirements | Yes (default) |
| **FUNCTIONALITY** | `@pytest.mark.functionality` | Optional extended features | No |
| **REGRESSION** | Tests from prior checkpoints | Prevent backsliding | No (unless policy requires) |
| **ERROR** | `@pytest.mark.error` | Error handling tests | No (assumed to fail) |

**GroupType determines which tests must pass:**
- CORE tests measure core functionality
- FUNCTIONALITY tests measure feature completeness
- REGRESSION tests ensure prior checkpoints still work
- ERROR tests verify error handling (expected failures)

### PassPolicy

The **PassPolicy** determines when a checkpoint is considered "solved." It controls which GroupTypes must have all tests passing.

| Policy | Requirement | When Used |
|--------|-------------|-----------|
| **CORE_CASES** | All CORE tests pass | Default (most common) |
| **ALL_NON_ERROR_CASES** | All CORE, FUNCTIONALITY, and REGRESSION tests pass | High bar for completeness |

**Example**: A checkpoint with 10 CORE tests and 5 FUNCTIONALITY tests:
- Passes CORE_CASES policy if: all 10 CORE pass (FUNCTIONALITY can fail)
- Passes ALL_NON_ERROR_CASES policy if: all 10 CORE + all 5 FUNCTIONALITY pass

### evaluation.json Structure

Example from an actual checkpoint:

```json
{
  "problem_name": "eve_industry",
  "problem_version": 1,
  "checkpoint_name": "checkpoint_1",
  "checkpoint_version": 1,
  "duration": 9.904023170471191,
  "entrypoint": "uv run industry.py",
  "tests": {
    "checkpoint_1-Core": {
      "passed": [
        "test_recipe_core[naga]",
        "test_recipe_core[barrage_l]",
        "test_recipe_core[fernite_carbide]"
      ],
      "failed": []
    },
    "checkpoint_1-Functionality": {
      "passed": [
        "test_recipe_functionality[athanor]",
        "test_recipe_functionality[azariel]"
      ],
      "failed": []
    },
    "checkpoint_1-Error": {
      "passed": [
        "test_unpublished_item_error",
        "test_case_sensitive_item_name"
      ],
      "failed": []
    }
  },
  "pass_counts": {
    "Core": 3,
    "Functionality": 2,
    "Error": 2
  },
  "total_counts": {
    "Core": 3,
    "Functionality": 2,
    "Error": 2
  },
  "pytest_exit_code": 0,
  "pytest_collected": 7,
  "infrastructure_failure": false
}
```

**Key fields:**
- `tests`: Groups test results by `{checkpoint}-{GroupType}`
- `pass_counts` / `total_counts`: Aggregated counts by GroupType
- `pytest_exit_code`: 0 = all tests ran, non-zero = test execution failed
- `pytest_collected`: Total test count pytest found
- `infrastructure_failure`: True if test environment failed (not code failure)

### Interpreting Pass/Fail by GroupType

**CORE tests**: Must pass for checkpoint to be considered "solved"
- All CORE passing → ✅ Checkpoint passes (under CORE_CASES policy)
- Any CORE failing → ❌ Checkpoint fails (requirements not met)

**FUNCTIONALITY tests**: Optional but indicate feature completeness
- All FUNCTIONALITY passing → More complete implementation
- Any FUNCTIONALITY failing → Features not fully implemented (acceptable under CORE_CASES)

**REGRESSION tests**: Indicate code stability across checkpoints
- All REGRESSION passing → Prior functionality still works
- Any REGRESSION failing → Code broke something from prior checkpoint (usually bad sign)

**ERROR tests**: Verify error handling (expected to have some failures)
- More passing → Better error handling coverage

### Pytest Artifacts

The `evaluation/` directory contains raw pytest output:

| File | Content |
|------|---------|
| `stdout.txt` | Pytest stdout with test names and results |
| `stderr.txt` | Pytest stderr (test errors, exceptions) |
| `report.json` | Detailed pytest-json-report format with timing info |

Use these to debug test failures or understand test execution details.

## Quality Metrics

Quality metrics are saved to `quality_analysis/` in each checkpoint directory.

### overall_quality.json

This file contains aggregated metrics across the entire checkpoint. It's organized into sections:

| Section | Metrics | Purpose |
|---------|---------|---------|
| **lines** | total_lines, loc, comments | Basic code size |
| **lint** | errors, fixable, counts | Code style issues |
| **symbols** | total, functions, methods, classes, statements | Structural breakdown |
| **functions** | cc_*, depth_*, lines_*, nesting_*, branches_* | Function complexity stats |
| **classes** | count, method_counts_mean, attribute_counts_mean | Class structure |
| **complexity** | cc_ratings, mi_ratings, cc_max, cc_mean | Complexity distribution |
| **waste** | single_use_functions, trivial_wrappers, single_method_classes | Abstraction efficiency |
| **redundancy** | clone_instances, clone_lines, clone_ratio_sum | Code duplication |
| **ast_grep** | violations, category_counts, category_weighted | Pattern violations |
| **graph** | node_count, edge_count, cyclic_dependency_mass | Dependency analysis |

Example excerpt:

```json
{
  "file_count": 1,
  "source_file_count": 1,
  "lines": {
    "loc": 422,
    "total_lines": 510,
    "comments": 17,
    "single_comment": 6,
    "multi_comment": 0
  },
  "complexity": {
    "cc_sum": 166,
    "cc_max": 54,
    "cc_mean": 5.2,
    "cc_high_count": 3,
    "cc_extreme_count": 1,
    "cc_ratings": {
      "A": 35,
      "B": 6,
      "C": 0,
      "D": 0,
      "E": 0,
      "F": 1
    },
    "mi_ratings": {
      "A": 1,
      "B": 0,
      "C": 0
    }
  },
  "waste": {
    "single_use_functions": 5,
    "trivial_wrappers": 0,
    "single_method_classes": 1
  }
}
```

**What to look for:**
- See [Interpreting Results](interpreting-results.md) for detailed metric meanings
- High `cc_max` (>20) indicates complex functions that need review
- Positive `waste` metrics suggest over-abstraction
- `clone_ratio` > 10% indicates duplication opportunities

### files.jsonl

Per-file metrics, one JSON object per line:

```json
{
  "file_path": "industry.py",
  "loc": 422,
  "total_lines": 510,
  "comments": 17,
  "lint_errors": 59,
  "lint_fixable": 43,
  "mi": 19.43,
  "depth": 1,
  "is_entry_language": true,
  "symbol_count": 42,
  "ast_grep_violation_count": 103,
  "clone_instances": 8,
  "clone_lines": 30,
  "single_use_count": 5,
  "trivial_wrapper_count": 0,
  "single_method_class_count": 1
}
```

**Use this to:**
- Identify which files have the most complexity or violations
- Compare file-level metrics across checkpoints
- Spot files with many clones or waste patterns

### symbols.jsonl

Per-function/class/method metrics, one JSON object per line:

```json
{
  "name": "calculate_total",
  "type": "function",
  "start": 45,
  "start_col": 0,
  "end": 62,
  "end_col": 15,
  "complexity": 3,
  "branches": 2,
  "statements": 8,
  "lines": 18,
  "file_path": "industry.py",
  "parent_class": null,
  "max_nesting_depth": 2,
  "rating": "A",
  "variables_defined": 3,
  "variables_used": 5,
  "return_count": 1,
  "raise_count": 0,
  "body_hash": "74fc0af387c5ff75b8f51dd1f293be77b82ec163aaabb38d801ea093ea6393b6",
  "signature_hash": "4940fc1dde3ba14e6798fc56d196721fb33dd85b265268f9974503cf654db042"
}
```

**Use this to:**
- Identify complex functions (high `complexity`, `branches`, `nesting_depth`)
- Track function-level changes via `body_hash` (hash changes when implementation changes)
- Understand function dependencies (`variables_defined`, `variables_used`)
- Find functions with high `raise_count` (error-prone)

### ast_grep.jsonl

AST-grep pattern violations, one per line:

```json
{
  "rule_id": "complex-tuple-type",
  "severity": "warning",
  "category": "types",
  "subcategory": "types",
  "weight": 2,
  "line": 256,
  "column": 15,
  "end_line": 256,
  "end_column": 39,
  "file_path": "industry.py"
}
```

| Field | Meaning |
|-------|---------|
| `rule_id` | Name of the pattern that was violated |
| `category` | Category: verbosity, naming, safety, complexity, style, types, performance |
| `weight` | Severity: 1 (minor) to 4 (critical) |
| `line` / `column` | Location in source code |

**Use this to:**
- Filter violations by category (e.g., safety violations)
- Prioritize fixes by weight (focus on weight 3-4)
- Identify specific patterns to improve
- See [Interpreting Results](interpreting-results.md) for category details

## Delta Metrics

Delta metrics measure how quality changes between consecutive checkpoints. They're included in the checkpoint-level metrics.

### Percentage-Based Deltas

| Metric | Formula | Interpretation |
|--------|---------|-----------------|
| `delta.loc` | `(curr_loc - prev_loc) / prev_loc * 100` | % change in code size |
| `delta.lint_errors` | Same formula | % change in lint errors |
| `delta.ast_grep_violations` | Same formula | % change in violations |
| `delta.cc_high_count` | Same formula | % change in complex functions |
| `delta.churn_ratio` | `(added + removed) / prev_total` | Code churn as % of prior size |

**Special cases:**
- `inf`: Previous value was 0, now non-zero (new issue)
- `0`: No change between checkpoints
- Positive: Metric increased (often worse)
- Negative: Metric decreased (often better)

### Mass Delta Metrics

Mass tracks "cognitive load" using the formula: `mass = max(0, metric - baseline) * sqrt(statements)`. Mass delta metrics separately track added vs removed complexity to distinguish between growth and refactoring.

#### Understanding Added vs Removed Mass

- **Added Mass**: Functions where complexity increased between checkpoints
- **Removed Mass**: Functions where complexity decreased (reported as absolute value)

| Scenario | Added | Removed | Interpretation |
|----------|-------|---------|----------------|
| `added = 150, removed = 10` | High | Low | Pure growth - new complexity added |
| `added = 80, removed = 70` | High | High | Heavy refactoring / restructuring |
| `added = 10, removed = 100` | Low | High | Code simplification / cleanup |

#### Complexity Mass (Full Suite)

| Metric | Description |
|--------|-------------|
| `delta.mass.complexity` | Net change (added - removed) - **backward compatible** |
| `delta.mass.complexity_added` | Total mass added (sum of positive deltas) |
| `delta.mass.complexity_added_count` | # functions with mass increases |
| `delta.mass.complexity_added_concentration` | Gini coefficient (0 = even, 1 = concentrated) |
| `delta.mass.complexity_added_top50_count` | # functions accounting for 50% of added mass |
| `delta.mass.complexity_added_top50_mass` | Actual mass in top 50% functions |
| `delta.mass.complexity_added_top75_count` | # functions accounting for 75% of added mass |
| `delta.mass.complexity_added_top75_mass` | Actual mass in top 75% functions |
| `delta.mass.complexity_added_top90_count` | # functions accounting for 90% of added mass |
| `delta.mass.complexity_added_top90_mass` | Actual mass in top 90% functions |
| `delta.mass.complexity_removed` | Total mass removed (sum of negative deltas, as positive) |
| `delta.mass.complexity_removed_count` | # functions with mass decreases |
| `delta.mass.complexity_removed_concentration` | Gini coefficient for removed mass |
| `delta.mass.complexity_gross` | Total churn (added + removed) |
| `delta.mass.complexity_net_to_gross_ratio` | (added - removed) / gross |

#### Interpreting Concentration Metrics

**Gini Coefficient (`_concentration`)**:
- `0.0` = Mass spread evenly across all functions
- `0.5` = Moderate concentration
- `0.8+` = Highly concentrated in a few functions
- `1.0` = All mass in a single function

**Top N% Distribution (`_top{50,75,90}_count`)**:
- If `top90_count = 1`: 90% of added mass went to a single function
- If `top90_count = 10` and 50 functions changed: Relatively spread out

**Net-to-Gross Ratio (`_net_to_gross_ratio`)**:
- `1.0` = Pure growth (all added, nothing removed)
- `0.0` = Balanced churn (equal add/remove)
- `-1.0` = Pure simplification (all removed, nothing added)

#### Other Mass Metrics (Top 90% Only)

For non-complexity mass metrics, only top 90% is tracked to minimize output keys:

| Metric | Description |
|--------|-------------|
| `delta.mass.branches_added_top90_count` | # functions for 90% of added branches mass |
| `delta.mass.branches_added_top90_mass` | Actual mass in those functions |
| `delta.mass.comparisons_added_top90_count` | # functions for 90% of added comparisons mass |
| `delta.mass.comparisons_added_top90_mass` | Actual mass in those functions |
| `delta.mass.vars_used_added_top90_count` | # functions for 90% of added vars_used mass |
| `delta.mass.vars_used_added_top90_mass` | Actual mass in those functions |
| `delta.mass.vars_defined_added_top90_count` | # functions for 90% of added vars_defined mass |
| `delta.mass.vars_defined_added_top90_mass` | Actual mass in those functions |
| `delta.mass.try_scaffold_added_top90_count` | # functions for 90% of added try_scaffold mass |
| `delta.mass.try_scaffold_added_top90_mass` | Actual mass in those functions |

### Example Analysis

**Example 1: Concentrated Growth**
```
delta.mass.complexity_added = 150.0
delta.mass.complexity_added_count = 5
delta.mass.complexity_added_concentration = 0.85
delta.mass.complexity_added_top90_count = 1
```
**Interpretation**: 90% of added complexity is in 1 of 5 modified functions. Consider reviewing that function.

**Example 2: Healthy Refactoring**
```
delta.mass.complexity_added = 80.0
delta.mass.complexity_removed = 70.0
delta.mass.complexity_gross = 150.0
delta.mass.complexity_net_to_gross_ratio = 0.067
```
**Interpretation**: Significant churn but low net change. Likely refactoring - complexity was moved around, not just added.

**Example 3: Distributed Growth**
```
delta.mass.complexity_added = 100.0
delta.mass.complexity_added_count = 20
delta.mass.complexity_added_concentration = 0.2
delta.mass.complexity_added_top90_count = 15
```
**Interpretation**: Growth is spread across many functions. Less risky than concentrated growth.

## Directory Structure

Complete checkpoint output layout:

```
checkpoint_N/
├── evaluation.json                    # Test results
├── diff.json                          # File changes from prior checkpoint
├── quality_analysis/                  # Code quality metrics
│   ├── overall_quality.json           # Aggregate quality metrics
│   ├── files.jsonl                    # Per-file metrics
│   ├── symbols.jsonl                  # Per-function/class metrics
│   └── ast_grep.jsonl                 # Pattern violations
├── evaluation/                        # Test artifacts
│   ├── stdout.txt                     # Pytest output
│   ├── stderr.txt                     # Pytest errors
│   └── report.json                    # Pytest JSON report
├── snapshot/                          # Code snapshot (actual files)
│   └── [solution files]
├── prompt.txt                         # Prompt given to agent
└── inference_result.json              # Agent timing/cost/tokens
```

## Reading Checkpoint Results Programmatically

### Load Test Results

```python
import json

with open('checkpoint_1/evaluation.json', 'r') as f:
    results = json.load(f)

# Check if checkpoint passes
core_passed = results['pass_counts']['Core']
core_total = results['total_counts']['Core']
passed = core_passed == core_total

print(f"Core tests: {core_passed}/{core_total} - {'PASS' if passed else 'FAIL'}")
```

### Load Quality Metrics

```python
import json

# Load aggregated metrics
with open('checkpoint_1/quality_analysis/overall_quality.json', 'r') as f:
    quality = json.load(f)

print(f"LOC: {quality['lines']['loc']}")
print(f"Lint errors: {quality['lint']['errors']}")
print(f"Complexity max: {quality['complexity']['cc_max']}")
```

### Stream Per-File Metrics

```python
import json

with open('checkpoint_1/quality_analysis/files.jsonl', 'r') as f:
    for line in f:
        file_metrics = json.loads(line)
        print(f"{file_metrics['file_path']}: {file_metrics['loc']} LOC")
```

### Stream Per-Function Metrics

```python
import json

with open('checkpoint_1/quality_analysis/symbols.jsonl', 'r') as f:
    for line in f:
        symbol = json.loads(line)
        if symbol['type'] == 'function':
            rating = symbol['rating']
            complexity = symbol['complexity']
            print(f"{symbol['name']}: complexity={complexity} ({rating})")
```

## Analyzing Checkpoint Performance

### Quick Checkpoint Health Check

```python
import json

def checkpoint_health(checkpoint_dir):
    # Load evaluation
    with open(f'{checkpoint_dir}/evaluation.json') as f:
        eval_results = json.load(f)

    # Load quality
    with open(f'{checkpoint_dir}/quality_analysis/overall_quality.json') as f:
        quality = json.load(f)

    # Check requirements
    core_passes = eval_results['pass_counts'].get('Core', 0) == eval_results['total_counts'].get('Core', 0)
    high_complexity = quality['complexity']['cc_max'] > 20
    too_many_violations = quality['ast_grep']['violations'] > 50

    return {
        'requirements_met': core_passes,
        'high_complexity': high_complexity,
        'too_many_violations': too_many_violations,
        'loc': quality['lines']['loc'],
        'lint_errors': quality['lint']['errors']
    }
```

### Compare Quality Against Prior Checkpoint

```python
import json

def quality_delta(checkpoint_dir, prior_dir):
    def load_quality(d):
        with open(f'{d}/quality_analysis/overall_quality.json') as f:
            return json.load(f)

    curr = load_quality(checkpoint_dir)
    prev = load_quality(prior_dir)

    # Calculate deltas
    loc_delta = (curr['lines']['loc'] - prev['lines']['loc']) / prev['lines']['loc'] * 100
    violations_delta = (curr['ast_grep']['violations'] - prev['ast_grep']['violations']) / prev['ast_grep']['violations'] * 100

    print(f"LOC change: {loc_delta:.1f}%")
    print(f"Violations change: {violations_delta:.1f}%")
    print(f"Complexity max: {prev['complexity']['cc_max']} → {curr['complexity']['cc_max']}")
```

## Interpreting Results

For detailed interpretation of specific metrics, see [Interpreting Results](interpreting-results.md). Key things to look for:

- **Correctness**: Are all CORE tests passing? Are REGRESSION tests still passing?
- **Complexity**: Is `cc_max` under control? Are most functions rated A/B?
- **Duplication**: Is `clone_ratio` under 10%? Any patterns in cloned code?
- **Violations**: Are critical violations (weight 3-4) being addressed?
- **Trends**: Are delta metrics improving or degrading? Is code growing too fast?
