---
version: 1.2
last_updated: 2025-10-16
---

# Evaluation Module Architecture Overview

The evaluation module provides a comprehensive framework for running automated benchmarks and tests against agent submissions. It orchestrates the execution of test cases, validates results, and generates detailed reports.

## High-Level Flow

**Hierarchical Structure:**
```
Problem (1)
├── config.yaml
├── loader.py
├── verifier.py
├── Checkpoint 1 (*)
│   ├── Group 1 (*)
│   │   ├── Case 1 (*)
│   │   ├── Case 2 (*)
│   │   └── ...
│   ├── Group 2 (*)
│   │   ├── Case 1 (*)
│   │   └── ...
│   └── ...
├── Checkpoint 2 (*)
│   ├── config.yaml
│   └── ...
└── ...

(*) = Multiple instances can exist
```

**Execution Flow:**
```
┌─────────────────┐
│   Problem       │
│   Config        │
└─────────┬───────┘
          │ Load config.yaml in the problem directory.
          ▼
┌──────────────────┐
│   For Each       │
│   Checkpoint:    │
│                  │
│ ┌──────────────┐ │
│ │   Load       │ │
│ │   checkpoint │ │
│ │   config     │ │
│ └──────────────┘ │
│                  │
│ ┌──────────────┐ │
│ │   Create     │ │
│ │   Adapter    │ │
│ │   (CLI/API)  │ │
│ └──────────────┘ │
│                  │
│ ┌──────────────┐ │
│ │   For Each   │ │
│ │   Group:     │ │
│ │ ┌─────────┐  │ │
│ │ │ Load    │  │ │
│ │ │ cases   │  │ │
│ │ └─────────┘  │ │
│ │ ┌─────────┐  │ │
│ │ │ For     │  │ │
│ │ │ Each    │  │ │
│ │ │ Case:   │  │ │
│ │ │ ┌─────┐ │  │ │
│ │ │ │Run  │ │  │ │
│ │ │ │Case │ │  │ │
│ │ │ └─────┘ │  │ │
│ │ │ ┌──────┐│  │ │
│ │ │ │Verify││  │ │
│ │ │ │Result││  │ │
│ │ │ └──────┘│  │ │
│ │ └─────────┘  │ │
│ └──────────────┘ │
└─────────┬────────┘
          │
          ▼
┌─────────────────┐
│   Report        │
│   Generation    │
│   (Aggregate    │
│    all results) │
└─────────────────┘
```

**Key Relationships:**
- **Problem → Checkpoints**: 1-to-many (problem contains multiple checkpoints)
- **Checkpoint → Groups**: 1-to-many (checkpoint contains multiple groups)  
- **Group → Cases**: 1-to-many (group contains multiple test cases)
- **Adapter**: Created once per checkpoint, shared by all groups within it
- **Verifier**: Instantiated once per checkpoint, used for all case verification

**Execution Sequence:**

1. **Problem Setup** → Load `config.yaml` with global configuration
2. **Checkpoint Iteration** → For each checkpoint in the problem:
   - Load `checkpoint/config.yaml`
   - Create adapter instance (CLI/API/Playwright)
   - Initialize verifier
   - Load group loader
3. **Group Processing** → For each group in the checkpoint:
   - Discover test cases using group loader
   - Execute all cases through the shared adapter
   - Verify each case result against expected values
4. **Report Generation** → Aggregate all group results into checkpoint report

Each checkpoint runs independently with its own adapter and verifier instances, but shares the problem-level configuration and execution environment.

## Terminology and Notation

- **Problem**: Top-level benchmark definition containing multiple checkpoints
- **Checkpoint**: A milestone or test suite within a problem (e.g., "checkpoint_1")
- **Group**: Collection of related test cases with shared configuration
- **Case**: Individual test scenario with inputs and expected outputs
- **Adapter**: Execution environment wrapper (CLI, API, or Playwright)
- **Verifier**: User-defined logic that validates actual vs expected results
- **Loader**: Component that discovers and loads test cases from filesystem
- **Static Assets**: Files mounted into execution environment (mock data, configs)
- **Submission**: Agent code being evaluated
- **CaseResult**: Standardized output structure from adapter execution
- **VerifierReport**: Detailed validation results with scoring and diffs

## Core Components

### 1. Configuration Layer (`config.py`)

The configuration system defines three hierarchical levels:

- **ProblemConfig**: Top-level problem definition with metadata, entry points, and shared assets
- **CheckpointConfig**: Execution-specific wiring for milestones, including adapter configuration and group definitions  
- **GroupConfig**: Case discovery rules and verification pipelines

All configurations use Pydantic models with validation and support inheritance of defaults from parent scopes.

### 2. Execution Adapters (`adapters/`)

Adapters provide different execution environments for running submissions:

- **CLI Adapter**: Executes command-line interface submissions
- **API Adapter**: Runs HTTP API-based submissions with mock server support
- **Playwright Adapter**: Handles web browser automation scenarios

All adapters implement the `Adapter` protocol and provide:
- Context manager setup/teardown
- Case execution with timeout handling
- Standardized `CaseResult` output

### 3. Verification System (`verifiers/`)

The verification layer validates submission results against expected outcomes:

- **VerifierProtocol**: Interface for user-defined verification logic
- **VerificationResult**: Per-attribute validation with diff information
- **VerifierReport**: Aggregated results with scoring and metadata

Verifiers can compare output, status codes, files, and custom attributes with weighted scoring.

### 4. Case Loading (`loader.py`)

Dynamic case discovery and loading system:

- **GroupLoader Protocol**: Interface for custom case loading logic
- **Script Loader**: Loads user-defined Python scripts for case generation
- **Pattern Matching**: Supports glob patterns and exclusion rules for file discovery

### 5. Orchestration Engine (`runner.py`)

The core execution coordinator that:

- Constructs adapters with proper execution environments
- Manages case execution lifecycle
- Coordinates verification and result collection
- Handles timeouts and error conditions

### 6. Reporting (`report.py`)

Comprehensive reporting system with:

- **CheckpointReport**: Aggregated results across all groups
- **PassPolicy**: Configurable passing criteria (any, all, core cases, etc.)
- Export formats: JSON, Parquet for analytics
- Detailed diff information and timing metrics

## Execution Flow

1. **Initialization**: Load problem and checkpoint configurations
2. **Environment Setup**: Build execution manager with static assets
3. **Adapter Construction**: Create appropriate adapter based on configuration
4. **Case Discovery**: Load test cases using configured group loader
5. **Execution**: Run each case through the adapter with timeout handling
6. **Verification**: Apply user-defined verifier to compare actual vs expected
7. **Aggregation**: Collect results into structured reports
8. **Output**: Generate reports in specified formats

## Key Design Patterns

### Protocol-Based Architecture
- Uses Python protocols for extensible interfaces
- Runtime type checking ensures compliance
- Allows user-defined implementations for loaders and verifiers

### Configuration Inheritance
- Child scopes inherit defaults from parents
- Nested priority merging ensures specific values override general ones
- Supports environment variables and timeouts at multiple levels

### Context Management
- Adapters use context managers for resource cleanup
- Execution context provides shared state across components
- Proper isolation between test runs

### Error Handling
- Structured exception hierarchy for different failure modes
- Detailed error reporting with context
- Graceful degradation for partial failures

## Usage Patterns

### Creating a New Problem
1. Define `ProblemConfig` in `config.yaml`
2. Create checkpoint directories with `CheckpointConfig`
3. Implement `verifier.py` with custom verification logic
4. implement `loader.py` with custom loading logic.

### Running Evaluations
```python
from slop_code.evaluation import run_checkpoint

report = run_checkpoint(
    seed=42,
    submission_path=Path("submission"),
    problem=problem_config,
    checkpoint=checkpoint_config,
    env_spec=environment_spec
)
```

### Custom Verification
```python
class MyVerifier:
    def __init__(self, checkpoint_config):
        self.config = checkpoint_config
    
    def __call__(self, group_name, case_name, actual, expected):
        return {
            "output": VerificationResult.create(diff, is_correct, weight),
            "status_code": VerificationResult.create(diff, is_correct, weight)
        }
```

## Integration Points

- **Task Runner**: CLI entry points for batch execution
- **Execution Module**: Environment specifications and Docker management
- **Protocol Loader**: Dynamic loading of user code
- **Analytics**: Parquet export for downstream analysis

The evaluation module is designed to be extensible while providing a consistent interface for different types of benchmarks and evaluation scenarios.