version: 1.2
last_updated: 2025-11-18
---

# Environment Specs

Environment specifications describe how runtimes prepare processes, materialise
files, and capture results. The shared base class lives in
`src/slop_code/execution/models.py`; individual backends extend it with extra
fields while retaining a common surface for sessions, workspaces, and runtimes.

All specs are Pydantic models so they can be loaded directly from problem YAML,
CLI overrides, or tests.

## Shared Models (`EnvironmentSpec`)

`EnvironmentSpec` captures behaviour that every backend supports:

- `type` – discriminator used by `spawn_runtime()` to pick a registered runtime.
- `environment: EnvironmentConfig` – structured environment variable handling.
- `setup: SetupConfig` – shell commands that run before the submission command.
- `commands: CommandConfig` – how the entry file is formatted and which command
  agents/evaluators should invoke.
- `snapshot: SnapshotConfig` – filters and storage policy for workspace archives.

Key helpers centralise the implementation for runtimes and adapters:

- `get_full_env()` merges OS variables (when `include_os_env=True`) with the
  spec’s explicit `env` mapping and any call-site overrides.
- `get_setup_commands(is_evaluation)` and `setup_eval_commands()` determine
  the precise setup command order for evaluation vs agent inference.
- `format_entry_file(entry_file)` and `get_command(entry_file, is_agent_run)`
  produce the command string executed inside the runtime.
- `get_ignore_globs(static_assets)` and `get_archive_save_dir()` drive snapshot
  behaviour so workspaces and snapshots stay consistent across backends.

### EnvironmentConfig

Defined in `models.py`, this Pydantic model holds:

- `env: dict[str, str]` – key/value pairs injected into every runtime command.
- `include_os_env: bool` – whether to merge the current process environment.

### SetupConfig

Controls one-time setup execution with separate paths for agent and evaluation contexts:

- `commands: list[str]` – Always run before user commands in both agent and evaluation contexts. These commands are visible to agents and should contain only essential setup that agents need to know about.
- `eval_commands: list[str]` – Appended when `is_evaluation=True`. These commands are **hidden from agents** and only run during evaluation, allowing you to set up test infrastructure, install dependencies, or configure evaluation-specific resources transparently.

**Example:**
```yaml
setup:
  commands:
    # Visible to agents
    - apt-get update
    - apt-get install -y build-essential

  eval_commands:
    # Hidden from agents, only run during evaluation
    - pip install -r requirements.txt
    - python -m pytest --version
```

For comprehensive examples and use cases, see [Environment Configuration in the Evaluation Guide](../evaluation/configuration.md#environment-configuration).

### CommandConfig

Describes how adapters and agents discover the entry file:

- `entry_file` – format string that receives the configured entry filename.
- `command` – evaluator-visible command (e.g. `python`).
- `agent_command` – optional override exposed to the agent UI.

### SnapshotConfig

Tunes workspace archiving:

- `keep_globs` / `ignore_globs` – inclusion and exclusion filters.
- `compression` – `gz`, `bz2`, `xz`, or `none`.
- `archive_save_dir` – persistent directory for snapshot archives (defaults to
  a temporary location when unset).

## LocalEnvironmentSpec

Located in `src/slop_code/execution/local_runtime.py`, the local backend extends
`EnvironmentSpec` with host-specific options:

- `type: Literal["local"]`.
- `local: LocalConfig` – encapsulates:
  - `requires_tty: bool` – hint the runtime should request a TTY.
  - `shell: str | None` – override the shell used to execute setup commands.

`LocalRuntime` uses these fields to coordinate `subprocess.Popen` execution while
reusing the shared workspace, snapshot, and file materialisation logic.

## DockerEnvironmentSpec

Defined in `src/slop_code/execution/docker_runtime.py`, the Docker backend adds
container-specific knobs:

- `type: Literal["docker"]`.
- `image: str` – container image to run commands in (required).
- `docker_binary: str` – CLI used for `docker exec` (defaults to `docker`).
- `workdir: str` – workspace mount point inside the container.
- `mount_workspace: bool` – toggle bind-mounting the session workspace.
- `extra_mounts: dict[str, str | dict[str, str]]` – additional host→container
  mounts (validated to avoid nesting under `workdir`).
- `network: str | None` – desired Docker network; reconciled via
  `effective_network_mode()` to account for platform constraints.
- `user: str | None` – user/group for container processes. Helpers
  `get_eval_user()` / `get_actual_user()` provide sensible defaults for
  evaluation vs agent inference contexts.
- `keep_container_after_clean: bool` – skip container removal so failed runs can
  be inspected manually.

`DockerRuntime` uses `get_effective_address()` to rewrite loopback bindings when
bridge networking is required and merges additional mounts, ports, and assets
before creating the long-lived container.

## Type Union

`EnvironmentSpecType` in `src/slop_code/execution/__init__.py` exposes a
discriminated union (`LocalEnvironmentSpec | DockerEnvironmentSpec`) so
configuration loaders can parse a heterogeneous collection of specs in one call.
`spawn_runtime()` and `Session.spawn()` rely on this union when dispatching to
runtime implementations.

## Adding a New Backend

1. Subclass `EnvironmentSpec` with backend-specific fields (and any nested
   configs required for that environment).
2. Register the runtime via `@register_runtime("<type>")`.
3. Extend `EnvironmentSpecType` to include the new spec.
4. Update documentation and tests so the new backend’s behaviour is validated.

Following this pattern keeps the execution layer predictable for adapters while
allowing new backends to compose with the existing session and workspace APIs.
