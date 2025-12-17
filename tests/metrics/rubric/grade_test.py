"""Tests for rubric grading helpers."""

from __future__ import annotations

from unittest.mock import MagicMock

import httpx
import pytest

from slop_code.metrics.rubric.llm_grade import OPENROUTER_API_URL
from slop_code.metrics.rubric.llm_grade import _parse_json_text
from slop_code.metrics.rubric.llm_grade import grade_file_async


@pytest.fixture(autouse=True)
def mock_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure an API key is available for tests."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")


@pytest.fixture
def mock_openrouter_response():
    """Create a mock OpenRouter API response."""

    def _make_response(
        content: str, prompt_tokens: int = 100, completion_tokens: int = 50
    ) -> httpx.Response:
        request = httpx.Request("POST", OPENROUTER_API_URL)
        return httpx.Response(
            200,
            request=request,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": content,
                        }
                    }
                ],
                "usage": {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                },
            },
        )

    return _make_response


@pytest.mark.asyncio
async def test_grade_file_grades_single_file(
    mock_openrouter_response,
) -> None:
    """Ensure grade_file_async calls API and parses the returned JSON."""
    # Use multi-file format as that's what the implementation expects
    response_data = """=== FILE: app.py ===
```json
[
  {
    "criteria": "test_criteria",
    "start": 1,
    "explanation": "test issue"
  }
]
```
=== END FILE ==="""
    mock_response = mock_openrouter_response(response_data)

    mock_client = MagicMock(spec=httpx.AsyncClient)
    mock_client.post.return_value = mock_response

    grades, raw = await grade_file_async(
        prompt_prefix="test prefix content",
        criteria_text="test criteria text",
        file_name="app.py",
        model="anthropic/claude-3.5-sonnet",
        client=mock_client,
    )

    mock_client.post.assert_called_once()
    call_kwargs = mock_client.post.call_args.kwargs

    assert call_kwargs["json"]["model"] == "anthropic/claude-3.5-sonnet"
    messages = call_kwargs["json"]["messages"]
    assert messages[0]["role"] == "system"
    assert call_kwargs["json"]["temperature"] == 0.0

    # Content is a list of dicts with cache control
    system_content = messages[0]["content"]
    assert isinstance(system_content, list)
    system_text = system_content[0]["text"]
    assert "expert code reviewer" in system_text

    assert messages[1]["role"] == "user"
    user_content = messages[1]["content"]
    assert isinstance(user_content, list)
    user_text = "".join(
        block["text"] for block in user_content if "text" in block
    )
    assert "test prefix content" in user_text
    assert "test criteria text" in user_text
    assert call_kwargs["headers"]["Authorization"] == "Bearer test-key"

    assert len(grades) == 1
    assert grades[0]["criteria"] == "test_criteria"
    assert grades[0]["file_name"] == "app.py"
    assert grades[0]["start"] == 1

    assert "usage" in raw
    assert raw["usage"]["prompt_tokens"] == 100
    assert raw["usage"]["completion_tokens"] == 50


@pytest.mark.asyncio
async def test_grade_file_respects_temperature(
    mock_openrouter_response,
) -> None:
    """Ensure temperature is forwarded to the API payload."""
    mock_response = mock_openrouter_response("[]")
    mock_client = MagicMock(spec=httpx.AsyncClient)
    mock_client.post.return_value = mock_response

    await grade_file_async(
        prompt_prefix="test prefix content",
        criteria_text="test criteria text",
        file_name="app.py",
        model="anthropic/claude-3.5-sonnet",
        client=mock_client,
        temperature=0.25,
    )

    call_kwargs = mock_client.post.call_args.kwargs
    assert call_kwargs["json"]["temperature"] == pytest.approx(0.25)


@pytest.mark.asyncio
async def test_grade_file_with_thinking(
    mock_openrouter_response,
) -> None:
    """Ensure reasoning parameter is passed when thinking_tokens is set."""
    mock_response = mock_openrouter_response("[]")
    mock_client = MagicMock(spec=httpx.AsyncClient)
    mock_client.post.return_value = mock_response

    await grade_file_async(
        prompt_prefix="test prefix",
        criteria_text="test criteria",
        file_name="app.py",
        model="anthropic/claude-3.5-sonnet",
        thinking_tokens=10240,
        client=mock_client,
    )

    call_kwargs = mock_client.post.call_args.kwargs
    assert "reasoning" in call_kwargs["json"]
    assert call_kwargs["json"]["reasoning"]["enabled"] is True
    assert call_kwargs["json"]["reasoning"]["max_tokens"] == 10240


@pytest.mark.asyncio
async def test_grade_file_no_thinking_when_none(
    mock_openrouter_response,
) -> None:
    """Ensure reasoning is disabled when thinking_tokens is None."""
    mock_response = mock_openrouter_response("[]")
    mock_client = MagicMock(spec=httpx.AsyncClient)
    mock_client.post.return_value = mock_response

    await grade_file_async(
        prompt_prefix="test prefix",
        criteria_text="test criteria",
        file_name="app.py",
        model="anthropic/claude-3.5-sonnet",
        thinking_tokens=None,
        client=mock_client,
    )

    call_kwargs = mock_client.post.call_args.kwargs
    assert "reasoning" in call_kwargs["json"]
    assert call_kwargs["json"]["reasoning"]["enabled"] is False


def test_parse_json_text_parses_fenced_json() -> None:
    """Parse JSON from fenced code block."""
    text = '```json\n{"score": 2}\n```'

    parsed = _parse_json_text(text)

    assert parsed == {"score": 2}


def test_parse_json_text_parses_raw_json() -> None:
    """Parse raw JSON without fencing."""
    text = '{"score": 3}'

    parsed = _parse_json_text(text)

    assert parsed == {"score": 3}


def test_parse_json_text_parses_list() -> None:
    """Parse JSON list."""
    text = '[{"a": 1}, {"b": 2}]'

    parsed = _parse_json_text(text)

    assert parsed == [{"a": 1}, {"b": 2}]


def test_parse_json_text_returns_none_on_invalid() -> None:
    """Return None when no valid JSON found."""
    text = "not valid json at all"

    result = _parse_json_text(text)

    assert result is None


@pytest.mark.asyncio
async def test_grade_file_retries_on_rate_limit(
    mock_openrouter_response,
) -> None:
    """Ensure grade_file_async retries on rate limit errors."""
    mock_response = mock_openrouter_response("[]")
    mock_client = MagicMock(spec=httpx.AsyncClient)

    call_count = 0

    request = httpx.Request("POST", OPENROUTER_API_URL)
    rate_limit_response = httpx.Response(
        429, request=request, json={"error": "Rate limit exceeded"}
    )
    rate_limit_error = httpx.HTTPStatusError(
        "Rate limit exceeded",
        request=request,
        response=rate_limit_response,
    )

    def mock_post(*_args, **_kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise rate_limit_error
        return mock_response

    mock_client.post.side_effect = mock_post

    grades, _ = await grade_file_async(
        prompt_prefix="test prefix",
        criteria_text="test criteria",
        file_name="app.py",
        model="anthropic/claude-3.5-sonnet",
        client=mock_client,
    )

    assert call_count == 2
    assert grades == []


@pytest.mark.asyncio
async def test_grade_file_uses_caching(
    mock_openrouter_response,
) -> None:
    """Ensure caching is enabled for Anthropic models."""
    mock_response = mock_openrouter_response("[]")
    mock_client = MagicMock(spec=httpx.AsyncClient)
    mock_client.post.return_value = mock_response

    await grade_file_async(
        prompt_prefix="test prefix",
        criteria_text="test criteria",
        file_name="app.py",
        model="anthropic/claude-3.5-sonnet",
        client=mock_client,
    )

    call_kwargs = mock_client.post.call_args.kwargs
    payload = call_kwargs["json"]

    # Content should be list of dicts with cache control
    messages = payload["messages"]
    assert isinstance(messages[0]["content"], list)
    assert messages[0]["content"][0]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in messages[1]["content"][1]

    # Should have usage for caching
    assert "usage" in payload
    assert payload["usage"] == {"include": True}


@pytest.mark.asyncio
async def test_grade_file_uses_caching_openai(
    mock_openrouter_response,
) -> None:
    """Ensure caching is enabled for OpenAI models via OpenRouter."""
    mock_response = mock_openrouter_response("[]")
    mock_client = MagicMock(spec=httpx.AsyncClient)
    mock_client.post.return_value = mock_response

    await grade_file_async(
        prompt_prefix="test prefix",
        criteria_text="test criteria",
        file_name="app.py",
        model="openai/gpt-4.1",
        client=mock_client,
    )

    call_kwargs = mock_client.post.call_args.kwargs
    payload = call_kwargs["json"]
    messages = payload["messages"]

    assert messages[0]["role"] == "system"
    system_block = messages[0]["content"][0]
    assert system_block["type"] == "input_text"
    assert system_block["input_text"]["cache_control"] == {"type": "ephemeral"}

    # Prompt prefix should be cached, criteria should not
    user_blocks = messages[1]["content"]
    assert user_blocks[0]["type"] == "input_text"
    assert user_blocks[0]["input_text"]["cache_control"] == {
        "type": "ephemeral"
    }
    assert "cache_control" not in user_blocks[1]["input_text"]

    assert payload["usage"] == {"include": True}
