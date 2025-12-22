# conftest.py Patterns

Reference for pytest fixture patterns in SCBench problem tests.

## Required Fixtures

Every problem's `tests/conftest.py` must include these fixtures:

```python
"""Pytest configuration for my_problem evaluation."""

import shlex

import pytest


def pytest_addoption(parser):
    """Register required CLI options for SCBench evaluation."""
    parser.addoption("--entrypoint", required=True)
    parser.addoption("--checkpoint", required=True)


@pytest.fixture(scope="session")
def entrypoint_argv(request):
    """Get submission entrypoint as argv list.

    Returns the command to invoke the agent's submission,
    split into an argv-style list for subprocess.run().

    Example: "python main.py" -> ["python", "main.py"]
    """
    return shlex.split(request.config.getoption("--entrypoint"))


@pytest.fixture(scope="session")
def checkpoint_name(request):
    """Get current checkpoint name.

    Returns the checkpoint being evaluated (e.g., "checkpoint_1").
    Useful for checkpoint-aware test logic.
    """
    return request.config.getoption("--checkpoint")
```

## Optional Fixtures

### Assets Directory

```python
from pathlib import Path


@pytest.fixture(scope="session")
def assets_dir():
    """Path to test assets directory.

    Returns: Path to tests/assets/
    """
    return Path(__file__).parent / "assets"
```

### Data Directory

```python
@pytest.fixture(scope="session")
def data_dir():
    """Path to test data directory.

    Returns: Path to tests/data/
    """
    return Path(__file__).parent / "data"


@pytest.fixture(scope="session")
def checkpoint_data_dir(data_dir, checkpoint_name):
    """Path to current checkpoint's data directory.

    Returns: Path to tests/data/checkpoint_N/
    """
    return data_dir / checkpoint_name
```

### Files Directory (Static Assets)

```python
import os


@pytest.fixture(scope="session")
def files_dir():
    """Path to problem's static files directory.

    Uses SCBENCH_ASSET_FILES environment variable if set,
    otherwise falls back to tests/assets/files.
    """
    env_path = os.environ.get("SCBENCH_ASSET_FILES")
    if env_path:
        return Path(env_path)
    return Path(__file__).parent / "assets" / "files"
```

## Fixture Scope

### Session Scope (Recommended)

Use `scope="session"` for fixtures that don't change between tests:

```python
@pytest.fixture(scope="session")
def entrypoint_argv(request):
    """Shared across all tests in the session."""
    return shlex.split(request.config.getoption("--entrypoint"))
```

### Function Scope (Default)

Use for fixtures that need fresh state per test:

```python
@pytest.fixture
def temp_workspace(tmp_path):
    """Fresh temporary directory for each test."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return workspace
```

### Module Scope

Use for fixtures shared within a test file:

```python
@pytest.fixture(scope="module")
def loaded_cases():
    """Load cases once per test file."""
    return load_cases(CHECKPOINT_DIR / "core")
```

## Complete conftest.py Examples

### Minimal (Inline Tests)

For problems with inline test data:

```python
"""Minimal conftest.py for inline tests."""

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

### With Assets (External Data)

For problems with external test data:

```python
"""conftest.py with asset directories."""

import shlex
from pathlib import Path

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


@pytest.fixture(scope="session")
def assets_dir():
    """Path to tests/assets/."""
    return Path(__file__).parent / "assets"


@pytest.fixture(scope="session")
def data_dir():
    """Path to tests/data/."""
    return Path(__file__).parent / "data"


@pytest.fixture(scope="session")
def checkpoint_data(data_dir, checkpoint_name):
    """Path to current checkpoint's data."""
    return data_dir / checkpoint_name
```

### With Helper Fixtures

For problems with complex test setup:

```python
"""conftest.py with helper fixtures."""

import json
import shlex
import subprocess
from pathlib import Path

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


@pytest.fixture(scope="session")
def run_command(entrypoint_argv):
    """Factory fixture for running commands.

    Usage:
        def test_example(run_command):
            result = run_command({"key": "value"})
            assert result.returncode == 0
    """
    def _run(input_data, extra_args=None):
        cmd = entrypoint_argv.copy()
        if extra_args:
            cmd.extend(extra_args)

        input_str = json.dumps(input_data) if isinstance(input_data, dict) else input_data

        return subprocess.run(
            cmd,
            input=input_str,
            capture_output=True,
            text=True,
            timeout=30,
        )

    return _run


@pytest.fixture(scope="session")
def parse_output():
    """Factory for parsing command output."""
    def _parse(result):
        if result.returncode != 0:
            return None
        return json.loads(result.stdout)

    return _parse
```

## Checkpoint-Aware Fixtures

### Conditional Logic

```python
@pytest.fixture(scope="session")
def expected_features(checkpoint_name):
    """Features available in current checkpoint."""
    features = {"basic_parse"}

    if checkpoint_name in {"checkpoint_2", "checkpoint_3"}:
        features.add("advanced_filter")

    if checkpoint_name == "checkpoint_3":
        features.add("aggregation")

    return features
```

### Version-Specific Behavior

```python
@pytest.fixture(scope="session")
def output_format(checkpoint_name):
    """Expected output format for checkpoint."""
    if checkpoint_name == "checkpoint_1":
        return "json"
    else:
        return "jsonl"
```

## Factory Fixtures

### Command Runner Factory

```python
@pytest.fixture(scope="session")
def create_runner(entrypoint_argv):
    """Create a command runner with specific config."""
    def _create(timeout=30, env=None):
        def runner(input_data, args=None):
            cmd = entrypoint_argv.copy()
            if args:
                cmd.extend(args)

            return subprocess.run(
                cmd,
                input=json.dumps(input_data),
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
            )
        return runner

    return _create
```

### Case Loader Factory

```python
@pytest.fixture(scope="session")
def load_cases(data_dir):
    """Factory for loading test cases from directory."""
    def _load(group_name, checkpoint_name):
        group_dir = data_dir / checkpoint_name / group_name
        cases = []

        for case_dir in sorted(group_dir.iterdir()):
            if case_dir.is_dir():
                case = yaml.safe_load((case_dir / "case.yaml").read_text())
                expected = json.loads((case_dir / "expected.json").read_text())
                cases.append({
                    "id": case_dir.name,
                    "case": case,
                    "expected": expected,
                })

        return cases

    return _load
```

## Best Practices

### Use Session Scope for Expensive Setup

```python
# Good: Load once, share across tests
@pytest.fixture(scope="session")
def reference_data(assets_dir):
    with open(assets_dir / "large_reference.json") as f:
        return json.load(f)

# Bad: Reload for every test
@pytest.fixture
def reference_data(assets_dir):
    with open(assets_dir / "large_reference.json") as f:
        return json.load(f)
```

### Keep Fixtures Focused

```python
# Good: Single responsibility
@pytest.fixture(scope="session")
def entrypoint_argv(request):
    return shlex.split(request.config.getoption("--entrypoint"))


@pytest.fixture(scope="session")
def run_command(entrypoint_argv):
    def _run(input_data):
        return subprocess.run(entrypoint_argv, ...)
    return _run


# Bad: Mixed responsibilities
@pytest.fixture
def everything(request):
    argv = shlex.split(request.config.getoption("--entrypoint"))
    def run(data):
        return subprocess.run(argv, ...)
    return {"argv": argv, "run": run}
```

### Document Non-Obvious Fixtures

```python
@pytest.fixture(scope="session")
def strip_regression_fields():
    """Remove fields that change between checkpoints.

    Some fields (like 'version' or 'timestamp') are added in later
    checkpoints. When running regression tests, strip these fields
    to allow comparison with checkpoint_1 expectations.
    """
    def _strip(data):
        data = data.copy()
        for field in ["version", "timestamp", "checkpoint"]:
            data.pop(field, None)
        return data

    return _strip
```

## Next Steps

- [Markers](markers.md) - Test categorization
- [Test Data](test-data.md) - Organizing test data
- [CLI Testing](../patterns/cli-testing.md) - CLI patterns
