---
version: 1.0
last_updated: 2025-12-17
---

# Metrics Configuration

This guide explains how to configure metrics thresholds and AST-grep rules.

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

## AST-grep Rules

AST-grep rules detect code patterns using structural matching on the AST.

### Rule Location

Rules are stored in `configs/ast-grep-rules/`:

```
configs/ast-grep-rules/
├── naming.yaml       # Identifier quality issues
├── safety.yaml       # Security and safety concerns
├── style.yaml        # Code style violations
├── types.yaml        # Type annotation issues
├── complexity.yaml   # Structural complexity
├── performance.yaml  # Performance anti-patterns
└── verbosity.yaml    # Overly verbose code
```

### Rule Format

Each rule is a YAML document with this structure:

```yaml
---
id: rule-identifier
language: python
severity: warning  # warning, error, info, hint
message: "Human-readable description of the issue"
metadata:
  weight: 2        # Severity weight (1-4)
  category: naming # Category name
rule:
  kind: identifier  # AST node type to match
  regex: "_list$"   # Pattern to match
```

### Rule Weights

Weights indicate severity for weighted scoring:

| Weight | Meaning | Examples |
|--------|---------|----------|
| 1 | Style preference | Verbose identifiers, redundant expressions |
| 2 | Best practice | Generic variable names, missing type hints |
| 3 | Likely problem | Deep nesting, complex conditionals |
| 4 | Bug or security risk | Bare except, dangerous patterns |

### Categories

| Category | Purpose | Example Issues |
|----------|---------|----------------|
| `naming` | Identifier quality | Type suffixes (`users_list`), generic names (`data`) |
| `verbosity` | Redundant code | Excessive comments, obvious docstrings |
| `safety` | Security/safety | Bare except, eval usage |
| `complexity` | Structural complexity | Deep nesting, many branches |
| `style` | Code style | Inconsistent patterns |
| `types` | Type annotations | Missing or incorrect types |
| `performance` | Performance | Inefficient patterns |

### Example Rules

**Type suffix in name** (naming.yaml):
```yaml
---
id: type-in-name
language: python
severity: warning
message: "Variable name includes type suffix - redundant with type annotation"
metadata:
  weight: 1
  category: naming
rule:
  kind: identifier
  regex: "_(list|dict|string|array|int|str|bool|set|tuple|map)$"
```

**Generic placeholder name** (naming.yaml):
```yaml
---
id: generic-placeholder-name
language: python
severity: warning
message: "Generic variable name - use descriptive name"
metadata:
  weight: 1
  category: naming
rule:
  kind: assignment
  has:
    kind: identifier
    field: left
    regex: "^(data|result|temp|item|output|value|obj|ret|res|tmp)$"
```

### Overriding Rules Directory

Set the `AST_GREP_RULES_DIR` environment variable to use a different rules directory:

```bash
export AST_GREP_RULES_DIR=/path/to/custom/rules
slop-code run ...
```

### Writing Custom Rules

1. Create a new YAML file in the rules directory (or add to existing)
2. Use ast-grep pattern syntax for matching
3. Assign appropriate weight and category

**Pattern reference:**

| Pattern | Matches |
|---------|---------|
| `$VAR` | Any single node |
| `$$$` | Zero or more nodes |
| `kind: function_definition` | Specific AST node type |
| `regex: "pattern"` | Node text matching regex |
| `has:` | Node contains child matching pattern |
| `inside:` | Node is inside parent matching pattern |

For full pattern documentation, see [ast-grep docs](https://ast-grep.github.io/).

### Testing Rules

Test a rule against your code:

```bash
# Using ast-grep directly
sg -p 'def $FUNC($$$): pass' -l python path/to/code/

# Scan with rules
sg scan --rule /path/to/rule.yaml path/to/code/
```

## Disabling Metrics

Currently, all metrics run by default. To exclude specific categories from analysis:

1. **Remove rule files**: Delete YAML files from `configs/ast-grep-rules/` to skip those checks
2. **Filter in analysis**: Post-process results to exclude unwanted metrics

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
