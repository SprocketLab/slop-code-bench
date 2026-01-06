---
version: 1.0
last_updated: 2025-12-22
---

# CLI Commands Reference

This section documents all commands available in the `slop-code` CLI.

## Quick Reference

| Command | Description |
|---------|-------------|
| [`run`](run.md) | Run agents on benchmarks with unified config system |
| [`eval`](eval.md) | Evaluate a directory of agent inference results |
| [`eval-problem`](eval-problem.md) | Evaluate a single problem directory |
| [`eval-snapshot`](eval-snapshot.md) | Evaluate a single snapshot directory |
| [`infer-problem`](infer-problem.md) | Run inference on a single problem |
| [`metrics`](metrics.md) | Calculate metrics (static, judge, carry-forward, variance) |
| [`utils`](utils.md) | Utility commands for maintenance and data processing |
| [`docker`](docker.md) | Docker image building utilities |
| [`problems`](problems.md) | Problem inspection and registry commands |
| [`tools`](tools.md) | Interactive tools and case runners |
| [`viz`](viz.md) | Visualization tools (diff viewer) |

## Global Options

These options are available on all commands:

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `-v, --verbose` | flag | 0 | Increase verbosity (repeatable) |
| `--seed` | int | 42 | Random seed |
| `-p, --problem-path` | path | `problems/` | Path to problem directory |
| `--overwrite` | flag | false | Overwrite existing output directory |
| `--debug` | flag | false | Enable debugging mode |
| `--snapshot-dir-name` | string | `snapshot` | Name of the snapshot directory |

## Command Categories

### Core Workflow

**Running agents:**
```bash
# Run with config file
slop-code run --config my_run.yaml --problem file_backup

# Run with CLI flags
slop-code run --model anthropic/sonnet-4.5 --problem file_backup
```

**Evaluating results:**
```bash
# Evaluate all problems in a run
slop-code eval outputs/my_run

# Evaluate a single problem
slop-code eval-problem outputs/my_run/file_backup

# Evaluate a single snapshot
slop-code eval-snapshot outputs/my_run/file_backup/checkpoint_1/snapshot \
  -o outputs/eval -p file_backup -c 1 -e configs/environments/docker-python3.12-uv.yaml
```

### Metrics and Analysis

```bash
# Calculate static code quality metrics
slop-code metrics static outputs/my_run

# Run LLM judge evaluation
slop-code metrics judge outputs/my_run -r configs/rubrics/slop.jsonl -m anthropic/sonnet-4.5

# Compute variance across runs
slop-code metrics variance base outputs/runs -o outputs/variance
```

### Utilities

```bash
# Backfill reports for existing runs
slop-code utils backfill-reports outputs/my_run

# Combine results from multiple runs
slop-code utils combine-results outputs/all_runs -o outputs/combined.jsonl
```

### Docker Management

```bash
# Build base image
slop-code docker build-base configs/environments/docker-python3.12-uv.yaml

# Build agent image
slop-code docker build-agent configs/agents/claude_code-2.0.51.yaml configs/environments/docker-python3.12-uv.yaml
```

### Problem Inspection

```bash
# List all problems
slop-code problems ls

# Check problem conversion status
slop-code problems status file_backup
```

### Test Case Runner

```bash
# Run pytest tests for a snapshot
slop-code tools run-case -s outputs/snapshot -p file_backup -c 1 -e configs/environments/docker-python3.12-uv.yaml
```

### Visualization

```bash
# Launch diff viewer for a run
slop-code viz diff outputs/my_run
```

## Documentation Index

| Document | Description |
|----------|-------------|
| [run.md](run.md) | Comprehensive guide to `slop-code run` with configuration system |
| [eval.md](eval.md) | Evaluating run directories |
| [eval-problem.md](eval-problem.md) | Evaluating single problems |
| [eval-snapshot.md](eval-snapshot.md) | Evaluating single snapshots |
| [infer-problem.md](infer-problem.md) | Running inference on single problems |
| [metrics.md](metrics.md) | All metrics subcommands |
| [utils.md](utils.md) | All utility subcommands |
| [docker.md](docker.md) | Docker image management |
| [problems.md](problems.md) | Problem inspection commands |
| [tools.md](tools.md) | Interactive tools |
| [viz.md](viz.md) | Visualization tools |

## See Also

- [Agent Configuration](../agents/README.md) - Agent setup and configuration
- [Evaluation System](../evaluation/README.md) - How evaluation works
- [Problem Authoring](../problems/README.md) - Creating and configuring problems
