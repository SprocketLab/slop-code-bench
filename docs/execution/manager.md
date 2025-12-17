version: 1.1
last_updated: 2025-11-09
---

# Session Lifecycle

`src/slop_code/execution/session.py` replaces the earlier execution manager
hierarchy with a lightweight orchestration class. A `Session` ties together:

- A `Workspace`, which prepares an isolated directory, restores snapshots, and
  exposes helpers for reading tracked files.
- Resolved static assets, including placeholder substitution for case payloads.
- One or more `SubmissionRuntime` instances spawned on demand.

Sessions are context managers so evaluation adapters can prepare and tear down
resources with a `with` block.

```python
from pathlib import Path
from slop_code.execution import Session, LocalEnvironmentSpec

spec = LocalEnvironmentSpec()
session = Session.from_environment_spec(spec, base_dir=Path("/problem"), static_assets=None)

with session as active:
    runtime = active.spawn()
    result = runtime.execute("python main.py", env={}, stdin=None, timeout=30)
```

## Core Workflow

1. **Construction** – Callers provide an `EnvironmentSpec`, a `Workspace`, and
   optional static assets. Helper constructor `Session.from_environment_spec`
   builds a workspace snapshot function that respects spec filters and assets.
2. **Preparation** – Entering the context calls `workspace.prepare()`, which
   materializes the initial snapshot and (for agent inference) copies static
   assets into place.
3. **Runtime Spawn** – `session.spawn()` delegates to the runtime registry via
   `spawn_runtime()`. The runtime shares the workspace root and receives any
   additional mounts, ports, env vars, or setup commands requested by adapters.
4. **File Materialization** – Request payloads are written with
   `session.materialize_input_files()`, which uses the unified file operations
   API to pick the correct handler based on file signatures.
5. **Execution & Streaming** – The returned `SubmissionRuntime` handles process
   execution (see [`local.md`](local.md) and [`docker.md`](docker.md)).
6. **Reading Results** – `session.get_file_contents()` applies glob patterns to
   the workspace so adapters can retrieve tracked files after a run.
7. **Checkpoint Completion** – Agent inference flows call `finish_checkpoint()` to
   update the workspace snapshot, export the archive, and compute a `SnapshotDiff`.
8. **Cleanup** – Leaving the context calls `runtime.cleanup()` on every spawned
   runtime and disposes of the workspace directory.

## Static Assets and Placeholders

Sessions keep a reference to the resolved static asset map. Two helpers make use
of it:

- `session.resolve_static_placeholders(data)` rewrites `{{static:name}}`
  placeholders so case fixtures can refer to assets using environment-appropriate
  paths (`/static/...` in Docker, absolute host paths locally).
- The workspace materializes assets when running in agent inference mode,
  copying directories or files into the temporary working directory.

## Agent vs Evaluation Sessions

The `is_agent_infer` flag changes a few behaviors:

- Evaluation sessions leave static assets on the host (or mounted read-only into
  containers) and skip workspace asset copies.
- Agent inference sessions allow `finish_checkpoint()` so runners can persist the
  resulting workspace and compute diffs for reporting.
- Runtime spawn calls mark `is_evaluation=not is_agent_infer`, influencing setup
  command ordering and Docker user selection.

## Logging Hooks

Every operation logs via `structlog`. Enable verbose logging in CLIs or tests to
trace workspace preparation, runtime spawn parameters, and file access patterns.

Understanding the session lifecycle clarifies how adapters interact with the
execution layer and where to introduce new instrumentation or backend features.
