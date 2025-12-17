version: 1.1
last_updated: 2025-05-26
---
# Evaluation Adapters

Adapters define how a submission is executed and what “result” is captured for verification. This package includes three adapters:

- CLI: Run a Python entry file per case.
- API: Start a server once per group and issue HTTP requests per case.
- Playwright: Launch an HTTP server and drive a headless browser per group.

All adapters produce a `CaseResult` (see below) and accept an `AdapterConfig` discriminated by `type`.

## Common Concepts

- Working Directory: Each adapter runs in a temporary working directory populated with:
  - Submission files matched by `submission_patterns`.
  - Group-scoped files (`group_files`).
  - Per-case files (`case.files`).
- Entry File: The Problem-level `entry_file` is required for all adapters and is resolved within the working directory.
- Executable: The Python interpreter or binary used to run the entry. Resolved by the runner (e.g., `python` inside the submission env) but can be overridden via the execution provider.
- Timeouts: Case-level `timeout_s` overrides the adapter/runner default.
- Tracked Files: Paths to read back after a run into `CaseResult.files`.
  - CLI: collected as text.
  - API: collected as bytes (use normalizers if you need to decode).
  - Playwright: collected as bytes for artifacts (screenshots, traces, video).
- Setup/Teardown Scripts: `setup_script` and `teardown_script` exist on the base config and are materialized into the working set. They are reserved for adapters that choose to run them.
- Copy Directories: The runner can instruct adapters to mirror directories (for example a virtual environment) into each working directory via `copy_dirs`. Adapters call `copy_dirs(...)` during setup; it is not user-configurable but is useful when debugging evaluation issues.
- Execution Providers: `AdapterConfig.execution` overrides the checkpoint/group execution provider. The default is `ProcessExecutionConfig`, but you can point adapters at remote or sandboxed providers without changing the global runner settings.

`CaseResult` fields

```yaml
type: cli | api
status_code: int
output: str | bytes | null
stderr: str | bytes | null
files: dict[str, str | bytes]
elapsed: float
timed_out: bool
path: str
adapter_error: bool
```

Cases extend `BaseCase`, which provides `id`, `arguments`, `files`, `tracked_files`, and optional `timeout_s`. Each adapter narrows the shape of `expected` by returning a typed `CaseResult` subclass.

Base adapter config (shared fields):

```yaml
entry_file: path/to/entry.py # Where in the submission to find it.
adapter:
  type: cli | api
  execution: # optional execution provider override
    type: process
    shell: true
  setup_script: path/to/setup.sh      # optional
  teardown_script: path/to/teardown.sh # optional
  tracked_files: []                   # optional; collects run outputs (supports globs)
```

## CLI Adapter

Runs a Python entry file for each case in a fresh temp directory.

- Command: `python <entry_file> <case.arguments...>`
- StdIO: `case.stdin` is piped to the process when present.
- Files: `initial_files` (submission + group) and `case.files` are materialized before execution.
- Collection: `tracked_files ∪ case.tracked_files` (paths or glob patterns) are read back as text.
- Execution Provider: Defaults to the checkpoint/group setting; override with `adapter.execution` to run commands through a different provider (e.g. containerized process runner).
- Directory Mirroring: Any `copy_dirs` passed by the runner (typically a virtual environment) is copied into the session working directory before execution.

Config:

```yaml
entry_file: main.py
adapter:
  type: cli
  tracked_files:
    - outputs/report.txt
```

Case fields (CLICase):

- id: stable identifier.
- arguments: list of strings passed positionally.
- stdin: optional string piped to the process.
- files: per-case files to write before running.
- tracked_files: additional files to collect for this case.
- timeout_s: optional per-case timeout.
- expected: structure to verify against (e.g., `output`, `status_code`, `files[...]`).

## API Adapter

Starts the provided entry file as an HTTP server once per group, waits for readiness (optional health path), then executes each case by issuing an HTTP request.

- Server command: `python <entry_file> --address <addr> --port <port>`
- Readiness: polls `http://<addr>:<port><health_path or '/'>` until success or timeout.
- Request per case: `method`, `path`, `headers`, `query`/`arguments`, optional `body`; supports retries for transient failures.
- Collection: `tracked_files ∪ case.tracked_files` (paths or glob patterns) are read after the request as bytes.
- Execution Provider: The adapter always requires an execution provider (either inherited or provided via `adapter.execution`) to spawn and supervise the server process.
- Directory Mirroring: Any directories requested by the runner are copied into the server working directory before startup.

Config (APIAdapterConfig):

```yaml
entry_file: server.py
adapter:
  type: api
  address: 127.0.0.1
  port: 8000            # optional; if omitted, a free port is chosen
  health_path: /health  # optional; GET path for readiness
  startup_timeout_s: 20 # wait time for server to become ready
  tracked_files: []
```

Case fields (APICase):

- id: stable identifier.
- method: HTTP method (default: GET).
- path: request path appended to the base URL.
- headers: optional string-to-string headers.
- query: key/value query parameters; alternatively use `arguments: ['k=v', ...]` (mutually exclusive with `query`).
- body: optional string or JSON-serializable object (dict/list → JSON; string sent as-is).
- retries: number of extra attempts on connect/timeout errors.
- tracked_files: extra files to collect for this case.
- timeout_s: per-case request timeout.
- expected: fields to verify (e.g., `status_code`, `output`, `headers`, `files.{...}`).

## Playwright Adapter

Extends the API adapter by launching a headless Chromium browser and running scripted interactions against the served application.

- Server lifecycle: identical to the API adapter; the Playwright adapter inherits all HTTP server configuration knobs.
- Browser lifecycle: headless Chromium (channel configurable) starts once per group. Set `reset_context` on a case to discard the previous browser context before executing its steps.
- Steps: Each case provides an ordered list of Playwright actions (`navigate`, `click`, `fill`, `upload_file`, `press`, `capture_relative_position`, `capture_count`). Actions can extract intermediate values for later verification or storage.
- Artifacts: `screenshot`, `trace`, and `video` policies control whether artifacts are disabled, kept on failure, or always retained. Collected artifacts surface under `CaseResult.files`.
- Result shape: `PlaywrightResult` includes the final page URL/title and a flat mapping of step outputs. Normalizers can reshape these payloads for downstream verifiers.

Config (PlaywrightAdapterConfig):

```yaml
entry_file: app/server.py
adapter:
  type: playwright
  address: 127.0.0.1
  browser_channel: chrome
  start_page: /login
  screenshot: retain-on-failure
  trace: off
  video: off
```

Case fields (PlaywrightCase):

- id: stable identifier.
- steps: list of action dictionaries, each with a `type`, `alias`, and `target`.
- reset_context: boolean indicating whether to discard and recreate the browser context before running the steps.
- expected: fields to verify (often nested under `output`).
- tracked_files/timeout_s: same semantics as other adapters.

## Choosing an Adapter in a Checkpoint

Adapters are selected in `checkpoint/config.yaml` via the discriminated union on `type`:

```yaml
adapter:
  type: cli | api | playwright
  # ... adapter-specific fields ...
```

The runner composes the working set from `submission_patterns` and `group_files`, enters the adapter context (starting servers when applicable), then for each case creates a case session, runs it, normalizes results, and applies verifiers.

## Notes and Tips

- File collection: CLI returns text; API and Playwright return bytes. Use normalizers like `load_json(files.{path})` or `decode(files.{path}, 'utf-8')` as needed.
- `retries` only applies to API/Playwright transport errors (connect/read timeouts). Non-2xx HTTP statuses still produce a normal result and are verified by verifiers.
- If an entry file or executable is missing, adapters surface an adapter error or raise `AdapterError` during setup.
- `CaseResult.adapter_error` differentiates infrastructure failures (e.g., missing entry file) from user failures (e.g., wrong exit code). Verifiers commonly treat adapter failures as immediate case failures.
- For long-running servers, check `startup_timeout_s` and `health_path` to avoid hanging the evaluator when the service never comes up.
