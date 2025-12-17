---
version: 1.0
last_updated: 2025-12-10
---

# Credentials Guide

The credential system resolves API keys and authentication files for agent execution. It provides a unified interface regardless of whether credentials come from environment variables or files.

## Credential Flow

```
RunConfig.model.provider (e.g., "anthropic")
        │
        ▼
ProviderCatalog.get(provider)
        │
        ▼
ProviderDefinition (type: env_var | file)
        │
        ▼
APIKeyStore.resolve()
        │
        ▼
ProviderCredential
        │
        ▼
Agent receives credential in from_config()
```

## Quick Start

### Environment Variable Credentials

Most providers use environment variables:

```bash
# Set your API key
export ANTHROPIC_API_KEY=sk-ant-...

# Run an agent
slop-code run --model anthropic/sonnet-4.5 --problem file_backup
```

### Using a Custom Environment Variable

Override the default env var name with `--provider-api-key-env`:

```bash
export MY_KEY=sk-ant-...
slop-code run \
  --model anthropic/sonnet-4.5 \
  --provider-api-key-env MY_KEY \
  --problem file_backup
```

## ProviderCredential Structure

When a credential is resolved, it returns a `ProviderCredential`:

| Field | Type | Description |
|-------|------|-------------|
| `provider` | str | Provider name (e.g., `"anthropic"`) |
| `credential_type` | `ENV_VAR` \| `FILE` | Type of credential |
| `value` | str | The actual API key or file contents |
| `source` | str | Where it came from (env var name or file path) |
| `destination_key` | str | Env var name to export as |

### Example

```python
from slop_code.agent_runner.credentials import API_KEY_STORE

cred = API_KEY_STORE.resolve("anthropic")
# cred.provider = "anthropic"
# cred.credential_type = CredentialType.ENV_VAR
# cred.value = "sk-ant-..."
# cred.source = "ANTHROPIC_API_KEY"
# cred.destination_key = "ANTHROPIC_API_KEY"
```

## How Agents Use Credentials

### Environment Variable Agents

Agents like `claude_code` and `mini_swe` inject credentials as environment variables:

```python
# In agent's _prepare_runtime_execution()
env_overrides[credential.destination_key] = credential.value
# Result: ANTHROPIC_API_KEY=sk-ant-... in the container
```

### File-based Agents

Agents like `codex` and `gemini` mount credential files:

```python
# Credential file is mounted into the container
# e.g., ~/.codex/auth.json -> /home/agent/.codex/auth.json
```

## CLI Override

The `--provider-api-key-env` flag overrides where the credential is read from:

```bash
slop-code run \
  --model anthropic/sonnet-4.5 \
  --provider-api-key-env CUSTOM_KEY \
  --problem file_backup
```

This reads from `CUSTOM_KEY` instead of `ANTHROPIC_API_KEY`, but the credential is still injected as `ANTHROPIC_API_KEY` in the agent container.

## API Reference

### APIKeyStore

```python
class APIKeyStore:
    def resolve(
        self,
        provider: str,
        *,
        file_path_override: Path | None = None,
        env_var_override: str | None = None,
    ) -> ProviderCredential:
        """Resolve credentials for a provider.

        Args:
            provider: Provider name (e.g., 'anthropic', 'codex_auth')
            file_path_override: Override file path for file providers
            env_var_override: Override env var name for env var providers

        Returns:
            ProviderCredential with the resolved value

        Raises:
            ValueError: If provider is unknown
            CredentialNotFoundError: If credential cannot be resolved
        """

    def has_credential(
        self,
        provider: str,
        *,
        file_path_override: Path | None = None,
    ) -> bool:
        """Check if a credential is available without raising."""

    @classmethod
    def supported_providers(cls) -> tuple[str, ...]:
        """Return all supported provider names."""

    @classmethod
    def get_credential_type(cls, provider: str) -> CredentialType:
        """Get credential type (ENV_VAR or FILE) for a provider."""

    @classmethod
    def get_env_var_name(cls, provider: str) -> str:
        """Get the env var name for an env var provider."""

    @classmethod
    def get_file_path(cls, provider: str) -> Path:
        """Get the default file path for a file provider."""
```

### Module-level Store

```python
from slop_code.agent_runner.credentials import API_KEY_STORE

# Pre-initialized, frozen store
cred = API_KEY_STORE.resolve("anthropic")
```

The `API_KEY_STORE` is frozen after initialization - credentials are cached but the store itself cannot be modified.

## Error Handling

### CredentialNotFoundError

Raised when a credential cannot be resolved:

```
CredentialNotFoundError: Environment variable 'ANTHROPIC_API_KEY' not found
for provider 'anthropic'
```

**Solution**: Export the required environment variable or use `--provider-api-key-env`.

### File Not Found

```
CredentialNotFoundError: Credential file not found for provider 'codex_auth':
/home/user/.codex/auth.json
```

**Solution**: Create the auth file (usually via the CLI tool, e.g., `codex auth login`).

### Unknown Provider

```
ValueError: Unknown provider 'custom'. Supported providers: anthropic, openai, ...
```

**Solution**: Add the provider to `configs/providers.yaml`. See [Providers Guide](providers.md).

## Caching

`APIKeyStore` caches resolved credentials:

- Cache key: `{provider}:{file_path_override}:{env_var_override}`
- Same parameters return the cached credential
- Use `store.clear_cache()` to reset (mainly for testing)

## Security Considerations

- Credentials are cached in memory only (not persisted)
- File credentials are read once at resolution time
- Use environment variables in CI/CD pipelines
- Never commit credentials to version control
- The `API_KEY_STORE` is frozen to prevent modification

## Troubleshooting

### Credential Not Being Used

Check that the provider matches:

```bash
# This uses the 'anthropic' provider
slop-code run --model anthropic/sonnet-4.5

# This uses the 'openrouter' provider (different credential!)
slop-code run --model openrouter/sonnet-4.5
```

### Wrong API Key

Verify the credential source:

```python
from slop_code.agent_runner.credentials import API_KEY_STORE

cred = API_KEY_STORE.resolve("anthropic")
print(f"Source: {cred.source}")  # Should show ANTHROPIC_API_KEY
print(f"Value starts with: {cred.value[:10]}...")
```

### Testing Credential Availability

```python
from slop_code.agent_runner.credentials import API_KEY_STORE

if API_KEY_STORE.has_credential("anthropic"):
    print("Anthropic credential available")
else:
    print("Missing ANTHROPIC_API_KEY")
```

## See Also

- [Providers Guide](providers.md) - Provider definitions
- [Models Guide](models.md) - Model provider references
- [Run Configuration](../commands/run.md) - CLI credential options
