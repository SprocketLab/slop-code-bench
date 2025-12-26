---
version: 1.0
last_updated: 2025-12-10
---

# MiniSWE Agent

The MiniSWE agent is a lightweight software engineering agent that uses bash commands to interact with the filesystem.

## Quick Start

```yaml
# configs/agents/miniswe-1.0.yaml
type: mini_swe
cost_limits:
  cost_limit: 20
  step_limit: 300
  net_cost_limit: 0
```

```bash
slop-code run --agent configs/agents/miniswe-1.0.yaml \
  --model openrouter/claude-sonnet-4.5 \
  --problem file_backup
```

## Configuration Schema

### Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `type` | `"mini_swe"` | Must be `mini_swe` |
| `cost_limits` | AgentCostLimits | Cost and step limits |

### Optional Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `system_template` | string | (built-in) | Jinja2 template for system prompt |
| `instance_template` | string | (built-in) | Jinja2 template for task prompt |
| `timeout_template` | string | (built-in) | Template for timeout messages |
| `format_error_template` | string | (built-in) | Template for format errors |
| `action_observation_template` | string | (built-in) | Template for action results |

### Flexible Validation

MiniSWE uses `extra="allow"`, accepting additional fields beyond those declared. This allows for future extensibility.

## Configuration Details

### Template System

MiniSWE uses Jinja2 templates for all prompts. Default templates can be overridden:

**System Template** - Defines agent behavior:
```yaml
system_template: |
  You are a helpful assistant that can interact with a computer.
  Your response must contain **EXACTLY ONE** bash code block...
```

**Instance Template** - Defines task format:
```yaml
instance_template: |
  Please solve this issue: {{task}}

  You can execute bash commands and edit files...
```

**Template Variables:**
- `{{task}}` - The task description
- `{{step_limit}}` - Maximum steps allowed
- `{{cost_limit}}` - Maximum cost allowed
- `{{net_cost_limit}}` - Maximum net cost

### Agent Workflow

MiniSWE follows a specific workflow:

1. System message sets up the assistant
2. Task prompt describes the problem
3. Agent responds with a bash command in code block
4. Command is executed and output returned
5. Loop continues until task completion or limits hit

### Termination

The agent terminates when it outputs:
```bash
echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT
```

or:
```bash
echo MINI_SWE_AGENT_FINAL_OUTPUT
```

### Thinking Configuration

MiniSWE supports thinking via OpenRouter reasoning:

**From model catalog:**
```yaml
agent_specific:
  mini_swe:
    model_class: openrouter
    reasoning:
      effort: medium
      enabled: true
```

**Presets:**
- `disabled`: `{"enabled": false}`
- `low`/`medium`/`high`: `{"effort": "<preset>", "enabled": true, "exclude": false}`

For LiteLLM models:
- Sets `reasoning_effort` parameter directly

## Artifacts

The agent saves these artifacts after each checkpoint:

| File | Description |
|------|-------------|
| `trajectory.jsonl` | Step-by-step trajectory with content, cost, tokens |

## Model Configuration

MiniSWE gets model configuration from the model catalog's `agent_specific.mini_swe` section:

```yaml
# configs/models/sonnet-4.5.yaml
agent_specific:
  mini_swe:
    model_name: anthropic/claude-sonnet-4.5  # Explicit model name
    model_class: openrouter                   # "litellm" or "openrouter"
    api_base: https://custom.api/v1           # Optional endpoint
    model_kwargs:                             # Additional kwargs
      temperature: 0.7
```

### Model Name Resolution

1. `agent_specific.mini_swe.model_name` (explicit)
2. `provider_slugs[model_class]` (provider-specific)
3. `internal_name` (fallback)

### Model Classes

| Class | Description |
|-------|-------------|
| `openrouter` | Uses OpenRouter API (default) |
| `litellm` | Uses LiteLLM for various providers |

## Environment Configuration

Unlike other agents (Claude Code, Codex, OpenCode) that use custom Docker templates, **MiniSWE manages its own execution environment** directly via the `minisweagent` library.

### Environment Types

MiniSWE supports both Docker and local execution:

**Docker Execution:**
- Uses `DockerEnvironment` from minisweagent
- Automatically handles container setup and command execution
- Mounts workspace into container at the configured workdir
- **No custom docker_template needed** - environment is managed by minisweagent

**Local Execution:**
- Uses `LocalEnvironment` for direct shell access
- Runs commands in the current shell without containers
- Useful for development and testing

### How MiniSWE Differs

- **No docker_template field**: Unlike Claude Code, Codex, and OpenCode which require a docker_template, MiniSWE doesn't use this mechanism
- **No version field**: MiniSWE doesn't need a version field - it uses the installed `minisweagent` package directly
- **Environment auto-selection**: The agent automatically chooses between Docker and Local based on the environment specification passed to `setup()`

### Choosing an Environment

When running MiniSWE, specify the environment in your run configuration:

```yaml
# Use Docker environment (recommended for consistency)
environment: configs/environments/docker-python3.12-uv.yaml

# Or use local environment (faster for development)
environment: configs/environments/local.yaml
```

## Complete Example

```yaml
type: mini_swe

system_template: |
  You are an expert software engineer.

  Your response must contain **EXACTLY ONE** bash code block.
  Include a **THOUGHT** section explaining your reasoning.

  Format:
  THOUGHT: Your reasoning here.

  ```bash
  your_command_here
  ```

instance_template: |
  Task: {{task}}

  Steps allowed: {{step_limit}}
  Budget: ${{cost_limit}}

  Submit when done: `echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT`

cost_limits:
  cost_limit: 20
  step_limit: 300
  net_cost_limit: 50
```

## Replay Support

MiniSWE supports trajectory replay (`supports_replay() -> True`), allowing recorded sessions to be replayed for debugging or analysis.

## Troubleshooting

### Format Errors

```
FormatError: Please always provide **EXACTLY ONE** action...
```

**Cause:** The model response contained multiple or no bash code blocks.

**Solution:** The agent automatically retries with a format error message. If persistent, consider adjusting the system template.

### Execution Timeout

```
ExecutionTimeoutError: The last command timed out...
```

**Cause:** A bash command took too long to execute.

**Solution:** The error includes command output. Agent will receive timeout message and can try a different approach.

### Limits Exceeded

```
LimitsExceeded: Agent hit cost or step limits
```

**Solution:** Increase `cost_limit` or `step_limit` in `cost_limits`.

### Model Cost Error

If using OpenRouter and cost calculation fails, the agent falls back to 0 cost to avoid crashes.

## See Also

- [Agent Configuration Guide](../agent-config.md) - Base configuration options
- [Models Guide](../models.md) - Model-specific settings
- [Credentials Guide](../credentials.md) - API key configuration
