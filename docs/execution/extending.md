version: 1.1
last_updated: 2025-11-09
---

# Extending Execution

The execution package is intentionally modular. Follow these guidelines when
adding new capabilities or backends.

## New Environment Specs & Runtimes

1. Subclass `EnvironmentSpec` with backend-specific fields. Give the model a
   distinct `type` literal so Pydantic can discriminate the union.
2. Implement a `SubmissionRuntime` subclass that fulfils the runtime protocol
   (`stream`, `execute`, `poll`, `kill`, `cleanup`, and the `spawn` classmethod).
3. Decorate the runtime with `@register_runtime("<type>")` so the session layer
   can dispatch to it.
4. Update `EnvironmentSpecType` in `execution/__init__.py` to include the new
   spec.
5. Document any assumptions about setup commands, mounts, or networking.

## Session Integration

Sessions act as the glue between specs, workspaces, and runtimes. When adding
new behaviour make sure:

- `Session.spawn()` can forward any additional keyword arguments your runtime
  requires.
- Workspace interactions (`materialize_input_files`, `get_file_contents`,
  `update_snapshot`) still behave predictably for both evaluation and agent
  inference modes.
- Static asset placeholder resolution continues to work across backends.

## Static Asset Enhancements

- Extend `StaticAssetConfig` if you need new metadata (archives, signed URLs,
  secrets).
- Update the workspace materialization logic or Docker volume wiring to honour
  the new fields.
- Document how placeholders should be interpreted for the added asset types.

## Error Surfaces

Raise `ExecutionError` (or a subclass) for user-facing failures such as missing
dependencies, container startup issues, or invalid configuration. Runtimes can
also raise `SolutionRuntimeError` for recoverable process lifecycle problems.
Keeping errors within the execution namespace helps adapters surface clear
messages and simplifies logging.

## Testing & Documentation

- Add unit tests under `tests/execution/` for both specs and runtime behaviour.
- Consider integration tests that drive a `Session` end-to-end with an evaluation
  adapter to catch wiring regressions.
- Update `docs/execution` and any adapter-specific docs when behaviour changes
  (volume mounts, networking defaults, snapshot policies, etc.).

Following these patterns keeps the execution layer predictable for adapters and
future maintainers.
