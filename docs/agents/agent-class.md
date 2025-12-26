---
version: 1.0
last_updated: 2025-12-10
---

# Agent Class Guide

The `Agent` abstract base class defines the interface for all agent implementations. This guide covers the agent lifecycle, abstract methods, and how to implement new agents.

## Quick Start

Minimal agent implementation:

```python
from slop_code.agent_runner.agent import Agent, AgentConfigBase
from slop_code.agent_runner.registry import register_agent

class MyAgentConfig(AgentConfigBase, agent_type="my_agent", register=True):
    type: Literal["my_agent"] = "my_agent"
    # ... additional config fields

class MyAgent(Agent):
    @classmethod
    def _from_config(cls, config, model, credential, problem_name,
                     verbose, image, thinking_preset, thinking_max_tokens):
        return cls(
            problem_name=problem_name,
            cost_limits=config.cost_limits,
            pricing=model.pricing,
            verbose=verbose,
        )

    def setup(self, session):
        self._session = session

    def run(self, task):
        # Execute the task
        pass

    def reset(self):
        # Clear state
        pass

    def save_artifacts(self, path):
        # Save outputs
        pass

    def cleanup(self):
        # Release resources
        pass

register_agent("my_agent", MyAgent)
```

## Agent Lifecycle

```
┌─────────────────────────────────────────────────────┐
│                   Agent Lifecycle                    │
├─────────────────────────────────────────────────────┤
│                                                     │
│  1. Agent.from_config(...)  ──►  Create instance    │
│                                                     │
│  2. agent.setup(session)    ──►  Initialize env     │
│                                                     │
│  ┌─────────────────────────────────────────────┐   │
│  │  Per-Checkpoint Loop:                        │   │
│  │                                              │   │
│  │  3. agent.run(task)        ──►  Execute      │   │
│  │     or                                       │   │
│  │     agent.run_checkpoint(task) ──► + metrics │   │
│  │                                              │   │
│  │  4. agent.save_artifacts(path)              │   │
│  │                                              │   │
│  │  5. agent.finish_checkpoint() ──► Reset +    │   │  ◄── Called by runner
│  │                                   accumulate │   │      (not user override)
│  └─────────────────────────────────────────────┘   │
│                                                     │
│  6. agent.cleanup()         ──►  Release resources  │
│                                                     │
└─────────────────────────────────────────────────────┘
```

### Lifecycle Methods

| Method | Purpose | When Called |
|--------|---------|-------------|
| `from_config()` | Create agent from configuration | Once at start |
| `setup()` | Initialize with execution session | Once before first task |
| `run()` | Execute a task (no state reset) | Each checkpoint |
| `run_checkpoint()` | Execute with metrics capture | Alternative to run() |
| `finish_checkpoint()` | Reset state, accumulate cost | Called by runner between checkpoints (optional override) |
| `save_artifacts()` | Persist outputs | After each checkpoint |
| `reset()` | Clear conversation/state | Via finish_checkpoint() |
| `cleanup()` | Release resources | Once at end |

## Abstract Methods

All concrete agents must implement these methods:

### `_from_config()`

Factory method called by `Agent.from_config()`:

```python
@classmethod
@abstractmethod
def _from_config(
    cls,
    config: AgentConfigBase,
    model: ModelDefinition,
    credential: ProviderCredential,
    problem_name: str,
    verbose: bool,
    image: str | None,
    thinking_preset: ThinkingPreset | None = None,
    thinking_max_tokens: int | None = None,
) -> Agent:
    """Create agent from configuration."""
```

**Responsibilities:**
- Validate config type
- Extract agent-specific settings from model catalog
- Resolve thinking configuration
- Return configured agent instance

### `setup()`

Initialize the agent with an execution session:

```python
@abstractmethod
def setup(self, session: Session) -> None:
    """Set up the agent with execution environment."""
```

**Typical tasks:**
- Store session reference
- Create temporary directories
- Spawn runtime (Docker container, subprocess)
- Mount volumes and configure environment

### `run()`

Execute a task without resetting state:

```python
@abstractmethod
def run(self, task: str) -> None:
    """Execute task. Does NOT reset context/messages/stats."""
```

**Important:** `run()` does not reset state. Call `reset()` or `finish_checkpoint()` between checkpoints if needed.

### `reset()`

Clear agent state:

```python
@abstractmethod
def reset(self) -> None:
    """Reset conversation history and internal state."""
```

**Typical tasks:**
- Clear message history
- Reset internal counters
- Reinitialize model instance (if stateful)

### `save_artifacts()`

Persist agent outputs:

```python
@abstractmethod
def save_artifacts(self, path: Path) -> None:
    """Save native artifacts to directory."""
```

**Typical artifacts:**
- `stdout.jsonl` / `stdout.log`
- `stderr.log`
- `trajectory.jsonl`
- `messages.jsonl`

### `cleanup()`

Release resources:

```python
@abstractmethod
def cleanup(self) -> None:
    """Clean up resources (environments, connections, etc.)."""
```

**Typical tasks:**
- Stop Docker containers
- Close file handles
- Clean up temporary directories

## Factory Pattern

### `Agent.from_config()`

The public factory method that dispatches to the correct agent class:

```python
@classmethod
def from_config(
    cls,
    config: AgentConfigBase,
    model: ModelDefinition,
    credential: ProviderCredential,
    problem_name: str,
    verbose: bool,
    image: str | None,
    thinking_preset: ThinkingPreset | None = None,
    thinking_max_tokens: int | None = None,
) -> Agent:
    """Create agent instance from configuration."""
    agent_cls = get_agent_cls(config.type)
    return agent_cls._from_config(
        config, model, credential, problem_name,
        verbose, image, thinking_preset, thinking_max_tokens,
    )
```

**Flow:**
1. Look up agent class from registry using `config.type`
2. Call `_from_config()` on the concrete class
3. Return configured agent instance

## Agent Registration Pattern

When implementing a new agent, you must register both the **config class** and the **agent class** in the registries. This two-step pattern enables the factory to dispatch to the correct agent type.

### Step 1: Config Auto-Registration

Define your config class with the `agent_type` parameter. This automatically registers the config:

```python
from slop_code.agent_runner.agent import AgentConfigBase

class MyAgentConfig(AgentConfigBase, agent_type="my_agent", register=True):
    """Configuration for MyAgent instances."""
    type: Literal["my_agent"] = "my_agent"
    # ... additional config fields ...
```

**What happens:**
- `__init_subclass__` is called when the class is defined
- If `register=True` (default), the config is registered in `_CONFIG_REGISTRY`
- The agent type is inferred from `agent_type` parameter or the `type` field default

### Step 2: Manual Agent Registration

After defining your agent class, register it explicitly:

```python
from slop_code.agent_runner.agent import Agent
from slop_code.agent_runner.registry import register_agent

class MyAgent(Agent):
    """Implementation of MyAgent."""

    @classmethod
    def _from_config(cls, config, model, credential, problem_name,
                     verbose, image, thinking_preset, thinking_max_tokens):
        # ... create and return agent instance ...
        return cls(...)

    # ... implement other abstract methods ...

# Register the agent class
register_agent("my_agent", MyAgent)
```

**Why manual?** The agent class doesn't use `__init_subclass__` like the config, so we register it explicitly at module load time.

### Complete Example

```python
# my_agent.py
from typing import Literal
from slop_code.agent_runner.agent import Agent, AgentConfigBase
from slop_code.agent_runner.registry import register_agent

# Step 1: Config auto-registers
class MyAgentConfig(AgentConfigBase, agent_type="my_agent", register=True):
    type: Literal["my_agent"] = "my_agent"
    timeout: int = 60
    custom_param: str = "default"

# Step 2: Agent implementation
class MyAgent(Agent):
    def _from_config(cls, config, model, credential, problem_name,
                     verbose, image, thinking_preset, thinking_max_tokens):
        return cls(problem_name=problem_name, cost_limits=config.cost_limits, ...)

    def setup(self, session):
        pass

    def run(self, task):
        pass

    def reset(self):
        pass

    def save_artifacts(self, path):
        pass

    def cleanup(self):
        pass

# Step 3: Manual registration
register_agent("my_agent", MyAgent)
```

### Registry Lookups

The registries enable these lookups:

```python
from slop_code.agent_runner.registry import get_agent_config_cls, get_agent_cls

# Get config class
config_cls = get_agent_config_cls("my_agent")  # MyAgentConfig

# Get agent class
agent_cls = get_agent_cls("my_agent")  # MyAgent

# Create agent from config
agent = agent_cls.from_config(
    config=config_cls(...),
    model=...,
    credential=...,
    problem_name=...,
    verbose=True,
)
```

## Agent Versioning

Agent configs can include a `version` field:

```python
class MyAgentConfig(AgentConfigBase):
    type: Literal["my_agent"] = "my_agent"
    version: str  # Required for this agent
```

**Use cases:**
- Different agent binary versions (e.g., `claude_code-2.0.51`)
- Different API versions
- Different capability sets

The version affects:
- Docker image naming: `{type}-{version}-{env_name}`
- Agent binary selection
- Feature availability

## Usage Tracking

Agents track usage via the `UsageTracker` class:

### UsageTracker

```python
class UsageTracker(BaseModel):
    cost: float = 0           # Total cost in dollars
    steps: int = 0            # Number of execution steps
    net_tokens: TokenUsage    # Cumulative token usage
    current_tokens: TokenUsage  # Latest step's tokens
```

### TokenUsage

```python
class TokenUsage(BaseModel):
    input: int = 0        # Input tokens
    output: int = 0       # Output tokens
    cache_read: int = 0   # Cache read tokens
    cache_write: int = 0  # Cache write tokens
    reasoning: int = 0    # Reasoning tokens (extended thinking)
```

### Recording Steps

Update usage with `UsageTracker.step()`:

```python
self.usage.step(
    cost=step_cost,
    tokens=TokenUsage(
        input=1000,
        output=500,
        cache_read=200,
    ),
)
```

### Cost Calculation

Calculate cost from tokens and pricing:

```python
cost = self.pricing.get_cost(tokens)
```

## Checkpoint Methods

### `run_checkpoint()`

Wraps `run()` with timing and error capture:

```python
def run_checkpoint(self, task: str) -> CheckpointInferenceResult:
    """Run task and capture execution metrics."""
    started = datetime.now()
    had_error = False
    error = None
    try:
        self.run(task)
    except Exception as e:
        had_error = True
        error = traceback.format_exc()
    finally:
        completed = datetime.now()
        elapsed = (completed - started).total_seconds()

    return CheckpointInferenceResult(
        started=started,
        completed=completed,
        elapsed=elapsed,
        usage=self.usage,
        had_error=had_error,
        error_message=error,
    )
```

### `finish_checkpoint()`

Reset state and accumulate cost:

```python
def finish_checkpoint(self, reset_context: bool = True) -> None:
    """Reset agent for new checkpoint."""
    if reset_context:
        self.reset()
    self.prior_cost += self.usage.cost
    self.usage = UsageTracker()
```

### Note on finish_checkpoint()

The `finish_checkpoint()` method is **called by the runner** automatically between checkpoints. Agents do NOT need to override this method unless they have custom cleanup beyond the default behavior.

**Default behavior** (from base Agent class):
1. Calls `self.reset()` if `reset_context` is enabled
2. Updates `prior_cost` with accumulated usage
3. Creates a new `UsageTracker` for next checkpoint

**When to override:**
- Custom state that needs special handling between checkpoints
- Additional logging or metrics tracking
- Resource cleanup beyond conversation reset

**Most agents should NOT override this method.**

### `CheckpointInferenceResult`

Result of running a checkpoint:

```python
class CheckpointInferenceResult(BaseModel):
    started: datetime         # When execution started
    completed: datetime       # When execution finished
    elapsed: float           # Duration in seconds
    usage: UsageTracker      # Token/cost usage
    had_error: bool          # Whether an error occurred
    error_message: str | None  # Error details
    checkpoint_path: Path | None
    snapshot_dir: Path | None
    artifacts_dir: Path | None
```

## Agent State Management

### State Across Checkpoints

Agents maintain different types of state with different lifetimes:

| State Type | Persists Across Checkpoints? | Reset By |
|------------|------------------------------|----------|
| Conversation history | Conditional* | `reset()` if `reset_context=True` |
| Working directory | Yes | Managed by Session/Workspace |
| `prior_cost` | Yes | Never (accumulates) |
| `usage` tracker | No | `finish_checkpoint()` creates new tracker |
| Custom agent state | Depends** | Agent's `reset()` implementation |

*Depends on `reset_context` flag (set per run, not per agent)
**Depends on agent implementation

### The reset_context Flag

Configured at runtime (not in agent config):

```python
# In runner configuration
reset_context = False  # Default: maintain state
```

**When `reset_context=False` (default):**
- Conversation history preserved
- Agent can reference prior checkpoint context
- More "human-like" continuation

**When `reset_context=True`:**
- `reset()` called between checkpoints
- Fresh conversation each checkpoint
- Prevents context pollution

### Implementing reset()

Override to clear agent-specific state:

```python
def reset(self) -> None:
    """Clear conversation and internal state."""
    super().reset()  # Call base if it exists

    self._messages = []
    self._internal_cache = {}
    # DON'T reset self.usage (tracked separately)
    # DON'T reset self.prior_cost (must accumulate)
    # DON'T reset working directory (managed by Session)
```

### Cost Accumulation

Cost **always accumulates** regardless of `reset_context`:

```python
# Checkpoint 1 uses $0.50
self.usage.cost = 0.50

# finish_checkpoint() called:
self.prior_cost += self.usage.cost  # Now prior_cost = $0.50
self.usage = UsageTracker()  # New tracker starts at $0

# Checkpoint 2 uses $0.30
self.usage.cost = 0.30

# Total cost check:
net_cost = self.prior_cost + self.usage.cost  # $0.80
if net_cost > cost_limit:
    raise AgentError("Cost limit exceeded")
```

This enables:
- Per-checkpoint cost tracking (`usage.cost`)
- Total run cost tracking (`prior_cost + usage.cost`)
- Cost limit enforcement across checkpoints

## Error Handling

### Exception Types

```python
class AgentError(Exception):
    """Base exception for agent errors."""

class UnsupportedEnvironmentError(AgentError):
    """Agent cannot run in this environment type."""

class AgentSetupError(AgentError):
    """Error during agent initialization."""

class AgentStepError(AgentError):
    """Error during individual execution step."""
```

### Limit Checking

Check if limits are exceeded:

```python
def hit_net_rate_limit(self) -> bool:
    """Check if net cost limit hit."""
    if self.cost_limits.net_cost_limit == 0:
        return False
    return (
        self.usage.cost + self.prior_cost
        >= self.cost_limits.net_cost_limit
    )
```

### Error Handling Patterns

#### When to Raise vs Continue

**Raise AgentError when:**
- Setup fails (missing credentials, invalid config)
- Agent process fails to start
- Agent process exits unexpectedly
- Cost/step limits exceeded
- Timeout reached

**Log and continue when:**
- Individual command fails (agent can retry)
- Parsing errors in output (may extract partial results)
- Rate limits hit (if retry logic exists)

#### Error Context

Always include context in error messages:

```python
from slop_code.agent_runner.models import AgentSetupError

if not api_key:
    raise AgentSetupError(
        f"Failed to initialize {self.__class__.__name__}: "
        f"missing required credential for provider '{provider}'. "
        f"Set {env_var} environment variable or configure credential file."
    )
```

#### Checkpoint Error Handling

Errors during checkpoints are captured in `CheckpointInferenceResult`:

```python
try:
    result = self._run_impl(task)
except Exception as e:
    return CheckpointInferenceResult(
        had_error=True,
        error_message=traceback.format_exc(),
        usage=self.usage,  # Partial usage still recorded
        elapsed=time.time() - start_time,
        snapshot_path=None,
        artifacts_path=self.artifacts_path,
    )
```

This allows the runner to:
- Continue to next checkpoints
- Continue to next problems
- Record partial progress
- Generate complete reports even with failures

## Replay Support

Agents can optionally support trajectory replay:

```python
def supports_replay(self) -> bool:
    """Return whether agent supports replay."""
    return False  # Override to return True

def run_replay(self, path: Path) -> CheckpointInferenceResult:
    """Replay recorded trajectory."""
    raise AgentError(f"{self.__class__.__name__} does not support replay")
```

Currently, only MiniSWE supports replay.

## Adding a New Agent

### Step 1: Create Config Class

```python
# src/slop_code/agent_runner/agents/my_agent/agent.py

from typing import Literal
from slop_code.agent_runner.agent import AgentConfigBase

class MyAgentConfig(AgentConfigBase, agent_type="my_agent", register=True):
    type: Literal["my_agent"] = "my_agent"
    version: str
    # ... additional fields
```

### Step 2: Create Agent Class

```python
class MyAgent(Agent):
    def __init__(
        self,
        problem_name: str,
        cost_limits: AgentCostLimits,
        pricing: APIPricing | None,
        verbose: bool,
        # ... agent-specific params
    ):
        super().__init__(
            agent_name="my_agent",
            problem_name=problem_name,
            cost_limits=cost_limits,
            pricing=pricing,
            verbose=verbose,
        )
        # Store agent-specific attributes

    @classmethod
    def _from_config(cls, config, model, credential, problem_name,
                     verbose, image, thinking_preset, thinking_max_tokens):
        if not isinstance(config, MyAgentConfig):
            raise TypeError(f"Expected MyAgentConfig")
        # Build and return agent instance
        return cls(...)

    def setup(self, session):
        # Initialize with session
        pass

    def run(self, task):
        # Execute task
        pass

    def reset(self):
        # Clear state
        pass

    def save_artifacts(self, path):
        # Save outputs
        pass

    def cleanup(self):
        # Release resources
        pass
```

### Step 3: Register Agent Class

**IMPORTANT:** Two separate registrations are required:

#### 1. Config Registration (Automatic)
The config class is automatically registered via `__init_subclass__` when you inherit from `AgentConfigBase` with `register=True`:

```python
class MyAgentConfig(AgentConfigBase, register=True):
    agent_type: str = "my_agent"  # Maps config to agent type
    # ...
```

#### 2. Agent Class Registration (Manual)
The agent class must be explicitly registered:

```python
from slop_code.agent_runner.registry import register_agent

@register_agent("my_agent")  # Decorator style (preferred)
class MyAgent(Agent):
    # ...

# OR function style:
register_agent("my_agent", MyAgent)
```

**Why two registrations?**
- Config registry: Maps agent type string → config class
- Agent registry: Maps agent type string → agent implementation
- This separation allows config validation before agent instantiation

Place the registration at module level (not inside the class) so it runs at import time.

### Step 4: Create Config File

```yaml
# configs/agents/my_agent-1.0.yaml
type: my_agent
version: "1.0"
cost_limits:
  cost_limit: 20
  step_limit: 100
  net_cost_limit: 0
```

### Step 5: Add Model Settings (Optional)

```yaml
# configs/models/my-model.yaml
agent_specific:
  my_agent:
    custom_setting: value
```

## API Reference

### Agent Base Class

```python
class Agent(ABC):
    def __init__(
        self,
        agent_name: str,
        problem_name: str,
        cost_limits: AgentCostLimits,
        pricing: APIPricing | None,
        verbose: bool,
    ) -> None: ...

    @classmethod
    def from_config(cls, config, model, credential, ...) -> Agent: ...

    @abstractmethod
    def setup(self, session: Session) -> None: ...

    @abstractmethod
    def run(self, task: str) -> None: ...

    @abstractmethod
    def reset(self) -> None: ...

    @abstractmethod
    def save_artifacts(self, path: Path) -> None: ...

    @abstractmethod
    def cleanup(self) -> None: ...

    def run_checkpoint(self, task: str) -> CheckpointInferenceResult: ...

    def finish_checkpoint(self, reset_context: bool = True) -> None: ...

    def hit_net_rate_limit(self) -> bool: ...

    def supports_replay(self) -> bool: ...
```

### Instance Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `problem_name` | str | Name of problem being solved |
| `log` | Logger | Structured logger |
| `usage` | UsageTracker | Current checkpoint usage |
| `cost_limits` | AgentCostLimits | Execution limits |
| `pricing` | APIPricing \| None | Token pricing |
| `verbose` | bool | Logging verbosity |
| `prior_cost` | float | Accumulated cost from prior checkpoints |

### StreamParser Protocol

Some agents parse streaming output from CLI tools using the `StreamParser` protocol:

```python
from typing import Protocol, Mapping, Iterable

class StreamParser(Protocol):
    """Parses streaming RuntimeEvents from SubmissionRuntime.stream()."""

    @property
    def totals(self) -> Mapping[str, int]:
        """Current token/cost totals."""
        ...

    def consume(self, event: RuntimeEvent) -> None:
        """Process a single runtime event."""
        ...

    def drain_steps(self) -> Iterable[TrajectoryStep]:
        """Yield completed trajectory steps."""
        ...

    def finish(self) -> Iterable[TrajectoryStep]:
        """Finalize and yield remaining steps."""
        ...
```

**Use cases:**
- Parsing Claude Code CLI JSON output
- Extracting step-by-step execution from agent logs
- Real-time token tracking during execution

**Example agent using StreamParser:**

```python
class MyCLIAgent(Agent):
    def _run_impl(self, task: str) -> CheckpointInferenceResult:
        parser = MyCLIStreamParser()

        for event in self.runtime.stream(command, env, None, timeout):
            parser.consume(event)

            # Drain completed steps
            for step in parser.drain_steps():
                self._trajectory.append(step)

        # Finalize
        for step in parser.finish():
            self._trajectory.append(step)

        # Get totals
        self.usage.step(parser.totals)
```

See `claude_code/agent.py` for complete implementation example.

## See Also

- [Agent Configuration Guide](agent-config.md) - Configuration options
- [Models Guide](models.md) - Model definitions
- [Credentials Guide](credentials.md) - Credential resolution
