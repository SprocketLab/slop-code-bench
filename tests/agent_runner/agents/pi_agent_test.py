"""Unit tests for the PI agent."""

from __future__ import annotations

import base64
import json
import threading
from collections.abc import Callable
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest
import yaml

from slop_code.agent_runner.agents.pi import PiAgent
from slop_code.agent_runner.agents.pi import PiConfig
from slop_code.agent_runner.agents.utils import HOME_PATH
from slop_code.agent_runner.credentials import CredentialType
from slop_code.agent_runner.credentials import ProviderCredential
from slop_code.agent_runner.models import AgentCostLimits
from slop_code.agent_runner.models import AgentError
from slop_code.agent_runner.registry import build_agent_config
from slop_code.common.llms import APIPricing
from slop_code.common.llms import ModelDefinition
from slop_code.execution import DockerConfig
from slop_code.execution import DockerEnvironmentSpec
from slop_code.execution.runtime import RuntimeEvent
from slop_code.execution.runtime import RuntimeResult

if TYPE_CHECKING:
    from slop_code.execution import Session


def run_with_deadline(call: Callable[[], None], timeout: float) -> None:
    """Run ``call`` on a worker thread, failing if it does not finish in time."""
    outcome: list[BaseException | None] = []

    def target() -> None:
        try:
            call()
        except BaseException as exc:  # noqa: BLE001
            outcome.append(exc)
        else:
            outcome.append(None)

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        raise AssertionError(f"call did not finish within {timeout}s")
    error = outcome[0]
    if error is not None:
        raise error


class FakeRuntime:
    """Minimal runtime stub for testing."""

    def __init__(self) -> None:
        self.events: list[RuntimeEvent] = []
        self.cleaned = False
        self.last_stream_args: tuple[tuple, dict] | None = None

    def stream(
        self,
        command: str,
        env: dict,
        timeout: float | None,
    ) -> Iterable[RuntimeEvent]:
        self.last_stream_args = ((command, env, timeout), {})
        yield from self.events

    def cleanup(self) -> None:
        self.cleaned = True


@dataclass
class FakeSession:
    """Fake session for testing."""

    runtime: FakeRuntime
    working_dir: Path
    spec: DockerEnvironmentSpec | None = None
    last_spawn_env_vars: dict[str, str] | None = None
    last_spawn_mounts: dict[str, dict[str, str] | str] | None = None

    def spawn(self, **_: object) -> FakeRuntime:
        env_vars = cast("dict[str, str] | None", _.get("env_vars"))
        mounts = cast(
            "dict[str, dict[str, str] | str] | None",
            _.get("mounts"),
        )
        self.last_spawn_env_vars = dict(env_vars or {})
        self.last_spawn_mounts = dict(mounts or {})
        return self.runtime


def _jwt_with_payload(payload: dict[str, object]) -> str:
    def encode(value: dict[str, object]) -> str:
        raw = json.dumps(value, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    return f"{encode({'alg': 'none'})}.{encode(payload)}.signature"


@pytest.fixture
def mock_pricing() -> APIPricing:
    return APIPricing(
        input=0.15,
        output=0.60,
        cache_read=0.03,
        cache_write=0.60,
    )


@pytest.fixture
def mock_cost_limits() -> AgentCostLimits:
    return AgentCostLimits(
        step_limit=10,
        cost_limit=100.0,
        net_cost_limit=200.0,
    )


@pytest.fixture
def mock_model_def(mock_pricing: APIPricing) -> ModelDefinition:
    return ModelDefinition(
        internal_name="gpt-5.2-codex",
        provider="openai",
        pricing=mock_pricing,
        provider_slugs={
            "openai": "gpt-5.2-codex",
            "openai-codex": "gpt-5.2-codex",
        },
    )


@pytest.fixture
def gateway_model_def() -> ModelDefinition:
    return ModelDefinition(
        internal_name="kimi-k3",
        name="kimi-k3",
        provider="openrouter",
        pricing=APIPricing(
            input=3.0,
            output=15.0,
            cache_read=0.3,
            cache_write=0.0,
        ),
        provider_slugs={
            "openrouter": "moonshotai/kimi-k3",
            "portkey": "@openrouter/moonshotai/kimi-k3",
        },
        agent_specific={
            "pi": {
                "endpoint": "openai",
                "reasoning": True,
                "context_window": 262144,
                "max_tokens": 65536,
            }
        },
    )


@pytest.fixture
def portkey_credential() -> ProviderCredential:
    return ProviderCredential(
        provider="portkey",
        credential_type=CredentialType.ENV_VAR,
        value="portkey-secret",
        source="SCB_PORTKEY",
        destination_key="PORTKEY_API_KEY",
    )


class TestPiConfig:
    """Tests for PiConfig."""

    def test_version_is_required(
        self, mock_cost_limits: AgentCostLimits
    ) -> None:
        with pytest.raises(Exception):
            PiConfig(  # type: ignore[call-arg]
                type="pi",
                cost_limits=mock_cost_limits,
            )

    def test_config_defaults(self, mock_cost_limits: AgentCostLimits) -> None:
        config = PiConfig(
            type="pi",
            version="0.45.7",
            cost_limits=mock_cost_limits,
        )
        assert config.binary == "pi"
        assert config.timeout is None
        assert config.extra_args == []
        assert config.env == {}
        assert config.provider is None
        assert config.thinking is None

    def test_config_loads_from_default_yaml(self) -> None:
        data = yaml.safe_load(Path("configs/agents/pi.yaml").read_text())
        config = build_agent_config(data)
        assert isinstance(config, PiConfig)
        assert config.type == "pi"
        assert config.version == "0.74.0"

    def test_get_docker_file_renders_version(
        self, mock_cost_limits: AgentCostLimits
    ) -> None:
        config = PiConfig(
            type="pi",
            version="0.45.7",
            cost_limits=mock_cost_limits,
        )
        dockerfile = config.get_docker_file("base-image:latest")
        assert dockerfile is not None
        assert "base-image:latest" in dockerfile
        assert "@earendil-works/pi-coding-agent@0.45.7" in dockerfile

    def test_get_docker_file_configures_user_npm_path(
        self, mock_cost_limits: AgentCostLimits
    ) -> None:
        config = PiConfig(
            type="pi",
            version="0.45.7",
            cost_limits=mock_cost_limits,
        )
        dockerfile = config.get_docker_file("base-image:latest")
        assert dockerfile is not None
        assert 'ENV NPM_CONFIG_PREFIX="$HOME/.npm-global"' in dockerfile
        assert 'ENV PATH="$HOME/.npm-global/bin:$PATH"' in dockerfile
        assert "USER agent" in dockerfile


class TestPiAgent:
    """Tests for PiAgent."""

    def test_from_config_creates_agent(
        self,
        mock_cost_limits: AgentCostLimits,
        mock_model_def: ModelDefinition,
    ) -> None:
        config = PiConfig(
            type="pi",
            version="0.45.7",
            cost_limits=mock_cost_limits,
        )
        credential = ProviderCredential(
            provider="openai",
            credential_type=CredentialType.ENV_VAR,
            value="test-api-key",
            source="OPENAI_API_KEY",
            destination_key="OPENAI_API_KEY",
        )

        agent = PiAgent._from_config(
            config=config,
            model=mock_model_def,
            credential=credential,
            problem_name="test-problem",
            verbose=False,
            image="test-image",
        )

        assert isinstance(agent, PiAgent)
        assert agent.binary == "pi"
        assert agent.provider == "openai"
        assert agent.model == "gpt-5.2-codex"

    def test_from_config_maps_disabled_thinking_to_headless_off(
        self,
        mock_cost_limits: AgentCostLimits,
        mock_model_def: ModelDefinition,
    ) -> None:
        config = PiConfig(
            type="pi",
            version="0.45.7",
            cost_limits=mock_cost_limits,
        )
        credential = ProviderCredential(
            provider="openai",
            credential_type=CredentialType.ENV_VAR,
            value="test-api-key",
            source="OPENAI_API_KEY",
            destination_key="OPENAI_API_KEY",
        )

        agent = PiAgent._from_config(
            config=config,
            model=mock_model_def,
            credential=credential,
            problem_name="test-problem",
            verbose=False,
            image="test-image",
            thinking_preset="disabled",
        )

        assert isinstance(agent, PiAgent)
        command = agent._build_command("do something")
        assert "--thinking" in command
        thinking_index = command.index("--thinking")
        assert command[thinking_index + 1] == "off"

    def test_from_config_requires_image(
        self,
        mock_cost_limits: AgentCostLimits,
        mock_model_def: ModelDefinition,
    ) -> None:
        config = PiConfig(
            type="pi",
            version="0.45.7",
            cost_limits=mock_cost_limits,
        )
        credential = ProviderCredential(
            provider="openai",
            credential_type=CredentialType.ENV_VAR,
            value="test-api-key",
            source="OPENAI_API_KEY",
            destination_key="OPENAI_API_KEY",
        )

        with pytest.raises(ValueError, match="requires an image"):
            PiAgent._from_config(
                config=config,
                model=mock_model_def,
                credential=credential,
                problem_name="test-problem",
                verbose=False,
                image=None,
            )

    @pytest.mark.parametrize(
        ("scb_provider", "pi_provider"),
        [
            ("openai", "openai"),
            ("codex_auth", "openai-codex"),
            ("anthropic", "anthropic"),
            ("google", "google"),
            ("openrouter", "openrouter"),
            ("groq", "groq"),
            ("mistral", "mistral"),
            ("xai", "xai"),
            ("bedrock", "amazon-bedrock"),
            ("zhipu", "zai"),
            ("zai", "zai"),
            ("ai_gateway", "vercel-ai-gateway"),
            ("vercel-ai-gateway", "vercel-ai-gateway"),
            ("minimax", "minimax"),
        ],
    )
    def test_resolve_pi_provider(
        self,
        scb_provider: str,
        pi_provider: str,
    ) -> None:
        assert PiAgent._resolve_pi_provider(scb_provider) == pi_provider

    def test_resolve_pi_provider_rejects_unsupported(self) -> None:
        with pytest.raises(ValueError, match="Unsupported PI provider mapping"):
            PiAgent._resolve_pi_provider("unknown_provider")

    def test_builtin_provider_model_has_no_models_json(
        self,
        mock_cost_limits: AgentCostLimits,
        mock_model_def: ModelDefinition,
    ) -> None:
        agent = PiAgent._from_config(
            config=PiConfig(
                type="pi",
                version="0.74.0",
                cost_limits=mock_cost_limits,
            ),
            model=mock_model_def,
            credential=ProviderCredential(
                provider="openai",
                credential_type=CredentialType.ENV_VAR,
                value="test-api-key",
                source="OPENAI_API_KEY",
                destination_key="OPENAI_API_KEY",
            ),
            problem_name="test-problem",
            verbose=False,
            image="test-image",
        )

        assert isinstance(agent, PiAgent)
        assert agent.models_json is None

    def test_gateway_model_becomes_custom_models_json_provider(
        self,
        mock_cost_limits: AgentCostLimits,
        gateway_model_def: ModelDefinition,
        portkey_credential: ProviderCredential,
    ) -> None:
        agent = PiAgent._from_config(
            config=PiConfig(
                type="pi",
                version="0.74.0",
                cost_limits=mock_cost_limits,
            ),
            model=gateway_model_def,
            credential=portkey_credential,
            problem_name="test-problem",
            verbose=False,
            image="test-image",
        )

        assert isinstance(agent, PiAgent)
        assert agent.provider == "portkey"
        assert agent.model == "@openrouter/moonshotai/kimi-k3"
        assert agent.models_json is not None
        provider_entry = agent.models_json["providers"]["portkey"]
        assert provider_entry["baseUrl"] == "https://api.portkey.ai/v1"
        assert provider_entry["api"] == "openai-completions"
        assert provider_entry["apiKey"] == "PORTKEY_API_KEY"
        assert provider_entry["models"] == [
            {
                "id": "@openrouter/moonshotai/kimi-k3",
                "name": "kimi-k3",
                "reasoning": True,
                "input": ["text"],
                "contextWindow": 262144,
                "maxTokens": 65536,
                "cost": {
                    "input": 3.0,
                    "output": 15.0,
                    "cacheRead": 0.3,
                    "cacheWrite": 0.0,
                },
            }
        ]

    def test_gateway_model_defaults_context_and_output_limits(
        self,
        gateway_model_def: ModelDefinition,
        portkey_credential: ProviderCredential,
    ) -> None:
        gateway_model_def.agent_specific["pi"] = {"endpoint": "openai"}

        models_json = PiAgent._build_models_json(
            provider="portkey",
            model=gateway_model_def,
            credential=portkey_credential,
        )

        assert models_json is not None
        entry = models_json["providers"]["portkey"]["models"][0]
        assert entry["reasoning"] is False
        assert entry["contextWindow"] == 128_000
        assert entry["maxTokens"] == 16_384

    def test_gateway_model_maps_anthropic_endpoint_to_pi_api(
        self,
        gateway_model_def: ModelDefinition,
        portkey_credential: ProviderCredential,
    ) -> None:
        gateway_model_def.agent_specific["pi"] = {"endpoint": "anthropic"}

        models_json = PiAgent._build_models_json(
            provider="portkey",
            model=gateway_model_def,
            credential=portkey_credential,
        )

        assert models_json is not None
        provider_entry = models_json["providers"]["portkey"]
        assert provider_entry["api"] == "anthropic-messages"
        assert provider_entry["baseUrl"] == "https://api.portkey.ai"

    def test_setup_writes_models_json_into_pi_agent_dir(
        self,
        tmp_path: Path,
        mock_cost_limits: AgentCostLimits,
        mock_pricing: APIPricing,
        portkey_credential: ProviderCredential,
    ) -> None:
        spec = DockerEnvironmentSpec(
            name="docker-test",
            docker=DockerConfig(image="pi-test-image"),
        )
        session = FakeSession(
            runtime=FakeRuntime(), working_dir=tmp_path, spec=spec
        )
        models_json = {"providers": {"portkey": {"models": []}}}

        agent = PiAgent(
            problem_name="test-problem",
            verbose=False,
            image="pi-test-image",
            cost_limits=mock_cost_limits,
            pricing=mock_pricing,
            credential=portkey_credential,
            binary="pi",
            provider="portkey",
            model="@openrouter/moonshotai/kimi-k3",
            timeout=None,
            thinking=None,
            extra_args=[],
            env={},
            models_json=models_json,
        )

        agent.setup(cast("Session", session))

        assert agent._pi_auth_dir is not None
        written = agent._pi_auth_dir / PiAgent.MODELS_FILENAME
        assert json.loads(written.read_text()) == models_json

    def test_gateway_credential_uses_provider_env_var(
        self,
        mock_cost_limits: AgentCostLimits,
        mock_pricing: APIPricing,
        portkey_credential: ProviderCredential,
    ) -> None:
        agent = PiAgent(
            problem_name="test-problem",
            verbose=False,
            image="test-image",
            cost_limits=mock_cost_limits,
            pricing=mock_pricing,
            credential=portkey_credential,
            binary="pi",
            provider="portkey",
            model="@openrouter/moonshotai/kimi-k3",
            timeout=None,
            thinking=None,
            extra_args=[],
            env={},
            models_json=None,
        )

        command, env_overrides = agent._prepare_runtime_execution("do it")

        assert env_overrides["PORTKEY_API_KEY"] == "portkey-secret"
        assert "portkey-secret" not in " ".join(command)

    def test_build_command_has_required_flags(
        self,
        mock_cost_limits: AgentCostLimits,
        mock_pricing: APIPricing,
    ) -> None:
        agent = PiAgent(
            problem_name="test-problem",
            verbose=False,
            image="test-image",
            cost_limits=mock_cost_limits,
            pricing=mock_pricing,
            credential=None,
            binary="pi",
            provider="openai",
            model="gpt-5.2-codex",
            timeout=None,
            thinking=None,
            extra_args=[],
            env={},
            models_json=None,
        )

        command = agent._build_command("do something")
        assert command[0] == "pi"
        assert "--print" in command
        assert "--mode" in command
        assert "json" in command
        assert "--no-session" in command
        assert "--provider" in command
        assert "openai" in command
        assert "--model" in command
        assert "gpt-5.2-codex" in command

    def test_build_command_with_minimal_thinking(
        self,
        mock_cost_limits: AgentCostLimits,
        mock_pricing: APIPricing,
    ) -> None:
        agent = PiAgent(
            problem_name="test-problem",
            verbose=False,
            image="test-image",
            cost_limits=mock_cost_limits,
            pricing=mock_pricing,
            credential=None,
            binary="pi",
            provider="openai",
            model="gpt-5.2-codex",
            timeout=None,
            thinking="minimal",
            extra_args=[],
            env={},
            models_json=None,
        )

        command = agent._build_command("do something")
        assert "--thinking" in command
        thinking_index = command.index("--thinking")
        assert command[thinking_index + 1] == "minimal"

    def test_resolve_pi_thinking_none_preset_does_not_force_off(self) -> None:
        thinking = PiAgent._resolve_pi_thinking(
            config_thinking=None,
            thinking_preset="none",
            thinking_max_tokens=None,
        )
        assert thinking is None

    def test_resolve_pi_thinking_disabled_preset_sets_off(
        self,
    ) -> None:
        thinking = PiAgent._resolve_pi_thinking(
            config_thinking=None,
            thinking_preset="disabled",
            thinking_max_tokens=None,
        )
        assert thinking == "off"

    def test_build_command_rejects_forbidden_extra_args(
        self,
        mock_cost_limits: AgentCostLimits,
        mock_pricing: APIPricing,
    ) -> None:
        agent = PiAgent(
            problem_name="test-problem",
            verbose=False,
            image="test-image",
            cost_limits=mock_cost_limits,
            pricing=mock_pricing,
            credential=None,
            binary="pi",
            provider="openai",
            model="gpt-5.2-codex",
            timeout=None,
            thinking=None,
            extra_args=["--mode", "text"],
            env={},
            models_json=None,
        )

        with pytest.raises(
            AgentError, match="extra_args contains protected PI flag"
        ):
            agent._build_command("do something")

    def test_prepare_runtime_execution_does_not_embed_api_key_in_command(
        self,
        mock_cost_limits: AgentCostLimits,
        mock_pricing: APIPricing,
    ) -> None:
        credential = ProviderCredential(
            provider="openai",
            credential_type=CredentialType.ENV_VAR,
            value="super-secret-key",
            source="OPENAI_API_KEY",
            destination_key="OPENAI_API_KEY",
        )
        agent = PiAgent(
            problem_name="test-problem",
            verbose=False,
            image="test-image",
            cost_limits=mock_cost_limits,
            pricing=mock_pricing,
            credential=credential,
            binary="pi",
            provider="openai",
            model="gpt-5.2-codex",
            timeout=None,
            thinking=None,
            extra_args=[],
            env={},
            models_json=None,
        )

        command, env_overrides = agent._prepare_runtime_execution(
            "do something"
        )
        joined = " ".join(command)
        assert "super-secret-key" not in joined
        assert env_overrides["OPENAI_API_KEY"] == "super-secret-key"

    def test_codex_auth_conversion_supports_codex_cli_format(self) -> None:
        access_token = _jwt_with_payload(
            {
                "exp": 1_800_000_000,
                "https://api.openai.com/auth": {
                    "chatgpt_account_id": "account-id"
                },
            }
        )
        codex_auth = {
            "tokens": {
                "access_token": access_token,
                "refresh_token": "refresh-token",
            }
        }
        converted = PiAgent._convert_codex_auth_payload(codex_auth)
        assert converted == {
            "openai-codex": {
                "type": "oauth",
                "access": access_token,
                "refresh": "refresh-token",
                "expires": 1_800_000_000_000,
                "accountId": "account-id",
            }
        }

    def test_codex_auth_conversion_rejects_invalid_payload(self) -> None:
        with pytest.raises(AgentError, match="Invalid Codex auth payload"):
            PiAgent._convert_codex_auth_payload({"tokens": {}})

    def test_setup_with_codex_auth_uses_temp_pi_auth_only(
        self,
        tmp_path: Path,
        mock_cost_limits: AgentCostLimits,
        mock_pricing: APIPricing,
    ) -> None:
        auth_source = tmp_path / "auth.json"
        auth_source.write_text(
            json.dumps(
                {
                    "tokens": {
                        "access_token": "a",
                        "refresh_token": "r",
                        "account_id": "acct",
                    }
                }
            )
        )
        credential = ProviderCredential(
            provider="codex_auth",
            credential_type=CredentialType.FILE,
            value=auth_source.read_text(),
            source=str(auth_source),
            destination_key="",
        )
        spec = DockerEnvironmentSpec(
            name="docker-test",
            docker=DockerConfig(image="pi-test-image"),
        )
        runtime = FakeRuntime()
        session = FakeSession(runtime=runtime, working_dir=tmp_path, spec=spec)

        agent = PiAgent(
            problem_name="test-problem",
            verbose=False,
            image="pi-test-image",
            cost_limits=mock_cost_limits,
            pricing=mock_pricing,
            credential=credential,
            binary="pi",
            provider="openai-codex",
            model="gpt-5.2-codex",
            timeout=None,
            thinking=None,
            extra_args=[],
            env={},
            models_json=None,
        )

        agent.setup(cast("Session", session))
        assert session.last_spawn_env_vars is not None
        assert session.last_spawn_env_vars["HOME"] == HOME_PATH
        assert (
            session.last_spawn_env_vars["PI_CODING_AGENT_DIR"]
            == f"{HOME_PATH}/.pi/agent"
        )
        assert session.last_spawn_mounts is not None
        assert any(
            isinstance(value, dict)
            and value.get("bind") == f"{HOME_PATH}/.pi/agent"
            for value in session.last_spawn_mounts.values()
        )
        assert agent._pi_auth_dir is not None
        converted_path = agent._pi_auth_dir / "auth.json"
        assert converted_path.exists()
        converted = json.loads(converted_path.read_text())
        assert "openai-codex" in converted
        assert converted["openai-codex"]["access"] == "a"
        assert auth_source.read_text() != converted_path.read_text()

    def test_setup_with_invalid_codex_auth_raises_clear_error(
        self,
        tmp_path: Path,
        mock_cost_limits: AgentCostLimits,
        mock_pricing: APIPricing,
    ) -> None:
        credential = ProviderCredential(
            provider="codex_auth",
            credential_type=CredentialType.FILE,
            value="{invalid-json",
            source=str(tmp_path / "missing.json"),
            destination_key="",
        )
        runtime = FakeRuntime()
        session = FakeSession(runtime=runtime, working_dir=tmp_path)

        agent = PiAgent(
            problem_name="test-problem",
            verbose=False,
            image="pi-test-image",
            cost_limits=mock_cost_limits,
            pricing=mock_pricing,
            credential=credential,
            binary="pi",
            provider="openai-codex",
            model="gpt-5.2-codex",
            timeout=None,
            thinking=None,
            extra_args=[],
            env={},
            models_json=None,
        )

        with pytest.raises(AgentError, match="Failed to parse Codex auth JSON"):
            agent.setup(cast("Session", session))

    def test_parse_line_message_end_usage(
        self, mock_pricing: APIPricing
    ) -> None:
        line = json.dumps(
            {
                "type": "message_end",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Done"}],
                    "usage": {
                        "input": 100,
                        "output": 10,
                        "cacheRead": 20,
                        "cacheWrite": 5,
                        "cost": {"total": 0.0123},
                    },
                },
            }
        )
        cost, tokens, payload = PiAgent.parse_line(line, pricing=mock_pricing)
        assert cost == pytest.approx(0.0123)
        assert tokens is not None
        assert tokens.input == 120
        assert tokens.output == 10
        assert tokens.cache_read == 20
        assert tokens.cache_write == 5
        assert payload is not None

    def test_parse_line_prices_usage_without_reported_cost(
        self,
        mock_pricing: APIPricing,
    ) -> None:
        line = json.dumps(
            {
                "type": "message_end",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Done"}],
                    "usage": {
                        "input": 1_000_000,
                        "output": 1_000_000,
                        "cacheRead": 1_000_000,
                        "cacheWrite": 1_000_000,
                    },
                },
            }
        )

        cost, tokens, payload = PiAgent.parse_line(line, pricing=mock_pricing)

        assert cost == pytest.approx(1.38)
        assert tokens is not None
        assert tokens.input == 2_000_000
        assert tokens.output == 1_000_000
        assert tokens.cache_read == 1_000_000
        assert tokens.cache_write == 1_000_000
        assert payload is not None

    def test_parse_line_ignores_non_message_end(
        self, mock_pricing: APIPricing
    ) -> None:
        line = json.dumps({"type": "tool_execution_start", "toolName": "bash"})
        cost, tokens, payload = PiAgent.parse_line(line, pricing=mock_pricing)
        assert cost is None
        assert tokens is None
        assert payload is not None

    def test_run_prices_pi_usage_when_reported_cost_is_absent(
        self,
        tmp_path: Path,
        mock_cost_limits: AgentCostLimits,
        mock_pricing: APIPricing,
    ) -> None:
        runtime = FakeRuntime()
        usage_line = json.dumps(
            {
                "type": "message_end",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Done"}],
                    "usage": {
                        "input": 1_000_000,
                        "output": 1_000_000,
                        "cacheRead": 1_000_000,
                        "cacheWrite": 1_000_000,
                    },
                },
            }
        )
        runtime.events = [
            RuntimeEvent(kind="stdout", text=f"{usage_line}\n"),
            RuntimeEvent(
                kind="finished",
                result=RuntimeResult(
                    exit_code=0,
                    stdout=f"{usage_line}\n",
                    stderr="",
                    setup_stdout="",
                    setup_stderr="",
                    elapsed=0.1,
                    timed_out=False,
                ),
            ),
        ]
        spec = DockerEnvironmentSpec(
            name="docker-test",
            docker=DockerConfig(image="pi-test-image"),
        )
        session = FakeSession(runtime=runtime, working_dir=tmp_path, spec=spec)
        agent = PiAgent(
            problem_name="test-problem",
            verbose=False,
            image="pi-test-image",
            cost_limits=mock_cost_limits,
            pricing=mock_pricing,
            credential=None,
            binary="pi",
            provider="openai",
            model="gpt-5.2-codex",
            timeout=None,
            thinking=None,
            extra_args=[],
            env={},
            models_json=None,
        )

        agent.setup(cast("Session", session))
        agent.run("do something")

        assert agent.usage.cost == pytest.approx(1.38)
        assert agent.usage.net_tokens.input == 2_000_000
        assert agent.usage.net_tokens.output == 1_000_000
        assert agent.usage.net_tokens.cache_read == 1_000_000
        assert agent.usage.net_tokens.cache_write == 1_000_000

    def test_run_raises_when_pi_returns_message_error_with_zero_exit(
        self,
        tmp_path: Path,
        mock_cost_limits: AgentCostLimits,
        mock_pricing: APIPricing,
    ) -> None:
        runtime = FakeRuntime()
        error_line = json.dumps(
            {
                "type": "message_end",
                "message": {
                    "role": "assistant",
                    "content": [],
                    "stopReason": "error",
                    "errorMessage": "400 Reasoning is mandatory for this endpoint and cannot be disabled.",
                    "usage": {
                        "input": 0,
                        "output": 0,
                        "cacheRead": 0,
                        "cacheWrite": 0,
                    },
                },
            }
        )
        runtime.events = [
            RuntimeEvent(kind="stdout", text=f"{error_line}\n"),
            RuntimeEvent(
                kind="finished",
                result=RuntimeResult(
                    exit_code=0,
                    stdout=f"{error_line}\n",
                    stderr="",
                    setup_stdout="",
                    setup_stderr="",
                    elapsed=0.1,
                    timed_out=False,
                ),
            ),
        ]
        spec = DockerEnvironmentSpec(
            name="docker-test",
            docker=DockerConfig(image="pi-test-image"),
        )
        session = FakeSession(runtime=runtime, working_dir=tmp_path, spec=spec)
        agent = PiAgent(
            problem_name="test-problem",
            verbose=False,
            image="pi-test-image",
            cost_limits=mock_cost_limits,
            pricing=mock_pricing,
            credential=None,
            binary="pi",
            provider="openrouter",
            model="minimax/minimax-m2.7",
            timeout=None,
            thinking=None,
            extra_args=[],
            env={},
            models_json=None,
        )

        agent.setup(cast("Session", session))
        with pytest.raises(AgentError, match="Reasoning is mandatory"):
            agent.run("do something")

    def test_save_artifacts_filters_streaming_deltas(
        self,
        tmp_path: Path,
        mock_cost_limits: AgentCostLimits,
        mock_pricing: APIPricing,
    ) -> None:
        runtime = FakeRuntime()
        session_event = json.dumps(
            {"type": "session", "id": "session-1", "cwd": "/workspace"}
        )
        message_update = json.dumps(
            {"type": "message_update", "delta": {"text": "partial"}}
        )
        tool_start = json.dumps(
            {
                "type": "tool_execution_start",
                "toolCallId": "call-1",
                "toolName": "bash",
                "args": {"command": "echo hi"},
            }
        )
        message_end = json.dumps(
            {
                "type": "message_end",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Done"}],
                    "usage": {"input": 1, "output": 1},
                },
            }
        )
        stdout = (
            f"{session_event}\n{message_update}\n{tool_start}\n{message_end}\n"
        )
        runtime.events = [
            RuntimeEvent(kind="stdout", text=stdout),
            RuntimeEvent(
                kind="finished",
                result=RuntimeResult(
                    exit_code=0,
                    stdout=stdout,
                    stderr="warning\n",
                    setup_stdout="",
                    setup_stderr="",
                    elapsed=0.1,
                    timed_out=False,
                ),
            ),
        ]
        spec = DockerEnvironmentSpec(
            name="docker-test",
            docker=DockerConfig(image="pi-test-image"),
        )
        session = FakeSession(runtime=runtime, working_dir=tmp_path, spec=spec)
        agent = PiAgent(
            problem_name="test-problem",
            verbose=False,
            image="pi-test-image",
            cost_limits=mock_cost_limits,
            pricing=mock_pricing,
            credential=None,
            binary="pi",
            provider="openai",
            model="gpt-5.2-codex",
            timeout=None,
            thinking=None,
            extra_args=[],
            env={},
            models_json=None,
        )

        agent.setup(cast("Session", session))
        agent.run("do something")
        output_dir = tmp_path / "artifacts"
        agent.save_artifacts(output_dir)

        saved_payloads = [
            json.loads(line)
            for line in (output_dir / "stdout.jsonl").read_text().splitlines()
        ]
        assert [payload["type"] for payload in saved_payloads] == [
            "session",
            "tool_execution_start",
            "message_end",
        ]
        assert not (output_dir / "messages.jsonl").exists()
        assert (output_dir / "stderr.log").read_text() == "warning\n"
        assert (output_dir / "prompt.txt").read_text() == "do something"

    def test_run_raises_when_stream_ends_without_final_message(
        self,
        tmp_path: Path,
        mock_cost_limits: AgentCostLimits,
        mock_pricing: APIPricing,
    ) -> None:
        """A clean exit with no assistant message must fail, not hang."""
        runtime = FakeRuntime()
        runtime.events = [
            RuntimeEvent(
                kind="finished",
                result=RuntimeResult(
                    exit_code=0,
                    stdout="",
                    stderr="",
                    setup_stdout="",
                    setup_stderr="",
                    elapsed=0.1,
                    timed_out=False,
                ),
            ),
        ]
        spec = DockerEnvironmentSpec(
            name="docker-test",
            docker=DockerConfig(image="pi-test-image"),
        )
        session = FakeSession(runtime=runtime, working_dir=tmp_path, spec=spec)
        agent = PiAgent(
            problem_name="test-problem",
            verbose=False,
            image="pi-test-image",
            cost_limits=mock_cost_limits,
            pricing=mock_pricing,
            credential=None,
            binary="pi",
            provider="openrouter",
            model="moonshotai/kimi-k3",
            timeout=7200,
            thinking="high",
            extra_args=[],
            env={},
            models_json=None,
        )

        agent.setup(cast("Session", session))
        with pytest.raises(AgentError, match="without emitting a final"):
            run_with_deadline(lambda: agent.run("do something"), timeout=10.0)

    def test_run_allows_sigterm_exit_to_preserve_partial_solution(
        self,
        tmp_path: Path,
        mock_cost_limits: AgentCostLimits,
        mock_pricing: APIPricing,
    ) -> None:
        runtime = FakeRuntime()
        runtime.events = [
            RuntimeEvent(
                kind="finished",
                result=RuntimeResult(
                    exit_code=143,
                    stdout="",
                    stderr="",
                    setup_stdout="",
                    setup_stderr="",
                    elapsed=0.1,
                    timed_out=False,
                ),
            ),
        ]
        spec = DockerEnvironmentSpec(
            name="docker-test",
            docker=DockerConfig(image="pi-test-image"),
        )
        session = FakeSession(runtime=runtime, working_dir=tmp_path, spec=spec)
        agent = PiAgent(
            problem_name="test-problem",
            verbose=False,
            image="pi-test-image",
            cost_limits=mock_cost_limits,
            pricing=mock_pricing,
            credential=None,
            binary="pi",
            provider="openrouter",
            model="moonshotai/kimi-k2.5",
            timeout=None,
            thinking="high",
            extra_args=[],
            env={},
            models_json=None,
        )

        agent.setup(cast("Session", session))
        agent.run("build a datagate.py server")

        assert agent._last_command is not None
        assert agent._last_command.result is not None
        assert agent._last_command.result.exit_code == 143


class TestPiAgentRegistration:
    """Tests for agent registration."""

    def test_agent_is_registered(self) -> None:
        from slop_code.agent_runner.registry import available_agent_types
        from slop_code.agent_runner.registry import get_agent_cls

        assert "pi" in available_agent_types()
        assert get_agent_cls("pi") is PiAgent
