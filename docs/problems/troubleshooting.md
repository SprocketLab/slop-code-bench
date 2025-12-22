# Problem Authoring Troubleshooting Guide

This guide provides solutions to common issues encountered when creating and debugging evaluation problems with pytest.

## Table of Contents

- [Test Discovery Issues](#test-discovery-issues)
- [Fixture Issues](#fixture-issues)
- [Configuration Issues](#configuration-issues)
- [Test Execution Issues](#test-execution-issues)
- [Assertion Issues](#assertion-issues)
- [Static Assets Issues](#static-assets-issues)
- [Marker Issues](#marker-issues)
- [Debugging Tools](#debugging-tools)

## Test Discovery Issues

### Problem: "No tests collected"

**Symptoms:**
```
collected 0 items
no tests ran in 0.12s
```

**Causes and fixes:**

#### Cause 1: Test file naming

```bash
# Wrong:
tests/checkpoint_1.py          # Missing 'test_' prefix

# Right:
tests/test_checkpoint_1.py     # Must start with 'test_'
```

#### Cause 2: Test function naming

```python
# Wrong:
def core_passthrough(entrypoint_argv):  # Missing 'test_' prefix
    ...

# Right:
def test_core_passthrough(entrypoint_argv):
    ...
```

#### Cause 3: Wrong tests directory

```
# Wrong:
problem/test/conftest.py       # 'test' not 'tests'

# Right:
problem/tests/conftest.py      # 'tests' directory
```

#### Cause 4: Missing conftest.py

```
tests/
├── test_checkpoint_1.py       # Exists
└── (no conftest.py!)          # Tests may not discover

# Right:
tests/
├── conftest.py                # Required
└── test_checkpoint_1.py
```

### Problem: "test not found" with parametrize

**Symptoms:**
```
ERRORS
E   fixture 'case' not found
```

**Causes and fixes:**

#### Cause: Empty cases list

```python
CORE_CASES = load_cases(CASES_DIR / "core")  # Returns []

@pytest.mark.parametrize("case", CORE_CASES, ids=[c["id"] for c in CORE_CASES])
def test_core(case):  # No tests generated!
    ...
```

**Fix**: Handle empty lists:
```python
CORE_CASES = load_cases(CASES_DIR / "core")

if CORE_CASES:
    @pytest.mark.parametrize("case", CORE_CASES, ids=[c["id"] for c in CORE_CASES])
    def test_core(case):
        ...
```

Or use `pytest.skip`:
```python
@pytest.mark.parametrize("case", CORE_CASES or [{"id": "skip"}], ids=...)
def test_core(case):
    if case.get("id") == "skip":
        pytest.skip("No test cases found")
    ...
```

## Fixture Issues

### Problem: "fixture 'entrypoint_argv' not found"

**Symptoms:**
```
E       fixture 'entrypoint_argv' not found
>       available fixtures: ...
```

**Causes and fixes:**

#### Cause 1: Missing conftest.py

```python
# tests/conftest.py - MUST EXIST
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

#### Cause 2: Typo in fixture name

```python
# Wrong:
def test_basic(entrypoint_arg):  # Missing 'v'
    ...

# Right:
def test_basic(entrypoint_argv):
    ...
```

#### Cause 3: Missing CLI arguments

```bash
# Wrong:
pytest tests/

# Right:
pytest tests/ --entrypoint="python main.py" --checkpoint=checkpoint_1
```

### Problem: "scope mismatch"

**Symptoms:**
```
ScopeMismatch: You tried to access a function scoped fixture from a session scoped one
```

**Causes and fixes:**

```python
# Wrong: session fixture using function-scoped tmp_path
@pytest.fixture(scope="session")
def shared_data(tmp_path):  # tmp_path is function-scoped!
    return tmp_path / "data"

# Right: Match scopes
@pytest.fixture(scope="function")
def test_data(tmp_path):  # Both function-scoped
    return tmp_path / "data"

# Or use tmp_path_factory for session scope
@pytest.fixture(scope="session")
def shared_data(tmp_path_factory):
    return tmp_path_factory.mktemp("data")
```

### Problem: "Error in setup of test"

**Symptoms:**
```
ERROR at setup of test_basic
E   FileNotFoundError: [Errno 2] No such file or directory
```

**Causes and fixes:**

#### Cause: Fixture fails during setup

```python
@pytest.fixture
def assets_dir():
    path = Path(__file__).parent / "assets"
    assert path.exists()  # Fails if directory missing!
    return path
```

**Fix**: Create missing directories or handle gracefully:
```python
@pytest.fixture
def assets_dir():
    path = Path(__file__).parent / "assets"
    if not path.exists():
        pytest.skip("Assets directory not found")
    return path
```

## Configuration Issues

### Problem: "Problem not found"

**Symptoms:**
```
Error: Problem 'my_problem' not found
```

**Causes and fixes:**

#### Cause: Directory name doesn't match config

```yaml
# config.yaml
name: my-problem        # Hyphen

# But directory is:
problems/my_problem/    # Underscore
```

**Fix**: Names must match exactly:
```yaml
name: my_problem
```

### Problem: "Checkpoint not found"

**Symptoms:**
```
Error: Checkpoint 'checkpoint_1' not found for problem 'my_problem'
```

**Causes and fixes:**

#### Cause 1: Missing in config.yaml

```yaml
# config.yaml
checkpoints:
  checkpoint_2:    # No checkpoint_1!
    version: 1
    order: 1
```

**Fix**: Add all checkpoints:
```yaml
checkpoints:
  checkpoint_1:
    version: 1
    order: 1
  checkpoint_2:
    version: 1
    order: 2
```

#### Cause 2: Missing test file

```
tests/
├── conftest.py
└── test_checkpoint_2.py   # No test_checkpoint_1.py!
```

**Fix**: Create test file for each checkpoint.

### Problem: "Invalid marker"

**Symptoms:**
```
PytestUnknownMarkWarning: Unknown pytest.mark.custom_marker
```

**Causes and fixes:**

```yaml
# config.yaml - Register custom markers
markers:
  custom_marker:
    group_type: FUNCTIONALITY
```

Or in conftest.py:
```python
def pytest_configure(config):
    config.addinivalue_line("markers", "custom_marker: description")
```

## Test Execution Issues

### Problem: "Timeout on every test"

**Symptoms:**
- All tests timeout
- No output captured

**Causes and fixes:**

#### Cause 1: Infinite loop in submission

```python
# Agent's code:
while True:
    process_data()  # Never exits!
```

**Fix**: Add timeout to subprocess calls:
```python
result = subprocess.run(
    entrypoint_argv,
    timeout=30,  # 30 second timeout
    capture_output=True
)
```

#### Cause 2: Waiting for input

```python
# Agent's code:
name = input("Enter name: ")  # Hangs waiting for stdin
```

**Fix**: Provide stdin or use --no-input flag in spec.

#### Cause 3: subprocess hangs

```python
# Wrong: No timeout
result = subprocess.run(cmd, capture_output=True)

# Right: With timeout
try:
    result = subprocess.run(cmd, capture_output=True, timeout=30)
except subprocess.TimeoutExpired:
    pytest.fail("Command timed out")
```

### Problem: "ImportError" during execution

**Symptoms:**
```
ImportError: No module named 'yaml'
```

**Causes and fixes:**

#### Cause: Missing dependencies

**Fix 1**: Document in spec:
```markdown
## Requirements

Create a `requirements.txt` or `pyproject.toml`:
```
pyyaml>=6.0
```

**Fix 2**: Add to test_dependencies in config.yaml:
```yaml
test_dependencies:
  - pyyaml>=6.0
```

### Problem: "FileNotFoundError" in tests

**Symptoms:**
```
FileNotFoundError: [Errno 2] No such file or directory: 'input.yaml'
```

**Causes and fixes:**

#### Cause: Working directory issues

```python
# Wrong: Assumes current directory
(Path("input.yaml")).write_text(content)
subprocess.run(cmd)  # May run in different directory

# Right: Use tmp_path
def test_example(entrypoint_argv, tmp_path):
    (tmp_path / "input.yaml").write_text(content)
    subprocess.run(cmd, cwd=tmp_path)  # Explicit cwd
```

## Assertion Issues

### Problem: "AssertionError" with matching output

**Symptoms:**
```
AssertionError: assert '{"key": "value"}' == {'key': 'value'}
```

**Causes and fixes:**

#### Cause: Comparing string to dict

```python
# Wrong: String vs dict
actual = result.stdout  # '{"key": "value"}'
expected = {"key": "value"}
assert actual == expected  # Fails!

# Right: Parse JSON first
import json
actual = json.loads(result.stdout)
assert actual == expected
```

### Problem: "Whitespace differences"

**Symptoms:**
```
AssertionError:
  Expected: 'Hello World'
  Actual:   'Hello World\n'
```

**Causes and fixes:**

```python
# Fix: Strip whitespace
actual = result.stdout.strip()
expected = "Hello World"
assert actual == expected

# Or: Be explicit about expectations
expected = "Hello World\n"
assert result.stdout == expected
```

### Problem: "Floating point differences"

**Symptoms:**
```
AssertionError: assert 1.2300000000000002 == 1.23
```

**Causes and fixes:**

```python
# Fix: Use pytest.approx
import pytest
assert result == pytest.approx(1.23, rel=1e-9)

# Or: Use math.isclose
import math
assert math.isclose(result, 1.23, rel_tol=1e-9)
```

### Problem: "Dict comparison fails on order"

**Symptoms:**
```
AssertionError: assert {'b': 2, 'a': 1} == {'a': 1, 'b': 2}
```

This shouldn't happen in Python 3.7+ (dicts are ordered), but if comparing JSON output:

```python
# Fix: Parse and compare as dicts
actual = json.loads(result.stdout)
expected = {"a": 1, "b": 2}
assert actual == expected  # Dict comparison ignores JSON key order
```

### Problem: "Timestamp/ID differences"

**Symptoms:**
```
AssertionError:
  Expected: {"id": "abc123", "created_at": "2025-01-01T00:00:00Z"}
  Actual:   {"id": "xyz789", "created_at": "2025-01-01T00:00:05Z"}
```

**Causes and fixes:**

```python
# Fix: Strip dynamic fields before comparison
def strip_dynamic(data):
    data = data.copy()
    data.pop("id", None)
    data.pop("created_at", None)
    return data

assert strip_dynamic(actual) == strip_dynamic(expected)

# Or: Validate field presence/types instead
assert "id" in actual
assert isinstance(actual["id"], str)
```

## Static Assets Issues

### Problem: "Static assets not found"

**Symptoms:**
```
FileNotFoundError: static_assets/files not found
```

**Causes and fixes:**

#### Cause 1: Environment variable not set

```python
# In conftest.py
@pytest.fixture(scope="session")
def files_dir():
    env_path = os.environ.get("SCBENCH_ASSET_FILES")
    if env_path:
        return Path(env_path)
    # Fallback for local testing
    return Path(__file__).parent.parent / "static_assets" / "files"
```

**Fix**: Set environment variable or use fallback path.

#### Cause 2: Asset path doesn't exist

```yaml
# config.yaml
static_assets:
  files:
    path: datasets           # But no problems/my_problem/datasets/!
```

**Fix**: Create directory or fix path:
```yaml
static_assets:
  files:
    path: static_assets/files
```

#### Cause 3: Wrong placeholder syntax

```yaml
# Wrong:
arguments: --files {static:files}      # Single braces

# Right:
arguments: --files {{static:files}}    # Double braces
```

## Marker Issues

### Problem: "Tests not categorized correctly"

**Symptoms:**
- Error tests counted as Core
- Functionality tests missing from report

**Causes and fixes:**

#### Cause: Missing markers

```python
# Wrong: No marker = Core
def test_invalid_input(entrypoint_argv):
    ...  # This will be counted as CORE!

# Right: Mark as error
@pytest.mark.error
def test_invalid_input(entrypoint_argv):
    ...
```

### Problem: "Multiple markers conflict"

**Symptoms:**
- Test appears in wrong category
- Unexpected GroupType assignment

**Causes and fixes:**

Priority order (highest to lowest):
1. `regression`
2. `error`
3. `functionality`
4. (unmarked = Core)

```python
# This will be REGRESSION (higher priority)
@pytest.mark.error
@pytest.mark.regression
def test_legacy_error():
    ...

# To make it ERROR, remove regression marker
@pytest.mark.error
def test_legacy_error():
    ...
```

## Debugging Tools

### Tool 1: Run pytest directly

```bash
cd problems/my_problem

# Run with verbose output
pytest tests/ \
  --entrypoint="python solution.py" \
  --checkpoint=checkpoint_1 \
  -v

# Run single test
pytest tests/test_checkpoint_1.py::test_basic \
  --entrypoint="python solution.py" \
  --checkpoint=checkpoint_1 \
  -v

# Show print statements
pytest tests/ ... -s

# Stop on first failure
pytest tests/ ... -x

# Show full assertion diffs
pytest tests/ ... --tb=long
```

### Tool 2: Debug test case manually

```bash
# Create test workspace
mkdir -p /tmp/test_debug
cd /tmp/test_debug

# Copy solution
cp -r /path/to/solution/* .

# Create input files manually
echo "key: value" > input.yaml

# Run command
python solution.py --input input.yaml

# Compare output
```

### Tool 3: Print debugging

```python
def test_example(entrypoint_argv, tmp_path):
    # Setup
    input_file = tmp_path / "input.yaml"
    input_file.write_text("key: value")

    # Debug: Print command
    cmd = entrypoint_argv + ["--input", str(input_file)]
    print(f"Running: {' '.join(cmd)}")

    result = subprocess.run(cmd, capture_output=True, text=True, cwd=tmp_path)

    # Debug: Print output
    print(f"Return code: {result.returncode}")
    print(f"Stdout: {result.stdout}")
    print(f"Stderr: {result.stderr}")

    assert result.returncode == 0
```

Run with `-s` to see print output:
```bash
pytest tests/ ... -s
```

### Tool 4: Validate case files

```bash
# Check all YAML files are valid
find problems/my_problem/tests -name "*.yaml" -exec \
  python -c "import yaml; yaml.safe_load(open('{}'))" \; -print
```

### Tool 5: Check test collection

```bash
# See what tests will be collected
pytest tests/ --collect-only \
  --entrypoint="python main.py" \
  --checkpoint=checkpoint_1

# Output shows all test IDs and markers
```

### Tool 6: Run with PDB

```bash
# Drop into debugger on failure
pytest tests/ ... --pdb

# Or set breakpoint in code
def test_example():
    import pdb; pdb.set_trace()
    ...
```

## Checklist for Debugging

When a problem isn't working:

**Configuration:**
- [ ] `name` in config.yaml matches directory name
- [ ] All checkpoints defined in config.yaml
- [ ] Each checkpoint has a test file
- [ ] static_assets paths exist

**conftest.py:**
- [ ] Defines `pytest_addoption` with --entrypoint and --checkpoint
- [ ] Defines `entrypoint_argv` fixture
- [ ] Defines `checkpoint_name` fixture
- [ ] All fixtures have correct scope

**Test files:**
- [ ] Named `test_checkpoint_N.py`
- [ ] Functions named `test_*`
- [ ] Correct markers applied (error, functionality, regression)
- [ ] Fixtures requested in function signature

**Test execution:**
- [ ] subprocess.run has timeout
- [ ] Using tmp_path for file isolation
- [ ] Parsing output correctly (JSON, JSONL, text)
- [ ] Stripping whitespace where needed

**Assertions:**
- [ ] Comparing same types (both dicts, both strings)
- [ ] Handling dynamic fields (IDs, timestamps)
- [ ] Using pytest.approx for floats

## Next Steps

- **[Pytest Markers](pytest/markers.md)** - Marker reference
- **[Conftest Patterns](pytest/conftest-patterns.md)** - Fixture patterns
- **[CLI Testing](patterns/cli-testing.md)** - subprocess patterns
- **[Examples](examples/)** - Working examples to reference
