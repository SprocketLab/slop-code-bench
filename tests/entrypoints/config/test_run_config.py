"""Tests for the RunConfig Pydantic models."""

from __future__ import annotations

import pytest

from slop_code.entrypoints.config.run_config import ModelConfig
from slop_code.entrypoints.config.run_config import RunConfig
from slop_code.entrypoints.config.run_config import ThinkingConfig
from slop_code.evaluation import PassPolicy


class TestModelConfig:
    def test_valid_model_config(self):
        config = ModelConfig(provider="anthropic", name="sonnet-4.5")
        assert config.provider == "anthropic"
        assert config.name == "sonnet-4.5"

    def test_rejects_extra_fields(self):
        with pytest.raises(ValueError, match="extra"):
            ModelConfig(provider="anthropic", name="sonnet-4.5", extra="field")


class TestThinkingConfig:
    def test_preset_only(self):
        config = ThinkingConfig(preset="medium")
        assert config.preset == "medium"
        assert config.max_tokens is None

    def test_max_tokens_only(self):
        config = ThinkingConfig(max_tokens=10000)
        assert config.preset is None
        assert config.max_tokens == 10000

    def test_mutual_exclusion(self):
        with pytest.raises(ValueError, match="Cannot specify both"):
            ThinkingConfig(preset="medium", max_tokens=10000)

    def test_empty_is_valid(self):
        config = ThinkingConfig()
        assert config.preset is None
        assert config.max_tokens is None


class TestRunConfig:
    def test_default_values(self):
        config = RunConfig()
        assert config.agent == "claude_code-2.0.51"
        assert config.environment == "docker-python3.12-uv"
        assert config.prompt == "just-solve"
        assert config.model.provider == "anthropic"
        assert config.model.name == "sonnet-4.5"
        assert config.thinking == "none"
        assert config.pass_policy == PassPolicy.ANY
        assert "${model.name}" in config.output_path
        assert "${now:" in config.output_path

    def test_custom_values(self):
        config = RunConfig(
            agent="./custom_agent.yaml",
            environment="local-py",
            prompt="best_practice",
            model=ModelConfig(provider="openai", name="gpt-4.1"),
            thinking="high",
            pass_policy=PassPolicy.ALL_CASES,
            output_path="custom/path",
        )
        assert config.agent == "./custom_agent.yaml"
        assert config.environment == "local-py"
        assert config.prompt == "best_practice"
        assert config.model.provider == "openai"
        assert config.model.name == "gpt-4.1"
        assert config.thinking == "high"
        assert config.pass_policy == PassPolicy.ALL_CASES
        assert config.output_path == "custom/path"

    def test_inline_agent_config(self):
        config = RunConfig(
            agent={"type": "claude_code", "version": "2.0.51"},
        )
        assert isinstance(config.agent, dict)
        assert config.agent["type"] == "claude_code"

    def test_thinking_as_config_object(self):
        config = RunConfig(thinking=ThinkingConfig(max_tokens=5000))
        assert isinstance(config.thinking, ThinkingConfig)
        assert config.thinking.max_tokens == 5000

    def test_get_thinking_preset_with_string(self):
        config = RunConfig(thinking="medium")
        assert config.get_thinking_preset() == "medium"
        assert config.get_thinking_max_tokens() is None

    def test_get_thinking_preset_with_config(self):
        config = RunConfig(thinking=ThinkingConfig(preset="high"))
        assert config.get_thinking_preset() == "high"
        assert config.get_thinking_max_tokens() is None

    def test_get_thinking_max_tokens_with_config(self):
        config = RunConfig(thinking=ThinkingConfig(max_tokens=8000))
        assert config.get_thinking_preset() is None
        assert config.get_thinking_max_tokens() == 8000

    def test_valid_thinking_presets(self):
        for preset in ["none", "disabled", "low", "medium", "high"]:
            config = RunConfig(thinking=preset)
            assert config.thinking == preset

    def test_invalid_thinking_preset(self):
        # Pydantic should reject invalid literal values
        with pytest.raises(ValueError):
            RunConfig(thinking="invalid_preset")

    def test_valid_pass_policies(self):
        for policy in PassPolicy:
            config = RunConfig(pass_policy=policy)
            assert config.pass_policy == policy

    def test_rejects_extra_fields(self):
        with pytest.raises(ValueError, match="extra"):
            RunConfig(extra_field="not_allowed")
