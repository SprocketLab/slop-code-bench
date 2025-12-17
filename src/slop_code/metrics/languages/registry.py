"""Language registry for code quality metrics.

This module provides the registry for language specifications and functions
to register and retrieve languages by name or file extension.
"""

from __future__ import annotations

from slop_code.metrics.models import LanguageSpec

# Language registry - maps language names to their specs
LANGUAGE_REGISTRY: dict[str, LanguageSpec] = {}
# Extension to language name mapping
EXT_TO_LANGUAGE: dict[str, str] = {}


def register_language(name: str, spec: LanguageSpec) -> None:
    """Register a language specification.

    Args:
        name: The name of the language (e.g., "PYTHON").
        spec: The LanguageSpec for the language.
    """
    LANGUAGE_REGISTRY[name] = spec
    for extension in spec.extensions:
        EXT_TO_LANGUAGE[extension] = name


def get_language(name: str) -> LanguageSpec:
    """Get a language specification by name.

    Args:
        name: The name of the language.

    Returns:
        The LanguageSpec for the language.

    Raises:
        KeyError: If the language is not registered.
    """
    return LANGUAGE_REGISTRY[name]


def get_language_by_extension(extension: str) -> LanguageSpec | None:
    """Get a language specification by file extension.

    Args:
        extension: The file extension including the dot (e.g., ".py").

    Returns:
        The LanguageSpec for the language, or None if not found.
    """
    lang = EXT_TO_LANGUAGE.get(extension)
    if lang is None:
        return None
    return LANGUAGE_REGISTRY[lang]


def get_language_for_extension(extension: str) -> str:
    """Get language name for code block syntax highlighting.

    Args:
        extension: File extension including the dot (e.g., ".py")

    Returns:
        Lowercase language name (e.g., "python") or extension without dot.
    """
    lang = EXT_TO_LANGUAGE.get(extension)
    if lang:
        return lang.lower()
    return extension.lstrip(".") or "text"
