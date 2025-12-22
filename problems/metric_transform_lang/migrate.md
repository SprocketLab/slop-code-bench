# Migration Plan: metric_transform_lang

## Overview
- **Adapter type**: CLI
- **Checkpoints**: 5
- **Has loader.py**: Yes
- **Has verifier.py**: Yes
- **Static assets**: None found
- **Tracked files** (adapter): `out.meta.json`, `out.jsonl`, `.mtl_state/KPIs.state.json`, `out.json`

## Checkpoint Summary

| Checkpoint | Core | Functionality | Error | Regressions From |
|------------|------|---------------|-------|------------------|
| 1          | Yes  | -             | Yes   | -                |
| 2          | Yes  | Yes           | Yes   | In-checkpoint `regression` group |
| 3          | Yes  | Yes           | Yes   | In-checkpoint `regression` group |
| 4          | Yes (`spec_correct`) | Yes | Yes (`spec_error`) | In-checkpoint `regression` group |
| 5          | Yes (`spec_correct`) | Yes | Yes (`spec_error`, `resume_error`) | In-checkpoint `regression` group (mark as regression; disable prior checkpoints) |

## Group to Type Mapping

### checkpoint_1
- `core/` -> Core (unmarked)
- `error/` -> Error (`@pytest.mark.error`)

### checkpoint_2
- `core/` -> Core (unmarked)
- `hidden/` -> Functionality (`@pytest.mark.functionality`)
- `error/` -> Error (`@pytest.mark.error`)
- `file_output/` -> Functionality (`@pytest.mark.functionality`)
- `regression/` -> Functionality (`@pytest.mark.functionality`)

### checkpoint_3
- `core/` -> Core (unmarked)
- `hidden/` -> Functionality (`@pytest.mark.functionality`)
- `error/` -> Error (`@pytest.mark.error`)
- `file_output/` -> Functionality (`@pytest.mark.functionality`)
- `regression/` -> Functionality (`@pytest.mark.functionality`)

### checkpoint_4
- `spec_correct/` -> Core (unmarked)
- `spec_error/` -> Error (`@pytest.mark.error`)
- `file_output/` -> Functionality (`@pytest.mark.functionality`)
- `hidden/` -> Functionality (`@pytest.mark.functionality`)
- `regression/` -> Functionality (`@pytest.mark.functionality`)

### checkpoint_5
- `spec_correct/` -> Core (unmarked)
- `spec_error/` -> Error (`@pytest.mark.error`)
- `resume_error/` -> Error (`@pytest.mark.error`)
- `file_output/` -> Functionality (`@pytest.mark.functionality`)
- `hidden/` -> Functionality (`@pytest.mark.functionality`)
- `regression/` -> Functionality (`@pytest.mark.regression`)

## Case Inventory

**Every case MUST become a test. No cases can be lost.**

| Checkpoint | Group | Case Count | Test Strategy |
|------------|-------|------------|---------------|
| 1 | core | 28 | Parametrize over case directories |
| 1 | error | 14 | Parametrize over case directories |
| 2 | core | 18 | Parametrize over case directories |
| 2 | hidden | 8 | Parametrize over case directories |
| 2 | error | 12 | Parametrize over case directories |
| 2 | file_output | 2 | Parametrize over case directories |
| 2 | regression | 12 | Parametrize over case directories |
| 3 | core | 16 | Parametrize over case directories |
| 3 | hidden | 5 | Parametrize over case directories |
| 3 | error | 10 | Parametrize over case directories |
| 3 | file_output | 1 | Parametrize over case directories |
| 3 | regression | 30 | Parametrize over case directories |
| 4 | spec_correct | 2 | Parametrize over case directories |
| 4 | spec_error | 4 | Parametrize over case directories |
| 4 | file_output | 1 | Parametrize over case directories |
| 4 | hidden | 9 | Parametrize over case directories |
| 4 | regression | 46 | Parametrize over case directories |
| 5 | spec_correct | 1 | Parametrize over case directories |
| 5 | spec_error | 3 | Parametrize over case directories |
| 5 | resume_error | 2 | Parametrize over case directories |
| 5 | file_output | 1 | Parametrize over case directories |
| 5 | hidden | 17 | Parametrize over case directories |
| 5 | regression | 48 | Parametrize over case directories |

### How Cases Are Discovered
- `helpers.get_group_path()` resolves the group directory for a checkpoint.
- `helpers.discover_dir_cases()` iterates **case directories** directly under each group directory.
- Each case directory contains an `ARGS` file (optional), input files (CSV/TSV/Parquet/DSL/config), and expected output files.

## Loader Analysis

### Input File Handling
- `ARGS` file is optional; when present, it is parsed with `shlex.split` and passed as CLI args.
- All files under the case directory are included as input files **except**:
  - `ARGS`
  - `EXPECTED`, `EXPECTED.json`, `EXPECTED.jsonl`
  - `META.yaml`
  - `out.json`
  - Anything under an `expected/` subdirectory
- `InputFile.from_path(relative_to=case_dir, path=rel_path)` is used, so nested inputs retain relative paths.

### Expected Output Handling
- Stdout expectations are read from the first of: `EXPECTED`, `EXPECTED.json`, `EXPECTED.jsonl`, parsed via `json.loads`.
- File output expectations:
  - If `out.json` exists, it is read as JSON and stored under `expected.files["out.json"]`.
  - If an `expected/` directory exists, each file inside is read as JSON and added to `expected.files` by filename.
- META expectations (optional): `META.yaml` can set `expected.status_code` and `expected.stderr`.
- Default status codes if META is absent:
  - group name starts with `resume` -> status `6`
  - group name starts with `spec_error` -> status `1`
  - otherwise -> status `0`

### Static Assets
- No `assets/` or `files/` directories in the problem root. All inputs live inside case directories.

### Special Processing
- Expected stderr patterns from `META.yaml` are **loaded** but not enforced by the verifier (see below).

## Solution Analysis

### Reference Implementation
- Each checkpoint provides `checkpoint_N/solution/mtl.py` plus a `mtl_core/` package.
- The CLI entrypoint is consistent across checkpoints; functionality expands from Part 1 through Part 5.

### Key Implementation Details
- Outputs are JSON objects or arrays (or file outputs like `out.json`) per the spec.
- Later checkpoints add multi-input ingestion, ingest config + joins, and resume/metadata features.

## Verifier Analysis

### Verification Logic
- **Error cases** (`expected.status_code != 0`):
  - Only checks that `actual.status_code != 0`.
  - Stderr is matched against `.*` (expected stderr from META is ignored).
- **Success cases**:
  - Always checks status code equals expected (weight 0.1).
  - Stdout JSON is parsed and deep-diffed when `expected.output` is truthy.
  - If `expected.output` is a list and actual output is a single object, it is wrapped in a list before comparison.
  - If `expected.output` is empty (`[]` or `{}`), it is **not** verified due to the truthiness check.
- **File outputs**:
  - If `expected.files` is set, it deep-diffs each expected file’s JSON content against the actual file’s JSON.
  - Adds a synthetic `META` file entry to report per-file diffs.

### Regression Handling
- Checkpoint 5 should treat `regression/` as regression-marked tests and **disable prior checkpoints** (set `include_prior_tests: false`).
- Earlier checkpoints use explicit `regression/` groups without disabling prior checkpoints.

### Tolerance/Approximate Matching
- Uses `deepdiff` with default options (no explicit numeric tolerances).

## Breaking Changes

- **checkpoint_3**: CLI moves from `--csv` to multi-file `--input` model and adds format/null/strict flags.
- **checkpoint_4**: introduces `--ingest-config` and multi-source joins; regression cases also use ingest configs.
- **checkpoint_5**: requires DSL version header and adds resume/metadata semantics; `resume_error` group expects exit code `6`.\n+  - Migration note: mark regression tests as regressions and set `include_prior_tests: false`.

No explicit `include_prior_tests: false` flags are present, so prior behavior is expected to remain supported via the regression groups in each checkpoint.

## Migration Notes

### Fixtures Needed
- `entrypoint_argv` (standard)
- `checkpoint_name` (standard)
- Case directory fixtures to build `InputFile` bundles and read `ARGS`, `EXPECTED*`, `META.yaml`, and `expected/` files

### Test Data
- Parametrize by case directory name per group.
- For each case:
  - Build CLI args from `ARGS` (or empty).
  - Add all non-expected files as inputs (retain relative paths).
  - Expected stdout = `EXPECTED*` JSON (if present).
  - Expected files = `out.json` and/or `expected/` directory JSON files.
  - Expected status code / stderr from `META.yaml` (if present) else use loader defaults.

### Edge Cases
- Error groups only require non-zero exit codes; do not assert exact codes.
- Some cases use file outputs (`expected/` or `out.json`) with no stdout expectation.
- `expected.output` truthiness affects verification; empty array/object outputs are not verified today.
- Resume and spec error groups use default status codes when META is absent (`6` and `1`).
