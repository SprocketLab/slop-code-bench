# Migration Plan: log_query

## Overview
- **Adapter type**: CLI
- **Checkpoints**: 5
- **Has loader.py**: Yes
- **Has verifier.py**: Yes
- **Static assets**: None (no assets/ or files/ dirs; tracked_files empty)

## Checkpoint Summary

| Checkpoint | Core | Functionality | Error | Regressions From |
|------------|------|---------------|-------|------------------|
| 1          | Y    | Y             | Y     | -                |
| 2          | Y    | Y             | Y     | 1                |
| 3          | Y    | Y             | Y     | 1, 2             |
| 4          | Y    | Y             | Y     | 1, 2, 3          |
| 5          | Y    | Y             | Y     | 1, 2, 3, 4       |

## Group to Type Mapping

### checkpoint_1
- `correct` → Core
- `hidden` → Functionality (`@pytest.mark.functionality`)
- `errors` → Error (`@pytest.mark.error`)

### checkpoint_2
- `group_agg` → Core
- `hidden` → Functionality (`@pytest.mark.functionality`)
- `errors` → Error (`@pytest.mark.error`)
- `c1_correct` → Regression (from `checkpoint_1/correct`)
- `c1_hidden` → Regression (from `checkpoint_1/hidden`)

### checkpoint_3
- `conflation` → Core
- `hidden` → Functionality (`@pytest.mark.functionality`)
- `errors` → Error (`@pytest.mark.error`)
- `c1_correct` → Regression (from `checkpoint_1/correct`)
- `c2_group_agg` → Regression (from `checkpoint_2/group_agg`)

### checkpoint_4
- `gloss` → Core
- `hidden` → Functionality (`@pytest.mark.functionality`)
- `errors` → Error (`@pytest.mark.error`)
- `c1_correct` → Regression (from `checkpoint_1/correct`)
- `c2_group_agg` → Regression (from `checkpoint_2/group_agg`)
- `c3_conflation` → Regression (from `checkpoint_3/conflation`)

### checkpoint_5
- `subqueries` → Core
- `hidden` → Functionality (`@pytest.mark.functionality`)
- `errors` → Error (`@pytest.mark.error`)
- `c1_correct` → Regression (from `checkpoint_1/correct`)
- `c2_group_agg` → Regression (from `checkpoint_2/group_agg`)
- `c3_conflation` → Regression (from `checkpoint_3/conflation`)
- `c4_gloss` → Regression (from `checkpoint_4/gloss`)

## Case Inventory

**Every case MUST become a test. No cases can be lost.**

| Checkpoint | Group | Case Count | Test Strategy |
|------------|-------|------------|---------------|
| 1 | correct | 10 | Parametrize from `correct.json` |
| 1 | hidden | 67 | Parametrize from `hidden.json` |
| 1 | errors | 5 | Parametrize from `errors.json` |
| 2 | group_agg | 5 | Parametrize from `group_agg.json` |
| 2 | hidden | 45 | Parametrize from `hidden.json` |
| 2 | errors | 4 | Parametrize from `errors.json` |
| 2 | c1_correct | 10 | Parametrize from `checkpoint_1/correct.json` |
| 2 | c1_hidden | 67 | Parametrize from `checkpoint_1/hidden.json` |
| 3 | conflation | 4 | Parametrize from `conflation.json` |
| 3 | hidden | 26 | Parametrize from `hidden.json` |
| 3 | errors | 4 | Parametrize from `errors.json` |
| 3 | c1_correct | 10 | Parametrize from `checkpoint_1/correct.json` |
| 3 | c2_group_agg | 5 | Parametrize from `checkpoint_2/group_agg.json` |
| 4 | gloss | 2 | Parametrize from `gloss.json` |
| 4 | hidden | 26 | Parametrize from `hidden.json` |
| 4 | errors | 4 | Parametrize from `errors.json` |
| 4 | c1_correct | 10 | Parametrize from `checkpoint_1/correct.json` |
| 4 | c2_group_agg | 5 | Parametrize from `checkpoint_2/group_agg.json` |
| 4 | c3_conflation | 4 | Parametrize from `checkpoint_3/conflation.json` |
| 5 | subqueries | 3 | Parametrize from `subqueries.json` |
| 5 | hidden | 25 | Parametrize from `hidden.json` |
| 5 | errors | 4 | Parametrize from `errors.json` |
| 5 | c1_correct | 10 | Parametrize from `checkpoint_1/correct.json` |
| 5 | c2_group_agg | 5 | Parametrize from `checkpoint_2/group_agg.json` |
| 5 | c3_conflation | 4 | Parametrize from `checkpoint_3/conflation.json` |
| 5 | c4_gloss | 2 | Parametrize from `checkpoint_4/gloss.json` |

### How Cases Are Discovered
`loader.py` reads a single JSON file per group. For regression groups,
the loader points at the original checkpoint's group file. Each JSON file
maps `case_name` → `{case: ..., expected: ...}`. No dynamic generation.

## Loader Analysis

### Input File Handling
- Each case specifies `case.input_files` with `path`, `content`, and
  optional `file_type` (e.g., `jsonl` for NDJSON). The loader passes these
  directly to `InputFile.model_validate` for file creation.

### CLI Arguments
- `case.arguments` is a shell-like string; the loader uses `shlex.split`.
- It re-quotes the argument after `--query` if needed to keep it a single
  argument. Tests should preserve the query as one CLI arg.

### Static Assets
- None referenced in `config.yaml`. No `assets/` or `files/` directories.

### Special Processing
- Regression groups load from the original checkpoint directory.
- Otherwise, no templating or dynamic file generation.

## Solution Analysis

### Reference Implementation
- Each checkpoint includes `checkpoint_N/solution/logql` (Python package),
  `checkpoint_N/solution/logql.py` wrapper, and tests.

### Key Implementation Details
- CLI outputs JSON arrays on success (to stdout or `--output` file).
- Errors are JSON payloads to stderr with an error message and code.
- Core flow: `parse_query` → `execute_query` → JSON output.

## Verifier Analysis

### Verification Logic
- Success: `stdout` is parsed as JSON (`allow_invalid=True`) and checked
  via deep diff against expected output (weight 0.9).
- Status code is always checked (weight 0.1).

### Error Handling
- For non-zero expected status, the verifier only checks that the status
  is non-zero. It does **not** check stderr contents or error codes.

### Regression Handling
- No special regression handling in the verifier beyond config grouping.

### Tolerance/Approximate Matching
- No numeric tolerance; deep diff comparison is strict after parsing.

## Breaking Changes

No checkpoints mark `include_prior_tests: false`. Each checkpoint adds
features (GROUP BY, CONFLATE, GLOSS, subqueries) while keeping earlier
behavior via explicit regression groups.

## Migration Notes

### Fixtures Needed
- `entrypoint_argv` (standard CLI entrypoint)
- `checkpoint_name` (for regression selection)
- `case_files` fixture to write `input_files` to disk (jsonl and json)

### Test Data
- Use JSON group files (`*.json`) as the source of parametrized test cases.
- `expected.output` is JSON data for stdout comparisons.
- `expected.stderr` appears in error cases but was not verified previously.

### Edge Cases
- Queries include nested quotes and uncommon keywords; keep `--query`
  argument intact when constructing argv.
- Error cases in `errors.json` rely only on non-zero status per verifier.
