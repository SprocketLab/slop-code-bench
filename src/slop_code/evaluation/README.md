# Evaluation Framework

The evaluation framework provides a comprehensive system for testing and validating agent submissions against structured problem specifications. It orchestrates execution, result collection, and verification through a modular architecture of adapters, verifiers, and configuration management.

## Architecture Overview

The evaluation framework operates on three hierarchical levels:

1. **Problem** - Top-level container defining metadata, environment, and checkpoints
2. **Checkpoint** - Individual evaluation milestones with specific adapters and test groups  
3. **Group** - Collections of test cases with shared verification logic

```
Problem/
├── config.yaml          # Problem-level configuration
├── design_doc.md        # Problem specification
├── checkpoint_1/
│   ├── config.yaml      # Checkpoint configuration
│   ├── spec.md          # Checkpoint specification
│   └── spec_cases/      # Test cases
│       ├── case1/
│       │   ├── BODY.json
│       │   ├── EXPECTED.json
│       │   └── META.yaml
│       └── case2/
└── checkpoint_2/
    └── ...
```

## Core Components

### Configuration System (`config.py`)

The configuration system uses Pydantic models to validate and manage hierarchical YAML configurations:

- **`ProblemConfig`** - Top-level problem definition with metadata, environment specs, and checkpoint list
- **`CheckpointConfig`** - Checkpoint-specific configuration including adapter setup and group definitions
- **`GroupConfig`** - Test group configuration with case discovery rules and verification settings
- **`BaseConfig`** - Shared configuration fields (environment variables, timeouts) that propagate from parent to child

### Execution Engine (`runner.py`)

The runner orchestrates the entire evaluation process:

- **`make_adapter()`** - Constructs appropriate adapter instances based on configuration
- **`run_case()`** - Executes individual test cases and captures results
- **`run_group()`** - Executes all cases within a group with shared adapter context
- **`run_checkpoint()`** - End-to-end checkpoint execution with comprehensive reporting

### Adapters (`adapters/`)

Adapters define how submissions are executed and what results are captured:

#### Available Adapters

- **CLI Adapter** (`cli.py`) - Executes Python entry files per case with command-line arguments
- **API Adapter** (`api.py`) - Starts HTTP servers and issues requests per case
- **Playwright Adapter** (`playwright/`) - Browser automation for web application testing

#### Adapter Interface

All adapters implement the `Adapter` protocol:

```python
@runtime_checkable
class Adapter(Protocol):
    def __enter__(self) -> "Adapter": ...
    def __exit__(self, exc_type, exc, tb) -> None: ...
    def run_case(self, case: BaseCase) -> CaseResult: ...
```

### Verifiers (`verifiers/`)

Verifiers validate execution results against expected outcomes:

- **`VerifierProtocol`** - Interface for user-defined verification logic
- **`VerificationResult`** - Individual attribute verification with diff and scoring
- **`VerifierReport`** - Aggregated verification results with scoring metrics
- **`parsers.py`** - Utilities for normalizing and parsing execution results
- **`verifiers.py`** - Common verification utilities and helper functions

### Reporting (`report.py`)

The reporting system generates comprehensive evaluation reports:

- **`CheckpointReport`** - Complete checkpoint execution summary
- **Group-level metrics** - Success rates, execution times, failure analysis
- **Case-level details** - Individual test results with diffs and artifacts

## Usage Patterns

### Basic Problem Structure

```yaml
# problems/my_problem/config.yaml
name: "My Problem"
version: 1
description: "Example problem for demonstration"
tags: ["example", "basic"]
category: "algorithm"
difficulty: "Easy"
entry_file: "solution.py"
checkpoints: ["checkpoint_1", "checkpoint_2"]
```

### Checkpoint Configuration

```yaml
# problems/my_problem/checkpoint_1/config.yaml
version: 1
adapter:
  type: cli
  tracked_files: ["output.txt"]
groups:
  basic_tests:
    type: test
    case_order: ["case1", "case2"]
```

### Test Case Definition

```json
// problems/my_problem/checkpoint_1/spec_cases/case1/BODY.json
{
  "arguments": ["input1.txt", "output.txt"],
  "files": {
    "input1.txt": "test data"
  },
  "tracked_files": ["output.txt"]
}
```

`tracked_files` entries can be literal relative paths or glob patterns (e.g.,
`"reports/**/*.json"`). Matches are collected after each case is executed.

```json
// problems/my_problem/checkpoint_1/spec_cases/case1/EXPECTED.json
{
  "status_code": 0,
  "output": "Success",
  "files": {
    "output.txt": "processed result"
  }
}
```

### Custom Verifier Implementation

```python
# problems/my_problem/verifier.py
from slop_code.evaluation.verifiers import VerifierProtocol, VerifierReturnType, VerificationResult

class MyVerifier:
    def __init__(self, checkpoint_config):
        self.checkpoint_config = checkpoint_config
    
    def __call__(self, group_name, case_name, actual, expected) -> VerifierReturnType:
        results = {}
        
        # Verify status code
        results["status_code"] = VerificationResult.create(
            diff=actual.status_code - expected.status_code,
            is_correct=actual.status_code == expected.status_code,
            weight=1.0
        )
        
        # Verify output content
        results["output"] = VerificationResult.create(
            diff={"actual": actual.output, "expected": expected.output},
            is_correct=actual.output.strip() == expected.output.strip(),
            weight=2.0
        )
        
        return results
```

## Execution Flow

1. **Problem Loading** - Parse problem configuration and validate structure
2. **Checkpoint Setup** - Load checkpoint config and initialize execution context
3. **Adapter Creation** - Construct appropriate adapter based on configuration
4. **Case Discovery** - Load test cases using configured loader strategy
5. **Group Execution** - Run all cases in a group with shared adapter context
6. **Verification** - Apply user-defined verifiers to compare actual vs expected results
7. **Reporting** - Generate comprehensive reports with metrics and diagnostics

## Advanced Features

### Static Assets

Static assets allow referencing external files without copying:

```yaml
# problem/config.yaml
static_assets:
  test_data:
    type: local
    path: "./data/large_dataset.csv"
```

### Environment Configuration

Fine-grained control over execution environment:

```yaml
# checkpoint/config.yaml
env:
  PYTHONPATH: "/additional/path"
  DEBUG: "true"
timeout: 30.0
```

### Regression Testing

Support for regression groups that reference previous checkpoints:

```yaml
groups:
  regression_tests:
    type: regression
    original_checkpoint: "checkpoint_1"
    original_group: "basic_tests"
```

### Mock Services

Integration with Mockoon for HTTP service mocking:

```yaml
adapter:
  type: api
  mocks:
    - data_file: "mocks/api.json"
      address: "127.0.0.1"
      port: 3001
```

## Error Handling

The framework provides comprehensive error handling:

- **`ConfigError`** - Configuration validation failures
- **`AdapterError`** - Adapter-level execution failures
- **Graceful degradation** - Continue evaluation when individual cases fail
- **Detailed diagnostics** - Rich error reporting with context and suggestions

## Performance Considerations

- **Parallel execution** - Groups run independently for better throughput
- **Resource management** - Proper cleanup of adapters and temporary resources
- **Caching** - Static assets and compiled verifiers are cached appropriately
- **Timeout handling** - Configurable timeouts at multiple levels

## Integration Points

The evaluation framework integrates with:

- **Agent Runner** - Orchestrates multiple checkpoints and problems
- **Execution Manager** - Provides Docker/local execution environments
- **CLI Tools** - Command-line interfaces for evaluation and debugging
- **Reporting System** - Generates human-readable and machine-parseable reports

## Best Practices

1. **Modular Design** - Keep verifiers focused and reusable
2. **Clear Configuration** - Use descriptive names and comprehensive documentation
3. **Robust Error Handling** - Provide meaningful error messages and recovery paths
4. **Comprehensive Testing** - Include edge cases and error conditions in test suites
5. **Performance Awareness** - Consider resource usage and execution time in design

## Troubleshooting

Common issues and solutions:

- **Missing entry file** - Ensure `entry_file` is correctly specified and accessible
- **Timeout failures** - Adjust timeout values or optimize submission performance
- **Environment issues** - Verify environment variables and dependencies
- **Adapter errors** - Check adapter-specific configuration and requirements
- **Verification failures** - Review verifier logic and expected values

For detailed adapter-specific documentation, see [`adapters/README.md`](adapters/README.md).
