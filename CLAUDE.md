# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

SlopCodeBench (SCBench) is a benchmark for evaluating coding agents under iterative specification refinement. Agents implement a spec, then extend their own code as the spec changes through checkpoints, exposing behaviors like path dependence, non-convergence, and trade-offs between explicit handling and structural stability.

## Essential Commands

### Setup and Installation
```bash
uv sync                          # Install dependencies (Python 3.12+ required)
```

### Running Agents
```bash
# Run an agent on a problem
uv run slop-code run \
  --agent claude_code \
  --model anthropic/opus-4.5 \
  --environment configs/environments/docker-python3.12-uv.yaml \
  --prompt configs/prompts/just-solve.jinja \
  --problem file_backup \
  thinking=low \
  version=2.0.51

# Run multiple problems
uv run slop-code run --problem file_backup --problem execution_server ...
```

**Run parameters:**
- `thinking=none|low|medium|high` - Extended thinking budget (low=10k, medium=20k, high=40k tokens)
- `version=X.Y.Z` - Agent version to use
- Results saved to: `outputs/{model}/{agent}-{prompt}_{params}_{timestamp}/`

### Evaluation
```bash
# Evaluate a run directory
slop-code eval outputs/<run-directory>/

# Grade code quality with LLM judge
slop-code metrics judge \
  --rubric configs/rubrics/llm_judge.jsonl \
  --model <model on openrouter> \
  --criteria-template configs/rubrics/templates/criteria_with_pn.j2 \
  --prefix-template configs/rubrics/templates/no_expl.j2
```

### Testing
```bash
uv run pytest -q                          # Run all tests
uv run pytest tests/path/to/test_file.py  # Run specific test file
uv run pytest -xvs                        # Verbose with early exit on failure
```

### Code Quality
```bash
uv run ruff check .                       # Lint
uv run isort .                            # Format imports
```

## Architecture

### Core Module Structure

**`src/slop_code/`** - Main library organized into:

- **`agent_runner/`** - Agent lifecycle management and execution
  - `agent.py` - Agent base class and protocol
  - `registry.py` - Agent and config registration system
  - `state.py` - Agent state management across checkpoints
  - `trajectory.py` - Execution history tracking
  - `agents/` - Agent implementations (claude_code, codex, gemini, miniswe, opencode, openhands)
  - `credentials.py` - API key and credential management

- **`execution/`** - Isolated execution environments
  - `session.py` - Session lifecycle: workspace + runtime coordination
  - `workspace.py` - Isolated directories, snapshots, file operations
  - `runtime.py` - `SubmissionRuntime` protocol for command execution
  - `docker_runtime/` - Docker container execution with networking and setup scripts
  - `snapshot.py` - Capturing workspace state and diffs between checkpoints
  - `assets.py` - Static asset resolution and placeholder substitution
  - `models.py` - `EnvironmentSpec` and related Pydantic models

- **`evaluation/`** - Pytest-based test execution and validation
  - `config.py` - `ProblemConfig`, `CheckpointConfig`, `MarkerConfig` definitions
  - `pytest_runner.py` - `PytestRunner` orchestrates pytest execution via uvx
  - `report.py` - `CorrectnessResults`, `TestResult`, and `GroupType` (CORE, FUNCTIONALITY, REGRESSION, ERROR)

- **`metrics/`** - Code quality measurement
  - `driver.py` - Quality metric orchestration
  - `grade.py` - Grading logic and scoring
  - `models.py` - Core data models for metrics
  - `checkpoint/` - Per-checkpoint quality tracking and extraction
  - `summary/` - Aggregation and run-level statistics
  - `languages/` - Language-specific parsers (Python, JavaScript, etc.)
  - `rubric/` - LLM judge templates and criteria

- **`entrypoints/`** - CLI and command handlers
  - `cli.py` - Main Typer application entry point (registered as `slop-code`)
  - `commands/` - Individual command implementations (run_agent, eval_*, docker, etc.)
  - `config/` - Run configuration loading and resolvers
  - `problem_runner/` - Problem execution driver and state management
  - `evaluation/` - Evaluation command drivers

- **`dashboard/`** - Dash-based visualization UI
  - `app.py` - Main Dash application
  - `pages/` - Individual dashboard pages (overview, checkpoints, quality, efficiency, etc.)
  - `graphs/` - Plotly graph components

- **`common/`** - Shared utilities
  - `common.py` - General helpers
  - `constants.py` - System-wide constants
  - `llms.py` - LLM API interactions via litellm
  - `paths.py` - Path resolution utilities

### Key Architectural Patterns

**Session → Workspace → Runtime Flow:**
1. `Session` manages overall execution lifecycle
2. `Workspace` provides isolated directory with file operations and snapshotting
3. `SubmissionRuntime` (Docker or Local) executes commands and captures output
4. Snapshots capture state between checkpoints for comparison

**Agent Execution Flow:**
1. Agent registered via `register_agent()` and `register_agent_config()`
2. `ProblemRunner` loads problem config and creates workspace
3. For each checkpoint:
   - Agent receives spec and implements solution
   - `Session.spawn()` creates runtime
   - Evaluation runs test cases via adapters
   - Workspace snapshot captures final state
   - Quality metrics computed via language parsers
4. Results aggregated into `CorrectnessResults` and quality reports

**Problem Evaluation Flow:**
1. `ProblemConfig` defines checkpoints with pytest markers
2. Each checkpoint has `checkpoint_N.md` (spec) and `tests/test_checkpoint_N.py` (tests)
3. `PytestRunner` copies tests to workspace, generates pytest.ini with markers
4. Pytest runs via `uvx` (isolated from solution environment)
5. Tests categorized by markers: unmarked=CORE, `@pytest.mark.functionality`=FUNCTIONALITY, `@pytest.mark.error`=ERROR, prior checkpoint tests=REGRESSION
6. `PassPolicy` ("core-cases" or "all-non-error-cases") determines checkpoint success
7. Metrics computed: correctness (pass/fail) + quality (complexity, duplication, etc.)

**Configuration Hierarchy:**
- `configs/agents/*.yaml` - Agent definitions
- `configs/models/*.yaml` - Model specifications
- `configs/environments/*.yaml` - Runtime environments (Docker, local)
- `configs/prompts/*.jinja` - Agent prompt templates
- `configs/runs/*.yaml` - Complete run configurations
- `problems/*/config.yaml` - Problem-specific settings (inline checkpoints)

### Problem Structure

Each problem in `problems/` follows this pattern:
```
problem_name/
├── config.yaml              # Problem metadata and inline checkpoint definitions
├── checkpoint_1.md          # Specification for checkpoint 1
├── checkpoint_2.md          # Specification for checkpoint 2
└── tests/
    ├── conftest.py          # Pytest configuration (entrypoint, checkpoint fixtures)
    ├── test_checkpoint_1.py # Tests for checkpoint 1
    ├── test_checkpoint_2.py # Tests for checkpoint 2
    ├── data/                # Test case data
    │   ├── checkpoint_1/
    │   │   ├── core/        # Core test cases (must pass)
    │   │   ├── hidden/      # Functionality tests (optional)
    │   │   └── errors/      # Error handling tests
    │   └── checkpoint_2/
    └── assets/              # Static test files
```

**Modern config.yaml structure** (checkpoints are inline, not separate files):
```yaml
name: problem_name
entry_file: main_command
timeout: 20
checkpoints:
  checkpoint_1:
    version: 1
    order: 1
    state: Core Tests
  checkpoint_2:
    version: 1
    order: 2
    state: Extended Features
test_dependencies:
  - pyyaml  # Additional packages for test environment
markers:  # Custom pytest markers beyond built-ins
  custom_marker:
    description: Custom test category
    group: Functionality
```

## Important Technical Notes

### Configuration System
- All configuration uses Pydantic models with strict validation
- OmegaConf used for YAML loading with resolvers
- Checkpoints are now defined inline in `config.yaml`, not as separate `checkpoint_N/config.yaml` files
- Static assets support placeholder resolution (e.g., `%%%ENTRYPOINT:entry_file%%%`)

### Agent Implementation
- Agents must implement `Agent` protocol from `agent_runner/agent.py`
- Lifecycle methods: `setup()`, `run()`, `reset()`, `cleanup()`
- State preserved between checkpoints via `AgentState`
- Credentials loaded from environment variables via `credentials.py`

### Docker Execution
- First run builds Docker images (5-10 minutes), subsequent runs are fast
- Images cached per agent version
- Workspaces mounted into containers with isolated networking
- Setup commands run before each checkpoint

### Evaluation System
- **GroupType**: CORE (must pass), FUNCTIONALITY (optional), REGRESSION (from prior checkpoints), ERROR (expected failures)
- **PassPolicy**: `"core-cases"` (all CORE tests pass), `"all-non-error-cases"` (CORE + FUNCTIONALITY + REGRESSION all pass)
- **Markers**: Tests categorized by pytest markers (`@pytest.mark.error`, `@pytest.mark.functionality`)
- **Isolation**: Tests run via `uvx` for complete isolation from solution environment

### Quality Metrics
- Language-specific parsers extract AST information
- Metrics: cyclomatic complexity, duplication, code churn, maintainability index
- ast-grep rules in `configs/ast-grep-rules/` for pattern-based analysis
- LLM judge for subjective quality assessment via rubric templates

### Logging and Debugging
- Uses `structlog` with structured logging throughout
- Set `verbose=True` in logger calls for detailed output
- Workspace snapshots enable diffing between checkpoints
- `outputs/` contains full execution artifacts per run

## Common Patterns

### Adding a New Agent
1. Create agent class in `src/slop_code/agent_runner/agents/`
2. Implement `Agent` protocol (setup, run, reset, cleanup)
3. Create config class extending `AgentConfigBase`
4. Register with `register_agent()` and `register_agent_config()`
5. Add YAML config to `configs/agents/`
6. Document in `docs/agents/agents/`

### Adding a New Problem
1. Design checkpoints and spec (see `docs/contributing-problems/`)
2. Create directory structure in `problems/`
3. Write `config.yaml` with inline checkpoint definitions
4. Write `checkpoint_N.md` for each checkpoint specification
5. Create `tests/conftest.py` with entrypoint/checkpoint fixtures
6. Write `tests/test_checkpoint_N.py` for each checkpoint
7. Add test data in `tests/data/checkpoint_N/{core,hidden,errors}/`
8. Use pytest markers for test categorization (`@pytest.mark.error`, etc.)
9. Validate with `slop-code eval` and submit PR

### Running Evaluation on Existing Workspace
```bash
# Evaluate checkpoint without re-running agent
slop-code eval checkpoint \
  --workspace outputs/{run}/submissions/{problem}/checkpoint_N/ \
  --problem {problem} \
  --checkpoint checkpoint_N
```

### Extracting Quality Metrics
```bash
# Run static analysis on checkpoint
slop-code metrics static \
  --workspace outputs/{run}/submissions/{problem}/checkpoint_N/
```

## Development Workflow

1. **Branch from main** - Latest stable code on `main`
2. **Run tests** - `uv run pytest -q` before committing
3. **Lint** - `uv run ruff check .` and `uv run isort .`
4. **Commit style** - Short, capitalized summaries (e.g., "Fix Docker runtime cleanup")
5. **PR** - Include description, link issues, note tests run, add screenshots for UI changes

## Known Limitations

- Docker required - no pure local execution for benchmarks
- First run slow due to image builds (cached afterward)
- Some agents (OpenHands) require additional dependencies (see `dependency-groups.openhands`)
- LLM judge quality depends on model capabilities
- Workspace diffs large for binary files

## Key Files to Reference

- `src/slop_code/agent_runner/agent.py` - Agent protocol definition
- `src/slop_code/execution/session.py` - Execution session management
- `src/slop_code/evaluation/pytest_runner.py` - Pytest execution orchestration
- `src/slop_code/entrypoints/problem_runner/driver.py` - Problem execution driver
- `docs/execution/README.md` - Execution architecture deep dive
- `docs/evaluation/README.md` - Evaluation system guide
- `docs/problems/tutorial.md` - Problem creation tutorial
