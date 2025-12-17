---
version: 1.4
last_updated: 2025-12-10
---

# Loaders Guide

This guide covers test case loading strategies, including script-based loaders, file-based discovery, and custom programmatic generation.

## Overview

Loaders discover and load test cases for evaluation using the GroupLoader protocol. The system supports:

1. **Script-based loaders**: Custom Python classes that implement the GroupLoader protocol
2. **File-based discovery**: Built-in helpers for scanning directories and glob patterns
3. **Data-driven generation**: Loaders that create cases from external data sources
4. **Case stores**: Optional storage for maintaining state across case execution

All loaders must be explicitly configured in the problem configuration.

## Loader Configuration

Loaders are configured at the problem level:

```yaml
# problem/config.yaml
loader_script: group_loader.py  # Path relative to problem root
loader_entrypoint: GroupLoader  # Class name (defaults to "GroupLoader")
```

The system will dynamically load and instantiate the specified class.

## GroupLoader Protocol

All loaders must implement the GroupLoader protocol:

```python
from collections.abc import Generator
from slop_code.evaluation.adapters.models import BaseCase, CaseResult
from slop_code.evaluation.config import GroupConfig, CheckpointConfig
from slop_code.evaluation.loaders.loader_protocol import CaseStore, NoOpStore

# Type alias for loader return type
LoaderYieldType = Generator[tuple[BaseCase, CaseResult], None, None]

@runtime_checkable
class GroupLoader(Protocol):
    """Group loader interface."""

    def __init__(
        self,
        checkpoint: CheckpointConfig,
        *,
        use_placeholders: bool = False,
    ): ...

    def initialize_store(self) -> CaseStore:
        """Initialize the case store for tracking state across cases."""
        ...

    def __call__(self, group: GroupConfig, store: CaseStore) -> LoaderYieldType:
        """Load test cases for a specific group.

        Args:
            group: The group configuration
            store: The case store for maintaining state

        Yields:
            Tuples of (base_case, expected_result) for each case in the group
        """
        ...
```

### BaseLoader Class

For convenience, inherit from `BaseLoader` which accepts both problem and checkpoint:

```python
from slop_code.evaluation.loaders.loader_protocol import BaseLoader, NoOpStore

class GroupLoader(BaseLoader):
    def __init__(
        self,
        problem: ProblemConfig,
        checkpoint: CheckpointConfig,
        *,
        use_placeholders: bool = False,
    ):
        super().__init__(problem, checkpoint, use_placeholders=use_placeholders)
        # self.problem and self.checkpoint are now available

    def initialize_store(self) -> CaseStore:
        return NoOpStore()  # or custom store implementation

    def __call__(self, group: GroupConfig, store: CaseStore) -> LoaderYieldType:
        # Your loader implementation
        ...
```

### Key Changes from Previous Version

- **Class-based protocol**: Loaders are now classes, not functions
- **Problem-level configuration**: Loader config is in problem config, not checkpoint
- **Case stores**: Optional storage for maintaining state across cases
- **Group-specific loading**: Each call handles one group, not all groups
- **Order preservation**: Case order is respected during evaluation

## Case File Format

### Basic Case File

```yaml
# checkpoint_1/my_group/case_1.yaml
name: test_addition
description: Test basic addition

arguments: ["add", "2", "3"]  # CLI adapter uses "arguments" instead of "input.args"

expected:
  output: "5\n"
  status_code: 0
```

### Case with Metadata

```yaml
name: complex_test
description: A more complex test case

# Optional metadata
tags:
  - integration
  - slow
priority: high
timeout: 120  # Override default timeout

arguments: ["--mode", "complex"]
stdin: "input data"

expected:
  output: "Success\n"
  status_code: 0
  files:
    - path: /app/output.json
      content: '{"status": "ok"}'
```

### Case File Naming

**Best practices:**
- Use descriptive names: `test_user_login.yaml` not `test1.yaml`
- Group related tests: `auth_login.yaml`, `auth_logout.yaml`, `auth_reset.yaml`
- Include test type: `unit_calculator.yaml`, `integration_api.yaml`

## Custom Loaders

### Basic Custom Loader

```python
# group_loader.py (in problem root)

from collections.abc import Generator
from slop_code.evaluation.adapters.models import BaseCase, CaseResult
from slop_code.evaluation.config import GroupConfig
from slop_code.evaluation.loaders.loader_protocol import BaseLoader, NoOpStore

class GroupLoader(BaseLoader):
    """Generate simple test cases."""
    
    def __call__(self, group: GroupConfig, store) -> Generator[tuple[BaseCase, CaseResult], None, None]:
        """Generate test cases for the given group."""
        
        # Generate test cases
        for i in range(10):
            case = BaseCase(
                name=f"test_multiply_{i}",
                description=f"Test multiplication by {i}",
                arguments=["multiply", str(i), "2"]
            )
            expected = CaseResult(
                output=f"{i * 2}\n",
                status_code=0
            )
            yield case, expected
```

Configuration:
```yaml
# problem/config.yaml
loader_script: group_loader.py
loader_entrypoint: GroupLoader
```

### Example 1: Data-Driven Tests

Load cases from a CSV file:

```python
# data_loader.py (in problem root)
import csv
from pathlib import Path
from collections.abc import Generator
from slop_code.evaluation.adapters.models import BaseCase, CaseResult
from slop_code.evaluation.config import GroupConfig
from slop_code.evaluation.loaders.loader_protocol import BaseLoader

class GroupLoader(BaseLoader):
    """Load test cases from CSV."""
    
    def __call__(self, group: GroupConfig, store) -> Generator[tuple[BaseCase, CaseResult], None, None]:
        """Load test cases from CSV data."""
        
        data_file = self.checkpoint.path / "test_data.csv"

        with open(data_file) as f:
            reader = csv.DictReader(f)
            for row in reader:
                case = BaseCase(
                    name=row["name"],
                    description=row.get("description", ""),
                    arguments=[row["operation"], row["arg1"], row["arg2"]]
                )
                expected = CaseResult(
                    output=row["expected_output"],
                    status_code=int(row.get("expected_status", 0))
                )
                yield case, expected
```

Data file (`checkpoint_1/test_data.csv`):
```csv
name,description,operation,arg1,arg2,expected_output
test_add_positive,Add positive numbers,add,5,3,"8\n"
test_add_negative,Add negative numbers,add,-5,-3,"-8\n"
test_multiply,Multiply numbers,multiply,4,3,"12\n"
```

### Example 2: Combinatorial Testing

Generate all combinations of inputs:

```python
# combinatorial_loader.py (in problem root)
import itertools
from collections.abc import Generator
from slop_code.evaluation.adapters.models import BaseCase, CaseResult
from slop_code.evaluation.config import GroupConfig
from slop_code.evaluation.loaders.loader_protocol import BaseLoader

class GroupLoader(BaseLoader):
    """Generate combinatorial test cases."""
    
    def __call__(self, group: GroupConfig, store) -> Generator[tuple[BaseCase, CaseResult], None, None]:
        """Generate all combinations of operations and values."""
        
        operations = ["add", "subtract", "multiply"]
        values = [0, 1, -1, 10, 100]

        for op, val1, val2 in itertools.product(operations, values, values):
            if op == "add":
                expected = val1 + val2
            elif op == "subtract":
                expected = val1 - val2
            else:  # multiply
                expected = val1 * val2

            case = BaseCase(
                name=f"test_{op}_{val1}_{val2}",
                description=f"Test {op}({val1}, {val2})",
                arguments=[op, str(val1), str(val2)]
            )
            expected_result = CaseResult(
                output=f"{expected}\n",
                status_code=0
            )
            yield case, expected_result
```

### Example 3: JSON Test Data

Load cases from a JSON file:

```python
# json_loader.py (in problem root)
import json
from pathlib import Path
from collections.abc import Generator
from slop_code.evaluation.adapters.models import BaseCase, CaseResult
from slop_code.evaluation.config import GroupConfig
from slop_code.evaluation.loaders.loader_protocol import BaseLoader

class GroupLoader(BaseLoader):
    """Load test cases from JSON."""
    
    def __call__(self, group: GroupConfig, store) -> Generator[tuple[BaseCase, CaseResult], None, None]:
        """Load test cases from JSON configuration."""
        
        test_file = self.checkpoint.path / "test_cases.json"
        
        with open(test_file) as f:
            data = json.load(f)

        for test_def in data["tests"]:
            case = BaseCase(
                name=test_def["name"],
                description=test_def.get("description", ""),
                arguments=test_def["input"].get("args", []),
                method=test_def["input"].get("method", "GET"),
                path=test_def["input"].get("path", ""),
                body=test_def["input"].get("body"),
                headers=test_def["input"].get("headers", {}),
                query=test_def["input"].get("query", {})
            )
            expected = CaseResult(
                output=test_def["expected"].get("output", ""),
                status_code=test_def["expected"]["status_code"]
            )
            yield case, expected
```

JSON data file (`checkpoint_1/test_cases.json`):
```json
{
  "tests": [
    {
      "name": "test_simple",
      "description": "Simple test case",
      "input": {
        "args": ["--mode", "simple"]
      },
      "expected": {
        "output": "Simple processing complete\n",
        "status_code": 0
      }
    },
    {
      "name": "test_complex",
      "input": {
        "args": ["--mode", "complex", "--verbose"]
      },
      "expected": {
        "output": "Complex processing complete\n",
        "status_code": 0
      }
    }
  ]
}
```

Test data (`test_cases.json`):
```json
{
  "tests": [
    {
      "name": "test_simple",
      "description": "Simple test case",
      "input": {
        "args": ["--mode", "simple"]
      },
      "expected": {
        "output": "Success\n",
        "status_code": 0
      }
    },
    {
      "name": "test_complex",
      "input": {
        "args": ["--mode", "complex", "--verbose"]
      },
      "expected": {
        "output": "Complex processing complete\n",
        "status_code": 0
      },
      "metadata": {
        "tags": ["integration"],
        "timeout": 120
      }
    }
  ]
}
```

### Example 4: File-Based Discovery Loader

Create a loader that discovers YAML files using built-in helpers:

```python
# file_discovery_loader.py (in problem root)
import yaml
from pathlib import Path
from collections.abc import Generator
from slop_code.evaluation.adapters.models import BaseCase, CaseResult
from slop_code.evaluation.config import GroupConfig
from slop_code.evaluation.loaders.loader_protocol import BaseLoader
from slop_code.evaluation.loaders.helpers import get_files_from_globs

class GroupLoader(BaseLoader):
    """Discover and load YAML case files from directories."""
    
    def __call__(self, group: GroupConfig, store) -> Generator[tuple[BaseCase, CaseResult], None, None]:
        """Load YAML files from the group directory."""
        
        group_path = self.checkpoint.path / group.name
        
        # Use helper to find YAML files
        yaml_files = get_files_from_globs(
            read_dir=group_path,
            globs=["*.yaml", "*.yml"]
        )
        
        for yaml_file in yaml_files:
            full_path = group_path / yaml_file
            with open(full_path) as f:
                case_data = yaml.safe_load(f)
                
            case = BaseCase(
                name=case_data["name"],
                description=case_data.get("description", ""),
                arguments=case_data.get("arguments", []),
                stdin=case_data.get("stdin"),
                method=case_data.get("method", "GET"),
                path=case_data.get("path", ""),
                body=case_data.get("body"),
                headers=case_data.get("headers", {}),
                query=case_data.get("query", {})
            )
            
            expected_data = case_data["expected"]
            expected = CaseResult(
                output=expected_data.get("output", ""),
                status_code=expected_data["status_code"]
            )
            
            yield case, expected
```

### Example 5: Parametrized Tests

Generate variations of a test template:

```python
# parametrized_loader.py (in problem root)
from collections.abc import Generator
from slop_code.evaluation.adapters.models import BaseCase, CaseResult
from slop_code.evaluation.config import GroupConfig
from slop_code.evaluation.loaders.loader_protocol import BaseLoader

class GroupLoader(BaseLoader):
    """Generate parametrized test cases."""
    
    def __call__(self, group: GroupConfig, store) -> Generator[tuple[BaseCase, CaseResult], None, None]:
        """Generate user creation tests with different roles."""
        
        # Parameters
        test_params = [
            {"name": "Alice", "role": "admin"},
            {"name": "Bob", "role": "user"},
            {"name": "Charlie", "role": "guest"},
        ]

        for params in test_params:
            case = BaseCase(
                name=f"create_user_{params['name'].lower()}",
                description=f"Create user {params['name']} with {params['role']} role",
                method="POST",
                path="/users",
                body=f'{{"name": "{params["name"]}", "role": "{params["role"]}"}}'
            )
            
            expected = CaseResult(
                status_code=201
            )
            
            yield case, expected
```

### Example 6: Random/Fuzz Testing

Generate random test cases:

```python
# fuzz_loader.py (in problem root)
import random
from collections.abc import Generator
from slop_code.evaluation.adapters.models import BaseCase, CaseResult
from slop_code.evaluation.config import GroupConfig
from slop_code.evaluation.loaders.loader_protocol import BaseLoader

class GroupLoader(BaseLoader):
    """Generate random test cases for fuzz testing."""
    
    def __call__(self, group: GroupConfig, store) -> Generator[tuple[BaseCase, CaseResult], None, None]:
        """Generate random fuzz tests."""
        
        # Seed for reproducibility
        seed = getattr(self.checkpoint, 'seed', 42)
        random.seed(seed)

        for i in range(100):  # Generate 100 random cases
            val1 = random.randint(-1000, 1000)
            val2 = random.randint(-1000, 1000)
            operation = random.choice(["add", "multiply", "subtract"])

            if operation == "add":
                expected = val1 + val2
            elif operation == "subtract":
                expected = val1 - val2
            else:
                expected = val1 * val2

            case = BaseCase(
                name=f"fuzz_{i}_{operation}",
                description=f"Fuzz test: {operation}({val1}, {val2})",
                arguments=[operation, str(val1), str(val2)]
            )
            
            expected_result = CaseResult(
                output=f"{expected}\n",
                status_code=0
            )
            
            yield case, expected_result
```

## Advanced Loader Patterns

### Pattern 1: Conditional Case Generation

Generate different cases based on configuration:

```python
class GroupLoader(BaseLoader):
    """Load cases based on checkpoint configuration."""
    
    def __call__(self, group: GroupConfig, store) -> Generator[tuple[BaseCase, CaseResult], None, None]:
        """Generate cases based on test mode."""
        
        # Check config for test mode
        test_mode = getattr(self.checkpoint, 'test_mode', 'standard')

        if test_mode == "smoke":
            # Generate minimal smoke tests
            yield from generate_smoke_tests()
        elif test_mode == "comprehensive":
            # Generate full test suite
            yield from generate_all_tests()
        else:
            # Standard test set
            yield from generate_standard_tests()
```

### Pattern 2: Case Store for State Management

Use case stores to maintain state across case execution:

```python
from slop_code.evaluation.loaders.loader_protocol import CaseStore

class StatefulStore(CaseStore):
    """Store that tracks created resources for cleanup."""

    def __init__(self):
        self.created_resources = []

    def update(self, case: BaseCase, result: CaseResult, expected: CaseResult) -> None:
        """Track resources created during case execution.

        Args:
            case: The executed case
            result: The actual execution result
            expected: The expected result for comparison
        """
        if result.status_code == 0 and "resource_id" in str(result.output):
            self.created_resources.append(str(result.output).strip())

class GroupLoader(BaseLoader):
    """Generate cases with resource tracking."""

    def initialize_store(self) -> CaseStore:
        """Initialize stateful store."""
        return StatefulStore()

    def __call__(self, group: GroupConfig, store: StatefulStore) -> Generator[tuple[BaseCase, CaseResult], None, None]:
        """Generate cases with cleanup support."""

        for i in range(5):
            case = BaseCase(
                id=f"create_resource_{i}",
                group=group.name,
                group_type=group.type,
                checkpoint=self.checkpoint.name,
                arguments=["create", f"resource_{i}"],
            )

            expected = CaseResult(
                id=case.id,
                group=case.group,
                group_type=case.group_type,
                status_code=0,
                output=f"resource_{i}_id\n",
            )

            yield case, expected

        # Add cleanup case using data collected in store
        cleanup_case = BaseCase(
            id="cleanup_resources",
            group=group.name,
            group_type=group.type,
            checkpoint=self.checkpoint.name,
            arguments=["cleanup"] + store.created_resources,
        )

        cleanup_expected = CaseResult(
            id=cleanup_case.id,
            group=cleanup_case.group,
            group_type=cleanup_case.group_type,
            status_code=0,
        )
        yield cleanup_case, cleanup_expected
```

### Pattern 3: Filtering Cases

Apply filters to generated cases:

```python
class GroupLoader(BaseLoader):
    """Load and filter cases based on configuration."""
    
    def __call__(self, group: GroupConfig, store) -> Generator[tuple[BaseCase, CaseResult], None, None]:
        """Generate and filter cases."""
        
        all_cases = list(generate_all_cases())

        # Apply filters from group configuration
        filters = getattr(group, 'filters', {})

        if "tags" in filters:
            # Filter by tags
            required_tags = set(filters["tags"])
            all_cases = [
                c for c in all_cases
                if required_tags & set(getattr(c[0], 'tags', []))
            ]

        if "priority" in filters:
            # Filter by priority
            min_priority = filters["priority"]
            all_cases = [
                c for c in all_cases
                if getattr(c[0], 'priority', 0) >= min_priority
            ]

        for case, expected in all_cases:
            yield case, expected
```

### Pattern 4: Hierarchical Case Organization

Organize cases in a hierarchy using helpers:

```python
from slop_code.evaluation.loaders.helpers import get_files_from_globs

class GroupLoader(BaseLoader):
    """Load cases from hierarchical structure."""
    
    def __call__(self, group: GroupConfig, store) -> Generator[tuple[BaseCase, CaseResult], None, None]:
        """Load cases from nested directory structure."""
        
        group_path = self.checkpoint.path / group.name
        
        # Get all YAML files recursively
        yaml_files = get_files_from_globs(
            read_dir=group_path,
            globs=["**/*.yaml", "**/*.yml"]
        )

        for yaml_file in yaml_files:
            full_path = group_path / yaml_file
            with open(full_path) as f:
                case_data = yaml.safe_load(f)

            # Add path information to case description
            relative_path = str(yaml_file)
            description = case_data.get("description", "")
            if description:
                description += f" (path: {relative_path})"
            else:
                description = f"From {relative_path}"

            case = BaseCase(
                name=case_data["name"],
                description=description,
                arguments=case_data.get("arguments", []),
                # ... other case properties
            )
            
            expected_data = case_data["expected"]
            expected = CaseResult(
                output=expected_data.get("output", ""),
                status_code=expected_data["status_code"]
            )
            
            yield case, expected
```

## Loader Best Practices

### 1. Use Descriptive Case Names

```python
# Good
name = f"test_login_with_{username}_as_{role}"

# Bad
name = f"test_{i}"
```

### 2. Include Metadata

```python
case = {
    "name": "test_edge_case",
    "metadata": {
        "tags": ["edge-case", "critical"],
        "jira_ticket": "PROJ-123",
        "author": "alice",
        "created": "2025-10-16"
    },
    # ...
}
```

### 3. Validate Generated Cases

```python
def load_cases(group_name, checkpoint_config):
    cases = generate_cases()

    # Validate each case
    for case in cases:
        assert "name" in case, f"Case missing name: {case}"
        assert "input" in case, f"Case {case['name']} missing input"
        assert "expected" in case, f"Case {case['name']} missing expected"

    return cases
```

### 4. Document Your Loader

```python
def load_cases(group_name, checkpoint_config):
    """
    Generate test cases for matrix multiplication.

    Generates cases covering:
    - Identity matrices
    - Zero matrices
    - Random matrices (various sizes)
    - Edge cases (1x1, very large)

    Configuration options:
    - seed: Random seed (default: 42)
    - num_random: Number of random cases (default: 10)
    - max_size: Maximum matrix dimension (default: 10)
    """
    # ...
```

### 5. Handle Errors Gracefully

```python
def load_cases(group_name, checkpoint_config):
    """Load cases with error handling."""
    try:
        cases = generate_cases()
    except FileNotFoundError as e:
        # Provide helpful error message
        raise ValueError(
            f"Test data file not found for {group_name}. "
            f"Expected file: {e.filename}"
        ) from e
    except Exception as e:
        # Log error and provide fallback
        print(f"Warning: Error loading cases for {group_name}: {e}")
        return get_fallback_cases()

    return cases
```

## Testing Your Loader

### Using `tools run-case` (Recommended)

The fastest way to test your loader is with the `tools run-case` command:

```bash
# Create a test snapshot from your solution
cp -r problems/my_problem/checkpoint_1/solution test_snapshot

# Run all cases - this exercises your loader
slop-code tools run-case \
  -s test_snapshot \
  -p my_problem \
  -c 1 \
  -e configs/environments/docker-python3.12-uv.yaml
```

**What this tests:**
- Case discovery (are all cases found?)
- Case structure (are fields populated correctly?)
- File loading (are input files loaded properly?)
- Expected result generation (do expected values match?)

**Debugging loader issues:**

```bash
# Test specific group to verify group discovery
slop-code tools run-case ... --group my_new_group

# If no output, your loader isn't finding cases in that group
# Check: helpers.get_group_path() returns correct path
# Check: Your discovery logic (discover_dir_cases or glob patterns)

# Test a specific case
slop-code tools run-case ... --case specific_case --full

# Check the full output to see what case/expected look like
```

**Common loader issues to debug:**

1. **Empty output for a group**: Loader not finding cases
   - Verify `helpers.get_group_path()` returns the correct directory
   - Check glob patterns or `discover_dir_cases()` logic

2. **Wrong arguments in cases**: Case construction error
   - Run with `--full` and check the `case` field in output
   - Verify YAML parsing or argument construction logic

3. **Missing input files**: File loading error
   - Check `InputFile.from_path()` calls
   - Verify file paths are relative to case directory

### Unit Testing (Supplementary)

For complex loaders with custom logic, add unit tests:

```python
# test_loader.py
from pathlib import Path
from unittest.mock import Mock
import sys

sys.path.insert(0, str(Path(__file__).parent))
from group_loader import GroupLoader

def test_loader_discovers_cases():
    """Test that loader finds all expected cases."""
    problem = Mock()
    problem.path = Path("problems/my_problem")

    checkpoint = Mock()
    checkpoint.path = Path("problems/my_problem/checkpoint_1")
    checkpoint.name = "checkpoint_1"

    group = Mock()
    group.name = "core"
    group.type = "Core"
    group.group_files = []

    loader = GroupLoader(problem, checkpoint)
    store = loader.initialize_store()

    cases = list(loader(group, store))

    assert len(cases) > 0, "Should find at least one case"
    for case, expected in cases:
        assert case.id, "Case must have an ID"
        assert case.group == "core", "Case group should match"

if __name__ == "__main__":
    test_loader_discovers_cases()
    print("✓ Loader tests passed")
```

### Iterative Development Workflow

1. **Write initial loader** with basic case discovery
2. **Run `tools run-case`** to see if cases load
3. **Check output** - are all cases found? Are fields correct?
4. **Fix issues** based on output
5. **Add new groups/cases**, repeat

This workflow is much faster than running full evaluations and gives immediate feedback on loader behavior.

## Built-in Helper Functions

The loaders module provides several helper functions:

### File Discovery

```python
from slop_code.evaluation.loaders.helpers import get_files_from_globs

# Get files matching patterns with exclusion
files = get_files_from_globs(
    read_dir=Path("test_cases"),
    globs=["*.yaml", "data/**/*.json"],
    exclude=["*.tmp.yaml", "data/excluded/**"]
)
```

### Directory Discovery

```python
from slop_code.evaluation.loaders.helpers import discover_dir_cases

# Find directories not already configured as groups
for case_dir in discover_dir_cases(group_config, checkpoint_dir):
    print(f"Found case directory: {case_dir}")
```

### Group Path Resolution

```python
from slop_code.evaluation.loaders.helpers import get_group_path

# Get correct path for regular or regression groups
group_path = get_group_path(group_config, problem_config, checkpoint_config)
```

## Combining Different Loading Strategies

Use different approaches in different groups:

```yaml
# problem/config.yaml
loader_script: group_loader.py

checkpoints:
  checkpoint_1:
    groups:
      manual_tests:
        description: Hand-written test cases
        type: file_based

      generated_tests:
        description: Programmatically generated cases
        type: generated

      regression_tests:
        description: Tests from previous checkpoint
        type: regression
        original_checkpoint: checkpoint_0
        original_group: manual_tests
```

## Common Pitfalls

### Pitfall 1: Large Number of Cases

**Problem**: Generating thousands of cases slows down evaluation

**Solution**: Use sampling or filtering
```python
class GroupLoader(BaseLoader):
    def __call__(self, group: GroupConfig, store) -> Generator[tuple[BaseCase, CaseResult], None, None]:
        # Generate subset based on config
        num_cases = getattr(group, 'num_cases', 100)
        all_cases = list(generate_all_possible_cases())
        selected_cases = random.sample(all_cases, min(num_cases, len(all_cases)))
        
        for case, expected in selected_cases:
            yield case, expected
```

### Pitfall 2: Non-Deterministic Generation

**Problem**: Cases change between runs

**Solution**: Use a fixed seed
```python
class GroupLoader(BaseLoader):
    def __call__(self, group: GroupConfig, store) -> Generator[tuple[BaseCase, CaseResult], None, None]:
        import random
        random.seed(getattr(self.checkpoint, 'seed', 42))
        # Generate cases...
```

### Pitfall 3: Missing Case Validation

**Problem**: Invalid cases cause cryptic errors later

**Solution**: Validate in loader
```python
from pydantic import BaseModel, ValidationError

class CaseSchema(BaseModel):
    name: str
    arguments: list[str] | None = None
    method: str | None = None

class GroupLoader(BaseLoader):
    def __call__(self, group: GroupConfig, store) -> Generator[tuple[BaseCase, CaseResult], None, None]:
        for case_data in generate_raw_cases():
            try:
                # Validate case structure
                CaseSchema(**case_data.__dict__)
                yield case_data, generate_expected(case_data)
            except ValidationError as e:
                print(f"Warning: Invalid case {case_data.name}: {e}")
```

### Pitfall 4: Incorrect Store Usage

**Problem**: Not using the case store properly

**Solution**: The store is updated by the evaluation runner after each case executes. You can read from it in your loader to inform subsequent cases:

```python
class GroupLoader(BaseLoader):
    def __call__(self, group: GroupConfig, store: CaseStore) -> Generator[tuple[BaseCase, CaseResult], None, None]:
        for case, expected in generate_cases():
            yield case, expected
            # Note: store.update(case, result, expected) is called
            # automatically by the runner after execution
            # You can read from store to inform later cases
```

## Migration from Previous Version

### Function-based to Class-based Loaders

**Old (function-based):**
```python
def load_cases(checkpoint_config, checkpoint_dir):
    group_config = GroupConfig(name="tests", description="Test cases")
    cases = []
    # ... generate cases
    yield group_config, cases
```

**New (class-based):**
```python
class GroupLoader(BaseLoader):
    def __call__(self, group: GroupConfig, store: CaseStore):
        # ... generate cases
        for case, expected in cases:
            yield case, expected
```

### Configuration Changes

**Legacy (per-checkpoint file, migrated inline):**
```yaml
# config.yaml → checkpoints.checkpoint_1
checkpoints:
  checkpoint_1:
    loader:
      type: script
      path: loader.py
      entrypoint: load_cases
```

**New (problem-level):**
```yaml
# problem/config.yaml
loader_script: loader.py
loader_entrypoint: GroupLoader
```

## Next Steps

- **Understand verification**: [Verification Guide](verification.md)
- **Configure your problem**: [Configuration Guide](configuration.md)
- **Review results**: [Reporting Guide](reporting.md)
- **Debug issues**: [Troubleshooting Guide](troubleshooting.md)
