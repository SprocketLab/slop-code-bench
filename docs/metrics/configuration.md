---
version: 1.0
last_updated: 2025-12-17
---

# Metrics Configuration

This guide explains how to configure metric thresholds.

## Metrics Thresholds

The `MetricsThresholds` class controls how metrics are categorized into buckets (e.g., "high complexity", "deep nesting").

### Default Values

```python
class MetricsThresholds:
    shallow_nesting_max: int = 1      # Max depth for "shallow" nesting
    deep_nesting_min: int = 4         # Min depth for "deep" nesting
    short_symbol_max: int = 10        # Max lines for "short" symbol
    medium_symbol_max: int = 30       # Max lines for "medium" symbol
    long_symbol_max: int = 75         # Max lines for "long" symbol
    few_expr_max: int = 5             # Max expressions for "few"
    many_expr_min: int = 20           # Min expressions for "many"
    many_control_blocks_min: int = 5  # Min control blocks for "many"
    complex_cc_threshold: int = 10    # CC above this is "complex"
```

### Cyclomatic Complexity Ratings

CC ratings follow the Radon standard and are **not configurable**:

| Rating | CC Range | Risk Level |
|--------|----------|------------|
| A | 1-5 | Low |
| B | 6-10 | Low |
| C | 11-20 | Moderate |
| D | 21-30 | High |
| E | 31-40 | Very High |
| F | 41+ | Untestable |

### Maintainability Index Ratings

MI ratings are also fixed:

| Rating | MI Range | Interpretation |
|--------|----------|----------------|
| A | >= 19 | Highly maintainable |
| B | 10-19 | Moderately maintainable |
| C | < 10 | Difficult to maintain |

## Metric Computation Options

### Entry Language

When measuring a snapshot, specify which file extensions define "source files":

```python
from slop_code.metrics.driver import measure_snapshot_quality

snapshot = measure_snapshot_quality(
    dir_path=Path("code/"),
    entry_extensions={".py"}  # Only .py files are "source" files
)
```

This affects:
- `source_file_count`: Count of files matching entry extensions
- `is_entry_language`: Per-file flag

### Graph Metrics

Dependency graph metrics are computed automatically for Python projects. They require:
- Python files with import statements
- Files reachable from the entry point

If no imports are found or the language doesn't support import tracing, `graph` will be `None` in the output.
