"""Placeholder resolution for static assets in case data.

This module provides utilities to resolve {{static:name}} placeholders in case
arguments and materialized files based on the execution environment type.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from slop_code.execution.assets import ResolvedStaticAsset

STATIC_PLACEHOLDER_RE = re.compile(r"\{\{static:([^}]+)\}\}")


def resolve_static_path(
    asset: ResolvedStaticAsset,
    *,
    is_docker: bool,
) -> str:
    """Get the appropriate path for a static asset based on environment type.

    Args:
        asset: Resolved static asset with both absolute and save paths.
        is_docker: Whether the execution environment is Docker-based.

    Returns:
        Absolute host path for local execution, or /static/{save_path}
        for Docker execution.
    """
    if is_docker:
        # For Docker, static assets are mounted to /static/{save_path}
        return str(Path("/static") / asset.save_path)
    # For local, return the absolute host path
    return str(asset.absolute_path)


def _replace_static_placeholders_in_string(
    value: str,
    static_assets: dict[str, ResolvedStaticAsset],
    *,
    is_docker: bool,
) -> str:
    """Replace {{static:name}} tokens in value with appropriate paths.

    Args:
        value: String potentially containing placeholders.
        static_assets: Mapping of asset name to resolved asset.
        is_docker: Whether the execution environment is Docker-based.

    Returns:
        String with placeholders replaced by appropriate paths.

    Raises:
        ValueError: If a placeholder references an unknown asset.
    """

    def _replace(match: re.Match[str]) -> str:
        asset_name = match.group(1)
        asset = static_assets.get(asset_name)
        if asset is None:
            raise ValueError(f"Unknown static asset placeholder: {asset_name}")
        return resolve_static_path(asset, is_docker=is_docker)

    return STATIC_PLACEHOLDER_RE.sub(_replace, value)


def resolve_static_placeholders(
    data: Any,
    static_assets: dict[str, ResolvedStaticAsset],
    *,
    is_docker: bool,
) -> Any:
    """Recursively substitute static asset placeholders within data.

    This function walks through dictionaries, lists, tuples, and strings,
    replacing any {{static:name}} placeholders with the appropriate paths
    for the execution environment.

    Args:
        data: Data structure potentially containing placeholders.
        static_assets: Mapping of asset name to resolved asset.
        is_docker: Whether the execution environment is Docker-based.

    Returns:
        Data structure with placeholders replaced by appropriate paths.
    """
    if isinstance(data, dict):
        resolved: dict[Any, Any] = {}
        for key, value in data.items():
            new_key = (
                _replace_static_placeholders_in_string(
                    key,
                    static_assets,
                    is_docker=is_docker,
                )
                if isinstance(key, str)
                else key
            )
            resolved[new_key] = resolve_static_placeholders(
                value,
                static_assets,
                is_docker=is_docker,
            )
        return resolved
    if isinstance(data, list):
        return [
            resolve_static_placeholders(
                item,
                static_assets,
                is_docker=is_docker,
            )
            for item in data
        ]
    if isinstance(data, tuple):
        return tuple(
            resolve_static_placeholders(
                item,
                static_assets,
                is_docker=is_docker,
            )
            for item in data
        )
    if isinstance(data, str):
        return _replace_static_placeholders_in_string(
            data,
            static_assets,
            is_docker=is_docker,
        )
    return data
