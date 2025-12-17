"""AWS Bedrock API client for LLM-based rubric grading."""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any

import boto3
from botocore.config import Config

from slop_code.common.llms import ModelCatalog
from slop_code.common.llms import TokenUsage
from slop_code.logging import get_logger

logger = get_logger(__name__)

# Configuration
DEFAULT_MAX_RETRIES = 5
DEFAULT_TIMEOUT = 60
DEFAULT_REGION = "us-east-1"

SYSTEM_MESSAGE = """You are an expert code reviewer. You are given a file and \
a rubric. You need to review the file and flag every code issue per the rubric. \
It is critical that you flag **all** issues, not just the ones that are most \
obvious."""

# JSON extraction patterns (same as llm_grade.py)
_JSON_FENCE_PATTERN = re.compile(
    r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", re.DOTALL
)
_JSON_BODY_PATTERN = re.compile(r"(\{.*\}|\[.*\])", re.DOTALL)

# Multi-file response pattern
_MULTI_FILE_BLOCK_PATTERN = re.compile(
    r"===\s*FILE:\s*(.+?)\s*===\s*(.*?)\s*===\s*END FILE\s*===",
    re.DOTALL,
)


def _build_messages_for_bedrock(
    prompt_prefix: str,
    criteria_text: str,
) -> list[dict[str, Any]]:
    """Build messages in Bedrock Anthropic format."""
    # Cache the static prompt prefix so later rubric batches can reuse it
    prefix_block = {
        "type": "text",
        "text": prompt_prefix,
        "cache_control": {"type": "ephemeral"},
    }
    return [
        {
            "role": "user",
            "content": [
                prefix_block,
                {"type": "text", "text": criteria_text},
            ],
        },
    ]


async def grade_file_async(
    prompt_prefix: str,
    criteria_text: str,
    file_name: str | None,
    model: str,
    temperature: float = 0.0,
    thinking_tokens: int | None = None,
    client: Any | None = None,
    api_key: str | None = None,
    api_key_env: str = "",
    api_url: str = "",
    region: str | None = None,
) -> tuple[list[dict], dict[str, Any]]:
    """Grade a file against rubric criteria using AWS Bedrock.

    Args:
        prompt_prefix: Static prompt content (spec + file content).
        criteria_text: Variable rubric criteria items text.
        file_name: Name of the file being graded (for result annotation).
        model: Bedrock model ID (e.g., "anthropic.claude-3-5-sonnet-20241022-v2:0").
        temperature: Sampling temperature for the model.
        thinking_tokens: Extended thinking token budget (None or 0 to disable).
        client: Optional boto3 bedrock-runtime client for reuse.
        api_key: Unused for Bedrock (uses AWS credential chain).
        api_key_env: Unused for Bedrock.
        api_url: Unused for Bedrock.
        region: AWS region (defaults to us-east-1 or AWS_REGION env var).

    Returns:
        Tuple of (flattened grades list, raw result dict).

    Raises:
        RuntimeError: If the API call fails.
    """
    start_time = time.perf_counter()
    logger.debug("Grading file via Bedrock", file_name=file_name, model=model)

    # Create client if not provided
    close_client = client is None
    if client is None:
        config = Config(
            read_timeout=3600,
            retries={"max_attempts": DEFAULT_MAX_RETRIES},
            connect_timeout=DEFAULT_TIMEOUT,
        )
        client = boto3.client(
            "bedrock-runtime",
            region_name=region or DEFAULT_REGION,
            config=config,
        )

    # Build messages
    messages = _build_messages_for_bedrock(prompt_prefix, criteria_text)

    # Build request body for Anthropic models on Bedrock
    request_body: dict[str, Any] = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 8192,
        "system": SYSTEM_MESSAGE,
        "messages": messages,
        "temperature": temperature,
    }

    if thinking_tokens and thinking_tokens > 0:
        request_body["thinking"] = {
            "type": "enabled",
            "budget_tokens": thinking_tokens,
        }

    logger.debug(
        "Bedrock request",
        model=model,
        file_name=file_name,
        temperature=temperature,
        thinking_tokens=thinking_tokens,
    )

    request_body_json = json.dumps(request_body)

    def _invoke_and_read() -> dict[str, Any]:
        response = client.invoke_model(
            modelId=model,
            body=request_body_json,
            contentType="application/json",
            accept="application/json",
        )
        return json.loads(response.get("body", {}).read())

    try:
        response_data = await asyncio.to_thread(_invoke_and_read)
    except Exception as exc:
        logger.error(
            "Bedrock API call failed",
            error=str(exc),
            file_name=file_name,
        )
        raise RuntimeError(f"Bedrock API error: {exc}") from exc
    finally:
        if close_client and client is not None:
            pass  # boto3 clients don't need explicit closing
    # Process response
    elapsed = time.perf_counter() - start_time
    usage = response_data.get("usage", {})
    logger.debug(
        "Bedrock API call complete",
        elapsed_seconds=round(elapsed, 2),
        input_tokens=usage.get("input_tokens", 0),
        output_tokens=usage.get("output_tokens", 0),
    )

    # Convert response to OpenRouter-compatible format for grade extraction
    normalized_response = _normalize_bedrock_response(response_data, model)

    # Extract grades from response
    grades = _extract_grades(normalized_response, file_name)
    return grades, normalized_response


def _compute_cost(model: str, usage: dict[str, Any]) -> float:
    """Compute cost from the model catalog pricing."""
    model_def = ModelCatalog.get(model)
    if model_def is None:
        raise ValueError(f"Model {model} not found in model catalog")
    token_usage = TokenUsage(
        input=usage["prompt_tokens"],
        output=usage["completion_tokens"],
        cache_read=usage["cache_read_input_tokens"],
        cache_write=usage["cache_creation_input_tokens"],
    )
    return model_def.pricing.get_cost(token_usage)


def _normalize_bedrock_response(
    response_data: dict[str, Any], model: str
) -> dict[str, Any]:
    """Normalize Bedrock response to OpenRouter-compatible format.

    Bedrock returns:
    {
        "content": [{"type": "text", "text": "..."}],
        "usage": {"input_tokens": N, "output_tokens": M}
    }

    We convert to:
    {
        "choices": [{"message": {"content": "..."}}],
        "usage": {"prompt_tokens": N, "completion_tokens": M}
    }
    """
    content_blocks = response_data.get("content", [])
    text_parts = []
    for block in content_blocks:
        if block.get("type") == "text":
            text_parts.append(block.get("text", ""))
        elif block.get("type") == "thinking":
            # Skip thinking blocks in output
            pass

    text_content = "".join(text_parts)

    bedrock_usage = response_data.get("usage", {})

    normalized_usage = {
        "choices": [{"message": {"content": text_content}}],
        "usage": {
            "prompt_tokens": bedrock_usage.get("input_tokens", 0),
            "completion_tokens": bedrock_usage.get("output_tokens", 0),
            "total_tokens": (
                bedrock_usage.get("input_tokens", 0)
                + bedrock_usage.get("output_tokens", 0)
            ),
            # Bedrock does not return cache usage; keep explicit zero fields
            "cache_read_input_tokens": bedrock_usage.get(
                "cache_read_input_tokens", 0
            ),
            "cache_creation_input_tokens": bedrock_usage.get(
                "cache_creation_input_tokens", 0
            ),
        },
        # Keep original data for debugging
        "_bedrock_raw": response_data,
    }
    normalized_usage["usage"]["cost"] = _compute_cost(
        response_data.get("model", model), normalized_usage["usage"]
    )
    return normalized_usage


def _extract_grades(
    response_data: dict[str, Any], file_name: str | None
) -> list[dict]:
    """Extract and flatten grades from API response.

    Automatically detects multi-file format (=== FILE: ... ===) and parses
    accordingly. For multi-file responses, file_name is extracted from
    block headers. For single-file responses, the provided file_name is used.
    """
    choice = (response_data.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    message_content = message.get("content")

    if isinstance(message_content, str):
        text_content = message_content
    elif isinstance(message_content, list):
        parts = [
            block.get("text", "")
            for block in message_content
            if isinstance(block, dict)
        ]
        text_content = "".join(parts)
    else:
        text_content = ""

    grades = _parse_multi_file_response(text_content)
    if grades is None:
        logger.warning(
            "Multi-file format detected but no grades extracted",
            file_name=file_name,
        )
    return grades or []


def _parse_json_text(message_text: str) -> list[dict] | None:
    """Parse JSON from message text, trying multiple strategies."""
    message_text = message_text.strip()

    fenced = _JSON_FENCE_PATTERN.search(message_text)
    candidates = [fenced.group(1)] if fenced else []
    candidates.append(message_text)

    for candidate in candidates:
        candidate = candidate.strip()
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            body = _JSON_BODY_PATTERN.search(candidate)
            if body:
                try:
                    return json.loads(body.group(1))
                except json.JSONDecodeError:
                    continue
    return None


def _parse_multi_file_response(message_text: str) -> list[dict] | None:
    """Parse response with per-file JSON blocks."""
    all_grades: list[dict] = []
    has_matches = False

    for match in _MULTI_FILE_BLOCK_PATTERN.finditer(message_text):
        file_path = match.group(1).strip()
        block_content = match.group(2).strip()

        parsed = _parse_json_text(block_content)
        if parsed is None:
            logger.warning(
                "No valid JSON found in file block",
                file_path=file_path,
            )
            continue

        has_matches = True
        if isinstance(parsed, dict):
            parsed = [parsed]

        for grade in parsed:
            all_grades.append({**grade, "file_name": file_path})

    if not has_matches:
        return None

    return all_grades
