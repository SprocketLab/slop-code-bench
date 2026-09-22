<div align="center">
<h1 > SlopCodeBench (SCBench)</h1>

  [![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
  [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
  [![GitHub stars](https://img.shields.io/github/stars/SprocketLab/slop-code-bench)](https://github.com/SprocketLab/slop-code-bench/stargazers)
  [![DOI](https://zenodo.org/badge/1118434028.svg)](https://doi.org/10.5281/zenodo.19257129)

  [🌐 Website](https://www.scbench.ai) | [📄 Paper](https://arxiv.org/abs/2603.24755) | [📝 Blog Post](https://gabeorlanski.github.io/posts/slop-code-bench)
</div>

![](assets/overview.png)
---

**SlopCodeBench** evaluates coding agents under iterative specification refinement: the agent implements a spec, then extends its own code as the spec changes. This exposes behaviors that single-shot benchmarks cannot measure, including path dependence, non-convergence, and trade-offs between explicit handling and structural stability. We release SCBench as an open, community-driven evaluation primitive rather than a finalized benchmark.


Problem definitions now live in the separate [scb-problems repository](https://github.com/gabeorlanski/scb-problems) and are also available as a [Harbor dataset](https://registry.harborframework.com/datasets/gabeorlanski/slopcodebench/latest). We actively want more problems; follow [the creating a problem guide](/docs/contributing-problems/) and open a PR there.

> [!NOTE]
> This is an initial release. We're actively developing and welcome feedback via [GitHub Issues](https://github.com/SprocketLab/slop-code-bench/issues).

## Prerequisites

Before installing, ensure you have:
- **Python 3.12+** installed
- **Docker** installed and running ([Get Docker](https://docs.docker.com/get-docker/))
- An **API key** for your chosen agent (e.g., Anthropic, OpenAI, Google)
- **8GB+ RAM** recommended for running evaluations
- **10GB+ disk space** for Docker images and workspaces

## 🚀 Install

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
git clone https://github.com/SprocketLab/slop-code-bench.git && cd slop-code-bench && uv sync
export ANTHROPIC_API_KEY="your-key"

# Run!
uv run slop-code run \
  --agent claude_code \
  --model anthropic/opus-4.5 \
  --environment configs/environments/docker-python3.12-uv.yaml \
  --prompt configs/prompts/just-solve.jinja \
  --problem file_backup \
  --problem execution_server \
  thinking=low \
  version=2.0.51
```

**Parameter Reference:**
- `thinking=none|low|medium|high` - Controls extended thinking budget based on agent.
- `version=X.Y.Z` - Agent version to use.

Results are saved to:
```
outputs/opus-4.5/claude_code-just-solve_low_{timestamp}/
```

**First Run:** Docker images build automatically for that _VERSION_ of the agent (5-10 minutes). Subsequent runs are faster.

### Troubleshooting

**Docker not found:**
```bash
# Check Docker is running
docker ps
# If not running, start Docker Desktop or daemon
```

**API key not found:**
```bash
# Verify your environment variable is set
echo $ANTHROPIC_API_KEY
# Or pass it directly
ANTHROPIC_API_KEY="your-key" uv run slop-code run ...
```

**Out of disk space:**
```bash
# Clean up old Docker images
docker system prune -a
```

For more issues, see [GitHub Issues](https://github.com/SprocketLab/slop-code-bench/issues).

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

- **Add problems** — Expand the benchmark with new evaluation scenarios in the [scb-problems repository](https://github.com/gabeorlanski/scb-problems), also published as a [Harbor dataset](https://registry.harborframework.com/datasets/gabeorlanski/slopcodebench/latest). See the [Problem Tutorial](docs/problems/tutorial.md) and [Contributing Guide](CONTRIBUTING.md).
- **Add agents** — Integrate new coding agents. See the [Agent Guide](docs/agents/README.md) and [Contributing Guide](CONTRIBUTING.md).

This is early-stage software. Your contributions will shape its direction.

## Documentation

| Guide | Description |
|-------|-------------|
| [❓ FAQ](docs/FAQ.md) | Frequently asked questions |
| [📖 Problem Tutorial](docs/problems/tutorial.md) | Create your first problem (30 min hands-on) |
| [📋 Quick Reference](docs/problems/quick-reference.md) | One-page cheat sheet for problem authoring |
| [🤖 Agent Guide](docs/agents/README.md) | Configure agents, models, and credentials |
| [🏗️ Architecture](docs/execution/README.md) | How sessions, workspaces, and runtimes work |
| [✅ Evaluation System](docs/evaluation/README.md) | Test cases, adapters, loaders, and verifiers |
| [💡 Problem Design](docs/contributing-problems/README.md) | What makes a good evaluation problem |
| [⚠️ Known Issues](docs/KNOWN_ISSUES.md) | Current limitations and workarounds |
| [📊 Commands](docs/commands/README.md) | CLI command reference (run, eval, metrics, viz, etc.) |

## Citing Us

If you found this useful, please cite us as:
```bibtex
@misc{Orlanski2026SlopCodeBench,
  author = {Orlanski, Gabriel and Roy, Devjeet and Yun, Alexander and Shin, Changho and Gu, Alex and Ge, Albert and Adila, Dyah and Roberts, Nicholas and Sala, Frederic and Albarghouthi, Aws},
  title = {{SlopCodeBench: Benchmarking How Coding Agents Degrade Over Long-Horizon Iterative Tasks}},
  year = {2026},
  eprint = {2603.24755},
  archivePrefix = {arXiv},
  primaryClass = {cs.SE},
  url = {https://arxiv.org/abs/2603.24755}
}
```
