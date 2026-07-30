"""Cursor CLI agent implementation."""

from __future__ import annotations

import functools
import json
import shlex
import typing as tp
from pathlib import Path

from jinja2 import Template
from pydantic import Field

from slop_code.agent_runner.agent import Agent
from slop_code.agent_runner.agent import AgentConfigBase
from slop_code.agent_runner.agents.cli_utils import AgentCommandResult
from slop_code.agent_runner.agents.cli_utils import stream_cli_command
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


class CursorCliConfig(AgentConfigBase):
    """Configuration for ``CursorCliAgent`` instances."""

    type: tp.Literal["cursor_cli"] = "cursor_cli"
    version: str
    binary: str = "cursor-agent"
    docker_template: Path = Path(__file__).parent / "docker.j2"
    mode: tp.Literal["plan", "ask"] | None = None
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

    def get_docker_file(self, base_image: str) -> str | None:
        """Render the Docker template with version."""
        if self.docker_template is None:
            return None
        template = self.docker_template.read_text()
        return Template(template).render(
            base_image=base_image, version=self.version
        )


class CursorCliAgent(Agent):
    """Agent implementation built on top of the Cursor CLI executor."""

    PROMPT_FILENAME = "prompt.txt"
    COMMAND_FILENAME = "command.txt"
    STDOUT_FILENAME = "stdout.jsonl"
    STDERR_FILENAME = "stderr.log"

    def __init__(
        self,
        problem_name: str,
        verbose: bool,  # noqa: FBT001
        image: str,
        # From base config
        cost_limits: AgentCostLimits,
        pricing: APIPricing | None,
        credential: ProviderCredential | None,
        # Cursor specific
        binary: str,
        model: str | None,
        mode: tp.Literal["plan", "ask"] | None,
        timeout: int | None,
        extra_args: list[str],
        env: dict[str, str],
    ) -> None:
        super().__init__(
            agent_name="cursor_cli",
            problem_name=problem_name,
            cost_limits=cost_limits,
            pricing=pricing,
            verbose=verbose,
        )

        self.credential = credential
        self.binary = binary
        self.model = model
        self.mode = mode
        self.timeout = timeout
        self.extra_args = extra_args
        self.env = env

        self._image = image
        self._session: Session | None = None
        self._environment: EnvironmentSpec | None = None
        self._runtime: StreamingRuntime | None = None

        self._last_prompt: str = ""
        self._last_command: AgentCommandResult | None = None
        self._last_command_text: str = ""
        self._last_command_stdout: str = ""
        self._last_command_stderr: str = ""

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
        """Create a CursorCliAgent from a CursorCliConfig."""
        if not isinstance(config, CursorCliConfig):
            raise TypeError(
                f"Expected CursorCliConfig, got {type(config).__name__}"
            )
        if image is None:
            raise ValueError("CursorCliAgent requires an image")

        model_slug = model.get_model_slug(credential.provider)
        agent_settings = model.get_agent_settings("cursor_cli") or {}
        configured_model = agent_settings.get("model_name")
        if not isinstance(configured_model, str) or not configured_model:
            configured_model = model_slug
        cursor_model = cls._cursor_model_from_slug(configured_model)

        env = dict(config.env)
        env_overrides = agent_settings.get("env_overrides")
        if isinstance(env_overrides, dict):
            env = {**{k: str(v) for k, v in env_overrides.items()}, **env}

        # Cursor currently does not support thinking options via this wrapper.
        _ = thinking_preset
        _ = thinking_max_tokens

        return cls(
            problem_name=problem_name,
            verbose=verbose,
            image=image,
            cost_limits=config.cost_limits,
            pricing=model.pricing,
            credential=credential,
            binary=config.binary,
            model=cursor_model,
            mode=config.mode,
            timeout=config.timeout,
            extra_args=config.extra_args,
            env=env,
        )

    @staticmethod
    def _cursor_model_from_slug(slug: str) -> str:
        """Normalize provider-prefixed slugs to Cursor's expected model value."""
        if "/" in slug:
            return slug.split("/")[-1]
        return slug

    @staticmethod
    def parse_line(
        line: str,
        pricing: APIPricing | None = None,
    ) -> tuple[float | None, TokenUsage | None, dict]:
        """Parse a single JSONL line from Cursor stream-json output."""
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            return None, None, {}

        if payload.get("type") != "result":
            return None, None, payload

        usage = payload.get("usage") or {}
        tokens = TokenUsage(
            input=int(usage.get("inputTokens") or 0),
            output=int(usage.get("outputTokens") or 0),
            cache_read=int(usage.get("cacheReadTokens") or 0),
            cache_write=int(usage.get("cacheWriteTokens") or 0),
            reasoning=0,
        )
        cost = pricing.get_cost(tokens) if pricing else 0.0
        return cost, tokens, payload

    @property
    def session(self) -> Session:
        if self._session is None:
            raise AgentError(
                "CursorCliAgent has not been set up with a session"
            )
        return self._session

    @property
    def spec(self) -> EnvironmentSpec:
        if self._environment is None:
            raise AgentError(
                "CursorCliAgent has not been set up with a session"
            )
        return self._environment

    @property
    def runtime(self) -> StreamingRuntime:
        if self._runtime is None:
            raise AgentError(
                "CursorCliAgent has not been set up with a runtime"
            )
        return self._runtime

    def setup(self, session: Session) -> None:
        self._session = session
        self._environment = session.spec
        self._runtime = session.spawn(
            mounts={},
            env_vars={
                "HOME": HOME_PATH,
            },
            image=self._image,
            user="agent",
            disable_setup=True,
        )

    def run(self, task: str) -> None:
        self._last_prompt = task
        self._last_command = None
        self._last_command_text = ""
        self._last_command_stdout = ""
        self._last_command_stderr = ""

        log_kwargs: dict[str, tp.Any] = {
            "workspace": str(self.session.working_dir),
            "prompt_chars": len(task),
            "environment": self.session.spec.type,
            "extra_args": self.extra_args,
            "mode": self.mode,
        }
        if isinstance(self.session.spec, DockerEnvironmentSpec):
            log_kwargs["image"] = self.session.spec.docker.image
        self.log.info("agent.cursor_cli.start", **log_kwargs)

        command_result = self._run_invocation(task)
        self._last_command = command_result
        self._last_command_stdout = command_result.stdout or ""
        self._last_command_stderr = command_result.stderr or ""

        self._sync_usage(command_result.usage_totals)

        runtime_result = command_result.result
        if runtime_result is None:
            message = "Cursor process failed to start"
            self.log.error(
                "agent.cursor_cli.start_failed",
                error_message=message,
                agent_message=command_result.error_message,
            )
            raise AgentError(message)

        if runtime_result.timed_out:
            message = (
                f"Cursor process timed out after {self.timeout}s."
                if self.timeout is not None
                else "Cursor process timed out."
            )
            self.log.error(
                "agent.cursor_cli.timeout",
                error_message=message,
                timeout=self.timeout,
            )
            raise AgentError(message)

        if runtime_result.exit_code != 0:
            message = f"Cursor process failed with exit code {runtime_result.exit_code}"
            if runtime_result.stderr:
                message = f"{message}\n--- Stderr ---\n{runtime_result.stderr.strip()}"
            self.log.error(
                "agent.cursor_cli.exit",
                error_message=message,
                exit_code=runtime_result.exit_code,
            )
            raise AgentError(message)

    def _run_invocation(self, task: str) -> AgentCommandResult:
        """Execute a Cursor CLI invocation and return results."""
        command, env_overrides = self._prepare_runtime_execution(task)
        if self._session is None:
            raise AgentError(
                "CursorCliAgent has not been set up with a session"
            )
        command_text = " ".join(command)
        self._last_command_text = command_text
        parser = functools.partial(self.parse_line, pricing=self.pricing)

        total_tokens = TokenUsage()
        step_count = 0
        runtime_result = None

        for item in stream_cli_command(
            runtime=self.runtime,
            command=command_text,
            parser=parser,
            env=env_overrides,
            timeout=(float(self.timeout) if self.timeout is not None else None),
            parse_stderr=True,
        ):
            if not isinstance(item, tuple):
                runtime_result = item
                break

            _, tokens, payload = item
            if tokens is not None:
                total_tokens = total_tokens + tokens

            if payload is not None:
                event_type = payload.get("type")
                if event_type == "assistant" or (
                    event_type == "tool_call"
                    and payload.get("subtype") == "completed"
                ):
                    step_count += 1
                    self.usage.steps += 1

        stdout = runtime_result.stdout if runtime_result else ""
        stderr = runtime_result.stderr if runtime_result else ""

        return AgentCommandResult(
            result=runtime_result,
            steps=[],
            usage_totals={
                "input_tokens": total_tokens.input,
                "output_tokens": total_tokens.output,
                "cached_input_tokens": total_tokens.cache_read,
                "cached_write_tokens": total_tokens.cache_write,
                "total_tokens": total_tokens.input + total_tokens.output,
                "steps": step_count,
            },
            stdout=stdout,
            stderr=stderr,
        )

    def _sync_usage(self, totals: dict[str, int]) -> None:
        totals = totals or {}
        input_tokens = int(totals.get("input_tokens") or 0)
        output_tokens = int(totals.get("output_tokens") or 0)
        cache_read_tokens = int(totals.get("cached_input_tokens") or 0)
        cache_write_tokens = int(totals.get("cached_write_tokens") or 0)
        tokens = TokenUsage(
            input=input_tokens,
            output=output_tokens,
            cache_read=cache_read_tokens,
            cache_write=cache_write_tokens,
        )
        cost = self.pricing.get_cost(tokens) if self.pricing else 0.0
        self.usage.cost += cost
        self.usage.net_tokens += tokens
        self.usage.current_tokens = tokens

        if self.cost_limits.is_above_limits(
            self.usage,
            prior_cost=self.prior_cost,
        ):
            raise AgentError("CursorCliAgent exceeded configured usage limits")

    def _prepare_runtime_execution(
        self, task: str
    ) -> tuple[list[str], dict[str, str]]:
        env_overrides = {key: str(value) for key, value in self.env.items()}

        if (
            self.credential is not None
            and self.credential.credential_type == CredentialType.ENV_VAR
        ):
            env_overrides[self.credential.destination_key] = (
                self.credential.value
            )

        if "CURSOR_API_KEY" not in env_overrides:
            raise AgentError(
                "CursorCliAgent requires CURSOR_API_KEY in the runtime environment."
            )

        return self._build_command(task), env_overrides

    def _build_command(self, prompt: str) -> list[str]:
        command = [
            'export PATH="$HOME/.local/bin:$PATH";',
            self.binary,
            "--yolo",
            "--print",
            "--output-format=stream-json",
        ]

        if self.model:
            command.append(f"--model={self.model}")
        if self.mode:
            command.append(f"--mode={self.mode}")

        command.extend(self.extra_args)
        command.extend(["--", shlex.quote(prompt)])
        return command

    @classmethod
    def _write_artifacts(
        cls,
        output_dir: Path,
        stdout_text: str,
        stderr_text: str,
    ) -> None:
        (output_dir / cls.STDOUT_FILENAME).write_text(
            stdout_text, encoding="utf-8"
        )
        (output_dir / cls.STDERR_FILENAME).write_text(
            stderr_text, encoding="utf-8"
        )

    def reset(self) -> None:
        self._last_prompt = ""
        self._last_command = None
        self._last_command_text = ""
        self._last_command_stdout = ""
        self._last_command_stderr = ""

    def save_artifacts(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)

        if self._last_prompt:
            (path / self.PROMPT_FILENAME).write_text(
                self._last_prompt, encoding="utf-8"
            )
        if self._last_command_text:
            (path / self.COMMAND_FILENAME).write_text(
                self._last_command_text, encoding="utf-8"
            )

        self._write_artifacts(
            output_dir=path,
            stdout_text=self._last_command_stdout,
            stderr_text=self._last_command_stderr,
        )

    def cleanup(self) -> None:
        if self._runtime is not None:
            self._runtime.cleanup()
            self._runtime = None

        self._session = None


register_agent("cursor_cli", CursorCliAgent)
