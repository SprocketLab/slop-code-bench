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

## Skills
These skills are discovered at startup from multiple local sources. Each entry
includes a name, description, and file path so you can open the source for full
instructions.
- edge-cases: Analyze checkpoint tests and suggest missing edge cases. Use
  after writing tests or when reviewing test coverage. Invoke with
  `/edge-cases <problem> <checkpoint>`. (file:
  `/home/gabe/Coding/slop-code-bench/.codex/skills/edge-cases/SKILL.md`)
- migrate-tests: Migrate SCBench problems from old loader/verifier style to new
  pytest style, one checkpoint at a time. Use when porting problems that have
  `loader.py` and `verifier.py` files, or when creating `tests/` directories
  with `conftest.py` and `test_checkpoint_*.py` files. (file:
  `/home/gabe/Coding/slop-code-bench/.codex/skills/migrate-tests/SKILL.md`)
- plan-migration: Analyze SCBench problems before migration and create a
  `migrate.md` plan. Use BEFORE migrate-tests to understand the problem
  structure, map groups to types, identify regression handling, and document
  special cases. Invoke with `/plan-migration <problem>`. (file:
  `/home/gabe/Coding/slop-code-bench/.codex/skills/plan-migration/SKILL.md`)
- validate-tests: Validate new-style pytest checkpoint tests against the
  checkpoint spec for SCBench problems. Use when comparing
  `problems/<problem>/tests/checkpoint_N.py` to
  `problems/<problem>/checkpoint_N.md` (or when verifying any checkpoint test
  expectations against the spec). Flag contradictions, out-of-scope tests,
  missing coverage, and ambiguous spec assumptions. (file:
  `/home/gabe/Coding/slop-code-bench/.codex/skills/validate-tests/SKILL.md`)
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
