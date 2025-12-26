# Creating Problems for SCBench

This guide covers how to create evaluation problems for SCBench using pytest-based tests.

## What is a Problem?

A **problem** is a specification-driven coding challenge that agents must solve. Each problem:

- Defines **checkpoints** - progressive milestones that build on each other
- Uses **pytest** - standard Python testing framework for evaluation
- Tests agent behavior - not just final output, but how agents handle evolving requirements

## Quick Start

Create a problem in 3 steps:

### Step 1: Create Directory Structure

```
problems/my_problem/
├── config.yaml           # Problem metadata
├── checkpoint_1.md       # Spec for checkpoint 1
├── checkpoint_2.md       # Spec for checkpoint 2
└── tests/
    ├── conftest.py       # Required fixtures
    ├── test_checkpoint_1.py
    └── test_checkpoint_2.py
```

### Step 2: Write Minimal config.yaml

```yaml
version: 1
name: my_problem
description: Short description of the problem
entry_file: main.py
timeout: 20
tags:
  - cli

checkpoints:
  checkpoint_1:
    version: 1
    order: 1
    state: Core Tests
```

### Step 3: Create Test Files

**conftest.py** (required fixtures):
```python
import shlex
import pytest

def pytest_addoption(parser):
    parser.addoption("--entrypoint", required=True)
    parser.addoption("--checkpoint", required=True)

@pytest.fixture(scope="session")
def entrypoint_argv(request):
    return shlex.split(request.config.getoption("--entrypoint"))

@pytest.fixture(scope="session")
def checkpoint_name(request):
    return request.config.getoption("--checkpoint")
```

**test_checkpoint_1.py**:
```python
import subprocess
import pytest

def test_basic(entrypoint_argv):
    """Core test - must pass."""
    result = subprocess.run(entrypoint_argv, capture_output=True, text=True)
    assert result.returncode == 0

@pytest.mark.functionality
def test_optional_feature(entrypoint_argv):
    """Functionality test - nice to have."""
    ...

@pytest.mark.error
def test_invalid_input(entrypoint_argv):
    """Error test - must handle gracefully."""
    ...
```

## Problem Structure Overview

```
problems/{problem_name}/
├── config.yaml              # Problem metadata and checkpoint definitions
├── checkpoint_1.md          # Specification for checkpoint 1
├── checkpoint_2.md          # Specification for checkpoint 2
├── tests/
│   ├── conftest.py          # Pytest fixtures (entrypoint_argv, checkpoint_name)
│   ├── test_checkpoint_1.py # Tests for checkpoint 1
│   ├── test_checkpoint_2.py # Tests for checkpoint 2
│   ├── data/                # Test case data (optional)
│   │   └── checkpoint_1/
│   │       ├── core/
│   │       └── errors/
│   └── assets/              # Static files for tests (optional)
└── static_assets/           # Files available to tests (optional)
```

## Test Categorization

Tests are categorized using pytest markers:

| Marker | GroupType | Description |
|--------|-----------|-------------|
| *(none)* | CORE | Must pass - essential functionality |
| `@pytest.mark.functionality` | FUNCTIONALITY | Nice to have - advanced features |
| `@pytest.mark.error` | ERROR | Error handling - edge cases |
| `@pytest.mark.regression` | REGRESSION | Prior checkpoint tests |

Prior checkpoint tests automatically become REGRESSION tests.

## Documentation Guide

### Getting Started (15 min)
- [Quick Reference](quick-reference.md) - Copy-paste templates and commands
- [Tutorial](tutorial.md) - Create your first problem step-by-step

### Core Concepts (30 min)
- [Structure](structure.md) - Directory layout and file purposes
- [Config Schema](config-schema.md) - Complete configuration reference
- [Checkpoints](checkpoints.md) - Designing checkpoint progression

### Pytest System
- [Overview](../pytest/README.md) - How the pytest evaluation works
- [conftest Patterns](../pytest/conftest-patterns.md) - Fixture patterns
- [Markers](../pytest/markers.md) - Built-in and custom markers
- [Test Data](../pytest/test-data.md) - Organizing test data
- [Runner Internals](../pytest/runner-internals.md) - Technical reference
- [Advanced Fixtures](../pytest/fixtures-advanced.md) - Advanced fixture patterns
- [Stateful Testing](../pytest/stateful-testing.md) - State across checkpoints
- [Complex Parametrization](../pytest/complex-parametrization.md) - Advanced case loading
- [Debugging Workflows](../pytest/debugging-workflows.md) - Test debugging and troubleshooting

### Testing Patterns
- [CLI Testing](patterns/cli-testing.md) - Testing command-line tools
- [Stream Testing](patterns/stream-testing.md) - Testing stdin/stdout
- [Parametrized Cases](patterns/parametrized-cases.md) - Loading external test cases
- [Regression Testing](patterns/regression-testing.md) - Testing backward compatibility

### Examples
- [file_backup](examples/file_backup.md) - CLI with parametrized cases
- [etl_pipeline](examples/etl_pipeline.md) - Stream-based inline tests
- [layered_config_synthesizer](examples/layered_config_synthesizer.md) - Advanced patterns

### Troubleshooting
- [Common Issues](troubleshooting.md) - Debugging test failures
