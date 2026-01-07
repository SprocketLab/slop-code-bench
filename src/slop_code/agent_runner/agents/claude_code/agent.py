"""Claude Code agent implementation built on top of the shared CLI runtime."""

from __future__ import annotations

import collections.abc
import json
import shlex
import tempfile
import typing as tp
from pathlib import Path

from pydantic import Field
from pydantic import JsonValue

from slop_code.agent_runner.agent import Agent
from slop_code.agent_runner.agent import AgentConfigBase
from slop_code.agent_runner.agents.cli_utils import AgentCommandResult
from slop_code.agent_runner.agents.cli_utils import stream_cli_command
from slop_code.agent_runner.agents.utils import HOME_PATH
from slop_code.agent_runner.agents.utils import resolve_env_vars
from slop_code.agent_runner.credentials import ProviderCredential
from slop_code.agent_runner.models import AgentCostLimits
from slop_code.agent_runner.models import AgentError
from slop_code.agent_runner.registry import register_agent
from slop_code.agent_runner.trajectory import TrajectoryStep
from slop_code.common import mask_sensitive_values
from slop_code.common.llms import APIPricing
from slop_code.common.llms import ModelDefinition
from slop_code.common.llms import ThinkingPreset
from slop_code.common.llms import TokenUsage
from slop_code.execution import EnvironmentSpec
from slop_code.execution import Session
from slop_code.execution import StreamingRuntime
from slop_code.execution.runtime import RuntimeResult
from slop_code.logging import get_logger

log = get_logger(__name__)

# Token limits for thinking presets
_THINKING_TOKEN_MAP: dict[str, int] = {
    "low": 4000,
    "medium": 10000,
    "high": 31999,
}


def _format_command_for_logging(
    command: collections.abc.Sequence[str] | str,
) -> str:
    """Convert a command into a readable shell string for logs."""
    if isinstance(command, str):
        out = command
    else:
        out = " ".join(shlex.quote(part) for part in command)
    if len(out) > 200:
        return f"{out[:200]}[{len(out) - 200:,} more]"
    return out


def serialize_tool_list(tools: list[str]) -> str | None:
    """Serialize tool list to a comma-separated string acceptable by the CLI."""
    filtered = [
        tool.strip() for tool in tools if isinstance(tool, str) and tool.strip()
    ]
    if not filtered:
        return None
    return ",".join(filtered)


class ClaudeCodeConfig(AgentConfigBase):
    """Configuration for ``ClaudeCodeAgent`` instances."""

    type: tp.Literal["claude_code"] = "claude_code"
    version: str
    binary: str = "claude"
    extra_args: list[str] = Field(
        default_factory=list,
        description="Additional arguments appended to the CLI invocation.",
    )
    env: dict[str, str] = Field(
        default_factory=dict,
        description="Environment variable overrides applied to the invocation.",
    )
    timeout: int | None = Field(
        default=None,
        description="Optional timeout (in seconds) for the CLI invocation.",
    )
    claude_version: str | None = None
    append_system_prompt: str | None = None
    allowed_tools: list[str] = Field(default_factory=list)
    disallowed_tools: list[str] = Field(default_factory=list)
    max_turns: int | None = None
    permission_mode: str | None = None
    settings: dict[str, JsonValue] = Field(default_factory=dict)
    max_output_tokens: int | None = None
    base_url: str | None = None
    docker_template: Path = Path(__file__).parent / "docker.j2"

    def get_binary(self) -> str:
        return self.binary


class ClaudeCodeAgent(Agent):
    """Agent implementation for the Claude Code CLI."""

    PROMPT_FILENAME = "prompt.txt"
    STDOUT_FILENAME = "stdout.jsonl"
    STDERR_FILENAME = "stderr.log"
    TRAJECTORY_FILENAME = "trajectory.jsonl"

    def __init__(
        self,
        problem_name: str,
        image: str,
        verbose: bool,
        # From base config
        cost_limits: AgentCostLimits,
        pricing: APIPricing,
        credential: ProviderCredential,
        # Claude Code specific
        binary: str,
        model: str,
        timeout: int | None,
        settings: dict[str, JsonValue],
        env: dict[str, str],
        extra_args: list[str],
        append_system_prompt: str | None,
        allowed_tools: list[str],
        disallowed_tools: list[str],
        permission_mode: str | None,
        base_url: str | None,
        thinking: ThinkingPreset | None,
        max_thinking_tokens: int | None,
        max_output_tokens: int | None,
    ) -> None:
        super().__init__(
            agent_name="claude_code",
            problem_name=problem_name,
            cost_limits=cost_limits,
            pricing=pricing,
            verbose=verbose,
        )

        # Store all config values as instance attributes
        self.credential = credential
        self.binary = binary
        self.model = model
        self.timeout = timeout
        self.settings = settings
        self.env = env
        self.extra_args = extra_args
        self.append_system_prompt = append_system_prompt
        self.allowed_tools = allowed_tools
        self.disallowed_tools = disallowed_tools
        self.permission_mode = permission_mode
        self.base_url = base_url
        self.thinking = thinking
        self.max_thinking_tokens = max_thinking_tokens
        self.max_output_tokens = max_output_tokens
        self._session: Session | None = None
        self._environment: EnvironmentSpec | None = None
        self._runtime: StreamingRuntime | None = None

        # Temporary directory for storing artifacts of agent execution
        self._tmp_dir: tempfile.TemporaryDirectory | None = None

        self._last_prompt: str = ""
        self._last_steps: list[TrajectoryStep] = []
        self._last_command: AgentCommandResult | None = None
        self._prior_cost = 0.0
        self._image = image
        self.steps = []
        self.final_result: RuntimeResult | None = None
        self._had_error: bool = False

    @classmethod
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
        """Create a ClaudeCodeAgent from a ClaudeCodeConfig."""
        if not isinstance(config, ClaudeCodeConfig):
            raise TypeError(
                f"Expected ClaudeCodeConfig, got {type(config).__name__}"
            )
        if image is None:
            raise ValueError("ClaudeCodeAgent requires an image")
        if model.pricing is None:
            raise AgentError("ClaudeCodeAgent requires a pricing configuration")

        # Get model slug for API calls
        model_slug = model.get_model_slug(credential.provider)

        # Get agent-specific settings from model catalog
        agent_settings = model.get_agent_settings("claude_code") or {}

        # Get endpoint from provider if specified in agent_specific
        # Use credential.provider (from CLI) to allow provider override
        endpoint = model.get_agent_endpoint("claude_code", credential.provider)

        # Resolve base_url: config > agent_settings > endpoint
        base_url = config.base_url
        if base_url is None and "base_url" in agent_settings:
            base_url = agent_settings["base_url"]
        if base_url is None and endpoint:
            base_url = endpoint.api_base

        # Merge env_overrides
        env = dict(config.env)
        if "env_overrides" in agent_settings:
            # Config env wins on conflicts
            env = {**agent_settings["env_overrides"], **env}

        # Resolve thinking: CLI/config override > model default
        thinking: ThinkingPreset | None = thinking_preset
        max_thinking_tokens: int | None = thinking_max_tokens
        if thinking is None and max_thinking_tokens is None:
            # Fall back to model's default thinking config
            thinking, max_thinking_tokens = model.get_thinking_config(
                "claude_code"
            )

        return cls(
            problem_name=problem_name,
            image=image,
            verbose=verbose,
            cost_limits=config.cost_limits,
            pricing=model.pricing,
            credential=credential,
            binary=config.binary,
            model=model_slug,
            timeout=config.timeout,
            settings=config.settings,
            env=env,
            extra_args=config.extra_args,
            append_system_prompt=config.append_system_prompt,
            allowed_tools=config.allowed_tools,
            disallowed_tools=config.disallowed_tools,
            permission_mode=config.permission_mode,
            base_url=base_url,
            thinking=thinking,
            max_thinking_tokens=max_thinking_tokens,
            max_output_tokens=config.max_output_tokens,
        )

    @property
    def session(self) -> Session:
        if self._session is None:
            raise AgentError(
                "ClaudeCodeAgent has not been set up with a session"
            )
        return self._session

    @property
    def spec(self) -> EnvironmentSpec:
        if self._environment is None:
            raise AgentError(
                "ClaudeCodeAgent has not been set up with a session"
            )
        return self._environment

    @property
    def workspace(self) -> Path:
        if self._workspace is None:
            raise AgentError(
                "ClaudeCodeAgent has not been set up with a session"
            )
        return self._workspace

    @property
    def runtime(self) -> StreamingRuntime:
        if self._runtime is None:
            raise AgentError(
                "ClaudeCodeAgent has not been set up with a runtime"
            )
        return self._runtime

    @property
    def tmp_dir(self) -> Path:
        if self._tmp_dir is None:
            raise AgentError(
                "ClaudeCodeAgent has not been set up with a tmp dir"
            )
        return Path(self._tmp_dir.name)

    def _get_volumes(self) -> dict[str, dict[str, str]]:
        volumes = {}
        settings = {
            "spinnerTipsEnabled": False,
        }
        if self.settings:
            settings.update(resolve_env_vars(self.settings))
        settings_path = self.tmp_dir / "settings.json"
        with settings_path.open("w") as f:
            json.dump(resolve_env_vars(self.settings), f)
        volumes[str(settings_path.absolute())] = {
            "bind": f"{HOME_PATH}/.claude/settings.json",
            "mode": "rw",
        }
        return volumes

    @staticmethod
    def parse_line(line: str):
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            return None, None, None
        if payload["type"] == "result":
            input_tokens = payload["usage"].get("input_tokens", 0)
            output_tokens = payload["usage"].get("output_tokens", 0)
            cache_write_tokens = payload["usage"].get(
                "cache_creation_input_tokens", 0
            )
            cache_read_tokens = payload["usage"].get(
                "cache_read_input_tokens", 0
            )
            tokens = TokenUsage(
                input=input_tokens,
                output=output_tokens,
                cache_read=cache_read_tokens,
                cache_write=cache_write_tokens,
                reasoning=0,
            )

            return (payload["total_cost_usd"], tokens, payload)

        message = payload.get("message", {})
        if not message or not isinstance(message, dict):
            return None, None, payload

        role = message.get("role", "")
        if role != "assistant":
            return None, None, payload
        usage = payload.get("message", {}).get("usage", {})
        if not usage:
            return None, None, payload

        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)
        cache_write_tokens = usage.get("cache_creation_input_tokens", 0)
        cache_read_tokens = usage.get("cache_read_input_tokens", 0)
        return (
            None,
            TokenUsage(
                input=input_tokens,
                output=output_tokens,
                cache_read=cache_read_tokens,
                cache_write=cache_write_tokens,
                reasoning=0,
            ),
            payload,
        )

    def _run(
        self, command: str | list[str], env_overrides: dict[str, str]
    ) -> RuntimeResult:
        if isinstance(command, list):
            # I dont trust shlex join tbh
            command = " ".join(command)

        gen = stream_cli_command(
            runtime=self.runtime,
            command=command,
            parser=self.parse_line,
            env=env_overrides,
            timeout=(float(self.timeout) if self.timeout is not None else None),
        )
        added_msg_ids: set[str] = set()
        final_result = None
        for step in gen:
            if not isinstance(step, tuple):
                self.log.debug("Received final result")
                final_result = step
                break
            cost, tokens, payload = step

            if payload is None:
                continue
            msg_id = payload.get("message", {}).get("id", None)
            content = payload.get("message", {}).get("content", {})
            if "text" in content:
                content = content["text"]
            else:
                content = json.dumps(content, ensure_ascii=False)

            self.log.debug(
                "Received payload",
                msg_id=msg_id,
                type=payload.get("type"),
                content=content[:128],
            )
            if (
                "is_error" in payload
                and payload["is_error"]
                and not self._had_error
            ):
                self._had_error = True
                self.log.error(
                    "Claude Code process had an error", error=payload
                )

            if cost is not None:
                self.log.debug("Got result", cost=cost, verbose=True)
                self.usage.cost = cost
                assert tokens is not None
                self.usage.net_tokens += tokens
                self.usage.current_tokens = tokens
            elif tokens is not None and msg_id not in added_msg_ids:
                cost = self.pricing.get_cost(tokens)
                self.log.debug(
                    "Received step",
                    tokens=tokens,
                    cost=cost,
                    steps=self.usage.steps,
                    verbose=True,
                )
                self.usage.cost += cost
                self.usage.steps += 1
                self.usage.current_tokens = tokens
                self.usage.net_tokens += tokens
                added_msg_ids.add(msg_id)
            self.steps.append(payload)
        return final_result

    def setup(self, session: Session) -> None:
        self._session = session
        self._environment = session.spec
        self._workspace = session.working_dir
        self._tmp_dir = tempfile.TemporaryDirectory()
        self._runtime = session.spawn(
            mounts=self._get_volumes(),
            env_vars={
                "HOME": HOME_PATH,
            },
            image=self._image,
            user="1000:1000",
            disable_setup=True,
        )
        self.log.debug(
            "agent.claude_code.setup",
            workspace=str(self._workspace),
            environment_type=self.spec.type if self.spec else None,
            image=self._image,
        )

    def run(self, task: str) -> None:
        self.log.debug(
            "Starting run...",
            thinking=self.thinking,
            max_thinking_tokens=self.max_thinking_tokens,
        )
        self._last_prompt = task
        self._last_steps = []
        self._last_command = None

        log_kwargs: dict[str, tp.Any] = {
            "workspace": str(self.workspace),
            "prompt_chars": len(task),
            "environment": self.spec.type,
            "extra_args": self.extra_args,
        }
        self.log.info("agent.claude_code.start", **log_kwargs)
        self.log.debug(
            "agent.claude_code.run.begin",
            prompt_preview=task[:128],
            prompt_truncated=len(task) > 128,
        )

        command, env_overrides = self._prepare_runtime_execution(task)
        self.log.debug(
            "agent.claude_code.command.prepared",
            command=_format_command_for_logging(command),
            env=mask_sensitive_values(env_overrides),
            environment_type=self.spec.type if self.spec else None,
        )

        result = self._run(command, env_overrides)

        if result is None:
            self.log.error("Claude Code process failed to start")
            raise AgentError("Claude Code process failed to start")

        self.final_result = result

        self.log.debug(
            "agent.claude_code.command.completed",
            exit_code=(result.exit_code if result else None),
            timed_out=(result.timed_out if result else None),
            stdout_chars=len(result.stdout or ""),
            stderr_chars=len(result.stderr or ""),
            step_count=len(self.steps),
            usage=self.usage,
        )
        self.log.debug(
            "agent.claude_code.steps.captured",
            total_steps=len(self._last_steps),
            agent_steps=self.usage.steps,
            cost=self.usage.cost,
        )
        if result.timed_out:
            message = (
                f"Claude Code process timed out after {self.timeout}s."
                if self.timeout is not None
                else "Claude Code process timed out."
            )
            log.error("agent.claude_code.timeout", timeout=self.timeout)
            raise AgentError(message)

        if self._had_error:
            self.log.error(
                "Claude Code process had an error", error=self.steps[-1]
            )
            raise AgentError("Claude Code process had an error")

    def _prepare_runtime_execution(
        self,
        task: str,
    ) -> tuple[collections.abc.Sequence[str] | str, dict[str, str]]:
        env_overrides = {key: str(value) for key, value in self.env.items()}

        # Set credential in environment
        env_overrides[self.credential.destination_key] = self.credential.value
        # When using a non-Claude-Code credential, also set ANTHROPIC_AUTH_TOKEN
        if self.credential.destination_key not in (
            "ANTHROPIC_API_KEY",
            "CLAUDE_CODE_OAUTH_TOKEN",
        ):
            env_overrides["ANTHROPIC_AUTH_TOKEN"] = self.credential.value
        if self.max_output_tokens is not None:
            env_overrides["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] = str(
                self.max_output_tokens
            )

        env_overrides["FORCE_AUTO_BACKGROUND_TASKS"] = "1"
        env_overrides["ENABLE_BACKGROUND_TASKS"] = "1"
        env_overrides["DISABLE_AUTOUPDATER"] = "1"
        env_overrides["DISABLE_NON_ESSENTIAL_MODEL_CALLS"] = "1"
        if self.base_url:
            env_overrides["ANTHROPIC_BASE_URL"] = self.base_url

        # Set thinking tokens from preset or explicit value
        thinking_tokens: int | None = None
        if self.max_thinking_tokens is not None:
            thinking_tokens = self.max_thinking_tokens
        elif self.thinking == "disabled":
            # Explicitly disable thinking with 0 tokens
            thinking_tokens = 0
        elif self.thinking is not None and self.thinking != "none":
            thinking_tokens = _THINKING_TOKEN_MAP[self.thinking]

        if thinking_tokens is not None:
            env_overrides["MAX_THINKING_TOKENS"] = str(thinking_tokens)
        cli_args = self._build_cli_args()
        cli_args.append(shlex.quote(task))
        command_str = " ".join(cli_args)
        return command_str, env_overrides

    def _build_cli_args(
        self,
    ) -> list[str]:
        args = [
            self.binary,
            "--output-format",
            "stream-json",
            "--verbose",
        ]

        allowed_tools_value = serialize_tool_list(self.allowed_tools)
        disallowed_tools_value = serialize_tool_list(self.disallowed_tools)

        option_map: dict[str, str | bool | None] = {
            "--append-system-prompt": self.append_system_prompt,
            "--model": self.model,
            "--max-turns": (
                str(self.cost_limits.step_limit)
                if self.cost_limits.step_limit > 0
                else None
            ),
            "--allowedTools": allowed_tools_value,
            "--disallowedTools": disallowed_tools_value,
            "--permission-mode": self.permission_mode,
        }

        for flag, value in option_map.items():
            if value is None:
                continue
            if isinstance(value, bool):
                if value:
                    args.append(flag)
                continue
            args.extend([flag, value])

        args.extend(self.extra_args)
        args.append("--print")
        args.append("--")
        return args

    def _write_artifacts(
        self,
        output_dir: Path,
    ) -> None:
        if self.final_result is not None:
            (output_dir / self.STDOUT_FILENAME).write_text(
                self.final_result.stdout or ""
            )
            (output_dir / self.STDERR_FILENAME).write_text(
                self.final_result.stderr
            )

    def reset(self) -> None:
        self._last_steps = []
        self._last_prompt = ""
        self._last_command = None

    def save_artifacts(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)

        self._write_artifacts(
            path,
        )

    def cleanup(self) -> None:
        self._session = None
        self.log.debug("agent.claude_code.cleanup")


# Register this agent type with the agent registry
register_agent("claude_code", ClaudeCodeAgent)
