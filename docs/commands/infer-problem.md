---
version: 1.0
last_updated: 2025-12-17
---

# infer-problem

Run inference on a single problem with explicit configuration.

## Quick Start

```bash
slop-code infer-problem file_backup \
  -a configs/agents/claude_code-2.0.51.yaml \
  -e configs/environments/docker-python3.12-uv.yaml \
  -o outputs/test_run \
  -prompt configs/prompts/just-solve.jinja \
  -m anthropic/sonnet-4.5
```

## Usage

```bash
slop-code infer-problem [OPTIONS] PROBLEM_NAME
```

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `PROBLEM_NAME` | Yes | Name of the problem (must exist in problem directory) |

## Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `-a, --agent` | path | **required** | Path to agent configuration YAML |
| `-e, --environment-config-path` | path | **required** | Path to environment configuration |
| `-o, --output-path` | path | **required** | Path to output directory |
| `-prompt, --prompt-template` | path | **required** | Path to prompt template |
| `-m, --model` | string | **required** | Model in format `{provider}/{model}` |
| `--provider-api-key-env` | string | - | Override API key environment variable |
| `--thinking` | string | - | Thinking budget: none, low, medium, high |
| `--max-thinking-tokens` | int | - | Maximum thinking tokens |
| `-pass, --pass-policy` | enum | `ANY` | Policy to determine checkpoint pass |
| `--evaluate/--no-evaluate` | flag | true | Whether to run evaluation |

## Behavior

This command provides low-level control over running a single problem. It:

1. Loads agent, environment, and prompt configurations
2. Resolves API credentials for the specified provider
3. Builds Docker image if required by agent
4. Runs the agent through all checkpoints
5. Optionally evaluates results after inference

### Thinking Options

`--thinking` and `--max-thinking-tokens` are mutually exclusive:

```bash
# Use preset
--thinking medium

# Use explicit token budget
--max-thinking-tokens 10000
```

## Examples

**Basic run:**
```bash
slop-code infer-problem file_backup \
  -a configs/agents/claude_code-2.0.51.yaml \
  -e configs/environments/docker-python3.12-uv.yaml \
  -o outputs/test \
  -prompt configs/prompts/just-solve.jinja \
  -m anthropic/sonnet-4.5
```

**With extended thinking:**
```bash
slop-code infer-problem file_backup \
  -a configs/agents/claude_code-2.0.51.yaml \
  -e configs/environments/docker-python3.12-uv.yaml \
  -o outputs/test_thinking \
  -prompt configs/prompts/just-solve.jinja \
  -m anthropic/sonnet-4.5 \
  --thinking high
```

**Inference only (no evaluation):**
```bash
slop-code infer-problem file_backup \
  -a configs/agents/claude_code-2.0.51.yaml \
  -e configs/environments/docker-python3.12-uv.yaml \
  -o outputs/infer_only \
  -prompt configs/prompts/just-solve.jinja \
  -m anthropic/sonnet-4.5 \
  --no-evaluate
```

**Custom API key:**
```bash
slop-code infer-problem file_backup \
  -a configs/agents/claude_code-2.0.51.yaml \
  -e configs/environments/docker-python3.12-uv.yaml \
  -o outputs/test \
  -prompt configs/prompts/just-solve.jinja \
  -m anthropic/sonnet-4.5 \
  --provider-api-key-env MY_ANTHROPIC_KEY
```

## Output Structure

```
OUTPUT_PATH/
└── PROBLEM_NAME/
    ├── checkpoint_1/
    │   ├── snapshot/
    │   │   └── <agent code>
    │   └── evaluation.json  # if --evaluate
    ├── checkpoint_2/
    │   └── ...
    └── agent/
        └── <agent artifacts>
```

## See Also

- [run](run.md) - Run agents with unified config system (recommended)
- [eval](eval.md) - Evaluate inference results
