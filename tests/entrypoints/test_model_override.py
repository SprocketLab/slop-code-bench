import pytest

from slop_code.entrypoints import utils


class TestParseModelOverride:
    def test_parses_provider_and_alias(self):
        override = utils.parse_model_override("anthropic/claude-sonnet-4.5")

        assert override.provider == "anthropic"
        # name is the registered name (config filename)
        assert override.name == "sonnet-4.5"
        # internal_name is the API model identifier
        assert override.internal_name == "claude-sonnet-4-5-20250929"
        # model_def contains the full model definition
        assert override.model_def is not None
        assert override.model_def.name == "sonnet-4.5"

    def test_raises_without_provider(self):
        """Provider is now required in {provider}/{model} format."""
        with pytest.raises(ValueError, match="'{provider}/{model}' format"):
            utils.parse_model_override("gpt-5")

    def test_raises_on_unknown_provider(self):
        with pytest.raises(ValueError):
            utils.parse_model_override("unknown-provider/gpt-5")


def test_parse_model_override_raises_on_empty_provider():
    """Empty provider in /model format should raise."""
    with pytest.raises(ValueError, match="Provider cannot be empty"):
        utils.parse_model_override("/gpt-5")


def test_parse_model_override_raises_on_empty_model():
    """Empty model in provider/ format should raise."""
    with pytest.raises(ValueError, match="Model name cannot be empty"):
        utils.parse_model_override("openai/")


def test_parse_model_override_raises_on_unknown_model():
    """Unknown model name should raise with helpful error."""
    with pytest.raises(ValueError, match="Unknown model 'nonexistent-model'"):
        utils.parse_model_override("anthropic/nonexistent-model")
