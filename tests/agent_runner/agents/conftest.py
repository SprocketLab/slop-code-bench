"""Shared fixtures for agent tests."""

from __future__ import annotations

import pytest

from slop_code.common.llms import APIPricing


@pytest.fixture
def mock_catalog_miniswe(monkeypatch):
    """Mock the model catalog with a model that has mini_swe settings.

    This fixture is automatically used by tests that need MiniSWE config
    to resolve model from catalog.
    """
    from slop_code.common.llms import ModelCatalog
    from slop_code.common.llms import ModelDefinition

    mock_model = ModelDefinition(
        internal_name="test-model",
        provider="anthropic",
        pricing=APIPricing(
            input=3, output=15, cache_read=0.30, cache_write=3.75
        ),
        agent_specific={
            "mini_swe": {
                "model_name": "claude-3-5-sonnet-20241022",
                "model_class": "litellm",
            }
        },
    )

    def mock_get(model_name):
        if model_name == "test-model":
            return mock_model
        return None

    monkeypatch.setattr(ModelCatalog, "get", staticmethod(mock_get))
    return mock_model
