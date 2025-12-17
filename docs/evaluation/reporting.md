---
version: 1.3
last_updated: 2025-12-10
---

# Reporting Guide

This guide covers the reporting system, including checkpoint reports, pass policies, scoring, and export formats.

## Overview

The reporting system aggregates verification results from all test cases and provides:

- **Structured results**: Hierarchical organization of test outcomes
- **Scoring**: Weighted scoring across multiple dimensions
- **Pass/fail criteria**: Configurable policies for determining success
- **Export formats**: JSON and Parquet for analysis and storage
- **Detailed diagnostics**: Diffs, timing, and error information

## Report Structure

### Hierarchy

```
CorrectnessResults
├── Group 1 outcomes (GroupReport)
│   └── scores: dict[case_id -> score]
├── Group 2 outcomes (GroupReport)
│   └── ...
├── All VerifierReports (flat list)
├── pass_counts: dict[GroupType -> count]
└── total_counts: dict[GroupType -> count]
```

### CorrectnessResults

The top-level report for a checkpoint evaluation:

```python
class CorrectnessResults(BaseModel):
    problem_name: str                              # Problem identifier
    problem_version: int                           # Problem version number
    name: str                                      # Checkpoint name
    version: int                                   # Checkpoint version
    timestamp: datetime                            # When evaluation ran
    duration: float = 0.0                          # Total evaluation time
    reports: list[VerifierReport] = []             # All case reports
    group_outcomes: dict[str, GroupReport] = {}    # Group summaries
    pass_counts: dict[GroupType, int] = Counter()  # Passing cases by type
    total_counts: dict[GroupType, int] = Counter() # Total cases by type

    def add_group_report(
        self,
        group_name: str,
        group_type: GroupType,
        duration: float,
        reports: list[VerifierReport],
    ) -> None:
        """Add results for a group."""
        ...

    def save(self, save_dir: Path) -> None:
        """Save results to JSON and Parquet files."""
        ...

    @classmethod
    def from_dir(cls, dir: Path) -> CorrectnessResults:
        """Load results from a directory."""
        ...
```

**Key Properties:**

```python
results.problem_name     # "my_benchmark"
results.name             # "checkpoint_1"
results.pass_counts      # {GroupType.CORE: 5, GroupType.FUNCTIONALITY: 10}
results.total_counts     # {GroupType.CORE: 5, GroupType.FUNCTIONALITY: 12}
results.duration         # 123.45 seconds
```

### GroupReport

Aggregate outcome for a single test group:

```python
class GroupReport(BaseModel):
    duration: float                    # Group execution time
    results: dict[str, float]          # case_id -> score (0.0-1.0)
    type: GroupType                    # Group type enum
```

### VerifierReport

Per-case verification results (see [Verification Guide](verification.md)):

```python
class VerifierReport(BaseModel):
    id: str                                   # Case identifier
    group: str                                # Group name
    type: GroupType                           # Group type enum
    timestamp: datetime                       # Verification timestamp
    duration: float                           # Verification duration
    results: dict[str, AttributeResult]       # Attribute name -> result
    case: dict[str, JsonValue] = {}           # Case metadata

    def calculate_score(self) -> float: ...
    def did_pass(self) -> bool: ...
```

## Accessing Report Data

### Basic Access

```python
from slop_code.evaluation import run_checkpoint

# Run evaluation
results = run_checkpoint(...)

# Overall statistics by group type
core_passed = results.pass_counts.get(GroupType.CORE, 0)
core_total = results.total_counts.get(GroupType.CORE, 0)
print(f"Core: {core_passed}/{core_total}")

total_passed = sum(results.pass_counts.values())
total_count = sum(results.total_counts.values())
print(f"Total: {total_passed}/{total_count}")
print(f"Duration: {results.duration:.2f}s")
```

### Iterate Over Groups

```python
for group_name, group_report in results.group_outcomes.items():
    num_passed = sum(1 for score in group_report.results.values() if score >= 1.0)
    num_total = len(group_report.results)
    print(f"\nGroup: {group_name} ({group_report.type.value})")
    print(f"  Passed: {num_passed}/{num_total}")
    print(f"  Duration: {group_report.duration:.2f}s")
```

### Iterate Over Cases

```python
for report in results.reports:
    status = "✓" if report.did_pass() else "✗"
    score = report.calculate_score()
    print(f"{status} {report.group}/{report.id}: {score:.1%}")
```

### Access Specific Case

```python
# Find a specific case report
case_report = next(
    (r for r in results.reports if r.id == "my_case" and r.group == "my_group"),
    None
)

if case_report:
    # Check individual verification results
    for attr, result in case_report.results.items():
        if result.is_correct is False:
            print(f"Failed: {attr}")
            print(f"  {result.diff}")
```

### Filter Failed Cases

```python
# Find all failed cases
failed_reports = [r for r in results.reports if not r.did_pass()]

# Print failures
for report in failed_reports:
    print(f"\nFailed: {report.group}/{report.id}")
    print(f"Score: {report.calculate_score():.1%}")
    for attr, result in report.results.items():
        if result.is_correct is False:
            print(f"  {attr}: {result.diff}")
```

## Pass Policies

Pass policies determine whether a checkpoint passes or fails based on case results by group type.

### PassPolicy Enum

```python
class PassPolicy(str, Enum):
    ANY = "any"                         # At least one case passes
    ANY_CASE = "any-case"               # Same as ANY
    ALL_CASES = "all-cases"             # All cases must pass
    ALL_NON_ERROR_CASES = "all-non-error-cases"  # All non-Error cases pass
    CORE_CASES = "core-cases"           # All Core group cases pass (default)
    ANY_CORE_CASES = "any-core-cases"   # At least one Core case passes
    ALL_CORE_CASES = "all-core-cases"   # Same as CORE_CASES
```

### Policy Types

| Policy | Description | Passes When |
|--------|-------------|-------------|
| `any-case` | At least one case passes | ≥1 case passes |
| `all-cases` | All cases must pass | 100% of cases pass |
| `all-non-error-cases` | Non-Error cases pass | All Functionality/Core/Regression pass |
| `core-cases` | Core group cases pass | All cases in Core groups pass |
| `any-core-cases` | At least one Core case | ≥1 Core case passes |

### Using Pass Policies

```python
from slop_code.evaluation.report import PassPolicy

# Check if results pass a policy
results = run_checkpoint(...)
passed = PassPolicy.CORE_CASES.check(results.pass_counts, results.total_counts)

# Or check multiple policies
for policy in [PassPolicy.ALL_CASES, PassPolicy.CORE_CASES]:
    status = "PASS" if policy.check(results.pass_counts, results.total_counts) else "FAIL"
    print(f"{policy.value}: {status}")
```

### Policy Examples

#### Policy: All Cases Must Pass

```python
PassPolicy.ALL_CASES.check(pass_counts, total_counts)
```

**Behavior:**
- Checkpoint passes only if all cases pass
- Strict: any failure = checkpoint failure
- Use for: Critical functionality, must-have features

#### Policy: Any Case Passes

```python
PassPolicy.ANY_CASE.check(pass_counts, total_counts)
```

**Behavior:**
- Checkpoint passes if at least one case passes
- Lenient: useful for experimental features
- Use for: Exploratory testing, optional features

#### Policy: Core Cases (Default)

```python
PassPolicy.CORE_CASES.check(pass_counts, total_counts)
```

**Behavior:**
- Only cases in `GroupType.CORE` groups must pass
- Other group types (Functionality, Regression, Error) can fail
- Use for: Distinguishing critical vs nice-to-have tests

**Group type assignment:**
```yaml
# checkpoint/config.yaml
groups:
  critical_tests:
    type: Core        # Must pass under CORE_CASES policy

  nice_to_have:
    type: Functionality  # Can fail under CORE_CASES policy

  edge_cases:
    type: Error       # Expected to fail, not counted
```

#### Policy: All Non-Error Cases

```python
PassPolicy.ALL_NON_ERROR_CASES.check(pass_counts, total_counts)
```

**Behavior:**
- All Core, Functionality, and Regression cases must pass
- Error-type cases are excluded from the check
- Use for: Comprehensive testing excluding expected failures

### Default Policy

The default policy is `CORE_CASES` - only cases in Core groups must pass.

## Scoring System

### Hierarchical Scoring

Scores are computed at three levels:

1. **Case Level**: Weighted average of verification results
2. **Group Level**: Average of case scores
3. **Checkpoint Level**: Average of group scores

### Case Score Calculation

```python
# Given verification results with weights
results = {
    "output": VerificationResult(is_correct=True, weight=1.0),
    "status": VerificationResult(is_correct=True, weight=0.5),
    "format": VerificationResult(is_correct=False, weight=0.3),
}

# Score calculation
total_weight = 1.0 + 0.5 + 0.3 = 1.8
correct_weight = 1.0 + 0.5 = 1.5
score = 1.5 / 1.8 = 0.833  # 83.3%
```

### Group Score

Average of case scores:
```python
case_scores = [1.0, 0.8, 0.9, 0.6]
group_score = sum(case_scores) / len(case_scores) = 0.825  # 82.5%
```

### Checkpoint Score

Average of group scores:
```python
group_scores = [0.9, 0.85, 0.92]
checkpoint_score = sum(group_scores) / len(group_scores) = 0.89  # 89%
```

### Weighted Group Scoring

Optionally weight groups differently:

```yaml
# checkpoint/config.yaml
groups:
  - name: critical_tests
    weight: 2.0  # Double weight

  - name: optional_tests
    weight: 0.5  # Half weight
```

**Calculation:**
```python
# Group scores
critical_tests: 0.8 (weight=2.0)
optional_tests: 0.6 (weight=0.5)

# Weighted checkpoint score
score = (0.8 * 2.0 + 0.6 * 0.5) / (2.0 + 0.5)
      = (1.6 + 0.3) / 2.5
      = 0.76  # 76%
```

## Export Formats

### Saving Results

`CorrectnessResults.save()` writes two files to the output directory:

```python
results = run_checkpoint(...)

# Save to directory
results.save(Path("outputs/checkpoint_1"))
# Creates:
#   outputs/checkpoint_1/evaluation.json
#   outputs/checkpoint_1/reports.parquet
```

### JSON Export (evaluation.json)

Contains aggregate statistics (without individual case reports):

```json
{
  "problem_name": "my_benchmark",
  "problem_version": 1,
  "name": "checkpoint_1",
  "version": 1,
  "timestamp": "2025-12-10T10:30:00",
  "duration": 123.45,
  "group_outcomes": {
    "basic_tests": {
      "duration": 45.2,
      "results": {
        "case_1": 1.0,
        "case_2": 0.8,
        "case_3": 1.0
      },
      "type": "Core"
    }
  },
  "pass_counts": {
    "Core": 2,
    "Functionality": 5
  },
  "total_counts": {
    "Core": 3,
    "Functionality": 6
  }
}
```

### Parquet Export (reports.parquet)

Contains detailed per-case verification reports for analytics:

**Parquet Schema:**

| Column | Type | Description |
|--------|------|-------------|
| problem | string | Problem name |
| checkpoint | string | Checkpoint name |
| version | int | Checkpoint version |
| problem_version | int | Problem version |
| id | string | Case identifier |
| group | string | Group name |
| type | string | Group type (Core, Functionality, etc.) |
| timestamp | datetime | Verification timestamp |
| duration | float | Verification duration (seconds) |
| results | list[dict] | Per-attribute verification results |
| case | list[dict] | Case input metadata |
| original_checkpoint | string | For regression cases |
| original_group | string | For regression cases |

**Query with pandas/polars:**
```python
import pandas as pd

# Read Parquet
df = pd.read_parquet("outputs/checkpoint_1/reports.parquet")

# Basic analysis
print(f"Total cases: {len(df)}")
print(f"Groups: {df['group'].unique()}")

# Load from directory
from slop_code.evaluation.report import CorrectnessResults
results = CorrectnessResults.from_dir(Path("outputs/checkpoint_1"))
```

### CSV Export

Convert to CSV for spreadsheet compatibility:

```python
import pandas as pd

# From CorrectnessResults
cases = []
for report in results.reports:
    cases.append({
        "group": report.group,
        "case_id": report.id,
        "type": report.type.value,
        "passed": report.did_pass(),
        "score": report.calculate_score(),
        "duration": report.duration,
    })

df = pd.DataFrame(cases)
df.to_csv("results.csv", index=False)
```

## Detailed Diagnostics

### Timing Information

```python
# Total timing
print(f"Total time: {results.duration:.2f}s")

# Group timing
for group_name, group_report in results.group_outcomes.items():
    print(f"{group_name}: {group_report.duration:.2f}s")

# Case timing
for report in results.reports:
    print(f"  {report.group}/{report.id}: {report.duration:.3f}s")
```

### Diff Information

```python
# Print all diffs for failed cases
for report in results.reports:
    if not report.did_pass():
        print(f"\n{report.group}/{report.id}:")
        for attr, result in report.results.items():
            if result.is_correct is False:
                print(f"\n{attr}:")
                print(result.diff)
```

### Failure Analysis

```python
# Group failures by type
from collections import defaultdict

failures_by_type = defaultdict(list)
for report in results.reports:
    if not report.did_pass():
        failures_by_type[report.type].append(report)

# Print summary
print("Failures by group type:")
for group_type, failed in failures_by_type.items():
    print(f"  {group_type.value}: {len(failed)} cases")
    for report in failed[:3]:  # Show first 3
        print(f"    - {report.group}/{report.id}")
```

## Custom Report Formatting

### Summary Report

```python
def print_summary(results: CorrectnessResults):
    """Print concise summary report."""
    total_passed = sum(results.pass_counts.values())
    total_count = sum(results.total_counts.values())
    passed = PassPolicy.CORE_CASES.check(results.pass_counts, results.total_counts)

    print(f"{'='*60}")
    print(f"Problem: {results.problem_name}")
    print(f"Checkpoint: {results.name}")
    print(f"{'='*60}")
    print(f"Status: {'PASS' if passed else 'FAIL'}")
    print(f"Passed: {total_passed}/{total_count} cases")
    print(f"Time: {results.duration:.2f}s")
    print(f"{'='*60}")

    for group_name, group_report in results.group_outcomes.items():
        num_passed = sum(1 for s in group_report.results.values() if s >= 1.0)
        num_total = len(group_report.results)
        status = "✓" if num_passed == num_total else "✗"
        print(f"{status} {group_name} ({group_report.type.value}): {num_passed}/{num_total}")

print_summary(results)
```

### Detailed Report

```python
def print_detailed(results: CorrectnessResults):
    """Print detailed report with all case results."""
    # Group reports by group name
    reports_by_group = {}
    for report in results.reports:
        reports_by_group.setdefault(report.group, []).append(report)

    for group_name, case_reports in reports_by_group.items():
        group_info = results.group_outcomes.get(group_name)
        print(f"\n{'='*60}")
        print(f"Group: {group_name} ({group_info.type.value if group_info else 'Unknown'})")
        print(f"{'='*60}")

        for report in case_reports:
            passed = report.did_pass()
            score = report.calculate_score()
            status = "✓ PASS" if passed else "✗ FAIL"
            print(f"\n{status}: {report.id} ({score:.1%})")

            for attr, result in report.results.items():
                if result.is_correct is not None:
                    symbol = "✓" if result.is_correct else "✗"
                    print(f"  {symbol} {attr} (weight={result.weight})")
                    if result.is_correct is False:
                        print(f"    {result.diff}")

print_detailed(results)
```

### HTML Report

```python
def generate_html_report(results: CorrectnessResults, output_file: str):
    """Generate HTML report."""
    total_passed = sum(results.pass_counts.values())
    total_count = sum(results.total_counts.values())
    passed = PassPolicy.CORE_CASES.check(results.pass_counts, results.total_counts)

    html = f"""
    <html>
    <head>
        <title>Report: {results.problem_name}/{results.name}</title>
        <style>
            .pass {{ color: green; }}
            .fail {{ color: red; }}
            .score {{ font-weight: bold; }}
        </style>
    </head>
    <body>
        <h1>{results.problem_name} - {results.name}</h1>
        <p class="{'pass' if passed else 'fail'}">
            Status: {'PASS' if passed else 'FAIL'}
        </p>
        <p>Passed: {total_passed}/{total_count}</p>
        <p>Time: {results.duration:.2f}s</p>

        <h2>Groups</h2>
    """

    for group_name, group_report in results.group_outcomes.items():
        num_passed = sum(1 for s in group_report.results.values() if s >= 1.0)
        num_total = len(group_report.results)
        css_class = 'pass' if num_passed == num_total else 'fail'
        html += f"""
        <h3 class="{css_class}">
            {group_name} ({num_passed}/{num_total})
        </h3>
        <ul>
        """

        for case_id, score in group_report.results.items():
            css_class = 'pass' if score >= 1.0 else 'fail'
            html += f'<li class="{css_class}">{case_id}: {score:.1%}</li>'

        html += "</ul>"

    html += "</body></html>"

    with open(output_file, "w") as f:
        f.write(html)

generate_html_report(results, "report.html")
```

## Analytics and Aggregation

### Aggregate Across Multiple Runs

```python
import pandas as pd
from pathlib import Path
from slop_code.evaluation.report import CorrectnessResults

# Load results from multiple runs
run_dirs = [
    Path("outputs/run_1/checkpoint_1"),
    Path("outputs/run_2/checkpoint_1"),
    Path("outputs/run_3/checkpoint_1"),
]

results_list = [CorrectnessResults.from_dir(d) for d in run_dirs]

# Convert to DataFrame
data = []
for i, results in enumerate(results_list):
    total_passed = sum(results.pass_counts.values())
    total_count = sum(results.total_counts.values())
    data.append({
        "run": i,
        "passed": total_passed,
        "total": total_count,
        "pass_rate": total_passed / total_count if total_count > 0 else 0,
        "duration": results.duration
    })

df = pd.DataFrame(data)

# Analyze
print(f"Average pass rate: {df['pass_rate'].mean():.1%}")
print(f"Average time: {df['duration'].mean():.2f}s")
```

### Track Changes Over Time

```python
import glob
from pathlib import Path

# Find all evaluation results
eval_files = sorted(glob.glob("outputs/*/checkpoint_1/evaluation.json"))

for file in eval_files:
    results = CorrectnessResults.from_dir(Path(file).parent)
    total_passed = sum(results.pass_counts.values())
    total_count = sum(results.total_counts.values())
    print(f"{results.timestamp}: {total_passed}/{total_count}")
```

## Next Steps

- **Debug failures**: [Troubleshooting Guide](troubleshooting.md)
- **Improve verification**: [Verification Guide](verification.md)
- **Understand architecture**: [Architecture Guide](architecture.md)
