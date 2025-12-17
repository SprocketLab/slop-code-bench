---
version: 1.1
last_updated: 2025-11-15
---

# Static Assets

Static assets let checkpoints mount additional files or directories into the
execution workspace without duplicating them for every case. The configuration
and resolution helpers live in `src/slop_code/execution/assets.py` and are reused
by sessions, workspaces, and runtimes.

## Configuration

YAML configuration defines assets as name → `StaticAssetConfig` pairs. Each
config includes:

- `path` – relative to the problem/checkpoint directory.
- `save_path` – optional relative location inside the execution workspace where
  the asset should appear. If omitted, the asset is saved at the same relative
  path as `path`.
- Validation ensures both paths stay relative (no absolute paths or `..` escapes).

`StaticAssetConfig.resolve(base_path, name)` returns a `ResolvedStaticAsset`
containing both the absolute on-disk path and the workspace-relative save path.
Use `ResolvedStaticAsset.workspace_path(workspace_root)` to determine where an
asset will materialise inside a prepared workspace.

## Resolution

`resolve_static_assets()` accepts either:

- A flat mapping of assets (legacy style), or
- A map of asset groups plus an `ordering` list. Later groups override earlier
  ones, enabling submission-specific overrides to trump problem defaults.

The function logs which assets were resolved and returns a dictionary of
`ResolvedStaticAsset` instances ready for the session.

## Usage in Sessions and Runtimes

- **Workspace materialization** – Agent inference sessions copy assets into the
  temporary workspace so agents can modify or inspect them directly. Evaluation
  sessions leave assets on the host and rely on runtime-specific mounting.
- **Placeholder resolution** – `Session.resolve_static_placeholders()` replaces
  `{{static:name}}` tokens with the correct path. When running in Docker the
  result points at `/static/<save_path>`, matching how the runtime mounts assets.
- **Runtime mounts** – `DockerRuntime` adds each resolved asset as a read-only
  volume, while `LocalRuntime` simply exposes the host copy through the workspace
  path (which may itself contain materialized assets when running in agent mode).

## Placeholders in Cases

The evaluation runner exposes static assets to case loaders by swapping
placeholders such as `{{static:dataset}}` with the resolved host path. This
allows cases to reference large corpora or API specs without duplicating bytes.

`resolve_static_placeholders(data, static_assets, is_docker=...)` performs the
same substitution at runtime for adapter payloads, ensuring commands have
environment-appropriate paths regardless of backend.

When adding new asset types (archives, remote URLs, secrets), extend
`StaticAssetConfig` with additional fields and update the workspace/materializer
logic to honor them during session preparation.
