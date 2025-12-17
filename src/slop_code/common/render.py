"""Template rendering utilities for rubric grading."""

from __future__ import annotations

import re
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import Any

from jinja2 import Environment
from jinja2 import FileSystemLoader
from jinja2 import Template

from slop_code.logging import get_logger

logger = get_logger(__name__)

# Template directory: src/slop_code/common/render.py -> configs/rubrics/templates
TEMPLATES_DIR = (
    Path(__file__).parent.parent.parent.parent
    / "configs/rubrics/templates"
)

ENTRYPOINT_PLACEHOLDER_PATTERN = re.compile(r"%%%ENTRYPOINT:entry_file%%%")
ENTRYPOINT_COMMAND_PLACEHOLDER_PATTERN = re.compile(
    r"%%%ENTRYPOINT:entry_command%%%"
)
CANARY_HTML_COMMENT_PATTERN = re.compile(r"^<!-- .+ -->\n?")


def strip_canary_string(text: str) -> str:
    """Strip canary tracking strings from the start of text.

    Canary strings are injected into problem files for training data detection.
    For markdown files (like spec.md), they appear as HTML comments at the very
    start: <!-- CANARY_STRING_12345 -->

    Args:
        text: The text to strip canary strings from.

    Returns:
        Text with leading canary HTML comments removed.
    """
    return CANARY_HTML_COMMENT_PATTERN.sub("", text)


@lru_cache(maxsize=1)
def _get_template_env() -> Environment:
    """Get cached Jinja2 environment for template loading.

    Returns:
        Cached Jinja2 Environment configured with FileSystemLoader.
    """
    # autoescape=False is safe here: templates generate LLM prompts, not HTML
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=False,  # noqa: S701
    )


def _load_template(template_path: Path | None, default_name: str) -> Template:
    """Load a template from a path or use default.

    Args:
        template_path: Optional path to custom template file.
        default_name: Name of default template in TEMPLATES_DIR.

    Returns:
        Loaded Jinja2 Template.
    """
    if template_path is not None:
        # Load custom template from file
        env = Environment(autoescape=False)  # noqa: S701
        return env.from_string(template_path.read_text())

    # Use default template from templates directory
    return _get_template_env().get_template(default_name)


def get_file_params(
    source_file: Path,
    snapshot_dir: Path,
    language_resolver: Callable[[str], str] | None = None,
) -> dict:
    """Get file parameters for template rendering.

    Args:
        source_file: Path to the source file.
        snapshot_dir: Root snapshot directory for relative path calculation.
        language_resolver: Optional callable that maps file extension to
            language name. If None, uses extension without dot as fallback.

    Returns:
        Dict with file_path, file_content (with line numbers), and language.
    """
    lines = (
        source_file.read_bytes().decode("utf-8", errors="replace").splitlines()
    )
    file_contents = "\n".join(
        f"{i}: {line}" for i, line in enumerate(lines, start=1)
    )

    # Language resolution: use resolver if provided, else fallback to extension
    if language_resolver is not None:
        language = language_resolver(source_file.suffix)
    else:
        language = source_file.suffix.lstrip(".") or "text"

    return {
        "file_path": source_file.relative_to(snapshot_dir).as_posix(),
        "file_content": file_contents,
        "language": language,
    }


def render_criteria_text(
    rubric_items: list[dict],
    criteria_template: Path | None = None,
) -> str:
    """Render the criteria items part of the rubric prompt.

    This is the variable part that changes between batches.

    Args:
        rubric_items: List of rubric item dicts with 'name' and 'description'.
        criteria_template: Optional path to custom criteria template.

    Returns:
        Rendered criteria text.
    """
    template = _load_template(criteria_template, "criteria.j2")
    return template.render(items=rubric_items)


def render_multi_file_prefix(
    spec: str,
    snapshot_dir: Path,
    source_files: list[Path],
    prefix_template: Path | None = None,
    language_resolver: Callable[[str], str] | None = None,
) -> str:
    """Render the cacheable prefix for multiple files.

    This batches multiple files into a single prompt to reduce API calls
    and improve cache utilization.

    Args:
        spec: Problem specification text.
        snapshot_dir: Root snapshot directory.
        source_files: List of source file paths to include.
        prefix_template: Optional path to custom prefix template.
        language_resolver: Optional callable for language detection.
            If None, uses extension without dot as fallback.

    Returns:
        Rendered prefix string with all files included.
    """
    template = _load_template(prefix_template, "prefix_multi_file.j2")
    files_data = [
        get_file_params(f, snapshot_dir, language_resolver)
        for f in source_files
    ]
    return template.render(spec=spec, files=files_data)


def replace_spec_placeholders(
    spec_text: str, entry_file: str, entry_command: str
) -> str:
    spec_text = ENTRYPOINT_PLACEHOLDER_PATTERN.sub(entry_file, spec_text)
    return ENTRYPOINT_COMMAND_PLACEHOLDER_PATTERN.sub(entry_command, spec_text)


def render_prompt(
    spec_text: str,
    context: dict[str, Any],
    prompt_template: str,
    entry_file: str,
    entry_command: str,
) -> str:
    """Render a prompt template with spec text and context.

    Strips canary tracking strings, replaces entrypoint placeholders in spec
    text, and renders using Jinja2.

    Args:
        spec_text: The specification text with potential placeholders
        context: Additional context variables for template rendering
        prompt_template: Jinja2 template string for the prompt
        entry_file: Entry file path to substitute for placeholders
        entry_command: Entry command to substitute for placeholders

    Returns:
        Rendered prompt string ready for agent consumption
    """
    spec_text = strip_canary_string(spec_text)
    spec_text = replace_spec_placeholders(spec_text, entry_file, entry_command)
    template = Template(prompt_template)
    return template.render(spec=spec_text, **context)
