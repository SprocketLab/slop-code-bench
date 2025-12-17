---
version: 1.0
last_updated: 2025-12-10
---

# Gemini Agent

The Gemini agent wraps the Gemini CLI for executing coding tasks with Google's Gemini models.

## Quick Start

```yaml
# configs/agents/gemini-0.19.4.yaml
type: gemini
version: 0.19.4
binary: gemini
timeout: 3600
cost_limits:
  cost_limit: 20
  step_limit: 0
  net_cost_limit: 0
```

```bash
slop-code run --agent configs/agents/gemini-0.19.4.yaml \
  --model google/gemini-pro \
  --problem file_backup
```

## Configuration Schema

### Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `type` | `"gemini"` | Must be `gemini` |
| `version` | string | Gemini CLI version (e.g., `0.19.4`) |
| `cost_limits` | AgentCostLimits | Cost and step limits |

### Optional Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `binary` | string | `"gemini"` | CLI binary name |
| `extra_args` | list[str] | `[]` | Additional CLI arguments |
| `env` | dict[str, str] | `{}` | Environment variable overrides |
| `timeout` | int \| None | None | CLI timeout in seconds |

## Configuration Details

### Credential Handling

Gemini uses file-based authentication:

**Auth file structure:**
```
~/.gemini/
├── oauth_creds.json  # OAuth credentials
└── settings.json     # Optional settings
```

The agent:
1. Copies the auth directory to a temporary location
2. Mounts it at `~/.gemini` in the container
3. Allows write access for settings.json (Gemini modifies it)

### Extra Arguments

Pass additional CLI arguments:

```yaml
extra_args:
  - "--verbose"
  - "--no-color"
```

### CLI Command

The agent builds commands like:

```bash
gemini -p "<prompt>" \
  -y \
  --output-format stream-json \
  -m <model_slug>
```

Flags:
- `-p`: Prompt text
- `-y`: YOLO mode (auto-approve tool calls)
- `--output-format stream-json`: JSON output format
- `-m`: Model identifier

## Artifacts

The agent saves these artifacts after each checkpoint:

| File | Description |
|------|-------------|
| `prompt.txt` | The task prompt sent to Gemini |
| `stdout.jsonl` | Raw JSON output from Gemini |
| `stderr.log` | Error output (if any) |
| `messages.jsonl` | Collected JSON payloads |

## Output Parsing

The agent parses various event types from Gemini JSONL output:

| Event Type | Description |
|------------|-------------|
| `init` | Session initialization |
| `message` | User/assistant messages |
| `tool_use` | Tool invocations |
| `tool_result` | Tool execution results |
| `result` | Final result with token usage |

Token usage is extracted from `result` events:

```json
{
  "type": "result",
  "stats": {
    "input_tokens": 1234,
    "output_tokens": 567
  }
}
```

### Step Counting

Steps are counted based on:
- Assistant messages (pending until tool_use)
- Tool use events

Each tool_use counts as a step, plus the preceding assistant message.

## Docker Template

Uses `docker.j2` template:

```jinja2
FROM {{ base_image }}

RUN npm install -g @anthropic/gemini-cli@{{ version }}

USER agent
WORKDIR /workspace
```

## Complete Example

```yaml
type: gemini
version: 0.19.4
binary: gemini
timeout: 7200

extra_args:
  - "--verbose"

env:
  GEMINI_DEBUG: "1"

cost_limits:
  cost_limit: 30
  step_limit: 200
  net_cost_limit: 60
```

## Troubleshooting

### Process Failed to Start

```
AgentError: Gemini process failed to start
```

**Possible causes:**
- Missing or invalid OAuth credentials
- Binary not found in Docker image
- Network connectivity issues

**Solution:** Verify auth files exist at `~/.gemini/` and contain valid credentials.

### Process Timed Out

```
AgentError: Gemini process timed out after 3600s.
```

**Solution:** Increase `timeout` value or reduce task complexity.

### Non-Zero Exit Code

```
AgentError: Gemini process failed with exit code 1
```

**Solution:** Check stderr for error details. Common issues include:
- Invalid model name
- Quota exceeded
- API errors

### Exceeded Usage Limits

```
AgentError: GeminiAgent exceeded configured usage limits
```

**Solution:** Increase `cost_limit` or `step_limit` in `cost_limits`.

## See Also

- [Agent Configuration Guide](../agent-config.md) - Base configuration options
- [Models Guide](../models.md) - Model-specific settings
- [Credentials Guide](../credentials.md) - API key configuration
