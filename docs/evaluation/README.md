---
version: 2.0
last_updated: 2025-12-22
---

# Evaluation System Documentation

The evaluation module provides a pytest-based framework for testing agent submissions. It executes pytest tests against submission code, categorizes results by type, and generates structured reports.

## 30-Second Overview

Tests are standard pytest files in `problems/{problem}/tests/`. The `PytestRunner` executes them via `uvx` (for isolation), parses results, and categorizes tests using pytest markers:

- **Unmarked tests** in current checkpoint = **CORE** (must pass)
- `@pytest.mark.functionality` = **FUNCTIONALITY** (nice-to-have)
- `@pytest.mark.error` = **ERROR** (edge cases)
- Tests from prior checkpoints = **REGRESSION** (prevent breakage)

## Documentation Guide

### Getting Started
- **New to the evaluation system?** Start with [Architecture Overview](architecture.md)
- **Need to configure a problem?** See [Configuration Guide](configuration.md)

### Implementation
- **Understanding results?** See [Reporting Guide](reporting.md)
- **Debugging failures?** Try [Troubleshooting Guide](troubleshooting.md)

## Core Concepts at a Glance

| Concept | Description |
|---------|-------------|
| **Problem** | Top-level benchmark containing checkpoints and test files |
| **Checkpoint** | A milestone with associated pytest tests |
| **PytestRunner** | Orchestrates pytest execution via uvx |
| **TestResult** | Individual test outcome with categorization |
| **CorrectnessResults** | Aggregated results for a checkpoint |
| **GroupType** | Test category: CORE, FUNCTIONALITY, REGRESSION, ERROR |
| **PassPolicy** | Criteria for checkpoint success (e.g., "core-cases") |
| **Marker** | Pytest decorator for test categorization |

## Test File Structure

```
problems/{problem}/
├── config.yaml              # Problem configuration
└── tests/
    ├── conftest.py          # Shared fixtures (entrypoint, checkpoint)
    ├── test_checkpoint_1.py # Tests for checkpoint 1
    ├── test_checkpoint_2.py # Tests for checkpoint 2
    ├── data/                # Test case data (YAML/JSON)
    └── assets/              # Static test files
```

## Common Workflows

### Evaluating a Submission
```python
from slop_code.evaluation import run_checkpoint_pytest
from slop_code.evaluation import ProblemConfig
from slop_code.execution import EnvironmentSpec

problem = ProblemConfig.from_yaml(Path("problems/file_backup"))
checkpoint = problem.checkpoints["checkpoint_1"]
env = EnvironmentSpec.from_yaml(Path("configs/environments/docker-python3.12-uv.yaml"))

results = run_checkpoint_pytest(
    submission_path=Path("outputs/submission/checkpoint_1"),
    problem=problem,
    checkpoint=checkpoint,
    env_spec=env,
)

print(f"Passed: {results.passes_policy('core-cases')}")
```

### Checking Results
```python
# Check if all CORE tests passed
if results.passes_policy("core-cases"):
    print("Checkpoint passed!")

# Inspect individual test results
for test in results.tests:
    print(f"{test.id}: {test.status} ({test.group_type})")

# Get counts by group type
print(f"Core: {results.pass_counts.get(GroupType.CORE, 0)}/{results.total_counts.get(GroupType.CORE, 0)}")
```

## Key Exports

```python
from slop_code.evaluation import (
    run_checkpoint_pytest,  # Main entry point
    ProblemConfig,          # Problem configuration
    CheckpointConfig,       # Checkpoint configuration
    GroupType,              # CORE, FUNCTIONALITY, REGRESSION, ERROR
    PassPolicy,             # Pass criteria enum
    CorrectnessResults,     # Aggregated results
    TestResult,             # Individual test result
)
```

## Additional Resources

- **Code Location**: `src/slop_code/evaluation/`
- **Example Problem**: `problems/file_backup/` (good reference for test structure)
- **Main Entry Point**: `slop_code.evaluation.pytest_runner.run_checkpoint_pytest()`

## Version History

- **v2.0** (2025-12-22): Complete overhaul for pytest-based evaluation system
- **v1.4** (2025-12-10): Previous Adapter/Loader/Verifier system (deprecated)
