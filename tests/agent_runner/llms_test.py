"""Tests for the llms module (ModelCatalog and ModelDefinition)."""

from __future__ import annotations

from pathlib import Path

import pytest

from slop_code.common.llms import APIPricing
from slop_code.common.llms import ModelCatalog
from slop_code.common.llms import ModelDefinition


class TestModelDefinition:
    """Tests for ModelDefinition model."""

    def test_basic_definition(self):
        """Test creating a basic model definition."""
        model = ModelDefinition(
            internal_name="test-model",
            provider="anthropic",
            pricing=APIPricing(input=3, output=15),
        )
        assert model.internal_name == "test-model"
        assert model.provider == "anthropic"
        assert model.pricing.input == 3
        assert model.pricing.output == 15
        assert model.aliases == []
        assert model.agent_specific == {}

    def test_definition_with_aliases(self):
        """Test creating a model definition with aliases."""
        model = ModelDefinition(
            internal_name="claude-sonnet-4-5-20250929",
            provider="anthropic",
            pricing=APIPricing(input=3, output=15),
            aliases=["sonnet-4.5", "claude-sonnet-4.5"],
        )
        assert model.aliases == ["sonnet-4.5", "claude-sonnet-4.5"]

    def test_definition_with_agent_specific(self):
        """Test creating a model definition with agent-specific settings."""
        model = ModelDefinition(
            internal_name="test-model",
            provider="zhipu",
            pricing=APIPricing(input=0.6, output=2.2),
            agent_specific={
                "mini_swe": {
                    "model_name": "openai/test",
                    "api_base": "https://example.com",
                },
                "claude_code": {
                    "base_url": "https://proxy.example.com",
                },
            },
        )
        assert "mini_swe" in model.agent_specific
        assert "claude_code" in model.agent_specific

    def test_get_agent_settings_returns_settings(self):
        """Test get_agent_settings returns correct settings."""
        model = ModelDefinition(
            internal_name="test-model",
            provider="zhipu",
            pricing=APIPricing(input=0.6, output=2.2),
            agent_specific={
                "mini_swe": {
                    "model_name": "openai/test",
                    "api_base": "https://example.com",
                },
            },
        )
        settings = model.get_agent_settings("mini_swe")
        assert settings is not None
        assert settings["model_name"] == "openai/test"
        assert settings["api_base"] == "https://example.com"

    def test_get_agent_settings_returns_none_for_unknown(self):
        """Test get_agent_settings returns None for unknown agent type."""
        model = ModelDefinition(
            internal_name="test-model",
            provider="anthropic",
            pricing=APIPricing(input=3, output=15),
        )
        assert model.get_agent_settings("unknown_agent") is None


class TestModelDefinitionProviderSlugs:
    """Tests for provider_slugs and get_model_slug in ModelDefinition."""

    def test_default_provider_slugs_empty(self):
        """Test that provider_slugs defaults to empty dict."""
        model = ModelDefinition(
            internal_name="test-model",
            provider="anthropic",
            pricing=APIPricing(input=3, output=15),
        )
        assert model.provider_slugs == {}

    def test_get_model_slug_returns_internal_name_by_default(self):
        """Test get_model_slug returns internal_name when no provider specified."""
        model = ModelDefinition(
            internal_name="test-model",
            provider="anthropic",
            pricing=APIPricing(input=3, output=15),
        )
        assert model.get_model_slug() == "test-model"

    def test_get_model_slug_returns_internal_name_for_unknown_provider(self):
        """Test get_model_slug falls back to internal_name for unknown provider."""
        model = ModelDefinition(
            internal_name="test-model",
            provider="anthropic",
            pricing=APIPricing(input=3, output=15),
            provider_slugs={"openrouter": "provider/test-model"},
        )
        assert model.get_model_slug("unknown") == "test-model"

    def test_get_model_slug_returns_provider_specific_slug(self):
        """Test get_model_slug returns provider-specific slug when available."""
        model = ModelDefinition(
            internal_name="glm-4.6",
            provider="zhipu",
            pricing=APIPricing(input=0.6, output=2.2),
            provider_slugs={"openrouter": "z-ai/glm-4.6"},
        )
        assert model.get_model_slug("openrouter") == "z-ai/glm-4.6"
        assert model.get_model_slug("zhipu") == "glm-4.6"  # Falls back

    def test_get_model_slug_with_multiple_providers(self):
        """Test get_model_slug with multiple provider mappings."""
        model = ModelDefinition(
            internal_name="base-model",
            provider="default-provider",
            pricing=APIPricing(input=1, output=2),
            provider_slugs={
                "openrouter": "openrouter/model",
                "together": "together/model",
                "fireworks": "accounts/fireworks/models/model",
            },
        )
        assert model.get_model_slug("openrouter") == "openrouter/model"
        assert model.get_model_slug("together") == "together/model"
        assert model.get_model_slug("fireworks") == "accounts/fireworks/models/model"
        assert model.get_model_slug() == "base-model"


class TestModelDefinitionThinking:
    """Tests for thinking configuration in ModelDefinition."""

    def test_thinking_preset_field(self):
        """Test creating model with thinking preset."""
        model = ModelDefinition(
            internal_name="test-model",
            provider="anthropic",
            pricing=APIPricing(input=3, output=15),
            thinking="medium",
        )
        assert model.thinking == "medium"
        assert model.max_thinking_tokens is None

    def test_max_thinking_tokens_field(self):
        """Test creating model with explicit max_thinking_tokens."""
        model = ModelDefinition(
            internal_name="test-model",
            provider="anthropic",
            pricing=APIPricing(input=3, output=15),
            max_thinking_tokens=8000,
        )
        assert model.thinking is None
        assert model.max_thinking_tokens == 8000

    def test_thinking_mutual_exclusion(self):
        """Test that thinking and max_thinking_tokens are mutually exclusive."""
        with pytest.raises(ValueError, match="Cannot specify both"):
            ModelDefinition(
                internal_name="test-model",
                provider="anthropic",
                pricing=APIPricing(input=3, output=15),
                thinking="high",
                max_thinking_tokens=10000,
            )

    def test_get_thinking_config_top_level(self):
        """Test get_thinking_config returns top-level values."""
        model = ModelDefinition(
            internal_name="test-model",
            provider="anthropic",
            pricing=APIPricing(input=3, output=15),
            thinking="low",
        )
        thinking, max_tokens = model.get_thinking_config()
        assert thinking == "low"
        assert max_tokens is None

    def test_get_thinking_config_top_level_max_tokens(self):
        """Test get_thinking_config returns top-level max_thinking_tokens."""
        model = ModelDefinition(
            internal_name="test-model",
            provider="anthropic",
            pricing=APIPricing(input=3, output=15),
            max_thinking_tokens=5000,
        )
        thinking, max_tokens = model.get_thinking_config()
        assert thinking is None
        assert max_tokens == 5000

    def test_get_thinking_config_agent_specific_overrides(self):
        """Test get_thinking_config prefers agent_specific."""
        model = ModelDefinition(
            internal_name="test-model",
            provider="anthropic",
            pricing=APIPricing(input=3, output=15),
            thinking="low",  # Top-level
            agent_specific={
                "claude_code": {"thinking": "high"},  # Agent-specific
            },
        )
        thinking, max_tokens = model.get_thinking_config("claude_code")
        assert thinking == "high"  # Agent-specific wins
        assert max_tokens is None

    def test_get_thinking_config_agent_specific_max_tokens(self):
        """Test get_thinking_config with agent_specific max_thinking_tokens."""
        model = ModelDefinition(
            internal_name="test-model",
            provider="anthropic",
            pricing=APIPricing(input=3, output=15),
            thinking="low",  # Top-level
            agent_specific={
                "claude_code": {"max_thinking_tokens": 20000},
            },
        )
        thinking, max_tokens = model.get_thinking_config("claude_code")
        assert thinking is None
        assert max_tokens == 20000

    def test_get_thinking_config_falls_back_to_top_level(self):
        """Test get_thinking_config falls back when no agent_specific."""
        model = ModelDefinition(
            internal_name="test-model",
            provider="anthropic",
            pricing=APIPricing(input=3, output=15),
            thinking="medium",
        )
        thinking, max_tokens = model.get_thinking_config("claude_code")
        assert thinking == "medium"
        assert max_tokens is None

    def test_get_thinking_config_no_thinking_set(self):
        """Test get_thinking_config when no thinking is configured."""
        model = ModelDefinition(
            internal_name="test-model",
            provider="anthropic",
            pricing=APIPricing(input=3, output=15),
        )
        thinking, max_tokens = model.get_thinking_config("claude_code")
        assert thinking is None
        assert max_tokens is None

    def test_get_thinking_config_other_agent_specific_no_override(self):
        """Test get_thinking_config falls back when agent_specific is for other agent."""
        model = ModelDefinition(
            internal_name="test-model",
            provider="anthropic",
            pricing=APIPricing(input=3, output=15),
            thinking="low",
            agent_specific={
                "other_agent": {"thinking": "high"},  # Different agent
            },
        )
        # Asking for claude_code should fall back to top-level
        thinking, max_tokens = model.get_thinking_config("claude_code")
        assert thinking == "low"  # Top-level fallback
        assert max_tokens is None


class TestModelCatalog:
    """Tests for ModelCatalog class."""

    @pytest.fixture(autouse=True)
    def reset_catalog(self):
        """Reset catalog before each test and restore after."""
        # Save original state
        original_models = ModelCatalog._models.copy()
        original_aliases = ModelCatalog._aliases.copy()
        original_provider_slugs = ModelCatalog._provider_slugs.copy()
        original_loaded = ModelCatalog._loaded

        # Clear for test
        ModelCatalog.clear()

        yield

        # Restore original state
        ModelCatalog._models = original_models
        ModelCatalog._aliases = original_aliases
        ModelCatalog._provider_slugs = original_provider_slugs
        ModelCatalog._loaded = original_loaded

    def test_register_model(self):
        """Test registering a model."""
        model = ModelDefinition(
            internal_name="test-model",
            provider="openai",
            pricing=APIPricing(input=2, output=8),
        )
        ModelCatalog.register(model)

        # Bypass ensure_loaded by accessing _models directly
        # When no config_name is provided, register falls back to internal_name
        assert ModelCatalog._models.get("test-model") is model

    def test_register_model_with_aliases(self):
        """Test that aliases are registered."""
        model = ModelDefinition(
            internal_name="canonical-name",
            provider="anthropic",
            pricing=APIPricing(input=1, output=4),
            aliases=["alias1", "alias2"],
        )
        ModelCatalog.register(model)

        # Bypass ensure_loaded for direct access
        # When no config_name is provided, register falls back to internal_name
        assert ModelCatalog._models.get("canonical-name") is model
        assert ModelCatalog._aliases.get("alias1") == "canonical-name"
        assert ModelCatalog._aliases.get("alias2") == "canonical-name"

    def test_register_model_with_provider_slugs(self):
        """Provider slugs should be indexed for lookup."""
        model = ModelDefinition(
            internal_name="canonical-name",
            provider="anthropic",
            pricing=APIPricing(input=1, output=4),
            provider_slugs={"bedrock": "anthropic.claude-3-5-sonnet-20241022-v2:0"},
        )
        ModelCatalog.register(model)
        assert (
            ModelCatalog._provider_slugs["anthropic.claude-3-5-sonnet-20241022-v2:0"]
            == "canonical-name"
        )

    def test_get_by_internal_name(self):
        """Internal names should resolve to the registered model."""
        model = ModelDefinition(
            internal_name="internal-name",
            provider="openai",
            pricing=APIPricing(input=1, output=2),
        )
        ModelCatalog.register(model, config_name="friendly-name")
        ModelCatalog._loaded = True
        assert ModelCatalog.get("internal-name") is model

    def test_list_models(self):
        """Test listing registered models."""
        model1 = ModelDefinition(
            internal_name="z-model",
            provider="openai",
            pricing=APIPricing(input=1, output=2),
        )
        model2 = ModelDefinition(
            internal_name="a-model",
            provider="anthropic",
            pricing=APIPricing(input=3, output=4),
        )
        ModelCatalog.register(model1)
        ModelCatalog.register(model2)
        # Mark as loaded to skip file loading
        ModelCatalog._loaded = True

        models = ModelCatalog.list_models()
        assert models == ["a-model", "z-model"]  # Sorted

    def test_clear(self):
        """Test clearing the catalog."""
        model = ModelDefinition(
            internal_name="to-clear",
            provider="openai",
            pricing=APIPricing(input=1, output=2),
            aliases=["alias"],
            provider_slugs={"openrouter": "provider/model"},
        )
        ModelCatalog.register(model)
        ModelCatalog._loaded = True

        assert ModelCatalog._models.get("to-clear") is not None
        assert ModelCatalog._aliases.get("alias") is not None
        assert (
            ModelCatalog._provider_slugs.get("provider/model") == "to-clear"
        )

        ModelCatalog.clear()

        assert ModelCatalog._models.get("to-clear") is None
        assert ModelCatalog._aliases.get("alias") is None
        assert ModelCatalog._provider_slugs.get("provider/model") is None
        assert ModelCatalog._loaded is False


class TestModelCatalogYAMLLoading:
    """Tests for YAML-based model loading."""

    @pytest.fixture(autouse=True)
    def reset_catalog(self):
        """Reset catalog before each test and restore after."""
        original_models = ModelCatalog._models.copy()
        original_aliases = ModelCatalog._aliases.copy()
        original_provider_slugs = ModelCatalog._provider_slugs.copy()
        original_loaded = ModelCatalog._loaded

        ModelCatalog.clear()

        yield

        ModelCatalog._models = original_models
        ModelCatalog._aliases = original_aliases
        ModelCatalog._provider_slugs = original_provider_slugs
        ModelCatalog._loaded = original_loaded

    def test_load_from_directory(self, tmp_path: Path):
        """Test loading models from a directory of YAML files."""
        # Create a test YAML file
        model_file = tmp_path / "test-model.yaml"
        model_file.write_text("""
internal_name: test-model-internal
provider: anthropic
pricing:
  input: 3
  output: 15
aliases:
  - test-alias
""")

        ModelCatalog.load_from_directory(tmp_path)

        # The model is registered with the filename (without extension), not internal_name
        assert "test-model" in ModelCatalog._models
        model = ModelCatalog._models["test-model"]
        assert model.name == "test-model"  # Registered name from filename
        assert model.internal_name == "test-model-internal"  # API model name
        assert model.provider == "anthropic"
        assert model.pricing.input == 3
        assert ModelCatalog._aliases.get("test-alias") == "test-model"

    def test_load_from_directory_with_agent_specific(self, tmp_path: Path):
        """Test loading model with agent_specific settings."""
        model_file = tmp_path / "complex-model.yaml"
        model_file.write_text("""
internal_name: complex-model-internal
provider: zhipu
pricing:
  input: 0.6
  output: 2.2
agent_specific:
  mini_swe:
    model_name: openai/complex
    api_base: https://example.com
  claude_code:
    base_url: https://proxy.example.com
""")

        ModelCatalog.load_from_directory(tmp_path)

        # Registered with filename "complex-model"
        model = ModelCatalog._models["complex-model"]
        assert model.get_agent_settings("mini_swe") == {
            "model_name": "openai/complex",
            "api_base": "https://example.com",
        }
        assert model.get_agent_settings("claude_code") == {
            "base_url": "https://proxy.example.com",
        }

    def test_load_from_nonexistent_directory(self, tmp_path: Path):
        """Test loading from non-existent directory doesn't raise."""
        nonexistent = tmp_path / "does_not_exist"
        # Should not raise, just log warning
        ModelCatalog.load_from_directory(nonexistent)
        assert ModelCatalog._models == {}

    def test_ensure_loaded_is_idempotent(self, tmp_path: Path):
        """Test ensure_loaded only loads once."""
        model_file = tmp_path / "model.yaml"
        model_file.write_text("""
internal_name: loaded-once-internal
provider: openai
pricing:
  input: 1
  output: 2
""")

        ModelCatalog.ensure_loaded(tmp_path)
        # Registered with filename "model"
        first_model = ModelCatalog._models.get("model")

        # Modify file after first load
        model_file.write_text("""
internal_name: loaded-once-internal
provider: modified
pricing:
  input: 99
  output: 99
""")

        # Second call should not reload
        ModelCatalog.ensure_loaded(tmp_path)
        second_model = ModelCatalog._models.get("model")

        assert first_model is second_model
        assert second_model.provider == "openai"  # Not modified

    def test_get_triggers_ensure_loaded(self, tmp_path: Path, monkeypatch):
        """Test that get() triggers ensure_loaded()."""
        model_file = tmp_path / "auto-load.yaml"
        model_file.write_text("""
internal_name: auto-loaded-internal
provider: google
pricing:
  input: 1
  output: 2
""")

        # Patch default path
        monkeypatch.setattr(
            "slop_code.common.llms.Path",
            lambda *args: tmp_path if not args else Path(*args),
        )

        # Force ensure_loaded to use our tmp_path
        ModelCatalog.ensure_loaded(tmp_path)

        # Model is registered with filename "auto-load"
        model = ModelCatalog.get("auto-load")
        assert model is not None
        assert model.provider == "google"


class TestYAMLLoadedModels:
    """Tests for models loaded from configs/models/ YAML files."""

    def test_claude_sonnet_loaded(self):
        """Test that Claude Sonnet is loaded from YAML."""
        # Registered name is now the config filename
        model = ModelCatalog.get("sonnet-4.5")
        assert model is not None
        assert model.name == "sonnet-4.5"  # Config filename
        assert model.internal_name == "claude-sonnet-4-5-20250929"  # API model name
        assert model.provider == "anthropic"
        assert model.pricing.input == 3
        assert model.pricing.output == 15

    def test_claude_sonnet_aliases(self):
        """Test that Claude Sonnet aliases work."""
        canonical = ModelCatalog.get("sonnet-4.5")
        by_alias1 = ModelCatalog.get("claude-sonnet-4.5")

        assert canonical is by_alias1

    def test_claude_sonnet_provider_slug(self):
        """Provider slugs should resolve to the canonical model."""
        canonical = ModelCatalog.get("sonnet-4.5")
        by_slug = ModelCatalog.get("anthropic/claude-sonnet-4.5")
        assert canonical is by_slug
        assert ModelCatalog.resolve_canonical("anthropic/claude-sonnet-4.5") == (
            "sonnet-4.5"
        )

    def test_claude_opus_loaded(self):
        """Test that Claude Opus is loaded from YAML."""
        # Registered name is now the config filename
        model = ModelCatalog.get("opus-4.5")
        assert model is not None
        assert model.name == "opus-4.5"  # Config filename
        assert model.internal_name == "claude-opus-4-5-20251101"  # API model name
        assert model.provider == "anthropic"
        assert model.pricing.input == 5
        assert model.pricing.output == 25

    def test_opus_aliases(self):
        """Test that Opus aliases work."""
        by_alias = ModelCatalog.get("claude-opus-4.5")
        assert by_alias is not None
        # name is now the config filename, not internal_name
        assert by_alias.name == "opus-4.5"

    def test_glm_coding_plan_has_agent_specific(self):
        """Test that GLM-4.6-coding-plan has agent_specific settings."""
        model = ModelCatalog.get("glm-4.6-coding-plan")
        assert model is not None

        mini_swe_settings = model.get_agent_settings("mini_swe")
        assert mini_swe_settings is not None
        assert "model_name" in mini_swe_settings

        claude_code_settings = model.get_agent_settings("claude_code")
        assert claude_code_settings is not None
        assert "base_url" in claude_code_settings

    def test_glm_has_provider_slugs(self):
        """Test that GLM-4.6 has provider_slugs for openrouter."""
        model = ModelCatalog.get("glm-4.6")
        assert model is not None

        # Should have openrouter mapping
        assert model.provider_slugs.get("openrouter") == "z-ai/glm-4.6"

        # get_model_slug should return appropriate values
        assert model.get_model_slug("openrouter") == "z-ai/glm-4.6"
        assert model.get_model_slug() == "glm-4.6"
