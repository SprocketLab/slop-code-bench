---
version: 1.3
last_updated: 2025-12-10
---

# Verification Guide

This guide covers how to implement custom verification logic to validate submission results against expected outcomes.

## Overview

Verifiers compare actual execution results (`CaseResult` from adapters) with expected values (from test case definitions) and produce detailed validation reports with scoring.

## Verifier Protocol

All verifiers must implement this interface:

```python
@runtime_checkable
class VerifierProtocol(Protocol):
    def __init__(
        self,
        checkpoint_config: CheckpointConfig,
    ): ...

    def __call__(
        self,
        group_name: str,
        case_name: str,
        actual: CaseResult,
        expected: CaseResult,
    ) -> VerifierReturnType:
        """Execute verification and return per-attribute results."""
        ...
```

The verifier receives:
- `actual`: Raw execution result from the adapter (CaseResult)
- `expected`: Expected result values as a CaseResult
- Returns: Dictionary mapping attribute names to VerificationResult objects

Keys must be either:
- An attribute on the CaseResult (e.g., "output", "status_code")
- A file verification in the form "files-<filename>"

## Core Data Structures

### VerificationResult

Represents the verification of a single attribute:

```python
class VerificationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    diff: JsonValue
    is_correct: bool
    weight: float = Field(default=1.0, gt=0.0)

    @classmethod
    def create(
        cls,
        diff: deepdiff.DeepDiff | JsonValue,
        is_correct: bool,
        weight: float = 1.0,
    ):
        """Create a VerificationResult from a diff and a weight."""
        diff_value = diff
        if isinstance(diff, deepdiff.DeepDiff):
            diff_value = json.loads(diff.to_json())
        return cls(diff=diff_value, is_correct=is_correct, weight=weight)
```

### VerifierReport

Aggregates all verification results for a case:

```python
class VerifierReport(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=True)
    id: str                                       # Case identifier
    group: str                                    # Group name
    type: GroupType                               # Group type enum
    timestamp: datetime = Field(default_factory=datetime.now)
    duration: float                               # Verification duration
    results: dict[str, AttributeResult]           # Attribute name -> result
    case: dict[str, JsonValue] = {}               # Case metadata for parquet
    original_checkpoint: str | None = None        # For regression cases
    original_group: str | None = None             # For regression cases

    def calculate_score(self) -> float:
        """Return the weighted average of verifier scores."""
        total_weight = 0
        weighted_sum = 0
        for v in self.results.values():
            if v.is_correct is None:
                continue
            total_weight += v.weight
            weighted_sum += v.is_correct * v.weight
        return weighted_sum / total_weight

    def did_pass(self) -> bool:
        """Return True if all verified attributes passed."""
        return all(
            v.is_correct for v in self.results.values() if v.is_correct is not None
        )

    def get_verified_attributes(self) -> Generator[AttributeResult, None, None]:
        """Yield only attributes that were actually verified (non-None)."""
        for result in self.results.values():
            if result.is_correct is not None:
                yield result

    def format_result(self) -> dict[str, str]:
        """Return dict mapping attribute names to 'P' (pass) or 'F' (fail)."""
        return {
            r.attribute: "P" if r.is_correct else "F"
            for r in self.get_verified_attributes()
        }

    # Serialization methods
    def to_parquet_row(self) -> dict: ...
    @classmethod
    def from_parquet_row(cls, row) -> VerifierReport: ...
    @classmethod
    def from_verifier_result(
        cls,
        case: BaseCase,
        duration: float,
        actual_result: CaseResult,
        expected_result: CaseResult,
        raw_results: dict[str, VerificationResult],
    ) -> VerifierReport: ...
```

### AttributeResult

Represents a single attribute verification:

```python
class AttributeResult(BaseModel):
    attribute: str                          # Name of the verified attribute
    actual: JsonValue                       # Actual value from execution
    expected: JsonValue                     # Expected value from test case
    diff: JsonValue = None                  # Difference information
    is_correct: bool | None = None          # Verification result (None = not verified)
    weight: float = Field(default=1.0, ge=0.0)  # Weight for scoring

    def to_parquet_safe(self) -> dict[str, JsonValue]:
        """Convert to parquet-serializable dict."""
        ...

    @classmethod
    def from_parquet_row(cls, row) -> AttributeResult:
        """Reconstruct from parquet row."""
        ...
```

### Type Aliases

```python
VerifierReturnType = dict[str, VerificationResult]
```

## Basic Verifier Example

### Simple Output Comparison

```python
# verifier.py
from slop_code.evaluation.verifiers.models import VerificationResult

class Verifier:
    """Basic verifier comparing output and status code."""

    def __init__(self, checkpoint_config):
        self.config = checkpoint_config

    def __call__(self, group_name, case_name, actual, expected):
        results = {}

        # Verify output
        expected_output = expected.output
        output_match = actual.output == expected_output
        results["output"] = VerificationResult.create(
            diff=self._output_diff(expected_output, actual.output),
            is_correct=output_match,
            weight=1.0
        )

        # Verify status code
        expected_status = expected.status_code
        status_match = actual.status_code == expected_status
        results["status_code"] = VerificationResult.create(
            diff=f"Expected: {expected_status}, Got: {actual.status_code}",
            is_correct=status_match,
            weight=0.5
        )

        return results

    def _output_diff(self, expected, actual):
        """Generate human-readable diff."""
        if expected == actual:
            return "✓ Output matches"

        # Simple line-by-line diff
        expected_lines = str(expected).splitlines()
        actual_lines = str(actual).splitlines()

        diff_lines = []
        for i, (exp, act) in enumerate(zip(expected_lines, actual_lines)):
            if exp != act:
                diff_lines.append(f"Line {i+1}:")
                diff_lines.append(f"  Expected: {exp}")
                diff_lines.append(f"  Actual:   {act}")

        if len(expected_lines) != len(actual_lines):
            diff_lines.append(f"Line count: expected {len(expected_lines)}, got {len(actual_lines)}")

        return "\n".join(diff_lines) if diff_lines else "✓ Output matches"
```

## Advanced Verification Examples

### Example 1: JSON Response Validation

```python
import json
from typing import Any, Dict

class JSONVerifier:
    """Verifies JSON responses with flexible matching."""

    def __init__(self, checkpoint_config):
        self.config = checkpoint_config

    def __call__(self, group_name, case_name, actual, expected):
        results = {}

        # Parse JSON
        try:
            actual_json = json.loads(actual.output)
        except json.JSONDecodeError as e:
            return {
                "json_parse": VerificationResult.create(
                    diff=f"Failed to parse JSON: {e}",
                    is_correct=False,
                    weight=1.0
                )
            }

        expected_json = expected.output if expected.output else {}

        # Verify structure
        results["structure"] = self._verify_structure(expected_json, actual_json)

        # Verify specific fields (if expected contains fields dict)
        expected_fields = getattr(expected, 'fields', {})
        for field, expected_value in expected_fields.items():
            results[f"field_{field}"] = self._verify_field(
                field, expected_value, actual_json
            )

        # Verify status code
        expected_status = expected.status_code
        results["status_code"] = VerificationResult.create(
            diff=f"Expected: {expected_status}, Got: {actual.status_code}",
            is_correct=actual.status_code == expected_status,
            weight=0.5
        )

        return results

    def _verify_structure(self, expected, actual):
        """Verify JSON structure matches."""
        expected_keys = set(expected.keys())
        actual_keys = set(actual.keys()) if isinstance(actual, dict) else set()

        missing = expected_keys - actual_keys
        extra = actual_keys - expected_keys

        if not missing and not extra:
            return VerificationResult.create(
                diff="✓ Structure matches",
                is_correct=True,
                weight=1.0
            )

        diff_parts = []
        if missing:
            diff_parts.append(f"Missing keys: {missing}")
        if extra:
            diff_parts.append(f"Extra keys: {extra}")

        return VerificationResult.create(
            diff="\n".join(diff_parts),
            is_correct=False,
            weight=1.0
        )

    def _verify_field(self, field, expected_value, actual_json):
        """Verify a specific field value."""
        # Navigate nested fields (e.g., "user.name")
        actual_value = self._get_nested(actual_json, field)

        if actual_value == expected_value:
            return VerificationResult.create(
                diff=f"✓ {field} = {expected_value}",
                is_correct=True,
                weight=1.0
            )

        return VerificationResult.create(
            diff=f"{field}: expected {expected_value}, got {actual_value}",
            is_correct=False,
            weight=1.0
        )

    def _get_nested(self, obj, path):
        """Get nested dictionary value by dot-separated path."""
        keys = path.split(".")
        value = obj
        for key in keys:
            if isinstance(value, dict):
                value = value.get(key)
            else:
                return None
        return value
```

### Example 2: File Content Verification

```python
import difflib
from pathlib import Path

class FileVerifier:
    """Verifies file outputs."""

    def __init__(self, checkpoint_config):
        self.config = checkpoint_config

    def __call__(self, group_name, case_name, actual, expected):
        results = {}

        # Check status code first
        expected_status = expected.status_code
        results["status_code"] = VerificationResult.create(
            diff=f"Exit code: {actual.status_code}",
            is_correct=actual.status_code == expected_status,
            weight=0.3
        )

        # Verify each expected file
        expected_files = getattr(expected, 'files', [])
        for file_spec in expected_files:
            file_path = file_spec["path"]
            results[f"files-{file_path}"] = self._verify_file(
                file_path,
                file_spec,
                actual.files
            )

        return results

    def _verify_file(self, path, spec, actual_files):
        """Verify a single file."""
        # Check file exists
        if path not in actual_files:
            return VerificationResult.create(
                diff=f"File not found: {path}",
                is_correct=False,
                weight=1.0
            )

        actual_content = actual_files[path]

        # Exact match
        if "content" in spec:
            expected_content = spec["content"]
            if actual_content == expected_content:
                return VerificationResult.create(
                    diff="✓ Content matches",
                    is_correct=True,
                    weight=1.0
                )

            # Generate diff
            diff = self._unified_diff(expected_content, actual_content, path)
            return VerificationResult.create(
                diff=diff,
                is_correct=False,
                weight=1.0
            )

        # Pattern match
        if "contains" in spec:
            pattern = spec["contains"]
            if pattern in actual_content:
                return VerificationResult.create(
                    diff=f"✓ Contains '{pattern}'",
                    is_correct=True,
                    weight=0.5
                )
            return VerificationResult.create(
                diff=f"✗ Missing pattern '{pattern}'",
                is_correct=False,
                weight=0.5
            )

        # File exists is enough
        return VerificationResult.create(
            diff="✓ File exists",
            is_correct=True,
            weight=0.3
        )

    def _unified_diff(self, expected, actual, filename):
        """Generate unified diff."""
        expected_lines = expected.splitlines(keepends=True)
        actual_lines = actual.splitlines(keepends=True)

        diff = difflib.unified_diff(
            expected_lines,
            actual_lines,
            fromfile=f"{filename} (expected)",
            tofile=f"{filename} (actual)",
            lineterm=""
        )

        return "".join(diff)
```

### Example 3: Numeric Tolerance

```python
import re
from typing import Union

class NumericVerifier:
    """Verifies numeric outputs with tolerance."""

    def __init__(self, checkpoint_config):
        self.config = checkpoint_config
        self.default_tolerance = checkpoint_config.get("tolerance", 1e-6)

    def __call__(self, group_name, case_name, actual, expected):
        results = {}

        # Extract numbers from output
        actual_numbers = self._extract_numbers(actual.output)
        expected_numbers = getattr(expected, 'numbers', [])

        # Verify count
        results["number_count"] = VerificationResult.create(
            diff=f"Expected {len(expected_numbers)} numbers, got {len(actual_numbers)}",
            is_correct=len(actual_numbers) == len(expected_numbers),
            weight=0.5
        )

        # Verify each number
        tolerance = getattr(expected, 'tolerance', self.default_tolerance)
        for i, (exp, act) in enumerate(zip(expected_numbers, actual_numbers)):
            results[f"number_{i}"] = self._verify_number(
                exp, act, tolerance, i
            )

        return results

    def _extract_numbers(self, text):
        """Extract all numbers from text."""
        pattern = r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?"
        return [float(m) for m in re.findall(pattern, text)]

    def _verify_number(self, expected, actual, tolerance, index):
        """Verify a number with tolerance."""
        diff = abs(expected - actual)
        is_correct = diff <= tolerance

        if is_correct:
            return VerificationResult.create(
                diff=f"✓ Number {index}: {actual} (within {tolerance} of {expected})",
                is_correct=True,
                weight=1.0
            )

        return VerificationResult.create(
            diff=f"✗ Number {index}: expected {expected}, got {actual} (diff: {diff}, tolerance: {tolerance})",
            is_correct=False,
            weight=1.0
        )
```

### Example 4: Custom Weighted Scoring

```python
class WeightedVerifier:
    """Verifier with custom attribute weights."""

    def __init__(self, checkpoint_config):
        self.config = checkpoint_config
        # Define weights for different attributes
        self.weights = {
            "correctness": 1.0,      # Most important
            "efficiency": 0.5,       # Moderately important
            "format": 0.3,           # Least important
        }

    def __call__(self, group_name, case_name, actual, expected):
        results = {}

        # Verify correctness (high weight)
        expected_output = expected.output
        results["correctness"] = VerificationResult.create(
            diff=self._diff(expected_output, actual.output),
            is_correct=actual.output == expected_output,
            weight=self.weights["correctness"]
        )

        # Verify efficiency (medium weight)
        max_time = getattr(expected, 'max_execution_time', 10.0)
        is_efficient = actual.execution_time <= max_time
        results["efficiency"] = VerificationResult.create(
            diff=f"Execution time: {actual.execution_time:.3f}s (max: {max_time}s)",
            is_correct=is_efficient,
            weight=self.weights["efficiency"]
        )

        # Verify format (low weight)
        is_valid_format = self._check_format(actual.output)
        results["format"] = VerificationResult.create(
            diff="Output format is valid" if is_valid_format else "Invalid format",
            is_correct=is_valid_format,
            weight=self.weights["format"]
        )

        return results

    def _check_format(self, output):
        """Check if output follows expected format."""
        # Example: must be valid JSON
        try:
            json.loads(output)
            return True
        except:
            return False

    def _diff(self, expected, actual):
        return "Match" if expected == actual else f"Expected: {expected}, Got: {actual}"
```

## Scoring and Weighting

### Weight Principles

Weights determine the relative importance of each verification attribute:

```python
# Example: Critical vs optional checks
results = {
    "output": VerificationResult.create(..., weight=1.0),      # Critical
    "performance": VerificationResult.create(..., weight=0.5), # Important
    "formatting": VerificationResult.create(..., weight=0.2),  # Nice-to-have
}
```

### Score Calculation

The score is computed from the verification results (using `VerifierReport.calculate_score()`):

```python
def calculate_score(results: dict[str, VerificationResult]) -> float:
    """Calculate weighted average score from verification results."""
    total_weight = 0
    weighted_sum = 0
    for result in results.values():
        if result.is_correct is None:
            continue  # Skip unverified attributes
        total_weight += result.weight
        weighted_sum += result.is_correct * result.weight
    return weighted_sum / total_weight if total_weight > 0 else 0.0
```

Example:
```python
results = {
    "output": VerificationResult.create(..., is_correct=True, weight=1.0),
    "status": VerificationResult.create(..., is_correct=True, weight=0.5),
    "format": VerificationResult.create(..., is_correct=False, weight=0.3),
}

score = calculate_score(results)  # Returns 0.833 (83.3%)
```

### Partial Credit

Use weights to give partial credit:

```python
# All-or-nothing (weight=1.0 for everything)
# vs
# Partial credit (different weights for different aspects)

# Example: Code quality assessment
results = {
    "functionality": VerificationResult(..., weight=1.0),  # Must work
    "code_style": VerificationResult(..., weight=0.3),     # Nice to have
    "documentation": VerificationResult(..., weight=0.2),  # Bonus
}
```

## Diff Generation Strategies

### 1. Simple String Comparison

```python
def simple_diff(expected, actual):
    if expected == actual:
        return "✓ Match"
    return f"Expected:\n{expected}\n\nActual:\n{actual}"
```

### 2. Line-by-Line Diff

```python
def line_diff(expected, actual):
    exp_lines = expected.splitlines()
    act_lines = actual.splitlines()

    diff = []
    for i, (e, a) in enumerate(zip(exp_lines, act_lines)):
        if e != a:
            diff.append(f"Line {i+1}: '{e}' != '{a}'")

    return "\n".join(diff) if diff else "✓ Match"
```

### 3. Unified Diff (like git diff)

```python
import difflib

def unified_diff(expected, actual):
    diff = difflib.unified_diff(
        expected.splitlines(keepends=True),
        actual.splitlines(keepends=True),
        fromfile="expected",
        tofile="actual"
    )
    return "".join(diff)
```

### 4. Visual Diff

```python
def visual_diff(expected, actual):
    """Show differences with color indicators."""
    if expected == actual:
        return "✓ Match"

    lines = []
    for i, (e, a) in enumerate(zip(expected.splitlines(), actual.splitlines())):
        if e == a:
            lines.append(f"  {e}")
        else:
            lines.append(f"- {e}")
            lines.append(f"+ {a}")

    return "\n".join(lines)
```

## Common Verification Patterns

### Pattern 1: Flexible Matching

Allow minor variations in output:

```python
def flexible_match(expected, actual):
    # Strip whitespace
    exp_clean = expected.strip()
    act_clean = actual.strip()

    # Case-insensitive
    if exp_clean.lower() == act_clean.lower():
        return VerificationResult.create("✓ Match (case-insensitive)", True, 1.0)

    # Partial match
    if exp_clean in act_clean:
        return VerificationResult.create("✓ Contains expected", True, 0.8)

    return VerificationResult.create(f"No match: {exp_clean} vs {act_clean}", False, 1.0)
```

### Pattern 2: Schema Validation

Validate structure without exact matching:

```python
def validate_schema(actual_json, schema):
    """Verify JSON matches schema."""
    for key, value_type in schema.items():
        if key not in actual_json:
            return False, f"Missing key: {key}"

        if not isinstance(actual_json[key], value_type):
            return False, f"Wrong type for {key}: expected {value_type}, got {type(actual_json[key])}"

    return True, "✓ Schema valid"
```

### Pattern 3: Regex Matching

Match patterns instead of exact values:

```python
import re

def regex_match(pattern, actual):
    """Match output against regex pattern."""
    if re.fullmatch(pattern, actual):
        return VerificationResult.create(f"✓ Matches pattern: {pattern}", True, 1.0)

    return VerificationResult.create(f"✗ Does not match pattern: {pattern}", False, 1.0)
```

## Testing Your Verifier

### Using `tools run-case` (Recommended)

The `tools run-case` command is the most effective way to test and debug your verifier:

```bash
# Run verification on your reference solution
slop-code tools run-case \
  -s problems/my_problem/checkpoint_1/solution \
  -p my_problem \
  -c 1 \
  -e configs/environments/docker-python3.12-uv.yaml
```

**Basic output** (without `--full`):
```json
[
  {
    "id": "test_basic",
    "group": "core",
    "score": 1.0,
    "passed": true
  },
  {
    "id": "test_edge_case",
    "group": "core",
    "score": 0.5,
    "passed": false,
    "results": {
      "output": { "is_correct": false, "weight": 0.8, "..." },
      "status_code": { "is_correct": true, "weight": 0.2, "..." }
    }
  }
]
```

### Debugging with `--full`

When a case fails, use `--full` to see exactly what differs:

```bash
slop-code tools run-case \
  -s solution \
  -p my_problem -c 1 \
  -e configs/environments/docker-python3.12-uv.yaml \
  --case test_edge_case \
  --full
```

**Full output** includes:
```json
{
  "id": "test_edge_case",
  "group": "core",
  "results": {
    "output": {
      "attribute": "output",
      "actual": "got: 42",
      "expected": "expected: 43",
      "diff": {"values_changed": {"root": {"old": "43", "new": "42"}}},
      "is_correct": false,
      "weight": 0.8
    },
    "status_code": {
      "attribute": "status_code",
      "actual": 0,
      "expected": 0,
      "diff": "Match",
      "is_correct": true,
      "weight": 0.2
    }
  }
}
```

### Common Debugging Scenarios

**1. Verification always fails:**
```bash
# See exactly what's being compared
slop-code tools run-case ... --case failing --full | jq '.[0].results.output'
```
Check:
- Is `actual` what you expect from execution?
- Is `expected` what you defined in test cases?
- Does `diff` show meaningful differences?

**2. Wrong score calculation:**
```bash
# Check weights on all attributes
slop-code tools run-case ... --full | jq '.[0].results | to_entries | .[] | {attr: .key, weight: .value.weight, correct: .value.is_correct}'
```

**3. File verification issues:**
```bash
# Check file-specific results
slop-code tools run-case ... --full | jq '.[0].results | to_entries | .[] | select(.key | startswith("files-"))'
```

### Verifier Testing Workflow

1. **Create reference solution** that produces correct output
2. **Run `tools run-case`** on the solution
3. **All cases should pass** (score = 1.0) with correct solution
4. **If failures occur**: Use `--full` to debug verification logic
5. **Test error cases**: Run `--group errors` to verify error handling

### Testing with Intentionally Wrong Solutions

To verify your verifier correctly identifies failures:

```bash
# Create a broken solution
cp -r solution broken_solution
# Introduce a bug in broken_solution

# Run and verify it fails appropriately
slop-code tools run-case \
  -s broken_solution \
  -p my_problem -c 1 \
  -e configs/environments/docker-python3.12-uv.yaml

# Check that scores are less than 1.0
slop-code tools run-case ... | jq '[.[].score] | add / length'
```

### Unit Testing (Supplementary)

For complex verification logic, add unit tests:

```python
# test_verifier.py
from verifier import Verifier
from slop_code.evaluation.adapters import cli
from unittest.mock import Mock

def test_verifier_correct_output():
    """Test verifier passes correct output."""
    config = Mock()
    verifier = Verifier(config)

    actual = cli.CLIResult(
        id="test", group="core", group_type="Core",
        status_code=0, output="Hello, World!\n"
    )
    expected = cli.CLIResult(
        id="test", group="core", group_type="Core",
        status_code=0, output="Hello, World!\n"
    )

    results = verifier("core", "test", actual, expected)

    assert all(r.is_correct for r in results.values()), "Should pass"

def test_verifier_wrong_output():
    """Test verifier fails wrong output."""
    config = Mock()
    verifier = Verifier(config)

    actual = cli.CLIResult(
        id="test", group="core", group_type="Core",
        status_code=0, output="Wrong output"
    )
    expected = cli.CLIResult(
        id="test", group="core", group_type="Core",
        status_code=0, output="Expected output"
    )

    results = verifier("core", "test", actual, expected)

    assert not all(r.is_correct for r in results.values()), "Should fail"

if __name__ == "__main__":
    test_verifier_correct_output()
    test_verifier_wrong_output()
    print("✓ Verifier tests passed")
```

### Tips for Effective Debugging

1. **Start with `--full`**: Always use when investigating failures
2. **Use `jq` for filtering**: Extract specific fields from JSON output
3. **Compare actual vs expected**: The diff shows exactly what differs
4. **Check weights**: Ensure weights reflect importance correctly
5. **Test edge cases**: Run with `--group errors` or similar groups

## Next Steps

- **Understand reporting**: [Reporting Guide](reporting.md)
- **Set up test cases**: [Loaders Guide](loaders.md)
- **Debug issues**: [Troubleshooting Guide](troubleshooting.md)
