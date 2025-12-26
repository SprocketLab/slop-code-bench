# Debugging Pytest-Based Tests

Reference for systematically debugging test failures in SCBench.

## Overview

This guide covers common test failure patterns and debugging strategies for pytest-based evaluations:

1. **Collection errors** - Tests can't be collected/imported
2. **Fixture setup failures** - Fixture initialization fails
3. **Assertion failures** - Tests run but assertions fail
4. **Parametrized test failures** - Issues with specific test cases
5. **Timeout failures** - Tests exceed time limits
6. **Stateful test failures** - State-dependent tests fail

## Failure Type 1: Test Collection Errors

**Symptoms:** Error message like "ERROR collecting tests" or "fixture 'X' not found"

### Common Causes

1. **Import errors in test files**
2. **Missing or incorrect conftest.py**
3. **Fixture not registered**
4. **Syntax errors in tests**
5. **Missing dependencies**

### Debugging Steps

```bash
# Step 1: See what pytest collects
pytest tests/ --collect-only -q

# Step 2: Get full traceback of collection error
pytest tests/ --collect-only -vv

# Step 3: Check Python import path
python -c "import sys; print(sys.path)"

# Step 4: Try importing test file directly
python -c "from tests.test_checkpoint_1 import *"
```

### Example: Fixture Not Found

**Error:**
```
fixture 'entrypoint_argv' not found
  available fixtures: tmp_path, monkeypatch, capsys
```

**Solution:**
```python
# conftest.py MUST be in tests/ directory
tests/
├── conftest.py    # ← Must define entrypoint_argv here
├── test_checkpoint_1.py
```

```python
# tests/conftest.py
import shlex
import pytest

def pytest_addoption(parser):
    parser.addoption("--entrypoint", required=True)
    parser.addoption("--checkpoint", required=True)

@pytest.fixture(scope="session")
def entrypoint_argv(request):
    return shlex.split(request.config.getoption("--entrypoint"))
```

### Example: Import Error

**Error:**
```
ImportError: cannot import name 'my_helper' from 'tests.case_utils'
```

**Debugging:**
```bash
# Check if file exists
ls tests/case_utils.py

# Check if it has the function
grep -n "def my_helper" tests/case_utils.py

# Try importing
python -c "from tests.case_utils import my_helper"
```

## Failure Type 2: Fixture Setup Failures

**Symptoms:** Error during fixture setup, not in test itself (FAILED in fixture setup)

### Common Causes

1. **Server/resource not starting** (port conflict, permission denied)
2. **File not found** (wrong path)
3. **Invalid fixture dependency** (circular dependency)
4. **Timeout during setup**

### Debugging: Server Fixture Failure

**Error:**
```
E   RuntimeError: Server failed to start within timeout
```

**Debugging steps:**
```python
# Add debugging to fixture
@pytest.fixture(scope="session")
def api_server(entrypoint_argv):
    import socket
    import subprocess

    process = subprocess.Popen(
        entrypoint_argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Debug: Print what we're running
    print(f"Starting: {' '.join(entrypoint_argv)}")

    # Wait for readiness
    for attempt in range(100):
        try:
            with socket.create_connection(("127.0.0.1", 8080), timeout=0.2):
                print(f"Server ready after {attempt} attempts")
                break
        except OSError as e:
            print(f"Attempt {attempt}: {e}")
            if process.poll() is not None:
                stdout, stderr = process.communicate()
                print(f"Process died! Stdout: {stdout}")
                print(f"Stderr: {stderr}")
                raise

    yield "http://127.0.0.1:8080"
    process.terminate()
```

**Run with output visible:**
```bash
# Show print statements
pytest tests/ -s

# Show setup/teardown
pytest tests/ -setup-show

# Show full traceback
pytest tests/ -vv
```

### Debugging: Port Already in Use

**Error:**
```
Address already in use
```

**Solution:**
```bash
# Find what's using port 8080
lsof -i :8080

# Kill the process
kill -9 <PID>

# Or use a different port
# Use ephemeral port selection:
import socket
sock = socket.socket()
sock.bind(('', 0))  # OS picks a free port
port = sock.getsockname()[1]
sock.close()
```

## Failure Type 3: Test Assertion Failures

**Symptoms:** Test runs but assertion fails (FAILED assert ...)

### Common Assertion Patterns

**JSON comparison:**
```python
# Bad: Direct comparison loses precision
assert actual == expected

# Good: Use json for clear diff
import json
print(f"\nExpected:\n{json.dumps(expected, indent=2)}")
print(f"\nActual:\n{json.dumps(actual, indent=2)}")
assert actual == expected
```

**String comparison:**
```python
# Bad: No visible diff
assert actual_str == expected_str

# Good: Show what differs
if actual_str != expected_str:
    print(f"Expected:\n{expected_str}")
    print(f"Actual:\n{actual_str}")
    import difflib
    diff = difflib.unified_diff(
        expected_str.splitlines(),
        actual_str.splitlines(),
        lineterm=""
    )
    print("\n".join(diff))
assert actual_str == expected_str
```

### Debugging: Output Mismatch

**Error:**
```
AssertionError: assert {'result': 5} == {'result': 6}
```

**Debugging steps:**
```python
def test_calculation(entrypoint_argv):
    result = subprocess.run(
        entrypoint_argv + ["--calculate", "2+3"],
        capture_output=True,
        text=True,
    )

    print(f"Exit code: {result.returncode}")
    print(f"Stdout: {result.stdout}")
    print(f"Stderr: {result.stderr}")

    output = json.loads(result.stdout)

    # Add extra debugging
    expected = {"result": 5}
    if output != expected:
        print(f"Keys in actual but not expected: {set(output.keys()) - set(expected.keys())}")
        print(f"Keys in expected but not actual: {set(expected.keys()) - set(output.keys())}")
        for key in expected:
            if key in output:
                print(f"{key}: expected={expected[key]} (type={type(expected[key]).__name__}), actual={output[key]} (type={type(output[key]).__name__})")

    assert output == expected
```

**Run single test with output:**
```bash
pytest tests/test_checkpoint_1.py::test_calculation -xvs
```

### Debugging: Floating Point Comparison

```python
# Bad: Exact comparison fails due to precision
assert actual_float == 0.1

# Good: Use approximation
import pytest
assert actual_float == pytest.approx(0.1)

# Good: Or with tolerance
assert abs(actual_float - 0.1) < 0.0001
```

## Failure Type 4: Parametrized Test Failures

**Symptoms:** One parametrized case fails, others pass (e.g., test_core[case_5] fails but test_core[case_1] passes)

### Debugging Steps

```bash
# Run only the failing case
pytest tests/test_checkpoint_1.py::test_core[case_5] -xvs

# Run with case ID
pytest tests/test_checkpoint_1.py::test_core -k "case_5" -xvs

# See what cases were collected
pytest tests/test_checkpoint_1.py::test_core --collect-only
```

### Debugging: Case Not Found

```bash
# If case doesn't exist in parametrize:
# First, verify it's being discovered
pytest tests/test_checkpoint_1.py --collect-only -q | grep test_core

# Add debug to discover function
def discover_cases(group_dir):
    cases = []
    for entry in sorted(group_dir.iterdir()):
        if entry.is_dir() and (entry / "case.yaml").exists():
            cases.append(entry)
            print(f"Discovered case: {entry.name}")
    return cases
```

### Debugging: Case-Specific Failures

Real example pattern from `layered_config_synthesizer`:

```python
def test_core_case(entrypoint_argv, case_dir, tmp_path):
    """Debug a specific failing case."""
    case_file = case_dir / "case.yaml"
    print(f"\nTesting case: {case_dir.name}")
    print(f"Case file: {case_file}")

    if not case_file.exists():
        pytest.skip(f"Case file not found: {case_file}")

    case = yaml.safe_load(case_file.read_text())
    print(f"Case content: {case}")

    # Run with output visible
    result = subprocess.run(
        entrypoint_argv,
        input=json.dumps(case.get("input")),
        capture_output=True,
        text=True,
    )

    print(f"Exit code: {result.returncode}")
    print(f"Stdout:\n{result.stdout}")
    print(f"Stderr:\n{result.stderr}")

    # Verify expected file exists
    expected_file = case_dir / "expected.json"
    if not expected_file.exists():
        pytest.fail(f"Expected file not found: {expected_file}")

    expected = json.loads(expected_file.read_text())
    print(f"Expected:\n{json.dumps(expected, indent=2)}")

    output = json.loads(result.stdout)
    assert output == expected
```

## Failure Type 5: Timeout Failures

**Symptoms:** Test exceeds timeout (FAILED TimeoutError or similar)

### Debugging

```bash
# Increase timeout to get actual error
pytest tests/ --timeout=300 -xvs

# Find slow tests
pytest tests/ --durations=10  # Show 10 slowest tests

# Run specific test with no timeout
pytest tests/test_checkpoint_1.py::test_slow -xvs --timeout=0
```

### Common Timeout Causes

1. **Infinite loops** in code being tested
2. **Waiting for external service** (server not starting)
3. **Heavy computation** (legitimate but slow)
4. **Deadlock** (test waiting for something that never happens)

### Debugging: Slow Server Startup

```python
@pytest.fixture(scope="session")
def api_server(entrypoint_argv):
    import time

    start = time.time()
    process = subprocess.Popen(
        entrypoint_argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Wait with progress indicator
    for attempt in range(300):  # 30 seconds
        try:
            with socket.create_connection(("127.0.0.1", 8080), timeout=0.1):
                elapsed = time.time() - start
                print(f"Server ready in {elapsed:.1f}s after {attempt} attempts")
                break
        except OSError:
            if attempt % 10 == 0:
                print(f"Still waiting for server... ({attempt/10}s)")
            time.sleep(0.1)
    else:
        raise TimeoutError("Server failed to start")

    yield "http://127.0.0.1:8080"
    process.terminate()
```

## Local Testing Before Docker

Test locally without Docker for faster iteration:

```bash
# Run tests locally (outside Docker)
cd problems/my_problem

# Basic run
pytest tests/ \
  --entrypoint="python solution/main.py" \
  --checkpoint=checkpoint_1

# Verbose with output
pytest tests/ \
  --entrypoint="python solution/main.py" \
  --checkpoint=checkpoint_1 \
  -xvs

# Single test
pytest tests/test_checkpoint_1.py::test_basic \
  --entrypoint="python solution/main.py" \
  --checkpoint=checkpoint_1 \
  -xvs

# With print output visible
pytest tests/ \
  --entrypoint="python solution/main.py" \
  --checkpoint=checkpoint_1 \
  -s

# Stop on first failure
pytest tests/ \
  --entrypoint="python solution/main.py" \
  --checkpoint=checkpoint_1 \
  -x
```

## Workspace Artifacts

After a test run, inspect the workspace for clues:

```
workspace/
├── .scbench/
│   ├── ctrf-report.json        # Test results in CTRF format
│   ├── pytest-report.json      # Detailed pytest results
│   └── pytest.log              # Raw pytest output
├── tests/
│   ├── test_checkpoint_1.py
│   └── conftest.py
└── solution/                   # Submission being tested
    └── main.py
```

**View reports:**
```bash
# Look at test results
cat .scbench/pytest-report.json | python -m json.tool

# View pytest log
cat .scbench/pytest.log | tail -100

# Check CTRF report
cat .scbench/ctrf-report.json | python -m json.tool
```

## Useful Pytest Flags

| Flag | Purpose |
|------|---------|
| `-x` | Stop on first failure |
| `-v` | Verbose output |
| `-vv` | Very verbose (show setup/teardown) |
| `-s` | Show print statements |
| `--tb=short` | Shorter traceback |
| `--tb=long` | Full traceback |
| `-k pattern` | Run tests matching pattern |
| `--collect-only` | Just collect tests, don't run |
| `--lf` | Run last failed |
| `--ff` | Run failed first, then others |
| `-n auto` | Run tests in parallel (pytest-xdist) |
| `--durations=10` | Show 10 slowest tests |
| `--setup-show` | Show fixture setup/teardown |

## Assertion Helpers

Create custom assertion functions for common patterns:

```python
# circuit_eval pattern
def assert_error_payload(payload: dict, *, command: str, error_type: str):
    """Validate error response structure."""
    assert payload.get("ok") is False
    assert payload.get("command") == command

    error = payload.get("error")
    assert isinstance(error, dict)
    assert error.get("type") == error_type

    return error  # Return for further assertions


def test_invalid_command(client):
    response = client.post("/execute", json={"command": "invalid --flag"})
    assert response.status_code == 400

    error = assert_error_payload(
        response.json(),
        command="invalid --flag",
        error_type="InvalidCommandError",
    )
    assert error.get("message") is not None
```

## Case Study: Debugging Layered Config Synthesizer

**Complex multi-checkpoint problem:**

```python
# Checkpoint-specific debugging
def test_core_case(entrypoint_argv, case_dir, tmp_path, checkpoint_name):
    """Debug a complex case with checkpoint awareness."""

    # 1. Load case
    case_file = case_dir / "case.yaml"
    case_data = yaml.safe_load(case_file.read_text())
    print(f"\nCheckpoint: {checkpoint_name}")
    print(f"Case: {case_dir.name}")
    print(f"Input: {json.dumps(case_data.get('input'), indent=2)}")

    # 2. Prepare arguments (checkpoint-aware)
    args = case_data.get("args", [])
    checkpoint_num = int(checkpoint_name.split("_")[1])

    if checkpoint_num >= 2:
        # Checkpoint 2+ needs fragment directory
        fragment_dir = tmp_path / "fragments"
        fragment_dir.mkdir()
        args.extend(["--fragments", str(fragment_dir)])

    # 3. Run
    result = subprocess.run(
        entrypoint_argv + args,
        input=json.dumps(case_data.get("input")),
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )

    print(f"Exit code: {result.returncode}")
    print(f"Stderr: {result.stderr[:500]}")  # First 500 chars

    # 4. Check output exists
    output_file = tmp_path / "output.yaml"
    if not output_file.exists():
        print(f"Output file not found: {output_file}")
        print(f"Files in tmp_path: {list(tmp_path.iterdir())}")
        pytest.fail("No output file generated")

    # 5. Verify output
    actual = yaml.safe_load(output_file.read_text())
    expected_file = case_dir / "expected.yaml"
    expected = yaml.safe_load(expected_file.read_text())

    if actual != expected:
        print(f"\nExpected:\n{yaml.dump(expected, default_flow_style=False)}")
        print(f"\nActual:\n{yaml.dump(actual, default_flow_style=False)}")
        print(f"\nKeys only in actual: {set(actual.keys()) - set(expected.keys())}")
        print(f"Keys only in expected: {set(expected.keys()) - set(actual.keys())}")

    assert actual == expected
```

## Troubleshooting Checklist

- [ ] Check test collection: `pytest --collect-only`
- [ ] Run single test: `pytest test_file.py::test_name -xvs`
- [ ] Check fixture exists in conftest.py
- [ ] Verify paths are absolute or relative to correct dir
- [ ] Check for typos in fixture names
- [ ] Add print statements to fixture
- [ ] Add print statements to test
- [ ] Run with `-s` to see print output
- [ ] Check for port conflicts (server fixtures)
- [ ] Inspect `.scbench/pytest-report.json` for details
- [ ] Try local testing before Docker
- [ ] Check workspace for generated files
- [ ] Increase timeout to find real error

## Next Steps

- [Advanced Fixtures](fixtures-advanced.md) - Fixture debugging
- [Stateful Testing](stateful-testing.md) - State-related issues
- [Complex Parametrization](complex-parametrization.md) - Parametrized test debugging
