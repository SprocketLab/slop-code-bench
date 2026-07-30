from __future__ import annotations

import os
import tempfile
from collections.abc import Iterable
from pathlib import Path

HOME_PATH = str(Path(tempfile.gettempdir()) / "agent_home")


def resolve_env_vars(config):
    """
    Recursively resolves environment variables in a configuration dictionary.

    Any string value in the form "${VAR_NAME}" will be replaced by the value of
    the corresponding environment variable. Nested dictionaries and lists are supported.

    Args:
        config (dict): Configuration dictionary.

    Returns:
        dict: New dictionary with environment variables resolved.
    """

    def resolve_value(value):
        # Handle nested structures
        if isinstance(value, dict):
            return {k: resolve_value(v) for k, v in value.items()}
        if isinstance(value, list):
            return [resolve_value(v) for v in value]
        if isinstance(value, str):
            # Detect ${VAR_NAME} syntax
            if value.startswith("${") and value.endswith("}"):
                env_var = value[2:-1]
                return os.environ.get(
                    env_var, value
                )  # fallback to the original if missing
            return value
        return value

    return resolve_value(config)


def find_jsonl_files(root: Path, *, recursive: bool = True) -> list[Path]:
    if not root.exists():
        return []
    pattern = "**/*.jsonl" if recursive else "*.jsonl"
    return [path for path in root.glob(pattern) if path.is_file()]


def copy_jsonl_files(files: Iterable[Path], dest_dir: Path) -> list[Path]:
    dest_dir.mkdir(parents=True, exist_ok=True)
    copied: list[Path] = []
    used_names = {path.name for path in dest_dir.iterdir() if path.is_file()}
    for src in files:
        if not src.is_file():
            continue
        dest_name = src.name
        if dest_name in used_names:
            dest_name = _dedupe_name(dest_name, used_names)
        dest = dest_dir / dest_name
        dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        used_names.add(dest_name)
        copied.append(dest)
    return copied


def _dedupe_name(name: str, used_names: set[str]) -> str:
    stem = Path(name).stem
    suffix = Path(name).suffix
    counter = 1
    candidate = f"{stem}_{counter}{suffix}"
    while candidate in used_names:
        counter += 1
        candidate = f"{stem}_{counter}{suffix}"
    return candidate
