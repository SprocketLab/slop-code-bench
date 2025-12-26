---
version: 1.0
last_updated: 2025-12-26
---

# Run Configuration Guide

This guide covers the unified run configuration system for the `slop-code run` command. The system provides a Hydra-style configuration approach with priority-based merging, flexible path resolution, and output path interpolation.

## Quick Start

### Minimal Configuration File

Create a config file with just the settings you want to override:

```yaml
# my_run.yaml
model:
  provider: anthropic
  name: opus-4.5
```

Run with:

```bash
slop-code run --config my_run.yaml --problem file_backup
```

### Select Problems in the Config

Pin the problem list in your config so you can omit `--problem` on the CLI:

```yaml
# my_run.yaml
problems:
  - file_backup
  - trajectory_api
model:
  provider: anthropic
  name: opus-4.5
```

Run with:

```bash
slop-code run --config my_run.yaml
```

### CLI-Only (No Config File)

Use flags and defaults:

```bash
slop-code run \
  --model anthropic/sonnet-4.5 \
  --problem file_backup
```

### Mixed: Config + CLI Overrides

```bash
slop-code run \
  --config my_run.yaml \
  --model anthropic/opus-4.5 \
  thinking=high
```

## Configuration Priority

The system merges configuration from multiple sources with explicit precedence:

```
CLI overrides (key=value)    <- Highest priority
CLI flags (--agent, etc.)
Config file values
Built-in defaults            <- Lowest priority
```

### Example: Priority in Action

Given this config file:

```yaml
# my_run.yaml
model:
  provider: anthropic
  name: sonnet-4.5
thinking: low
```

And this command:

```bash
slop-code run --config my_run.yaml thinking=high
```

The result is:
- `model.provider`: "anthropic" (from config file)
- `model.name`: "sonnet-4.5" (from config file)
- `thinking`: "high" (CLI override wins)

## Configuration Fields

### Field Reference

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `agent` | string \| dict | `claude_code-2.0.51` | Agent configuration |
| `environment` | string \| dict | `docker-python3.12-uv` | Environment configuration |
| `prompt` | string | `just-solve` | Prompt template |
| `model` | object | `anthropic/sonnet-4.5` | Model configuration |
| `thinking` | string \| object | `none` | Thinking budget |
| `pass_policy` | string | `any` | Checkpoint pass policy |
| `one_shot` | object | disabled | Collapse checkpoints; prefix is a Jinja template with `idx` |
| `problems` | list<string> | `[]` | Specific problems to run (otherwise auto-discover) |
| `save_dir` | string | `outputs` | Base directory for run outputs |
| `save_template` | string | (template) | Output path template with interpolation |

### agent

The agent configuration. Can be:

- **Bare name**: Resolves from `configs/agents/` (e.g., `claude_code-2.0.51`)
- **Path**: Absolute or relative path to a YAML file (e.g., `./my_agent.yaml`)
- **Inline dict**: Full configuration embedded in the config file

```yaml
# Bare name (recommended)
agent: claude_code-2.0.51

# Explicit path
agent: ./custom_agents/my_agent.yaml

# Inline configuration
agent:
  type: claude_code
  binary: claude
  permission_mode: bypassPermissions
  version: 2.0.51
  cost_limits:
    cost_limit: 0
    step_limit: 100
```

### environment

The execution environment configuration. Same resolution rules as `agent`:

```yaml
# Bare name (resolves from configs/environments/)
environment: docker-python3.12-uv

# Explicit path
environment: /path/to/custom_env.yaml

# Inline configuration
environment:
  type: docker
  name: custom-python
  docker:
    image: python:3.12-slim
    workdir: /workspace
```

### prompt

The prompt template. Resolves from `configs/prompts/` with `.jinja` extension:

```yaml
# Bare name (resolves to configs/prompts/just-solve.jinja)
prompt: just-solve

# Other built-in options
prompt: simple
prompt: best_practice

# Explicit path
prompt: ./my_prompts/custom.jinja
```

### model

Model configuration specifying provider and model name:

```yaml
model:
  provider: anthropic  # Used for credential lookup
  name: sonnet-4.5     # Model name from catalog
```

**Built-in providers**: `anthropic`, `openai`, `google`, `openrouter`

For complete model configuration options, agent-specific settings, and thinking configuration, see the [Models Guide](../agents/models.md). For provider setup, see [Providers Guide](../agents/providers.md).

### thinking

Thinking budget configuration. Can be a preset string or an object:

**Preset strings**: `none`, `disabled`, `low`, `medium`, `high`

```yaml
# Preset (recommended)
thinking: medium

# Explicit token budget
thinking:
  max_tokens: 10000

# Preset via object form
thinking:
  preset: high
```

**Note**: `preset` and `max_tokens` are mutually exclusive.

### pass_policy

Policy for determining whether a checkpoint passes:

| Value | Description |
|-------|-------------|
| `any` | Pass if any case passes |
| `any-case` | Same as `any` |
| `all-cases` | Pass only if all cases pass |
| `all-non-error-cases` | Pass if all non-error cases pass |
| `core-cases` | Pass if all core cases pass |
| `any-core-cases` | Pass if any core case passes |
| `all-core-cases` | Same as `core-cases` |

```yaml
pass_policy: all-cases
```

### one_shot

Collapse all checkpoints into a single agent run while evaluating the final
checkpoint's cases. All checkpoint specs are concatenated in order; the
separator is a Jinja template rendered with `idx` (1-based checkpoint index)
followed by `"\n"`. Set `include_first_prefix: true` to emit the prefix before
the first checkpoint as well.

```yaml
one_shot:
  enabled: true
  prefix: "Next checkpoint ({{ idx }}):"
  include_first_prefix: false
```

### problems

Optional list of problem names to run. If omitted or empty, `slop-code run`
discovers all available problems under your problems directory. CLI
`--problem` flags override this list when provided.

```yaml
problems:
  - file_backup
  - trajectory_api
```

### save_dir

Base directory for run outputs:

```yaml
# Default
save_dir: outputs

# Custom directory
save_dir: /data/experiments
save_dir: ~/runs
```

### save_template

Output path template with interpolation support. The template is appended to `save_dir`:

```yaml
# Default template (includes agent version when available)
save_template: ${model.name}/${agent.type}-${agent.version}_${prompt}_${thinking}_${now:%Y%m%dT%H%M}

# Simple template
save_template: ${model.name}/${now:%Y%m%d}

# Custom structure
save_template: ${agent.type}/${model.name}/${prompt}_${now:%Y%m%dT%H%M}
```

The final output path is `{save_dir}/{save_template}`.

See [Output Path Interpolation](#output-path-interpolation) for available variables.

## Path Resolution

The system uses a two-tier lookup for bare names (names without path separators):

### Resolution Order

1. **Direct path**: If the value is a path to an existing file, use it directly
2. **Package configs**: `configs/{category}/{name}{extension}`
3. **CWD**: `./{name}{extension}`
4. **CWD with category**: `./{category}/{name}{extension}`

### Extensions by Category

| Category | Extension |
|----------|-----------|
| agents | `.yaml` |
| environments | `.yaml` |
| prompts | `.jinja` |

### Example Resolution

For `agent: my_agent`:

1. Check if `my_agent` is a path to an existing file
2. Try `configs/agents/my_agent.yaml`
3. Try `./my_agent.yaml`
4. Try `./agents/my_agent.yaml`

### Error Messages

If resolution fails, the error message shows all searched paths:

```
Config 'my_agent' not found. Searched:
  configs/agents/my_agent.yaml
  ./my_agent.yaml
  ./agents/my_agent.yaml
```

## Output Path Interpolation

The `save_template` field supports OmegaConf interpolation with these variables:

| Variable | Description | Example |
|----------|-------------|---------|
| `${model.name}` | Model name | `sonnet-4.5` |
| `${model.provider}` | Model provider | `anthropic` |
| `${agent.type}` | Agent type from config | `claude_code` |
| `${agent.version}` | Agent version (cleanly omitted if not set) | `2.0.51` |
| `${prompt}` | Prompt template stem | `just-solve` |
| `${thinking}` | Thinking preset | `medium` |
| `${env.name}` | Environment name | `python3.12` |
| `${now:FORMAT}` | Timestamp with strftime | `20251210T1430` |

**Note:** When `${agent.version}` is not set in the agent config, it is cleanly removed from the path along with any surrounding `-` or `_` characters. For example, `${agent.type}-${agent.version}_${prompt}` becomes `${agent.type}_${prompt}` when version is missing.

### Timestamp Format

The `${now:FORMAT}` resolver uses Python strftime format:

```yaml
# Default format (%Y%m%dT%H%M)
save_template: ${model.name}/${now}  # -> sonnet-4.5/20251210T1430

# Custom format
save_template: ${model.name}/${now:%Y-%m-%d}  # -> sonnet-4.5/2025-12-10
save_template: ${now:%Y%m%d_%H%M%S}/${model.name}  # -> 20251210_143022/sonnet-4.5
```

### Default Output Path

```yaml
save_dir: outputs
save_template: ${model.name}/${agent.type}-${agent.version}_${prompt}_${thinking}_${now:%Y%m%dT%H%M}
```

Produces paths like:
- With version: `outputs/sonnet-4.5/claude_code-2.0.51_just-solve_none_20251210T1430`
- Without version: `outputs/sonnet-4.5/claude_code_just-solve_none_20251210T1430`

## CLI Usage

### Command Syntax

```bash
slop-code run [OPTIONS] [OVERRIDES]...
```

### Flags

| Flag | Description |
|------|-------------|
| `--config PATH` | Path to run configuration YAML file |
| `--agent NAME` | Agent config (bare name or path) |
| `--environment NAME` | Environment config (bare name or path) |
| `--prompt NAME` | Prompt template (bare name or path) |
| `--model PROVIDER/NAME` | Model selection (e.g., `anthropic/sonnet-4.5`) |
| `--problem NAME` | Problem to run (can be repeated) |
| `--num-workers N` | Number of parallel workers |
| `--evaluate/--no-evaluate` | Run evaluation after agent |
| `--provider-api-key-env VAR` | Override API key environment variable (see [Credentials Guide](../agents/credentials.md)) |
| `--resume PATH` | Resume from an existing run directory (loads saved config; mutually exclusive with `--config`, `--agent`, `--environment`, `--prompt`, `--model`, and overrides) |
| `--dry-run` | Preview what would be done without making changes |
| `--live-progress/--no-live-progress` | Control live progress display (default: enabled) |

### CLI Overrides

Positional arguments in `key=value` format override all other sources:

```bash
slop-code run --config my_run.yaml \
  model.name=opus-4.5 \
  thinking=high \
  pass_policy=all-cases
```

#### Type Inference

Override values are automatically parsed:

| Input | Parsed Type | Result |
|-------|-------------|--------|
| `true` / `false` | bool | `True` / `False` |
| `42` | int | `42` |
| `3.14` | float | `3.14` |
| `text` | str | `"text"` |

#### Nested Keys

Use dot notation for nested values:

```bash
slop-code run model.name=opus-4.5 model.provider=anthropic
```

### Resume Mode

Use `--resume` to continue an interrupted run from a previous checkpoint:

```bash
# Resume from a previous run directory
slop-code run --resume outputs/my_run/opus-4.5/claude_code-2.0.51_just-solve_none_20251210T1430
```

**Key behaviors:**
- Loads the saved configuration from the run directory
- Detects the last completed checkpoint and resumes from the next one
- Validates that current config matches saved config for critical fields (model, agent, thinking, prompt, environment)
- Cannot be combined with `--config`, `--agent`, `--environment`, `--prompt`, `--model`, or config overrides
- Useful for recovering from network interruptions or timeout issues

### Dry Run Mode

Use `--dry-run` to preview what would be done without actually running agents:

```bash
# Preview run without executing
slop-code run --config my_run.yaml --dry-run --problem file_backup
```

Shows the resolved configuration and planned execution without consuming resources or API tokens.

## Example Configurations

### Minimal Configuration

```yaml
# minimal.yaml
model:
  provider: anthropic
  name: sonnet-4.5
```

### Full Configuration

```yaml
# full.yaml
agent: claude_code-2.0.51
environment: docker-python3.12-uv
prompt: just-solve

model:
  provider: anthropic
  name: sonnet-4.5

thinking: medium
pass_policy: all-cases

save_dir: outputs
save_template: ${model.name}/${agent.type}-${agent.version}_${prompt}_${thinking}_${now:%Y%m%dT%H%M}
```

### Configuration with Inline Agent

```yaml
# inline_agent.yaml
agent:
  type: claude_code
  binary: claude
  permission_mode: bypassPermissions
  version: 2.0.51
  cost_limits:
    cost_limit: 5.0
    step_limit: 200

environment: docker-python3.12-uv
prompt: best_practice

model:
  provider: anthropic
  name: opus-4.5

thinking: high
```

### Common Use Cases

**Quick experiment with different model:**
```bash
slop-code run --model anthropic/opus-4.5 --problem file_backup
```

**Run with extended thinking:**
```bash
slop-code run --config base.yaml thinking=high --problem file_backup
```

**Strict evaluation (all cases must pass):**
```bash
slop-code run --config base.yaml pass_policy=all-cases --problem file_backup
```

**Custom output directory:**
```bash
slop-code run --config base.yaml \
  save_dir=/experiments \
  --problem file_backup

# Or customize the template:
slop-code run --config base.yaml \
  save_template=${now:%Y%m%d}/run_${model.name} \
  --problem file_backup
```

## API Reference

### load_run_config()

Main entry point for loading configuration:

```python
from slop_code.entrypoints.config import load_run_config

resolved_cfg = load_run_config(
    config_path=Path("my_run.yaml"),  # Optional config file
    cli_flags={"agent": "claude_code-2.0.51"},  # CLI flag values
    cli_overrides=["thinking=high"],  # key=value overrides
)
```

### RunConfig

Raw configuration model before resolution:

```python
from slop_code.entrypoints.config import RunConfig

class RunConfig(BaseModel):
    agent: str | dict[str, Any] = "claude_code-2.0.51"
    environment: str | dict[str, Any] = "docker-python3.12-uv"
    prompt: str = "just-solve"
    model: ModelConfig
    thinking: ThinkingPresetType | ThinkingConfig = "none"
    pass_policy: PassPolicy = PassPolicy.ANY
    problems: list[str] = []
    save_dir: str = "outputs"
    save_template: str = "..."
```

### ResolvedRunConfig

Fully resolved configuration ready for execution:

```python
from slop_code.entrypoints.config import ResolvedRunConfig

class ResolvedRunConfig(BaseModel):
    agent_config_path: Path | None  # None if inline
    agent: dict[str, Any]
    environment_config_path: Path | None
    environment: dict[str, Any]
    prompt_path: Path
    prompt_content: str
    model: ModelConfig
    thinking: ThinkingPresetType | None
    thinking_max_tokens: int | None
    pass_policy: PassPolicy
    problems: list[str]
    save_dir: str
    save_template: str  # Resolved template
    output_path: str  # Combined: save_dir/save_template
```

### ModelConfig

```python
from slop_code.entrypoints.config import ModelConfig

class ModelConfig(BaseModel):
    provider: str  # e.g., "anthropic", "openai"
    name: str      # e.g., "sonnet-4.5", "gpt-4.1"
```

## See Also

### Agent Configuration
- [Models Guide](../agents/models.md) - Model catalog, pricing, agent-specific settings
- [Providers Guide](../agents/providers.md) - Provider definitions and setup
- [Credentials Guide](../agents/credentials.md) - API key and credential management

### Other Topics
- [Environment Configuration](../evaluation/configuration.md) - Detailed environment setup
- [Problem Configuration](../problems/config-schema.md) - Problem and checkpoint config
- [Pytest Patterns](../problems/pytest/README.md) - Test structure and patterns
