---
version: 1.0
last_updated: 2025-12-17
---

# docker

Utility commands for working with Docker images.

## Subcommands

| Command | Description |
|---------|-------------|
| [`make-dockerfile`](#make-dockerfile) | Generate a Dockerfile |
| [`build-base`](#build-base) | Build base image for environment |
| [`build-submission`](#build-submission) | Build image for a submission |
| [`build-agent`](#build-agent) | Build image for an agent |

---

## make-dockerfile

Generate a Dockerfile for a docker environment.

### Usage

```bash
slop-code docker make-dockerfile {base|agent} ENV_CONFIG_PATH
```

### Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `dockerfile` | Yes | Type: `base` or `agent` |
| `ENV_CONFIG_PATH` | Yes | Path to environment configuration file |

### Example

```bash
slop-code docker make-dockerfile base configs/environments/docker-python3.12-uv.yaml
```

---

## build-base

Build the base image for a docker environment.

### Usage

```bash
slop-code docker build-base [OPTIONS] ENV_CONFIG_PATH
```

### Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `ENV_CONFIG_PATH` | Yes | Path to environment configuration file |

### Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--force-build` | flag | false | Force rebuild even if image exists |

### Behavior

1. Reads environment specification
2. Generates Dockerfile for base image
3. Builds image with Docker client
4. Tags with environment name

### Examples

```bash
# Build base image
slop-code docker build-base configs/environments/docker-python3.12-uv.yaml

# Force rebuild
slop-code docker build-base configs/environments/docker-python3.12-uv.yaml --force-build
```

---

## build-submission

Build a docker image for a submission.

### Usage

```bash
slop-code docker build-submission [OPTIONS] NAME SUBMISSION_PATH ENV_CONFIG_PATH PROBLEM_NAME
```

### Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `NAME` | Yes | Name for the built image |
| `SUBMISSION_PATH` | Yes | Path to submission directory |
| `ENV_CONFIG_PATH` | Yes | Path to environment configuration |
| `PROBLEM_NAME` | Yes | Name of the problem |

### Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--force-build` | flag | false | Force rebuild |
| `--build-base` | flag | false | Also rebuild base image |

### Behavior

1. Loads environment and problem configurations
2. Resolves static assets for the problem
3. Builds submission image with code and assets mounted
4. Tags with provided name

### Examples

```bash
# Build submission image
slop-code docker build-submission my_submission \
  outputs/my_run/file_backup/checkpoint_1/snapshot \
  configs/environments/docker-python3.12-uv.yaml \
  file_backup

# With base rebuild
slop-code docker build-submission my_submission \
  outputs/snapshot \
  configs/environments/docker-python3.12-uv.yaml \
  file_backup \
  --build-base
```

---

## build-agent

Build a docker image for an agent.

### Usage

```bash
slop-code docker build-agent [OPTIONS] AGENT_CONFIG_PATH ENV_CONFIG_PATH
```

### Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `AGENT_CONFIG_PATH` | Yes | Path to agent configuration file |
| `ENV_CONFIG_PATH` | Yes | Path to environment configuration file |

### Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--force-build` | flag | false | Force rebuild agent image |
| `--force-build-base` | flag | false | Force rebuild base image too |

### Behavior

1. Loads agent and environment configurations
2. Uses agent's docker template if present
3. Builds image with agent-specific setup
4. Used automatically by `run` command when needed

### Examples

```bash
# Build agent image
slop-code docker build-agent \
  configs/agents/claude_code-2.0.51.yaml \
  configs/environments/docker-python3.12-uv.yaml

# Force rebuild everything
slop-code docker build-agent \
  configs/agents/claude_code-2.0.51.yaml \
  configs/environments/docker-python3.12-uv.yaml \
  --force-build --force-build-base
```

## See Also

- [run](run.md) - Run agents (builds images automatically)
- [Execution: Docker](../execution/docker.md) - Docker runtime documentation
