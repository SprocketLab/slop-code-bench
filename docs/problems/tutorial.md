---
version: 1.0
last_updated: 2025-11-06
---

# Tutorial: Create Your First Problem

This tutorial walks you through creating a complete evaluation problem from scratch. Follow along and you'll have a working problem in 30 minutes.

## What We're Building

**Problem**: A CLI tool that counts words in text files

**Features:**
- Read text file
- Count words (space-separated)
- Output JSON with counts
- Handle errors (file not found)

**Why this problem**: Simple enough to complete quickly, but demonstrates all key concepts.

## Prerequisites

- Slop Code repository cloned
- Python environment set up (`uv sync`)
- Basic understanding of Python and CLI tools

## Step 1: Create Directory Structure (2 minutes)

### Create Problem Directory

```bash
# From repository root
mkdir -p problems/word_counter/checkpoint_1/core
mkdir -p problems/word_counter/checkpoint_1/errors
```

**What we created:**
```
problems/word_counter/               # Problem root
└── checkpoint_1/                    # First milestone
    ├── core/                        # Success test cases
    └── errors/                      # Error test cases
```

### Verify Structure

```bash
ls -R problems/word_counter/
```

You should see:
```
problems/word_counter/:
checkpoint_1

problems/word_counter/checkpoint_1:
core  errors
```

## Step 2: Write Root Configuration (3 minutes)

Create `problems/word_counter/config.yaml`:

```bash
cat > problems/word_counter/config.yaml << 'EOF'
name: word_counter
description: CLI tool that counts words in text files
category: text-processing
difficulty: Easy
version: 1

adapter:
  type: cli
  tracked_files:
    - output.json

entry_file: word_counter
loader_script: loader.py
loader_entrypoint: Loader

checkpoints:
  checkpoint_1:
    order: 1
    path: checkpoint_1
    groups:
      core:
        type: Core
        timeout: 10
      errors:
        type: Error
        timeout: 10
    specification: spec.md
    state: Core Tests
    timeout: 10
    version: 1

tags:
  - cli
  - text-processing

timeout: 10
EOF
```

**What each field means:**

- `name: word_counter` - Must match directory name
- `adapter.type: cli` - We're testing a CLI tool
- `tracked_files: [output.json]` - Capture this output file
- `entry_file: word_counter` - Agent creates `word_counter.py`
- `checkpoints.checkpoint_1` - Inline checkpoint entry (order, path, groups, spec)

**Verify it's valid:**

```bash
python -c "import yaml; yaml.safe_load(open('problems/word_counter/config.yaml'))"
# No output = valid YAML
```

## Step 3: Review the Checkpoint Entry (1 minute)

The `checkpoints.checkpoint_1` block inside `config.yaml` replaces the old
`checkpoint_1/config.yaml` file. It already declares:

- Two groups: `core` (success) and `errors` (failures)
- 10 second timeout per test
- Spec filename `spec.md`

Make sure the directory referenced by `path` exists (created in Step 1):

```bash
ls problems/word_counter/checkpoint_1
```

You should see the directories you scaffold next for specs and cases.

## Step 4: Write Specification (5 minutes)

Create `problems/word_counter/checkpoint_1/spec.md`:

```bash
cat > problems/word_counter/checkpoint_1/spec.md << 'EOF'
# Checkpoint 1: Word Counter

Build a CLI tool that counts words in a text file.

## Deliverables

Create a `%%%ENTRYPOINT:entry_file%%%` that:

1. Accepts a text file path as input
2. Counts the number of words (space-separated)
3. Outputs the count as JSON

## Command-Line Interface
Invoked via: `%%%ENTRYPOINT:entry_command%%%`

**Arguments:**
- `--input`: Path to input text file
- `--output`: Path to output JSON file

## Output Format

Write a JSON file with this structure:

`{  "word_count": 42, "file": "input.txt"}`

## Error Handling

**Exit codes:**
- `0` - Success
- `1` - File not found

**Error output:**
- Print error message to stderr
- Exit with code 1

## Notes

- Words are separated by spaces
- Empty files have 0 words
- Only count non-empty words
EOF
```
**What we specified:**

- Clear CLI interface (`--input`, `--output`)
- Output format (JSON structure)
- Error handling (exit codes, stderr)
- Examples (always helpful!)

## Step 5: Create Test Cases (8 minutes)

### Test Case 1: Simple Word Count

```bash
mkdir -p problems/word_counter/checkpoint_1/core/simple_count

cat > problems/word_counter/checkpoint_1/core/simple_count/case.yaml << 'EOF'
arguments: --input hello.txt --output output.json

input_files:
  - path: hello.txt
    file_type: txt
    content: |
      Hello world
EOF

cat > problems/word_counter/checkpoint_1/core/simple_count/expected.json << 'EOF'
{
  "word_count": 2,
  "file": "hello.txt"
}
EOF
```

**What we created:**
- CLI arguments: `--input hello.txt --output output.json`
- Input file with "Hello world" (2 words)
- Expected output: `word_count: 2`

### Test Case 2: Multiple Words

```bash
mkdir -p problems/word_counter/checkpoint_1/core/multiple_words

cat > problems/word_counter/checkpoint_1/core/multiple_words/case.yaml << 'EOF'
arguments: --input text.txt --output output.json

input_files:
  - path: text.txt
    file_type: txt
    content: |
      The quick brown fox jumps over the lazy dog
EOF

cat > problems/word_counter/checkpoint_1/core/multiple_words/expected.json << 'EOF'
{
  "word_count": 9,
  "file": "text.txt"
}
EOF
```

### Test Case 3: Empty File

```bash
mkdir -p problems/word_counter/checkpoint_1/core/empty_file

cat > problems/word_counter/checkpoint_1/core/empty_file/case.yaml << 'EOF'
arguments: --input empty.txt --output output.json

input_files:
  - path: empty.txt
    file_type: txt
    content: ""
EOF

cat > problems/word_counter/checkpoint_1/core/empty_file/expected.json << 'EOF'
{
  "word_count": 0,
  "file": "empty.txt"
}
EOF
```

### Test Case 4: Error - File Not Found

```bash
mkdir -p problems/word_counter/checkpoint_1/errors/file_not_found

cat > problems/word_counter/checkpoint_1/errors/file_not_found/case.yaml << 'EOF'
arguments: --input missing.txt --output output.json

input_files: []
EOF

cat > problems/word_counter/checkpoint_1/errors/file_not_found/expected.yaml << 'EOF'
status_code: 1
stderr: ".*not found.*"
EOF
```

**Note**: Error cases use `expected.yaml` (not JSON) to specify status code and stderr pattern.

### Verify Test Cases

```bash
find problems/word_counter/checkpoint_1 -name "case.yaml" -o -name "expected.*"
```

You should see 4 case files and 4 expected files.

## Step 6: Write Loader (5 minutes)

Create `problems/word_counter/loader.py`:

```bash
cat > problems/word_counter/loader.py << 'EOF'
"""Loader for word_counter problem."""

from pathlib import Path
import yaml
import json

from slop_code.evaluation import GroupConfig
from slop_code.evaluation.adapters import CLICase, CLIResult
from slop_code.evaluation.loaders import BaseLoader, CaseStore, helpers
from slop_code.execution.file_ops import InputFile


class Loader(BaseLoader):
    """Load test cases for word_counter problem."""

    def __call__(self, group: GroupConfig, store: CaseStore):
        """Load all test cases in a group."""
        group_dir = helpers.get_group_path(group, self.problem, self.checkpoint)

        # Find all case directories
        for case_dir in helpers.discover_dir_cases(group, group_dir):
            case, expected = self.load_case(case_dir, group)
            yield case, expected

    def load_case(self, case_dir: Path, group: GroupConfig):
        """Load a single test case."""
        # Read case.yaml
        case_yaml = yaml.safe_load((case_dir / "case.yaml").read_text())

        # Create CLICase
        case = CLICase(
            id=case_dir.name,
            group=group.name,
            group_type=group.type,
            checkpoint=self.checkpoint.name,
            arguments=case_yaml["arguments"].split(),
            input_files=[
                InputFile.model_validate(f)
                for f in case_yaml.get("input_files", [])
            ],
        )

        # Load expected output
        if (case_dir / "expected.json").exists():
            # Success case: JSON output
            expected_output = json.loads((case_dir / "expected.json").read_text())
            status_code = 0
            stderr = ""
        else:
            # Error case: YAML with status_code and stderr
            expected_yaml = yaml.safe_load((case_dir / "expected.yaml").read_text())
            expected_output = {}
            status_code = expected_yaml.get("status_code", 0)
            stderr = expected_yaml.get("stderr", "")

        expected = CLIResult(
            id=case_dir.name,
            group=group.name,
            group_type=group.type,
            status_code=status_code,
            output=expected_output,
            stderr=stderr,
        )

        return case, expected
EOF
```

**What the loader does:**

1. Finds all case directories in the group
2. Reads `case.yaml` for arguments and input files
3. Reads `expected.json` (success) or `expected.yaml` (error)
4. Returns `(CLICase, CLIResult)` tuples

**Test the loader:**

```bash
# Ensure repository root is in PYTHONPATH
export PYTHONPATH=$PYTHONPATH:.
python -c "
from pathlib import Path
from problems.word_counter.loader import Loader
from slop_code.evaluation import ProblemConfig

problem = ProblemConfig.from_yaml(Path('problems/word_counter'))
checkpoint = problem.load_checkpoint('checkpoint_1')

loader = Loader(problem, checkpoint)
store = loader.initialize_store()

for group in checkpoint.groups.values():
    print(f'Group: {group.name}')
    for case, expected in loader(group, store):
        print(f'  - {case.id}')
"
```

You should see:
```
Group: core
  - empty_file
  - multiple_words
  - simple_count
Group: errors
  - file_not_found
```

## Step 7: Write Verifier (4 minutes)

Create `problems/word_counter/verifier.py`:

```bash
cat > problems/word_counter/verifier.py << 'EOF'
"""Verifier for word_counter problem."""

from slop_code.evaluation import CheckpointConfig
from slop_code.evaluation.adapters import CLIResult
from slop_code.evaluation.verifiers import verifiers, parsers


class Verifier:
    """Verify word_counter outputs."""

    def __init__(self, checkpoint_config: CheckpointConfig):
        self.checkpoint_config = checkpoint_config

    def __call__(
        self,
        group_name: str,
        case_name: str,
        actual: CLIResult,
        expected: CLIResult,
    ):
        """Verify a test case."""
        # Always check status code
        results = {
            "status_code": verifiers.matches_status_code(
                actual.status_code,
                expected.status_code,
                weight=0.2
            )
        }

        # For error cases, check stderr
        if expected.status_code != 0:
            results["stderr"] = verifiers.matches_regex(
                actual.stderr,
                expected.stderr,
                lstrip=True,
                weight=0.8
            )
            return results

        # For success cases, check output.json
        output_file = actual.files.get("output.json")
        if not output_file:
            results["output"] = verifiers.VerificationResult(
                score=0.0,
                weight=0.8,
                message="output.json not found"
            )
            return results

        # Parse actual output
        actual_output = parsers.parse_json(output_file.content)

        # Compare with expected
        results["output"] = verifiers.deepdiff_verify(
            actual_output,
            expected.output,
            weight=0.8
        )

        return results
EOF
```

**What the verifier does:**

1. Checks status code (20% weight)
2. For errors: Checks stderr matches pattern (80% weight)
3. For success: Parses `output.json` and compares with expected (80% weight)

**Test the verifier:**

```bash
# Ensure repository root is in PYTHONPATH
export PYTHONPATH=$PYTHONPATH:.
python -c "
from pathlib import Path
from problems.word_counter.verifier import Verifier
from slop_code.evaluation import ProblemConfig
from slop_code.evaluation.adapters import CLIResult, FileContent

problem = ProblemConfig.from_yaml(Path('problems/word_counter'))
checkpoint = problem.load_checkpoint('checkpoint_1')

verifier = Verifier(checkpoint)

# Test success case
actual = CLIResult(
    id='test',
    group='core',
    status_code=0,
    files={'output.json': FileContent(
        path='output.json',
        content='{\"word_count\": 2, \"file\": \"hello.txt\"}'
    )}
)
expected = CLIResult(
    id='test',
    group='core',
    status_code=0,
    output={'word_count': 2, 'file': 'hello.txt'}
)

results = verifier('core', 'test', actual, expected)
print('Success case results:')
for key, result in results.items():
    print(f'  {key}: {result.score}')
"
```

You should see:
```
Success case results:
  status_code: 1.0
  output: 1.0
```

## Step 8: Create Reference Solution (Optional but Recommended)

Create `problems/word_counter/solution/word_counter.py`:

```bash
mkdir -p problems/word_counter/solution

cat > problems/word_counter/solution/word_counter.py << 'EOF'
#!/usr/bin/env python3
"""Word counter CLI tool."""

import argparse
import json
import sys
from pathlib import Path


def count_words(file_path: Path) -> int:
    """Count words in a file."""
    text = file_path.read_text()
    words = text.split()
    return len(words)


def main():
    parser = argparse.ArgumentParser(description="Count words in a file")
    parser.add_argument("--input", required=True, help="Input file path")
    parser.add_argument("--output", required=True, help="Output JSON path")
    args = parser.parse_args()

    input_path = Path(args.input)

    # Check if file exists
    if not input_path.exists():
        print(f"Error: File {args.input} not found", file=sys.stderr)
        sys.exit(1)

    # Count words
    word_count = count_words(input_path)

    # Write output
    output = {
        "word_count": word_count,
        "file": args.input
    }

    output_path = Path(args.output)
    output_path.write_text(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
EOF

chmod +x problems/word_counter/solution/word_counter.py
```

**Why create a reference solution:**
- Verify your test cases are correct
- Test the loader and verifier
- Provide example for debugging

**Test the solution manually:**

```bash
cd problems/word_counter/solution

# Create test file
echo "Hello world from the tutorial" > test.txt

# Run solution
python word_counter.py --input test.txt --output output.json

# Check output
cat output.json
# Should show: {"word_count": 5, "file": "test.txt"}

cd ../../..
```

## Step 9: Validate Your Problem (3 minutes)

### Check Directory Structure

```bash
tree problems/word_counter -I '__pycache__|*.pyc'
```

Expected structure:
```
problems/word_counter
├── config.yaml
├── loader.py
├── verifier.py
├── checkpoint_1
│   ├── spec.md
│   ├── core
│   │   ├── empty_file
│   │   │   ├── case.yaml
│   │   │   └── expected.json
│   │   ├── multiple_words
│   │   │   ├── case.yaml
│   │   │   └── expected.json
│   │   └── simple_count
│   │       ├── case.yaml
│   │       └── expected.json
│   └── errors
│       └── file_not_found
│           ├── case.yaml
│           └── expected.yaml
└── solution
    └── word_counter.py
```

### Validate YAML Files

```bash
find problems/word_counter -name "*.yaml" | while read f; do
    echo "Checking $f..."
    python -c "import yaml; yaml.safe_load(open('$f'))" || echo "FAILED: $f"
done
```

All files should pass.

### Test Loader Loads All Cases

```bash
# Ensure repository root is in PYTHONPATH
export PYTHONPATH=$PYTHONPATH:.
python -c "
from pathlib import Path
from problems.word_counter.loader import Loader
from slop_code.evaluation import ProblemConfig

problem = ProblemConfig.from_yaml(Path('problems/word_counter'))
checkpoint = problem.load_checkpoint('checkpoint_1')

loader = Loader(problem, checkpoint)
store = loader.initialize_store()

total_cases = 0
for group in checkpoint.groups.values():
    for case, expected in loader(group, store):
        total_cases += 1

print(f'Loaded {total_cases} test cases')
assert total_cases == 4, f'Expected 4 cases, got {total_cases}'
print('✓ All test cases loaded successfully')
"
```

## Step 10: Test with Reference Solution (5 minutes)

### Run Evaluation on Your Solution

```bash
# Create output directory
mkdir -p outputs/word_counter_test

# Evaluate your solution against a snapshot
uv run python -m slop_code.entrypoints.cli eval-snapshot \
  --problem-name word_counter \
  --checkpoint-num 1 \
  --env-config configs/environments/local.yaml \
  --save-dir outputs/word_counter_test \
  problems/word_counter/solution
```

**Expected output:**
```
Checkpoint 1: 4/4 tests passed (100%)
  core: 3/3 passed
  errors: 1/1 passed
```

If you see this, **congratulations!** Your problem works correctly.

### Debug Failures

If tests fail:

**Check which test failed:**
```bash
# The output shows which tests failed
# Example: "core/simple_count: FAILED"
```

**Debug the specific test:**
```bash
# Run just that test manually
cd /tmp/test_workspace
echo "Hello world" > hello.txt

# Run your solution
python -m word_counter --input hello.txt --output output.json

# Check output
cat output.json
```

**Common issues:**
- Wrong output format (verify JSON structure)
- Wrong file path (check `tracked_files` in config)
- Wrong status code (check error cases exit with 1)

## Step 11: Run an Agent on Your Problem (Optional)

Now test if an agent can solve it:

```bash
slop-code run \
  --agent configs/agents/haiku-4.5-claude-code.yaml \
  --environment configs/environments/docker-python3.12-uv.yaml \
  --prompt configs/prompts/simple.jinja \
  --problem word_counter \
  --num-workers 1
```

This will:
1. Give the agent your `spec.md`
2. Let it write `word_counter.py`
3. Run your test cases against its solution
4. Show results

**Evaluate agent's solution:**
```bash
uv run python -m slop_code.entrypoints.cli eval \
  outputs/[run-directory]
```

Replace `[run-directory]` with the actual agent run directory path.

## Success Checklist

Your problem is complete when:

- [ ] **Structure**: All directories and files exist
- [ ] **Config**: Root and checkpoint configs are valid YAML
- [ ] **Spec**: Clear requirements and examples
- [ ] **Test Cases**: At least 3 success cases, 1 error case
- [ ] **Loader**: Loads all test cases without errors
- [ ] **Verifier**: Returns scores for all cases
- [ ] **Reference Solution**: Passes all tests (100%)
- [ ] **Agent Test**: (Optional) Agent can solve it

## What You Learned

Congratulations! You've created a complete evaluation problem. You now understand:

1. **Problem structure** - Directories, configs, test cases
2. **Configuration** - Root config, checkpoint config, adapter settings
3. **Specification** - How to write clear requirements for agents
4. **Test cases** - Success cases (core) and error cases (errors)
5. **Loader** - How to discover and parse test cases
6. **Verifier** - How to compare actual vs expected outputs
7. **Validation** - How to test your problem works correctly

## Next Steps

### Add More Test Cases

```bash
# Add edge cases
mkdir -p problems/word_counter/checkpoint_1/core/multiple_spaces
mkdir -p problems/word_counter/checkpoint_1/core/long_text

# Add more error cases
mkdir -p problems/word_counter/checkpoint_1/errors/invalid_argument
```

### Add a Second Checkpoint

```bash
# Create checkpoint_2
mkdir -p problems/word_counter/checkpoint_2/core

# Update root config
# Add "- checkpoint_2" to checkpoints list

# Write checkpoint_2/spec.md
# Extend the tool with character counting
```

### Improve Your Problem

- Add more realistic test cases
- Test with different text formats
- Add optional features (--verbose flag)
- Create hidden test cases
- Add performance tests

## Common Issues and Solutions

### "No module named 'word_counter'"

**Fix**: Ensure you're running from the correct directory with the right Python path.

### "File output.json not found"

**Fix**: Check `tracked_files` in root config matches what your solution outputs.

### "All tests fail with score 0.0"

**Fix**: Check verifier is reading the correct file:
```python
output_file = actual.files.get("output.json")  # Must match tracked_files
```

### "Loader yields no cases"

**Fix**: Ensure case directories exist and contain `case.yaml`.

## Further Reading

- **[Quick Reference](quick-reference.md)** - Templates and commands
- **[Config Schema](config-schema.md)** - Complete field reference
- **[Test Cases Guide](test-cases.md)** - Best practices
- **[Simple CLI Example](examples/simple-cli.md)** - More complex CLI example
- **[Troubleshooting](troubleshooting.md)** - Debug common issues

## Feedback

If you found this tutorial helpful or have suggestions for improvement, please let us know!

---

**You did it!** 🎉

You've created your first evaluation problem. Now you can create problems to test any CLI tool, API, or web application you can imagine.
