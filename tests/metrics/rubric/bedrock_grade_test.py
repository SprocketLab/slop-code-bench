from __future__ import annotations

import io
import json
from types import SimpleNamespace

import pytest

from slop_code.common.llms import APIPricing
from slop_code.metrics.rubric import bedrock_grade
from slop_code.metrics.rubric.bedrock_grade import _build_messages_for_bedrock
from slop_code.metrics.rubric.bedrock_grade import _normalize_bedrock_response


def test_build_messages_adds_cache_control():
    """Prompt prefix should include cache control for Bedrock caching."""
    messages = _build_messages_for_bedrock("prefix", "criteria")
    prefix_block = messages[0]["content"][0]
    assert prefix_block["cache_control"]["type"] == "ephemeral"


def test_normalize_bedrock_response_adds_cost(monkeypatch: pytest.MonkeyPatch):
    """Cost should be derived from the model catalog pricing."""

    def _mock_get(model: str):
        return SimpleNamespace(pricing=APIPricing(input=1, output=2))

    monkeypatch.setattr(
        bedrock_grade.ModelCatalog, "get", staticmethod(_mock_get)
    )

    response = {
        "content": [{"type": "text", "text": "payload"}],
        "usage": {"input_tokens": 1000, "output_tokens": 500},
    }
    normalized = _normalize_bedrock_response(response, "bedrock-model")

    usage = normalized["usage"]
    assert usage["prompt_tokens"] == 1000
    assert usage["completion_tokens"] == 500
    assert usage["cache_read_input_tokens"] == 0
    assert usage["cache_creation_input_tokens"] == 0
    assert usage["cost"] == pytest.approx(0.002)


@pytest.mark.asyncio
async def test_grade_file_includes_temperature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensure temperature is passed through to Bedrock payload."""

    def _mock_get(model: str):
        return SimpleNamespace(pricing=APIPricing(input=1, output=2))

    monkeypatch.setattr(
        bedrock_grade.ModelCatalog, "get", staticmethod(_mock_get)
    )

    response_body = {
        "content": [{"type": "text", "text": "[]"}],
        "usage": {"input_tokens": 0, "output_tokens": 0},
    }
    captured_request: dict[str, object] = {}

    class FakeClient:
        def invoke_model(self, *, modelId, body, contentType, accept):
            del contentType, accept, modelId  # Unused in test
            captured_request.update(json.loads(body))
            return {"body": io.BytesIO(json.dumps(response_body).encode())}

    await bedrock_grade.grade_file_async(
        prompt_prefix="prefix",
        criteria_text="criteria",
        file_name="app.py",
        model="anthropic.claude-3-5-sonnet-20241022-v2:0",
        temperature=0.12,
        client=FakeClient(),
    )

    assert captured_request["temperature"] == pytest.approx(0.12)
