"""Kimi CLI agent implementation."""

from __future__ import annotations

import json
import shlex
import typing as tp
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path

from jinja2 import Template
from pydantic import Field

from slop_code.agent_runner.agent import RETRY_PROMPT
from slop_code.agent_runner.agent import Agent
from slop_code.agent_runner.agent import AgentConfigBase
from slop_code.agent_runner.agents.cli_utils import AgentCommandResult
from slop_code.agent_runner.agents.kimi_cli.parser import _WireStep
from slop_code.agent_runner.agents.kimi_cli.parser import (
    group_events_into_steps,
)
from slop_code.agent_runner.agents.kimi_cli.parser import has_final_result
from slop_code.agent_runner.agents.kimi_cli.parser import parse_wire_events
from slop_code.agent_runner.agents.utils import HOME_PATH
from slop_code.agent_runner.credentials import CredentialType
from slop_code.agent_runner.credentials import ProviderCredential
from slop_code.agent_runner.models import AgentCostLimits
from slop_code.agent_runner.models import AgentError
from slop_code.agent_runner.registry import register_agent
from slop_code.common.llms import APIPricing
from slop_code.common.llms import ModelDefinition
from slop_code.common.llms import ThinkingPreset
from slop_code.common.llms import TokenUsage
from slop_code.execution import DockerEnvironmentSpec
from slop_code.execution import EnvironmentSpec
from slop_code.execution import Session
from slop_code.execution import StreamingRuntime

_DEFAULT_MAX_CONTEXT_SIZE = 131072
_SIGTERM_EXIT_CODE = 128 + 15
_KIMI_CONFIG_PATH = "/tmp/kimi-config.json"  # noqa: S108
_NO_FINAL_RESULT_MARKER = (
    "kimi-cli: stdout closed before a final result was received"
)
_MAX_REASONING_CHARS = 1800
_MAX_ASSISTANT_CHARS = 1200
_MAX_TOOL_ARG_CHARS = 160
_MAX_TOOL_OUTPUT_CHARS = 400
_MAX_SECTION_CHARS = 1800
_MAX_EVENT_SUMMARY_CHARS = 280


@dataclass
class _AttemptRecord:
    """Raw artifacts captured for a single Kimi CLI invocation.

    ``run_checkpoint`` may invoke the CLI several times (one initial run plus
    retries) before artifacts are saved once at the end. Keeping one record per
    invocation prevents a crashed attempt's stderr from being overwritten by
    the attempt that follows it.
    """

    prompt: str
    command_text: str
    stdout: str
    stderr: str
    events: list[dict[str, tp.Any]] = field(default_factory=list)


_PROVIDER_CONFIG: dict[str, dict[str, tp.Any]] = {
    "moonshot": {
        "type": "kimi",
        "base_url": "https://api.moonshot.ai/v1",
        "env_keys": ["MOONSHOT_API_KEY"],
    },
    "kimi": {
        "type": "kimi",
        "base_url": "https://api.kimi.com/coding/v1",
        "env_keys": ["KIMI_API_KEY", "MOONSHOT_API_KEY"],
    },
    # Portkey gateway (OpenAI-compatible); model slugs must be Portkey model
    # catalog ids, e.g. "@openrouter/moonshotai/kimi-k3" via provider_slugs.
    "portkey": {
        "type": "kimi",
        "base_url": "https://api.portkey.ai/v1",
        "env_keys": ["PORTKEY_API_KEY"],
    },
}


class KimiCliConfig(AgentConfigBase):
    """Configuration for ``KimiCliAgent`` instances."""

    type: tp.Literal["kimi_cli"] = "kimi_cli"
    version: str
    binary: str = "kimi"
    docker_template: Path = Path(__file__).parent / "docker.j2"
    timeout: int | None = Field(
        default=None,
        description="Optional timeout (in seconds) for the CLI invocation.",
    )
    extra_args: list[str] = Field(
        default_factory=list,
        description="Additional arguments appended to the CLI invocation.",
    )
    env: dict[str, str] = Field(
        default_factory=dict,
        description="Environment variable overrides applied to the invocation.",
    )
    base_url: str | None = Field(
        default=None,
        description="Optional provider API base URL override.",
    )
    max_context_size: int | None = Field(
        default=None,
        description="Optional max context size override for Kimi model config.",
    )

    def get_docker_file(self, base_image: str) -> str | None:
        """Render the Docker template with version."""
        if self.docker_template is None:
            return None
        template = self.docker_template.read_text()
        return Template(template).render(
            base_image=base_image,
            version=self.version,
        )


class KimiCliAgent(Agent):
    """Agent implementation built on top of the Kimi CLI executor."""

    PROMPT_FILENAME = "prompt.txt"
    COMMAND_FILENAME = "command.txt"
    OUTPUT_FILENAME = "kimi-cli.txt"
    STDOUT_FILENAME = "stdout.log"
    STDERR_FILENAME = "stderr.log"
    EVENTS_FILENAME = "events.jsonl"
    TRAJECTORY_FILENAME = "trajectory.jsonl"

    def __init__(
        self,
        problem_name: str,
        verbose: bool,  # noqa: FBT001
        image: str,
        # From base config
        cost_limits: AgentCostLimits,
        pricing: APIPricing | None,
        credential: ProviderCredential | None,
        # Kimi specific
        binary: str,
        provider: str,
        model: str,
        timeout: int | None,
        extra_args: list[str],
        env: dict[str, str],
        base_url: str | None,
        max_context_size: int | None,
        thinking: ThinkingPreset | None = None,
        max_thinking_tokens: int | None = None,
    ) -> None:
        super().__init__(
            agent_name="kimi_cli",
            problem_name=problem_name,
            cost_limits=cost_limits,
            pricing=pricing,
            verbose=verbose,
        )

        self.credential = credential
        self.binary = binary
        self.provider = provider
        self.model = model
        self.timeout = timeout
        self.extra_args = extra_args
        self.env = env
        self.base_url = base_url
        self.max_context_size = max_context_size
        self.thinking = thinking
        self.max_thinking_tokens = max_thinking_tokens

        self._image = image
        self._session: Session | None = None
        self._environment: EnvironmentSpec | None = None
        self._runtime: StreamingRuntime | None = None

        self._task: str = ""
        self._last_prompt: str = ""
        self._last_command_text: str = ""
        self._last_stdout: str = ""
        self._last_stderr: str = ""
        self._last_events: list[dict[str, tp.Any]] = []
        self._attempts: list[_AttemptRecord] = []

    @classmethod
    def _from_config(
        cls,
        config: AgentConfigBase,
        model: ModelDefinition,
        credential: ProviderCredential,
        problem_name: str,
        verbose: bool,  # noqa: FBT001
        image: str | None,
        thinking_preset: ThinkingPreset | None = None,
        thinking_max_tokens: int | None = None,
    ) -> Agent:
        """Create a KimiCliAgent from a KimiCliConfig."""
        if not isinstance(config, KimiCliConfig):
            raise TypeError(
                f"Expected KimiCliConfig, got {type(config).__name__}"
            )
        if image is None:
            raise ValueError("KimiCliAgent requires an image")

        thinking = thinking_preset
        max_thinking_tokens = thinking_max_tokens
        if thinking is None and max_thinking_tokens is None:
            thinking, max_thinking_tokens = model.get_thinking_config(
                "kimi_cli"
            )

        model_slug = model.get_model_slug(credential.provider)
        return cls(
            problem_name=problem_name,
            verbose=verbose,
            image=image,
            cost_limits=config.cost_limits,
            pricing=model.pricing,
            credential=credential,
            binary=config.binary,
            provider=credential.provider,
            model=model_slug,
            timeout=config.timeout,
            extra_args=config.extra_args,
            env=config.env,
            base_url=config.base_url,
            max_context_size=config.max_context_size,
            thinking=thinking,
            max_thinking_tokens=max_thinking_tokens,
        )

    @staticmethod
    def parse_line(
        line: str,
        pricing: APIPricing | None = None,
    ) -> tuple[float | None, TokenUsage | None, dict | None]:
        """Parse a single Kimi wire line.

        Returns only event payloads. Final JSON-RPC ``result`` messages are
        skipped so downstream consumers operate on wire events only.
        """
        try:
            payload = json.loads(line, strict=False)
        except json.JSONDecodeError:
            return None, None, None

        if payload.get("method") != "event":
            return None, None, None

        params = payload.get("params")
        if not isinstance(params, dict):
            return None, None, None

        tokens: TokenUsage | None = None
        if params.get("type") == "StatusUpdate":
            status_payload = params.get("payload", {})
            if isinstance(status_payload, dict):
                token_usage = status_payload.get("token_usage", {})
                if isinstance(token_usage, dict):
                    tokens = KimiCliAgent._token_usage_from_wire(token_usage)

        cost = pricing.get_cost(tokens) if pricing and tokens else None
        return cost, tokens, params

    @staticmethod
    def _extract_reasoning_tokens(
        token_usage: dict[str, tp.Any],
    ) -> int:
        for key in (
            "reasoning",
            "reasoning_tokens",
            "output_reasoning",
            "output_reasoning_tokens",
            "reasoning_output_tokens",
        ):
            value = token_usage.get(key)
            if isinstance(value, int | float):
                return int(value)
        return 0

    @staticmethod
    def _token_usage_from_wire(
        token_usage: dict[str, tp.Any],
    ) -> TokenUsage:
        input_other = int(token_usage.get("input_other") or 0)
        cache_read = int(token_usage.get("input_cache_read") or 0)
        cache_creation = int(token_usage.get("input_cache_creation") or 0)
        output_tokens = int(token_usage.get("output") or 0)
        reasoning_tokens = KimiCliAgent._extract_reasoning_tokens(token_usage)
        return TokenUsage(
            input=input_other + cache_read + cache_creation,
            output=output_tokens,
            cache_read=cache_read,
            cache_write=cache_creation,
            reasoning=reasoning_tokens,
        )

    @property
    def session(self) -> Session:
        if self._session is None:
            raise AgentError("KimiCliAgent has not been set up with a session")
        return self._session

    @property
    def spec(self) -> EnvironmentSpec:
        if self._environment is None:
            raise AgentError("KimiCliAgent has not been set up with a session")
        return self._environment

    @property
    def runtime(self) -> StreamingRuntime:
        if self._runtime is None:
            raise AgentError("KimiCliAgent has not been set up with a runtime")
        return self._runtime

    def setup(self, session: Session) -> None:
        self._session = session
        self._environment = session.spec
        self._runtime = session.spawn(
            mounts={},
            env_vars={"HOME": HOME_PATH},
            image=self._image,
            disable_setup=True,
        )

    def run(self, task: str) -> None:
        self._task = task
        self._execute_prompt(task)

    def retry(self) -> None:
        """Re-run the CLI, always restating the original task.

        The Kimi CLI has no session resume: every invocation starts a fresh
        process with an empty context. A bare "continue from where you left
        off" therefore reaches a model that has no idea what the task was, and
        it answers truthfully that there is nothing to continue - a clean exit
        that the runner records as a completed checkpoint over an empty
        workspace. Restating the task makes the retry a real second attempt.
        """
        if not self._task:
            raise AgentError("KimiCliAgent has no task to retry")

        has_progress = self._workspace_has_files()
        prompt = (
            f"{RETRY_PROMPT} The original task was:\n\n{self._task}"
            if has_progress
            else self._task
        )
        self.log.info(
            "agent.kimi_cli.retry",
            workspace=str(self.session.working_dir),
            workspace_has_files=has_progress,
            attempts=len(self._attempts),
        )
        self._execute_prompt(prompt)

    def _workspace_has_files(self) -> bool:
        working_dir = self.session.working_dir
        if not working_dir.is_dir():
            return False
        return any(
            entry.name != ".git" and not entry.name.startswith(".")
            for entry in working_dir.iterdir()
        )

    def _execute_prompt(self, task: str) -> None:
        self._last_prompt = task
        self._last_command_text = ""
        self._last_stdout = ""
        self._last_stderr = ""
        self._last_events = []

        log_kwargs: dict[str, tp.Any] = {
            "workspace": str(self.session.working_dir),
            "prompt_chars": len(task),
            "environment": self.session.spec.type,
            "extra_args": self.extra_args,
            "provider": self.provider,
        }
        if isinstance(self.session.spec, DockerEnvironmentSpec):
            log_kwargs["image"] = self.session.spec.docker.image
        self.log.info("agent.kimi_cli.start", **log_kwargs)

        command_result = self._run_invocation(task)
        self._sync_usage(command_result.usage_totals)

        runtime_result = command_result.result
        if runtime_result is None:
            message = "Kimi process failed to start"
            self.log.error(
                "agent.kimi_cli.start_failed",
                error_message=message,
                agent_message=command_result.error_message,
            )
            raise AgentError(message)

        if runtime_result.timed_out:
            message = (
                f"Kimi process timed out after {self.timeout}s."
                if self.timeout is not None
                else "Kimi process timed out."
            )
            self.log.error(
                "agent.kimi_cli.timeout",
                error_message=message,
                timeout=self.timeout,
            )
            raise AgentError(message)

        saw_final_result = bool(
            int(command_result.usage_totals.get("final_result_seen") or 0)
        )
        if runtime_result.exit_code == _SIGTERM_EXIT_CODE and saw_final_result:
            return

        if runtime_result.exit_code != 0:
            message = (
                f"Kimi process failed with exit code {runtime_result.exit_code}"
            )
            if runtime_result.stderr:
                message = f"{message}\n--- Stderr ---\n{runtime_result.stderr.strip()}"
            self.log.error(
                "agent.kimi_cli.exit",
                error_message=message,
                exit_code=runtime_result.exit_code,
            )
            raise AgentError(message)

        if not saw_final_result:
            message = "Kimi process completed without a final response"
            self.log.error(
                "agent.kimi_cli.no_final_response",
                error_message=message,
            )
            raise AgentError(message)

    def _run_invocation(self, task: str) -> AgentCommandResult:
        command, env_overrides = self._prepare_runtime_execution(task)
        if self._session is None:
            raise AgentError("KimiCliAgent has not been set up with a session")

        command_text = shlex.join(command)
        self._last_command_text = command_text

        runtime_result = None
        stdout_text = ""
        stderr_text = ""
        stdout_buffer = ""
        live_step_count = 0

        for event in self.runtime.stream(
            command=command_text,
            env=env_overrides,
            timeout=(float(self.timeout) if self.timeout is not None else None),
        ):
            if event.kind == "stdout":
                chunk = event.text or ""
                stdout_text += chunk
                stdout_buffer += chunk
                while "\n" in stdout_buffer:
                    line, stdout_buffer = stdout_buffer.split("\n", 1)
                    params = self._parse_streamed_wire_event(line.strip())
                    if params is None:
                        continue
                    if params.get("type") == "StepBegin":
                        live_step_count += 1
                        self.usage.steps += 1
                continue
            if event.kind == "stderr":
                stderr_text += event.text or ""
                continue
            if event.kind == "finished":
                runtime_result = event.result
                break

        self._last_stdout = stdout_text
        self._last_stderr = stderr_text
        self._last_events = parse_wire_events(stdout_text)
        self._attempts.append(
            _AttemptRecord(
                prompt=task,
                command_text=command_text,
                stdout=stdout_text,
                stderr=stderr_text,
                events=self._last_events,
            )
        )
        wire_steps = group_events_into_steps(self._last_events)
        usage_totals = self._summarize_wire_steps(wire_steps)
        usage_totals["steps"] = len(wire_steps)
        usage_totals["live_steps"] = live_step_count
        usage_totals["final_result_seen"] = int(has_final_result(stdout_text))

        return AgentCommandResult(
            result=runtime_result,
            steps=[],
            usage_totals=usage_totals,
            stdout=stdout_text,
            stderr=stderr_text,
        )

    @staticmethod
    def _parse_streamed_wire_event(line: str) -> dict[str, tp.Any] | None:
        if not line or not line.lstrip().startswith('{"jsonrpc"'):
            return None
        try:
            payload = json.loads(line, strict=False)
        except json.JSONDecodeError:
            return None
        if payload.get("method") != "event":
            return None
        params = payload.get("params")
        if not isinstance(params, dict):
            return None
        return params

    @staticmethod
    def _truncate_text(text: str, max_chars: int) -> str:
        if len(text) <= max_chars:
            return text
        overflow = len(text) - max_chars
        return f"{text[:max_chars]}... [truncated {overflow} chars]"

    @classmethod
    def _format_tool_arg_value(cls, key: str, value: tp.Any) -> str:
        if key == "content" and isinstance(value, str):
            return f"<{len(value)} chars>"
        if isinstance(value, str):
            return cls._truncate_text(value, _MAX_TOOL_ARG_CHARS)
        if isinstance(value, list):
            return f"<list len={len(value)}>"
        if isinstance(value, dict):
            return f"<object keys={len(value)}>"
        if value is None:
            return "null"
        return str(value)

    @classmethod
    def _summarize_tool_args(cls, arguments: dict[str, tp.Any]) -> str:
        if not arguments:
            return ""

        ordered_keys: list[str] = []
        for key in ("command", "cmd", "path", "file_path", "target", "url"):
            if key in arguments:
                ordered_keys.append(key)
        for key in sorted(arguments):
            if key not in ordered_keys:
                ordered_keys.append(key)

        rendered: list[str] = []
        max_keys = 5
        for key in ordered_keys[:max_keys]:
            rendered.append(
                f"{key}={cls._format_tool_arg_value(key, arguments[key])}"
            )
        hidden = len(ordered_keys) - max_keys
        if hidden > 0:
            rendered.append(f"... +{hidden} more args")
        return ", ".join(rendered)

    @classmethod
    def _summarize_tool_calls(
        cls, tool_calls: list[dict[str, tp.Any]]
    ) -> str | None:
        if not tool_calls:
            return None

        lines: list[str] = []
        for tool_call in tool_calls:
            name = str(tool_call.get("name", "unknown"))
            call_id = str(tool_call.get("id", ""))
            arguments = tool_call.get("arguments")
            if not isinstance(arguments, dict):
                arguments = {}
            arg_summary = cls._summarize_tool_args(arguments)
            label = f"{name} [{call_id}]" if call_id else name
            if arg_summary:
                lines.append(f"{label}: {arg_summary}")
            else:
                lines.append(label)

        section = "\n".join(lines)
        return cls._truncate_text(section, _MAX_SECTION_CHARS)

    @classmethod
    def _summarize_tool_results(
        cls,
        tool_calls: list[dict[str, tp.Any]],
        tool_results: dict[str, dict[str, tp.Any]],
    ) -> str | None:
        if not tool_results:
            return None

        tool_names_by_id = {
            str(tool_call.get("id", "")): str(tool_call.get("name", "unknown"))
            for tool_call in tool_calls
        }

        lines: list[str] = []
        for call_id, payload in tool_results.items():
            if not isinstance(payload, dict):
                continue

            name = tool_names_by_id.get(call_id, "tool")
            prefix = f"{name} [{call_id}]"
            status = "error" if bool(payload.get("is_error")) else "ok"
            segments = [status]

            message = payload.get("message")
            if isinstance(message, str) and message:
                segments.append(
                    f"message={cls._truncate_text(message, _MAX_TOOL_ARG_CHARS)}"
                )

            output = payload.get("output")
            if output is not None:
                if isinstance(output, str):
                    output_text = output
                else:
                    output_text = json.dumps(output, ensure_ascii=False)
                segments.append(
                    "output="
                    f"{cls._truncate_text(output_text, _MAX_TOOL_OUTPUT_CHARS)}"
                )

            lines.append(f"{prefix}: {'; '.join(segments)}")

        if not lines:
            return None
        section = "\n".join(lines)
        return cls._truncate_text(section, _MAX_SECTION_CHARS)

    @classmethod
    def _build_step_message(cls, wire_step: _WireStep) -> str:
        sections: list[str] = []

        reasoning = "".join(wire_step.reasoning_parts).strip()
        if reasoning:
            sections.append(
                "THOUGHT:\n"
                + cls._truncate_text(reasoning, _MAX_REASONING_CHARS)
            )

        action_summary = cls._summarize_tool_calls(wire_step.tool_calls)
        if action_summary:
            sections.append("ACTION:\n" + action_summary)

        result_summary = cls._summarize_tool_results(
            wire_step.tool_calls, wire_step.tool_results
        )
        if result_summary:
            sections.append("RESULT:\n" + result_summary)

        assistant_text = "".join(wire_step.text_parts).strip()
        if assistant_text:
            sections.append(
                "ASSISTANT:\n"
                + cls._truncate_text(assistant_text, _MAX_ASSISTANT_CHARS)
            )

        if not sections:
            return "(empty step)"

        return "\n\n".join(sections)

    @classmethod
    def _build_event_row(
        cls, step_id: int, wire_step: _WireStep
    ) -> dict[str, tp.Any]:
        reasoning = "".join(wire_step.reasoning_parts).strip()
        assistant_text = "".join(wire_step.text_parts).strip()
        summary = cls._build_step_message(wire_step).replace("\n", " ")
        row: dict[str, tp.Any] = {
            "type": "step",
            "step_id": step_id,
            "tool_call_count": len(wire_step.tool_calls),
            "tool_result_count": len(wire_step.tool_results),
            "tool_names": [
                str(tool_call.get("name", "unknown"))
                for tool_call in wire_step.tool_calls
            ],
            "reasoning_chars": len(reasoning),
            "assistant_chars": len(assistant_text),
            "summary": cls._truncate_text(summary, _MAX_EVENT_SUMMARY_CHARS),
        }
        if wire_step.token_usage:
            row["token_usage"] = wire_step.token_usage
        return row

    def _resolve_api_key(self, provider: str) -> str:
        if self.credential is not None and self.credential.value:
            return self.credential.value

        provider_config = _PROVIDER_CONFIG.get(provider, {})
        env_keys = provider_config.get("env_keys", [])
        for key in env_keys:
            value = self.env.get(key)
            if value:
                return str(value)
        return ""

    def _build_config_json(self, provider: str, model: str) -> str:
        provider_config = _PROVIDER_CONFIG.get(provider)
        if provider_config is None:
            raise ValueError(
                f"Unsupported provider '{provider}' for kimi-cli. "
                f"Supported: {sorted(_PROVIDER_CONFIG)}"
            )

        config = {
            "default_model": "model",
            "default_yolo": True,
            "providers": {
                "slop_code": {
                    "type": provider_config["type"],
                    "base_url": self.base_url or provider_config["base_url"],
                    "api_key": self._resolve_api_key(provider),
                }
            },
            "models": {
                "model": {
                    "provider": "slop_code",
                    "model": model,
                    "max_context_size": (
                        self.max_context_size or _DEFAULT_MAX_CONTEXT_SIZE
                    ),
                }
            },
        }
        return json.dumps(config)

    def _build_command(
        self,
        config_json: str,
        prompt_request: str,
    ) -> list[str]:
        escaped_config = shlex.quote(config_json)
        escaped_prompt = shlex.quote(prompt_request)

        kimi_command_parts = [
            self.binary,
            "--config-file",
            _KIMI_CONFIG_PATH,
            "--wire",
            "--yolo",
        ]
        thinking_flag = self._resolve_thinking_flag()
        if thinking_flag is not None:
            kimi_command_parts.append(thinking_flag)
        kimi_command_parts.extend(self._resolved_extra_args())
        kimi_command = " ".join(
            shlex.quote(part) for part in kimi_command_parts
        )

        script = "\n".join(
            [
                'export PATH="$HOME/.local/bin:$PATH"',
                f"printf %s {escaped_config} > {_KIMI_CONFIG_PATH}",
                f'(printf "%s\\n" {escaped_prompt}; sleep 86400) | '
                f"{kimi_command} | (",
                "saw_result=",
                "while IFS= read -r line; do",
                '  printf "%s\\n" "$line"',
                '  case "$line" in *\'"id":"1"\'*) saw_result=1; break ;; esac',
                "done",
                # Reaching EOF without a final result means the CLI itself
                # closed stdout (crash or stall). The `kill 0` below would
                # otherwise make that indistinguishable from the harness
                # terminating a healthy run.
                'if [ -z "$saw_result" ]; then',
                f'  echo "{_NO_FINAL_RESULT_MARKER}" >&2',
                "fi",
                "kill 0 2>/dev/null",
                ")",
            ]
        )
        return ["/bin/sh", "-c", script]

    def _prepare_runtime_execution(
        self,
        task: str,
    ) -> tuple[list[str], dict[str, str]]:
        env_overrides = {key: str(value) for key, value in self.env.items()}

        if (
            self.credential is not None
            and self.credential.credential_type == CredentialType.ENV_VAR
        ):
            env_overrides[self.credential.destination_key] = (
                self.credential.value
            )

        config_json = self._build_config_json(self.provider, self.model)
        prompt_request = json.dumps(
            {
                "jsonrpc": "2.0",
                "method": "prompt",
                "id": "1",
                "params": {"user_input": task},
            }
        )
        return self._build_command(config_json, prompt_request), env_overrides

    def _resolve_thinking_flag(self) -> str | None:
        if self.max_thinking_tokens is not None:
            return (
                "--thinking"
                if self.max_thinking_tokens > 0
                else "--no-thinking"
            )

        if self.thinking in {"none", "disabled"}:
            return "--no-thinking"

        if self.thinking in {"low", "medium", "high", "xhigh"}:
            return "--thinking"

        return None

    def _resolved_extra_args(self) -> list[str]:
        resolved = list(self.extra_args)
        if self.cost_limits.step_limit > 0 and not self._has_cli_flag(
            resolved, "--max-steps-per-turn"
        ):
            resolved.extend(
                ["--max-steps-per-turn", str(self.cost_limits.step_limit)]
            )
        return resolved

    @staticmethod
    def _has_cli_flag(args: list[str], flag: str) -> bool:
        return any(arg == flag or arg.startswith(f"{flag}=") for arg in args)

    def _summarize_wire_steps(
        self, wire_steps: list[_WireStep]
    ) -> dict[str, int]:
        totals = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cached_input_tokens": 0,
            "cached_write_tokens": 0,
            "reasoning_tokens": 0,
            "total_tokens": 0,
        }

        for wire_step in wire_steps:
            token_usage = wire_step.token_usage
            if token_usage is None:
                continue
            tokens = self._token_usage_from_wire(token_usage)
            totals["input_tokens"] += tokens.input
            totals["output_tokens"] += tokens.output
            totals["cached_input_tokens"] += tokens.cache_read
            totals["cached_write_tokens"] += tokens.cache_write
            totals["reasoning_tokens"] += tokens.reasoning

        totals["total_tokens"] = (
            totals["input_tokens"] + totals["output_tokens"]
        )
        return totals

    def _sync_usage(self, totals: dict[str, int]) -> None:
        totals = totals or {}
        tokens = TokenUsage(
            input=int(totals.get("input_tokens") or 0),
            output=int(totals.get("output_tokens") or 0),
            cache_read=int(totals.get("cached_input_tokens") or 0),
            cache_write=int(totals.get("cached_write_tokens") or 0),
            reasoning=int(totals.get("reasoning_tokens") or 0),
        )
        cost = self.pricing.get_cost(tokens) if self.pricing else 0.0
        self.usage.cost += cost
        final_steps = int(totals.get("steps") or 0)
        live_steps = int(totals.get("live_steps") or 0)
        self.usage.steps += max(final_steps - live_steps, 0)
        self.usage.net_tokens += tokens
        self.usage.current_tokens = tokens

        if self.cost_limits.is_above_limits(
            self.usage,
            prior_cost=self.prior_cost,
        ):
            raise AgentError("KimiCliAgent exceeded configured usage limits")

    def reset(self) -> None:
        self._task = ""
        self._last_prompt = ""
        self._last_command_text = ""
        self._last_stdout = ""
        self._last_stderr = ""
        self._last_events = []
        self._attempts = []

    def save_artifacts(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)

        if self._last_prompt:
            (path / self.PROMPT_FILENAME).write_text(
                self._last_prompt,
                encoding="utf-8",
            )
        if self._last_command_text:
            (path / self.COMMAND_FILENAME).write_text(
                self._last_command_text,
                encoding="utf-8",
            )

        (path / self.OUTPUT_FILENAME).write_text(
            self._last_stdout,
            encoding="utf-8",
        )
        (path / self.STDOUT_FILENAME).write_text(
            self._last_stdout,
            encoding="utf-8",
        )
        (path / self.STDERR_FILENAME).write_text(
            self._last_stderr,
            encoding="utf-8",
        )

        self._save_prior_attempts(path)

        if self._last_events:
            wire_steps = group_events_into_steps(self._last_events)
            self._write_events_file(path / self.EVENTS_FILENAME, wire_steps)

            with (path / self.TRAJECTORY_FILENAME).open(
                "w", encoding="utf-8"
            ) as f:
                for index, wire_step in enumerate(wire_steps, start=1):
                    row: dict[str, tp.Any] = {
                        "step_id": index,
                        "message": self._build_step_message(wire_step),
                    }

                    if wire_step.token_usage:
                        token_usage = wire_step.token_usage
                        tokens = self._token_usage_from_wire(token_usage)
                        row["metrics"] = {
                            "prompt_tokens": tokens.input,
                            "completion_tokens": tokens.output,
                            "cached_tokens": tokens.cache_read,
                            "input_cache_creation": tokens.cache_write,
                            "reasoning_tokens": tokens.reasoning,
                            "token_usage": token_usage,
                        }

                    f.write(json.dumps(row, ensure_ascii=False))
                    f.write("\n")

    def _write_events_file(
        self, path: Path, wire_steps: list[_WireStep]
    ) -> None:
        with path.open("w", encoding="utf-8") as f:
            for index, wire_step in enumerate(wire_steps, start=1):
                f.write(
                    json.dumps(
                        self._build_event_row(index, wire_step),
                        ensure_ascii=False,
                    )
                )
                f.write("\n")

    def _save_prior_attempts(self, path: Path) -> None:
        """Write per-attempt artifacts when the CLI ran more than once.

        The canonical ``stdout.log``/``stderr.log``/``events.jsonl`` files hold
        the final attempt only; without these copies the stderr of a crashed
        attempt (the evidence for why a retry happened) would be lost.
        """
        if len(self._attempts) < 2:
            return

        for index, attempt in enumerate(self._attempts):
            suffix = f".attempt{index}"
            (path / f"{self.PROMPT_FILENAME}{suffix}").write_text(
                attempt.prompt, encoding="utf-8"
            )
            (path / f"{self.COMMAND_FILENAME}{suffix}").write_text(
                attempt.command_text, encoding="utf-8"
            )
            (path / f"{self.STDOUT_FILENAME}{suffix}").write_text(
                attempt.stdout, encoding="utf-8"
            )
            (path / f"{self.STDERR_FILENAME}{suffix}").write_text(
                attempt.stderr, encoding="utf-8"
            )
            self._write_events_file(
                path / f"{self.EVENTS_FILENAME}{suffix}",
                group_events_into_steps(attempt.events),
            )

    def cleanup(self) -> None:
        if self._runtime is not None:
            self._runtime.cleanup()
            self._runtime = None
        self._session = None


register_agent("kimi_cli", KimiCliAgent)
