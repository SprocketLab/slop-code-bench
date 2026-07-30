"""OpenCode agent implementation."""

from __future__ import annotations

import contextlib
import json
import shlex
import tempfile
from pathlib import Path
from typing import Any, Literal

from pydantic import Field
from pydantic import JsonValue

from slop_code.agent_runner.agent import RETRY_PROMPT
from slop_code.agent_runner.agent import Agent
from slop_code.agent_runner.agent import AgentConfigBase
from slop_code.agent_runner.agents.utils import HOME_PATH
from slop_code.agent_runner.credentials import CredentialType
from slop_code.agent_runner.credentials import ProviderCredential
from slop_code.agent_runner.models import AgentCostLimits
from slop_code.agent_runner.models import AgentError
from slop_code.agent_runner.registry import register_agent
from slop_code.common import deep_merge as _deep_merge
from slop_code.common.llms import APIPricing
from slop_code.common.llms import ModelDefinition
from slop_code.common.llms import ThinkingPreset
from slop_code.common.llms import TokenUsage
from slop_code.execution import Session
from slop_code.execution import StreamingRuntime

STEP_FINISH_TYPE = "step_finish"
THINKING_TO_VARIANT: dict[ThinkingPreset, str] = {
    "low": "low",
    "medium": "medium",
    "high": "high",
    "xhigh": "max",
}


class OpenCodeAgentConfig(AgentConfigBase):
    """Configuration for ``OpenCodeAgent`` instances."""

    model_config = {"extra": "allow"}
    type: Literal["opencode"] = "opencode"
    config: dict[str, JsonValue] = Field(default_factory=dict)
    docker_template: Path = Path(__file__).parent / "docker.j2"
    version: str
    env: dict[str, str] = Field(
        default_factory=dict,
        description="Environment variable overrides applied to the invocation.",
    )


class OpenCodeAgent(Agent):
    def __init__(  # noqa: FBT001
        self,
        problem_name: str,
        verbose: bool,  # noqa: FBT001
        # From base config
        cost_limits: AgentCostLimits,
        pricing: APIPricing | None,
        credential: ProviderCredential | None,
        # OpenCode specific
        model_id: str,
        provider: str,
        opencode_config: dict[str, Any],
        env: dict[str, str],
        thinking: ThinkingPreset | None,
        image: str = "sc-opencode:latest",
    ) -> None:
        super().__init__(
            "OpenCode", problem_name, cost_limits, pricing, verbose
        )

        # Store all config values as instance attributes
        self.credential = credential
        self.model_id = model_id
        self.provider = provider
        self.open_code_config = opencode_config
        self.env = env
        self.image = image

        self.messages: list[dict[str, Any]] = []
        self.continue_on_run = True
        self._runtime: StreamingRuntime | None = None
        self._tmp_dir: tempfile.TemporaryDirectory | None = None
        self._session: Session | None = None
        self._storage_dir: Path | None = None
        self._stderr: str = ""
        self._stdout: str = ""
        self.thinking: ThinkingPreset | None = thinking
        self._retry_next_run = False

    @classmethod
    def _from_config(  # noqa: FBT001
        cls,
        config: AgentConfigBase,
        model: ModelDefinition,
        credential: ProviderCredential,
        problem_name: str,
        verbose: bool,  # noqa: FBT001
        image: str | None,
        thinking_preset: ThinkingPreset | None = None,
        thinking_max_tokens: int | None = None,
    ) -> OpenCodeAgent:
        """Create an OpenCodeAgent from an OpenCodeAgentConfig."""
        if not isinstance(config, OpenCodeAgentConfig):
            raise TypeError(
                f"Expected OpenCodeAgentConfig, got {type(config).__name__}"
            )

        # Get agent-specific settings from model catalog
        agent_settings = model.get_agent_settings("opencode") or {}

        # Get endpoint from provider if specified in agent_specific
        # Use credential.provider (from CLI) to allow provider override
        endpoint = model.get_agent_endpoint("opencode", credential.provider)

        provider_overrides = agent_settings.get("provider_name_overrides", {})
        provider_override = None
        if isinstance(provider_overrides, dict):
            provider_override = provider_overrides.get(credential.provider)

        # Provider resolution order:
        # credential-specific override -> configured default -> model default.
        provider = (
            provider_override
            or agent_settings.get("provider_name")
            or model.provider
        )

        # Get model slug for API calls
        model_slug = model.get_model_slug(provider)

        # Merge config (agent_specific base, YAML config overrides)
        opencode_config = dict(config.config)
        if "config" in agent_settings:
            opencode_config = _deep_merge(
                agent_settings["config"], opencode_config
            )

        # Inject endpoint api_base into provider config if endpoint is specified
        if endpoint:
            # Ensure provider config section exists
            if "provider" not in opencode_config:
                opencode_config["provider"] = {}
            if provider not in opencode_config["provider"]:
                opencode_config["provider"][provider] = {}
            if "options" not in opencode_config["provider"][provider]:
                opencode_config["provider"][provider]["options"] = {}
            # Set baseURL from endpoint if not already set
            if (
                "baseURL"
                not in opencode_config["provider"][provider]["options"]
            ):
                opencode_config["provider"][provider]["options"]["baseURL"] = (
                    endpoint.api_base
                )

        # Merge env (agent_specific base, YAML env overrides)
        env = dict(config.env)
        if "env_overrides" in agent_settings:
            env = {**agent_settings["env_overrides"], **env}

        # Resolve thinking: CLI/config override > model default
        thinking: ThinkingPreset | None = thinking_preset
        if thinking is None and thinking_max_tokens is None:
            thinking, _ = model.get_thinking_config("opencode")

        return cls(
            problem_name=problem_name,
            verbose=verbose,
            cost_limits=config.cost_limits,
            pricing=model.pricing,
            credential=credential,
            model_id=model_slug,
            provider=provider,
            opencode_config=opencode_config,
            env=env,
            thinking=thinking,
            image=image or "sc-opencode:latest",
        )

    @property
    def session(self) -> Session:
        if self._session is None:
            raise AgentError("Trying to get session before setup")

        return self._session

    @property
    def runtime(self) -> StreamingRuntime:
        if self._runtime is None:
            raise AgentError("Trying to get runtime before setup")
        return self._runtime

    @property
    def tmp_dir(self) -> Path:
        if self._tmp_dir is None:
            raise AgentError("Trying to get tmp dir before setup")
        return Path(self._tmp_dir.name)

    def _build_opencode_command(
        self, task: str, *, resume: bool = False
    ) -> str:
        quoted_task = shlex.quote(task)
        quoted_model = shlex.quote(f"{self.provider}/{self.model_id}")
        variant_flag = self._get_variant_flag()
        maybe_variant = f" {variant_flag}" if variant_flag else ""
        maybe_continue = " --continue" if resume else ""
        return (
            f"opencode --model={quoted_model} run --format=json "
            f"--thinking --dangerously-skip-permissions{maybe_variant}"
            f"{maybe_continue} -- {quoted_task}"
        )

    def _get_variant_flag(self) -> str | None:
        if self.thinking in (None, "none", "disabled"):
            return None
        variant = THINKING_TO_VARIANT.get(self.thinking)
        if self.thinking == "xhigh" and self.provider == "openai":
            variant = "xhigh"
        if variant is None:
            return None
        return f"--variant={shlex.quote(variant)}"

    def _make_opencode_config(self) -> Path:
        opencode_config_path = self.tmp_dir / "opencode.json"
        self.log.debug(
            "Writing opencode config...",
            verbose=True,
            opencode_config_path=str(opencode_config_path),
            opencode_config=self.open_code_config,
        )
        if not self.open_code_config:
            self.open_code_config = {
                "$schema": "https://opencode.ai/config.json",
            }

        if self._should_inject_thinking_config():
            self._inject_thinking_config()

        with opencode_config_path.open("w") as f:
            # Write config JSON that gets mounted into the runtime container.
            f.write(json.dumps(self.open_code_config))
        return opencode_config_path

    def _should_inject_thinking_config(self) -> bool:
        if self.thinking in (None, "none", "disabled"):
            return False
        return self.provider != "openai"

    def _inject_thinking_config(self) -> None:
        """Inject thinking/reasoning config as a compatibility fallback.

        OpenAI flows should prefer ``--variant`` and let opencode handle
        provider/model behavior. Non-OpenAI providers keep injection support.
        """
        if self.provider == "openrouter":
            defaults: dict[str, Any] = {
                "provider": {
                    "openrouter": {
                        "models": {
                            self.model_id: {
                                "options": {
                                    "reasoningEffort": self.thinking,
                                }
                            }
                        }
                    }
                }
            }
        else:
            defaults = {
                "agent": {
                    "build": {
                        "reasonEffort": self.thinking,
                    }
                }
            }
        self.open_code_config = _deep_merge(defaults, self.open_code_config)

    def _get_volumes(self) -> dict[str, dict[str, str] | str]:
        volumes: dict[str, dict[str, str] | str] = {}
        opencode_config_path = self._make_opencode_config()
        volumes[str(opencode_config_path.absolute())] = {
            "bind": f"{HOME_PATH}/.config/opencode/opencode.json",
            "mode": "rw",
        }

        # Handle file-based credentials (auth file)
        if (
            self.credential is not None
            and self.credential.credential_type == CredentialType.FILE
        ):
            auth_file_path = Path(self.credential.source)
            volumes[str(auth_file_path)] = {
                "bind": f"{HOME_PATH}/.local/share/opencode/auth.json",
                "mode": "ro",
            }

        self._storage_dir = self.tmp_dir / "storage"
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        volumes[str(self._storage_dir.absolute())] = {
            "bind": f"{HOME_PATH}/.local/share/opencode/storage/",
            "mode": "rw",
        }
        return volumes

    def setup(self, session: Session) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()

        self._session = session

        # Build env vars: base defaults, then env overrides, then credential
        env_vars = {
            "HOME": HOME_PATH,
            "OPENCODE_FAKE_VCS": "git",
        }

        # Apply env overrides from config (YAML/catalog merged)
        env_vars.update(self.env)

        # Credential env var takes highest priority
        if (
            self.credential is not None
            and self.credential.credential_type == CredentialType.ENV_VAR
        ):
            # Use destination_key for the env var name
            env_vars[self.credential.destination_key] = self.credential.value
        # File credentials are handled in _get_volumes()

        self._runtime = session.spawn(
            mounts=self._get_volumes(),
            env_vars=env_vars,
            disable_setup=True,
            image=self.image,
            user="1000:1000",
        )
        self.log.debug("Opencode agent has been setup")

    def run(self, task: str):
        resume = self._retry_next_run
        self._retry_next_run = False
        command = self._build_opencode_command(task, resume=resume)
        self.log.debug(
            "Starting OpenCode run",
            command=command[:256],
            verbose=self.verbose,
        )

        self.continue_on_run = True
        buffer = ""
        result = None
        saw_step_finish = False

        for event in self.runtime.stream(
            command=command,
            env={},
            timeout=None,
        ):
            if event.kind != "stdout":
                if event.kind == "finished":
                    self.log.debug(
                        "OpenCode runtime finished",
                        exit_code=event.result.exit_code
                        if event.result
                        else None,
                        stderr=(
                            event.result.stderr[:500]
                            if event.result and event.result.stderr
                            else None
                        ),
                    )
                    result = event.result
                    break
                if event.kind == "stderr":
                    self._stderr += event.text or ""
                continue
            if event.text is None:
                continue
            buffer += event.text
            self._stdout += event.text or ""
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()
                if not line:
                    continue
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    self.log.debug(
                        "Failed to parse OpenCode output line",
                        line=line,
                    )
                    continue

                saw_step = self._handle_message(message)
                saw_step_finish = saw_step_finish or saw_step
        if buffer.strip():
            try:
                message = json.loads(buffer.strip())
            except json.JSONDecodeError:
                self.log.debug(
                    "Failed to parse trailing OpenCode output",
                    buffer=buffer,
                )
            else:
                saw_step = self._handle_message(message)
                saw_step_finish = saw_step_finish or saw_step

        if result is None:
            message = "OpenCode runtime did not provide a finished event"
            self.log.error(
                "agent.opencode.no_finished_event",
                error_message=message,
                stderr=self._stderr,
            )
            raise AgentError(message)
        if not saw_step_finish:
            message = (
                "OpenCode runtime did not provide any step_finish messages"
            )
            self.log.error(
                "agent.opencode.no_step_finish",
                error_message=message,
                stderr=self._stderr,
            )
            raise AgentError(message)

        self.continue_on_run = False

    def retry(self) -> None:
        self._retry_next_run = True
        self.run(RETRY_PROMPT)

    def _handle_message(
        self,
        message: dict[str, Any],
    ) -> bool:
        self.messages.append(message)
        self._raise_on_opencode_error(message)
        if not self.is_agent_message(message):
            return False

        self.handle_step(message)
        self.log.debug(
            "OpenCode agent parsed",
            message_type=message.get("type"),
            message_content=str(message)[:32],
            tokens=self.usage.current_tokens.total,
            cache_read=self.usage.current_tokens.cache_read,
            cache_write=self.usage.current_tokens.cache_write,
            generated=self.usage.net_tokens.output,
            reasoning=self.usage.net_tokens.reasoning,
            cost=self.usage.cost,
            steps=self.usage.steps,
        )

        if self.should_stop(message) or self._enforce_limits():
            self.log.debug(
                "OpenCode step finished with stop reason",
                message=message,
            )
            self.continue_on_run = False
        return True

    def _raise_on_opencode_error(self, message: dict[str, Any]) -> None:
        if message.get("type") != "error":
            return

        error_payload = message.get("error")
        error_message: str | None = None
        if isinstance(error_payload, dict):
            message_value = error_payload.get("message")
            if isinstance(message_value, str):
                error_message = message_value
        elif isinstance(error_payload, str):
            error_message = error_payload

        if error_message is None:
            error_message = "unknown OpenCode error"

        self.log.error(
            "OpenCode runtime reported an error",
            error_message=error_message,
        )
        raise AgentError(f"OpenCode error: {error_message}")

    def save_artifacts(self, path: Path) -> None:
        with (path / "messages.jsonl").open("w") as f:
            for m in self.messages:
                f.write(json.dumps(m) + "\n")
        with (path / "stdout.txt").open("w") as f:
            f.write(self._stdout)
        with (path / "stderr.txt").open("w") as f:
            f.write(self._stderr)

    def is_agent_message(self, message: dict) -> bool:
        return message.get("type") == STEP_FINISH_TYPE

    def should_stop(self, message: dict) -> bool:
        return message.get("part", {}).get("reason") == "stop"

    def handle_step(self, message: dict):
        msg_part = message["part"]
        tokens = msg_part["tokens"]
        token_usage = TokenUsage(
            input=tokens["input"],
            output=tokens["output"],
            cache_read=tokens["cache"]["read"],
            cache_write=tokens["cache"].get("write", 0),
            reasoning=tokens["reasoning"],
        )
        step_cost = self._resolve_step_cost(
            reported_cost=msg_part.get("cost"),
            token_usage=token_usage,
        )
        self.usage.step(
            cost=step_cost,
            tokens=token_usage,
        )

    def _resolve_step_cost(
        self,
        reported_cost: Any,
        token_usage: TokenUsage,
    ) -> float:
        step_cost: float | None = None
        if isinstance(reported_cost, int | float):
            step_cost = float(reported_cost)
        elif isinstance(reported_cost, str):
            with contextlib.suppress(ValueError):
                step_cost = float(reported_cost)

        # Trust a positive reported cost; otherwise fall back to catalog pricing.
        if step_cost is not None and step_cost > 0:
            return step_cost
        if self.pricing is not None:
            return self.pricing.get_cost(token_usage)
        return 0.0

    def reset(self) -> None:
        self.continue_on_run = False
        self.messages = []
        self._stderr = ""
        self._stdout = ""

    def cleanup(self) -> None:
        self.log.debug("Cleaning up agent")
        if self._runtime is not None:
            self._runtime.cleanup()

        if self._tmp_dir is not None:
            self._tmp_dir.cleanup()

    def _enforce_limits(self) -> bool:
        if not self.cost_limits.is_above_limits(
            self.usage,
            prior_cost=self.prior_cost,
        ):
            return False

        self.continue_on_run = False
        if self._runtime is not None:
            with contextlib.suppress(Exception):
                self._runtime.kill()
        return True


# Register this agent type with the agent registry
register_agent("opencode", OpenCodeAgent)
