---
version: 2.0
last_updated: 2025-12-22
---

# Troubleshooting Guide

This guide covers common issues, debugging techniques, and solutions for the pytest-based evaluation system.

## Quick Diagnostics

When something goes wrong, check:

1. **Exit code**: What was `pytest_exit_code`? (0=ok, 1=failures, 2-5=infrastructure)
2. **Infrastructure failure**: Is `infrastructure_failure: true`?
3. **Tests collected**: Were tests discovered? Check `pytest_collected`
4. **Pytest output**: Read `evaluation/stdout.txt` and `evaluation/stderr.txt`
5. **CTRF report**: Check `evaluation/report.json` for raw results

## Exit Codes

| Code | Meaning | Action |
|------|---------|--------|
| 0 | All tests passed | Success! |
| 1 | Some tests failed | Review failure messages |
| 2 | Interrupted | Check timeout or manual cancel |
| 3 | Internal error | Pytest itself crashed - check stderr |
| 4 | Usage error | Invalid pytest options |
| 5 | No tests collected | Tests not found - check paths |

## Infrastructure Failures

Infrastructure failures mean pytest itself failed to run properly.

### No Tests Collected (Exit Code 5)

**Symptoms:**
- `pytest_collected: 0`
- `infrastructure_failure: true`
- Empty or no test results

**Causes and Solutions:**

1. **Test files not copied correctly**
   ```bash
   # Check test directory in workspace
   ls -la .evaluation_tests/
   ```

2. **Wrong checkpoint in test filename**
   ```
   # Must be: test_checkpoint_1.py (not test_cp1.py)
   problems/my_problem/tests/test_checkpoint_1.py
   ```

3. **Import errors in test file**
   ```bash
   # Check pytest output for import errors
   cat evaluation/stderr.txt
   ```

4. **Missing conftest.py**
   ```python
   # Required in tests/conftest.py
   def pytest_addoption(parser):
       parser.addoption("--entrypoint", action="store", required=True)
       parser.addoption("--checkpoint", action="store", required=True)
   ```

### Collection Errors (Exit Code 3)

**Symptoms:**
- `infrastructure_failure: true`
- Errors in stderr about syntax or imports

**Causes and Solutions:**

1. **Syntax error in test file**
   ```bash
   # Check for Python syntax errors
   python -m py_compile tests/test_checkpoint_1.py
   ```

2. **Missing pytest dependency**
   ```yaml
   # Add to problem config
   test_dependencies:
     - "some-package>=1.0"
   ```

3. **Fixture not defined**
   ```python
   # Make sure conftest.py defines all required fixtures
   @pytest.fixture
   def entrypoint_argv(request):
       return shlex.split(request.config.getoption("--entrypoint"))
   ```

## Test Failures

### All Tests Fail

**Check entrypoint:**
```bash
# The entrypoint passed to tests
cat evaluation/stdout.txt | grep "entrypoint"
```

**Check if submission runs:**
```bash
# Try running manually in workspace
cd outputs/checkpoint_1
python main.py --help
```

### Specific Tests Fail

**Get failure details:**
```python
# Load results and inspect failures
for test in results.tests:
    if test.status == "failed":
        print(f"{test.id}: {test.failure_message}")
```

**Check CTRF report for details:**
```python
import json
with open("evaluation/report.json") as f:
    ctrf = json.load(f)
for test in ctrf["results"]["tests"]:
    if test["status"] == "failed":
        print(test["name"], test.get("message", ""))
```

### Timeout Errors

**Symptoms:**
- Tests killed after timeout
- `pytest-timeout` messages in output

**Solutions:**

1. **Increase checkpoint timeout**
   ```yaml
   checkpoints:
     checkpoint_1:
       timeout: 120  # seconds
   ```

2. **Check for infinite loops in submission**

3. **Check for blocking I/O**

## uvx Issues

### Dependency Installation Fails

**Symptoms:**
- stderr shows pip/uv errors
- `infrastructure_failure: true`

**Solutions:**

1. **Check dependency format**
   ```yaml
   test_dependencies:
     - "requests>=2.28"  # Version specifier
     - "pyyaml"          # Just package name
   ```

2. **Check for incompatible versions**
   ```bash
   # Try installing manually
   uvx --with=pytest --with=my-package pytest --version
   ```

### Package Not Found

**Check PyPI name:**
```bash
pip search my-package  # Verify package exists
```

## Marker Issues

### Unknown Marker Warnings

**Symptoms:**
- "PytestUnknownMarkWarning" in output
- Tests still run but with warnings

**Solutions:**

1. **Register marker in problem config**
   ```yaml
   markers:
     my_marker:
       description: "My custom marker"
       group: Functionality
   ```

2. **Use built-in markers**
   - `@pytest.mark.error` (GroupType.ERROR)
   - `@pytest.mark.functionality` (GroupType.FUNCTIONALITY)
   - `@pytest.mark.regression` (GroupType.REGRESSION)

### Wrong GroupType Assignment

**Check marker precedence:**
1. `@pytest.mark.error` always wins
2. Prior checkpoint tests → REGRESSION
3. Custom markers from config
4. `@pytest.mark.functionality` → FUNCTIONALITY
5. Default → CORE

## Docker Issues

### Container Fails to Start

**Check Docker status:**
```bash
docker ps -a
docker logs <container_id>
```

**Common causes:**
- Port conflicts
- Resource limits
- Image not found

### Network Issues

**Check connectivity:**
```bash
# Inside container
curl -v http://host.docker.internal:8080
```

### Volume Mount Issues

**Check permissions:**
```bash
ls -la /workspace  # Inside container
```

## Debugging Techniques

### Read Pytest Output

```bash
# View stdout (test output)
cat outputs/checkpoint_1/evaluation/stdout.txt

# View stderr (errors and warnings)
cat outputs/checkpoint_1/evaluation/stderr.txt
```

### Examine CTRF Report

```python
import json
with open("outputs/checkpoint_1/evaluation/report.json") as f:
    report = json.load(f)

# Summary
print(f"Passed: {report['results']['summary']['passed']}")
print(f"Failed: {report['results']['summary']['failed']}")

# Individual tests
for test in report["results"]["tests"]:
    print(f"{test['name']}: {test['status']}")
```

### Run Pytest Manually

```bash
# Navigate to workspace with tests
cd outputs/run_123/checkpoint_1

# Run pytest directly (similar to what PytestRunner does)
uvx \
  --with=pytest \
  --with=pytest-json-ctrf \
  --with=pytest-json-report \
  pytest \
  --entrypoint='python main.py' \
  --checkpoint='checkpoint_1' \
  -vv \
  .evaluation_tests/
```

### Enable Verbose Logging

```python
import logging
logging.basicConfig(level=logging.DEBUG)

from slop_code.evaluation import run_checkpoint_pytest
results = run_checkpoint_pytest(...)
```

### Check Test File Copying

```bash
# Verify tests were copied
ls -la outputs/checkpoint_1/.evaluation_tests/

# Should contain:
# - conftest.py
# - test_checkpoint_1.py
# - (possibly test_checkpoint_0.py if include_prior_tests=true)
```

## Common Errors

### "ModuleNotFoundError: No module named 'conftest'"

**Fix**: Add `__init__.py` or check test directory structure
```bash
touch tests/__init__.py  # Sometimes needed
```

### "fixture 'entrypoint_argv' not found"

**Fix**: Define fixture in conftest.py
```python
@pytest.fixture(scope="session")
def entrypoint_argv(request):
    return shlex.split(request.config.getoption("--entrypoint"))
```

### "unrecognized arguments: --entrypoint"

**Fix**: Add pytest_addoption in conftest.py
```python
def pytest_addoption(parser):
    parser.addoption("--entrypoint", action="store", required=True)
    parser.addoption("--checkpoint", action="store", required=True)
```

### "No tests ran"

**Fix**: Check test function names start with `test_`
```python
# Wrong
def check_something():
    ...

# Correct
def test_something():
    ...
```

### "Unable to run submission"

**Fix**: Check entrypoint configuration
```yaml
# Problem config
entry_file: main.py

# Environment config
commands:
  command: python
  entry_file: "{entry_file}"
```

## Performance Issues

### Slow Test Execution

1. **Reduce test count** for development
   ```bash
   pytest -k "test_basic" .evaluation_tests/
   ```

2. **Increase parallelization** (if tests are independent)
   ```yaml
   test_dependencies:
     - "pytest-xdist"
   # Then use: pytest -n auto
   ```

3. **Check for slow submission startup**

### High Memory Usage

1. **Profile tests**
   ```bash
   pytest --memprof .evaluation_tests/
   ```

2. **Reduce test data size**

3. **Use fixtures with proper scope**
   ```python
   @pytest.fixture(scope="session")  # Not "function"
   def expensive_data():
       return load_data()
   ```

## Getting Help

When reporting issues, include:

1. **Exit code and infrastructure_failure status**
2. **Pytest stdout and stderr** (from evaluation/ directory)
3. **Problem config** (especially test_dependencies, markers)
4. **Checkpoint config** (timeout, include_prior_tests)
5. **Test file structure** (list of files in tests/)
6. **Environment** (Python version, Docker version if applicable)

### Example Issue Report

```
Issue: Tests not collected

Exit code: 5
infrastructure_failure: true
pytest_collected: 0

Directory structure:
problems/my_problem/
├── config.yaml
└── tests/
    ├── conftest.py
    └── test_checkpoint_1.py

stderr:
ModuleNotFoundError: No module named 'custom_utils'

config.yaml:
test_dependencies: []  # Missing custom_utils
```

## Next Steps

- **Understand architecture**: [Architecture Guide](architecture.md)
- **Check configuration**: [Configuration Guide](configuration.md)
- **Interpret results**: [Reporting Guide](reporting.md)
