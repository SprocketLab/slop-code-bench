---
version: 1.0
last_updated: 2025-11-03
---

# Authoring Evaluation Problems

This guide walks through end-to-end problem authoring for the evaluation framework. It uses two shipped problems as anchors:

- `examples/yaml_joiner/problem/` — a compact CLI example focused on filesystem inputs and deterministic file output.
- `problems/dynamic_config_service_api/` — a larger API scenario that exercises ordered case execution, JSON schemas, and temporal tolerances.

Pair this document with `docs/guides/creating-loaders-and-verifiers.md` for protocol details and helper APIs.

## Overview & Prerequisites

- **Audience**: Engineers designing new problems for Slop Code’s evaluation runner.
- **Tooling**: Python 3.12+, project set up with `uv sync`, and access to the repository’s `docs/guides` references.
- **Baseline Knowledge**: Familiarity with `ProblemConfig`, group/checkpoint hierarchy, and either CLI or API adapters.
- **Reference Patterns**:
  - CLI: `yaml_joiner` demonstrates directory-based cases, static assets, and file comparison verifiers.
  - API: `dynamic_config_service_api` models stateful API workflows, strict case ordering, and JSON schema validation.

## Core Concepts in Plain Language

If you are new to the framework, keep these ideas in mind before diving into the examples:

- **Problem**: A self-contained evaluation package that lives in its own directory. Every problem has a root `config.yaml`, a `loader.py`, and a `verifier.py`.
- **Checkpoints**: Milestones within a problem (e.g., `checkpoint_1`). Each checkpoint contains specific tests plus its own `config.yaml` and `spec.md` file describing the requirements.
- **Groups**: Named collections of related cases inside a checkpoint (for example `core`, `error`, or `spec_cases`). Groups let you separate success scenarios from error scenarios.
- **Cases**: Individual tests. In CLI problems they usually live in dedicated directories; in API problems they live in YAML files. The loader transforms each case into a runnable request plus an expected response.
- **Adapters**: Decide how the evaluation engine interacts with the submission. CLI adapters run command-line programs; API adapters send HTTP requests to a server.
- **Static Assets & Group Files**: Shared resources (configuration snippets, seed data) that are mounted into the execution environment for every case or every group.
- **Case Order**: For stateful scenarios—especially APIs—cases must run in a predictable sequence. Listing case IDs in `case_order` guarantees that order.

With those definitions, you can read the rest of the guide without prior exposure to the configuration files.

## Project Scaffolding

Problem directories live under `problems/` (production) or `examples/` (teaching). Scaffold the following pieces:

| Component | YAML Joiner (CLI) | Dynamic Config Service (API) |
|-----------|-------------------|------------------------------|
| Root `config.yaml` | Declares the adapter type (`cli`), the script that loads cases, the tracked output files, and the list of checkpoints. | Specifies the adapter type (`api`), details for reaching the service (host, health endpoint, JSON output flag), plus shared loader/entry file references. |
| Checkpoints | Each checkpoint folder contains `config.yaml`, `spec.md`, and one directory per group (for example `core/`). | Same structure, but every group lists a `case_order` so HTTP calls happen in a controlled sequence. |
| Assets | `static_cfgs/` listed under `static_assets`. Cases access them through placeholders such as `{{static:cfg_dir}}`. | Uses `group_files` and shared YAML fixtures inside checkpoint directories to bootstrap the API state. |
| Solution Entrypoint | `entry_file: solution` identifies the CLI binary or script to execute. | `entry_file: config_server` identifies the module that launches the HTTP service under test. |
| Expected Outputs | Each case directory includes a `result.yaml` file representing the correct CLI output. | Expected API responses live alongside the case files under keys like `expected.output`, often as JSON or JSON schema. |

**Key scaffolding steps**:

1. **Copy a template**: Start from `examples/yaml_joiner/problem/` (CLI) or `problems/dynamic_config_service_api/` (API) when creating a new directory tree.
2. **Define checkpoints**: Add each checkpoint name to root `config.yaml`, then create matching directories with their own `config.yaml` and specs.
3. **Group configuration**: Under `checkpoint_X/config.yaml`, declare groups (`core`, `spec_cases`, `error`, etc.), timeouts, and optional `group_files` that should be injected into every case.
4. **Case assets**: For CLI problems, keep each case self-contained in a directory (e.g., `checkpoint_1/core/multiple/` with `ARGS`, inputs, expected output). For API problems, store YAML case files named after their logical step (e.g., `activate_specific_version.yaml`) and rely on `case_order`.

## Loader Implementation

Loaders transform checkpoint/group config into `(Case, Expected)` pairs that the runner executes. The core protocol is covered in `creating-loaders-and-verifiers.md`; the examples show two common patterns.

### CLI Loader (`yaml_joiner`)

- **What it produces**: A `CLICase` object describing how to invoke the command-line program (arguments plus input files) and a `CLIResult` object containing the expected status code and output files.
- Implements `Loader` without inheritance, but uses `NoOpStore` because cases are stateless.
- Uses `helpers.discover_dir_cases` to iterate case directories and `helpers.get_files_from_globs` to bundle all YAML inputs except the expected result.
- Reads CLI arguments from an `ARGS` file with `shlex.split`, builds `InputFile` objects, and registers tracked files so the adapter captures results.
- Returns `CLICase` populated with arguments and input files, plus a `CLIResult` wrapping the parsed expected YAML file.

**Example flow**: for `checkpoint_1/core/multiple/`, the loader
1. Reads `ARGS` (`result.yaml -c A.yaml B.yaml`) and turns it into an argument list
2. Packages every YAML file in the directory (except `result.yaml`) as inputs
3. Parses `result.yaml` into a Python dictionary and stores it as the expected file payload
4. Yields the `(CLICase, CLIResult)` tuple back to the runner

### API Loader (`dynamic_config_service_api`)

- **What it produces**: An `APICase` describing a single HTTP request (method, path, headers, body) and an `APIResult` containing the expected status, headers, and payload for that request.
- Inherits from `BaseLoader` to reuse the default store handling but could also implement the protocol directly.
- Enforces execution order by iterating `group.case_order` and reading matching `*.yaml` files.
- Constructs `APICase` objects with HTTP method, path, headers, and body pulled from the YAML’s `case` block; expected responses become `APIResult` instances.
- Relies on `helpers.get_group_path` to resolve the absolute directory for the current group, keeping loader logic independent of filesystem layout.

**Example flow**: for `checkpoint_1/functionality/activate_specific_version.yaml`, the loader
1. Loads the YAML file and reads the `case` section, which contains fields like `method: POST`, `path: /scopes/billing/activate`, and a JSON request body
2. Builds an `APICase` with those values along with metadata (group name, checkpoint name)
3. Reads the `expected` section, typically including `status_code`, optional `headers`, and an `output` payload or schema, and wraps it in an `APIResult`
4. Yields the `(APICase, APIResult)` pair in the order defined by `case_order`

### Shared Tips

- Always honor `group_config.group_files` and `static` placeholders so shared assets resolve correctly.
- Initialize a custom `CaseStore` when later cases depend on earlier results (see the “API Cases with State Management” pattern in the loader guide).
- Validate that every case mentioned in `case_order` has a matching file or directory; raise descriptive errors if something is missing.

## Verifier Implementation

Verifiers score each case and must return a dictionary of `VerificationResult` objects keyed by result attribute (see `creating-loaders-and-verifiers.md`).

### CLI Verifier (`yaml_joiner`)

- Verifies status codes with `verifiers.matches_status_code` (weight 0.25) and compares expected vs actual YAML by parsing the tracked `result.yaml` file through `parsers.parse_yaml_file` followed by `verifiers.deepdiff_verify`.
- Handles error-focused groups by matching stderr with `verifiers.matches_regex`, showing how to branch on group name or expected status.
- Keeps logic compact (<50 lines) while delivering actionable diffs.

**Why it works**: Each CLI run writes a `result.yaml` file. The verifier opens that file, converts it to Python data, and compares it against the dictionary stored in the expected result. Differences appear in the DeepDiff output, making it obvious which keys changed.

### API Verifier (`dynamic_config_service_api`)

- Always checks status codes and conditionally verifies headers when present, adjusting weights to prioritize payload accuracy (0.7–0.8).
- Parses response bodies with `parsers.parse_json` and automatically detects JSON Schema expectations, delegating to `verifiers.jsonschema_verify` when appropriate.
- Normalizes timestamps within a five-second tolerance so tests remain stable despite execution timing; `_align_datetimes` walks nested structures and rewrites near-equal ISO timestamps.
- Demonstrates how to combine deep diff comparisons with custom preprocessing when the domain demands leniency around specific fields.

**Reading the YAML**: Each API case stores expected values like this:

```yaml
expected:
  status_code: 200
  headers:
    content-type: application/json
  output:
    config:
      name: billing
      version: 2
```

The verifier turns the `output` block into data and compares it to the server’s JSON response. If the YAML includes JSON Schema keywords (`properties`, `type`, etc.), the verifier automatically switches to schema validation instead of literal comparison.

### Best Practices

- Centralize all comparison logic through helpers (`deepdiff_verify`, `matches_regex`, `jsonschema_verify`) instead of custom assertions.
- Choose weights that reflect importance: status (0.1–0.2), headers/metadata (0.1), primary output (0.6+).
- Use `parsers.ensure_expected_is_not_none` and related utilities to guard against missing expectations.
- Keep verifiers deterministic and side-effect free; avoid accessing the filesystem directly except via `CaseResult.files`.

## Regression Testing Between Checkpoints

As problems evolve through multiple checkpoints, regression testing ensures that functionality from earlier checkpoints continues to work. The framework provides a powerful regression system that automatically imports test cases from previous checkpoints.

### When to Use Regression Testing

Consider regression testing when:

- **Progressive Features**: Each checkpoint adds new functionality while maintaining existing features
- **Bug Fix Validation**: Ensure bugs fixed in earlier checkpoints don't reappear
- **API Evolution**: New endpoints or features must maintain backward compatibility
- **Quality Assurance**: Critical functionality must work across all checkpoint iterations

### Setting Up Regression Tests

Add a `regressions` field to your checkpoint configuration:

```yaml
regressions:
  - checkpoint: checkpoint_1
    groups: [core, errors]
  - checkpoint: checkpoint_2
    type_filter: Core
```

This imports:
- `core` and `errors` groups from `checkpoint_1`
- All `Core` type groups from `checkpoint_2`

### Common Patterns

#### Progressive Core Functionality

For problems where each checkpoint builds on the previous:

```yaml
# checkpoint_5/config.yaml
regressions:
  - checkpoints: "*"  # Import from all prior checkpoints
    type_filter: Core  # Only core functionality
```

#### Selective Bug Fix Import

Import specific bug fix groups:

```yaml
regressions:
  - checkpoint: checkpoint_2
    groups: [security_fixes, critical_bugs]
    name_template: "must_not_regress_{group}"
```

#### Exclude Slow or Redundant Tests

```yaml
regressions:
  - checkpoints: "*"
    exclude: [slow_integration, experimental]
```

### How Regression Groups Work with Loaders

Your loader doesn't need special handling for regression groups. The `get_group_path` helper automatically resolves to the original test location:

```python
from slop_code.evaluation.loaders import helpers, BaseLoader
from slop_code.evaluation.config import GroupConfig

class Loader(BaseLoader):
    def __call__(self, group: GroupConfig, store):
        # Automatically handles both regular and regression groups
        # self.problem and self.checkpoint are set in __init__
        group_path = helpers.get_group_path(group, self.problem, self.checkpoint)

        # Load cases normally - the path points to the original tests
        for case_dir in group_path.iterdir():
            # Process cases...
```

### Design Considerations

1. **Consistent Group Names**: Use the same group names across checkpoints for easy regression testing
2. **Type Classification**: Properly classify groups (Core, Error, Functionality) to enable type filtering
3. **Performance Impact**: Large regression imports can slow evaluation - be selective
4. **Clear Documentation**: Document your regression strategy in comments

### Example: API with Regression Testing

```yaml
# problems/api_service/config.yaml
checkpoints:
  checkpoint_1:
    groups:
      v1_endpoints:
        type: Core
        case_order: [create, read, update, delete]

  checkpoint_2:
    groups:
      v2_endpoints:
        type: Core
        case_order: [create_v2, read_v2]
    regressions:
      - checkpoint: checkpoint_1
        groups: [v1_endpoints]  # v1 must still work

  checkpoint_3:
    groups:
      v3_features:
        type: Functionality
    regressions:
      - checkpoints: "*"
        type_filter: Core  # All core functionality from v1 and v2
```

This ensures that as the API evolves, earlier versions remain functional and tested.

### Best Practices

1. **Start Simple**: Begin with basic regression imports before complex patterns
2. **Be Selective**: Import only relevant tests, not everything
3. **Monitor Performance**: Watch evaluation time as regression tests accumulate
4. **Document Intent**: Explain why specific groups are imported
5. **Test Incrementally**: Verify regression imports work at each checkpoint

For more detailed information, see the [Regression Testing Guide](regression-testing.md).

## Testing & Iteration

1. **Review loaded cases**: Use `streamlit run src/slop_code/entrypoints/tasks.py` to see what your cases are loading.
2. **Run evaluation**: Test your problem with the evaluation command:
   ```bash
   slop-code eval-snapshot \
     --problem-name your_problem \
     --submission-path problems/your_problem/checkpoint_1/solution \
     --checkpoint-num 1 \
     --env-config configs/environments/docker-python3.12-uv.yaml
   ```
3. **Debug verifier output**: Check the evaluation report for verification diffs to understand what's failing.

By combining these steps with the helper patterns documented in `creating-loaders-and-verifiers.md`, you can develop robust, maintainable evaluation problems that blend deterministic scoring with rich diagnostics.


