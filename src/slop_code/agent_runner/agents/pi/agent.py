"""PI CLI agent implementation."""

from __future__ import annotations

import base64
import binascii
import functools
import json
import os
import shlex
import tempfile
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

PiThinking = tp.Literal["off", "minimal", "low", "medium", "high", "xhigh"]

_SCB_TO_PI_PROVIDER: dict[str, str] = {
    "openai": "openai",
    "codex_auth": "openai-codex",
    "anthropic": "anthropic",
    "claude_code_oauth": "anthropic",
    "google": "google",
    "openrouter": "openrouter",
    "groq": "groq",
    "mistral": "mistral",
    "xai": "xai",
    "bedrock": "amazon-bedrock",
    "zhipu": "zai",
    "zhipu-coding-plan": "zai",
    "zai": "zai",
    "ai_gateway": "vercel-ai-gateway",
    "vercel-ai-gateway": "vercel-ai-gateway",
    "minimax": "minimax",
}

_PI_PROVIDER_NAMES = {
    "anthropic",
    "openai",
    "openai-codex",
    "google",
    "google-vertex",
    "amazon-bedrock",
    "mistral",
    "xai",
    "groq",
    "cerebras",
    "openrouter",
    "vercel-ai-gateway",
    "zai",
    "minimax",
    "minimax-cn",
    "github-copilot",
    "google-gemini-cli",
    "google-antigravity",
}

_CREDENTIAL_ENV_KEYS: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "claude_code_oauth": "ANTHROPIC_OAUTH_TOKEN",
    "google": "GEMINI_API_KEY",
    "groq": "GROQ_API_KEY",
    "xai": "XAI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "zhipu": "ZAI_API_KEY",
    "zhipu-coding-plan": "ZAI_API_KEY",
    "zai": "ZAI_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "ai_gateway": "AI_GATEWAY_API_KEY",
    "vercel-ai-gateway": "AI_GATEWAY_API_KEY",
    "minimax": "MINIMAX_API_KEY",
    "cerebras": "CEREBRAS_API_KEY",
}

# pi speaks these API dialects; keys are the ``api_format`` values used by the
# provider catalog endpoints in ``configs/providers.yaml``.
_PI_API_FORMATS: dict[str, str] = {
    "openai": "openai-completions",
    "anthropic": "anthropic-messages",
}

# pi's own defaults for custom models (docs/models.md).
_PI_DEFAULT_CONTEXT_WINDOW = 128_000
_PI_DEFAULT_MAX_TOKENS = 16_384

_AWS_ENV_KEYS = (
    "AWS_PROFILE",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "AWS_REGION",
    "AWS_DEFAULT_REGION",
)

_PROTECTED_PI_FLAGS = (
    "--print",
    "-p",
    "--mode",
    "--no-session",
    "--session",
    "--continue",
    "-c",
    "--resume",
    "-r",
    "--provider",
    "--model",
    "--api-key",
)

_SIGTERM_EXIT_CODE = 128 + 15
_OPENAI_AUTH_CLAIM = "https://api.openai.com/auth"
_PI_ARTIFACT_EXCLUDED_EVENT_TYPES = frozenset({"message_update"})


def _decode_jwt_payload(token: str) -> dict[str, tp.Any] | None:
    parts = token.split(".")
    if len(parts) != 3:
        return None

    payload = parts[1]
    padded_payload = payload + "=" * (-len(payload) % 4)
    try:
        decoded = base64.urlsafe_b64decode(padded_payload.encode()).decode()
        parsed = json.loads(decoded)
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError):
        return None

    if isinstance(parsed, dict):
        return parsed
    return None


def _get_auth_claim(payload: dict[str, tp.Any]) -> dict[str, tp.Any]:
    claim = payload.get(_OPENAI_AUTH_CLAIM)
    if isinstance(claim, dict):
        return claim
    return {}


def _extract_chatgpt_account_id(*tokens: str | None) -> str | None:
    for token in tokens:
        if not token:
            continue
        payload = _decode_jwt_payload(token)
        if payload is None:
            continue
        claim = _get_auth_claim(payload)
        account_id = claim.get("chatgpt_account_id")
        if isinstance(account_id, str) and account_id:
            return account_id
    return None


def _extract_expiry_ms(*tokens: str | None) -> int:
    for token in tokens:
        if not token:
            continue
        payload = _decode_jwt_payload(token)
        if payload is None:
            continue
        exp = payload.get("exp")
        if isinstance(exp, int | float):
            return int(exp * 1000)
    return 0


class PiConfig(AgentConfigBase):
    """Configuration for ``PiAgent`` instances."""

    type: tp.Literal["pi"] = "pi"
    binary: str = "pi"
    version: str
    timeout: int | None = None
    extra_args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    provider: str | None = None
    thinking: PiThinking | None = None
    docker_template: Path = Path(__file__).parent / "docker.j2"

    def get_docker_file(self, base_image: str) -> str | None:
        if self.docker_template is None:
            return None
        template = self.docker_template.read_text()
        return Template(template).render(
            base_image=base_image,
            version=self.version,
        )


class PiAgent(Agent):
    """Agent implementation built on top of the PI CLI executor."""

    PROMPT_FILENAME = "prompt.txt"
    STDOUT_FILENAME = "stdout.jsonl"
    STDERR_FILENAME = "stderr.log"
    MODELS_FILENAME = "models.json"

    def __init__(
        self,
        problem_name: str,
        verbose: bool,  # noqa: FBT001
        image: str,
        # From base config
        cost_limits: AgentCostLimits,
        pricing: APIPricing | None,
        credential: ProviderCredential | None,
        # PI specific
        binary: str,
        provider: str,
        model: str,
        timeout: int | None,
        thinking: PiThinking | None,
        extra_args: list[str],
        env: dict[str, str],
        models_json: dict[str, tp.Any] | None,
    ) -> None:
        super().__init__(
            agent_name="pi",
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
        self.thinking = thinking
        self.extra_args = extra_args
        self.env = env
        self.models_json = models_json

        self._image = image
        self._session: Session | None = None
        self._environment: EnvironmentSpec | None = None
        self._runtime: StreamingRuntime | None = None
        self._tmp_dir: tempfile.TemporaryDirectory | None = None
        self._pi_auth_dir: Path | None = None
        self._pi_agent_dir_env: str | None = None

        self._last_prompt: str = ""
        self._last_command: AgentCommandResult | None = None
        self._artifact_payloads: list[dict[str, tp.Any]] = []
        self._saw_assistant_message_end = False

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
        if not isinstance(config, PiConfig):
            raise TypeError(f"Expected PiConfig, got {type(config).__name__}")
        if image is None:
            raise ValueError("PiAgent requires an image")

        pi_provider_input = config.provider or credential.provider
        models_json = cls._build_models_json(
            provider=pi_provider_input,
            model=model,
            credential=credential,
        )
        if models_json is None:
            pi_provider = cls._resolve_pi_provider(pi_provider_input)
            model_slug = cls._resolve_model_slug(
                model=model,
                pi_provider=pi_provider,
                credential_provider=credential.provider,
            )
        else:
            pi_provider = pi_provider_input
            model_slug = model.get_model_slug(pi_provider_input)
        thinking = cls._resolve_pi_thinking(
            config_thinking=config.thinking,
            thinking_preset=thinking_preset,
            thinking_max_tokens=thinking_max_tokens,
        )

        return cls(
            problem_name=problem_name,
            verbose=verbose,
            image=image,
            cost_limits=config.cost_limits,
            pricing=model.pricing,
            credential=credential,
            binary=config.binary,
            provider=pi_provider,
            model=model_slug,
            timeout=config.timeout,
            thinking=thinking,
            extra_args=config.extra_args,
            env=config.env,
            models_json=models_json,
        )

    @classmethod
    def _build_models_json(
        cls,
        provider: str,
        model: ModelDefinition,
        credential: ProviderCredential,
    ) -> dict[str, tp.Any] | None:
        """Describe a gateway provider for pi's ``models.json``.

        pi only knows its built-in providers. A model routed through a gateway
        (Portkey, for instance) declares ``agent_specific.pi.endpoint``; the
        endpoint resolves against the credential provider's entry in
        ``configs/providers.yaml`` and becomes a custom pi provider named after
        that credential provider. Models without that declaration keep using
        pi's built-in providers and get ``None`` here.
        """
        endpoint = model.get_agent_endpoint("pi", provider_override=provider)
        if endpoint is None:
            return None

        settings = model.get_agent_settings("pi") or {}
        pricing = model.pricing
        return {
            "providers": {
                provider: {
                    "baseUrl": endpoint.api_base,
                    "api": _PI_API_FORMATS[endpoint.api_format],
                    "apiKey": cls._credential_env_key(credential),
                    "models": [
                        {
                            "id": model.get_model_slug(provider),
                            "name": model.name or model.internal_name,
                            "reasoning": bool(settings.get("reasoning", False)),
                            "input": ["text"],
                            "contextWindow": int(
                                settings.get(
                                    "context_window",
                                    _PI_DEFAULT_CONTEXT_WINDOW,
                                )
                            ),
                            "maxTokens": int(
                                settings.get(
                                    "max_tokens", _PI_DEFAULT_MAX_TOKENS
                                )
                            ),
                            "cost": {
                                "input": pricing.input,
                                "output": pricing.output,
                                "cacheRead": pricing.cache_read,
                                "cacheWrite": pricing.cache_write,
                            },
                        }
                    ],
                }
            }
        }

    @staticmethod
    def _credential_env_key(credential: ProviderCredential) -> str:
        return _CREDENTIAL_ENV_KEYS.get(
            credential.provider, credential.destination_key
        )

    @staticmethod
    def _resolve_model_slug(
        model: ModelDefinition,
        pi_provider: str,
        credential_provider: str,
    ) -> str:
        slug = model.get_model_slug(pi_provider)
        if slug != model.internal_name:
            return slug
        if credential_provider == pi_provider:
            return slug
        return model.get_model_slug(credential_provider)

    @staticmethod
    def _resolve_pi_provider(provider: str) -> str:
        if provider in _PI_PROVIDER_NAMES:
            return provider
        mapped = _SCB_TO_PI_PROVIDER.get(provider)
        if mapped is not None:
            return mapped
        raise ValueError(
            "Unsupported PI provider mapping for "
            f"'{provider}'. Configure a supported provider explicitly."
        )

    @staticmethod
    def _resolve_pi_thinking(
        config_thinking: PiThinking | None,
        thinking_preset: ThinkingPreset | None,
        thinking_max_tokens: int | None,
    ) -> PiThinking | None:
        if config_thinking is not None:
            return config_thinking
        if thinking_max_tokens is not None:
            return None
        if thinking_preset is None:
            return None

        mapped = {
            "disabled": "off",
            "low": "low",
            "medium": "medium",
            "high": "high",
            "xhigh": "xhigh",
        }.get(thinking_preset)
        if mapped is None:
            return None
        return tp.cast("PiThinking", mapped)

    @staticmethod
    def _convert_codex_auth_payload(
        payload: dict[str, tp.Any],
    ) -> dict[str, dict[str, tp.Any]]:
        tokens: dict[str, tp.Any]
        if "openai-codex" in payload and isinstance(
            payload["openai-codex"], dict
        ):
            tokens = payload["openai-codex"]
        elif "tokens" in payload and isinstance(payload["tokens"], dict):
            tokens = payload["tokens"]
        else:
            tokens = payload

        def _pick(*keys: str) -> str | None:
            for key in keys:
                value = tokens.get(key)
                if isinstance(value, str) and value:
                    return value
            return None

        access = _pick("access", "access_token")
        refresh = _pick("refresh", "refresh_token")
        id_token = _pick("id_token")
        account_id = _pick(
            "accountId",
            "account_id",
        ) or _extract_chatgpt_account_id(access, id_token)

        if not access or not refresh or not account_id:
            raise AgentError(
                "Invalid Codex auth payload: expected access token, refresh token, "
                "and account id."
            )

        raw_expires = tokens.get("expires")
        expires = (
            int(raw_expires)
            if isinstance(raw_expires, int | float)
            else _extract_expiry_ms(access, id_token)
        )

        return {
            "openai-codex": {
                "type": "oauth",
                "access": access,
                "refresh": refresh,
                "expires": expires,
                "accountId": account_id,
            }
        }

    @staticmethod
    def parse_line(
        line: str,
        pricing: APIPricing | None = None,
    ) -> tuple[float | None, TokenUsage | None, dict | None]:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            return None, None, None

        if payload.get("type") != "message_end":
            return None, None, payload

        message = payload.get("message")
        if not isinstance(message, dict):
            return None, None, payload
        if message.get("role") != "assistant":
            return None, None, payload

        usage = message.get("usage")
        if not isinstance(usage, dict):
            return None, None, payload

        cache_read = int(usage.get("cacheRead") or 0)
        tokens = TokenUsage(
            input=int(usage.get("input") or 0) + cache_read,
            output=int(usage.get("output") or 0),
            cache_read=cache_read,
            cache_write=int(usage.get("cacheWrite") or 0),
            reasoning=int(usage.get("reasoning") or 0),
        )

        reported_cost: float | None = None
        usage_cost = usage.get("cost")
        if isinstance(usage_cost, dict):
            total = usage_cost.get("total")
            if isinstance(total, int | float):
                reported_cost = float(total)

        cost = (
            reported_cost
            if reported_cost is not None
            else pricing.get_cost(tokens)
            if pricing is not None
            else 0.0
        )

        return cost, tokens, payload

    @property
    def session(self) -> Session:
        if self._session is None:
            raise AgentError("PiAgent has not been set up with a session")
        return self._session

    @property
    def spec(self) -> EnvironmentSpec:
        if self._environment is None:
            raise AgentError("PiAgent has not been set up with a session")
        return self._environment

    @property
    def runtime(self) -> StreamingRuntime:
        if self._runtime is None:
            raise AgentError("PiAgent has not been set up with a runtime")
        return self._runtime

    def setup(self, session: Session) -> None:
        self._session = session
        self._environment = session.spec
        self._artifact_payloads = []
        self._tmp_dir = tempfile.TemporaryDirectory()
        self._pi_auth_dir = Path(self._tmp_dir.name) / "pi-agent"
        self._pi_auth_dir.mkdir(parents=True, exist_ok=True)
        self._pi_auth_dir.chmod(0o777)

        if (
            self.credential is not None
            and self.credential.provider == "codex_auth"
            and self.credential.credential_type == CredentialType.FILE
        ):
            self._write_converted_codex_auth(self._pi_auth_dir)

        if self.models_json is not None:
            models_path = self._pi_auth_dir / self.MODELS_FILENAME
            models_path.write_text(
                json.dumps(self.models_json, indent=2), encoding="utf-8"
            )
            models_path.chmod(0o666)

        pi_agent_container_path = f"{HOME_PATH}/.pi/agent"
        mounts: dict[str, dict[str, str] | str] = {}
        if isinstance(session.spec, DockerEnvironmentSpec):
            mounts[str(self._pi_auth_dir)] = {
                "bind": pi_agent_container_path,
                "mode": "rw",
            }
            self._pi_agent_dir_env = pi_agent_container_path
        else:
            self._pi_agent_dir_env = str(self._pi_auth_dir)

        self._runtime = session.spawn(
            mounts=mounts,
            env_vars={
                "HOME": HOME_PATH,
                "PI_CODING_AGENT_DIR": self._pi_agent_dir_env,
            },
            image=self._image,
            disable_setup=True,
        )

    def _write_converted_codex_auth(self, target_dir: Path) -> None:
        if self.credential is None:
            raise AgentError("Codex auth conversion requires a credential")

        try:
            payload = json.loads(self.credential.value)
        except json.JSONDecodeError as e:
            raise AgentError("Failed to parse Codex auth JSON") from e

        if not isinstance(payload, dict):
            raise AgentError("Invalid Codex auth payload: expected JSON object")

        converted = self._convert_codex_auth_payload(payload)
        auth_path = target_dir / "auth.json"
        auth_path.write_text(json.dumps(converted), encoding="utf-8")
        auth_path.chmod(0o666)

    def run(self, task: str) -> None:
        self._last_prompt = task
        self._last_command = None
        self._artifact_payloads = []
        self._saw_assistant_message_end = False

        log_kwargs: dict[str, tp.Any] = {
            "workspace": str(self.session.working_dir),
            "prompt_chars": len(task),
            "environment": self.session.spec.type,
            "extra_args": self.extra_args,
            "provider": self.provider,
            "model": self.model,
        }
        if isinstance(self.session.spec, DockerEnvironmentSpec):
            log_kwargs["image"] = self.session.spec.docker.image
        self.log.info("agent.pi.start", **log_kwargs)

        command_result = self._run_invocation(task)
        self._last_command = command_result
        self._sync_usage(command_result.usage_totals)

        runtime_result = command_result.result
        if runtime_result is None:
            message = "PI process failed to start"
            self.log.error(
                "agent.pi.start_failed",
                error_message=message,
                agent_message=command_result.error_message,
                stdout=command_result.stdout,
                stderr=command_result.stderr,
            )
            raise AgentError(message)

        if runtime_result.timed_out:
            message = (
                f"PI process timed out after {self.timeout}s."
                if self.timeout is not None
                else "PI process timed out."
            )
            self.log.error(
                "agent.pi.timeout",
                error_message=message,
                timeout=self.timeout,
            )
            raise AgentError(message)

        if runtime_result.exit_code == _SIGTERM_EXIT_CODE:
            self.log.warning(
                "agent.pi.sigterm",
                exit_code=runtime_result.exit_code,
            )
        elif runtime_result.exit_code != 0:
            message = (
                f"PI process failed with exit code {runtime_result.exit_code}"
            )
            if runtime_result.stderr:
                message = f"{message}\n--- Stderr ---\n{runtime_result.stderr.strip()}"
            self.log.error(
                "agent.pi.exit",
                error_message=message,
                exit_code=runtime_result.exit_code,
            )
            raise AgentError(message)

        if command_result.had_error:
            message = (
                command_result.error_message
                or "PI returned an error event in structured output."
            )
            self.log.error("agent.pi.message_error", error_message=message)
            raise AgentError(message)

        if (
            runtime_result.exit_code != _SIGTERM_EXIT_CODE
            and not self._saw_assistant_message_end
        ):
            message = (
                "PI exited with code "
                f"{runtime_result.exit_code} without emitting a final assistant "
                "message."
            )
            self.log.error(
                "agent.pi.missing_final_message",
                error_message=message,
                exit_code=runtime_result.exit_code,
                stderr=runtime_result.stderr,
            )
            raise AgentError(message)

    def _run_invocation(self, task: str) -> AgentCommandResult:
        command, env_overrides = self._prepare_runtime_execution(task)
        if self._session is None:
            raise AgentError("PiAgent has not been set up with a session")

        command_text = " ".join(shlex.quote(part) for part in command)
        parser = tp.cast(
            "tp.Callable[[str], tuple[float | None, TokenUsage | None, dict]]",
            functools.partial(self.parse_line, pricing=self.pricing),
        )

        total_tokens = TokenUsage()
        step_count = 0
        runtime_result = None
        reported_cost_micros = 0
        has_reported_cost = False
        stream_error_message: str | None = None

        for item in stream_cli_command(
            runtime=self.runtime,
            command=command_text,
            parser=parser,
            env=env_overrides,
            timeout=(float(self.timeout) if self.timeout is not None else None),
        ):
            if not isinstance(item, tuple):
                runtime_result = item
                break

            _, tokens, payload = item
            if tokens is not None:
                total_tokens = total_tokens + tokens

            if not payload:
                continue

            event_type = payload.get("type")
            if event_type not in _PI_ARTIFACT_EXCLUDED_EVENT_TYPES:
                self._artifact_payloads.append(payload)

            if event_type == "message_end":
                message = payload.get("message")
                if (
                    isinstance(message, dict)
                    and message.get("role") == "assistant"
                ):
                    step_count += 1
                    self.usage.steps += 1
                    self._saw_assistant_message_end = True
                    stop_reason = message.get("stopReason")
                    if isinstance(stop_reason, str) and stop_reason in {
                        "error",
                        "aborted",
                    }:
                        error_message = message.get("errorMessage")
                        if isinstance(error_message, str) and error_message:
                            stream_error_message = error_message
                        else:
                            stream_error_message = (
                                "PI assistant message ended with "
                                f"stopReason='{stop_reason}'."
                            )
                    usage = message.get("usage")
                    if isinstance(usage, dict):
                        usage_cost = usage.get("cost")
                        if isinstance(usage_cost, dict):
                            total = usage_cost.get("total")
                            if isinstance(total, int | float):
                                has_reported_cost = True
                                reported_cost_micros += int(
                                    round(float(total) * 1_000_000)
                                )
            elif event_type == "tool_execution_end":
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
                "reasoning_tokens": total_tokens.reasoning,
                "total_tokens": total_tokens.input + total_tokens.output,
                "steps": step_count,
                "reported_cost_present": int(has_reported_cost),
                "reported_cost_micros": reported_cost_micros,
            },
            stdout=stdout,
            stderr=stderr,
            had_error=stream_error_message is not None,
            error_message=stream_error_message,
        )

    def _prepare_runtime_execution(
        self,
        task: str,
    ) -> tuple[list[str], dict[str, str]]:
        env_overrides = {key: str(value) for key, value in self.env.items()}

        if self._pi_agent_dir_env:
            env_overrides["PI_CODING_AGENT_DIR"] = self._pi_agent_dir_env

        env_overrides.update(self._build_credential_env())
        command = self._build_command(task)
        return command, env_overrides

    def _build_credential_env(self) -> dict[str, str]:
        if self.credential is None:
            return {}

        if self.credential.provider == "bedrock":
            env = {"AWS_BEARER_TOKEN_BEDROCK": self.credential.value}
            for key in _AWS_ENV_KEYS:
                value = os.environ.get(key)
                if value:
                    env[key] = value
            return env

        if self.credential.credential_type != CredentialType.ENV_VAR:
            return {}

        return {
            self._credential_env_key(self.credential): self.credential.value
        }

    def _build_command(self, prompt: str) -> list[str]:
        self._validate_extra_args()

        command = [
            self.binary,
            "--print",
            "--mode",
            "json",
            "--no-session",
            "--provider",
            self.provider,
            "--model",
            self.model,
        ]
        if self.thinking:
            command.extend(["--thinking", self.thinking])
        command.extend(self.extra_args)
        command.append(prompt)
        return command

    def _validate_extra_args(self) -> None:
        for arg in self.extra_args:
            if any(
                arg == protected or arg.startswith(f"{protected}=")
                for protected in _PROTECTED_PI_FLAGS
            ):
                raise AgentError(
                    "extra_args contains protected PI flag "
                    f"'{arg}'. Configure required PI flags via PiConfig fields."
                )

    def _sync_usage(self, totals: dict[str, int]) -> None:
        totals = totals or {}
        input_tokens = int(totals.get("input_tokens") or 0)
        output_tokens = int(totals.get("output_tokens") or 0)
        cache_read_tokens = int(totals.get("cached_input_tokens") or 0)
        cache_write_tokens = int(totals.get("cached_write_tokens") or 0)
        reasoning_tokens = int(totals.get("reasoning_tokens") or 0)

        tokens = TokenUsage(
            input=input_tokens,
            output=output_tokens,
            cache_read=cache_read_tokens,
            cache_write=cache_write_tokens,
            reasoning=reasoning_tokens,
        )

        if int(totals.get("reported_cost_present") or 0):
            cost = (
                float(int(totals.get("reported_cost_micros") or 0)) / 1_000_000
            )
        else:
            cost = self.pricing.get_cost(tokens) if self.pricing else 0.0

        self.usage.cost += cost
        self.usage.net_tokens += tokens
        self.usage.current_tokens = tokens

        if self.cost_limits.is_above_limits(
            self.usage,
            prior_cost=self.prior_cost,
        ):
            raise AgentError("PiAgent exceeded configured usage limits")

    @classmethod
    def _write_artifacts(
        cls,
        output_dir: Path,
        artifact_payloads: list[dict[str, tp.Any]],
        stderr_text: str,
    ) -> None:
        with (output_dir / cls.STDOUT_FILENAME).open("w") as handle:
            for payload in artifact_payloads:
                handle.write(json.dumps(payload, separators=(",", ":")))
                handle.write("\n")
        (output_dir / cls.STDERR_FILENAME).write_text(stderr_text)

    def reset(self) -> None:
        self._last_prompt = ""
        self._last_command = None
        self._artifact_payloads = []
        self._saw_assistant_message_end = False

    def save_artifacts(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)

        if self._last_prompt:
            (path / self.PROMPT_FILENAME).write_text(self._last_prompt)

        stderr_text = ""
        if self._last_command is not None:
            stderr_text = self._last_command.stderr or ""

        self._write_artifacts(path, self._artifact_payloads, stderr_text)

    def cleanup(self) -> None:
        if self._runtime is not None:
            self._runtime.cleanup()
            self._runtime = None
        if self._tmp_dir is not None:
            self._tmp_dir.cleanup()
            self._tmp_dir = None
        self._session = None
        self._environment = None
        self._pi_auth_dir = None
        self._pi_agent_dir_env = None


register_agent("pi", PiAgent)
