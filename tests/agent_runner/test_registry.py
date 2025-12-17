from __future__ import annotations

from typing import Literal

import pytest
from pydantic import Field

from slop_code.agent_runner.agent import AgentConfigBase
from slop_code.agent_runner.registry import build_agent_config


@pytest.fixture()
def isolated_registry(monkeypatch):
    from slop_code.agent_runner import registry as registry_module

    monkeypatch.setattr(registry_module, "_CONFIG_REGISTRY", {})
    return registry_module


def _cost_limits() -> dict[str, float]:
    return {"cost_limit": 1.0, "net_cost_limit": 2.0, "step_limit": 0}


def test_build_agent_config_uses_registry(isolated_registry):
    class DummyAgentConfig(AgentConfigBase):
        type: Literal["dummy"] = "dummy"
        extra: str

        def initialize_agent(self, problem_name: str, verbose: bool, image: str):
            raise NotImplementedError

    config = build_agent_config(
        {"type": "dummy", "extra": "value", "cost_limits": _cost_limits()}
    )
    assert isinstance(config, DummyAgentConfig)
    assert config.extra == "value"


def test_duplicate_agent_type_registration_errors(isolated_registry):
    class FirstConfig(AgentConfigBase):
        type: Literal["dup"] = "dup"

        def initialize_agent(self, problem_name: str, verbose: bool, image: str):
            raise NotImplementedError

    with pytest.raises(ValueError, match="already registered"):
        class SecondConfig(AgentConfigBase):
            type: Literal["dup"] = "dup"

            def initialize_agent(self, problem_name: str, verbose: bool, image: str):
                raise NotImplementedError


def test_agent_type_validator_requires_match(isolated_registry):
    class SampleConfig(AgentConfigBase):
        agent_type = "sample"
        type: str = Field(default="sample", frozen=True)

        def initialize_agent(self, problem_name: str, verbose: bool, image: str):
            raise NotImplementedError

    with pytest.raises(ValueError, match="Agent type mismatch"):
        SampleConfig.model_validate(
            {"type": "other", "cost_limits": _cost_limits()}
        )
