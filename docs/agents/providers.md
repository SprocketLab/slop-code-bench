---
version: 1.0
last_updated: 2025-12-10
---

# Providers Guide

Providers define where credentials come from for each API service. They map provider names (like `anthropic`) to credential sources (like `ANTHROPIC_API_KEY`).

## Provider Reference

### Environment Variable Providers

| Provider | Environment Variable | Description |
|----------|---------------------|-------------|
| `anthropic` | `ANTHROPIC_API_KEY` | Anthropic API key for Claude models |
| `openai` | `OPENAI_API_KEY` | OpenAI API key |
| `openrouter` | `OPENROUTER_API_KEY` | OpenRouter API key for multi-provider access |
| `google` | `GEMINI_API_KEY` | Google API key for Gemini models |
| `zhipu` | `ZHIPU_API_KEY` | Zhipu AI API key for GLM models |
| `mistral` | `MISTRAL_API_KEY` | Mistral AI API key |
| `deepseek` | `DEEPSEEK_API_KEY` | DeepSeek API key |
| `together` | `TOGETHER_API_KEY` | Together AI API key |
| `groq` | `GROQ_API_KEY` | Groq API key |
| `cohere` | `COHERE_API_KEY` | Cohere API key |
| `xai` | `XAI_API_KEY` | xAI API key for Grok models |
| `moonshot` | `MOONSHOT_API_KEY` | Moonshot AI API key for Kimi models |
| `claude_code_oauth` | `CLAUDE_CODE_OAUTH_TOKEN` | Claude Code OAuth token |

### File-based Providers

| Provider | File Path | Description |
|----------|-----------|-------------|
| `codex_auth` | `~/.codex/auth.json` | OpenAI Codex CLI authentication file |
| `opencode_auth` | `~/.local/share/opencode/auth.json` | OpenCode authentication file |
| `gemini_auth` | `~/.gemini/oauth_creds.json` | Gemini CLI OAuth credentials file |

## Provider Types

### Environment Variable Providers

Most providers use environment variables. To set up:

```bash
# Set the environment variable
export ANTHROPIC_API_KEY=sk-ant-...

# Run an agent
slop-code run --model anthropic/sonnet-4.5 --problem file_backup
```

You can also use a different environment variable name:

```bash
# Use a custom env var
export MY_CUSTOM_KEY=sk-ant-...
slop-code run --model anthropic/sonnet-4.5 \
  --provider-api-key-env MY_CUSTOM_KEY \
  --problem file_backup
```

### File-based Providers

Some providers (like `codex_auth`) read credentials from files. The file path supports `~` expansion:

```bash
# Codex expects auth at ~/.codex/auth.json
# The file is typically created by the codex CLI:
codex auth login
```

File-based credentials are read once and cached.

## Configuration File

Providers are defined in `configs/providers.yaml`:

```yaml
providers:
  # Environment variable provider
  anthropic:
    type: env_var
    env_var: ANTHROPIC_API_KEY
    description: Anthropic API key for Claude models

  # File-based provider
  codex_auth:
    type: file
    file_path: ~/.codex/auth.json
    description: OpenAI Codex CLI authentication file
```

### Schema

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | `env_var` \| `file` | Yes | Credential source type |
| `env_var` | string | For `env_var` type | Environment variable name |
| `file_path` | string | For `file` type | Path to credential file (supports `~`) |
| `description` | string | No | Human-readable description |

## Adding a New Provider

### Step 1: Add to providers.yaml

```yaml
providers:
  # ... existing providers ...

  my_provider:
    type: env_var
    env_var: MY_PROVIDER_API_KEY
    description: My provider API key
```

### Step 2: Set Up the Credential

```bash
export MY_PROVIDER_API_KEY=your-api-key
```

### Step 3: Create a Model Config

Create a model file that references the provider:

```yaml
# configs/models/my-model.yaml
internal_name: my-model-v1
provider: my_provider
pricing:
  input: 1.0
  output: 2.0
```

### Step 4: Test

```bash
slop-code run --model my_provider/my-model --problem test_problem
```

## API Reference

### ProviderDefinition

```python
class ProviderDefinition(BaseModel):
    name: str                    # Provider identifier
    credential_type: CredentialType  # ENV_VAR or FILE
    env_var: str | None          # Env var name (for env_var type)
    file_path: str | None        # File path (for file type)
    description: str             # Human-readable description
```

### ProviderCatalog

```python
class ProviderCatalog:
    @classmethod
    def get(cls, name: str) -> ProviderDefinition | None:
        """Get provider by name."""

    @classmethod
    def list_providers(cls) -> list[str]:
        """List all registered provider names."""

    @classmethod
    def ensure_loaded(cls) -> None:
        """Load providers from configs/providers.yaml (idempotent)."""
```

## Troubleshooting

### Unknown Provider Error

```
ValueError: Unknown provider 'custom'. Supported providers: anthropic, openai, ...
```

**Solution**: Add the provider to `configs/providers.yaml`.

### Provider Type Mismatch

```
ValueError: Provider 'anthropic' does not use file credentials.
```

**Solution**: Check that you're using the correct provider type. Use `APIKeyStore.get_credential_type(provider)` to verify.

## See Also

- [Credentials Guide](credentials.md) - How credentials are resolved
- [Models Guide](models.md) - How models reference providers
- [Run Configuration](../commands/run.md) - Using providers in runs
