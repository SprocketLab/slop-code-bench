---
version: 1.0
last_updated: 2025-12-10
---

# OpenHands Agent

The OpenHands agent wraps the [OpenHands](https://github.com/All-Hands-AI/OpenHands) framework for executing coding tasks.

## Quick Start

```yaml
# configs/agents/openhands-0.62.yaml
type: openhands
version: "0.62"
timeout: 3600
cost_limits:
  cost_limit: 50
  step_limit: 0
  net_cost_limit: 0
```

```bash
slop-code run --agent configs/agents/openhands-0.62.yaml \
  --model anthropic/claude-sonnet-4 \
  --problem file_backup
```

## Configuration Schema

### Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `type` | `"openhands"` | Must be `openhands` |
| `version` | string | PyPI version of openhands-ai (e.g., `0.62`) |
| `cost_limits` | AgentCostLimits | Cost and step limits |

### Optional Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `model` | string \| None | None | LLM model identifier |
| `base_url` | string \| None | None | LLM API base URL |
| `timeout` | int \| None | None | CLI timeout in seconds |
| `env` | dict[str, str] | `{}` | Environment variable overrides |

## Configuration Details

### Model Configuration

The model identifier follows the pattern `provider/model`:

```yaml
model: anthropic/claude-sonnet-4-20250514
```

For OpenRouter, the agent automatically prefixes `openrouter/`:
```
anthropic/claude-sonnet-4 -> openrouter/anthropic/claude-sonnet-4
```

### Base URL

The `base_url` is auto-configured for certain providers:

| Provider | Base URL |
|----------|----------|
| `openrouter` | `https://openrouter.ai/api/v1` |

Or set explicitly:

```yaml
base_url: "https://custom.api/v1"
```

### Environment Variables

OpenHands requires many environment variables. The agent sets:

```bash
RUNTIME=cli
AGENT_ENABLE_JUPYTER=false
SANDBOX_VOLUMES=/workspace:/workspace:rw
AGENT_ENABLE_PROMPT_EXTENSIONS=false
AGENT_ENABLE_BROWSING=false
ENABLE_BROWSER=false
SANDBOX_ENABLE_AUTO_LINT=false
SKIP_DEPENDENCY_CHECK=1
RUN_AS_OPENHANDS=false
LOG_ALL_EVENTS=true
SKIP_VSCODE_BUILD=true
SAVE_TRAJECTORY_PATH=/openhands/output/trajectory.json
```

Cost limits are mapped to:
- `MAX_ITERATIONS` from `step_limit`
- `MAX_BUDGET_PER_TASK` from `cost_limit`

Add custom env vars:

```yaml
env:
  CUSTOM_VAR: "value"
```

### Credential Handling

OpenHands uses `LLM_API_KEY` for authentication:

```bash
export ANTHROPIC_API_KEY=sk-...  # Resolved to LLM_API_KEY
```

## Artifacts

The agent saves these artifacts after each checkpoint:

| File | Description |
|------|-------------|
| `prompt.txt` | The task prompt |
| `stdout.log` | Standard output |
| `stderr.log` | Standard error |
| `output.log` | Collected log lines |
| `events.jsonl` | JSON events from execution |
| `trajectory.json` | Full trajectory with LLM metrics |

## Usage Tracking

OpenHands tracks usage in `trajectory.json`:

```json
{
  "llm_metrics": {
    "accumulated_cost": 1.23,
    "accumulated_token_usage": {
      "prompt_tokens": 10000,
      "completion_tokens": 5000,
      "cache_read_tokens": 2000,
      "cache_write_tokens": 500
    }
  }
}
```

The agent extracts the final `llm_metrics` entry for usage reporting.

### Step Counting

Steps are counted by matching action patterns in stderr:
- `**CmdRunAction**`
- `**FileEditAction**`
- `TaskTrackingAction(`

## Docker Template

Uses `docker.j2` template that installs openhands-ai from PyPI:

```jinja2
FROM {{ base_image }}

RUN pip install openhands-ai=={{ version }}

USER agent
WORKDIR /workspace
```

## CLI Command

The agent runs OpenHands as a Python module:

```bash
/openhands/.venv/bin/python -u -m openhands.core.main \
  --config-file /openhands/config.toml \
  --task "<prompt>"
```

## Complete Example

```yaml
type: openhands
version: "0.62"
model: anthropic/claude-sonnet-4-20250514
base_url: "https://api.anthropic.com"
timeout: 7200

env:
  OPENHANDS_DEBUG: "1"
  AGENT_MAX_TOKENS: "8192"

cost_limits:
  cost_limit: 50
  step_limit: 500
  net_cost_limit: 100
```

## Troubleshooting

### Process Failed to Start

```
AgentError: OpenHands process failed to start
```

**Possible causes:**
- Missing credentials
- Invalid model identifier
- Docker image issues

**Solution:** Check stdout/stderr output and verify configuration.

### Missing Credential

```
AgentError: OpenHandsAgent requires a credential
```

**Solution:** Ensure the provider has valid credentials configured.

### Missing Model

```
AgentError: OpenHandsAgent requires a model
```

**Solution:** Set the `model` field in configuration or model catalog.

### Process Timed Out

```
AgentError: OpenHands process timed out after 3600s.
```

**Solution:** Increase `timeout` value.

### Non-Zero Exit Code

OpenHands may exit with non-zero codes for various reasons. This is logged as a warning, not an error, since useful work may have been completed.

## See Also

- [Agent Configuration Guide](../agent-config.md) - Base configuration options
- [Models Guide](../models.md) - Model-specific settings
- [Credentials Guide](../credentials.md) - API key configuration
