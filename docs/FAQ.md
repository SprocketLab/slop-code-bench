# Frequently Asked Questions (FAQ)

## Getting Started

### What is SlopCodeBench?
SlopCodeBench measures code erosion under iterative specification refinement — quantifying how code quality degrades as AI agents iterate on programming problems. It helps evaluate how agents handle evolving requirements.

### What are the system requirements?
- **Python 3.12+**
- **Docker** (installed and running)
- **8GB+ RAM** recommended
- **10GB+ disk space** for Docker images and workspaces
- API keys for the agents you want to test

### How long does the first run take?
First run takes 5-10 minutes because Docker images need to build. Subsequent runs are much faster (typically 1-2 minutes per problem depending on the agent and model).

### Do I need Docker?
Yes, Docker is required for isolated execution environments. This ensures reproducibility and prevents agents from affecting your local system.

---

## Running Benchmarks

### What does `thinking=low|medium|high` mean?
This controls the extended thinking token budget for models that support extended thinking:
- `low` = 10,000 tokens
- `medium` = 20,000 tokens
- `high` = 40,000 tokens

### What does the `version` parameter do?
Specifies the agent version to use (e.g., `version=2.0.51`). If omitted, the latest version is used. This is useful for reproducing results or testing specific agent versions.

### Can I run multiple problems at once?
Yes, you can specify multiple `--problem` flags:
```bash
uv run slop-code run --problem file_backup --problem execution_server
```

### How do I run with a different agent?
Use the `--agent` flag with one of the supported agents:
- `claude_code`
- `codex`
- `gemini`
- `miniswe`
- `opencode`
- `openhands`

See [Agent Guide](agents/README.md) for configuration details.

### Where are results saved?
Results are saved to `outputs/{model_name}/{agent}-{prompt}_{params}_{timestamp}/`

Each run creates:
- `results.json` - Evaluation results
- `overall_quality.json` - Code quality metrics
- `submissions/` - Agent-generated code
- `workspaces/` - Execution environments

---

## Evaluation

### What's the difference between correctness and quality metrics?
- **Correctness**: Does the solution pass the test cases? (Pass/Fail)
- **Quality**: How clean, maintainable, and well-structured is the code? (Metrics like complexity, duplication, etc.)

### How do I interpret pass policies?
Pass policies determine what counts as "passing" an evaluation:
- `ALL_CASES` - All test cases must pass
- `ANY_CASE` - At least one test case must pass
- `MAJORITY` - More than 50% of test cases must pass

### What are checkpoints?
Checkpoints represent stages of specification refinement. Problems have multiple checkpoints, each adding requirements or complexity. This tests how code quality evolves as specifications change.

### Can I create custom test cases?
Yes! See the [Problem Tutorial](problems/tutorial.md) for a step-by-step guide on creating problems with custom test cases.

---

## Problems

### How do I create a new problem?
Follow the [Problem Tutorial](problems/tutorial.md) which walks through creating a complete problem in ~30 minutes. Also see the [Contributing Guide](../CONTRIBUTING.md).

### What makes a good problem?
Good problems:
- Take ~40 hours to solve well (not just make it work)
- Have clear, incremental checkpoints
- Test realistic refactoring scenarios
- Encourage flexible, maintainable code over quick hacks

See [Problem Design Guide](contributing-problems/README.md) for details.

---

## Agents

### Which agent should I use?
It depends on your use case:
- **Claude Code**: Best for complex refactoring, supports extended thinking
- **Codex**: OpenAI's code model
- **Gemini**: Google's model with long context
- **MiniSWE**: Lightweight agent for quick testing
- **OpenCode**: DeepSeek-based agent
- **OpenHands**: Multi-tool agent

See agent-specific docs in [docs/agents/agents/](agents/agents/).

### How do I configure API keys?
Set environment variables for your provider:
```bash
export ANTHROPIC_API_KEY="your-key"
export OPENAI_API_KEY="your-key"
export GOOGLE_API_KEY="your-key"
```

Or see [Credentials Guide](agents/credentials.md) for file-based configuration.

### Can I add a new agent?
Yes! See the [Agent Implementation Guide](agents/agent-class.md) and [Contributing Guide](../CONTRIBUTING.md).

---

## Troubleshooting

### Docker build fails
```bash
# Clean Docker cache and rebuild
docker system prune -a
uv run slop-code docker build-base --environment configs/environments/docker-python3.12-uv.yaml
```

### "Command not found: docker"
Docker is not running or not installed. Install Docker Desktop and ensure it's running:
```bash
docker ps  # Should list running containers
```

### API key errors
Verify your environment variable is set:
```bash
echo $ANTHROPIC_API_KEY  # Should print your key
```

### Out of disk space
Docker images can take significant space. Clean up:
```bash
docker system prune -a  # Remove unused images
docker volume prune     # Remove unused volumes
```

### Tests fail but solution looks correct
Check the expected outputs in the problem's test cases. Some test failures may be due to:
- Formatting differences (whitespace, newlines)
- Numeric precision (for floating point)
- Output order (for unordered results)

See [Troubleshooting Guide](evaluation/troubleshooting.md) for handling edge cases.

---

## Metrics

### What metrics are collected?
- **Correctness**: Pass/fail for each test case
- **Complexity**: Cyclomatic complexity, nesting depth
- **Code Quality**: Duplication, code smells, maintainability
- **Size**: Lines of code, file count
- **Deltas**: Changes between checkpoints

See [Metrics Guide](metrics/README.md) for complete list.

### How do I run the LLM judge?
```bash
slop-code metrics judge \
  --rubric configs/rubrics/llm_judge.jsonl \
  --model <model on openrouter> \
  --criteria-template configs/rubrics/templates/criteria_with_pn.j2
```

### What's a good score?
It depends on the problem and checkpoint. See [Interpreting Results](metrics/interpreting-results.md) for guidance on what different metric values mean.

---

## Contributing

### How do I contribute a problem?
1. Design the problem (see [Design Philosophy](contributing-problems/README.md))
2. Write pytest tests (see [Tutorial](problems/tutorial.md))
3. Test thoroughly (see [Checklist](contributing-problems/checklist.md))
4. Submit a PR (see [Contributing Guide](../CONTRIBUTING.md))

### How long does PR review take?
This is early-stage software. Review times vary. We'll work with you to iterate on the problem design.

### Can I contribute to documentation?
Absolutely! Documentation improvements are very welcome. See the [Contributing Guide](../CONTRIBUTING.md).

---

## Advanced

### Can I run evaluations in parallel?
Yes, you can run evaluations with multiple workers:
```bash
slop-code eval outputs/my_run --num-workers 4
```
This speeds up evaluation by running multiple problems or checkpoints in parallel.

### How do I create custom metrics?
Custom metrics require modifying the metrics system. This is not yet documented. See existing metrics in `src/slop_code/metrics/` for examples.

### Can I use this in CI/CD?
Yes, you can integrate SlopCodeBench into your CI/CD pipeline. Results are saved in JSON format for easy parsing.

### How do I reproduce results from a paper?
Use the same:
- Agent version (via `version=X.Y.Z`)
- Model
- Environment configuration
- Problem set
- Random seed (if applicable)

---

## Still have questions?

- Check the [full documentation](README.md)
- Open a [GitHub Issue](https://github.com/SprocketLab/slop-code-bench/issues)
- See [Known Issues](KNOWN_ISSUES.md) for current limitations
