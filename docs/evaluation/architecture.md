---
version: 1.3
last_updated: 2025-12-10
---

# Evaluation System Architecture

This guide provides a detailed overview of the evaluation system's architecture, including its hierarchical structure, execution flow, and key design patterns.

## Hierarchical Structure

The evaluation system uses a four-level hierarchy:

```
Problem (1)
├── config.yaml
├── loader.py
├── verifier.py
├── Checkpoint 1 (*)
│   ├── config.yaml
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

### Key Relationships

- **Problem → Checkpoints**: 1-to-many (problem contains multiple checkpoints)
- **Checkpoint → Groups**: 1-to-many (checkpoint contains multiple groups)
- **Group → Cases**: 1-to-many (group contains multiple test cases)
- **Adapter**: Created once per checkpoint, shared by all groups within it
- **Verifier**: Instantiated once per checkpoint, used for all case verification

## Execution Flow

### High-Level Flow

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

### Execution Sequence

1. **Problem Setup** → Load `problem.yaml` with global configuration
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

### Detailed Execution Steps

1. **Initialization**: Load problem and checkpoint configurations
2. **Context Creation**: Build ExecutionContext with environment and assets
3. **Adapter Construction**: Create appropriate adapter based on configuration
4. **Loader Initialization**: Initialize group loader for case discovery
5. **Case Discovery**: Load test cases using configured group loader
6. **Execution**: Run each case through the adapter with timeout handling
7. **Verification**: Apply user-defined verifier to compare actual vs expected
8. **Aggregation**: Collect results into structured reports
9. **Output**: Generate reports in specified formats

## Core Components

### 1. Configuration Layer (`config.py`)

The configuration system defines three hierarchical levels:

- **ProblemConfig**: Top-level problem definition with metadata, entry points, and shared assets
- **CheckpointConfig**: Execution-specific wiring for milestones, including adapter configuration and group definitions
- **GroupConfig**: Case discovery rules and verification pipelines

All configurations use Pydantic models with validation and support inheritance of defaults from parent scopes.

**See**: [Configuration Guide](configuration.md) for detailed YAML examples and structure.

### 2. Execution Adapters (`adapters/`)

Adapters provide different execution environments for running submissions:

- **CLI Adapter**: Executes command-line interface submissions
- **API Adapter**: Runs HTTP API-based submissions with mock server support
- **Playwright Adapter**: Handles web browser automation scenarios

All adapters implement the `Adapter` protocol and provide:
- Context manager setup/teardown
- Case execution with timeout handling
- Standardized `CaseResult` output

**See**: [Adapters Guide](adapters.md) for choosing and configuring adapters.

### 3. Verification System (`verifiers/`)

The verification layer validates submission results against expected outcomes:

- **VerifierProtocol**: Interface for user-defined verification logic
- **VerificationResult**: Per-attribute validation with diff information
- **VerifierReport**: Aggregated results with scoring and metadata

Verifiers can compare output, status codes, files, and custom attributes with weighted scoring.

**See**: [Verification Guide](verification.md) for implementation details.

### 4. Case Loading (`loader.py`)

Dynamic case discovery and loading system:

- **GroupLoader Protocol**: Interface for custom case loading logic
- **Script Loader**: Loads user-defined Python scripts for case generation
- **Pattern Matching**: Supports glob patterns and exclusion rules for file discovery

**See**: [Loaders Guide](loaders.md) for case discovery strategies.

### 5. Execution Context (`context.py`)

Enhanced execution context that combines configuration with execution capabilities:

- **ExecutionContext**: Aggregates configuration from problem and checkpoint scopes
- **Environment Management**: Handles environment variables and execution specifications
- **Static Asset Resolution**: Manages static assets available at runtime
- **Run Information Tracking**: Tracks problem, checkpoint, and version metadata

### 6. Orchestration Engine (`runner.py`)

The core execution coordinator that:

- Constructs ExecutionContext with proper configuration
- Creates adapters with execution environments
- Manages case execution lifecycle through loaders
- Coordinates verification and result collection
- Handles timeouts and error conditions

### 7. Reporting (`report.py`)

Comprehensive reporting system with:

- **CorrectnessResults**: Aggregated results across all groups with pass/fail counts by GroupType
- **GroupReport**: Per-group summaries with case scores
- **PassPolicy**: Configurable passing criteria (any-case, all-cases, core-cases, etc.)
- Export formats: JSON (evaluation.json), Parquet (reports.parquet) for analytics
- Detailed diff information and timing metrics

**See**: [Reporting Guide](reporting.md) for understanding results and scoring.

## Terminology and Notation

| Term | Definition |
|------|------------|
| **Problem** | Top-level benchmark definition containing multiple checkpoints |
| **Checkpoint** | A milestone or test suite within a problem (e.g., "checkpoint_1") |
| **Group** | Collection of related test cases with shared configuration |
| **Case** | Individual test scenario with inputs and expected outputs |
| **ExecutionContext** | Execution bundle with configuration, environment, and metadata |
| **Adapter** | Execution environment wrapper (CLI, API, or Playwright) |
| **Verifier** | User-defined logic that validates actual vs expected results |
| **Loader** | Component that discovers and loads test cases from filesystem |
| **Static Assets** | Files mounted into execution environment (mock data, configs) |
| **Submission** | Agent code being evaluated |
| **CaseResult** | Standardized output structure from adapter execution |
| **VerificationResult** | Per-attribute validation with diff information |

## Key Design Patterns

### Protocol-Based Architecture

- Uses Python protocols for extensible interfaces
- Runtime type checking ensures compliance
- Allows user-defined implementations for loaders and verifiers

**Benefits:**
- Type safety without inheritance constraints
- Easy to extend with custom implementations
- Clear contracts between components

### Configuration Inheritance

- Child scopes inherit defaults from parents
- Nested priority merging ensures specific values override general ones
- Supports environment variables and timeouts at multiple levels

**Benefits:**
- DRY principle: define once, use everywhere
- Easy to override at specific levels
- Consistent behavior across checkpoints

### Context Management

- Adapters use context managers for resource cleanup
- ExecutionContext provides shared configuration and state across components
- Proper isolation between test runs

**Benefits:**
- Automatic resource cleanup
- Centralized configuration management
- Clean state between executions
- Consistent environment setup across checkpoints

### Error Handling

- Structured exception hierarchy for different failure modes
- Detailed error reporting with context
- Graceful degradation for partial failures

**Benefits:**
- Clear error diagnostics
- Partial results even on failures
- Easier debugging

**See**: [Troubleshooting Guide](troubleshooting.md) for exception reference.

## Integration Points

The evaluation module integrates with several other system components:

- **Task Runner**: CLI entry points for batch execution
- **Execution Module**: Environment specifications and Docker management
- **Protocol Loader**: Dynamic loading of user code (loaders and verifiers)
- **Analytics**: Parquet export for downstream analysis

## Design Philosophy

The evaluation module is designed to be:

1. **Extensible**: Protocol-based interfaces allow custom implementations
2. **Consistent**: Standardized interfaces across different execution modes
3. **Isolated**: Proper resource management prevents cross-contamination
4. **Observable**: Detailed reporting and error diagnostics
5. **Composable**: Mix and match adapters, verifiers, and loaders

## Next Steps

- **Implement your first evaluation**: [Getting Started Guide](getting-started.md)
- **Configure problems and checkpoints**: [Configuration Guide](configuration.md)
- **Understand verification**: [Verification Guide](verification.md)
