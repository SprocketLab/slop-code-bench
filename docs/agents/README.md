---
version: 1.0
last_updated: 2025-12-10
---

# Agents Documentation

This module covers agent configuration, model selection, provider setup, and credential management for running agents with `slop-code run`.

## Quick Start

New to running agents? Start here:

1. **[Run Configuration](../commands/run.md)** - CLI usage and config files
2. **[Agent Configuration](agent-config.md)** - Configure agent behavior and limits
3. **[Providers](providers.md)** - Set up API credentials
4. **[Models](models.md)** - Understand the model catalog
5. **[Credentials](credentials.md)** - How API keys are resolved

Implementing a new agent? See:
- **[Agent Class Guide](agent-class.md)** - Agent lifecycle and implementation

## Documentation Index

| Document | Description |
|----------|-------------|
| [Run Configuration](../commands/run.md) | CLI commands, config files, output paths |
| [Agent Configuration](agent-config.md) | AgentConfigBase, cost limits, registry |
| [Agent Class Guide](agent-class.md) | Agent lifecycle, abstract methods, implementation |
| [Providers](providers.md) | Provider definitions and credential sources |
| [Models](models.md) | Model catalog, pricing, agent-specific settings |
| [Credentials](credentials.md) | Credential resolution and troubleshooting |

### Agent Types

| Agent | Description |
|-------|-------------|
| [Claude Code](agents/claude-code.md) | Anthropic's Claude Code CLI agent |
| [Codex](agents/codex.md) | OpenAI's Codex CLI agent |
| [MiniSWE](agents/miniswe.md) | Lightweight bash-based agent |
| [OpenCode](agents/opencode.md) | OpenCode CLI agent |
| [Gemini](agents/gemini.md) | Google's Gemini CLI agent |
| [OpenHands](agents/openhands.md) | OpenHands framework agent |

## Core Concepts

| Concept | Description | Configuration |
|---------|-------------|---------------|
| **Provider** | Defines where credentials come from | `configs/providers.yaml` |
| **Model** | API endpoint, pricing, agent-specific settings | `configs/models/*.yaml` |
| **Credential** | Resolved API key or auth file | Environment variables or files |
| **[Agent Config](agent-config.md)** | Agent type, cost limits, Docker template | `configs/agents/*.yaml` |
| **[Agent Class](agent-class.md)** | Agent implementation and lifecycle | Source code |

## Configuration Flow

```
RunConfig (YAML or CLI)
    │
    ├─ model.provider ──► ProviderCatalog ──► ProviderDefinition
    │                                              │
    │                                              ▼
    │                                         APIKeyStore
    │                                              │
    ├─ model.name ─────► ModelCatalog ──────► ModelDefinition
    │                                              │
    │                                              ▼
    └─ agent ──────────► AgentConfigBase ◄── ProviderCredential
                               │
                               ▼
                            Agent.from_config()
```

## Common Workflows

### Running an Agent

```bash
# Minimal - uses defaults
slop-code run --model anthropic/sonnet-4.5 --problem file_backup

# With config file
slop-code run --config my_run.yaml --problem file_backup

# Override thinking budget
slop-code run --model anthropic/opus-4.5 thinking=high --problem file_backup
```

### Setting Up Credentials

```bash
# Environment variable (most providers)
export ANTHROPIC_API_KEY=sk-...

# Or use a different env var
slop-code run --model anthropic/sonnet-4.5 --provider-api-key-env MY_KEY
```

### Adding a New Model

1. Create `configs/models/my-model.yaml`
2. Specify `provider`, `internal_name`, `pricing`
3. Add `agent_specific` settings if needed

See [Models Guide](models.md) for details.

### Adding a New Provider

1. Add entry to `configs/providers.yaml`
2. Set up the credential (env var or file)
3. Reference provider in model configs

See [Providers Guide](providers.md) for details.

## Related Documentation

- [Environment Configuration](../evaluation/configuration.md) - Execution environment setup
- [Problem Configuration](../problems/config-schema.md) - Problem and checkpoint config
