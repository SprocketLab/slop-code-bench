<div align="center">
<h1 > SlopCodeBench (SCBench)</h1>

  [![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
  [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
  [![GitHub stars](https://img.shields.io/github/stars/SprocketLab/slop-code-bench)](https://github.com/SprocketLab/slop-code-bench/stargazers)

  [🌐 Website](https://www.scbench.ai) | [📝 Blog Post](https://gabeorlanski.github.io/posts/slop-code-bench) | [📄 Paper](#citing-us)
</div>

![](assets/overview.png)
---

**SlopCodeBench** measures *code erosion under iterative specification refinement* — quantifying how code quality degrades as AI agents iterate on programming problems. As agents receive feedback and refine their solutions, they often introduce subtle degradations: unnecessary abstractions, defensive programming patterns, and structural bloat. This benchmark captures and measures that drift.


> [!NOTE]
> This is an initial release. We're actively developing and welcome feedback via [GitHub Issues](https://github.com/SprocketLab/slop-code-bench/issues).

## 🚀 Install

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
git clone https://github.com/SprocketLab/slop-code-bench.git && cd slop-code-bench && uv sync
export ANTHROPIC_API_KEY="your-key"

# Run!
uv run slop-code run \
  --agent configs/agents/claude_code-2.0.51.yaml \
  --model anthropic/opus-4.5 \
  --environment configs/environments/docker-python3.12-uv.yaml \
  --prompt configs/prompts/just-solve.jinja \
  --problem file_backup \
  --problem execution_server \
  thinking=low
```

Results are saved to:
```
outputs/opus-4.5/claude_code-just-solve_low_{timestamp}/
```

Docker images are built automatically on first run.

## 📊 Evaluation

**Evaluate a run:**
```bash
slop-code eval outputs/your-run-directory/
```

**Grade code quality with LLM judge:**
```bash
slop-code metrics judge \
  --rubric configs/rubrics/llm_judge.jsonl \
  --model <model on openrouter> \
  --criteria-template configs/rubrics/templates/criteria_with_pn.j2 \
  --prefix-template configs/rubrics/templates/no_expl.j2
```

## Contributing

We welcome contributions. Two ways to help:

- **Add problems** — Expand the benchmark with new evaluation scenarios. See the [Problem Tutorial](docs/problems/tutorial.md) and [Contributing Guide](CONTRIBUTING.md).
- **Add agents** — Integrate new coding agents. See the [Agent Guide](docs/agents/README.md) and [Contributing Guide](CONTRIBUTING.md).

This is early-stage software. Your contributions will shape its direction.

## 📚 Documentation

| Guide | Description |
|-------|-------------|
| [📖 Problem Tutorial](docs/problems/tutorial.md) | Create your first problem (30 min hands-on) |
| [📋 Quick Reference](docs/problems/quick-reference.md) | One-page cheat sheet for problem authoring |
| [🤖 Agent Guide](docs/agents/README.md) | Configure agents, models, and credentials |
| [🏗️ Architecture](docs/execution/README.md) | How sessions, workspaces, and runtimes work |
| [✅ Evaluation System](docs/evaluation/README.md) | Test cases, adapters, loaders, and verifiers |
| [💡 Problem Design](docs/contributing-problems/README.md) | What makes a good evaluation problem |

## 📖 Citing Us

If you found this useful, please cite us as:
```bibtex
@misc{slopcodebench,
  title        = {SlopCodeBench: Measuring Code Erosion Under Iterative Specification Refinement},
  author       = {Gabriel Orlanski and Devjeet Roy and Alexander Yun and 
                  Changho Shin and Alex Gu and Albert Ge and 
                  Dyah Adila and Aws Albarghouthi and Frederic Sala},
  year         = {2025},
  howpublished = {\url{https://github.com/your-repo}},
}
```
