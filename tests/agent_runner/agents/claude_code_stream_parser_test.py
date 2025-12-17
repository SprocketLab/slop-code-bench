"""Tests for the Claude Code agent parse_line method."""

from __future__ import annotations

import json

import pytest

from slop_code.agent_runner.agents.claude_code.agent import ClaudeCodeAgent


def test_parse_line_result_with_cache_tokens() -> None:
    """Test parsing result type with both cache_read and cache_write tokens."""
    payload = {
        "type": "result",
        "usage": {
            "input_tokens": 225,
            "output_tokens": 16818,
            "cache_creation_input_tokens": 17820,
            "cache_read_input_tokens": 597190,
        },
        "total_cost_usd": 0.5253359999999999,
    }

    line = json.dumps(payload)
    cost, tokens, returned_payload = ClaudeCodeAgent.parse_line(line)

    assert cost == pytest.approx(0.5253359999999999)
    assert tokens is not None
    assert tokens.input == 225
    assert tokens.output == 16818
    assert tokens.cache_write == 17820
    assert tokens.cache_read == 597190
    assert tokens.reasoning == 0
    assert returned_payload == payload


def test_parse_line_result_without_cache_tokens() -> None:
    """Test parsing result type without cache tokens (should default to 0)."""
    payload = {
        "type": "result",
        "usage": {
            "input_tokens": 100,
            "output_tokens": 50,
        },
        "total_cost_usd": 0.01,
    }

    line = json.dumps(payload)
    cost, tokens, returned_payload = ClaudeCodeAgent.parse_line(line)

    assert cost == pytest.approx(0.01)
    assert tokens is not None
    assert tokens.input == 100
    assert tokens.output == 50
    assert tokens.cache_write == 0
    assert tokens.cache_read == 0
    assert tokens.reasoning == 0


def test_parse_line_message_with_cache_tokens() -> None:
    """Test parsing message type with cache tokens in usage."""
    payload = {
        "type": "message",
        "message": {
            "role": "assistant",
            "id": "msg_123",
            "content": {"text": "Hello"},
            "usage": {
                "input_tokens": 500,
                "output_tokens": 200,
                "cache_creation_input_tokens": 100,
                "cache_read_input_tokens": 50,
            },
        },
    }

    line = json.dumps(payload)
    cost, tokens, returned_payload = ClaudeCodeAgent.parse_line(line)

    assert cost is None  # Messages don't have total cost
    assert tokens is not None
    assert tokens.input == 500
    assert tokens.output == 200
    assert tokens.cache_write == 100
    assert tokens.cache_read == 50
    assert tokens.reasoning == 0
    assert returned_payload == payload


def test_parse_line_message_without_cache_tokens() -> None:
    """Test parsing message type without cache tokens."""
    payload = {
        "type": "message",
        "message": {
            "role": "assistant",
            "id": "msg_456",
            "content": {"text": "World"},
            "usage": {
                "input_tokens": 300,
                "output_tokens": 150,
            },
        },
    }

    line = json.dumps(payload)
    cost, tokens, returned_payload = ClaudeCodeAgent.parse_line(line)

    assert cost is None
    assert tokens is not None
    assert tokens.input == 300
    assert tokens.output == 150
    assert tokens.cache_write == 0
    assert tokens.cache_read == 0


def test_parse_line_message_non_assistant_role() -> None:
    """Test that non-assistant messages return None for tokens."""
    payload = {
        "type": "message",
        "message": {
            "role": "user",
            "content": {"text": "Question"},
        },
    }

    line = json.dumps(payload)
    cost, tokens, returned_payload = ClaudeCodeAgent.parse_line(line)

    assert cost is None
    assert tokens is None
    assert returned_payload == payload


def test_parse_line_message_without_usage() -> None:
    """Test that messages without usage return None for tokens."""
    payload = {
        "type": "message",
        "message": {
            "role": "assistant",
            "content": {"text": "Response"},
        },
    }

    line = json.dumps(payload)
    cost, tokens, returned_payload = ClaudeCodeAgent.parse_line(line)

    assert cost is None
    assert tokens is None
    assert returned_payload == payload


def test_parse_line_invalid_json() -> None:
    """Test that invalid JSON returns None for all values."""
    line = "not valid json {"

    cost, tokens, payload = ClaudeCodeAgent.parse_line(line)

    assert cost is None
    assert tokens is None
    assert payload is None


def test_parse_line_non_result_non_message_type() -> None:
    """Test that other message types return None for tokens."""
    payload = {
        "type": "error",
        "message": "Something went wrong",
    }

    line = json.dumps(payload)
    cost, tokens, returned_payload = ClaudeCodeAgent.parse_line(line)

    assert cost is None
    assert tokens is None
    assert returned_payload == payload


def test_parse_line_ensures_no_double_counting() -> None:
    """Test that we don't add cache tokens to input (old bug)."""
    payload = {
        "type": "result",
        "usage": {
            "input_tokens": 1000,
            "output_tokens": 500,
            "cache_creation_input_tokens": 200,
            "cache_read_input_tokens": 300,
        },
        "total_cost_usd": 0.1,
    }

    line = json.dumps(payload)
    cost, tokens, returned_payload = ClaudeCodeAgent.parse_line(line)

    # The key assertion: input should NOT include cache tokens
    # Old code did: input=input_tokens + cache_creation_input_tokens
    # New code should: input=input_tokens (separate fields for cache)
    assert tokens is not None
    assert tokens.input == 1000  # NOT 1200!
    assert tokens.cache_write == 200
    assert tokens.cache_read == 300
    assert tokens.output == 500


def test_parse_line_real_world_example() -> None:
    """Test with the exact payload from the user's example."""
    payload = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "duration_ms": 257556,
        "duration_api_ms": 280883,
        "num_turns": 20,
        "result": "",
        "session_id": "d597c4d6-18a7-423a-968d-b186eb6b7ab4",
        "total_cost_usd": 0.5253359999999999,
        "usage": {
            "input_tokens": 225,
            "cache_creation_input_tokens": 17820,
            "cache_read_input_tokens": 597190,
            "output_tokens": 16818,
            "server_tool_use": {"web_search_requests": 0, "web_fetch_requests": 0},
            "service_tier": "standard",
            "cache_creation": {
                "ephemeral_1h_input_tokens": 0,
                "ephemeral_5m_input_tokens": 17820,
            },
        },
        "modelUsage": {
            "claude-haiku-4-5-20251001": {
                "inputTokens": 19276,
                "outputTokens": 616,
                "cacheReadInputTokens": 0,
                "cacheCreationInputTokens": 0,
                "webSearchRequests": 0,
                "costUSD": 0.022355999999999994,
                "contextWindow": 200000,
            },
            "claude-sonnet-4-5-20250929": {
                "inputTokens": 826,
                "outputTokens": 16968,
                "cacheReadInputTokens": 597190,
                "cacheCreationInputTokens": 17820,
                "webSearchRequests": 0,
                "costUSD": 0.50298,
                "contextWindow": 200000,
            },
        },
        "permission_denials": [],
        "uuid": "98873ad4-cffb-478e-84e6-5012261329e6",
    }

    line = json.dumps(payload)
    cost, tokens, returned_payload = ClaudeCodeAgent.parse_line(line)

    assert cost == pytest.approx(0.5253359999999999)
    assert tokens is not None
    assert tokens.input == 225
    assert tokens.output == 16818
    assert tokens.cache_write == 17820
    assert tokens.cache_read == 597190
    assert tokens.reasoning == 0

    # Verify we're not losing the 597K cache read tokens!
    assert tokens.cache_read > 0
