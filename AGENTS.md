# Repository Guidelines

## Project Structure & Module Organization
- `src/slop_code/` holds the core library. Key areas: `entrypoints/` (CLI), `evaluation/`, `execution/`, `agent_runner/`, `metrics/`, and `dashboard/`.
- `tests/` contains the pytest suite, generally mirroring `src/` subpackages.
- `problems/` contains benchmark problems. Each problem has `config.yaml`, `loader.py`, `verifier.py` (optional), and `checkpoint_N/spec.md` plus test case data under `checkpoint_N/core/`.
- `configs/` houses agent, model, prompt, environment, and run configs (e.g., `configs/agents/`, `configs/models/`).
- `docs/` provides guides for agents, evaluation, execution, and problem authoring; `assets/` stores images; `outputs/` stores run artifacts.

## Build, Test, and Development Commands
```bash
uv sync                          # Install dependencies
uv run slop-code --help           # List CLI commands
uv run slop-code run ...          # Run an agent (see README for full example)
slop-code eval outputs/<run-dir>  # Evaluate a run directory
uv run pytest -q                  # Run all tests
uv run pytest tests/path/to/test_file.py
uv run ruff check .               # Lint
uv run isort .                    # Format imports
```

## Coding Style & Naming Conventions
- Python 3.12+, 4-space indentation, max line length 80 (ruff).
- Use `from __future__ import annotations`, `pathlib.Path`, and type annotations for all functions.
- Configuration should use Pydantic models; logging uses `structlog.get_logger(__name__)`.
- Imports are single-line (ruff isort settings); module names are `snake_case`, classes `CapWords`.

## Testing Guidelines
- Framework: pytest (see `pyproject.toml`).
- Test files use `*_test.py` or `test_*.py` under `tests/`.
- No explicit coverage target; add tests for new behavior and edge cases.

## Commit & Pull Request Guidelines
- Commit history favors short, capitalized summaries without scopes (e.g., “Canary Fix”). Keep messages concise and descriptive.
- For problem contributions, follow the PR template in `docs/contributing-problems/checklist.md` (overview, checkpoints, test counts).
- For other PRs, include a clear description, link relevant issues, note tests run, and add screenshots for dashboard/UI changes.

## Configuration & Credentials
- API keys are provided via environment variables (see README). Do not commit secrets.
- Environment/runtime settings live in `configs/environments/` and `configs/providers.yaml`.
