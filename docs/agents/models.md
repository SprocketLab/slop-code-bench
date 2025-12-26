---
version: 1.0
last_updated: 2025-12-10
---

# Models Guide

Models define API endpoints, pricing, and agent-specific configuration. The model catalog provides a central registry loaded from `configs/models/*.yaml`.

## Quick Start

Create a model file:

```yaml
# configs/models/my-model.yaml
internal_name: my-model-v1
provider: anthropic
pricing:
  input: 3.0
  output: 15.0
```

Use it:

```bash
slop-code run --model anthropic/my-model --problem file_backup
```

## Model Definition Schema

### Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `internal_name` | string | API model identifier (e.g., `claude-sonnet-4-5-20250929`) |
| `provider` | string | Credential provider (must exist in `providers.yaml`) |
| `pricing` | APIPricing | Token pricing per million |

### Optional Fields

| Field | Type | Description |
|-------|------|-------------|
| `aliases` | list[str] | Alternative names for lookup |
| `provider_slugs` | dict[str, str] | Provider-specific model identifiers |
| `agent_specific` | dict[str, dict] | Per-agent configuration |
| `thinking` | string | Thinking preset (`none`/`disabled`/`low`/`medium`/`high`) |
| `max_thinking_tokens` | int | Explicit token limit (mutually exclusive with `thinking`) |

## Pricing Configuration

Pricing is specified per million tokens:

```yaml
pricing:
  input: 3.0        # Cost per 1M input tokens
  output: 15.0      # Cost per 1M output tokens
  cache_read: 0.30  # Cost per 1M cache read tokens
  cache_write: 3.75 # Cost per 1M cache write tokens
```

## Aliases

Models can have multiple names:

```yaml
internal_name: claude-sonnet-4-5-20250929
aliases:
  - claude-sonnet-4.5
  - sonnet-4.5
```

All of these work:

```bash
slop-code run --model anthropic/claude-sonnet-4-5-20250929
slop-code run --model anthropic/claude-sonnet-4.5
slop-code run --model anthropic/sonnet-4.5
```

## Provider Slugs

When a model needs different identifiers for different providers:

```yaml
internal_name: claude-sonnet-4-5-20250929
provider: anthropic
provider_slugs:
  openrouter: anthropic/claude-sonnet-4.5
```

Resolution order:
1. `provider_slugs[provider]` if provider is in the map
2. `internal_name` (fallback)

## Agent-Specific Configuration

Different agents require different settings. The `agent_specific` block provides per-agent overrides.

### mini_swe

```yaml
agent_specific:
  mini_swe:
    model_name: anthropic/claude-sonnet-4.5  # Model identifier
    model_class: openrouter                   # "litellm" | "openrouter"
    api_base: https://custom.api/v1           # Optional endpoint override
    model_kwargs:                             # Additional constructor kwargs
      temperature: 0.7
```

Model name resolution for mini_swe:
1. `agent_specific.mini_swe.model_name` (explicit)
2. `provider_slugs[model_class]`
3. `internal_name` (fallback)

### claude_code

```yaml
agent_specific:
  claude_code:
    base_url: https://custom.anthropic.api/  # Override ANTHROPIC_BASE_URL
    env_overrides:                            # Additional env vars
      CUSTOM_VAR: value
    thinking: high                            # Thinking preset override
```

### codex

```yaml
agent_specific:
  codex:
    reasoning_effort: medium  # low/medium/high
    env_overrides:
      CODEX_CUSTOM: value
    thinking: medium
```

### opencode

```yaml
agent_specific:
  opencode:
    provider_name: anthropic  # Provider for opencode config
```

## Thinking Configuration

### Presets

| Preset | Description |
|--------|-------------|
| `none` | No thinking (default) |
| `disabled` | Explicitly disable thinking |
| `low` | ~4,000 tokens |
| `medium` | ~10,000 tokens |
| `high` | ~32,000 tokens |

### Configuration Priority

1. CLI override (`thinking=high` or `--config` with `thinking:`)
2. `agent_specific.{agent_type}.thinking`
3. Top-level model `thinking`
4. Default (`none`)

### Example

```yaml
# Top-level default
thinking: medium

agent_specific:
  claude_code:
    thinking: high  # Override for Claude Code only
  codex:
    thinking: low   # Override for Codex only
```

### Explicit Token Budget

Use `max_thinking_tokens` instead of presets:

```yaml
max_thinking_tokens: 20000
```

Note: `thinking` and `max_thinking_tokens` are mutually exclusive.

## Complete Example

```yaml
# configs/models/sonnet-4.5.yaml
internal_name: claude-sonnet-4-5-20250929
provider: anthropic

pricing:
  input: 3
  output: 15
  cache_read: 0.30
  cache_write: 3.75

aliases:
  - claude-sonnet-4.5
  - sonnet-4.5

provider_slugs:
  openrouter: anthropic/claude-sonnet-4.5

agent_specific:
  mini_swe:
    model_name: anthropic/claude-sonnet-4.5
    model_class: openrouter

  codex:
    thinking: medium

  opencode:
    provider_name: anthropic
```

## Real-World Examples

### Example 1: Claude Opus with Reasoning

Configure Opus for agents that need extended thinking:

```yaml
# configs/models/opus-4.5.yaml
internal_name: claude-opus-4-5-20251101
provider: anthropic
pricing:
  input: 5
  output: 25
  cache_read: 0.5
  cache_write: 6.25

aliases:
  - claude-opus-4.5
  - opus-4.5

provider_slugs:
  openrouter: anthropic/claude-opus-4-5-20251101

thinking: high  # Enable thinking for all agents

agent_specific:
  mini_swe:
    model_name: anthropic/claude-opus-4-5-20251101
    model_class: openrouter

  codex:
    thinking: medium  # Use medium for codex specifically

  opencode:
    provider_name: anthropic
```

### Example 2: OpenRouter with Multi-Agent Config

Use different models for different agents via OpenRouter:

```yaml
# configs/models/multi-agent-opus.yaml
internal_name: claude-opus-4-5-20251101
provider: openrouter

pricing:
  input: 5
  output: 25

provider_slugs:
  openrouter: anthropic/claude-opus-4-5-20251101
  litellm: openrouter/anthropic/claude-opus-4-5-20251101

agent_specific:
  mini_swe:
    model_name: anthropic/claude-opus-4-5-20251101
    model_class: openrouter
    model_kwargs:
      temperature: 0.3  # Lower temp for deterministic behavior

  claude_code:
    base_url: https://api.openrouter.ai/v1
    thinking: high

  codex:
    reasoning_effort: high
```

### Example 3: Local Development with LiteLLM

Configure for local testing with LiteLLM:

```yaml
# configs/models/local-sonnet.yaml
internal_name: claude-sonnet-4-5-20250929
provider: anthropic

pricing:
  input: 3
  output: 15

agent_specific:
  mini_swe:
    model_name: claude-sonnet-4-5-20250929
    model_class: litellm
    api_base: http://localhost:8000  # Local LLM server
    model_kwargs:
      temperature: 0.5
      max_tokens: 4096

  claude_code:
    base_url: http://localhost:8000
```

### Example 4: Cost-Optimized Configuration

Minimal cost setup for testing:

```yaml
# configs/models/budget-haiku.yaml
internal_name: claude-haiku-4-5-20250929
provider: anthropic

pricing:
  input: 0.80
  output: 4.0

aliases:
  - haiku
  - budget

thinking: disabled  # Disable thinking to save cost

agent_specific:
  mini_swe:
    model_name: anthropic/claude-haiku-4-5-20250929
    model_class: openrouter

  opencode:
    provider_name: anthropic
```

## Adding a New Model

### Step 1: Create Model File

```yaml
# configs/models/my-model.yaml
internal_name: my-model-api-id
provider: anthropic
pricing:
  input: 1.0
  output: 2.0
  cache_read: 0.0
  cache_write: 0.0
aliases:
  - my-model
```

### Step 2: Validate Provider

Ensure the provider exists in `configs/providers.yaml`. If not, add it first. See [Providers Guide](providers.md).

### Step 3: Add Agent-Specific Settings

If the model needs special configuration for certain agents:

```yaml
agent_specific:
  mini_swe:
    model_name: my-provider/my-model
    model_class: litellm
```

### Step 4: Test

```bash
slop-code run --model anthropic/my-model --problem file_backup
```

## API Reference

### ModelDefinition

```python
class ModelDefinition(BaseModel):
    internal_name: str
    provider: str
    pricing: APIPricing
    name: str = ""              # Set from filename during registration
    aliases: list[str] = []
    agent_specific: dict[str, dict[str, Any]] = {}
    provider_slugs: dict[str, str] = {}
    thinking: ThinkingPreset | None = None
    max_thinking_tokens: int | None = None

    def get_model_slug(self, provider: str | None = None) -> str:
        """Get provider-specific model identifier."""

    def get_agent_settings(self, agent_type: str | None) -> dict | None:
        """Get agent-specific configuration."""

    def get_thinking_config(self, agent_type: str | None) -> tuple:
        """Get thinking preset and max tokens."""
```

### ModelCatalog

```python
class ModelCatalog:
    @classmethod
    def get(cls, name: str) -> ModelDefinition | None:
        """Get model by name or alias."""

    @classmethod
    def resolve_canonical(cls, name: str) -> str:
        """Resolve alias to canonical name."""

    @classmethod
    def list_models(cls) -> list[str]:
        """List all registered model names."""

    @classmethod
    def ensure_loaded(cls) -> None:
        """Load models from configs/models/ (idempotent)."""
```

## Troubleshooting

### Unknown Provider Error

```
ValueError: Model config 'my-model' references unknown provider 'custom'.
Add it to configs/providers.yaml
```

**Solution**: Add the provider to `configs/providers.yaml` before creating the model config.

### Model Not Found

```
ValueError: Unknown model 'my-model'. Available models: opus-4.5, sonnet-4.5, ...
```

**Solution**: Check that `configs/models/my-model.yaml` exists and is valid YAML.

### Agent-Specific Settings Not Applied

Verify the agent type key matches:
- `mini_swe` (not `miniswe`)
- `claude_code` (not `claude-code`)
- `codex` (not `openai_codex`)
- `opencode` (not `open_code`)

### Thinking Not Working

Check the resolution order:
1. Is `thinking=X` being passed via CLI?
2. Is there an `agent_specific.{agent}.thinking` override?
3. Is `thinking` set at the top level?

Use verbose mode to see the resolved configuration:

```bash
slop-code run --model anthropic/sonnet-4.5 --problem file_backup -v
```

## See Also

- [Providers Guide](providers.md) - Provider definitions
- [Credentials Guide](credentials.md) - Credential resolution
- [Run Configuration](../commands/run.md) - Using models in runs
