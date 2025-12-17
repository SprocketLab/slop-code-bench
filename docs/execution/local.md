version: 1.1
last_updated: 2025-11-09
---

# Local Runtime

`src/slop_code/execution/local_runtime.py` implements a host-based
`SubmissionRuntime`. It is the fastest option for trusted code paths and mirrors
exactly what would happen if the user executed the command directly on their
machine.

## Lifecycle

- The session passes a prepared workspace directory, resolved static assets, and
  optional setup command overrides when calling `LocalRuntime.spawn()`.
- Setup commands defined on the `LocalEnvironmentSpec` run immediately before the
  runtime is handed back to the caller. This keeps behaviour consistent with the
  Docker backend.
- Each runtime instance owns a single `subprocess.Popen`. New commands wait for
  the previous process to exit (or are forced to exit) before reusing the runtime.

## Executing Commands

`LocalRuntime` exposes the full `SubmissionRuntime` interface:

- `execute()` starts a process with optional stdin, waits for completion (respecting
  the timeout), and returns a `RuntimeResult` populated with stdout/stderr.
- `stream()` demultiplexes stdout/stderr using `selectors.DefaultSelector` and
  yields `RuntimeEvent` objects. Stdin is not supported in streaming mode; adapters
  should fallback to `execute()` if interactive input is required.
- `poll()` delegates to `Popen.poll()` so sessions can check liveness without
  blocking.
- `kill()` and `cleanup()` terminate lingering processes when sessions exit.

All commands honour environment variables from `LocalEnvironmentSpec.get_full_env()`
and execute relative to the workspace directory managed by the session.

## Timeouts and Error Handling

- If a timeout is provided to `execute()`, the process is killed and the result
  is marked `timed_out=True`.
- `SolutionRuntimeError` is raised when callers attempt to access the underlying
  process before it exists or after it has been cleaned up.
- Streams are consumed in text mode (`encoding="utf-8", errors="replace"`) to
  avoid crashes on malformed output while keeping behaviour deterministic.

## When to Use

- Rapid iteration during development or CI when container overhead is unnecessary.
- Debugging evaluation failures locally with full insight into the workspace.
- Scenarios where Docker is unavailable but snapshotting and static asset support
  are still required.

Because this backend runs processes with host privileges, only use it for trusted
submissions or within controlled environments.