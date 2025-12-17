"""Provider routing for LLM-based rubric grading."""

from __future__ import annotations

from typing import Any

from slop_code.metrics.rubric import RubricProvider


async def grade_file_async(
    prompt_prefix: str,
    criteria_text: str,
    file_name: str | None,
    model: str,
    provider: RubricProvider = RubricProvider.OPENROUTER,
    temperature: float = 0.0,
    thinking_tokens: int | None = None,
    client: Any | None = None,
    api_key: str | None = None,
    api_key_env: str = "",
    api_url: str = "",
    region: str | None = None,
) -> tuple[list[dict], dict[str, Any]]:
    """Grade a file against rubric criteria using the specified provider.

    Routes to the appropriate provider implementation based on the provider
    parameter.

    Args:
        prompt_prefix: Static prompt content (spec + file content).
        criteria_text: Variable rubric criteria items text.
        file_name: Name of the file being graded (for result annotation).
        model: Model ID in provider-specific format.
        provider: LLM provider to use (openrouter or bedrock).
        temperature: Sampling temperature for the model.
        thinking_tokens: Extended thinking token budget (None or 0 to disable).
        client: Optional client for reuse (httpx.AsyncClient for OpenRouter,
            boto3 client for Bedrock).
        api_key: API key override (OpenRouter only).
        api_key_env: Environment variable for API key (OpenRouter only).
        api_url: API URL override (OpenRouter only).
        region: AWS region (Bedrock only).

    Returns:
        Tuple of (flattened grades list, raw result dict).

    Raises:
        RuntimeError: If the API call fails.
        ValueError: If an unsupported provider is specified.
    """
    if provider == RubricProvider.OPENROUTER:
        from slop_code.metrics.rubric.llm_grade import (
            grade_file_async as openrouter_grade,
        )

        return await openrouter_grade(
            prompt_prefix=prompt_prefix,
            criteria_text=criteria_text,
            file_name=file_name,
            model=model,
            temperature=temperature,
            thinking_tokens=thinking_tokens,
            client=client,
            api_key=api_key,
            api_key_env=api_key_env,
            api_url=api_url,
        )
    if provider == RubricProvider.BEDROCK:
        from slop_code.metrics.rubric.bedrock_grade import (
            grade_file_async as bedrock_grade,
        )

        return await bedrock_grade(
            prompt_prefix=prompt_prefix,
            criteria_text=criteria_text,
            file_name=file_name,
            model=model,
            temperature=temperature,
            thinking_tokens=thinking_tokens,
            client=client,
            region=region,
        )
    raise ValueError(f"Unsupported provider: {provider}")
