---
version: 1.1
last_updated: 2025-11-18
---

# Problem Authoring Troubleshooting Guide

This guide provides solutions to common issues encountered when creating and debugging evaluation problems.

## Table of Contents

- [Loader Issues](#loader-issues)
- [Verifier Issues](#verifier-issues)
- [Configuration Issues](#configuration-issues)
- [Test Case Issues](#test-case-issues)
- [Execution Issues](#execution-issues)
- [API-Specific Issues](#api-specific-issues)
- [Static Assets Issues](#static-assets-issues)
- [Debugging Tools](#debugging-tools)

## Loader Issues

### Problem: "No test cases found"

**Symptoms:**
- Loader yields no cases
- Empty test results
- Message: "No cases for group X"

**Causes and fixes:**

#### Cause 1: Wrong directory structure

**For CLI problems:**
```bash
# Wrong:
checkpoint_1/core/test_case.yaml     # File, not directory

# Right:
checkpoint_1/core/test_case/         # Directory
  ├── case.yaml
  └── expected.txt
```

**For API problems:**
```bash
# Wrong:
checkpoint_1/core/test_case/         # Directory, not file
  └── case.yaml

# Right:
checkpoint_1/core/test_case.yaml     # File
```

#### Cause 2: Missing `case_order` for API

```yaml
# Wrong:
groups:
  core:
    type: Core
    # Missing case_order!

# Right:
groups:
  core:
    type: Core
    case_order:
      - create_item
      - get_item
```

#### Cause 3: Case names don't match files

```yaml
# config.yaml
case_order:
  - create_user              # Looking for create_user.yaml

# But file is named:
# checkpoint_1/core/create-user.yaml   ← Hyphen, not underscore!
```

**Fix**: Ensure filenames match `case_order` exactly.

### Problem: "FileNotFoundError" when loading cases

**Symptoms:**
```
FileNotFoundError: checkpoint_1/core/test_case.yaml
```

**Causes and fixes:**

#### Cause 1: Case in `case_order` but file missing

```yaml
case_order:
  - setup
  - test_feature     # ← No test_feature.yaml file!
  - cleanup
```

**Fix**: Create the missing file or remove from `case_order`.

#### Cause 2: Wrong group directory

```python
# Loader tries to find:
checkpoint_1/functionality/test.yaml

# But file is at:
checkpoint_1/core/test.yaml
```

**Fix**: Move file to correct group or update config.

#### Cause 3: Typo in filename

```yaml
case_order:
  - create_user

# But file is:
checkpoint_1/core/creat_user.yaml    # Missing 'e'
```

**Fix**: Rename file or fix `case_order`.

### Problem: "Invalid YAML" when parsing cases

**Symptoms:**
```
yaml.scanner.ScannerError: mapping values are not allowed here
```

**Causes and fixes:**

#### Cause 1: Indentation error

```yaml
# Wrong:
case:
  body:
  scope:           # ← Should be indented
    env: prod

# Right:
case:
  body:
    scope:
      env: prod
```

#### Cause 2: Missing quotes

```yaml
# Wrong:
path: /v1/users/{id}    # { } have special meaning

# Right:
path: "/v1/users/{id}"
```

#### Cause 3: Multiline string format

```yaml
# Wrong:
content: |
  line 1
    line 2          # ← Inconsistent indentation

# Right:
content: |
  line 1
  line 2
```

**Debug**: Validate YAML with:
```bash
python -c "import yaml; yaml.safe_load(open('case.yaml'))"
```

## Verifier Issues

### Problem: "All tests failing with score 0.0"

**Symptoms:**
- Every test fails
- Score always 0.0
- Diff shows everything is different

**Causes and fixes:**

#### Cause 1: Wrong output field

```python
# Verifier checks:
actual.output         # This is the whole output string

# But actual data is in:
actual.files["output.json"]    # Tracked file
```

**Fix**: Parse tracked files:
```python
output_file = actual.files.get("output.json")
if output_file:
    actual_data = json.loads(output_file.content)
```

#### Cause 2: Not parsing output format

```python
# Wrong: Comparing string to dict
actual.output              # "{'key': 'value'}"
expected.output            # {'key': 'value'}

# Right: Parse first
actual_data = parsers.parse_json(actual.output)
```

#### Cause 3: Wrong expected output location

```python
# Loader puts expected in wrong field
expected = CLIResult(
    output="data"           # ← String
)

# But verifier expects:
expected.output = {"parsed": "data"}   # ← Dict
```

**Fix**: Ensure loader parses expected output correctly.

### Problem: "Tests pass but shouldn't"

**Symptoms:**
- Obviously wrong output scores 1.0
- No diff shown
- False positives

**Causes and fixes:**

#### Cause 1: Verifier returns wrong type

```python
# Wrong:
def __call__(self, ...):
    return 1.0          # ← Wrong type!

# Right:
def __call__(self, ...):
    return {
        "status_code": VerificationResult(...),
        "output": VerificationResult(...)
    }
```

#### Cause 2: Not actually comparing

```python
# Wrong:
def verify_output(self, actual, expected):
    return VerificationResult(score=1.0, ...)  # Always returns 1.0!

# Right:
def verify_output(self, actual, expected):
    return verifiers.deepdiff_verify(actual, expected, weight=0.8)
```

#### Cause 3: Comparing wrong values

```python
# Wrong: Compares expected to itself
verifiers.deepdiff_verify(expected, expected, ...)  # Always equal!

# Right:
verifiers.deepdiff_verify(actual, expected, ...)
```

### Problem: "Tests fail due to timestamps/IDs"

**Symptoms:**
- Diff shows only timestamp differences
- UUIDs don't match
- Auto-increment IDs differ

**Causes and fixes:**

#### Cause 1: Exact timestamp matching

```yaml
# Expected:
created_at: "2025-11-06T15:30:00Z"

# Actual:
created_at: "2025-11-06T15:30:02Z"    # 2 seconds later

# Fails because not exact match
```

**Fix 1**: Normalize timestamps in verifier:
```python
def _align_datetimes(self, expected, actual):
    expected_dt = parse_datetime(expected)
    actual_dt = parse_datetime(actual)
    if abs(expected_dt - actual_dt) <= timedelta(seconds=5):
        return actual, actual  # Treat as equal
    return expected, actual
```

**Fix 2**: Use JSON Schema:
```yaml
expected:
  output:
    type: object
    properties:
      created_at: {type: string, format: date-time}
```

#### Cause 2: Generated IDs

```yaml
# Expected:
id: "123e4567-e89b-12d3-a456-426614174000"

# Actual:
id: "7c9e6679-7425-40de-944b-e07fc1f90ae7"  # Different UUID

# Fails
```

**Fix**: Use dynamic placeholder or JSON Schema:
```yaml
expected:
  output:
    id: "{{dynamic}}"     # Any value accepted
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

#### Cause 1: Missing directory

```yaml
# config.yaml lists:
checkpoints:
  - checkpoint_1
  - checkpoint_2       # ← No checkpoint_2/ directory!
```

**Fix**: Create missing checkpoint directory.

#### Cause 2: Typo in checkpoint list

```yaml
checkpoints:
  - checkpoint_1
  - checkpont_2        # ← Missing 'i'
```

**Fix**: Match directory name exactly.

### Problem: "Invalid adapter configuration"

**Symptoms:**
```
ValidationError: adapter.type is required
```

**Causes and fixes:**

#### Cause 1: Missing required fields

```yaml
# Wrong:
adapter:
  tracked_files: []     # Missing 'type'

# Right:
adapter:
  type: cli
  tracked_files: []
```

#### Cause 2: Wrong adapter type

```yaml
adapter:
  type: rest            # ← Should be 'api'
```

**Fix**: Use valid types: `cli`, `api`, or `playwright`

## Test Case Issues

### Problem: "Expected output doesn't match actual"

**Symptoms:**
- Diff shows differences
- But actual output looks correct

**Causes and fixes:**

#### Cause 1: Whitespace differences

```
Expected: "Hello World"
Actual:   "Hello World\n"    # Extra newline
```

**Fix**: Strip whitespace in verifier or expected:
```python
actual_clean = actual.output.strip()
```

#### Cause 2: Line ending differences

```
Expected: "line1\nline2"      # LF
Actual:   "line1\r\nline2"    # CRLF
```

**Fix**: Normalize line endings:
```python
actual_normalized = actual.output.replace('\r\n', '\n')
```

#### Cause 3: Floating point precision

```
Expected: {"value": 1.23}
Actual:   {"value": 1.2300000000000002}
```

**Fix**: Round or use approximate matching:
```python
import math
if math.isclose(actual["value"], expected["value"], rel_tol=1e-9):
    ...
```

### Problem: "Input files not found in workspace"

**Symptoms:**
```
FileNotFoundError: schedule.yaml (from CLI execution)
```

**Causes and fixes:**

#### Cause 1: Path in `case.yaml` doesn't match CLI argument

```yaml
# case.yaml
arguments: --schedule config.yaml    # Looking for config.yaml
input_files:
  - path: schedule.yaml              # But creates schedule.yaml!
```

**Fix**: Match names:
```yaml
arguments: --schedule schedule.yaml
input_files:
  - path: schedule.yaml
```

#### Cause 2: Relative path in wrong location

```yaml
arguments: --schedule configs/schedule.yaml
input_files:
  - path: schedule.yaml    # Creates at root, not in configs/
```

**Fix**: Create nested structure:
```yaml
input_files:
  - path: configs/schedule.yaml
```

## Execution Issues

### Problem: "Timeout on every test"

**Symptoms:**
- All tests timeout
- No output captured

**Causes and fixes:**

#### Cause 1: Infinite loop in submission

```python
# Agent's code:
while True:
    # Never exits!
    process_data()
```

**Fix**: Lower timeout to fail fast, fix agent code.

#### Cause 2: Waiting for input

```python
# Agent's code:
name = input("Enter name: ")    # Hangs waiting for stdin
```

**Fix**: Don't use `input()` in evaluated code.

#### Cause 3: Timeout too short

```yaml
# config.yaml
timeout: 1    # Only 1 second!
```

**Fix**: Increase timeout to reasonable value:
```yaml
timeout: 30    # 30 seconds
```

### Problem: "ImportError" during execution

**Symptoms:**
```
ImportError: No module named 'yaml'
```

**Causes and fixes:**

#### Cause: Missing dependencies

```python
# Agent's code:
import yaml    # Not installed in environment
```

**Fix**: Specify dependencies:

**Option 1**: Document in spec:
```markdown
## Requirements

Your solution should include a `requirements.txt`:
```
pyyaml==6.0
```

**Option 2**: Pre-install in environment config:
```yaml
# environment config
setup:
  eval_commands:  # Hidden from agents, evaluation only
    - pip install pyyaml
```

**Note:** Use `eval_commands` for dependencies that should be transparently installed during evaluation. See the environment configuration section in your environment YAML files for details.

## API-Specific Issues

### Problem: "Health check fails"

**Symptoms:**
```
Error: Server health check failed after 10 seconds
```

**Causes and fixes:**

#### Cause 1: Server crashes on startup

```python
# Server code:
app = Flask(__name__)
# Crashes here due to missing config
```

**Check logs**: Look at server stderr for crash details.

#### Cause 2: Wrong health endpoint

```yaml
# config.yaml
adapter:
  health_path: /health    # Configured as /health

# But server has:
@app.get("/healthz")      # ← Different path!
```

**Fix**: Match paths:
```yaml
health_path: /healthz
```

#### Cause 3: Health endpoint not returning correct format

```python
# Wrong:
@app.get("/healthz")
def health():
    return "OK"           # ← Should be JSON

# Right:
@app.get("/healthz")
def health():
    return {"ok": True}
```

### Problem: "Cases run in wrong order"

**Symptoms:**
- Later cases fail with 404
- State seems wrong
- Tests fail randomly

**Causes and fixes:**

#### Cause: Missing or wrong `case_order`

```yaml
# Wrong: No case_order (undefined order)
groups:
  core:
    type: Core

# Right:
groups:
  core:
    type: Core
    case_order:
      - create_item
      - get_item
      - update_item
```

### Problem: "API returns 500 on every request"

**Symptoms:**
- All requests return 500
- Server logs show errors

**Causes and fixes:**

#### Cause 1: Exception in handler

```python
@app.post("/users")
def create_user():
    data = request.json
    user = User(**data)    # Crashes if fields missing
    return user.to_dict()
```

**Fix**: Add error handling:
```python
@app.post("/users")
def create_user():
    try:
        data = request.json
        user = User(**data)
        return user.to_dict(), 201
    except Exception as e:
        return {"error": {"code": "internal", "message": str(e)}}, 500
```

#### Cause 2: Database not initialized

```python
# Server starts without DB
@app.post("/users")
def create_user():
    db.insert(...)    # db is None!
```

**Fix**: Initialize in startup:
```python
def main():
    init_database()
    app.run()
```

## Static Assets Issues

### Problem: "Static assets not found"

**Symptoms:**
```
FileNotFoundError: /workspace/files/data.csv
```

**Causes and fixes:**

#### Cause 1: Wrong placeholder syntax

```yaml
# Wrong:
arguments: --files {static:files}      # Missing braces

# Right:
arguments: --files {{static:files}}
```

#### Cause 2: Asset path doesn't exist

```yaml
# config.yaml
static_assets:
  data:
    path: datasets           # But no problems/my_problem/datasets/!

# Fix: Create directory or fix path
static_assets:
  data:
    path: data               # problems/my_problem/data/ exists
```

#### Cause 3: Asset not defined

```yaml
# case.yaml references:
arguments: --db {{static:database}}

# But config.yaml doesn't define it:
static_assets:
  files:                     # No 'database' asset!
    path: files
```

**Fix**: Add to config:
```yaml
static_assets:
  files:
    path: files
  database:
    path: db
```

### Problem: "Static asset path is absolute in tests"

**Symptoms:**
```
Expected: files/data.csv
Actual:   /tmp/workspace/files/data.csv
```

**Causes and fixes:**

#### Cause: Not stripping mount prefix

```python
# Agent outputs absolute path:
print(f"/tmp/workspace/files/data.csv")

# But expected uses relative:
"files/data.csv"
```

**Fix Option 1**: Use relative paths in expected output

**Fix Option 2**: Strip prefix in verifier:
```python
def normalize_path(path):
    return path.replace("/tmp/workspace/", "")
```

## Debugging Tools

### Tool 1: Test Loader Directly

```python
# test_loader.py
from pathlib import Path
# Ensure repository root is in PYTHONPATH
import sys
sys.path.append(".")

from problems.my_problem.loader import Loader
from slop_code.evaluation import ProblemConfig

# Load configs
problem_config = ProblemConfig.from_yaml(Path("problems/my_problem"))
checkpoint_config = problem_config.load_checkpoint("checkpoint_1")

# Create loader
loader = Loader(problem_config, checkpoint_config)
store = loader.initialize_store()

# Load cases
for group in checkpoint_config.groups.values():
    print(f"\nGroup: {group.name}")
    for case, expected in loader(group, store):
        print(f"  - Case: {case.id}")
        print(f"    Args: {case.arguments}")
        print(f"    Expected status: {expected.status_code}")
```

### Tool 2: Test Verifier Directly

```python
# test_verifier.py
from problems.my_problem.verifier import Verifier
from slop_code.evaluation.adapters import CLIResult

# Create verifier
verifier = Verifier(checkpoint_config)

# Create mock actual/expected
actual = CLIResult(
    id="test",
    group="core",
    status_code=0,
    output='{"result": "value"}'
)
expected = CLIResult(
    id="test",
    group="core",
    status_code=0,
    output={"result": "value"}
)

# Verify
results = verifier("core", "test", actual, expected)
print("Results:", results)
for key, result in results.items():
    print(f"  {key}: score={result.score}, message={result.message}")
```

### Tool 3: Validate YAML Files

```bash
# Check all test case YAML files
find problems/my_problem -name "*.yaml" -exec \
  python -c "import yaml; yaml.safe_load(open('{}'))" \;
```

### Tool 4: Run Single Test Case

```bash
# Create test workspace
mkdir -p /tmp/test_case
cd /tmp/test_case

# Extract input files from case.yaml and create them
# Then run CLI command manually
python -m my_solution --schedule schedule.yaml --now 2025-01-10T10:00:00Z

# Compare output
cat output.jsonl
```

### Tool 5: Use Dashboard

```bash
# Run evaluation
uv run python -m slop_code.entrypoints.cli eval \
  outputs/agent_run_dir

# Launch dashboard
uv run python -m slop_code.visualization.app outputs/
```

Navigate to failed test to see:
- Input provided
- Expected output
- Actual output
- Detailed diff

### Tool 6: Enable Debug Logging

```python
# In loader.py or verifier.py
import structlog
logger = structlog.get_logger(__name__)

class Loader:
    def __call__(self, group, store):
        logger.info("Loading cases", group=group.name)
        for case_dir in discover_cases():
            logger.debug("Found case", case=case_dir.name)
            yield self.load_case(case_dir)
```

## Checklist for Debugging

When a problem isn't working:

**Configuration:**
- [ ] `name` in config.yaml matches directory name
- [ ] All checkpoints in list have corresponding directories
- [ ] Adapter type is correct (cli/api/playwright)
- [ ] Required adapter fields are present

**Loader:**
- [ ] Case files exist in correct locations
- [ ] CLI uses directories, API uses files
- [ ] API has `case_order` defined
- [ ] Loader yields (case, expected) tuples
- [ ] All YAML files are valid

**Verifier:**
- [ ] Returns dict of VerificationResult objects
- [ ] Uses framework helpers (deepdiff_verify, etc.)
- [ ] Parses output format correctly
- [ ] Handles timestamps/IDs appropriately

**Test Cases:**
- [ ] Expected output format matches actual
- [ ] File paths are correct
- [ ] Static asset placeholders use {{static:name}}
- [ ] API case_order is complete and correct

**Execution:**
- [ ] Timeouts are reasonable
- [ ] Dependencies are installed
- [ ] API health endpoint works
- [ ] No infinite loops or blocking input

## Next Steps

- **[Test Cases Guide](test-cases.md)** - Write better test cases
- **[Config Schema](config-schema.md)** - Verify configuration
- **[Simple CLI Example](examples/simple-cli.md)** - See working example
- **[Stateful API Example](examples/stateful-api.md)** - See API example
- **[Structure Guide](structure.md)** - Check directory layout
