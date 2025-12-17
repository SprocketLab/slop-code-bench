# Contributing

We welcome contributions. 

## Adding an Agent

Want to evaluate a new coding agent? The framework is designed for this.

### Requirements

1. Implement the `Agent` interface from `src/slop_code/agent_runner/agent.py`
2. Define lifecycle methods: `setup()`, `run()`, `reset()`, `cleanup()`
3. Create an agent configuration YAML in `configs/agents/`
4. Add setup documentation in `docs/agents/`

### Resources

- [Agent interface](src/slop_code/agent_runner/agent.py)
- [Example agents](src/slop_code/agent_runner/agents/)
- [Agent setup docs](docs/agents/)
- [Architecture overview](docs/execution/index.md)

## Adding a Problem

Contribute new evaluation problems to expand the benchmark. The process has three steps: design your problem, implement it, then validate and submit.

### Step 1: Design Your Problem

Start with a full problem concept, then break it into checkpoints. Good problems test whether agents can write flexible, maintainable code that handles progressive requirements.

- **[Problem Design Philosophy](docs/contributing-problems/README.md)** - What makes a good problem, checkpoint patterns, common pitfalls
- **[Example: Designing a Calculator Problem](docs/contributing-problems/example_process.md)** - See the design thinking process in action

### Step 2: Implement Your Problem

Turn your design into code with test cases, loader, and verifier.

- **[Step-by-Step Tutorial](docs/problems/tutorial.md)** - Create your first problem (30 min hands-on)
- **[Problem Structure Reference](docs/problems/structure.md)** - Directory layout and file roles
- **[Test Case Authoring](docs/problems/test-cases.md)** - Writing effective test cases
- **[Creating Loaders & Verifiers](docs/guides/creating-loaders-and-verifiers.md)** - Implementation patterns

### Step 3: Validate & Submit

Ensure your problem works and submit a PR.

- **[Validation Checklist](docs/contributing-problems/checklist.md)** - Pre-submission checklist with PR guidance
- **[Troubleshooting](docs/problems/troubleshooting.md)** - Common issues and solutions

### Quick Reference

| Component | Description |
|-----------|-------------|
| `config.yaml` | Problem metadata and adapter configuration |
| `checkpoint_N/spec.md` | What agents must build at each checkpoint |
| `checkpoint_N/core/` | Test case definitions |
| `loader.py` | Discovers and loads test cases |
| `verifier.py` | Validates outputs (optional) |

## Development

### Setup

```bash
uv sync
```

### Testing

```bash
uv run pytest -q                           # Run all tests
uv run pytest tests/path/to/test_file.py   # Run specific test
```

### Linting

```bash
uv run ruff check .   # Lint
uv run isort .        # Format imports
```

### Code Standards

- Line length: 80 characters
- Use `from __future__ import annotations` in all modules
- Use pathlib (`Path`) instead of `os.path`
- Type all function signatures
- Use Pydantic models for configuration
- Use `structlog.get_logger(__name__)` for logging

## Getting Help

```bash
uv run slop-code --help
```

Or look at the [documentation](docs/).
