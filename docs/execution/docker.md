version: 1.1
last_updated: 2025-11-09
---

# Docker Runtime

`src/slop_code/execution/docker_runtime/runtime.py` implements the container-based
`SubmissionRuntime`. It isolates submissions inside Docker while keeping the API
aligned with the local runtime.

## Lifecycle

- `DockerRuntime.spawn()` receives a prepared workspace directory, resolved static
  assets, and runtime overrides from the session.
- Setup commands are rendered into a temporary entry script (`HANDLE_ENTRY.sh`)
  that runs before the requested command. Sessions can disable setup execution
  by passing `disable_setup=True` when spawning the runtime, which bypasses all
  setup commands and the split marker.
- The runtime creates a Docker client and keeps track of the active container so
  later calls to `poll()`, `kill()`, or `cleanup()` behave consistently.

### Disabling Setup

For scenarios where setup has already run (e.g., resuming from snapshot):

```python
runtime = session.spawn(disable_setup=True)
result = runtime.execute("python main.py")
# result.setup_stdout and result.setup_stderr will be empty
```

## Volume and Asset Handling

Volume mounts merge three sources:

1. The workspace directory (unless `mount_workspace=False` on the spec).
2. Static assets, mounted read-only under `/static/<save_path>`.
3. Spec-defined `extra_mounts` plus any mounts provided at spawn time.

Relative host paths are resolved against the workspace root, so tests can supply
fixtures without precomputing absolute paths.

## Volume Merging Order

The `_build_volumes()` method constructs volume mappings by merging four sources
in priority order:

1. **Workspace mount** (if `mount_workspace=True`):
   - Host: `{session.workspace.working_dir}`
   - Container: `{docker.workdir}`
   - Mode: Read-write

2. **Spec mounts** (`docker.extra_mounts`):
   - Validated to ensure no subdirectory of `workdir`
   - Can be string (path) or dict (with mode)

3. **Runtime mounts** (provided at `spawn()`):
   - Merged from `mounts` kwarg
   - Same validation as spec mounts

4. **Static assets**:
   - Mounted read-only to `/static/{asset.save_path}`
   - One mount per asset

**Conflict Resolution:**
- Later sources override earlier ones for same container path
- Workspace mount takes lowest priority
- Runtime mounts take highest priority (except assets)

**Example:**
```python
# Spec has:
extra_mounts = {"/host/config": "/workspace/config"}

# Runtime overrides:
runtime = session.spawn(mounts={"/host/config2": "/workspace/config"})
# Result: /host/config2 mounted to /workspace/config
```

## Command Execution

- `execute()` uses the long-lived container created by `spawn()` and starts a
  `docker exec` process with the command. It optionally passes stdin, waits for
  completion with timeout support, and returns a `RuntimeResult`.

  Output is automatically split into `setup_*` and command segments using a
  `SPLIT_STRING` marker emitted by the entry script (unless `disable_setup=True`
  was used at spawn time).

  The container persists across multiple `execute()` calls until `cleanup()` is
  called.
- `stream()` raises `ValueError` if stdin is provided (stdin not supported for
  streaming execution). It starts a `docker exec` process, reads from stdout/
  stderr pipes using threaded readers, and feeds chunks into `process_stream()`,
  yielding `RuntimeEvent` objects suitable for adapters that need live output.

  Unlike `execute()`, streaming mode does NOT split setup vs command output - the
  split marker is still emitted but not parsed during streaming.
- `poll()` checks the active `docker exec` process status via `_process.poll()`.
  If no process is active (never started or already finished), it returns the
  cached `_exit_code` from the last execution. Returns `None` if still running,
  or the exit code if finished.

## Networking

`DockerEnvironmentSpec` exposes helpers used during spawn:

- `effective_network_mode()` ensures host networking is only requested on Linux.
- `get_effective_address()` rewrites loopback bind addresses to `0.0.0.0` when
  running in bridge mode so port mappings remain accessible.
- Session-provided port maps are ignored when using host networking; otherwise,
  the runtime merges spec defaults with call-site overrides.

## Platform Differences

### Network Mode

- **Linux:** Both `bridge` and `host` modes supported
- **macOS/Windows:** Only `bridge` mode supported
  - Docker Desktop doesn't support `--network host`
  - `effective_network_mode()` auto-converts `host` → `bridge` on non-Linux

### Address Rewriting

When using bridge networking:
- Loopback addresses (`127.0.0.1`, `localhost`) are rewritten to `0.0.0.0`
- Binds to all interfaces so port mappings remain accessible from host
- `get_effective_address()` handles this automatically

### User Mapping

- **HUID/HGID environment variables:** Host UID/GID passed to container
- **Evaluation context:** Uses host UID to match permissions
- **Agent context:** May use different user for isolation
- Helpers: `get_eval_user()` vs `get_actual_user()`

## Docker Configuration

`DockerConfig` in `src/slop_code/execution/docker_runtime/models.py` provides
Docker-specific settings:

### Core Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `image` | str | Required | Container image for execution |
| `binary` | str | `"docker"` | Docker CLI binary path |
| `workdir` | str | `"/workspace"` | Container working directory |
| `mount_workspace` | bool | `True` | Mount session workspace into container |
| `extra_mounts` | dict | `{}` | Additional volume mounts |
| `network` | str \| None | `None` | Docker network mode (reconciled by platform) |
| `user` | str \| None | `None` | User specification (e.g., "1000:1000") |

### Helper Methods

- `get_base_image()` → Returns `"slop-code:{env_name}"`
- `get_eval_user()` → User for evaluation context (respects HUID/HGID)
- `get_actual_user()` → User for agent context
- `effective_network_mode()` → Platform-aware network mode (host only on Linux)
- `get_effective_address(addr)` → Rewrites loopback for bridge mode

### Example

```yaml
# configs/environments/docker-python3.12.yaml
type: docker
docker:
  image: python:3.12-slim
  workdir: /workspace
  mount_workspace: true
  network: bridge  # Auto-adjusts to "host" on Linux if specified
  extra_mounts:
    /host/data: /container/data:ro
```

## Cleanup and Debugging

- `kill()` stops and removes the container.

  **Note:** The `DockerConfig.keep_container_after_clean` field exists in the
  configuration spec but is not currently implemented in the cleanup logic. All
  containers are removed on `kill()` or `cleanup()` regardless of this setting.
- `cleanup()` performs full teardown:

  1. Calls `kill()` to stop and remove the container
  2. Closes the Docker client (`_client.close()`)
  3. Sets `_client = None` to prevent reuse
  4. Clears container ID and process references

  This prevents resource leaks during repeated session usage. After `cleanup()`,
  the runtime instance cannot be reused - a new `spawn()` is required.
- All Docker SDK errors are converted into `SolutionRuntimeError`, allowing
  adapters to surface precise diagnostics without handling SDK types directly.

## When to Use

- Running untrusted submissions that require process isolation.
- Enforcing consistent Linux toolchains across contributors.
- Evaluation scenarios that depend on Docker-specific networking or mount
  semantics.

Ensure the Docker daemon is available before selecting this backend; otherwise
`spawn_runtime()` will raise when the runtime attempts to create the client.