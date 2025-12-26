# Pytest Evaluation System

Overview of how SCBench uses pytest to evaluate agent submissions.

## Why Pytest?

SCBench uses pytest as its evaluation framework because:

1. **Standard tooling** - Familiar to Python developers
2. **Rich ecosystem** - Fixtures, parametrization, markers, plugins
3. **Flexible assertions** - Clear failure messages
4. **Isolated execution** - Tests run independently

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                     PytestRunner                             │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  1. Copy tests from problem/tests/ to workspace              │
│  2. Generate pytest.ini with markers                         │
│  3. Execute via uvx for isolation                            │
│  4. Parse CTRF + pytest-json-report                          │
│  5. Categorize results by GroupType                          │
│                                                              │
└─────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                    Test Execution                            │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  pytest tests/                                               │
│    --entrypoint="python main.py"                             │
│    --checkpoint=checkpoint_1                                 │
│    --ctrf=.scbench/ctrf-report.json                         │
│    --json-report                                             │
│                                                              │
└─────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                    Test Results                              │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  TestResult(                                                 │
│    name="test_basic_case",                                   │
│    passed=True,                                              │
│    group_type=GroupType.CORE,                                │
│    duration=0.5,                                             │
│  )                                                           │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

## Key Concepts

### Required Fixtures

Every problem's `tests/conftest.py` must provide:

```python
@pytest.fixture(scope="session")
def entrypoint_argv(request):
    """Command to invoke the submission."""
    return shlex.split(request.config.getoption("--entrypoint"))

@pytest.fixture(scope="session")
def checkpoint_name(request):
    """Current checkpoint being evaluated."""
    return request.config.getoption("--checkpoint")
```

### Test Markers

Tests are categorized using pytest markers:

| Marker | GroupType | Purpose |
|--------|-----------|---------|
| *(none)* | CORE | Must pass - essential functionality |
| `@pytest.mark.functionality` | FUNCTIONALITY | Nice to have - advanced features |
| `@pytest.mark.error` | ERROR | Error handling - edge cases |
| `@pytest.mark.regression` | REGRESSION | Prior checkpoint tests |

### Test File Naming

Tests must follow the naming convention:
- `test_checkpoint_1.py` for checkpoint 1
- `test_checkpoint_2.py` for checkpoint 2
- etc.

This naming is used to:
1. Determine which tests belong to which checkpoint
2. Include prior checkpoint tests when `include_prior_tests: true`

## Execution Flow

1. **Session Creation**
   - Create workspace with agent's submission
   - Copy test files from problem directory

2. **Test Selection**
   - Include `test_checkpoint_N.py` for current checkpoint
   - If `include_prior_tests: true`, include earlier checkpoints

3. **pytest.ini Generation**
   - Register built-in markers (error, functionality, regression)
   - Register custom markers from `config.yaml`

4. **Test Execution**
   - Run via `uvx` for environment isolation
   - Pass `--entrypoint` and `--checkpoint` options
   - Generate CTRF and pytest-json reports

5. **Result Parsing**
   - Parse test outcomes from reports
   - Categorize by GroupType based on markers
   - Prior checkpoint tests become REGRESSION type

## Test Isolation

Tests run in an isolated environment:

- **uvx**: Ensures clean Python environment
- **Session scope**: Fixtures shared within session
- **Workspace**: Agent submission in isolated directory

## Report Formats

### CTRF Report
```json
{
  "results": {
    "tests": [
      {
        "name": "test_basic_case",
        "status": "passed",
        "duration": 0.5,
        "filePath": "tests/test_checkpoint_1.py",
        "tags": ["functionality"]
      }
    ]
  }
}
```

### pytest-json-report
```json
{
  "tests": [
    {
      "nodeid": "tests/test_checkpoint_1.py::test_basic_case",
      "outcome": "passed",
      "duration": 0.5,
      "markers": ["functionality"]
    }
  ]
}
```

## Documentation

### Core Concepts
- [conftest Patterns](conftest-patterns.md) - Fixture patterns and examples
- [Markers](markers.md) - Built-in and custom markers
- [Test Data](test-data.md) - Organizing test data
- [Runner Internals](runner-internals.md) - Technical reference

### Advanced Topics
- [Advanced Fixtures](fixtures-advanced.md) - Session/module scopes, factories, composition
- [Stateful Testing](stateful-testing.md) - State across checkpoints and sessions
- [Complex Parametrization](complex-parametrization.md) - External data loading patterns
- [Debugging Workflows](debugging-workflows.md) - Test debugging and troubleshooting

## Next Steps

- [Quick Reference](../problems/quick-reference.md) - Templates and commands
- [Tutorial](../problems/tutorial.md) - Create your first problem
- [Examples](../problems/examples/) - Real problem walkthroughs
