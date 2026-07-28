---
version: 1.0
last_updated: 2025-12-17
---

# Interpreting Metrics Results

This guide explains what each metric means and how to interpret the values in your evaluation results.

## Line Count Metrics

Basic code size measurements computed using Radon.

| Metric | Description | Interpretation |
|--------|-------------|----------------|
| `total_lines` | Total lines in file including blanks | Raw file size |
| `loc` | Source lines of code | Actual code (excludes blanks) |
| `comments` | Total comment lines | Documentation coverage |
| `single_comment` | Single-line comments (`#`) | Inline documentation |
| `multi_comment` | Multi-line comment lines | Block documentation |

## Lint Metrics

Code quality issues detected by Ruff.

| Metric | Description | Interpretation |
|--------|-------------|----------------|
| `lint_errors` | Total violations found | Lower is better |
| `lint_fixable` | Auto-fixable violations | Can be fixed with `ruff --fix` |
| `counts` | Violations by rule code | Identifies specific issues |

**Common Ruff rule prefixes:**
- `E`: pycodestyle errors (style issues)
- `W`: pycodestyle warnings
- `F`: pyflakes (logical errors, unused imports)
- `I`: isort (import ordering)
- `B`: flake8-bugbear (likely bugs)

## Complexity Metrics

Measures code complexity using cyclomatic complexity (CC) and maintainability index (MI).

### Cyclomatic Complexity (CC)

CC counts the number of independent paths through code. Each decision point (if, for, while, and, or, except) adds 1.

**Rating Scale (Radon standard):**

| Rating | CC Range | Interpretation |
|--------|----------|----------------|
| **A** | 1-5 | Simple, low risk |
| **B** | 6-10 | Moderate complexity |
| **C** | 11-20 | Complex, moderate risk |
| **D** | 21-30 | Very complex, high risk |
| **E** | 31-40 | Highly complex |
| **F** | 41+ | Untestable, very high risk |

**Key metrics:**
| Metric | Description |
|--------|-------------|
| `cc_max` | Highest CC in any function |
| `cc_mean` | Average CC across functions |
| `cc_std` | Standard deviation of CC |
| `cc_high_count` | Functions with CC > 10 |
| `cc_extreme_count` | Functions with CC > 30 |
| `cc_concentration` | How unevenly complexity is distributed |

**What to look for:**
- `cc_max` > 20: Consider refactoring the most complex function
- `cc_high_count` > 0: Review functions with CC > 10
- High `cc_concentration`: Complexity concentrated in few functions

### Maintainability Index (MI)

MI is a composite score (0-100) based on LOC, CC, and Halstead metrics.

| Rating | MI Range | Interpretation |
|--------|----------|----------------|
| **A** | >= 19 | Highly maintainable |
| **B** | 10-19 | Moderately maintainable |
| **C** | < 10 | Difficult to maintain |

**Key metrics:**
| Metric | Description |
|--------|-------------|
| `mi_min` | Lowest MI (worst file) |
| `mi_sum` | Sum of MI across files |
| `mi_ratings` | Distribution of A/B/C ratings |

## Function Statistics

Aggregated statistics across all functions and methods.

| Metric | Description | Threshold |
|--------|-------------|-----------|
| `nesting_mean` | Average max nesting depth | > 3 is concerning |
| `nesting_high_count` | Functions with deep nesting | Should be minimized |
| `comparisons_mean` | Average comparison operators | High values indicate complex logic |
| `branches_mean` | Average branch points | High values indicate decision-heavy code |
| `control_mean` | Average control blocks | High values indicate complex flow |
| `lines_mean` | Average lines per function | Long functions may need splitting |

**Concentration metrics** (e.g., `nesting_concentration`) measure how unevenly a metric is distributed. High concentration means a few functions dominate.

## Class Statistics

| Metric | Description |
|--------|-------------|
| `count` | Total number of classes |
| `method_counts_mean` | Average methods per class |
| `attribute_counts_mean` | Average attributes per class |

## Waste Metrics

Detects potential over-abstraction or unnecessary indirection.

| Metric | Description | Why It Matters |
|--------|-------------|----------------|
| `single_use_functions` | Functions called only once | May be premature abstraction |
| `trivial_wrappers` | Functions that just call another function | Unnecessary indirection |
| `single_method_classes` | Classes with only one method | May not need to be a class |

**Interpretation:**
- Some single-use functions are fine (e.g., for readability)
- Trivial wrappers add cognitive overhead without benefit
- Single-method classes might be better as functions

## Redundancy Metrics

Detects duplicate code using AST hashing.

| Metric | Description |
|--------|-------------|
| `clone_instances` | Total duplicate code blocks |
| `clone_lines` | Lines of code in duplicates |
| `clone_ratio` | Percentage of code that's duplicated |
| `files_with_clones` | Number of files containing duplicates |

**Interpretation:**
- High `clone_ratio` (> 10%) suggests refactoring opportunities
- Duplicates often indicate missing abstractions

## Graph Metrics

Dependency analysis based on import relationships (Python only).

| Metric | Description | Interpretation |
|--------|-------------|----------------|
| `node_count` | Files/modules in graph | Codebase size |
| `edge_count` | Import relationships | Coupling indicator |
| `cyclic_dependency_mass` | Ratio of edges in cycles | 0 = no cycles, 1 = all cyclic |
| `propagation_cost` | Average reachability | How changes propagate |
| `dependency_entropy` | Normalized Shannon entropy | Evenness of dependencies |

**What to look for:**
- `cyclic_dependency_mass` > 0: Has circular dependencies (problematic)
- High `propagation_cost`: Changes affect many modules
- Low `dependency_entropy`: Uneven dependency distribution (some modules are hubs)

## Delta Metrics

Percentage changes between consecutive checkpoints.

| Metric | Description | Formula |
|--------|-------------|---------|
| `delta.loc` | LOC change | `(curr - prev) / prev * 100` |
| `delta.verbosity` | `scb-check` verbosity change | Same formula |
| `delta.churn_ratio` | Code churn | `(added + removed) / prev_total` |

**Interpretation:**
- Positive delta: Metric increased (often worse)
- Negative delta: Metric decreased (often better)
- `inf`: Previous value was 0, now non-zero
- 0: No change

## Composite Summary Scores

High-level scores reported by the pinned `scb-check` release and aggregated
across checkpoints.

### Verbosity Score

Measures code bloat and over-abstraction. Lower is better.

### Erosion Score

Measures structural degradation. Lower is better. `scb_check_version` records
the exact checker release used for the checkpoint scores.

## Summary: What Good Code Looks Like

**Target metrics for high-quality submissions:**

| Category | Good | Concerning |
|----------|------|------------|
| CC ratings | Mostly A/B | Multiple D/E/F |
| `cc_max` | < 15 | > 30 |
| `lint_errors` | 0 | > 10 |
| `verbosity` | Lower relative to comparable runs | Higher relative to comparable runs |
| `clone_ratio` | < 5% | > 15% |
| `trivial_wrappers` | 0 | > 3 |
| `cyclic_dependency_mass` | 0 | > 0.1 |

Remember: Context matters. Some complex functions are unavoidable, and metrics are guidelines, not absolute rules.
