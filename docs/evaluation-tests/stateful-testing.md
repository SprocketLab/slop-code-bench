# Stateful Testing: Across Checkpoints and Sessions

Reference for testing patterns that maintain and verify state across test boundaries.

## Overview

**Stateful testing** involves tests that depend on state created by previous tests. This is especially important in SCBench where:

1. **Multi-checkpoint problems** - State from checkpoint 1 may persist into checkpoint 2
2. **API tests** - Tests that create resources (POST) followed by tests that retrieve them (GET)
3. **Long-running workflows** - Multi-step processes where each step builds on the previous

## Pattern 1: Class-Scoped Server Fixtures

Use class-scoped fixtures for long-lived services used by multiple test methods in the same class.

### Example from `execution_server`

```python
@pytest.fixture(scope="class")
def server_url(entrypoint_argv):
    """Start one server for entire test class.

    This server instance is reused by all test methods in the class,
    reducing overhead compared to per-test startup.
    """
    process = subprocess.Popen(
        entrypoint_argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Wait for readiness
    for _ in range(50):
        try:
            with socket.create_connection(("127.0.0.1", 8080), timeout=0.2):
                break
        except OSError:
            time.sleep(0.1)

    base_url = "http://127.0.0.1:8080"
    yield base_url

    process.terminate()
    process.wait(timeout=5)


@pytest.fixture(scope="class")
def client(server_url):
    """HTTP client pointing to shared server."""
    with httpx.Client(base_url=server_url, timeout=10.0) as http_client:
        yield http_client


class TestExecutionServer:
    """All tests in this class share the same server instance."""

    def test_execute_simple_command(self, client):
        response = client.post("/execute", json={
            "command": "echo hello"
        })
        assert response.status_code == 200
        assert response.json()["stdout"] == "hello\n"

    def test_execute_with_timeout(self, client):
        response = client.post("/execute", json={
            "command": "sleep 100",
            "timeout": 1,
        })
        assert response.status_code == 200
        assert response.json()["timed_out"] is True

    def test_execute_captures_stderr(self, client):
        response = client.post("/execute", json={
            "command": "echo error >&2"
        })
        assert response.status_code == 200
        assert response.json()["stderr"] == "error\n"
```

**Why Class Scope?**
- Efficient: One server for all tests in a class
- Isolated: Separate class = separate server
- Logical: Groups related tests together
- Flexible: Multiple classes can have different server configs

## Pattern 2: Module-Scoped Mutable State Stores

Use module-scoped dictionaries to track state created in one test for validation in subsequent tests.

### Real Example from `trajectory_api`

```python
@pytest.fixture(scope="module")
def case_store():
    """Shared mutable state across all tests in a module.

    Tests that create resources store their IDs here.
    Tests that query those resources retrieve IDs from here.
    """
    return {
        "trajectory_ids": [],
        "event_ids": [],
        "assertions": [],
    }


def test_01_create_trajectory(client, case_store):
    """Create a trajectory and store its ID."""
    response = client.post("/trajectories", json={
        "name": "test_trajectory",
        "description": "Created in test_01",
    })

    assert response.status_code == 201
    trajectory_data = response.json()
    trajectory_id = trajectory_data["id"]

    # Store for use in later tests
    case_store["trajectory_ids"].append(trajectory_id)
    case_store["assertions"].append({
        "created_trajectory": trajectory_id,
    })


def test_02_list_trajectories(client, case_store):
    """List trajectories, should include the one from test_01."""
    response = client.get("/trajectories")

    assert response.status_code == 200
    trajectory_ids = [t["id"] for t in response.json()]

    # Verify trajectory from test_01 appears in list
    for stored_id in case_store["trajectory_ids"]:
        assert stored_id in trajectory_ids


def test_03_get_trajectory(client, case_store):
    """Retrieve the trajectory created in test_01."""
    trajectory_id = case_store["trajectory_ids"][0]

    response = client.get(f"/trajectories/{trajectory_id}")

    assert response.status_code == 200
    assert response.json()["id"] == trajectory_id
    assert response.json()["name"] == "test_trajectory"
```

**Key Patterns:**
- Naming: Prefix tests with `01_`, `02_` to enforce ordering
- Clarity: Clear test names that describe the workflow
- Documentation: Comments explaining why state is being stored
- Validation: Tests verify not just the current operation but also persistence

**When to Use:**
- API testing with resource creation/retrieval workflows
- Multi-step processes where each step depends on previous state
- Testing data persistence across multiple operations

**When to Avoid:**
- Unit tests (each test should be independent)
- Complex interdependencies (hard to debug)
- Performance-sensitive tests (state management adds overhead)

## Pattern 3: Checkpoint-Aware Conditional Logic

Use `checkpoint_name` fixture to conditionally run test logic based on current checkpoint.

### Real Example from `layered_config_synthesizer`

```python
def checkpoint_index(checkpoint_name):
    """Extract numeric index from checkpoint name.

    checkpoint_1 → 1
    checkpoint_2 → 2
    checkpoint_3 → 3
    """
    if not checkpoint_name:
        return None
    parts = checkpoint_name.split("_", 1)
    if len(parts) != 2:
        return None
    try:
        return int(parts[1])
    except ValueError:
        return None


@pytest.fixture(scope="session")
def expected_output_version(checkpoint_name):
    """Output format varies by checkpoint."""
    checkpoint_num = checkpoint_index(checkpoint_name)

    if checkpoint_num is None or checkpoint_num == 1:
        return "v1"
    elif checkpoint_num == 2:
        return "v2"
    else:
        return "v3"


def test_config_output_format(entrypoint_argv, tmp_path, checkpoint_name, expected_output_version):
    """Output format changes with checkpoints."""
    # Run synthesizer
    result = subprocess.run(
        entrypoint_argv + ["--output", str(tmp_path / "output.yaml")],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0

    output = yaml.safe_load((tmp_path / "output.yaml").read_text())

    # Different checkpoints have different output structures
    if expected_output_version == "v1":
        assert "config" in output
        assert "version" not in output
    elif expected_output_version == "v2":
        assert "config" in output
        assert "version" in output
    else:
        assert "config" in output
        assert "version" in output
        assert "schema" in output


@pytest.fixture(scope="session")
def enable_advanced_features(checkpoint_name):
    """Some features only available in later checkpoints."""
    checkpoint_num = checkpoint_index(checkpoint_name)
    return checkpoint_num and checkpoint_num >= 3


def test_schema_validation(entrypoint_argv, enable_advanced_features):
    """Schema validation only in checkpoint 3+."""
    if not enable_advanced_features:
        pytest.skip("Schema validation not in this checkpoint")

    # Test schema validation...
```

**When to Use:**
- Tests that change behavior across checkpoints
- Conditional feature tests (some features only in later checkpoints)
- Checkpoint-specific assertions or expectations

## Pattern 4: Snapshot and Diff Patterns

Capture expected values per checkpoint and enable comparison.

```python
@pytest.fixture(scope="session")
def expected_values(checkpoint_name):
    """Version-specific expected values."""
    expectations = {
        "checkpoint_1": {
            "status": "created",
            "version": None,
        },
        "checkpoint_2": {
            "status": "created",
            "version": 2,
            "features": ["logging"],
        },
        "checkpoint_3": {
            "status": "created",
            "version": 3,
            "features": ["logging", "metrics", "tracing"],
        },
    }
    return expectations.get(checkpoint_name, {})


def test_output_structure(entrypoint_argv, tmp_path, expected_values):
    """Verify output has expected structure for this checkpoint."""
    result = subprocess.run(
        entrypoint_argv,
        capture_output=True,
        text=True,
    )

    output = json.loads(result.stdout)

    # Check all expected fields are present
    for key, value in expected_values.items():
        if value is not None:
            assert output[key] == value
        else:
            # None means field shouldn't exist
            assert key not in output
```

## Pattern 5: Progressive Feature Addition

Test features that are only available in later checkpoints.

```python
@pytest.fixture(scope="session")
def available_commands(checkpoint_name):
    """Commands available in each checkpoint."""
    all_commands = {
        "checkpoint_1": ["parse", "validate"],
        "checkpoint_2": ["parse", "validate", "transform"],
        "checkpoint_3": ["parse", "validate", "transform", "aggregate"],
    }
    return all_commands.get(checkpoint_name, [])


@pytest.mark.functionality
def test_transform_command(entrypoint_argv, available_commands):
    """Transform command only in checkpoint_2+."""
    if "transform" not in available_commands:
        pytest.skip("Transform not available in this checkpoint")

    result = subprocess.run(
        entrypoint_argv + ["transform", "--input", "data.json"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0


class TestAggregation:
    """Tests for aggregation feature (checkpoint 3 only)."""

    @pytest.fixture(autouse=True)
    def skip_if_unavailable(self, available_commands):
        """Skip all tests in this class if aggregation unavailable."""
        if "aggregate" not in available_commands:
            pytest.skip("Aggregation not available in this checkpoint")

    def test_aggregate_numbers(self, entrypoint_argv):
        result = subprocess.run(
            entrypoint_argv + ["aggregate", "--input", "numbers.json", "--operation", "sum"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
```

## Real-World Case Study: Layered Config Synthesizer

This problem demonstrates all stateful testing patterns:

```python
def test_checkpoint_1_basic():
    """Checkpoint 1: Basic config synthesis."""
    # Inline test with simple structure
    pass


def test_checkpoint_2_fragment_inclusion():
    """Checkpoint 2: Include fragments from external files."""
    # Tests create fragment files, verify they're included
    # Checkpoint-aware logic: prepare different artifacts
    pass


def test_checkpoint_3_environment_variables():
    """Checkpoint 3: Interpolate environment variables."""
    # Advanced: state from previous checkpoints persists
    # Must handle both old and new features
    pass


def test_checkpoint_4_schema_validation():
    """Checkpoint 4: Validate against JSON schema."""
    # Most advanced: all previous features + schema
    # Legacy cases must still pass
    pass
```

**Key Lessons:**
- Tests evolve as features are added
- Early checkpoints are subsets of later ones
- State management becomes complex with many checkpoints
- Clear naming and documentation are essential

## State Management Best Practices

### 1. Limit Interdependencies

```python
# Bad: Every test depends on previous tests
def test_a(): store["a"] = get_a()
def test_b(store): store["b"] = process(store["a"])
def test_c(store): store["c"] = process(store["b"])

# Good: Group related tests in class with shared fixture
class TestWorkflow:
    def test_step_1(self):
        self.result1 = compute_step1()

    def test_step_2(self):
        self.result2 = compute_step2(self.result1)

    def test_step_3(self):
        self.result3 = compute_step3(self.result2)
```

### 2. Parallel Test Execution

Be aware that parallel execution breaks module-scoped state:

```python
# Can't run in parallel (module-scoped state)
@pytest.fixture(scope="module")
def case_store():
    return {}

# Can run in parallel (each test is independent)
@pytest.fixture
def temp_store():
    return {}
```

### 3. Clear Test Naming

```python
# Good: Clear ordering
def test_01_create_user(case_store):
def test_02_update_user(case_store):
def test_03_delete_user(case_store):

# Bad: Unclear dependencies
def test_create(case_store):
def test_update(case_store):
def test_delete(case_store):
```

### 4. Isolate State from Logic

```python
# Bad: State and logic mixed
@pytest.fixture(scope="module")
def process_data(case_store):
    case_store["data"] = load_and_process_large_file()
    return case_store["data"]

# Good: Logic separate from state
@pytest.fixture(scope="module")
def case_store():
    return {}

@pytest.fixture(scope="session")
def processed_data():
    return load_and_process_large_file()

def test_something(case_store, processed_data):
    case_store["data"] = processed_data
```

## Debugging Stateful Tests

### Check Test Ordering

```bash
# Use -v to see test execution order
pytest tests/test_checkpoint_1.py -v

# Collect only, don't run
pytest tests/test_checkpoint_1.py --collect-only
```

### Isolate State Issues

```python
# Add debug prints
@pytest.fixture(scope="module")
def case_store():
    store = {}
    yield store
    print(f"\nFinal state: {store}")  # See what state was created
```

### Verify State Persistence

```python
def test_state_is_preserved(case_store):
    """Verify module-scoped fixture persists."""
    # First run
    case_store["value"] = 42

    # Later test sees the same store
    assert case_store["value"] == 42
```

## Next Steps

- [Advanced Fixtures](fixtures-advanced.md) - Session/module scope patterns
- [Debugging Workflows](debugging-workflows.md) - Debugging state issues
- [Complex Parametrization](complex-parametrization.md) - Advanced data loading
