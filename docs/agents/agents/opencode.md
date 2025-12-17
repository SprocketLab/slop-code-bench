---
version: 1.0
last_updated: 2025-12-10
---

# OpenCode Agent

The OpenCode agent wraps the OpenCode CLI for executing coding tasks.

## Quick Start

```yaml
# configs/agents/opencode-1.0.134.yaml
type: opencode
version: 1.0.134
cost_limits:
  cost_limit: 20
  step_limit: 250
  net_cost_limit: 0
```

```bash
slop-code run --agent configs/agents/opencode-1.0.134.yaml \
  --model anthropic/sonnet-4.5 \
  --problem file_backup
```

## Configuration Schema

### Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `type` | `"opencode"` | Must be `opencode` |
| `cost_limits` | AgentCostLimits | Cost and step limits |

### Optional Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `version` | string | `"1.0.134"` | OpenCode CLI version |
| `config` | dict | `{}` | OpenCode configuration JSON |
| `env` | dict[str, str] | `{}` | Environment variable overrides |

### Flexible Validation

OpenCode uses `extra="allow"`, accepting additional fields beyond those declared.

## Configuration Details

### Provider Requirement

OpenCode requires a `provider_name` in the model's agent-specific settings:

```yaml
# configs/models/sonnet-4.5.yaml
agent_specific:
  opencode:
    provider_name: anthropic  # Required
```

Without this, the agent raises:
```
AgentError: OpenCode requires 'provider_name' in model's agent_specific.opencode settings
```

### OpenCode Config

Pass OpenCode-specific configuration:

```yaml
config:
  agent:
    build:
      reasonEffort: medium
```

This creates a `opencode.json` config file mounted at `~/.config/opencode/opencode.json`.

### Credential Handling

OpenCode supports both environment variable and file-based credentials:

**Environment variable:**
- Set via `credential.destination_key`

**File-based auth:**
- Auth file mounted at `~/.local/share/opencode/auth.json`

### Thinking Configuration

OpenCode supports reasoning effort via config:

**From CLI/model:**
```yaml
thinking: medium  # low/medium/high
```

This sets `agent.build.reasonEffort` in the OpenCode config.

### CLI Command

The agent builds commands like:

```bash
opencode run "<prompt>" \
  --log-level DEBUG \
  --print-logs \
  --format json \
  --model <provider>/<model_id>
```

## Artifacts

The agent saves these artifacts after each checkpoint:

| File | Description |
|------|-------------|
| `messages.jsonl` | All parsed JSON messages |
| `stdout.txt` | Raw stdout output |
| `stderr.txt` | Raw stderr output |

## Output Parsing

The agent parses `step_finish` events from OpenCode output:

```json
{
  "type": "step_finish",
  "part": {
    "tokens": {
      "input": 1234,
      "output": 567,
      "cache": {"read": 100, "write": 50},
      "reasoning": 200
    },
    "cost": 0.05,
    "reason": "stop"
  }
}
```

## Docker Template

Uses `docker.j2` template in the agent directory. Requires OpenCode CLI installed.

## Model Catalog Settings

Configure agent-specific settings in model definitions:

```yaml
# configs/models/sonnet-4.5.yaml
agent_specific:
  opencode:
    provider_name: anthropic  # Required
    config:                    # Optional base config
      agent:
        maxSteps: 100
    env_overrides:             # Optional env vars
      OPENCODE_DEBUG: "1"
```

### Configuration Merging

Settings merge in order (later wins):
1. Model catalog `agent_specific.opencode.config`
2. Agent YAML `config` field

## Complete Example

```yaml
type: opencode
version: 1.0.134

config:
  agent:
    build:
      reasonEffort: high
    maxSteps: 200

env:
  OPENCODE_DEBUG: "1"

cost_limits:
  cost_limit: 20
  step_limit: 250
  net_cost_limit: 50
```

## Troubleshooting

### Missing Provider Name

```
AgentError: OpenCode requires 'provider_name' in model's agent_specific.opencode settings
```

**Solution:** Add `provider_name` to the model's `agent_specific.opencode` section.

### No Messages Received

```
AgentError: OpenCode runtime did not provide any messages
```

**Possible causes:**
- OpenCode failed to start
- Invalid configuration
- Credential issues

**Solution:** Check stderr output for error details.

### Runtime Finished Without Event

```
AgentError: OpenCode runtime did not provide a finished event
```

**Solution:** May occur if limits were hit during execution. Check if task completed before the error.

## See Also

- [Agent Configuration Guide](../agent-config.md) - Base configuration options
- [Models Guide](../models.md) - Model-specific settings
- [Credentials Guide](../credentials.md) - API key configuration
