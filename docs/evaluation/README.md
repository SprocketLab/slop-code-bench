---
version: 1.4
last_updated: 2025-12-10
---

# Evaluation System Documentation

The evaluation module provides a comprehensive framework for running automated benchmarks and tests against agent submissions. It orchestrates the execution of test cases, validates results, and generates detailed reports.

## 30-Second Overview

The evaluation system runs your agent code through **Problems** containing **Checkpoints**, each with **Groups** of **Test Cases**. Cases execute through **Adapters** (CLI/API/Browser), results are validated by **Verifiers**, and aggregated into **CorrectnessResults**.

## Documentation Guide

### 🚀 **Getting Started**
- **New to the evaluation system?** Start with [Architecture Overview](architecture.md)
- **Need to configure a problem?** See [Configuration Guide](configuration.md)

### 📋 **Configuration & Setup**
- **Writing configs?** Read [Configuration Guide](configuration.md)
- **Setting up test cases?** See [Loaders Guide](loaders.md)

### 🔧 **Implementation**
- **Choosing execution environment?** Check [Adapters Guide](adapters.md)
- **Writing verification logic?** Read [Verification Guide](verification.md)
- **Understanding results?** See [Reporting Guide](reporting.md)

### 🐛 **Troubleshooting**
- **Something not working?** Try [Troubleshooting Guide](troubleshooting.md)

## Core Concepts at a Glance

| Concept | Description |
|---------|-------------|
| **Problem** | Top-level benchmark with multiple checkpoints |
| **Checkpoint** | Milestone containing groups of related test cases |
| **Group** | Collection of test cases sharing configuration and type (Core, Functionality, etc.) |
| **Case** | Individual test scenario with inputs/outputs (BaseCase, CaseResult) |
| **Adapter** | Execution environment (CLI, API, or Playwright) |
| **Verifier** | Validation logic comparing actual vs expected (VerifierProtocol) |
| **Loader** | Component discovering and loading test cases (GroupLoader) |
| **Environment** | Execution configuration with setup commands ([see evaluation-specific setup](configuration.md#environment-configuration)) |
| **Report** | Aggregated results with scoring and diagnostics (CorrectnessResults) |

## Common Workflows

### Creating a New Evaluation
1. Read [Architecture](architecture.md) → Understand the evaluation flow
2. Read [Configuration](configuration.md) → Define problem and checkpoint configs
3. Read [Verification](verification.md) → Implement custom verifier
4. Read [Loaders](loaders.md) → Set up case discovery (if needed)

### Debugging Failures
1. Check [Troubleshooting](troubleshooting.md) → Common issues
2. Review [Adapters](adapters.md) → Execution environment specifics
3. Check [Verification](verification.md) → Validation logic
4. Review [Reporting](reporting.md) → Understand failure details

### Extending the System
1. Read [Architecture](architecture.md) → Understand design patterns
2. Read specific guide for component you're extending
3. Check [Troubleshooting](troubleshooting.md) → Debugging custom code

## Additional Resources

- **Code Location**: `src/slop_code/evaluation/`
- **Example Problems**: `problems/` (if available)
- **Main Entry Point**: `slop_code.evaluation.runner.run_checkpoint()`
- **Key Exports**: `ProblemConfig`, `CheckpointConfig`, `GroupConfig`, `GroupType`, `PassPolicy`, `CorrectnessResults`, `VerifierProtocol`, `GroupLoader`

## Version History

- **v1.4** (2025-12-10): Updated to reflect current interfaces (CorrectnessResults, GroupLoader, etc.)
- **v1.3** (2025-11-18): Documentation improvements
- **v1.2** (2025-10-16): Split into modular guide structure
- **v1.1**: Added comprehensive architecture documentation
- **v1.0**: Initial evaluation module documentation
