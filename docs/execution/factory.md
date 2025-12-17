version: 1.1
last_updated: 2025-11-09
---

# Runtime Registry

`src/slop_code/execution/runtime.py` defines the protocol that powers both the
local and Docker backends. Instead of a monolithic factory, runtimes register
themselves under a name and the session layer dispatches to the registry.

```python
from slop_code.execution import spawn_runtime, LocalEnvironmentSpec

spec = LocalEnvironmentSpec()
runtime = spawn_runtime(
    environment=spec,
    working_dir=workspace_root,
    static_assets=resolved_assets,
    ports={},
    mounts={},
    env_vars={},
)
result = runtime.execute("python main.py", env={}, stdin=None, timeout=30)
```

## SubmissionRuntime Protocol

`SubmissionRuntime` is an abstract base class that implementations must satisfy.
Key methods include:

- `stream(command, env, stdin, timeout)` – yields `RuntimeEvent` objects while
  the process or container is running.
- `execute(command, env, stdin, timeout)` – runs a command synchronously and
  returns a `RuntimeResult`.
- `poll()` / `kill()` / `cleanup()` – lifecycle management hooks called by the
  session when cleaning up resources.
- `spawn()` (classmethod) – entry point for creating runtime instances. Registered
  implementations receive the environment spec, workspace path, static assets,
  port mappings, mounts, extra env vars, and flags such as `is_evaluation` or
  `disable_setup`.

Two concrete runtimes ship with the project:

- `LocalRuntime` (`local_runtime.py`) executes commands via `subprocess.Popen`.
- `DockerRuntime` (`docker_runtime.py`) launches containers using the Docker SDK.

Both use `register_runtime("local" | "docker")` to advertise support for the
matching `EnvironmentSpec.type`.

## LaunchSpec and RuntimeResult

While most call sites work directly with keyword arguments, `LaunchSpec`,
`RuntimeResult`, and `RuntimeEvent` document the shared contract:

- `LaunchSpec` captures the working directory, environment spec, static assets,
  mounts, ports, environment variables, and optional setup command overrides.
- `RuntimeResult` reports exit code, stdout/stderr (split into setup and command
  output), elapsed time, and timeout status.
- `RuntimeEvent` mirrors `RuntimeResult` for streaming execution, including
  demultiplexed stdout/stderr chunks followed by a terminal `finished` event.

These models live alongside the runtime protocol to keep data structures close to
the code that produces them.

## Spawning Runtimes

`spawn_runtime(environment, **kwargs)` looks up the runtime class using the
spec’s `type` field and forwards keyword arguments untouched. This keeps the
registry minimal and avoids circular imports. The session module calls
`spawn_runtime()` after preparing the workspace, while tests can construct
runtimes directly for fine-grained assertions.

## Registering New Implementations

To add another backend (remote execution, Kubernetes jobs, etc.):

1. Implement a `SubmissionRuntime` subclass with the required lifecycle methods.
2. Expose a matching `EnvironmentSpec` (see [`environment_specs.md`](environment_specs.md)).
3. Decorate the class with `@register_runtime("<type>")`.
4. Update documentation and tests to cover setup commands, cleanup guarantees,
   and any environment-specific behavior.

The registry approach keeps dispatch logic declarative while allowing new
runtimes to ship in isolation from the session layer.
