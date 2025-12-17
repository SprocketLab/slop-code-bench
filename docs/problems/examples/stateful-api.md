---
version: 1.0
last_updated: 2025-11-06
---

# Example Walkthrough: Stateful API Problem (`dynamic_config_service_api`)

This document walks through the `dynamic_config_service_api` problem as a complete example of an API-based evaluation problem with stateful test sequences. We'll examine how it differs from CLI problems and why.

## Problem Overview

**What it tests**: A REST API for managing versioned configuration objects:
1. Create immutable config versions
2. Activate specific versions (rollback)
3. Resolve configs with includes/inheritance
4. Handle scope-based namespacing

**Why this structure**: This problem demonstrates:
- Stateful HTTP workflows (create → read → update → delete)
- JSON Schema validation
- Complex business logic (versioning, includes, conflict detection)
- Timestamp normalization for non-deterministic values

## Directory Structure

```
problems/dynamic_config_service_api/
├── config.yaml                   # API problem configuration
├── loader.py                     # Simple YAML file loader
├── verifier.py                   # JSON/schema validation with timestamp normalization
├── checkpoint_1/
│   ├── spec.md                  # API specification
│   ├── spec_cases/              # Basic API compliance
│   │   ├── create_base_v1.yaml
│   │   ├── create_billing_v1_including_base.yaml
│   │   ├── get_active_billing.yaml
│   │   └── ... (more cases in order)
│   ├── functionality/           # Advanced features
│   │   ├── setup_array_base.yaml
│   │   ├── activate_specific_version.yaml
│   │   └── ... (more cases)
│   └── spec_errors/             # Error handling
│       ├── missing_pair_get_active.yaml
│       ├── invalid_input_create_missing_scope.yaml
│       └── ... (more errors)
├── checkpoint_2/                # Extended features
├── checkpoint_3/                # Complex merge scenarios
└── checkpoint_4/                # Rate limiting and scaling
```

**Key difference from CLI**: Test cases are YAML files (not directories), and order matters!

## Component Breakdown

### 1. Root Configuration (`config.yaml`)

```yaml
adapter:
  address: 127.0.0.1              # ← Server address
  health_path: /healthz           # ← Health check endpoint
  startup_timeout_s: 10           # ← Wait for server to start
  tracked_files: []               # ← No file outputs for APIs
  type: api                       # ← API adapter
  response_is_json: true          # ← All responses are JSON

category: api-management
checkpoints:
  checkpoint_1:
    order: 1
    path: checkpoint_1
    groups:
      spec_cases:
        type: Core
        case_order:
          - create_base_v1
          - create_billing_v1_including_base
      functionality:
        type: Functionality
      spec_errors:
        type: Error
    specification: spec.md
    state: Core Tests
  checkpoint_2:
    order: 2
    path: checkpoint_2
    groups:
      migrations:
        type: Core
    specification: spec.md
    state: Core Tests
  checkpoint_3:
    order: 3
    path: checkpoint_3
    groups:
      migrations:
        type: Core
      regression:
        type: Regression
    specification: spec.md
    state: Full Tests
  checkpoint_4:
    order: 4
    path: checkpoint_4
    groups:
      performance:
        type: Functionality
    specification: spec.md
    state: Verified

description: 'A versioned config service...'
difficulty: Medium

entry_file: config_server         # ← Server module to start

loader_script: loader.py
loader_entrypoint: Loader

name: dynamic_config_service_api
tags: [api, versioned, config-management, json, rest]
timeout: 10
version: 1
```

**Key differences from CLI:**

1. **`adapter.type: api`**
   - Framework starts the server before running tests
   - Waits for `/healthz` to return 200 OK
   - Sends HTTP requests instead of CLI commands

2. **`health_path`**
   - Required for API problems
   - Framework polls this endpoint until server is ready
   - Must return `200 OK` with `{"ok": true}`

3. **`address` and `startup_timeout_s`**
   - Where to connect to the server
   - How long to wait for startup

4. **`tracked_files: []`**
   - APIs don't typically write files
   - Responses are captured directly

### 2. Checkpoint 1 Entry

Located in `config.yaml → checkpoints.checkpoint_1`

```yaml
checkpoints:
  checkpoint_1:
    order: 1
    path: checkpoint_1
    groups:
      spec_cases:                 # ← Basic API spec compliance
        type: Core
        timeout: 20
        case_order:               # ← REQUIRED: Explicit ordering
          - create_base_v1
          - create_billing_v1_including_base
          - list_versions_billing
          - get_active_billing
          - resolve_billing_active
          - create_billing_v2_override_pool
          - list_versions_after_second
          - resolve_billing_active_after_second
          - rollback_billing_to_v1
          - get_active_billing_after_rollback

      functionality:              # ← Advanced features
        type: Functionality
        timeout: 20
        case_order:
          - setup_array_base
          - setup_type_conflict_base
          - get_specific_version
          - activate_specific_version
          # ... more cases

      spec_errors:                # ← Error handling
        type: Error
        timeout: 20
        case_order:
          - missing_pair_get_active
          - update_inactive_scope
          - activate_missing_version
          # ... more cases

    specification: spec.md        # ← API spec instructions
    state: Core Tests
    timeout: 20
    version: 1
```

**Critical difference from CLI:**

- **`case_order` is REQUIRED** for API problems
- Tests execute in exact order listed
- Later tests depend on state created by earlier tests
- Each group has independent state (different sequences)

**Why order matters:**

```
create_base_v1              → Creates config "base" v1
↓
create_billing_v1_including_base  → Creates "billing" v1, includes "base"
↓
get_active_billing          → Retrieves "billing" (depends on it existing)
↓
rollback_billing_to_v1      → Rolls back "billing" (depends on v2 existing)
```

### 3. Specification (`checkpoint_1/spec.md`)

```markdown
Design and implement a small REST service that stores JSON configuration
objects with **immutable versions**, supports **scoping**, **rollback**
to any earlier version, and **imports/inheritance** across configs.

## Deliverable

A network service (single process) exposing HTTP/JSON endpoints.

* **Entrypoint:** `config_server`.
* **Flags:**
  * `--address` (default `0.0.0.0`)
  * `--port` (default `8080`)
* **Healthcheck:** `GET /healthz` → `200 OK` and `{"ok":true}`.
* **Errors:** Non-2xx responses must be JSON with this shape:
  ```json
  { "error": { "code": "...", "message": "...", "details": {} } }
  ```

## API (required)

### Create a new version
`POST /v1/configs/{name}`

Body:
```json
{
  "scope": { "k":"v" },
  "config": { /* arbitrary json */ },
  "includes": [ /* optional */ ]
}
```

Returns `201 Created` with version info.

### Get active version
`POST /v1/configs/{name}:active`

Body:
```json
{ "scope": { "k":"v" } }
```

Returns the currently active version for this (name, scope) pair.
...
```

**Key elements:**

1. **Server requirements**: Address, port, health endpoint
2. **API specification**: Every endpoint documented
3. **Error format**: Structured error responses required
4. **JSON-only**: All requests/responses are JSON

### 4. Test Case Structure (Spec Cases)

#### Example: `create_base_v1.yaml`

```yaml
case:                             # ← Request definition
  id: create_base_v1
  method: POST                    # ← HTTP method
  path: /v1/configs/base          # ← URL path
  body:                           # ← Request body (JSON)
    scope:
      env: prod
    config:
      db:
        host: prod.db
        pool: 4

expected:                         # ← Expected response
  status_code: 201                # ← HTTP status
  output:                         # ← Response body
    name: base
    scope:
      env: prod
    version: 1
    active: true
```

**What happens:**

1. Framework sends: `POST /v1/configs/base` with JSON body
2. Server processes request, creates config "base" v1
3. Framework captures response
4. Verifier compares against `expected`

#### Example: Stateful Test (`get_active_billing.yaml`)

```yaml
case:
  id: get_active_billing
  method: POST
  path: /v1/configs/billing:active
  body:
    scope:
      env: prod

expected:
  status_code: 200
  output:
    name: billing
    scope:
      env: prod
    version: 1                    # ← Depends on create_billing_v1... running first
    active: true
```

**Why it's stateful:**

- Depends on `create_billing_v1_including_base` running first
- Without that prior request, this endpoint returns 404
- `case_order` ensures correct execution sequence

#### Example: Error Case (`missing_pair_get_active.yaml`)

```yaml
case:
  id: missing_pair_get_active
  method: POST
  path: /v1/configs/nonexistent:active
  body:
    scope:
      env: prod

expected:
  status_code: 404
  output:
    error:
      code: not_found
      message: Config pair not found
      details: {}
```

**Error validation:**

- Expects 404 status
- Verifies error response structure
- Checks error code matches spec

### 5. Loader Implementation (`loader.py`)

The loader for API problems is much simpler than CLI!

```python
class Loader(BaseLoader):
    def load_case(self, case_file: Path, group_config: GroupConfig):
        # Read YAML file
        contents = case_file.read_text()
        case_yaml = yaml.safe_load(contents)

        # Create APICase from "case" section
        case = APICase(
            group=group_config.name,
            group_type=group_config.type,
            checkpoint=self.checkpoint.name,
            **case_yaml["case"],        # ← Unpack method, path, body, etc.
        )

        # Create APIResult from "expected" section
        expected = APIResult(
            id=case_file.stem,
            group=group_config.name,
            group_type=group_config.type,
            **case_yaml["expected"],    # ← Unpack status_code, output, etc.
        )

        return case, expected

    def __call__(self, group: GroupConfig, store: CaseStore):
        group_dir = helpers.get_group_path(group, self.problem, self.checkpoint)

        # CRITICAL: Iterate in case_order
        for case_name in group.case_order:
            case_file = group_dir / f"{case_name}.yaml"
            yield self.load_case(case_file, group)
```

**Key features:**

1. **File-based**: Each case is a single YAML file (not a directory)
2. **Respects case_order**: Iterates through cases in specified order
3. **Simple unpacking**: Case YAML maps directly to APICase/APIResult fields
4. **No complex logic**: Just read YAML and create objects

**Why simpler than CLI:**
- No multiple input files per case
- No complex argument parsing
- YAML structure matches object fields directly

### 6. Verifier Implementation (`verifier.py`)

The verifier handles API-specific challenges:

```python
class Verifier:
    def __call__(self, group_name, case_name, actual, expected):
        results = {}

        # 1. Always verify status code (20% weight)
        results["status_code"] = verifiers.matches_status_code(
            actual.status_code,
            expected.status_code,
            weight=0.2
        )

        # 2. Optionally verify headers (10% weight if present)
        if expected.headers:
            results["headers"] = verifiers.deepdiff_verify(
                actual.headers or {},
                expected.headers,
                weight=0.1
            )
            output_weight = 0.7
        else:
            output_weight = 0.8

        # 3. Parse JSON bodies
        actual_body = parsers.parse_json(actual.output)
        expected_body = parsers.parse_json(expected.output)

        # 4. Detect JSON Schema in expected
        if self._is_json_schema(expected_body):
            results["output"] = verifiers.jsonschema_verify(
                actual_body,
                expected_body,
                weight=output_weight
            )
            return results

        # 5. Normalize timestamps (within 5 second tolerance)
        normalized_expected, normalized_actual = self._normalize_for_comparison(
            expected_body,
            actual_body
        )

        # 6. Deep compare normalized bodies
        results["output"] = verifiers.deepdiff_verify(
            normalized_actual,
            normalized_expected,
            weight=output_weight
        )

        return results
```

**Advanced features:**

#### Feature 1: JSON Schema Detection

```python
def _is_json_schema(self, payload):
    """Detect if expected output is a JSON Schema."""
    if not isinstance(payload, dict):
        return False

    # Check for schema keywords
    if JSON_SCHEMA_KEYS.intersection(payload):
        return True

    # Check for type declaration with properties/items
    schema_type = payload.get("type")
    return schema_type in {"object", "array", "string", ...} and \
           any(key in payload for key in ("properties", "items"))
```

**Usage in test cases:**

```yaml
# Instead of exact matching:
expected:
  output:
    id: "some-uuid"               # ← Won't match generated UUIDs

# Use JSON Schema:
expected:
  output:
    type: object
    properties:
      id: {type: string}          # ← Accepts any string
      version: {type: integer, minimum: 1}
      name: {type: string}
    required: [id, version, name]
```

#### Feature 2: Timestamp Normalization

```python
def _align_datetimes(self, expected, actual):
    """
    Normalize timestamps within 5 second tolerance.

    Walks nested structures (dicts, lists) and aligns
    ISO 8601 timestamps that are within tolerance.
    """
    if isinstance(expected, dict) and isinstance(actual, dict):
        for key in set(expected.keys()).intersection(actual.keys()):
            expected[key], actual[key] = self._align_datetimes(
                expected[key], actual[key]
            )
        return expected, actual

    if isinstance(expected, str) and isinstance(actual, str):
        expected_dt = self._parse_datetime(expected)
        actual_dt = self._parse_datetime(actual)

        if expected_dt and actual_dt:
            # If within 5 seconds, treat as equal
            if abs(expected_dt - actual_dt) <= TIMESTAMP_TOLERANCE:
                return actual, actual  # ← Use actual for both (no diff)

    return expected, actual
```

**Why this matters:**

```yaml
# Test case expects:
expected:
  output:
    created_at: "2025-11-06T15:30:00Z"

# Server responds with:
actual:
  output:
    created_at: "2025-11-06T15:30:02Z"  # 2 seconds later

# Without normalization: FAIL (timestamps don't match)
# With normalization: PASS (within 5 second tolerance)
```

## Execution Flow

### Test Execution Sequence

```
1. Runner creates execution environment (Docker container)
   ↓
2. Runner starts server: python -m config_server --address 0.0.0.0 --port 8080
   ↓
3. Runner polls GET /healthz until 200 OK (max 10 seconds)
   ↓
4. Loader reads checkpoint_1/spec_cases/create_base_v1.yaml
   ↓
5. Framework sends: POST /v1/configs/base with JSON body
   ↓
6. Server processes request, stores config "base" v1
   ↓
7. Server responds: 201 Created with version info
   ↓
8. Framework captures response (status, headers, body)
   ↓
9. Verifier compares actual vs expected
   ├── Status: 201 == 201 ✓
   └── Body: {"name":"base","version":1,...} == expected ✓
   ↓
10. Score: {status_code: 0.2, output: 0.8} = 1.0
    ↓
11. Next case: create_billing_v1_including_base.yaml
    (Server state persists: "base" v1 still exists)
```

### Stateful Sequence Example

**Sequence from `spec_cases` group:**

```
Case 1: create_base_v1
  POST /v1/configs/base
  → Creates "base" v1
  → Server state: {base: [v1]}

Case 2: create_billing_v1_including_base
  POST /v1/configs/billing
  body: {includes: [{name: "base", ...}]}
  → Creates "billing" v1, includes "base" v1
  → Server state: {base: [v1], billing: [v1]}

Case 3: get_active_billing
  POST /v1/configs/billing:active
  → Returns "billing" v1 (created in case 2)
  → Depends on case 2 state

Case 4: create_billing_v2_override_pool
  POST /v1/configs/billing
  → Creates "billing" v2
  → Server state: {base: [v1], billing: [v1, v2]}

Case 5: rollback_billing_to_v1
  POST /v1/configs/billing/1:activate
  → Activates "billing" v1 again
  → Depends on both v1 and v2 existing

Case 6: get_active_billing_after_rollback
  POST /v1/configs/billing:active
  → Returns "billing" v1 (rolled back in case 5)
  → Depends on rollback working correctly
```

**Why order is critical:**
- Case 3 needs case 2's state
- Case 5 needs both case 2 and case 4's state
- Case 6 needs case 5's state
- Running out of order → 404 errors or wrong results

## Design Patterns

### Pattern 1: File-Based Test Cases

**Why:**
- API tests are simple request/response pairs
- All data fits in one YAML file
- Clear mapping to HTTP concepts

**Structure:**
```yaml
case:             # ← Maps to HTTP request
  method: POST
  path: /endpoint
  headers: {}
  body: {}

expected:         # ← Maps to HTTP response
  status_code: 200
  headers: {}
  output: {}
```

### Pattern 2: Explicit Case Ordering

**Why:**
- API tests are stateful (CRUD operations)
- Tests depend on previous requests
- Execution order determines correctness

**Implementation:**
```yaml
groups:
  spec_cases:
    case_order:           # ← Explicit list
      - create_item       # 1. Must run first
      - get_item          # 2. Depends on create
      - update_item       # 3. Depends on get
      - delete_item       # 4. Depends on update
```

### Pattern 3: JSON Schema for Flexible Validation

**Why:**
- Some values are non-deterministic (UUIDs, timestamps, auto-increment IDs)
- Exact matching would fail
- Schema validates structure and types instead

**Example:**
```yaml
# Exact matching (too strict):
expected:
  output:
    id: "123e4567-e89b-12d3-a456-426614174000"  # ← Will never match

# JSON Schema (flexible):
expected:
  output:
    type: object
    properties:
      id: {type: string, pattern: "^[0-9a-f-]{36}$"}  # ← Any valid UUID
      name: {type: string}
      created_at: {type: string, format: date-time}
    required: [id, name, created_at]
```

### Pattern 4: Timestamp Normalization

**Why:**
- Server generates timestamps at request time
- Test cases can't predict exact timestamp
- Small differences (< 5 seconds) should be ignored

**Implementation:**
```python
# In verifier
TIMESTAMP_TOLERANCE = timedelta(seconds=5)

def _align_datetimes(self, expected, actual):
    expected_dt = parse_datetime(expected)
    actual_dt = parse_datetime(actual)

    if abs(expected_dt - actual_dt) <= TIMESTAMP_TOLERANCE:
        return actual, actual  # Treat as equal
```

### Pattern 5: Separate Group Sequences

**Why:**
- Different features need different setup
- Independent test sequences don't interfere
- Easier to understand and maintain

**Example:**
```yaml
groups:
  spec_cases:               # Basic API spec
    case_order:
      - create_base_v1
      - get_base
      # ... basic CRUD

  functionality:            # Advanced features (independent state)
    case_order:
      - setup_array_base    # Different starting state
      - test_array_merge
      # ... array-specific tests

  spec_errors:              # Error cases (independent)
    case_order:
      - test_404
      - test_400
      # ... error scenarios
```

## Advanced Features

### 1. Dynamic Values in Expected Output

**Problem**: Can't predict generated values.

**Solution 1**: Use placeholder (if verifier supports):
```yaml
expected:
  output:
    id: "{{dynamic}}"           # Any value accepted
    created_at: "{{dynamic}}"
    name: "billing"             # Must match exactly
```

**Solution 2**: Use JSON Schema:
```yaml
expected:
  output:
    type: object
    properties:
      id: {type: string}        # Any string accepted
      name: {enum: ["billing"]} # Must be "billing"
```

### 2. Cross-Request State Validation

**Problem**: Later requests need to verify earlier state changes.

**Pattern**:
```yaml
# Case 1: Create item
case_order:
  - create_user_alice
    # Creates user with id: 123

  - get_user_alice
    # Verifies user exists with id: 123

  - update_user_alice
    # Updates email

  - get_user_alice_after_update
    # Verifies email was updated
```

### 3. Error Response Validation

**Pattern**:
```yaml
case:
  method: POST
  path: /v1/configs/missing:active

expected:
  status_code: 404
  output:
    error:
      code: not_found           # Machine-readable code
      message: Config pair not found  # Human message
      details: {}               # Optional details
```

**Verifier checks**:
- Correct HTTP status (404)
- Error structure matches spec
- Error code is correct

## Common Pitfalls and Solutions

### Pitfall 1: Missing `case_order`

**Problem:**
```yaml
groups:
  core:
    type: Core
    # Missing case_order!
```

**Error**: Cases run in undefined order, stateful tests fail.

**Solution**:
```yaml
groups:
  core:
    type: Core
    case_order:          # ← Required for APIs
      - create
      - read
      - update
      - delete
```

### Pitfall 2: Case Files Don't Match `case_order`

**Problem:**
```yaml
case_order:
  - create_user           # ← No create_user.yaml file!
```

**Error**: `FileNotFoundError: create_user.yaml`

**Solution**: Ensure every case in `case_order` has a matching `.yaml` file.

### Pitfall 3: Exact Timestamp Matching

**Problem:**
```yaml
expected:
  output:
    created_at: "2025-11-06T15:30:00Z"  # ← Will never match exactly
```

**Solution 1**: Implement timestamp normalization in verifier (like this problem does).

**Solution 2**: Use JSON Schema:
```yaml
expected:
  output:
    type: object
    properties:
      created_at: {type: string, format: date-time}
```

### Pitfall 4: Not Checking Server Startup

**Problem**: Server crashes on startup, tests run against nothing.

**Solution**: Always implement health endpoint:
```python
@app.get("/healthz")
def health():
    return {"ok": True}
```

Framework waits for this to return 200 before running tests.

### Pitfall 5: Ignoring Error Response Structure

**Problem:**
```python
# Server returns:
return {"message": "Not found"}, 404

# But spec requires:
{"error": {"code": "not_found", "message": "...", "details": {}}}
```

**Solution**: Follow error structure from spec exactly.

## Testing Your Problem

### 1. Run Agent

```bash
slop-code run \
  --agent configs/agents/haiku-4.5-claude-code.yaml \
  --environment configs/environments/docker-python3.12-uv.yaml \
  --problem dynamic_config_service_api
```

### 2. Evaluate Results

```bash
uv run python -m slop_code.entrypoints.cli eval \
  outputs/agent_run_dir \
  --pass-policy all-cases
```

Replace `agent_run_dir` with the actual output directory created by the run command.

### 3. Debug Individual Checkpoint

```bash
uv run python -m slop_code.entrypoints.cli eval-snapshot \
  --problem-name dynamic_config_service_api \
  --checkpoint-num 1 \
  --env-config configs/environments/docker-python3.12-uv.yaml \
  --save-dir outputs/eval_results \
  outputs/agent_run_dir/dynamic_config_service_api/checkpoint_1/snapshot
```

Replace `agent_run_dir` with the actual output directory path.

### 4. View in Dashboard

```bash
uv run python -m slop_code.visualization.app outputs/
```

## Comparison: CLI vs API

| Aspect | CLI Problem | API Problem |
|--------|-------------|-------------|
| **Test case format** | Directories with case.yaml | Single .yaml files |
| **Case ordering** | Optional (tests independent) | Required (tests stateful) |
| **Execution** | Run command, capture files | Send HTTP requests |
| **State** | Usually stateless | Usually stateful |
| **Loader complexity** | ~100 lines | ~40 lines |
| **Verifier complexity** | ~50 lines | ~150 lines (timestamp handling) |
| **Output capture** | Files in tracked_files | HTTP response body |
| **Dynamic values** | Rare | Common (IDs, timestamps) |
| **Health check** | Not needed | Required |
| **Startup** | Instant | Wait for server ready |

## Summary

**Key takeaways:**

1. **API problems use file-based cases**
   - One YAML file per test case
   - Simpler structure than CLI directories

2. **`case_order` is critical**
   - Required for stateful APIs
   - Tests depend on previous requests
   - Order determines correctness

3. **Verifier handles non-determinism**
   - JSON Schema for dynamic values
   - Timestamp normalization
   - Flexible validation

4. **Server lifecycle matters**
   - Health endpoint required
   - Startup timeout configuration
   - State persists across tests

5. **Test sequences tell a story**
   - Create → Read → Update → Delete
   - Setup → Execute → Verify → Teardown
   - Clear dependency chains

## Next Steps

- **[Simple CLI Example](simple-cli.md)** - Compare with CLI approach
- **[Test Cases Guide](../test-cases.md)** - Best practices for API tests
- **[Config Schema](../config-schema.md)** - API adapter fields
- **[Troubleshooting](../troubleshooting.md)** - Common API problems
