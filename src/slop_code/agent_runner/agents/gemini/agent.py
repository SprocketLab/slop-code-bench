"""Gemini CLI agent implementation."""

from __future__ import annotations

import functools
import json
import shlex
import shutil
import tempfile
import typing as tp
from pathlib import Path

from jinja2 import Template
from pydantic import Field

from slop_code.agent_runner.agent import Agent, AgentConfigBase
from slop_code.agent_runner.agents.cli_utils import (
    AgentCommandResult,
    stream_cli_command,
)
from slop_code.agent_runner.agents.utils import HOME_PATH
from slop_code.agent_runner.credentials import (
    CredentialType,
    ProviderCredential,
)
from slop_code.agent_runner.models import AgentCostLimits, AgentError
from slop_code.agent_runner.registry import register_agent
from slop_code.common.llms import (
    APIPricing,
    ModelDefinition,
    ThinkingPreset,
    TokenUsage,
)
from slop_code.execution import (
    DockerEnvironmentSpec,
    EnvironmentSpec,
    Session,
    StreamingRuntime,
)
from slop_code.logging import get_logger

log = get_logger(__name__)


class GeminiConfig(AgentConfigBase):
    """Configuration for ``GeminiAgent`` instances.

    Model is provided via ModelDefinition at agent creation time.
    """

    type: tp.Literal["gemini"] = "gemini"
    version: str
    binary: str = "gemini"
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


class GeminiAgent(Agent):
    """Agent implementation built on top of the Gemini CLI executor."""

    PROMPT_FILENAME = "prompt.txt"
    STDOUT_FILENAME = "stdout.jsonl"
    STDERR_FILENAME = "stderr.log"
    MESSAGES_FILENAME = "messages.jsonl"

    def __init__(
        self,
        problem_name: str,
        verbose: bool,
        image: str,
        # From base config
        cost_limits: AgentCostLimits,
        pricing: APIPricing | None,
        credential: ProviderCredential | None,
        # Gemini specific
        binary: str,
        model: str | None,
        timeout: int | None,
        extra_args: list[str],
        env: dict[str, str],
    ) -> None:
        super().__init__(
            agent_name="gemini",
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
        self.extra_args = extra_args
        self.env = env

        self._image = image
        self._session: Session | None = None
        self._environment: EnvironmentSpec | None = None
        self._runtime: StreamingRuntime | None = None

        # Get auth file from credential (file-based auth)
        # Also check for settings.json in the same directory
        self._auth_file: Path | None = None
        self._settings_file: Path | None = None
        if (
            self.credential is not None
            and self.credential.credential_type == CredentialType.FILE
        ):
            candidate = Path(self.credential.source)
            self._auth_file = candidate if candidate.exists() else None

            # Look for settings.json in the same directory as auth file
            if self._auth_file is not None:
                settings_candidate = self._auth_file.parent / "settings.json"
                if settings_candidate.exists():
                    self._settings_file = settings_candidate

        self._last_prompt: str = ""
        self._last_command: AgentCommandResult | None = None
        self._payloads: list[dict] = []
        self._tmp_dir: tempfile.TemporaryDirectory | None = None

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
        """Create a GeminiAgent from a GeminiConfig."""
        if not isinstance(config, GeminiConfig):
            raise TypeError(
                f"Expected GeminiConfig, got {type(config).__name__}"
            )
        if image is None:
            raise ValueError("GeminiAgent requires an image")

        # Get model slug for API calls
        model_slug = model.get_model_slug(credential.provider)

        # thinking_preset and thinking_max_tokens not currently used by Gemini
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
            model=model_slug,
            timeout=config.timeout,
            extra_args=config.extra_args,
            env=config.env,
        )

    @staticmethod
    def parse_line(
        line: str,
        pricing: APIPricing | None = None,
    ) -> tuple[float | None, TokenUsage | None, dict | None]:
        """Parse a single JSONL line from Gemini output.

        Returns (cost, tokens, payload) matching the CLI streaming pattern.

        Gemini outputs several event types:
        - init: Session initialization
        - message: User/assistant messages
        - tool_use: Tool invocations
        - tool_result: Tool execution results
        - result: Final result with stats (contains token usage)
        """
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            return None, None, None

        # Only "result" type has usage stats
        if payload.get("type") != "result":
            return None, None, payload

        stats = payload.get("stats") or {}
        input_tokens = stats.get("input_tokens", 0)
        output_tokens = stats.get("output_tokens", 0)

        tokens = TokenUsage(
            input=input_tokens,
            output=output_tokens,
            cache_read=0,
            cache_write=0,
            reasoning=0,
        )

        cost = pricing.get_cost(tokens) if pricing else 0.0
        return (cost, tokens, payload)

    @property
    def session(self) -> Session:
        if self._session is None:
            raise AgentError("GeminiAgent has not been set up with a session")
        return self._session

    @property
    def spec(self) -> EnvironmentSpec:
        if self._environment is None:
            raise AgentError("GeminiAgent has not been set up with a session")
        return self._environment

    @property
    def runtime(self) -> StreamingRuntime:
        if self._runtime is None:
            raise AgentError("GeminiAgent has not been set up with a runtime")
        return self._runtime

    def _get_volumes(self) -> dict[str, dict[str, str]]:
        """Get volume mounts for the Gemini agent.

        Creates a temporary directory for settings.json since Gemini modifies
        it during runtime, while keeping oauth_creds.json read-only.
        """
        mounts: dict[str, dict[str, str]] = {}
        gemini_dir = Path(HOME_PATH) / ".gemini"

        if self._tmp_dir is None:
            self._tmp_dir = tempfile.TemporaryDirectory()

        tmp_auth_path = Path(self._tmp_dir.name) / "gemini"

        # Mount auth file as read-only (Gemini doesn't modify this)
        if self._auth_file is not None:
            shutil.copytree(Path(self._auth_file).parent, tmp_auth_path)
            mounts[str(tmp_auth_path.absolute())] = {
                "bind": str(gemini_dir),
                "mode": "rw",
            }

        return mounts

    def setup(self, session: Session) -> None:
        """Set up the agent with a session, mounting auth and settings files."""
        self._session = session
        self._environment = session.spec

        # Get volume mounts (creates temp dir for settings if needed)
        mounts = self._get_volumes()
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
        """Execute a task through the Gemini CLI."""
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
        log.info("agent.gemini.start", **log_kwargs)

        command_result = self._run_invocation(task)
        self._last_command = command_result

        self._sync_usage(command_result.usage_totals)

        runtime_result = command_result.result
        if runtime_result is None:
            log.error(
                "Gemini process failed to start",
                error_message=command_result.error_message,
            )
            log.error("STDOUT", stdout=command_result.stdout)
            log.error("STDERR", stderr=command_result.stderr)
            raise AgentError("Gemini process failed to start")

        if runtime_result.timed_out:
            message = (
                f"Gemini process timed out after {self.timeout}s."
                if self.timeout is not None
                else "Gemini process timed out."
            )
            log.error("agent.gemini.timeout", timeout=self.timeout)
            raise AgentError(message)

        if runtime_result.exit_code != 0:
            message = (
                f"Gemini process failed with exit code "
                f"{runtime_result.exit_code}"
            )
            if runtime_result.stderr:
                message = (
                    f"{message}\n--- Stderr ---\n"
                    f"{runtime_result.stderr.strip()}"
                )
            log.error(
                "agent.gemini.exit",
                exit_code=runtime_result.exit_code,
            )
            raise AgentError(message)

    def _run_invocation(self, task: str) -> AgentCommandResult:
        """Execute a Gemini CLI invocation and return results."""
        command, env_overrides = self._prepare_runtime_execution(task)

        if self._session is None:
            raise AgentError("GeminiAgent has not been set up with a session")
        if isinstance(command, list):
            command = " ".join(command)

        # Use partial to bind pricing to parse_line
        parser = functools.partial(self.parse_line, pricing=self.pricing)

        total_cost = 0.0
        total_tokens = TokenUsage()
        step_count = 0
        runtime_result = None
        pending_message = False  # Track if we have a message before tool_use

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
            payload_str = str(payload)[:200] if payload else None
            self.log.debug("Received item", payload=payload_str, verbose=True)

            if cost is not None:
                total_cost += cost
            if tokens is not None:
                total_tokens = total_tokens + tokens

            # Collect raw payload for artifact saving
            if payload is not None:
                self._payloads.append(payload)

            # Count steps: tool_use + the last assistant message before each tool_use
            if payload is not None:
                event_type = payload.get("type")
                if (
                    event_type == "message"
                    and payload.get("role") == "assistant"
                ):
                    # Mark that we have a pending assistant message (might be streamed)
                    pending_message = True
                elif event_type == "tool_use":
                    # Count the preceding assistant message (if any) and the tool_use
                    if pending_message:
                        step_count += 1
                        self.usage.steps += 1
                        pending_message = False
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
                "total_tokens": total_tokens.input + total_tokens.output,
                "steps": step_count,
            },
            stdout=stdout,
            stderr=stderr,
        )

    def _sync_usage(self, totals: dict[str, int]) -> None:
        """Synchronize usage tracking from execution totals."""
        totals = totals or {}
        input_tokens = int(totals.get("input_tokens") or 0)
        output_tokens = int(totals.get("output_tokens") or 0)

        tokens = TokenUsage(
            input=input_tokens,
            output=output_tokens,
        )

        cost = self.pricing.get_cost(tokens) if self.pricing else 0.0

        # Sync token usage directly (steps already tracked incrementally)
        self.usage.cost = cost
        self.usage.net_tokens = tokens
        self.usage.current_tokens = tokens

        if self.cost_limits.is_above_limits(
            self.usage,
            prior_cost=self.prior_cost,
        ):
            raise AgentError("GeminiAgent exceeded configured usage limits")

    def _prepare_runtime_execution(
        self,
        task: str,
    ) -> tuple[list[str], dict[str, str]]:
        """Prepare command and environment overrides for runtime execution."""
        env_overrides = {key: str(value) for key, value in self.env.items()}

        # Handle env_var type credentials
        if (
            self.credential is not None
            and self.credential.credential_type == CredentialType.ENV_VAR
        ):
            env_overrides[self.credential.destination_key] = (
                self.credential.value
            )

        command = self._build_command(task)
        return command, env_overrides

    def _build_command(self, prompt: str) -> list[str]:
        """Build CLI command arguments for Gemini."""
        command = [
            self.binary,
            "-p",
            shlex.quote(prompt),
            "-y",  # YOLO mode - auto-approve tool calls
            "--output-format",
            "stream-json",
        ]

        if self.model:
            command.extend(["-m", self.model])

        command.extend(self.extra_args)
        return command

    @classmethod
    def _write_artifacts(
        cls,
        output_dir: Path,
        stdout_text: str,
        stderr_text: str,
    ) -> None:
        """Write stdout and stderr to artifact files."""
        (output_dir / cls.STDOUT_FILENAME).write_text(stdout_text)
        if stderr_text:
            (output_dir / cls.STDERR_FILENAME).write_text(stderr_text)

    def reset(self) -> None:
        """Reset agent state between runs."""
        self._last_prompt = ""
        self._last_command = None
        self._payloads = []

    def save_artifacts(self, path: Path) -> None:
        """Save agent execution artifacts to the specified directory."""
        path.mkdir(parents=True, exist_ok=True)

        if self._last_prompt:
            (path / self.PROMPT_FILENAME).write_text(self._last_prompt)

        stdout_text = ""
        stderr_text = ""
        if self._last_command is not None:
            stdout_text = self._last_command.stdout or ""
            stderr_text = self._last_command.stderr or ""

        self._write_artifacts(path, stdout_text, stderr_text)

        # Write collected payloads
        if self._payloads:
            with (path / self.MESSAGES_FILENAME).open("w") as f:
                for payload in self._payloads:
                    f.write(json.dumps(payload) + "\n")

    def cleanup(self) -> None:
        """Clean up resources held by the Gemini agent."""
        self.log.debug("agent.gemini.cleanup")

        if self._runtime is not None:
            self._runtime.cleanup()
            self._runtime = None

        # Clean up temporary directory
        if self._tmp_dir is not None:
            self._tmp_dir.cleanup()
            self._tmp_dir = None

        self._session = None


# Register this agent type with the agent registry
register_agent("gemini", GeminiAgent)
