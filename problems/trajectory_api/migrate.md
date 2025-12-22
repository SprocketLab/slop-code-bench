# Migration Plan: trajectory_api

## Overview
- **Adapter type**: API (HTTP server, `/healthz`, `response_is_json: true`)
- **Checkpoints**: 5
- **Has loader.py**: Yes (case_order-driven, Jinja placeholders, CaseStore)
- **Has verifier.py**: Yes (status/headers/jsonschema)
- **Static assets**: None (no `assets/` or `files/`, `tracked_files: []`)

## Checkpoint Summary

| Checkpoint | Core | Functionality | Error | Regressions From |
|------------|------|---------------|-------|------------------|
| 1          | 4    | 30            | 6     | -                |
| 2          | 12   | 50            | 13    | checkpoint_1 (spec_cases) |
| 3          | 8    | 94            | 8     | checkpoint_1, checkpoint_2 (spec_cases, hidden) |
| 4          | 6    | 88            | 5     | checkpoint_1, checkpoint_2, checkpoint_3 (spec_cases, hidden) |
| 5          | 7    | -             | 11    | checkpoint_1, checkpoint_2, checkpoint_3, checkpoint_4 (spec_cases, hidden) |

## Group to Type Mapping

### checkpoint_1
- `spec_cases/` -> Core (unmarked)
- `spec_errors/` -> Error (`@pytest.mark.error`)
- `hidden/` -> Functionality (`@pytest.mark.functionality`)

### checkpoint_2
- `spec_cases/` -> Core (unmarked)
- `spec_errors/` -> Error (`@pytest.mark.error`)
- `hidden/` -> Functionality (`@pytest.mark.functionality`)

### checkpoint_3
- `spec_cases/` -> Core (unmarked)
- `spec_errors/` -> Error (`@pytest.mark.error`)
- `hidden/` -> Functionality (`@pytest.mark.functionality`)

### checkpoint_4
- `spec_cases/` -> Core (unmarked)
- `spec_errors/` -> Error (`@pytest.mark.error`)
- `hidden/` -> Functionality (`@pytest.mark.functionality`)

### checkpoint_5
- `spec_cases/` -> Core (unmarked)
- `spec_errors/` -> Error (`@pytest.mark.error`)

## Case Inventory

**Every case MUST become a test. No cases can be lost.**

| Checkpoint | Group | Case Count | Test Strategy |
|------------|-------|------------|---------------|
| 1          | spec_cases | 4  | parametrized in config order; shared store |
| 1          | spec_errors | 6 | parametrized in config order; shared store |
| 1          | hidden | 30 | parametrized in config order; shared store |
| 2          | spec_cases | 12 | parametrized in config order; shared store |
| 2          | spec_errors | 13 | parametrized in config order; shared store |
| 2          | hidden | 50 | parametrized in config order; shared store |
| 3          | spec_cases | 8 | parametrized in config order; shared store |
| 3          | spec_errors | 8 | parametrized in config order; shared store |
| 3          | hidden | 94 | parametrized in config order; shared store |
| 4          | spec_cases | 6 | parametrized in config order; shared store |
| 4          | spec_errors | 5 | parametrized in config order; shared store |
| 4          | hidden | 88 | parametrized in config order; shared store |
| 5          | spec_cases | 7 | parametrized in config order; shared store |
| 5          | spec_errors | 11 | parametrized in config order; shared store |

### How Cases Are Discovered
- `loader.py` uses `group.case_order` from `config.yaml` and loads
  `<checkpoint>/<group>/<case_name>.yaml` in that exact order.
- No globbing or manifest files. Case order matters (some groups explicitly
  note setup cases must run first).
- Each YAML file contains `case` and `expected` blocks. `expected.output` is a
  JSON schema; `expected.headers` is optional.
- Jinja placeholders like `{{store.some_case}}` are rendered before parsing;
  the store is updated from prior responses (IDs, toolpack versions).

## Loader Analysis

### Input File Handling
- YAML case files are parsed with `yaml.safe_load` after Jinja rendering.
- `case` maps directly to `APICase` fields (method/path/headers/body/etc.).
- `expected` maps to `APIResult` fields; output is JSON schema for validation.

### Static Assets
- None.

### Special Processing
- `TrajectoryStore` tracks IDs and versions across cases:
  - Stores `id` from `POST /trajectories` and `POST /trajectories/{id}/fork`.
  - Stores `version` from `POST /environments/{name}/toolpacks`.
- Placeholders referencing these values appear in later case paths/expected
  output, so tests must preserve order and share the store across cases.

## Solution Analysis

### Reference Implementation
- Each checkpoint has `checkpoint_N/solution/trajectory_api.py`.
- Checkpoints 1-2 also include `api/` and `tests/` helper code.
- Uses Python stdlib HTTP server (`ThreadingHTTPServer`/`BaseHTTPRequestHandler`)
  with in-process data storage.

### Key Implementation Details
- Checkpoint 1: create/get/search/report/totals with validation and
  derived fields.
- Checkpoint 2: mutable trajectories (in-progress/finalized), append/finalize,
  ETag-style revision tracking.
- Checkpoint 3: forking with lineage and parent-child search.
- Checkpoint 4: grammar upload/activation, tool call extraction, env versions.
- Checkpoint 5: toolpacks, tool execution records, file snapshot fetch.

## Verifier Analysis

### Verification Logic
- Status code match (weight 0.2).
- Optional header deepdiff (weight 0.1 when expected headers are present).
- Output validated with JSON schema (weight 0.7/0.8) after parsing JSON with
  `allow_invalid=True`.

### Regression Handling
- None in verifier; relies on `config.yaml` regressions.

### Tolerance/Approximate Matching
- None (strict schema-based validation).

## Breaking Changes

- No explicit breaking changes. Note that checkpoint_2 only regresses
  checkpoint_1 `spec_cases` (not hidden), which may indicate behavioral shifts
  or deprioritized hidden regressions.

## Migration Notes

### Fixtures Needed
- `entrypoint_argv` (standard)
- `checkpoint_name` (standard)
- `case_store` or equivalent fixture to track IDs/versions and perform
  placeholder substitution

### Test Data
- Convert each YAML case into a parametrized test entry; keep config order.
- Use a helper to render Jinja placeholders from the store before sending
  requests.
- Validate responses with jsonschema using the `expected.output` schema.

### Edge Cases
- Order matters; some hidden groups include setup cases that must run first.
- Store updates for toolpack versions are used later (e.g., activate toolpack
  by version).
- Some tests validate headers; only assert headers when `expected.headers` is
  defined.
