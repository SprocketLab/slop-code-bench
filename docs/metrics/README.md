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

### Understanding Your Results
- **New to metrics?** Start with [Interpreting Results](interpreting-results.md) - explains what each metric means
- **Looking at output files?** See [Output Files Reference](output-files.md) - file locations and formats

### Configuration
- **Adjusting thresholds?** Read [Configuration Guide](configuration.md) - thresholds and AST-grep rules

## Core Concepts

| Concept | Description |
|---------|-------------|
| **LOC** | Lines of code (source lines, excluding blanks) |
| **Cyclomatic Complexity (CC)** | Number of independent paths through code (A=1-5, F=41+) |
| **Maintainability Index (MI)** | Composite score of code maintainability (A >= 19) |
| **AST-grep Violations** | Pattern-based code quality issues (verbosity, safety, etc.) |
| **Waste** | Abstraction inefficiencies (trivial wrappers, single-use functions) |
| **Clones** | Duplicate code blocks detected via AST hashing |
| **Delta Metrics** | Percentage changes between checkpoints |

## Common Questions

### What metrics indicate good code quality?
- **CC ratings**: More A/B ratings, fewer D/E/F
- **Lint errors**: Lower is better
- **AST-grep violations**: Lower is better (especially safety/complexity categories)
- **Waste metrics**: Fewer trivial wrappers and single-use functions
- **Clone ratio**: Lower percentage means less duplication

### Where do I find metrics for my run?
Metrics are saved in each checkpoint directory:
```
outputs/run_name/problem_name/checkpoint_N/
├── quality_analysis/
│   ├── overall_quality.json    # Aggregated snapshot metrics
│   ├── files.jsonl             # Per-file metrics
│   └── symbols.jsonl           # Per-function/class metrics
└── ...
```

### How do I compare checkpoints?
Delta metrics (prefixed with `delta.`) show percentage changes:
- `delta.loc`: Lines of code change
- `delta.lint_errors`: Lint error change
- `delta.ast_grep_violations`: Violation change
- `delta.churn_ratio`: Code churn (lines added + removed / prior total)

## Code Location

- **Metrics source**: `src/slop_code/metrics/`
- **AST-grep rules**: `configs/ast-grep-rules/`
- **Main entry point**: `slop_code.metrics.driver.measure_snapshot_quality()`

## Version History

- **v1.0** (2025-12-17): Initial metrics documentation
