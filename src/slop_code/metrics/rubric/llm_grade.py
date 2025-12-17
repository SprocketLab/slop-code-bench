"""OpenRouter API client for LLM-based rubric grading."""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from typing import Any
from urllib.parse import urlparse

import httpx
from tenacity import AsyncRetrying
from tenacity import retry_if_exception
from tenacity import stop_after_attempt
from tenacity import wait_exponential_jitter

from slop_code.common import mask_sensitive_values
from slop_code.logging import get_logger

logger = get_logger(__name__)

# Configuration
DEFAULT_MAX_RETRIES = 5
DEFAULT_TIMEOUT = 60
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_API_KEY_ENV = "OPENROUTER_API_KEY"

SYSTEM_MESSAGE = """You are an expert code reviewer. You are given a file and \
a rubric. You need to review the file and flag every code issue per the rubric. \
It is critical that you flag **all** issues, not just the ones that are most \
obvious."""

# JSON extraction patterns
_JSON_FENCE_PATTERN = re.compile(
    r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", re.DOTALL
)
_JSON_BODY_PATTERN = re.compile(r"(\{.*\}|\[.*\])", re.DOTALL)

# Multi-file response pattern
# Matches: === FILE: path/to/file.py === ... === END FILE ===
_MULTI_FILE_BLOCK_PATTERN = re.compile(
    r"===\s*FILE:\s*(.+?)\s*===\s*(.*?)\s*===\s*END FILE\s*===",
    re.DOTALL,
)


def _get_provider(model: str) -> str:
    """Return provider prefix from model string (e.g., openai/..., anthropic/...)."""
    return model.split("/", 1)[0].lower() if "/" in model else ""


def _format_for_anthropic(prefix: str, criteria: str) -> list[dict[str, Any]]:
    return [
        {
            "role": "system",
            "content": [
                {
                    "type": "text",
                    "text": SYSTEM_MESSAGE,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": prefix,
                    "cache_control": {"type": "ephemeral"},
                },
                {"type": "text", "text": criteria},
            ],
        },
    ]


def _format_for_openai(prefix: str, criteria: str) -> list[dict[str, Any]]:
    return [
        {
            "role": "system",
            "content": [
                {
                    "type": "input_text",
                    "input_text": {
                        "text": SYSTEM_MESSAGE,
                        "cache_control": {"type": "ephemeral"},
                    },
                }
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "input_text",
                    "input_text": {
                        "text": prefix,
                        "cache_control": {"type": "ephemeral"},
                    },
                },
                {"type": "input_text", "input_text": {"text": criteria}},
            ],
        },
    ]


def _build_messages(
    prompt_prefix: str,
    criteria_text: str,
    provider: str,
) -> list[dict[str, Any]]:
    """Build provider-aware messages with cache directives."""

    if provider == "openai":
        messages = _format_for_openai(prompt_prefix, criteria_text)
    elif provider in {"anthropic", "google"}:
        messages = _format_for_anthropic(prompt_prefix, criteria_text)
    else:
        raise ValueError(f"Unsupported provider: {provider}")
    return messages


def grade_file(
    prompt_prefix: str,
    criteria_text: str,
    file_name: str,
    model: str,
    temperature: float = 0.0,
    thinking_tokens: int | None = None,
    api_key: str | None = None,
    api_key_env: str = OPENROUTER_API_KEY_ENV,
    api_url: str = OPENROUTER_API_URL,
) -> tuple[list[dict], dict[str, Any]]:
    """Grade a file against rubric criteria (sync wrapper).

    Args:
        prompt_prefix: Static prompt content (spec + file content).
        criteria_text: Variable rubric criteria items text.
        file_name: Name of the file being graded.
        model: OpenRouter model ID (e.g., "anthropic/claude-3.5-sonnet").
        temperature: Sampling temperature for the model.
        thinking_tokens: Extended thinking token budget (None or 0 to disable).
        api_key: Optional override for the OpenRouter API key.
        api_url: Optional override for the OpenRouter API URL.

    Returns:
        Tuple of (flattened grades list, raw API response dict).
    """
    return asyncio.run(
        grade_file_async(
            prompt_prefix=prompt_prefix,
            criteria_text=criteria_text,
            file_name=file_name,
            model=model,
            temperature=temperature,
            thinking_tokens=thinking_tokens,
            api_key=api_key,
            api_url=api_url,
            api_key_env=api_key_env,
        )
    )


async def grade_file_async(
    prompt_prefix: str,
    criteria_text: str,
    file_name: str,
    model: str,
    temperature: float = 0.0,
    thinking_tokens: int | None = None,
    client: httpx.AsyncClient | None = None,
    api_key: str | None = None,
    api_key_env: str = OPENROUTER_API_KEY_ENV,
    api_url: str = OPENROUTER_API_URL,
) -> tuple[list[dict], dict[str, Any]]:
    """Grade a file against rubric criteria using the OpenRouter API.

    Args:
        prompt_prefix: Static prompt content (spec + file content) to cache.
        criteria_text: Variable rubric criteria items text.
        file_name: Name of the file being graded (for result annotation).
        model: OpenRouter model ID (e.g., "anthropic/claude-3.5-sonnet").
        temperature: Sampling temperature for the model.
        thinking_tokens: Extended thinking token budget (None or 0 to disable).
        client: Optional httpx async client for reuse in batching.
        api_key: Optional override for the OpenRouter API key.
        api_key_env: Environment variable to read the OpenRouter API key from
            when api_key is not provided.
        api_url: Optional override for the OpenRouter chat completions URL.

    Returns:
        Tuple of (flattened grades list, raw result dict).

    Raises:
        RuntimeError: If the API call fails.
    """
    start_time = time.perf_counter()
    logger.info("Grading file", file_name=file_name, model=model)

    provider = _get_provider(model)

    # Get API key
    key = api_key or os.getenv(api_key_env)
    if not key:
        raise RuntimeError(
            "OpenRouter API key missing. "
            f"Set {api_key_env} or pass api_key explicitly."
        )

    # Build headers
    headers: dict[str, str] = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    if referer := os.getenv("OPENROUTER_HTTP_REFERER") or os.getenv(
        "OPENROUTER_REFERRER"
    ):
        headers["HTTP-Referer"] = referer
    if title := os.getenv("OPENROUTER_TITLE"):
        headers["X-Title"] = title

    logger.debug(
        "Headers",
        headers=mask_sensitive_values(headers),
        api_url=api_url,
        file_name=file_name,
        model=model,
        temperature=temperature,
        thinking_tokens=thinking_tokens,
    )
    # Build messages with cache control
    messages = _build_messages(
        prompt_prefix=prompt_prefix,
        criteria_text=criteria_text,
        provider=provider,
    )

    # Build payload
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "usage": {"include": True},
        "temperature": temperature,
    }
    if thinking_tokens:
        payload["reasoning"] = {
            "enabled": True,
            "max_tokens": thinking_tokens,
            "exclude": False,
        }
    else:
        payload["reasoning"] = {
            "enabled": False,
        }

    # Retry configuration
    def is_retryable(exc: BaseException) -> bool:
        if isinstance(exc, httpx.HTTPStatusError):
            status = exc.response.status_code
            # Retry on 429 (Too Many Requests), 402 (Payment Required), or 5xx server errors
            return status == 429 or status == 402 or status >= 500
        return bool(isinstance(exc, httpx.RequestError))

    def before_sleep(retry_state):
        logger.debug(
            "Retryable API error, backing off",
            error=str(retry_state.outcome.exception()),
            attempt=retry_state.attempt_number,
            delay_seconds=round(retry_state.next_action.sleep, 2),
            file_name=file_name,
        )

    # Make API call with retries
    close_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=DEFAULT_TIMEOUT, trust_env=False)

    response_data: dict[str, Any] | None = None
    try:
        async for attempt in AsyncRetrying(
            retry=retry_if_exception(is_retryable),
            stop=stop_after_attempt(DEFAULT_MAX_RETRIES + 1),
            wait=wait_exponential_jitter(initial=1, max=60),
            before_sleep=before_sleep,
            reraise=True,
        ):
            with attempt:
                response = await client.post(
                    api_url, headers=headers, json=payload
                )
                response.raise_for_status()
                response_data = response.json()
    except httpx.HTTPStatusError as exc:
        logger.error(
            "OpenRouter API call failed",
            status_code=exc.response.status_code,
            body=exc.response.text,
            file_name=file_name,
        )
        raise RuntimeError(f"OpenRouter API error: {exc}") from exc
    except httpx.RequestError as exc:
        logger.error(
            "OpenRouter request failed",
            error=str(exc),
            api_url=repr(api_url),
            hostname=urlparse(api_url).hostname,
            port=urlparse(api_url).port,
            headers=mask_sensitive_values(headers),
            payload=payload.keys(),
        )
        raise RuntimeError(f"OpenRouter request error: {exc}") from exc
    finally:
        if close_client:
            await client.aclose()

    if response_data is None:
        raise RuntimeError("No response received after retries")

    # Process response
    elapsed = time.perf_counter() - start_time
    usage = response_data.get("usage", {})
    logger.info(
        "API call complete",
        elapsed_seconds=round(elapsed, 2),
        prompt_tokens=usage.get("prompt_tokens", 0),
        completion_tokens=usage.get("completion_tokens", 0),
        cache_read_tokens=usage.get("cache_read_input_tokens", 0),
        cache_write_tokens=usage.get("cache_creation_input_tokens", 0),
    )

    # Extract grades from response
    grades = _extract_grades(response_data, file_name)
    return grades, response_data


def _extract_grades(
    response_data: dict[str, Any], file_name: str | None
) -> list[dict]:
    """Extract and flatten grades from API response.

    Automatically detects multi-file format (=== FILE: ... ===) and parses
    accordingly. For multi-file responses, file_name is extracted from
    block headers. For single-file responses, the provided file_name is used.

    Args:
        response_data: Raw API response dictionary.
        file_name: File being graded (for single-file annotation, ignored
            for multi-file responses).

    Returns:
        List of grade dictionaries with file_name added.
    """
    choice = (response_data.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    message_content = message.get("content")

    # Extract text content from message
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
    """Parse JSON from message text, trying multiple strategies.

    Args:
        message_text: Raw text that may contain JSON.

    Returns:
        Parsed JSON as list of dicts, or None if parsing failed.
    """
    message_text = message_text.strip()

    # Try fenced JSON first
    fenced = _JSON_FENCE_PATTERN.search(message_text)
    candidates = [fenced.group(1)] if fenced else []
    candidates.append(message_text)

    for candidate in candidates:
        candidate = candidate.strip()
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            # Try extracting JSON body
            body = _JSON_BODY_PATTERN.search(candidate)
            if body:
                try:
                    return json.loads(body.group(1))
                except json.JSONDecodeError:
                    continue
    return None


def _parse_multi_file_response(message_text: str) -> list[dict] | None:
    """Parse response with per-file JSON blocks.

    Expected format:
    === FILE: src/main.py ===
    ```json
    [{"criteria": "...", "start": 1, "end": 2, ...}]
    ```
    === END FILE ===

    Args:
        message_text: Raw response text with file-delimited blocks.

    Returns:
        List of grade dictionaries with file_name added from block headers.
    """
    all_grades: list[dict] = []
    has_matches = False

    for match in _MULTI_FILE_BLOCK_PATTERN.finditer(message_text):
        file_path = match.group(1).strip()
        block_content = match.group(2).strip()

        # Parse JSON from block content
        parsed = _parse_json_text(block_content)
        if parsed is None:
            logger.warning(
                "No valid JSON found in file block",
                file_path=file_path,
            )
            continue

        has_matches = True
        # Handle both list and dict responses
        if isinstance(parsed, dict):
            parsed = [parsed]

        # Add file_name to each grade and flatten occurrences
        for grade in parsed:
            all_grades.append({**grade, "file_name": file_path})

    if not has_matches:
        return None

    return all_grades
