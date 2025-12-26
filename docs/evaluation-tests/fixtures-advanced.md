# Advanced Fixture Patterns

Reference for advanced pytest fixture patterns found in SCBench problems.

## Overview

This document covers sophisticated fixture patterns for managing complex test setups:
- Session-scoped expensive resources (servers, large datasets)
- Module-scoped state stores (shared mutable state within test files)
- Factory fixtures for dynamic test case generation
- Fixture composition and hierarchies

## Pattern 1: Session-Scoped Expensive Resources

Use session-scoped fixtures for resources with high initialization cost that can be safely reused across all tests.

### Server Startup Fixture

**Real example from `trajectory_api`:**

```python
import socket
import subprocess
import time

@pytest.fixture(scope="session")
def api_server(entrypoint_argv: list[str]) -> str:
    """Start API server once per test session.

    This fixture:
    - Starts the submission server once at session start
    - Waits for readiness with polling
    - Cleans up gracefully at session end
    """
    process = subprocess.Popen(
        entrypoint_argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    base_url = "http://127.0.0.1:8080"

    # Wait for server readiness using connection polling
    for attempt in range(100):
        try:
            with socket.create_connection(("127.0.0.1", 8080), timeout=0.2):
                break
        except OSError:
            if process.poll() is not None:
                # Process died before becoming ready
                raise RuntimeError("Server exited before becoming ready")
            time.sleep(0.1)
    else:
        # Polling exhausted
        raise RuntimeError("Server failed to start within timeout")

    yield base_url

    # Graceful cleanup with fallback to kill
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
```

**Key Points:**
- `scope="session"`: Server runs once for entire test session
- Readiness polling: Check that server is actually ready to accept requests
- Proper cleanup: `terminate()` first, then `kill()` if needed
- Error handling: Detect if process dies before readiness
- Generator pattern: Use `yield` for setup/teardown

### Large Data Fixture

```python
@pytest.fixture(scope="session")
def large_reference_dataset(assets_dir):
    """Load large reference data once, share across all tests.

    Loading large files is expensive, so do it once at session start
    and reuse the parsed data across all tests.
    """
    with open(assets_dir / "large_reference.json") as f:
        return json.load(f)
```

## Pattern 2: Module-Scoped State Stores

Use module-scoped mutable dictionaries to track state created in one test for validation in subsequent tests.

### Real Example from `trajectory_api`

```python
@pytest.fixture(scope="module")
def case_store() -> dict[str, str]:
    """Shared mutable state across all tests in a module.

    Tests that create resources (POST requests) store IDs here.
    Tests that retrieve resources (GET requests) use those IDs.
    """
    return {}


def test_create_trajectory(client, case_store):
    """Create trajectory and store its ID."""
    response = client.post("/trajectories", json={"name": "test"})
    trajectory_id = response.json()["id"]

    # Store for use in later tests
    case_store["trajectory_id"] = trajectory_id

    assert response.status_code == 201


def test_get_trajectory(client, case_store):
    """Retrieve trajectory using ID from earlier test."""
    trajectory_id = case_store["trajectory_id"]

    response = client.get(f"/trajectories/{trajectory_id}")
    assert response.status_code == 200
    assert response.json()["name"] == "test"
```

**When to Use:**
- API testing where one test creates a resource, others use it
- Multi-step workflows that depend on state from previous tests
- Avoiding duplication of expensive setup operations

**Be Careful:**
- Test ordering matters (tests must run in a specific order)
- Can make tests interdependent and harder to debug
- Consider whether state should be per-function instead

## Pattern 3: Factory Fixtures

Factory fixtures return callables that can create objects with varying configurations.

### Command Runner Factory

```python
@pytest.fixture(scope="session")
def create_runner(entrypoint_argv):
    """Factory for creating command runners with different configs."""
    def _create_runner(timeout=30, env=None, extra_args=None):
        """Create a runner with specific configuration.

        Args:
            timeout: Subprocess timeout in seconds
            env: Environment variables override
            extra_args: Additional command-line arguments
        """
        def runner(input_data, additional_args=None):
            cmd = entrypoint_argv.copy()

            if extra_args:
                cmd.extend(extra_args)
            if additional_args:
                cmd.extend(additional_args)

            return subprocess.run(
                cmd,
                input=json.dumps(input_data),
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
            )

        return runner

    return _create_runner


def test_with_custom_timeout(create_runner):
    """Use factory to create runner with longer timeout."""
    runner = create_runner(timeout=60)
    result = runner({"slow_operation": True})
    assert result.returncode == 0
```

### Case Loader Factory

**Real pattern from `layered_config_synthesizer`:**

```python
@pytest.fixture(scope="session")
def load_cases(data_dir):
    """Factory for loading test cases from different directories."""
    def _load(group_name, checkpoint_name=None):
        """Load cases from group directory.

        Args:
            group_name: "core", "errors", "functionality"
            checkpoint_name: "checkpoint_1", "checkpoint_2", etc.
        """
        if checkpoint_name:
            group_dir = data_dir / checkpoint_name / group_name
        else:
            group_dir = data_dir / group_name

        if not group_dir.exists():
            return []

        cases = []
        for case_dir in sorted(group_dir.iterdir()):
            if case_dir.is_dir() and (case_dir / "case.yaml").exists():
                case_data = yaml.safe_load((case_dir / "case.yaml").read_text())
                expected_path = case_dir / "expected.json"
                if expected_path.exists():
                    expected = json.loads(expected_path.read_text())
                else:
                    expected_path = case_dir / "expected.yaml"
                    expected = yaml.safe_load(expected_path.read_text())

                cases.append({
                    "id": case_dir.name,
                    "case": case_data,
                    "expected": expected,
                })

        return cases

    return _load


CORE_CASES = load_cases("core", "checkpoint_1")
ERROR_CASES = load_cases("errors", "checkpoint_1")

@pytest.mark.parametrize("case", CORE_CASES, ids=[c["id"] for c in CORE_CASES])
def test_core_cases(entrypoint_argv, case):
    result = run_case(entrypoint_argv, case["case"])
    assert result == case["expected"]
```

## Pattern 4: Fixture Composition Hierarchies

Build complex fixtures from simpler ones using dependency injection.

### Real Example from `execution_server`

```python
@pytest.fixture(scope="module")
def server_config():
    """Server configuration."""
    return {
        "host": "127.0.0.1",
        "port": 8080,
        "workers": 1,
    }


@pytest.fixture(scope="module")
def server_url(entrypoint_argv, server_config):
    """Start server and provide URL.

    Depends on:
    - entrypoint_argv: how to start the server
    - server_config: where to start it
    """
    host = server_config["host"]
    port = server_config["port"]
    base_url = f"http://{host}:{port}"

    # Start server...
    process = subprocess.Popen(...)

    # Wait for readiness
    time.sleep(1)

    yield base_url

    process.terminate()


@pytest.fixture(scope="module")
def client(server_url):
    """Create HTTP client pointing to server.

    Depends on:
    - server_url: where the server is running
    """
    with httpx.Client(base_url=server_url, timeout=10.0) as http_client:
        yield http_client


@pytest.fixture(scope="class")
def authenticated_client(client):
    """Create authenticated client.

    Depends on:
    - client: base HTTP client
    """
    client.headers["Authorization"] = "Bearer token123"
    return client


class TestExecutionAPI:
    """Tests using composed fixtures."""

    def test_execute(self, client):
        # Uses module-scoped client
        response = client.post("/execute", json={"cmd": "echo hello"})
        assert response.status_code == 200

    def test_auth_required(self, authenticated_client):
        # Uses class-scoped authenticated client
        response = authenticated_client.get("/status")
        assert response.status_code == 200
```

**Fixture Dependency Graph:**
```
server_config
    ↓
entrypoint_argv + server_config
    ↓
server_url
    ↓
client
    ↓
authenticated_client
```

## Pattern 5: Conditional Fixtures

Fixtures that behave differently based on checkpoint or other configuration.

```python
@pytest.fixture(scope="session")
def expected_features(checkpoint_name):
    """Features available in current checkpoint.

    Different checkpoints enable different features.
    Tests use this to conditionally verify features.
    """
    features = {"basic_parsing"}

    if checkpoint_name in {"checkpoint_2", "checkpoint_3"}:
        features.add("advanced_filtering")

    if checkpoint_name == "checkpoint_3":
        features.add("aggregation")

    return features


def test_basic_parsing(entrypoint_argv, expected_features):
    """Always works."""
    assert "basic_parsing" in expected_features


def test_advanced_filtering(entrypoint_argv, expected_features):
    """Only in checkpoint_2+."""
    if "advanced_filtering" not in expected_features:
        pytest.skip("Feature not available in this checkpoint")
    # Test the feature...
```

## Pattern 6: Parametrized Fixtures

Create multiple variations of a fixture.

```python
@pytest.fixture(params=["json", "yaml", "toml"])
def config_format(request):
    """Test with different configuration formats."""
    return request.param


@pytest.fixture
def config_parser(config_format):
    """Parser for specific format."""
    parsers = {
        "json": json.loads,
        "yaml": yaml.safe_load,
        "toml": tomli.loads,
    }
    return parsers[config_format]


def test_parse_valid_config(config_parser, tmp_path):
    """Runs 3 times: once for each config_format."""
    data = {"key": "value"}
    config_file = tmp_path / f"config.{config_format}"
    # ...
```

## Best Practices

### 1. Fixture Scope Decisions

| Scope | Overhead | When to Use |
|-------|----------|------------|
| `function` | Per test | Fresh state for each test (default) |
| `class` | Per class | Shared state for related tests in a class |
| `module` | Per file | Expensive resources within a file |
| `session` | Per run | Very expensive resources, initialized once |

**Choose based on cost vs isolation trade-off:**
- Small cost → use function scope for isolation
- High cost → use module/session scope for efficiency
- Complex setup → use class scope for test organization

### 2. Avoid Fixture Coupling

```python
# Bad: Fixtures depend on implicit order
@pytest.fixture
def first_result(runner):
    return runner({"step": 1})

@pytest.fixture
def second_result(first_result, runner):
    # Depends on first_result running first
    return runner({"step": 2})


# Good: Make dependencies explicit
def test_multiple_steps(runner):
    """Both steps in one test."""
    result1 = runner({"step": 1})
    result2 = runner({"step": 2})

    assert result2.depends_on(result1)
```

### 3. Clean Teardown

Always ensure cleanup happens:

```python
# Good: Using yield for guaranteed cleanup
@pytest.fixture
def temporary_file(tmp_path):
    file = tmp_path / "temp.txt"
    file.write_text("data")
    yield file
    # Cleanup is guaranteed even if test fails
    assert file.exists()


# Bad: Cleanup might not run if test fails
@pytest.fixture
def temporary_file(tmp_path):
    file = tmp_path / "temp.txt"
    file.write_text("data")
    yield file
    file.unlink()  # Won't run if test raises
```

### 4. Document Non-Obvious Fixtures

```python
@pytest.fixture(scope="session")
def strip_version_fields():
    """Remove fields that change between checkpoints.

    Some fields (like 'version', 'timestamp') are added in later
    checkpoints. When comparing output across checkpoints, we need to
    strip these fields to allow proper comparison.

    Returns a function that removes version-related fields from data.
    """
    def _strip(data):
        if isinstance(data, dict):
            data = data.copy()
            for field in ["version", "timestamp", "build_id"]:
                data.pop(field, None)
        return data

    return _strip
```

## Troubleshooting

### Fixture "X" not found
- Verify fixture is defined in `conftest.py` (not in individual test file)
- Check fixture name spelling
- Verify import paths if in helper module

### Fixture scope conflict
```python
# Error: Session fixture depends on function fixture
@pytest.fixture(scope="session")
def bad_fixture(tmp_path):  # tmp_path is function-scoped
    return tmp_path / "file"

# Fix: Use appropriate scope or recreate
@pytest.fixture(scope="session")
def good_fixture(tmp_path_factory):
    return tmp_path_factory.mktemp("session") / "file"
```

### Module-scoped fixture pollution
```python
# Problem: State leaks between test modules
@pytest.fixture(scope="module")
def mutable_state():
    return []  # Reused across modules!

# Solution: Make it session-scoped with clearing, or function-scoped
@pytest.fixture(scope="function")
def isolated_state():
    return []  # Fresh for each test
```

## Next Steps

- [conftest Patterns](conftest-patterns.md) - Basic fixture patterns
- [Stateful Testing](stateful-testing.md) - Testing state across checkpoints
- [Debugging Workflows](debugging-workflows.md) - Debugging fixture issues
