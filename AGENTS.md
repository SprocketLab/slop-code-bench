# Repository Guidelines

## Project Structure & Module Organization
- `src/slop_code/` holds the core library. Key areas: `entrypoints/` (CLI), `evaluation/`, `execution/`, `agent_runner/`, `metrics/`, and `dashboard/`.
- `tests/` contains the pytest suite, generally mirroring `src/` subpackages.
- `problems/` contains benchmark problems. Each problem has `config.yaml`, `checkpoint_N.md` (specs), and a `tests/` directory with `conftest.py`, `test_checkpoint_N.py` files, and test data under `tests/data/`.
- `configs/` houses agent, model, prompt, environment, and run configs (e.g., `configs/agents/`, `configs/models/`).
- `docs/` provides guides for agents, evaluation, execution, and problem authoring; `assets/` stores images; `outputs/` stores run artifacts.

Note: Dashboard visualization features are partially documented via the `viz diff` command. See `docs/commands/viz.md` for details.

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

## Skills
These skills are discovered at startup from multiple local sources. Each entry
includes a name, description, and file path so you can open the source for full
instructions.
- edge-cases: Analyze checkpoint tests and suggest missing edge cases. Use
  after writing tests or when reviewing test coverage. Invoke with
  `/edge-cases <problem> <checkpoint>`. (file:
  `/home/gabe/Coding/slop-code-bench/.codex/skills/edge-cases/SKILL.md`)
- skill-creator: Guide for creating effective skills. This skill should be used
  when users want to create a new skill (or update an existing skill) that
  extends Codex's capabilities with specialized knowledge, workflows, or tool
  integrations. (file:
  `/home/gabe/.codex/skills/.system/skill-creator/SKILL.md`)
- skill-installer: Install Codex skills into `$CODEX_HOME/skills` from a
  curated list or a GitHub repo path. Use when a user asks to list installable
  skills, install a curated skill, or install a skill from another repo
  (including private repos). (file:
  `/home/gabe/.codex/skills/.system/skill-installer/SKILL.md`)
