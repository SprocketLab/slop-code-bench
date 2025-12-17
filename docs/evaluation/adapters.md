---
version: 1.3
last_updated: 2025-12-10
---

# Adapters Guide

Adapters provide different execution environments for running submissions. This guide covers when to use each adapter type, their configuration, and how they differ.

## Adapter Types Overview

| Adapter | Use Case | Input Format | Output Capture |
|---------|----------|--------------|----------------|
| **CLI** | Command-line tools | Args, stdin, files | stdout, stderr, exit code |
| **API** | HTTP APIs, web services | HTTP requests | Response body, status, headers |
| **Playwright** | Web applications, browsers | Browser interactions | DOM state, screenshots, network |

## Discriminated Union Configuration

The adapter system uses a discriminated union pattern where you specify the `type` field to select the adapter configuration:

```yaml
# CLI Adapter - simplest configuration
adapter:
  type: cli

# API Adapter - with server-specific settings
adapter:
  type: api
  address: http://localhost:8000
  health_path: /health
  startup_timeout_s: 30

# Playwright Adapter - extends API with browser settings
adapter:
  type: playwright
  address: http://localhost:3000
  browser: chromium
  headless: true
```

The `type` field acts as a discriminator that determines which configuration schema to validate against.

## Choosing an Adapter

### Use CLI Adapter when:
- ✅ Submission is a command-line tool
- ✅ Interaction is through stdin/stdout/local files
- ✅ Testing file processing or system utilities
- ✅ Simple input/output verification

**Examples**: Data processing scripts, CLI calculators, file converters

### Use API Adapter when:
- ✅ Submission is an HTTP API server
- ✅ Testing REST/GraphQL endpoints
- ✅ Need to mock external API dependencies
- ✅ Testing request/response validation

**Examples**: Web APIs, microservices, HTTP endpoints

### Use Playwright Adapter when:
- ✅ Submission is a web application
- ✅ Testing browser interactions
- ✅ Need to verify UI elements
- ✅ Testing complex user workflows

**Examples**: Web UIs, single-page applications, browser automation

## CLI Adapter

### Overview

Executes submissions as command-line processes, capturing stdout, stderr, and exit codes.

### Configuration

```yaml
# checkpoint/config.yaml
adapter:
  type: cli  # Simple discriminated union - just specify the type
```

### Case Structure

```yaml
# Test case definition
name: process_data
description: Process CSV data

arguments: ["--input", "data.csv", "--output", "result.json"]  # Command arguments
stdin: "optional input data"                                  # Optional: stdin input

expected:
  output: "Processing complete\n"    # Expected stdout
  status_code: 0                     # Expected exit code
  files:                             # Optional: expected file outputs
    - path: /app/result.json
      content: '{"result": "success"}'
```

### BaseCase Structure

All adapters receive cases that extend `BaseCase`:

```python
class BaseCase(BaseModel):
    id: str                           # Stable identifier for the case
    group: str                        # Group this case belongs to
    group_type: GroupType             # Type of group (Core, Functionality, etc.)
    checkpoint: str                   # Checkpoint name
    order: int = -1                   # Execution order within group
    arguments: list[str] = []         # Command arguments (CLI adapter)
    timeout_s: float | None = None    # Optional per-case timeout override
    input_files: list[InputFile] = [] # Files to write before execution
    tracked_files: list[str] = []     # File paths/globs to collect after execution
    reset: bool = False               # Reset workspace before this case
    original_group: str | None = None         # For regression cases
    original_checkpoint: str | None = None    # For regression cases
```

### CaseResult Structure

```python
class CaseResult(BaseModel):
    id: str                           # Case identifier
    group: str                        # Group name
    group_type: GroupType             # Group type enum
    type: str = "base"                # Adapter type identifier
    elapsed: float = 0                # Execution duration in seconds
    status_code: int = 0              # Process exit code or HTTP status
    resource_path: str | None = None  # Adapter-specific path (CLI entry, URL)
    adapter_error: bool = False       # True if adapter encountered an error
    output: JsonValue = None          # Primary output (stdout or HTTP body)
    stderr: JsonValue = None          # Stderr output (if captured)
    timed_out: bool = False           # True if execution exceeded timeout
    files: dict[str, JsonValue] = {}  # Collected file contents
```

### Examples

#### Example 1: Simple CLI Tool

```yaml
# Checkpoint config
adapter:
  type: cli

# Case
name: calculator_add
arguments: ["add", "5", "3"]
expected:
  output: "8\n"
  status_code: 0
```

#### Example 2: File Processing

```yaml
name: csv_processor
arguments: ["--input", "/app/data/input.csv", "--format", "json"]
expected:
  status_code: 0
  files:
    - path: /app/output/result.json
      # File content verified by custom verifier
```

#### Example 3: Stdin Input

```yaml
name: text_processor
stdin: "Hello World\n"
arguments: ["--uppercase"]
expected:
  output: "HELLO WORLD\n"
  status_code: 0
```

### Timeout Behavior

- Execution is terminated if it exceeds the timeout
- `CaseResult.error` will contain timeout information
- Process is forcefully killed (SIGKILL) after grace period

### Common Patterns

**Pattern 1: Multi-step Processing**
```yaml
input:
  args: ["--step1", "--step2", "--step3"]
```

**Pattern 2: Configuration Files**
```yaml
# Use static assets to provide config
# problem/config.yaml
static_assets:
  - source: test_config.json
    destination: /app/config.json

# case
arguments: ["--config", "/app/config.json"]
```

## API Adapter

### Overview

Runs submissions as HTTP API servers and sends requests to test endpoints.

### Configuration

```yaml
# checkpoint/config.yaml
adapter:
  type: api
  address: http://localhost:8000  # Base URL for the API
  port: 8000                      # Optional: port (defaults to 8000)
  health_path: /health            # Optional: health check endpoint
  startup_timeout_s: 30           # Optional: time to wait for server startup (default: 10)
  max_startup_attempts: 5         # Optional: max startup attempts (default: 5)
  delay_startup_attempts: 5       # Optional: delay between attempts (default: 5)
```

### Case Structure

```yaml
name: get_user
description: Test GET /users/:id endpoint

method: GET                        # HTTP method
path: /users/123                   # Request path
headers:                           # Optional: request headers
  Authorization: Bearer test_token
query:                             # Optional: query parameters
  include: profile
body: null                         # Optional: request body

expected:
  status_code: 200
  output: '{"id": 123, "name": "Test User"}'  # Expected response body
```

### CaseResult Structure

The API adapter returns the same `CaseResult` structure as CLI:

```python
class CaseResult(BaseModel):
    id: str                           # Case identifier
    group: str                        # Group name
    group_type: GroupType             # Group type enum
    type: str = "api"                 # Adapter type identifier
    elapsed: float = 0                # Request duration in seconds
    status_code: int = 0              # HTTP status code
    resource_path: str | None = None  # Full request URL
    adapter_error: bool = False       # True if request failed
    output: JsonValue = None          # Response body
    stderr: JsonValue = None          # Error details (if any)
    timed_out: bool = False           # True if request timed out
    files: dict[str, JsonValue] = {}  # Collected files (if tracked)
```

### Examples

#### Example 1: REST API

```yaml
adapter:
  type: api
  address: http://localhost:8000
  health_path: /health
  startup_timeout_s: 20

groups:
  - name: user_endpoints
```

```yaml
# Case: Create user
name: create_user
method: POST
path: /users
headers:
  Content-Type: application/json
body: '{"name": "Alice", "email": "alice@example.com"}'
expected:
  status_code: 201
  # Verifier checks response structure
```

#### Example 2: Basic Health Check

```yaml
adapter:
  type: api
  address: http://localhost:8080
  health_path: /api/health
  startup_timeout_s: 15
```

```yaml
# Case tests health endpoint
name: health_check
method: GET
path: /api/health
expected:
  status_code: 200
  output: '{"status": "healthy"}'
```

#### Example 3: Query Parameters

```yaml
name: search_items
method: GET
path: /items
query:
  q: laptop
  min_price: 500
  max_price: 1000
expected:
  status_code: 200
  # Body verified by custom verifier
```

### Startup and Health Checks

The API adapter:
1. Starts the submission server
2. Waits for health check to pass (if configured)
3. Runs test cases
4. Shuts down the server

```yaml
adapter:
  type: api
  startup_timeout: 30
  health_check:
    path: /health       # Endpoint to check
    timeout: 10         # Max time to wait for healthy
    interval: 1         # Check every N seconds
    expected_status: 200  # Optional: expected status code
```

### Mock Servers

Mock external APIs that your submission depends on:

```yaml
mock_servers:
  - name: weather_api
    port: 9002
    routes:
      - path: /current
        method: GET
        response:
          status: 200
          body: '{"temp": 72, "condition": "sunny"}'
          headers:
            Content-Type: application/json

      - path: /forecast
        method: GET
        response:
          status: 200
          body: '{"forecast": [...]}'
```

Your submission can then call `http://localhost:9002/current`.

## Playwright Adapter

### Overview

Runs submissions as web applications and tests them through browser automation.

### Configuration

```yaml
# checkpoint/config.yaml
adapter:
  type: playwright
  timeout: 60
  browser: chromium        # Optional: chromium, firefox, webkit (default: chromium)
  headless: true          # Optional: run headless (default: true)
  viewport:               # Optional: viewport size
    width: 1280
    height: 720
  base_url: http://localhost:3000  # Optional: override base URL
  startup_timeout: 30     # Optional: wait for app to start
  record_video: false     # Optional: record test execution
  screenshot_on_failure: true  # Optional: capture screenshot on failure
```

### Case Structure

```yaml
name: login_flow
description: Test user login

input:
  actions:                         # Browser actions to perform
    - type: goto
      url: /login

    - type: fill
      selector: 'input[name="username"]'
      value: testuser

    - type: fill
      selector: 'input[name="password"]'
      value: password123

    - type: click
      selector: 'button[type="submit"]'

    - type: wait
      selector: '.dashboard'       # Wait for element to appear

  wait_for_load: true             # Optional: wait for page load

expected:
  url: /dashboard                  # Expected final URL
  title: Dashboard                 # Expected page title
  elements:                        # Expected elements
    - selector: '.welcome-message'
      text: Welcome, testuser
    - selector: '.logout-button'
      visible: true
```

### CaseResult Structure

The Playwright adapter extends the API adapter result with browser-specific data:

```python
class CaseResult(BaseModel):
    id: str                           # Case identifier
    group: str                        # Group name
    group_type: GroupType             # Group type enum
    type: str = "playwright"          # Adapter type identifier
    elapsed: float = 0                # Total execution time in seconds
    status_code: int = 0              # Final HTTP status (200 = success)
    resource_path: str | None = None  # Final page URL
    adapter_error: bool = False       # True if browser actions failed
    output: JsonValue = None          # Page content or extracted data
    stderr: JsonValue = None          # Error details or console logs
    timed_out: bool = False           # True if execution timed out
    files: dict[str, JsonValue] = {}  # Screenshots, collected files
```

### Examples

#### Example 1: Form Submission

```yaml
adapter:
  type: playwright
  browser: chromium
  headless: true

# Case
name: contact_form
input:
  actions:
    - type: goto
      url: /contact

    - type: fill
      selector: '#name'
      value: John Doe

    - type: fill
      selector: '#email'
      value: john@example.com

    - type: fill
      selector: '#message'
      value: Test message

    - type: click
      selector: 'button[type="submit"]'

    - type: wait
      selector: '.success-message'
      timeout: 5000

expected:
  elements:
    - selector: '.success-message'
      text: Message sent successfully
```

#### Example 2: Navigation Test

```yaml
name: navigation
input:
  actions:
    - type: goto
      url: /

    - type: click
      selector: 'a[href="/about"]'

    - type: wait
      url: /about

expected:
  url: /about
  title: About Us
```

#### Example 3: JavaScript Interaction

```yaml
name: interactive_widget
input:
  actions:
    - type: goto
      url: /calculator

    - type: evaluate
      script: |
        document.querySelector('#num1').value = '5';
        document.querySelector('#num2').value = '3';
        document.querySelector('#add').click();

    - type: wait
      selector: '#result'

expected:
  elements:
    - selector: '#result'
      text: '8'
```

### Action Types

| Action | Description | Parameters |
|--------|-------------|------------|
| `goto` | Navigate to URL | `url` |
| `click` | Click element | `selector` |
| `fill` | Fill input field | `selector`, `value` |
| `type` | Type text (with delay) | `selector`, `value`, `delay` (optional) |
| `select` | Select dropdown option | `selector`, `value` |
| `wait` | Wait for element | `selector`, `timeout` (optional) |
| `wait_for_url` | Wait for URL | `url`, `timeout` (optional) |
| `evaluate` | Run JavaScript | `script` |
| `screenshot` | Take screenshot | `path` (optional) |
| `hover` | Hover over element | `selector` |
| `press` | Press keyboard key | `selector`, `key` |

### Video Recording

Capture video of test execution:

```yaml
adapter:
  type: playwright
  record_video: true
  video_dir: /app/test_videos  # Where to save videos
```

Videos are saved per test case for debugging.

### Screenshot on Failure

Automatically capture screenshots when tests fail:

```yaml
adapter:
  type: playwright
  screenshot_on_failure: true
  screenshot_dir: /app/screenshots
```

## Cross-Adapter Concepts

### Timeouts

All adapters support timeouts at multiple levels:

```yaml
# Global (problem config)
timeout: 120

# Checkpoint level
adapter:
  timeout: 60

# Group level
groups:
  - name: slow_tests
    timeout: 300
```

**Timeout hierarchy**: Group > Checkpoint > Problem (most specific wins)

### Error Handling

All adapters set `CaseResult.adapter_error` when execution fails:

```python
if case_result.adapter_error:
    print(f"Execution failed: {case_result.stderr}")

if case_result.timed_out:
    print(f"Execution timed out after {case_result.elapsed}s")
```

Common error conditions:
- **Timeout**: `timed_out=True` when execution exceeded timeout
- **Startup failure**: `adapter_error=True` if server/app failed to start
- **Execution error**: Non-zero `status_code` or `adapter_error=True`
- **Network error**: `adapter_error=True` for connection failures (API/Playwright)

### Context Management

All adapters use context managers for proper cleanup:

```python
with adapter:
    result = adapter.run_case(case)
# Automatic cleanup: processes killed, servers stopped, browsers closed
```

## Performance Considerations

### CLI Adapter
- **Fast**: Direct process execution
- **Scalable**: Can run many in parallel
- **Lightweight**: Minimal overhead

### API Adapter
- **Moderate**: Server startup adds overhead
- **Reusable**: Server stays running across cases
- **Network overhead**: HTTP request/response latency

### Playwright Adapter
- **Slow**: Browser startup is expensive
- **Resource-intensive**: Uses significant CPU/memory
- **Limited parallelism**: Browsers are heavy

**Tip**: Use CLI for large test suites, Playwright only when necessary.

## Adapter-Specific Troubleshooting

### CLI Adapter

**Problem**: Process times out
```yaml
# Increase timeout
adapter:
  timeout: 120
```

**Problem**: Stderr pollutes output
```yaml
# Separate stderr
adapter:
  capture_stderr: false
```

### API Adapter

**Problem**: Server doesn't start
```yaml
# Increase startup timeout and add health check
adapter:
  startup_timeout: 60
  health_check:
    path: /health
    timeout: 30
```

**Problem**: Port already in use
```yaml
# Configure different port in submission startup
```

### Playwright Adapter

**Problem**: Elements not found
```yaml
# Increase wait timeout
- type: wait
  selector: '.slow-loading-element'
  timeout: 10000  # 10 seconds
```

**Problem**: Flaky tests
```yaml
# Enable video recording to debug
adapter:
  record_video: true
  screenshot_on_failure: true
```

**Problem**: Browser crashes
```yaml
# Try different browser
adapter:
  browser: firefox  # or webkit
```

## Next Steps

- **Implement verification**: [Verification Guide](verification.md)
- **Set up case loading**: [Loaders Guide](loaders.md)
- **Understand results**: [Reporting Guide](reporting.md)
- **Debug issues**: [Troubleshooting Guide](troubleshooting.md)
