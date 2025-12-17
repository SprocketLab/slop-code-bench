"Codex agent implementation."

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
from slop_code.execution import SubmissionRuntime
from slop_code.logging import get_logger

log = get_logger(__name__)


class CodexConfig(AgentConfigBase):
    """Configuration for ``CodexAgent`` instances."""

    type: tp.Literal["codex"] = "codex"
    version: str
    binary: str = "codex"
    docker_template: Path = Path(__file__).parent / "docker.j2"
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


class CodexAgent(Agent):
    """Agent implementation built on top of the Codex CLI executor."""

    PROMPT_FILENAME = "prompt.txt"
    STDOUT_FILENAME = "stdout.jsonl"
    STDERR_FILENAME = "stderr.log"

    def __init__(
        self,
        problem_name: str,
        verbose: bool,
        image: str,
        # From base config
        cost_limits: AgentCostLimits,
        pricing: APIPricing | None,
        credential: ProviderCredential | None,
        # Codex specific
        binary: str,
        model: str,
        timeout: int | None,
        thinking: ThinkingPreset | None,
        max_thinking_tokens: int | None,
        extra_args: list[str],
        env: dict[str, str],
    ) -> None:
        super().__init__(
            agent_name="codex",
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
        self.thinking = thinking
        self.max_thinking_tokens = max_thinking_tokens
        self.extra_args = extra_args
        self.env = env

        self._image = image
        self._session: Session | None = None

        self._environment: EnvironmentSpec | None = None
        self._runtime: SubmissionRuntime | None = None

        # Get auth file from credential if it's a file credential
        self._auth_file: Path | None = None
        if (
            self.credential is not None
            and self.credential.credential_type == CredentialType.FILE
        ):
            candidate = Path(self.credential.source)
            self._auth_file = candidate if candidate.exists() else None

        self._last_prompt: str = ""
        self._last_command: AgentCommandResult | None = None

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
        """Create a CodexAgent from a CodexConfig."""
        if not isinstance(config, CodexConfig):
            raise TypeError(
                f"Expected CodexConfig, got {type(config).__name__}"
            )
        if image is None:
            raise ValueError("CodexAgent requires an image")

        # Get model slug for API calls
        model_slug = model.get_model_slug(credential.provider)

        # Resolve thinking: CLI/config override > model default
        thinking: ThinkingPreset | None = thinking_preset
        max_thinking_tokens: int | None = thinking_max_tokens
        if thinking is None and max_thinking_tokens is None:
            thinking, max_thinking_tokens = model.get_thinking_config("codex")

        return cls(
            problem_name=problem_name,
            verbose=verbose,
            image=image,
            cost_limits=config.cost_limits,
            pricing=model.pricing,
            credential=credential,
            binary=config.binary,
            model=model_slug,
            timeout=config.timeout,
            thinking=thinking,
            max_thinking_tokens=max_thinking_tokens,
            extra_args=config.extra_args,
            env=config.env,
        )

    @staticmethod
    def parse_line(
        line: str,
        pricing: APIPricing | None = None,
    ) -> tuple[float | None, TokenUsage | None, dict | None]:
        """Parse a single JSONL line from Codex output.

        Returns (cost, tokens, payload) matching Claude's pattern.
        """
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            return None, None, None

        # Only turn.completed has usage data
        if payload.get("type") != "turn.completed":
            return None, None, payload

        usage = payload.get("usage") or {}
        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)
        cached_tokens = usage.get("cached_input_tokens", 0)

        tokens = TokenUsage(
            input=input_tokens,
            output=output_tokens,
            cache_read=cached_tokens,
            cache_write=0,
            reasoning=0,
        )

        cost = pricing.get_cost(tokens) if pricing else 0.0
        return (cost, tokens, payload)

    @property
    def session(self) -> Session:
        if self._session is None:
            raise AgentError("CodexAgent has not been set up with a session")
        return self._session

    @property
    def spec(self) -> EnvironmentSpec:
        if self._environment is None:
            raise AgentError("CodexAgent has not been set up with a session")
        return self._environment

    @property
    def runtime(self) -> SubmissionRuntime:
        if self._runtime is None:
            raise AgentError("CodexAgent has not been set up with a runtime")
        return self._runtime

    def setup(
        self,
        session: Session,
    ) -> None:
        self._session = session
        self._environment = session.spec
        mounts: dict[str, dict[str, str]] = {}
        if self._auth_file is not None:
            mounts[str(self._auth_file)] = {
                "bind": str(Path(HOME_PATH) / ".codex" / "auth.json"),
                "mode": "ro",
            }
        self._runtime = session.spawn(
            mounts=mounts,
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

        log_kwargs: dict[str, tp.Any] = {
            "workspace": str(self.session.working_dir),
            "prompt_chars": len(task),
            "environment": self.session.spec.type,
            "extra_args": self.extra_args,
        }
        if isinstance(self.session.spec, DockerEnvironmentSpec):
            log_kwargs["image"] = self.session.spec.docker.image
        self.log.info("agent.codex.start", **log_kwargs)

        command_result = self._run_invocation(task)
        self._last_command = command_result

        self._sync_usage(command_result.usage_totals)

        runtime_result = command_result.result
        if runtime_result is None:
            self.log.error(
                "Codex process failed to start",
                error_message=command_result.error_message,
            )
            self.log.error("STDOUT", stdout=command_result.stdout)
            self.log.error("STDERR", stderr=command_result.stderr)
            raise AgentError("Codex process failed to start")
        if runtime_result.timed_out:
            message = (
                f"Codex process timed out after {self.timeout}s."
                if self.timeout is not None
                else "Codex process timed out."
            )
            self.log.error("agent.codex.timeout", timeout=self.timeout)
            raise AgentError(message)

        if runtime_result.exit_code != 0:
            message = f"Codex process failed with exit code {runtime_result.exit_code}"
            if runtime_result.stderr:
                message = f"{message}\n--- Stderr ---\n{runtime_result.stderr.strip()}"
            self.log.error(
                "agent.codex.exit",
                exit_code=runtime_result.exit_code,
            )
            raise AgentError(message)

    def _run_invocation(
        self,
        task: str,
    ) -> AgentCommandResult:
        """Execute a Codex CLI invocation and return results."""
        command, env_overrides = self._prepare_runtime_execution(task)

        if self._session is None:
            raise AgentError("CodexAgent has not been set up with a session")
        if isinstance(command, list):
            command = " ".join(command)

        # Use partial to bind pricing to parse_line
        parser = functools.partial(self.parse_line, pricing=self.pricing)

        total_cost = 0.0
        total_tokens = TokenUsage()
        step_count = 0
        runtime_result = None

        for item in stream_cli_command(
            runtime=self.runtime,
            command=command,
            parser=parser,
            env=env_overrides,
            timeout=(float(self.timeout) if self.timeout is not None else None),
        ):
            # Final item is RuntimeResult
            if not isinstance(item, tuple):
                runtime_result = item
                break

            cost, tokens, payload = item
            self.log.debug("Received item", item=item, verbose=True)
            if cost is not None:
                total_cost += cost
            if tokens is not None:
                total_tokens = total_tokens + tokens

            # Count steps from turn.started and item.completed events
            if payload is not None:
                event_type = payload.get("type")
                if event_type in ("turn.started", "item.completed"):
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
        tokens = TokenUsage(
            input=input_tokens,
            output=output_tokens,
            cache_read=cache_read_tokens,
        )
        cost = self.pricing.get_cost(tokens) if self.pricing else 0.0
        # Update tokens and cost without incrementing steps (already done during streaming)
        self.usage.cost += cost
        self.usage.net_tokens += tokens
        self.usage.current_tokens = tokens

        if self.cost_limits.is_above_limits(
            self.usage,
            prior_cost=self.prior_cost,
        ):
            raise AgentError("CodexAgent exceeded configured usage limits")

    def _prepare_runtime_execution(
        self,
        task: str,
    ) -> tuple[list[str], dict[str, str]]:
        """Prepare command and environment overrides for runtime execution."""
        env_overrides = {key: str(value) for key, value in self.env.items()}

        # Set credential in environment if it's an env var credential
        if (
            self.credential is not None
            and self.credential.credential_type == CredentialType.ENV_VAR
        ):
            env_overrides[self.credential.destination_key] = (
                self.credential.value
            )
        command = self._build_command(task)

        return command, env_overrides

    def _build_command(
        self,
        prompt: str,
    ) -> list[str]:
        command = [
            self.binary,
            "exec",
            shlex.quote(prompt),
            "--skip-git-repo-check",
            "--json",
            "--dangerously-bypass-approvals-and-sandbox",
        ]
        if self.model:
            command.extend(["--model", self.model])

        # Handle thinking configuration
        if self.thinking in {"disabled", "none"}:
            # Disabled: omit model_reasoning_effort, set output tokens to 0
            command.extend(["--config", "model_max_output_tokens=0"])
        elif self.thinking:
            # Preset (low/medium/high): set reasoning effort
            command.extend(
                [
                    "--config",
                    f'model_reasoning_effort="{self.thinking}"',
                ]
            )
        elif self.max_thinking_tokens is not None:
            # Explicit token limit
            command.extend(
                [
                    "--config",
                    f"model_max_output_tokens={self.max_thinking_tokens}",
                ]
            )
        command.extend(self.extra_args)
        return command

    @classmethod
    def _write_artifacts(
        cls,
        output_dir: Path,
        stdout_text: str,
        stderr_text: str,
    ) -> None:
        (output_dir / cls.STDOUT_FILENAME).write_text(stdout_text)
        (output_dir / cls.STDERR_FILENAME).write_text(stderr_text)

    def reset(self) -> None:
        self._last_prompt = ""
        self._last_command = None

    def save_artifacts(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        if self._last_prompt:
            (path / self.PROMPT_FILENAME).write_text(self._last_prompt)

        stdout_text = ""
        stderr_text = ""
        if self._last_command is not None:
            stdout_text = self._last_command.stdout or ""
            stderr_text = self._last_command.stderr or ""

        self._write_artifacts(path, stdout_text, stderr_text)

    def cleanup(self) -> None:
        """Clean up resources held by the Codex agent."""
        self._session = None
        self.log.debug("agent.codex.cleanup")


# Register this agent type with the agent registry
register_agent("codex", CodexAgent)
