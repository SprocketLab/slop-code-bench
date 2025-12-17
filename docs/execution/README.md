version: 1.1
last_updated: 2025-11-09
---

# Execution Package

The execution layer provides a unified set of primitives for staging workspaces,
launching runtimes, capturing filesystem changes, and bridging evaluation and
agent flows. Core modules live under `src/slop_code/execution` and are composed
around three building blocks:

- `Workspace` – prepares isolated directories, restores snapshots, and exposes
  file-reading helpers.
- `Session` – coordinates workspace lifecycle, static assets, and `SubmissionRuntime`
  instances.
- `SubmissionRuntime` implementations – execute commands locally or inside
  containers while streaming output to adapters.

Use these pages to navigate the package:

- [Session Lifecycle](manager.md) – Workspace orchestration, runtime spawning, and checkpoint handoff
- [Runtime Registry](factory.md) – `SubmissionRuntime` protocol and spawn helpers
- [Environment Specs](environment_specs.md) – Pydantic models shared by all runtimes
- [Local Runtime](local.md) – Host-based execution details
- [Docker Runtime](docker.md) – Container execution, networking, and setup scripts
- [Static Assets](assets.md) – Configuration, resolution, and materialization rules
- [Snapshots & Diffs](snapshots.md) – Capturing workspace state and comparing runs
- [File Operations](file_ops.md) – Reading, writing, and classifying execution files
- [Extending Execution](extending.md) – Adding new specs, runtimes, or tooling
