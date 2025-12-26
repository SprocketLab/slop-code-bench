---
version: 1.0
last_updated: 2025-12-26
---

# Run-Level Results

This guide explains how checkpoint metrics aggregate into run-level summaries, enabling performance comparison and trend analysis across multiple problems and checkpoints.

## Introduction

After an agent completes a run (all problems and checkpoints), two summary files are generated at the run root:

1. **checkpoint_results.jsonl**: All checkpoint metrics in one flattened JSONL file (one line per checkpoint)
2. **result.json**: Aggregated statistics across all checkpoints and problems

**Hierarchy:**
```
Run Level (result.json)
  ├─ Problem 1 Level (aggregated from checkpoints)
  │   ├─ Checkpoint 1
  │   ├─ Checkpoint 2
  │   └─ ...
  └─ Problem 2 Level (aggregated from checkpoints)
      ├─ Checkpoint 1
      └─ ...
```

## checkpoint_results.jsonl

All checkpoint-level metrics are flattened into a single JSONL file at the run root. This enables efficient analysis and filtering.

### Format

One JSON object per line, one line per checkpoint across all problems.

```json
{
  "problem": "circuit_eval",
  "version": 1,
  "checkpoint": "checkpoint_1",
  "path": "outputs/run_001/circuit_eval/checkpoint_1",
  "idx": 1,
  "state": "ran",
  "is_first": true,
  "is_last": false,
  "pass_rate": 1.0,
  "core_pass_rate": 1.0,
  "checkpoint_pass_rate": 1.0,
  "duration": 5.770282983779907,
  "total_tests": 36,
  "passed_tests": 36,
  "core_total": 12,
  "core_passed": 12,
  "functionality_total": 15,
  "functionality_passed": 15,
  "error_total": 9,
  "error_passed": 9,
  "regression_total": 0,
  "regression_passed": 0,
  "started": "2025-12-25T16:21:09.469411",
  "ended": "2025-12-25T16:29:08.741500",
  "elapsed": 479.272089,
  "cost": 1.67457395,
  "steps": 52,
  "cache_read": 645504,
  "cache_write": 0,
  "input": 727773,
  "output": 20572,
  "reasoning": 0,
  "loc": 430,
  "total_lines": 544,
  "single_comments": 1,
  "lint_errors": 81,
  "lint_fixable": 10,
  "files": 1,
  "functions": 12,
  "methods": 12,
  "classes": 18,
  "statements": 181,
  "symbols_total": 52,
  "cc_max": 24,
  "cc_mean": 5.208333333333333,
  "cc_std": 6.372353102110006,
  "cc_high_count": 5,
  "cc_extreme_count": 0,
  "clone_instances": 0,
  "clone_lines": 0,
  "ast_grep_violations": 35,
  "sg_verbosity_violations": 5,
  "sg_naming_violations": 3,
  "sg_performance_violations": 0,
  "sg_types_violations": 2,
  "sg_safety_violations": 4,
  "sg_style_violations": 9,
  "sg_complexity_violations": 12,
  "ast_grep_per_loc": 0.08139534883720931,
  "lint_per_loc": 0.1883720930232558
}
```

### Field Categories

**Metadata:**
- `problem`: Problem name
- `checkpoint`: Checkpoint name
- `version`: Problem version
- `idx`: Checkpoint index (1-based)
- `state`: "ran" or other status
- `path`: Full path to checkpoint directory
- `started` / `ended`: Timestamps
- `is_first` / `is_last`: Boolean flags for checkpoint position

**Correctness (from evaluation.json):**
- `pass_rate`: Total pass rate (passed_tests / total_tests)
- `core_pass_rate`: CORE tests pass rate
- `checkpoint_pass_rate`: Same as pass_rate
- `total_tests`, `passed_tests`: Overall test counts
- `core_total` / `core_passed`: CORE test counts
- `functionality_total` / `functionality_passed`: FUNCTIONALITY test counts
- `regression_total` / `regression_passed`: REGRESSION test counts
- `error_total` / `error_passed`: ERROR test counts
- `duration`: Test execution time in seconds

**Inference (from inference_result.json):**
- `elapsed`: Total elapsed time for checkpoint
- `cost`: API cost in dollars
- `steps`: Number of agent steps
- `cache_read` / `cache_write`: Cache hit/write bytes
- `input` / `output` / `reasoning`: Token counts

**Quality (from quality_analysis/):**
- `loc`: Lines of code
- `total_lines`: Including blanks
- `lint_errors`: Linting violations
- `files`: Number of files
- `functions`: Function count
- `methods`: Method count
- `classes`: Class count
- `cc_max`: Max cyclomatic complexity
- `cc_mean`: Mean complexity
- `cc_std`: Standard deviation of complexity
- `cc_high_count`: Functions with CC > 10
- `cc_extreme_count`: Functions with CC > 30
- `clone_instances`: Duplicate code blocks
- `ast_grep_violations`: Total pattern violations
- `sg_*_violations`: Violations by category (verbosity, naming, etc.)
- `ast_grep_per_loc`: Violations per line of code
- `lint_per_loc`: Lint errors per line of code

**Use cases:**
- Time-series analysis: Track how metrics change across checkpoints
- Filtering: Find slow/expensive checkpoints
- Comparisons: Compare same checkpoint across different runs
- Quality trends: Identify improvement or degradation patterns

## result.json (RunSummary)

Complete aggregated statistics across all checkpoints and problems.

### Structure

**Configuration:**
```json
{
  "model": "anthropic/claude-3-5-sonnet-20241022",
  "thinking": "low",
  "prompt": "just-solve",
  "agent_type": "claude_code",
  "agent_version": "2.0.51"
}
```

**Counts:**
```json
{
  "num_problems": 3,
  "num_checkpoints": 9
}
```

**Efficiency Metrics:**
```json
{
  "costs": {
    "checkpoint": {"mean": 2.45, "stddev": 1.23, "min": 0.50, "max": 5.20, "median": 2.10, "count": 9},
    "problem": {"mean": 7.35, "stddev": 2.10, "min": 4.50, "max": 12.30, "median": 7.20, "count": 3},
    "total": 22.05
  },
  "time": {
    "checkpoint": {"mean": 487.23, "stddev": 245.67, ...},
    "problem": {"mean": 1461.69, "stddev": 456.78, ...}
  },
  "tokens": {
    "input": 2847293,
    "output": 287293,
    "cache_read": 1928473,
    "cache_write": 0,
    "reasoning": 0
  },
  "steps": {
    "checkpoint": {"mean": 52.33, "stddev": 12.45, ...},
    "problem": {"mean": 157.0, "stddev": 34.20, ...}
  }
}
```

**Solve Rates:**
```json
{
  "solve_rates": {
    "pct_checkpoints_solved": 88.89,
    "pct_problems_solved": 66.67,
    "pct_problems_partial": 33.33
  }
}
```

- `pct_checkpoints_solved`: % of checkpoints passing their PassPolicy
- `pct_problems_solved`: % of problems with all checkpoints solved
- `pct_problems_partial`: % of problems with some (but not all) checkpoints solved

**Pass Rates:**
```json
{
  "pass_rates": {
    "checkpoint": {
      "core": {"mean": 0.95, "stddev": 0.05, ...},
      "total": {"mean": 0.87, "stddev": 0.08, ...},
      "error": {"mean": 0.72, "stddev": 0.15, ...},
      "functionality": {"mean": 0.85, "stddev": 0.10, ...},
      "regression": {"mean": 0.92, "stddev": 0.06, ...}
    },
    "problem": {
      "core": {...},
      "total": {...}
    }
  }
}
```

**Quality Statistics:**
```json
{
  "cc": {
    "cc_sum": 1847,
    "cc_max": 54,
    "cc_mean": 5.2,
    "cc_high_count": {"mean": 3.2, "stddev": 1.5, "min": 0, "max": 7, "median": 3, "count": 9},
    "cc_extreme_count": {"mean": 0.2, "stddev": 0.4, ...},
    "cc_ratings": {"A": 312, "B": 43, "C": 5, "D": 0, "E": 0, "F": 2},
    "mi_ratings": {"A": 8, "B": 1, "C": 0}
  },
  "ratios": {
    "ast_grep_per_loc": {"mean": 0.092, "stddev": 0.045, ...},
    "lint_per_loc": {"mean": 0.156, "stddev": 0.034, ...},
    "rubric_per_loc": {"mean": 0.034, "stddev": 0.019, ...}
  },
  "delta": {
    "loc": {"mean": 23.5, "stddev": 15.2, ...},
    "lint_errors": {"mean": -12.3, "stddev": 24.5, ...},
    "ast_grep_violations": {"mean": 18.4, "stddev": 31.2, ...},
    "cc_high_count": {"mean": 5.2, "stddev": 8.1, ...},
    "churn_ratio": {"mean": 0.38, "stddev": 0.21, ...}
  },
  "composite_scores": {
    "verbosity": {"mean": 0.156, "stddev": 0.067, ...},
    "erosion": {"mean": 0.234, "stddev": 0.089, ...}
  }
}
```

### MetricStats Structure

Each numeric metric is aggregated using `MetricStats`:

| Field | Meaning |
|-------|---------|
| `mean` | Average value across checkpoints |
| `stddev` | Standard deviation (variability) |
| `min` | Minimum value |
| `max` | Maximum value |
| `median` | Middle value (50th percentile) |
| `count` | Number of values aggregated |

**Example interpretation:**
```json
"cc_high_count": {
  "mean": 3.2,
  "stddev": 1.5,
  "min": 0,
  "max": 7,
  "median": 3
}
```
Meaning: On average, 3.2 functions with CC > 10, ranging from 0 to 7, typically 3.

### Complete Structure Reference

**Top-level sections:**
- `model`, `thinking`, `prompt`, `agent_type`, `agent_version`: Configuration
- `num_problems`, `num_checkpoints`: Counts
- `costs`, `time`, `tokens`, `steps`: Efficiency metrics at checkpoint/problem levels
- `solve_rates`: Overall solution percentages
- `pass_rates`: Test pass rates by type
- `cc`: Complexity statistics
- `ratios`: Quality per unit code
- `delta`: Average changes between checkpoints
- `composite_scores`: High-level quality indicators

## Aggregation Logic

### Checkpoint-Level Statistics

Computed within each checkpoint from checkpoint_results.jsonl:
- `pass_rate`: (passed_tests / total_tests) * 100
- `core_pass_rate`: (core_passed / core_total) * 100
- Quality metrics: Direct from quality_analysis/

### Problem-Level Statistics

Aggregated across checkpoints for one problem:
- `mean_time`: Average elapsed time per checkpoint
- `total_cost`: Sum of costs across checkpoints
- `pct_solved`: (checkpoints_passed / total_checkpoints) * 100
- `cc_mean`: Mean of cc_mean across checkpoints
- Quality ratios: Aggregate violations / aggregate LOC

### Run-Level Statistics

Aggregated across all problems:
- All metrics computed as mean ± stddev across all problems
- `pct_checkpoints_solved`: (solved_checkpoints / total_checkpoints) * 100
- `pct_problems_solved`: (fully_solved_problems / total_problems) * 100
- `pct_problems_partial`: (partially_solved_problems / total_problems) * 100
- Total cost: Sum across entire run

### Composite Scores

**Verbosity Score**: Measures code bloat and over-abstraction

**Formula:**
```
verbosity_per_checkpoint = (
  (ast_grep_violations + rubric_flags) / loc +
  trivial_wrappers / (functions + methods) +
  single_use_functions / (functions + methods)
) / 3
```

Mean across all checkpoints = verbosity score

**Erosion Score**: Measures code health degradation

**Formula:**
```
erosion_per_checkpoint = (
  (cc_high_count + cc_extreme_count) / (functions + methods) +
  lint_errors / loc
) / 2
```

Mean across all checkpoints = erosion score

Higher scores indicate worse code health.

## Directory Structure

Run output organization:

```
outputs/{model}/{agent-prompt-params-timestamp}/
├── config.yaml                        # Run configuration
├── environment.yaml                   # Environment spec
├── checkpoint_results.jsonl           # All checkpoint metrics
├── result.json                        # Aggregated run summary
├── {problem_name_1}/
│   ├── checkpoint_1/
│   │   ├── evaluation.json
│   │   └── quality_analysis/
│   ├── checkpoint_2/
│   │   └── ...
│   └── ...
└── {problem_name_2}/
    └── ...
```

**Key files:**
- `checkpoint_results.jsonl`: Query individual checkpoints efficiently
- `result.json`: High-level run comparison, summaries, trends

## Reading Run Results Programmatically

### Load RunSummary

```python
import json

with open('result.json', 'r') as f:
    summary = json.load(f)

# Overall performance
print(f"Problems solved: {summary['solve_rates']['pct_problems_solved']}%")
print(f"Total cost: ${summary['costs']['total']:.2f}")

# Average complexity
cc_mean = summary['cc']['cc_mean']
cc_high = summary['cc']['cc_high_count']['mean']
print(f"Average CC: {cc_mean:.1f}, High-CC functions: {cc_high:.1f}")
```

### Stream checkpoint_results.jsonl

```python
import json

with open('checkpoint_results.jsonl', 'r') as f:
    for line in f:
        checkpoint = json.loads(line)
        print(f"{checkpoint['problem']} {checkpoint['checkpoint']}: "
              f"pass_rate={checkpoint['pass_rate']:.2%}, "
              f"cost=${checkpoint['cost']:.2f}")
```

### Filter by Problem

```python
import json

problem_name = 'circuit_eval'
checkpoints = []

with open('checkpoint_results.jsonl', 'r') as f:
    for line in f:
        cp = json.loads(line)
        if cp['problem'] == problem_name:
            checkpoints.append(cp)

print(f"Problem '{problem_name}': {len(checkpoints)} checkpoints")
for cp in checkpoints:
    print(f"  {cp['checkpoint']}: {cp['core_pass_rate']:.0%} core pass")
```

### Compute Custom Aggregations

```python
import json
from statistics import mean, stdev

# Find average cost per LOC
costs_per_loc = []

with open('checkpoint_results.jsonl', 'r') as f:
    for line in f:
        cp = json.loads(line)
        if cp['loc'] > 0:
            cost_per_loc = cp['cost'] / cp['loc']
            costs_per_loc.append(cost_per_loc)

print(f"Cost per LOC: {mean(costs_per_loc):.4f} ± {stdev(costs_per_loc):.4f}")
```

## Comparing Runs

### Compare Overall Performance

```python
import json

def compare_runs(run1_path, run2_path):
    def load_summary(path):
        with open(f'{path}/result.json') as f:
            return json.load(f)

    s1 = load_summary(run1_path)
    s2 = load_summary(run2_path)

    print("Metric                  | Run 1      | Run 2      | Change")
    print("-" * 60)
    print(f"Problems solved         | {s1['solve_rates']['pct_problems_solved']:6.1f}%  | {s2['solve_rates']['pct_problems_solved']:6.1f}%  | {s2['solve_rates']['pct_problems_solved'] - s1['solve_rates']['pct_problems_solved']:+6.1f}%")
    print(f"Total cost              | ${s1['costs']['total']:8.2f}  | ${s2['costs']['total']:8.2f}  | {((s2['costs']['total'] - s1['costs']['total']) / s1['costs']['total'] * 100):+6.1f}%")
    print(f"Avg checkpoint time     | {s1['time']['checkpoint']['mean']:8.1f}s | {s2['time']['checkpoint']['mean']:8.1f}s | {((s2['time']['checkpoint']['mean'] - s1['time']['checkpoint']['mean']) / s1['time']['checkpoint']['mean'] * 100):+6.1f}%")
    print(f"CC high count (mean)    | {s1['cc']['cc_high_count']['mean']:8.1f}  | {s2['cc']['cc_high_count']['mean']:8.1f}  | {s2['cc']['cc_high_count']['mean'] - s1['cc']['cc_high_count']['mean']:+6.1f}")
```

### Identify Problem Patterns

```python
import json

with open('checkpoint_results.jsonl', 'r') as f:
    problems = {}
    for line in f:
        cp = json.loads(line)
        problem = cp['problem']
        if problem not in problems:
            problems[problem] = []
        problems[problem].append(cp)

# Find most expensive problem
for problem, checkpoints in problems.items():
    total_cost = sum(cp['cost'] for cp in checkpoints)
    total_time = sum(cp['elapsed'] for cp in checkpoints)
    avg_cc_max = sum(cp['cc_max'] for cp in checkpoints) / len(checkpoints)
    print(f"{problem}: ${total_cost:.2f}, {total_time:.0f}s, avg CC max: {avg_cc_max:.1f}")
```

### Track Quality Trends

```python
import json

with open('checkpoint_results.jsonl', 'r') as f:
    for line in f:
        cp = json.loads(line)
        # Look for degradation patterns
        if cp['delta.lint_errors'] and cp['delta.lint_errors'] > 50:
            print(f"WARNING: {cp['problem']} {cp['checkpoint']} "
                  f"lint errors increased {cp['delta.lint_errors']:.0f}%")
        if cp['cc_max'] > 30:
            print(f"WARNING: {cp['problem']} {cp['checkpoint']} "
                  f"very complex function detected (CC={cp['cc_max']})")
```

## Dashboard Integration

Run-level results are used by the SlopCodeBench dashboard for visualization:
- **Overview page**: Shows solve rates, costs, solve time distributions
- **Checkpoints page**: Time-series of checkpoint metrics across problems
- **Quality page**: Complexity and code quality trends
- **Efficiency page**: Cost, time, token utilization per problem

See dashboard documentation for visualization details.

## Troubleshooting

**Missing checkpoint_results.jsonl?**
- Generated after first checkpoint completes
- Check that run completed without crashing

**Unexpected aggregated values?**
- Verify all checkpoints have quality_analysis/ directories
- Check that evaluation.json exists for each checkpoint

**Delta metrics showing 'inf'?**
- First checkpoint (no prior to compare against) will have inf deltas
- This is expected and can be filtered out if needed

See [Checkpoint Results](checkpoint-results.md) for checkpoint-level troubleshooting.
