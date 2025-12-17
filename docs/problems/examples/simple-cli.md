---
version: 1.0
last_updated: 2025-11-06
---

# Example Walkthrough: Simple CLI Problem (`file_backup`)

This document walks through the `file_backup` problem as a complete example of a CLI-based evaluation problem. We'll examine each component and explain the design decisions.

## Problem Overview

**What it tests**: A CLI backup scheduler that:
1. Parses YAML schedule files
2. Determines which backup jobs are due
3. Simulates running backups with exclusion rules
4. Emits JSON Lines event history

**Why this structure**: This problem demonstrates:
- CLI argument parsing
- File I/O (YAML → JSONL)
- Time-based logic (scheduling)
- Progressive complexity across 4 checkpoints

## Directory Structure

```
problems/file_backup/
├── config.yaml                   # Problem configuration
├── loader.py                     # Test case discovery
├── verifier.py                   # Output validation
├── checkpoint_1/                 # Milestone 1: Basic scheduling
│   ├── spec.md
│   ├── core/                     # Success tests
│   │   ├── daily_due_simple/
│   │   │   ├── case.yaml
│   │   │   └── expected.jsonl
│   │   ├── multiple_jobs_sorting/
│   │   └── ... (more cases)
│   └── errors/                   # Error handling tests
│       ├── error_yaml_parse/
│       └── ... (more cases)
├── checkpoint_2/                 # Milestone 2: Add execution modes
├── checkpoint_3/                 # Milestone 3: Add verification
├── checkpoint_4/                 # Milestone 4: Add incremental backup
├── files/                        # Static test data
│   ├── A/
│   │   ├── B/C/D.py
│   │   └── I.py
│   └── M.py
└── solution/                     # Reference implementation
    └── backup_scheduler.py
```

## Component Breakdown

### 1. Root Configuration (`config.yaml`)

```yaml
adapter:
  tracked_files:
    - events.jsonl          # ← Capture this output file
  type: cli                 # ← CLI adapter (runs commands)

category: scheduling        # Problem classification
checkpoints:                # List of milestones
  - checkpoint_1
  - checkpoint_2
  - checkpoint_3
  - checkpoint_4

description: 'CLI backup scheduler...'
difficulty: Medium

entry_file: backup_scheduler    # ← Python module to execute

loader_script: loader.py
loader_entrypoint: Loader

name: file_backup           # ← Must match directory name

static_assets:              # ← Mount files/ directory
  files:
    path: files

checkpoints:
  checkpoint_1:
    order: 1
    path: checkpoint_1
    groups:
      core:
        type: Core
        timeout: 20
    specification: spec.md
    state: Core Tests
  checkpoint_2:
    order: 2
    path: checkpoint_2
    groups:
      core:
        type: Core
      errors:
        type: Error
    specification: spec.md
    state: Core Tests
  checkpoint_3:
    order: 3
    path: checkpoint_3
    groups:
      core:
        type: Core
      regression:
        type: Regression
    specification: spec.md
    state: Full Tests
  checkpoint_4:
    order: 4
    path: checkpoint_4
    groups:
      functionality:
        type: Functionality
    specification: spec.md
    state: Verified

tags:
  - cli
  - scheduling
  - jsonl
  - yaml

timeout: 20                 # Default timeout for all tests
version: 1
```

**Key decisions:**

1. **`tracked_files: [events.jsonl]`**
   - The CLI writes events to `events.jsonl`
   - Adapter captures this file after execution
   - Verifier compares captured file against expected output

2. **`static_assets`**
   - The `files/` directory contains test data (Python/HTML/markdown files)
   - Mounted into test environment
   - Test cases reference as `{{static:files}}/A/I.py`

3. **`entry_file: backup_scheduler`**
   - Agents must create `backup_scheduler.py` module
   - Framework runs: `python -m backup_scheduler <args>`

### 2. Checkpoint 1 Entry

Located in `config.yaml → checkpoints.checkpoint_1`

```yaml
checkpoints:
  checkpoint_1:
    order: 1
    path: checkpoint_1
    groups:
      core:                 # ← Happy path tests
        timeout: 20
        type: Core
      errors:               # ← Error handling tests
        timeout: 20
        type: Error
    specification: spec.md  # ← Instructions for agents
    state: Core Tests
    timeout: 20
    version: 1
```

**Key decisions:**

1. **Two groups**: `core` and `errors`
   - `core`: Valid inputs, expected to succeed (exit code 0)
   - `errors`: Invalid inputs, expected to fail (exit code 3 or 4)

2. **No `case_order`**: Not needed for CLI (unlike stateful APIs)
   - Tests are independent
   - Can run in any order

### 3. Specification (`checkpoint_1/spec.md`)

```markdown
Build a single-run, CLI-driven backup scheduler that parses a YAML file,
decides which jobs are due "now", runs it, applies exclusion rules, and
emits event history as JSON Lines.

# Deliverables

Extend `backup_scheduler.py` that reads a YAML schedule, evaluates what
is due at a specified time, simulates running those jobs, and writes an
event history as JSON Lines.

**Command-line interface:**

- `--schedule <path>`: Path to YAML schedule file.
- `--now <iso8601>`: Wall clock used for scheduling decisions.
- `--duration <hours>`: Duration to simulate for in hours.
- `--mount`: Path to the location where files are mounted.

**Exit codes:**

- `0` success; `3` YAML parse error; `4` schema error

**Error printing (non-zero exit only):**

- Print exactly one line to stderr:
  ```
  ERROR:<CODE>:<human-readable message>
  ```
...
```

**Key decisions:**

1. **Clear interface specification**
   - Exact CLI arguments
   - Exit codes for different errors
   - Output format (JSONL)

2. **Error handling requirements**
   - Specific error codes (3 = parse error, 4 = schema error)
   - Structured stderr format

3. **Placeholder syntax**
   - `%%%ENTRYPOINT:entry_file%%%` → `backup_scheduler`
   - Dynamically replaced during evaluation

### 4. Test Case Structure (Core Group)

#### Example: `daily_due_simple/`

```
checkpoint_1/core/daily_due_simple/
├── case.yaml           # Input definition
└── expected.jsonl      # Expected output
```

**`case.yaml`:**
```yaml
arguments: --schedule schedule.yaml --now 2025-09-10T03:30:00Z --duration 24 --mount {{static:files}}

input_files:
  - path: schedule.yaml
    file_type: yaml
    content: |
      version: 1
      timezone: "UTC"
      jobs:
        - id: "daily-home"
          enabled: true
          when:
            kind: "daily"
            at: "03:30"
          source: mount://
          exclude: []
```

**Key elements:**

1. **`arguments`**: CLI arguments passed to `backup_scheduler.py`
   - `{{static:files}}` → Replaced with mounted files path

2. **`input_files`**: Files created in workspace before execution
   - `schedule.yaml` written with specified content
   - Agent's code reads this file

**`expected.jsonl`:**
```jsonl
{"event":"job_start","job_id":"daily-home","timestamp":"2025-09-10T03:30:00+00:00"}
{"event":"file_backed_up","job_id":"daily-home","file":"A/B/C/D.py","timestamp":"2025-09-10T03:30:00+00:00"}
{"event":"file_backed_up","job_id":"daily-home","file":"A/I.py","timestamp":"2025-09-10T03:30:00+00:00"}
{"event":"job_end","job_id":"daily-home","timestamp":"2025-09-10T03:30:00+00:00"}
```

**Key elements:**

- Each line is a JSON object (JSONL format)
- Events describe what the backup scheduler did
- Verifier compares actual output against this line-by-line

#### Example: Error Case (`error_yaml_parse/`)

```
checkpoint_1/errors/error_yaml_parse/
├── case.yaml
└── expected.yaml       # ← YAML for error cases
```

**`case.yaml`:**
```yaml
arguments: --schedule bad.yaml --now 2025-09-10T03:30:00Z

input_files:
  - path: bad.yaml
    file_type: yaml
    content: |
      invalid yaml {{{
```

**`expected.yaml`:**
```yaml
status_code: 3
stderr: "ERROR:E_PARSE:.*"    # Regex pattern
```

**Key decisions:**

1. **YAML format for errors**: Easier to specify status codes and patterns
2. **Regex matching**: `stderr` pattern allows flexible message matching
3. **Different exit code**: 3 = parse error (per spec)

### 5. Loader Implementation (`loader.py`)

The loader discovers test cases and creates Case/Expected objects.

**Core logic (simplified):**

```python
class Loader(BaseLoader):
    def __call__(self, group: GroupConfig, store: CaseStore):
        group_dir = helpers.get_group_path(group, self.problem, self.checkpoint)

        # Find all case directories
        for case_dir in helpers.discover_dir_cases(group, group_dir):
            case, expected = self.load_case(case_dir, group)
            yield case, expected

    def load_case(self, case_dir: Path, group: GroupConfig):
        # Read case.yaml
        with (case_dir / "case.yaml").open() as f:
            case_yaml = yaml.safe_load(f)

        # Create CLICase (what to execute)
        case = CLICase(
            id=case_dir.name,
            group=group.name,
            checkpoint=self.checkpoint.name,
            arguments=shlex.split(case_yaml["arguments"]),
            input_files=[
                InputFile.model_validate(f)
                for f in case_yaml.get("input_files", [])
            ],
        )

        # Create Expected (what should be produced)
        if (case_dir / "expected.jsonl").exists():
            with (case_dir / "expected.jsonl").open() as f:
                expected_output = [json.loads(line) for line in f]
        else:
            # Error case with expected.yaml
            with (case_dir / "expected.yaml").open() as f:
                expected_yaml = yaml.safe_load(f)
            expected_output = expected_yaml

        expected = CLIResult(
            id=case_dir.name,
            group=group.name,
            output=expected_output,
            status_code=expected_yaml.get("status_code", 0),
            stderr=expected_yaml.get("stderr", ""),
        )

        return case, expected
```

**What it does:**

1. **Discovers cases**: Finds all directories in `core/` or `errors/`
2. **Reads `case.yaml`**: Extracts CLI arguments and input files
3. **Reads expected output**: Either JSONL (success) or YAML (error)
4. **Creates objects**: `CLICase` and `CLIResult` for the runner

**Why directory-based:**
- Each test case can have multiple input files
- Clear separation between test cases
- Easy to add new cases (just create a new directory)

### 6. Verifier Implementation (`verifier.py`)

The verifier compares actual outputs against expected results.

**Core logic:**

```python
class Verifier:
    def __call__(self, group_name, case_name, actual, expected):
        # Always verify exit code
        status_code = verifiers.matches_status_code(
            actual.status_code,
            expected.status_code,
            weight=0.1
        )

        # For error cases, verify stderr
        if expected.status_code != 0:
            return {
                "status_code": status_code,
                "stderr": verifiers.matches_regex(
                    actual.stderr,
                    expected.stderr,
                    weight=0.9
                ),
            }

        # For success cases, verify JSONL output
        return {
            "status_code": status_code,
            "output": self.verify_stdout(actual, expected),
        }

    def verify_stdout(self, actual, expected):
        # Parse JSONL from actual output
        stdout = parsers.parse_jsonl(actual.output)

        # Deep comparison
        return verifiers.deepdiff_verify(
            stdout,
            expected.output,
            weight=0.9
        )
```

**Key decisions:**

1. **Weight distribution**:
   - Exit code: 10% (must match, but simple)
   - Output/stderr: 90% (complex, most important)

2. **Use framework helpers**:
   - `verifiers.matches_status_code()`: Simple integer comparison
   - `verifiers.matches_regex()`: Regex matching for stderr
   - `verifiers.deepdiff_verify()`: Deep comparison of data structures

3. **Different paths for errors vs success**:
   - Errors: Check stderr matches pattern
   - Success: Check JSONL output matches expected

## Execution Flow

### Test Execution Sequence

```
1. Runner creates execution environment (Docker container)
   ↓
2. Mounts static assets (files/ directory)
   ↓
3. Loader discovers test case "daily_due_simple"
   ↓
4. Loader reads case.yaml
   ↓
5. Runner creates workspace with input files
   ├── schedule.yaml (from case.yaml)
   └── [agent's code]
   ↓
6. Runner executes: python -m backup_scheduler --schedule schedule.yaml ...
   ↓
7. Agent's code runs, writes events.jsonl
   ↓
8. Runner captures tracked files (events.jsonl)
   ↓
9. Verifier compares actual events.jsonl vs expected.jsonl
   ↓
10. Verification result: {output: 0.9, status_code: 0.1} = 1.0 (perfect score)
```

### Example Execution

**Input (case.yaml):**
```yaml
arguments: --schedule schedule.yaml --now 2025-09-10T03:30:00Z
input_files:
  - path: schedule.yaml
    content: |
      jobs:
        - id: daily-backup
          when: {kind: daily, at: "03:30"}
```

**Agent's code creates:**
```jsonl
{"event":"job_start","job_id":"daily-backup","timestamp":"2025-09-10T03:30:00+00:00"}
{"event":"job_end","job_id":"daily-backup","timestamp":"2025-09-10T03:30:00+00:00"}
```

**Expected:**
```jsonl
{"event":"job_start","job_id":"daily-backup","timestamp":"2025-09-10T03:30:00+00:00"}
{"event":"job_end","job_id":"daily-backup","timestamp":"2025-09-10T03:30:00+00:00"}
```

**Verification:**
- Parse both as JSONL (list of dicts)
- Deep compare: Perfect match!
- Score: 1.0

## Design Patterns

### Pattern 1: Directory-Based Test Cases

**Why:**
- Each test needs multiple input files (schedule.yaml, etc.)
- Clear separation between tests
- Easy to add new tests

**Alternative (not used):**
- File-based: All data in one YAML file
- Better for simple tests with minimal inputs

### Pattern 2: Separate Core and Error Groups

**Why:**
- Different verification logic (stdout vs stderr)
- Clear separation of concerns
- Different expectations (exit 0 vs exit 3/4)

**Benefits:**
- Easy to see test coverage (N success cases, M error cases)
- Can run groups independently

### Pattern 3: Static Assets for Test Data

**Why:**
- Real filesystem structure (directories, files)
- Reused across multiple test cases
- Simulates production environment

**Alternative (not used):**
- Generate files per test case
- More verbose case definitions

### Pattern 4: Framework Helpers for Verification

**Why:**
- Consistent scoring across problems
- Detailed diff output for debugging
- Less code to maintain

**Example helpers used:**
- `parsers.parse_jsonl()`: Safely parse JSONL
- `verifiers.deepdiff_verify()`: Deep comparison with detailed diffs
- `verifiers.matches_regex()`: Flexible error message matching

## Checkpoint Progression

### Checkpoint 1: Basic Scheduling
- Parse YAML schedules
- Determine due jobs
- Emit JSONL events
- **Complexity**: Basic parsing + time logic

### Checkpoint 2: Execution Modes
- Add `--mode full|verify|pack`
- Different backup strategies
- **Complexity**: Multiple code paths

### Checkpoint 3: Verification Mode
- Read existing backups
- Verify file integrity
- **Complexity**: Checksum calculation

### Checkpoint 4: Incremental Backup
- Track what was previously backed up
- Only backup changed files
- **Complexity**: State management

**Pattern**: Each checkpoint builds on the previous one.

## Common Pitfalls and Solutions

### Pitfall 1: Hardcoded Paths in Expected Output

**Problem:**
```jsonl
{"file": "/tmp/workspace/files/A/I.py"}
```

**Solution**: Use relative paths or placeholders
```jsonl
{"file": "A/I.py"}
```

### Pitfall 2: Timestamp Precision Mismatches

**Problem**: Agent outputs `2025-09-10T03:30:00.123Z`, expected `2025-09-10T03:30:00Z`

**Solution**:
- Normalize timestamps in verifier
- Or use regex patterns for flexible matching

### Pitfall 3: Case Directory Names Not Descriptive

**Bad:**
```
core/test1/
core/test2/
```

**Good:**
```
core/daily_due_simple/
core/weekly_not_due/
```

### Pitfall 4: Not Using Framework Helpers

**Bad:**
```python
def verify_output(actual, expected):
    return 1.0 if actual == expected else 0.0  # Too simple!
```

**Good:**
```python
def verify_output(actual, expected):
    return verifiers.deepdiff_verify(actual, expected, weight=0.9)
    # Returns detailed diff information
```

## Testing Your Problem

### 1. Run Agent

```bash
slop-code run \
  --agent configs/agents/haiku-4.5-claude-code.yaml \
  --environment configs/environments/docker-python3.12-uv.yaml \
  --prompt configs/prompts/simple.jinja \
  --problem file_backup
```

### 2. Evaluate Results

```bash
uv run python -m slop_code.entrypoints.cli eval \
  outputs/agent_run_dir \
  --pass-policy all-cases
```

Replace `agent_run_dir` with the actual output directory created by the run command (e.g., `outputs/claude_code_sonnet-4.5_docker-python3.12-uv_simple/20250115T1234_claude_code/`).

### 3. View in Dashboard

```bash
uv run python -m slop_code.visualization.app outputs/
```

## Summary

**Key takeaways:**

1. **Directory structure follows conventions**
   - Root config, checkpoint configs, test cases
   - Clear hierarchy: Problem → Checkpoint → Group → Case

2. **Loader and verifier are simple**
   - Loader: ~100 lines (mostly helper calls)
   - Verifier: ~50 lines (mostly helper calls)

3. **Framework helpers do the heavy lifting**
   - `helpers.discover_dir_cases()`: Find test cases
   - `verifiers.deepdiff_verify()`: Compare complex data
   - `parsers.parse_jsonl()`: Safe parsing

4. **Design for clarity**
   - Descriptive directory names
   - Separate success/error tests
   - Progressive checkpoint complexity

5. **Static assets simplify tests**
   - Reuse files across tests
   - Realistic filesystem structure

## Next Steps

- **[Stateful API Example](stateful-api.md)** - See how APIs differ
- **[Config Schema](../config-schema.md)** - Field reference
- **[Test Cases Guide](../test-cases.md)** - Best practices
- **[Creating Loaders and Verifiers](../../guides/creating-loaders-and-verifiers.md)** - Detailed patterns
