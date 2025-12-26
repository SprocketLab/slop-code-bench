---
version: 1.0
last_updated: 2025-12-17
---

# Metrics System Documentation

The metrics system automatically measures code quality for agent submissions, tracking everything from lines of code to cyclomatic complexity to code clones.

## 30-Second Overview

When an agent completes a checkpoint, the metrics system analyzes the submitted code and generates:
- **Line metrics**: LOC, comments, total lines
- **Lint metrics**: Ruff errors and violations
- **Complexity metrics**: Cyclomatic complexity (A-F ratings), nesting depth
- **Pattern violations**: AST-grep rule violations across 7 categories
- **Code quality**: Waste detection (trivial wrappers, single-use functions), code clones
- **Dependencies**: Graph metrics for import relationships

Results are saved to JSON/JSONL files in each checkpoint's `quality_analysis/` directory.

## Documentation Guide

### Understanding Results at Different Levels

**Checkpoint-level results** (individual checkpoint):
- Want details on test results and quality metrics for a single checkpoint? See [Checkpoint Results](checkpoint-results.md) - covers evaluation.json and quality_analysis/
- Contains correctness (test results) and quality (code metrics) for that checkpoint
- Located in: `checkpoint_N/evaluation.json` and `checkpoint_N/quality_analysis/`

**Run-level results** (aggregated across all checkpoints):
- Comparing runs or analyzing trends across checkpoints? See [Run-Level Results](run-results.md) - aggregated statistics
- Contains solve rates, average costs, efficiency metrics, quality trends
- Located in: `checkpoint_results.jsonl` and `result.json` at run root

### All Metrics
- **New to metrics?** Start with [Interpreting Results](interpreting-results.md) - explains what each metric means
- **Looking at output files?** See [Output Files Reference](output-files.md) - file locations and formats

### Configuration
- **Adjusting thresholds?** Read [Configuration Guide](configuration.md) - thresholds and AST-grep rules

## Core Concepts

| Concept | Description |
|---------|-------------|
| **Checkpoint Results** | Correctness (tests) + Quality (code metrics) for a single checkpoint |
| **Run Summary** | Aggregated statistics across all checkpoints and problems |
| **LOC** | Lines of code (source lines, excluding blanks) |
| **Cyclomatic Complexity (CC)** | Number of independent paths through code (A=1-5, F=41+) |
| **Maintainability Index (MI)** | Composite score of code maintainability (A >= 19) |
| **AST-grep Violations** | Pattern-based code quality issues (verbosity, safety, etc.) |
| **Waste** | Abstraction inefficiencies (trivial wrappers, single-use functions) |
| **Clones** | Duplicate code blocks detected via AST hashing |
| **Delta Metrics** | Percentage changes between checkpoints |
| **Pass Rate** | Percentage of tests passing by category (CORE, FUNCTIONALITY, etc.) |
| **Solve Rate** | Percentage of checkpoints/problems meeting success criteria |

## Common Questions

### What metrics indicate good code quality?
- **CC ratings**: More A/B ratings, fewer D/E/F
- **Lint errors**: Lower is better
- **AST-grep violations**: Lower is better (especially safety/complexity categories)
- **Waste metrics**: Fewer trivial wrappers and single-use functions
- **Clone ratio**: Lower percentage means less duplication

### Where do I find metrics for my run?

Metrics are saved at two levels:

**Checkpoint-level** (detailed for single checkpoint):
```
outputs/run_name/problem_name/checkpoint_N/
├── evaluation.json                       # Test results
├── quality_analysis/
│   ├── overall_quality.json              # Aggregated snapshot metrics
│   ├── files.jsonl                       # Per-file metrics
│   ├── symbols.jsonl                     # Per-function/class metrics
│   └── ast_grep.jsonl                    # Pattern violations
└── evaluation/
    ├── stdout.txt, stderr.txt, report.json  # Test artifacts
```

**Run-level** (aggregated across all checkpoints):
```
outputs/run_name/
├── checkpoint_results.jsonl       # All checkpoint metrics in one file
└── result.json                    # Aggregated statistics and summaries
```

Use checkpoint-level files for detailed analysis of a specific checkpoint. Use run-level files for comparing runs or identifying trends.

### How do I compare checkpoints?
Delta metrics (prefixed with `delta.`) show percentage changes:
- `delta.loc`: Lines of code change
- `delta.lint_errors`: Lint error change
- `delta.ast_grep_violations`: Violation change
- `delta.churn_ratio`: Code churn (lines added + removed / prior total)

## Code Location

- **Quality metrics computation**: `src/slop_code/metrics/`
  - `driver.py`: Main entry point for measuring quality
  - `languages/`: Language-specific parsers (Python, JavaScript, etc.)
  - `checkpoint/`: Checkpoint-level metrics extraction and delta computation
  - `summary/`: Run-level aggregation and summary statistics
- **Evaluation (test results)**: `src/slop_code/evaluation/report.py`
  - `CorrectnessResults`: Test result model
  - `GroupType`: Test categorization (CORE, FUNCTIONALITY, REGRESSION, ERROR)
  - `PassPolicy`: Success criteria
- **AST-grep rules**: `configs/ast-grep-rules/`
- **Main entry points**:
  - Snapshot quality: `slop_code.metrics.driver.measure_snapshot_quality()`
  - Checkpoint metrics: `slop_code.metrics.checkpoint.driver.get_checkpoint_metrics()`
  - Run summary: `slop_code.metrics.summary.aggregators` module

## Version History

- **v1.1** (2025-12-26): Added checkpoint-results.md and run-results.md documentation for two-level metrics hierarchy
- **v1.0** (2025-12-17): Initial metrics documentation
