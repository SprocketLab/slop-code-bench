---
version: 1.0
last_updated: 2025-10-24
---

# Creating Loaders and Verifiers

This guide covers how to create custom loaders and verifiers for evaluation problems. Loaders discover and load test cases, while verifiers validate whether submission outputs match expected results.

## Overview

Every problem needs two key components:

1. **Loader** (`loader.py`) - Discovers and loads test cases from files or generates them programmatically
2. **Verifier** (`verifier.py`) - Validates actual outputs against expected results

Both components follow specific interfaces and leverage framework helpers to minimize boilerplate code.

## Loaders

### The Loader Protocol

Loaders are classes that implement the `GroupLoader` protocol (no inheritance required):

```python
from collections.abc import Generator
from slop_code.evaluation.config import GroupConfig, CheckpointConfig, ProblemConfig
from slop_code.evaluation.loaders import CaseStore, NoOpStore, BaseLoader
from slop_code.evaluation.adapters import CLICase, CLIResult  # or APICase, APIResult

class Loader(BaseLoader):  # Inherit from BaseLoader for convenience
    def __init__(
        self,
        problem: ProblemConfig,
        checkpoint: CheckpointConfig,
        *,
        use_placeholders: bool = False,
    ):
        self.problem = problem
        self.checkpoint = checkpoint
        self.use_placeholders = use_placeholders

    def initialize_store(self) -> CaseStore:
        """Initialize optional case store for state management."""
        return NoOpStore()  # Default implementation

    def __call__(
        self,
        group: GroupConfig,
        store: CaseStore
    ) -> Generator[tuple[CLICase, CLIResult], None, None]:
        """Yield (case, expected_result) tuples for each test case."""
        ...
```

**Key Requirements:**
- `__init__` receives `problem`, `checkpoint`, and optional `use_placeholders`
- `initialize_store()` returns a `CaseStore` for stateful scenarios (optional)
- `__call__` yields `(BaseCase, CaseResult)` tuples for each test case
- Case order is respected during evaluation (important for stateful APIs)

**Implementation Note:**
The `BaseLoader` class provides a convenient base with all required parameters. While there is also a `GroupLoader` protocol, **we recommend inheriting from `BaseLoader`** as it matches the actual loader implementations throughout the codebase and provides sensible defaults.

### Common Loader Patterns

#### Pattern 1: YAML File Discovery (Most Common)

Used by `file_merger` - loads cases from YAML files in directories.

```python
import yaml
from slop_code.evaluation.loaders import helpers, BaseLoader

class Loader(BaseLoader):  # Can inherit from BaseLoader or just implement protocol
    def load_case(
        self, case_file: Path, group_config: GroupConfig
    ) -> tuple[CLICase, CLIResult]:
        with open(case_file) as f:
            case_yaml = yaml.safe_load(f)
        
        case = CLICase(
            id=case_file.stem,
            group=group_config.name,
            group_type=group_config.type,
            checkpoint=self.checkpoint.name,
            arguments=case_yaml["case"]["arguments"],
            input_files=[
                InputFile.model_validate(file)
                for file in case_yaml["case"]["input_files"]
            ],
        )
        
        expected = CLIResult(
            id=case_file.stem,
            group=group_config.name,
            group_type=group_config.type,
            status_code=case_yaml["expected"]["status_code"],
            output=case_yaml["expected"].get("output"),
            files=case_yaml["expected"].get("files", {}),
        )
        
        return case, expected

    def __call__(self, group: GroupConfig, store: CaseStore):
        group_dir = helpers.get_group_path(group, self.problem, self.checkpoint)
        for case_file in group_dir.glob("*.yaml"):
            if case_file.name == "config.yaml":
                continue
            yield self.load_case(case_file, group)
```

**YAML Case File Structure:**
```yaml
# checkpoint_1/my_group/test_case.yaml
case:
  arguments: --output output.csv --key id A.csv B.csv
  input_files:
    - content:
        - id: '1'
          value: 'test'
      file_type: csv
      path: A.csv

expected:
  status_code: 0
  files:
    output.csv:
      - id: 1
        value: test
```

#### Pattern 2: Directory-Based Cases

Used by `eve_jump_planner` - each directory contains a complete test case.

```python
from slop_code.evaluation.loaders import BaseLoader

class Loader(BaseLoader):
    def load_case_dir(
        self, case_dir: Path, group_config: GroupConfig, default_args: list[str]
    ) -> tuple[CLICase, CLIResult]:
        # Load input files from directory
        input_files = [
            InputFile.from_path(case_dir, Path("manifest.yaml")),
        ]
        
        # Load expected output from EXPECTED file
        expected = None
        if (case_dir / "EXPECTED").exists():
            expected = (case_dir / "EXPECTED").read_text().split("---")[-1].strip()
        
        case = CLICase(
            id=case_dir.name,
            group=group_config.name,
            group_type=group_config.type,
            checkpoint=self.checkpoint.name,
            arguments=default_args,
            input_files=input_files,
        )
        
        result = CLIResult(
            id=case_dir.name,
            group=group_config.name,
            group_type=group_config.type,
            status_code=0,
            output=expected,
        )
        
        return case, result

    def __call__(self, group: GroupConfig, store: CaseStore):
        group_dir = helpers.get_group_path(group, self.problem, self.checkpoint)
        default_args = ["--manifest", "manifest.yaml", "--sde-dir", "{{static:sde_dir}}"]
        
        for case_dir in helpers.discover_dir_cases(group, group_dir):
            yield self.load_case_dir(case_dir, group, default_args)
```

**Directory Structure:**
```
checkpoint_1/
└── function/
    └── 7ly_jump/
        ├── manifest.yaml      # Input data
        └── EXPECTED          # Expected output
```

#### Pattern 3: API Cases with State Management

Used by `trajectory_api` - manages state between API calls (e.g., created resource IDs).

**When to use this pattern:**
- API tests where later cases depend on IDs/data from earlier cases (e.g., GET /resource/{id} after POST /resource)
- Tests requiring cumulative state tracking across multiple cases
- Scenarios with dynamic placeholder resolution based on previous results

**When NOT to use this pattern:**
- Independent test cases with no dependencies between them
- Simple CLI tools with no stateful interactions
- Cases where all test data is known upfront

```python
import json
from jinja2 import Template
from slop_code.evaluation.adapters import APICase, APIResult
from slop_code.evaluation.loaders import BaseLoader

class TrajectoryStore:
    """Manages state between API calls (e.g., created trajectory IDs).

    This custom store implements the CaseStore protocol by providing an
    update() method that gets called after each case execution.
    """
    def __init__(self):
        self.trajectory_ids = {}

    def update(self, case: APICase, result: APIResult, expected: APIResult) -> None:
        """Extract and store trajectory IDs from creation responses.

        This is called automatically by the framework after each case,
        allowing you to capture state for later cases.

        Args:
            case: The case that was executed
            result: The actual result from execution
            expected: The expected result (useful for validation)
        """
        _ = expected  # Often unused, but available if needed
        if case.method == "POST" and case.path == "/trajectories":
            body = result.output
            if isinstance(body, str):
                try:
                    body = json.loads(body)
                except json.JSONDecodeError:
                    return
            if isinstance(body, dict) and "id" in body:
                self.trajectory_ids[case.id] = body["id"]

    def resolve_placeholders(self, raw: str) -> str:
        """Replace {{store.trajectory_id}} placeholders with actual IDs.

        Uses Jinja2 templating for flexible placeholder resolution.
        """
        template = Template(raw)
        return template.render(store=self.trajectory_ids)

class Loader(BaseLoader):
    def initialize_store(self) -> TrajectoryStore:
        return TrajectoryStore()
    
    def load_case(self, case_file: Path, group_config: GroupConfig, store: TrajectoryStore):
        with case_file.open() as f:
            # Resolve placeholders from previous cases
            case_contents = store.resolve_placeholders(f.read())
            case_yaml = yaml.safe_load(case_contents)
        
        case = APICase(
            group=group_config.name,
            group_type=group_config.type,
            checkpoint=self.checkpoint.name,
            **case_yaml["case"],
        )
        
        expected = APIResult(
            id=case_file.stem,
            group=group_config.name,
            group_type=group_config.type,
            **case_yaml["expected"],
        )
        
        return case, expected
    
    def __call__(self, group: GroupConfig, store: CaseStore):
        store = cast("TrajectoryStore", store)
        group_dir = helpers.get_group_path(group, self.problem, self.checkpoint)

        # Process cases in order to maintain state
        # Note: The framework automatically calls store.update() after each case
        # execution with the actual results. Here we just yield the cases.
        for case_file in group.case_order:
            case, expected = self.load_case(group_dir / f"{case_file}.yaml", group, store)
            yield case, expected
```

**API Case File with Placeholders:**
```yaml
# get_trajectory_by_id.yaml
case:
  method: GET
  path: /trajectories/{{store.create_valid_trajectory}}
  headers:
    content-type: application/json

expected:
  status_code: 200
  output:
    # JSON Schema validation
    type: object
    properties:
      id:
        type: string
        pattern: '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
```

### Understanding CaseStore

The `CaseStore` is a protocol for managing state across test cases. Most loaders use `NoOpStore()` (does nothing), but stateful scenarios need custom stores.

**NoOpStore (Default):**
```python
from slop_code.evaluation.loaders import NoOpStore

class Loader:
    def initialize_store(self):
        return NoOpStore()  # No state tracking needed
```

**Custom Store (For Stateful Tests):**
```python
from slop_code.evaluation.loaders.loader_protocol import CaseStore
from slop_code.evaluation.adapters import BaseCase, CaseResult

class MyStore:
    """Custom store implementing CaseStore protocol."""
    def __init__(self):
        self.state = {}

    def update(self, case: BaseCase, result: CaseResult, expected: CaseResult) -> None:
        """Called after each case execution to capture state.

        Args:
            case: The case that was executed
            result: The actual result from execution
            expected: The expected result
        """
        # Extract and store data for use in later cases
        self.state[case.id] = result.output

class Loader(BaseLoader):
    def initialize_store(self):
        return MyStore()  # Use custom state tracking

    def __call__(self, group, store):
        # The same store instance persists across all cases
        # Framework calls store.update() after each case execution
        for case_file in group.case_order:
            case, expected = self.load_case(case_file, group, store)
            yield case, expected
```

**Key Points:**
- Store is initialized once per group via `initialize_store()`
- The same store instance is passed to all cases in the group
- Framework calls `store.update(case, result)` after each case execution
- Use stores to track IDs, tokens, or any state needed by later cases

### Static Placeholders

Static placeholders resolve to fixed values from problem configuration, unlike store placeholders that come from previous case results.

**Usage in test cases:**
```python
# In CLI arguments
arguments=["--data-dir", "{{static:data_dir}}", "--api-key", "{{static:api_key}}"]

# In file paths
path="{{static:base_url}}/api/users"
```

**Configuration:**
Static values are typically defined in problem or checkpoint config and resolved by the framework. Common uses:
- File paths to shared resources
- Environment-specific values
- Problem-specific constants

**Example:**
```python
# In loader
default_args = ["--sde-dir", "{{static:sde_dir}}"]
# Framework resolves to: ["--sde-dir", "/path/to/sde"]
```

### Framework Helpers for Loaders

The framework provides powerful helpers in [`slop_code.evaluation.loaders.helpers`](../../../src/slop_code/evaluation/loaders/helpers.py):

```python
from slop_code.evaluation.loaders import helpers

# Get the directory path for a group
group_dir = helpers.get_group_path(group, self.problem, self.checkpoint)
# Returns: Path to the group directory (e.g., problem/checkpoint_1/core/)

# Discover directory-based cases (excludes group_files directories)
for case_dir in helpers.discover_dir_cases(group, group_dir):
    # Process case_dir (each is a Path object)...
    pass

# Get files from glob patterns with exclusion support
files = helpers.get_files_from_globs(
    read_dir=group_dir,
    globs=["*.yaml", "data/**/*"],
    exclude={"*.tmp", "config.yaml"}  # Can be set or list
)
# Returns: List of Path objects relative to read_dir
```

#### Helper Details

**`get_group_path(group, problem, checkpoint)`**
- Returns absolute `Path` to the group's directory
- Handles regression groups by looking up original checkpoint/group
- Raises `LoaderError` if directory doesn't exist

**`discover_dir_cases(group_config, checkpoint_dir)`**
- Yields `Path` objects for each case directory
- Excludes directories listed in `group_config.group_files`
- Example: If `group_files = ["shared/A.yaml"]`, the "shared/" directory is excluded
- Only yields immediate subdirectories (not recursive)

**`get_files_from_globs(read_dir, globs, exclude)`**
- Returns list of `Path` objects relative to `read_dir`
- `globs`: List of patterns like `["*.yaml", "**/*.json"]`
- `exclude`: Set or list of patterns to exclude
- Handles both glob patterns and literal paths
- Smart precedence: specific include globs override exclusions

### Loader Configuration

Loaders are configured in checkpoint configs:

```yaml
# config.yaml → checkpoints.checkpoint_1.groups
checkpoints:
  checkpoint_1:
    groups:
      my_group:
        type: Core
        case_order:  # Optional: specify case execution order
          - create_user        # Case ID (typically filename without extension)
          - get_user_by_id     # Cases run in this exact order
          - update_user
          - delete_user
        timeout: 30
        group_files:  # Optional: files shared across all cases in group
          - shared/common.yaml
```

**Configuration Details:**

- **`case_order`**: List of case IDs (strings) specifying execution order
  - Required for stateful API tests where order matters
  - Maps to case file names without extension (e.g., `create_user` → `create_user.yaml`)
  - Access in loader via `group.case_order`
  - If not specified, cases are discovered in filesystem order

- **`group_files`**: List of file paths relative to group directory
  - Files shared across all cases (e.g., reference data, configs)
  - Directories listed here are excluded from `discover_dir_cases()`
  - Access via `group_config.group_files`

### Loader Best Practices

#### DO ✅

1. **Use framework helpers** - `helpers.get_group_path()`, `helpers.discover_dir_cases()`
2. **Handle missing files gracefully** - check existence before reading
3. **Use consistent naming** - case IDs should be descriptive and unique
4. **Leverage InputFile.from_path()** for existing files
5. **Keep it simple** - most loaders are under 100 lines

#### DON'T ❌

1. **Don't hardcode paths** - use framework helpers
2. **Don't ignore errors** - handle missing files gracefully
3. **Don't create complex logic** - keep case discovery straightforward
4. **Don't mix different patterns** - choose one pattern and stick with it
5. **Don't ignore case_order** - important for API tests with dependencies

## Verifiers

### The Verifier Protocol

Verifiers are classes that implement the `VerifierProtocol` (no inheritance required):

```python
from slop_code.evaluation.config import CheckpointConfig
from slop_code.evaluation.verifiers import VerifierReturnType
from slop_code.evaluation.adapters import cli  # or api

class Verifier:  # Note: No inheritance required
    def __init__(self, checkpoint_config: CheckpointConfig) -> None:
        self.checkpoint_config = checkpoint_config
    
    def __call__(
        self,
        group_name: str,
        case_name: str,
        actual: cli.CLIResult,  # or api.APIResult
        expected: cli.CLIResult,
    ) -> VerifierReturnType:
        """Return dict mapping attribute names to VerificationResult objects.
        
        Keys must be either:
        - An attribute on CaseResult (e.g., "output", "status_code")
        - A file verification in form "files-<filename>"
        """
        ...
```

**Key Protocol Requirements:**
- `__init__` receives `checkpoint_config` for context
- `__call__` receives group/case names and actual/expected results
- Returns `dict[str, VerificationResult]` mapping attributes to verification results
- Attribute names must match result object fields or use `files-<filename>` pattern

**Note on Terminology:**
- `CaseResult` is the base class/protocol for results
- `CLIResult` and `APIResult` are concrete implementations for CLI and API adapters
- In your verifier, type hints should use the specific result type (`CLIResult` or `APIResult`)

### Framework Helpers (Use These!)

The framework provides powerful helpers in [`slop_code.evaluation.verifiers`](../../../src/slop_code/evaluation/verifiers/) - **use them for everything!**

#### Verification Helpers ([`verifiers.py`](../../../src/slop_code/evaluation/verifiers/verifiers.py))

```python
from slop_code.evaluation.verifiers import verifiers

# Status code verification
verifiers.matches_status_code(actual.status, expected.status, weight=0.2)

# Deep comparison (JSON, dicts, lists, strings) - USE THIS FOR EVERYTHING!
verifiers.deepdiff_verify(actual_value, expected_value, weight=0.8)

# Regex pattern matching
verifiers.matches_regex(actual_string, expected_pattern)

# JSON Schema validation
verifiers.jsonschema_verify(actual_json, expected_schema)
```

#### Parser Helpers ([`parsers.py`](../../../src/slop_code/evaluation/verifiers/parsers.py))

```python
from slop_code.evaluation.verifiers import parsers

# Parse JSON from strings or bytes
parsed = parsers.parse_json(string_content, allow_invalid=True)
# Returns: dict (or {"error": "Invalid JSON"} if allow_invalid=True)

# Parse CSV content into list of dicts
rows = parsers.parse_csv_content(csv_string, allows_error=True)
# Returns: list[dict] (or [{"error": "Invalid CSV"}] if allows_error=True)

# Parse YAML content or files
config = parsers.parse_yaml(yaml_content, decode="utf-8")
# Returns: dict (or {} if content is None/empty)

config = parsers.parse_yaml_file(
    result, "config.yaml", decode="utf-8", allow_missing=False
)
# Returns: dict from result.files["config.yaml"]
# Raises VerifierError if file missing and allow_missing=False

# Parse JSONL (one JSON per line)
records = parsers.parse_jsonl(jsonl_content, decode="utf-8")
# Returns: list[dict] (skips invalid lines silently)

# Parse markdown tables
table = parsers.parse_markdown_table(markdown_content, allow_errors=True)
# Returns: list[dict] (or [{"error": "Invalid markdown table"}] if errors)

# Extract and normalize output from CaseResult
output = parsers.extract_actual_output(
    actual,
    split_output_on="---\n",  # Optional: split and take specific part
    split_output_index=-1,     # Which part to take after splitting
    output_key="output",       # Attribute name to extract
    decode="utf-8",            # Decode bytes if needed
    strip=True                 # Strip whitespace
)
# Returns: str or None

# Split string on delimiter and take specific part
part = parsers.maybe_split_string(
    content,
    split_output_on="---\n",
    split_output_index=-1  # -1 for last part, 0 for first, etc.
)
# Returns: str (or "" if content is None)

# Ensure expected values are not None
expected_str = parsers.ensure_expected_is_not_none(expected_value, decode="utf-8")
# Returns: str (raises VerifierError if None)

# Convert values to string, handling None and bytes
safe_str = parsers.ensure_non_null_string(val, allow_empty=False)
# Returns: str (raises VerifierError if empty and allow_empty=False)

# Drop specific keys from list of dicts
cleaned = parsers.drop_keys_from_dicts(dicts, keys={"id", "timestamp"})
# Returns: list[dict] with specified keys removed
```

#### Default DeepDiff Configuration
The framework provides sensible defaults for deep comparisons:
```python
DEFAULT_DEEPDIFF_KWARGS = {
    "ignore_string_type_changes": True,    # "123" == 123
    "ignore_numeric_type_changes": True,    # 1.0 == 1
    "ignore_nan_inequality": True,         # NaN == NaN
    "math_epsilon": 1e-6,                  # Floating point tolerance
}
```

**Overriding Defaults:**
```python
# Pass custom kwargs to deepdiff_verify to override defaults
verifiers.deepdiff_verify(
    actual,
    expected,
    weight=0.8,
    ignore_string_type_changes=False,  # Now "123" != 123
    math_epsilon=1e-9,                 # Stricter floating point comparison
    ignore_order=True                  # [1,2,3] == [3,2,1]
)
```

### Common Verifier Patterns

#### Pattern 1: Simple CLI Output Verification

```python
def __call__(self, group_name: str, case_name: str, actual: cli.CLIResult, expected: cli.CLIResult):
    return {
        "status_code": verifiers.matches_status_code(
            actual.status_code, expected.status_code, weight=0.2
        ),
        "output": verifiers.deepdiff_verify(
            actual.output, expected.output, weight=0.8
        ),
    }
```

#### Pattern 2: File Output Verification

Used by `file_merger` - verifies generated CSV files.

```python
def __call__(self, group_name: str, case_name: str, actual: cli.CLIResult, expected: cli.CLIResult):
    results = {
        "status_code": verifiers.matches_status_code(
            actual.status_code, expected.status_code
        ),
    }
    
    # Verify each expected file
    for file_name, file_content in expected.files.items():
        parsed_actual = parsers.parse_csv_content(
            actual.files.get(file_name, ""), allows_error=True
        )
        results[f"files-{file_name}"] = verifiers.deepdiff_verify(
            parsed_actual, file_content
        )
    
    return results
```

#### Pattern 3: Error Case Verification

```python
def verify_error_case(self, actual: cli.CLIResult, expected: cli.CLIResult):
    return {
        "status_code": verifiers.matches_status_code(
            actual.status_code, expected.status_code
        ),
        "stderr": verifiers.matches_regex(
            actual.stderr or "", expected.stderr or ""
        ),
    }

def __call__(self, group_name: str, case_name: str, actual: cli.CLIResult, expected: cli.CLIResult):
    if expected.status_code != 0:  # Error case
        return self.verify_error_case(actual, expected)
    
    # Success case logic
    return {
        "status_code": verifiers.matches_status_code(
            actual.status_code, expected.status_code, weight=0.1
        ),
        "output": verifiers.deepdiff_verify(
            actual.output, expected.output, weight=0.9
        ),
    }
```

#### Pattern 4: API Response Verification

Used by `trajectory_api` - verifies status codes, headers, and JSON schema.

```python
def __call__(self, group_name: str, case_name: str, actual: api.APIResult, expected: api.APIResult):
    results = {}
    
    # Always verify status code
    results["status_code"] = verifiers.matches_status_code(
        actual.status_code, expected.status_code, weight=0.2
    )
    
    # Verify headers if expected
    if expected.headers:
        results["headers"] = verifiers.deepdiff_verify(
            actual.headers or {}, expected.headers, weight=0.1
        )
        output_weight = 0.7
    else:
        output_weight = 0.8
    
    # Parse and verify JSON output against schema
    actual_output = parsers.parse_json(actual.output)
    results["output"] = verifiers.jsonschema_verify(
        actual_output, expected.output, weight=output_weight
    )
    
    return results
```

#### Pattern 5: Complex Output Parsing

Used by `eve_jump_planner` - handles multi-part output with separators.

```python
def __call__(self, group_name: str, case_name: str, actual: cli.CLIResult, expected: cli.CLIResult):
    if "error" in group_name:
        return self.verify_error_case(actual, expected)
    
    # Split output on separator and take the last part
    actual_stdout = parsers.maybe_split_string(
        parsers.extract_actual_output(actual, "---\n"), "---\n"
    )
    expected_stdout = parsers.maybe_split_string(
        parsers.ensure_expected_is_not_none(expected.output), "---\n"
    )
    
    return {
        "status_code": verifiers.matches_status_code(
            actual.status_code, expected.status_code, weight=0.1
        ),
        "output": verifiers.deepdiff_verify(
            actual_stdout, expected_stdout, weight=0.9
        ),
    }
```

### VerificationResult and Weights

Every verification returns a `VerificationResult` with:
- `diff`: Detailed difference information
- `is_correct`: Whether the verification passed
- `weight`: Importance weight (default: 1.0)

**Weight Guidelines:**
- **0.1-0.2**: Minor aspects (status codes, headers)
- **0.3-0.5**: Important aspects (file presence, basic structure)
- **0.6-0.8**: Core functionality (main output, key results)
- **0.9-1.0**: Critical aspects (must be correct)

**How Weights Work:**
- Final score = (sum of is_correct * weight) / (sum of all weights)
- Weights don't need to sum to 1.0
- Higher weights = more impact on final score
- Results with `is_correct=None` or `weight=0.0` are excluded from scoring

**Example:**
```python
{
    "status_code": VerificationResult(is_correct=True, weight=0.2),   # 0.2 points
    "output": VerificationResult(is_correct=False, weight=0.8),        # 0.0 points
}
# Score = (1*0.2 + 0*0.8) / (0.2 + 0.8) = 0.2 / 1.0 = 0.20 (20%)
```

### Return Value Structure

```python
{
    "status_code": VerificationResult(...),      # Standard field
    "output": VerificationResult(...),           # Standard field
    "files-output.csv": VerificationResult(...), # File reference
    "headers": VerificationResult(...),          # API-specific
}
```

**Valid attribute names:**
- Any field on the result object (`output`, `status_code`, `stderr`, etc.)
- File references in the format `files-{filename}`

**Important Notes:**
- You can return any subset of attributes - not all fields are required
- Attributes you don't verify will have `is_correct=None` and `weight=0.0` in the report
- Only verified attributes (those you return) contribute to the final score
- Use `files-{filename}` for file verification to match the report format

### VerificationResult Model

The [`VerificationResult`](../../../src/slop_code/evaluation/verifiers/models.py) model:

```python
class VerificationResult(BaseModel):
    diff: JsonValue                    # Detailed difference information
    is_correct: bool                   # Whether the verification passed
    weight: float = Field(default=1.0, gt=0.0)  # Importance weight
```

**Helper for creating results:**
```python
# Use the class method for proper DeepDiff handling
VerificationResult.create(diff=deep_diff_obj, is_correct=True, weight=0.8)
```

### Verifier Best Practices

#### DO ✅

1. **Use framework helpers** - `verifiers.deepdiff_verify()` for everything
2. **Weight appropriately** - reflect what matters for your problem
3. **Handle error cases separately** - different logic for success vs error
4. **Use parsers** - `parsers.parse_json()`, `parsers.parse_csv_content()`
5. **Keep it simple** - most verifiers are under 50 lines

#### DON'T ❌

1. **Don't write custom comparison logic** - use `deepdiff_verify`
2. **Don't ignore weights** - they determine scoring importance
3. **Don't assume string types** - handle None and non-string outputs
4. **Don't use wrong attribute names** - `output` not `stdout`, `files-{name}` for files
5. **Don't over-engineer** - the framework handles 95% of cases

## Complete Example: yaml_joiner

Let's walk through the [`yaml_joiner`](../../../examples/yaml_joiner/problem/) example to understand how loaders and verifiers work together.

### Problem Structure
```
yaml_joiner/problem/
├── loader.py
├── verifier.py
├── config.yaml
├── static_cfgs/
│   ├── A.yaml
│   ├── B.yaml
│   └── C.yaml
└── checkpoint_1/
    ├── config.yaml
    └── core/
        ├── single/
        │   ├── A.yaml
        │   ├── ARGS
        │   └── result.yaml
        └── multiple/
            ├── A.yaml
            ├── B.yaml
            ├── ARGS
            └── result.yaml
```

### Problem Configuration
```yaml
# config.yaml
name: yaml_joiner
description: A simple yaml problem to demonstrate static files/group files
tags:
  - tutorial 
  - cli
adapter:
  type: cli
  tracked_files:
  - result.yaml  # supports glob patterns
loader_script: loader.py
loader_entrypoint: Loader
```

### loader.py
```python
import shlex
from pathlib import Path
import yaml
from slop_code.evaluation.loaders import helpers, NoOpStore
from slop_code.evaluation.adapters import CLICase, CLIResult
from slop_code.execution.file_ops import InputFile

from slop_code.evaluation.config import GroupConfig

def load_case_dir(case_dir: Path, group_config: GroupConfig, checkpoint_name: str):
    """Load a single test case from directory."""
    # Get all YAML files except result.yaml and ARGS
    input_files = helpers.get_files_from_globs(
        case_dir, ["*.yaml", "**/*.yaml"], exclude={"result.yaml", "ARGS"}
    )
    
    # Read CLI arguments from ARGS file
    args = shlex.split((case_dir / "ARGS").read_text())
    
    # Read expected result from result.yaml
    with (case_dir / "result.yaml").open("r") as f:
        result = yaml.safe_load(f)

    # Create InputFile objects for all input files
    input_files = [
        InputFile.from_path(relative_to=case_dir, path=file)
        for file in input_files
    ]
    
    # Add group-level files (if any)
    input_files.extend(
        InputFile.from_path(relative_to=case_dir.parent, path=Path(group_file))
        for group_file in group_config.group_files
    )

    case = CLICase(
        id=case_dir.name,
        group=group_config.name,
        group_type=group_config.type,
        checkpoint=checkpoint_name,
        original_group=group_config.original_group,
        original_checkpoint=group_config.original_checkpoint,
        arguments=args,
        input_files=input_files,
        tracked_files=["result.yaml"],
    )
    
    result_obj = CLIResult(
        id=case_dir.name,
        group=group_config.name,
        group_type=group_config.type,
        status_code=0,
        files={"result.yaml": result},
    )
    return case, result_obj

class Loader:  # Note: No inheritance required
    def __init__(self, problem, checkpoint, *, use_placeholders=False):
        self.problem = problem
        self.checkpoint = checkpoint
        self.use_placeholders = use_placeholders

    def initialize_store(self):
        """Initialize case store."""
        return NoOpStore()

    def __call__(self, group, store):
        """Load all cases for a group."""
        group_dir = helpers.get_group_path(group, self.problem, self.checkpoint)
        
        # Discover all case directories in the group
        for case_dir in helpers.discover_dir_cases(group, group_dir):
            yield load_case_dir(case_dir, group, self.checkpoint.name)
```

### verifier.py
```python
from slop_code.evaluation.config import CheckpointConfig
from slop_code.evaluation.adapters import cli
from slop_code.evaluation.verifiers import VerificationResult, VerifierReturnType
from slop_code.evaluation.verifiers import parsers, verifiers

class Verifier:  # Note: No inheritance required
    def __init__(self, checkpoint_config: CheckpointConfig) -> None:
        self.checkpoint_config = checkpoint_config

    def verify_output(self, actual: cli.CLIResult, expected: cli.CLIResult) -> VerificationResult:
        """Verify the result.yaml file content."""
        # Parse YAML from actual result file
        actual_config = parsers.parse_yaml_file(
            actual, "result.yaml", allow_missing=True
        )
        # Compare with expected result
        return verifiers.deepdiff_verify(actual_config, expected.files["result.yaml"])

    def __call__(
        self,
        group_name: str,
        case_name: str,
        actual: cli.CLIResult,
        expected: cli.CLIResult,
    ) -> VerifierReturnType:
        if "error" in group_name:
            # Handle error cases - verify stderr and status code
            expected_stderr = parsers.ensure_expected_is_not_none(expected.stderr)
            return {
                "stderr": verifiers.matches_regex(actual.stderr, expected_stderr),
                "status_code": verifiers.matches_status_code(
                    actual.status_code, expected.status_code
                ),
            }
        
        # Handle success cases - verify status code and result file
        return {
            "status_code": verifiers.matches_status_code(
                actual.status_code, expected.status_code, weight=0.25
            ),
            "files-result.yaml": self.verify_output(actual, expected),
        }
```

### Test Case Example

#### Input Files
```yaml
# checkpoint_1/core/single/A.yaml
original: A
```

```bash
# checkpoint_1/core/single/ARGS
result.yaml -c A.yaml
```

#### Expected Result
```yaml
# checkpoint_1/core/single/result.yaml
A.yaml:
  original: A
```

### How It Works

1. **Loader discovers cases**: Finds `single/` and `multiple/` directories under `core/`
2. **Loader reads inputs**: 
   - Reads `A.yaml` as input file
   - Reads `ARGS` file for CLI arguments: `["result.yaml", "-c", "A.yaml"]`
   - Reads `result.yaml` as expected output
3. **Loader creates case**: [`CLICase`](src/slop_code/evaluation/adapters/cli.py) with input files and arguments, `CLIResult` with expected file content
4. **Verifier checks results**:
   - Verifies status code is 0 (weight: 0.25)
   - Parses actual `result.yaml` output and compares with expected using `deepdiff_verify`
5. **Framework scores**: Combines weighted results to determine pass/fail

## Testing Your Components

### Test the Loader
```python
# Test loader directly
from pathlib import Path
from loader import Loader
from slop_code.evaluation.config import GroupConfig, ProblemConfig, CheckpointConfig

# Create mock configs
problem = ProblemConfig.from_yaml(Path("yaml_joiner/problem"))
checkpoint = problem.load_checkpoint("checkpoint_1")

loader = Loader(problem, checkpoint)

for case, expected in loader(group, None):
    print(f"Loaded case: {case.id}")
    print(f"Arguments: {case.arguments}")
    print(f"Input files: {[f.path for f in case.input_files]}")
    print(f"Expected files: {list(expected.files.keys())}")
```

### Test the Verifier
```python
# Test verifier directly
from verifier import Verifier
from slop_code.evaluation.adapters import cli

verifier = Verifier(mock_config)

# Create mock results
actual = cli.CLIResult(
    status_code=0, 
    files={"result.yaml": {"A.yaml": {"original": "A"}}}
)
expected = cli.CLIResult(
    status_code=0, 
    files={"result.yaml": {"A.yaml": {"original": "A"}}}
)

results = verifier("core", "single", actual, expected)
print(f"Verification results: {results}")
for attr, result in results.items():
    print(f"  {attr}: correct={result.is_correct}, weight={result.weight}")
```

## Testing with `tools run-case`

The most effective way to test your loaders and verifiers is with the `tools run-case` command. This runs your actual loader and verifier against real test cases, giving you immediate feedback.

### Basic Usage

```bash
# First, create a test snapshot (or use an existing solution)
cp -r problems/my_problem/checkpoint_1/solution test_snapshot

# Run all cases
slop-code tools run-case \
  -s test_snapshot \
  -p my_problem \
  -c 1 \
  -e configs/environments/docker-python3.12-uv.yaml
```

### Filtering for Targeted Testing

```bash
# Test only the 'core' group
slop-code tools run-case ... --group core

# Test cases matching a pattern
slop-code tools run-case ... --case "test_valid_*"

# Test error handling cases
slop-code tools run-case ... --group errors
```

### Debugging with Full Output

The `--full` flag shows complete verification reports with diffs:

```bash
slop-code tools run-case \
  -s test_snapshot \
  -p my_problem -c 1 \
  -e configs/environments/docker-python3.12-uv.yaml \
  --case failing_test \
  --full
```

This outputs the complete `VerifierReport` including:
- `actual` and `expected` values for each attribute
- `diff` information showing exactly what differs
- `is_correct` status per attribute
- Weighted scores

### Iterative Development Workflow

1. **Start with your solution**: Copy your reference solution to a test directory
2. **Run all cases**: `slop-code tools run-case -s solution -p my_problem -c 1 -e ...`
3. **Identify failures**: Look for `"passed": false` in the output
4. **Debug specific case**: Re-run with `--case failing_case --full`
5. **Fix loader/verifier**: Make changes based on the detailed diff
6. **Re-run**: Repeat until all cases pass

### Common Debugging Scenarios

**Loader not finding cases:**
```bash
# Check if cases are being discovered
slop-code tools run-case ... --group my_group
# Empty output? Check your loader's discover logic
```

**Verification always failing:**
```bash
# Get full diff to see what's different
slop-code tools run-case ... --case always_fails --full | jq '.[0].results'
```

**Testing specific file outputs:**
```bash
# Run and check file verification results
slop-code tools run-case ... --case file_test --full | \
  jq '.[0].results | to_entries | .[] | select(.key | startswith("files-"))'
```

### JSON Output for Scripting

The JSON output enables powerful scripting:

```bash
# Count passing vs failing
slop-code tools run-case ... | jq '[.[] | .passed] | group_by(.) | map({(.[0] | tostring): length}) | add'

# Get all failing case names
slop-code tools run-case ... | jq -r '.[] | select(.passed == false) | .id'

# Average score across cases
slop-code tools run-case ... | jq '[.[].score] | add / length'
```

### Comparison with Unit Testing

| Approach | When to Use |
|----------|-------------|
| `tools run-case` | Testing actual loader/verifier behavior, debugging failures, iterative development |
| Unit tests | Testing helper functions in isolation, edge cases for parsers, CI integration |

**Recommendation:** Use `tools run-case` as your primary testing method, with unit tests for complex helper functions.

## Common Pitfalls to Avoid

### Loader Pitfalls
1. **Complex directory traversal** - keep case discovery simple
2. **Hardcoded paths** - use framework helpers
3. **Ignoring case_order** - important for API tests
4. **Poor error handling** - check file existence before reading
5. **Inconsistent naming** - use descriptive case IDs

### Verifier Pitfalls
1. **Custom comparison logic** - use `deepdiff_verify`
2. **Wrong attribute names** - `output` not `stdout`, `files-{name}` for files
3. **Ignoring weights** - they determine scoring
4. **Type assumptions** - handle None and non-string outputs
5. **Over-engineering** - most verifiers are simple

## Framework Reference

### Loader Protocol Details
- **BaseLoader**: [`src/slop_code/evaluation/loaders/loader_protocol.py`](../../../src/slop_code/evaluation/loaders/loader_protocol.py#L89)
- **Helpers**: [`src/slop_code/evaluation/loaders/helpers.py`](../../../src/slop_code/evaluation/loaders/helpers.py)
- **Protocol**: [`GroupLoader`](../../../src/slop_code/evaluation/loaders/loader_protocol.py#L58)

### Verifier Protocol Details
- **Protocol**: [`VerifierProtocol`](../../../src/slop_code/evaluation/verifiers/models.py#L187)
- **Verification helpers**: [`src/slop_code/evaluation/verifiers/verifiers.py`](../../../src/slop_code/evaluation/verifiers/verifiers.py)
- **Parser utilities**: [`src/slop_code/evaluation/verifiers/parsers.py`](../../../src/slop_code/evaluation/verifiers/parsers.py)
- **Models**: [`src/slop_code/evaluation/verifiers/models.py`](../../../src/slop_code/evaluation/verifiers/models.py)

## Quick Reference

### Common Questions

**Q: Do I need to inherit from BaseLoader?**
A: No - you can implement the `GroupLoader` protocol directly. Inheriting from `BaseLoader` just gives you a default `initialize_store()` implementation.

**Q: What's the difference between CaseResult, CLIResult, and APIResult?**
A: `CaseResult` is the base protocol. `CLIResult` is for CLI adapters, `APIResult` is for API adapters. Use the concrete type in your code.

**Q: When do I need a custom CaseStore?**
A: Only when test cases have dependencies (e.g., API tests where later cases need IDs from earlier cases). Most loaders use `NoOpStore()`.

**Q: How do weights affect scoring?**
A: Score = Σ(is_correct × weight) / Σ(weight). Higher weights = more impact. Weights don't need to sum to 1.0.

**Q: Can I verify only some attributes?**
A: Yes! You only need to return verification results for attributes you care about. Others will be marked with `is_correct=None` and `weight=0.0`.

**Q: What's the difference between static placeholders and store placeholders?**
A: Static placeholders (`{{static:value}}`) come from config and are fixed. Store placeholders (`{{store.value}}`) come from previous case results and are dynamic.

**Q: How does case_order work?**
A: It's a list of case IDs (filename without extension) in the group config. Cases execute in that exact order. Required for stateful tests.

**Q: What does discover_dir_cases() exclude?**
A: It excludes directories listed in `group_config.group_files` to avoid treating shared resource directories as test cases.

### Must-Know Helpers

**Loaders:**
- `helpers.get_group_path()` - Get group directory path
- `helpers.discover_dir_cases()` - Find case directories
- `helpers.get_files_from_globs()` - Get files with glob patterns
- `NoOpStore()` - Default store for stateless tests

**Verifiers:**
- `verifiers.deepdiff_verify()` - Use for ALL comparisons
- `verifiers.matches_status_code()` - Verify status codes
- `verifiers.jsonschema_verify()` - Validate JSON schemas
- `verifiers.matches_regex()` - Pattern matching
- `parsers.parse_*()` - Parse JSON, YAML, CSV, JSONL, markdown tables
- `parsers.extract_actual_output()` - Extract and normalize output
- `parsers.maybe_split_string()` - Split strings on delimiters

## Next Steps

- **Configuration**: [Configuration Guide](configuration.md)
- **Adapters**: [Adapters Guide](adapters.md)
- **Reporting**: [Reporting Guide](reporting.md)
- **Troubleshooting**: [Troubleshooting Guide](troubleshooting.md)

Remember: **Keep it simple!** The framework provides powerful helpers that handle most common cases. Focus on what makes your problem unique, and let the framework handle the boilerplate!
