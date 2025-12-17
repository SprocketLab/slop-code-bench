"""Config loading pipeline with two-tier path resolution and OmegaConf merging."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer
import yaml
from omegaconf import OmegaConf
from pydantic import ValidationError

from slop_code.entrypoints.config.resolvers import register_resolvers
from slop_code.entrypoints.config.run_config import ModelConfig
from slop_code.entrypoints.config.run_config import OneShotConfig
from slop_code.entrypoints.config.run_config import ResolvedRunConfig
from slop_code.entrypoints.config.run_config import ThinkingConfig
from slop_code.entrypoints.config.run_config import ThinkingPresetType
from slop_code.evaluation import PassPolicy
from slop_code.execution.models import EnvironmentSpec
from slop_code.logging import get_logger

logger = get_logger(__name__)


def get_package_config_dir() -> Path:
    """Get the package's configs directory.

    Returns:
        Path to the configs/ directory in the package root.
    """
    # src/slop_code/entrypoints/config/loader.py -> configs/
    return Path(__file__).parents[4] / "configs"


def resolve_config_path(value: str, category: str) -> Path:
    """Resolve a config reference to an actual file path.

    Resolution order:
    1. If value is a path to an existing file, use it directly
    2. Otherwise, treat as bare name and search with extension added

    Extension handling for bare names:
    - agents/environments: .yaml
    - prompts: .jinja

    Args:
        value: The config reference (path or bare name)
        category: The config category ("agents", "environments", "prompts")

    Returns:
        Resolved path to the config file.

    Raises:
        FileNotFoundError: If the config file cannot be found.
    """
    # First, check if it's a direct path to an existing file
    path = Path(value).expanduser()
    if path.is_file():
        return path

    # Bare name - two-tier lookup with extension
    ext = ".jinja" if category == "prompts" else ".yaml"
    package_config_dir = get_package_config_dir()

    # 1. Package configs
    package_path = package_config_dir / category / f"{value}{ext}"
    if package_path.exists():
        return package_path

    # 2. CWD with extension
    cwd_path = Path.cwd() / f"{value}{ext}"
    if cwd_path.exists():
        return cwd_path

    # 3. CWD with category subdir
    cwd_category_path = Path.cwd() / category / f"{value}{ext}"
    if cwd_category_path.exists():
        return cwd_category_path

    # Build helpful error message
    searched = [str(path)] if path != Path(value) else []
    searched.extend([
        str(package_path),
        str(cwd_path),
        str(cwd_category_path),
    ])
    raise FileNotFoundError(
        f"Config '{value}' not found. Searched:\n  " + "\n  ".join(searched)
    )


def parse_override(override: str) -> tuple[str, Any]:
    """Parse a CLI override in 'key=value' or 'key.nested=value' format.

    Handles type inference for common types:
    - "true"/"false" -> bool
    - Integer strings -> int
    - Float strings -> float
    - Everything else -> str

    Args:
        override: The override string (e.g., "model.name=opus-4")

    Returns:
        Tuple of (key, parsed_value)

    Raises:
        ValueError: If the override format is invalid.
    """
    if "=" not in override:
        raise ValueError(
            f"Invalid override format: '{override}'. Expected 'key=value'."
        )

    key, value = override.split("=", 1)
    key = key.strip()
    value = value.strip()

    if not key:
        raise ValueError(f"Override key cannot be empty: '{override}'")

    # Type inference
    if value.lower() == "true":
        return key, True
    if value.lower() == "false":
        return key, False

    # Try integer
    try:
        return key, int(value)
    except ValueError:
        pass

    # Try float
    try:
        return key, float(value)
    except ValueError:
        pass

    # String (default)
    return key, value


def _load_yaml_file(path: Path) -> dict[str, Any]:
    """Load a YAML file and return its contents as a dict."""
    with path.open() as f:
        data = yaml.safe_load(f)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected YAML mapping in {path}, got {type(data).__name__}")
    return data


def _resolve_agent_config(
    agent_ref: str | dict[str, Any],
) -> tuple[Path | None, dict[str, Any]]:
    """Resolve agent config reference to path and data.

    Args:
        agent_ref: Bare name, path string, or inline dict

    Returns:
        Tuple of (path or None if inline, config data dict)
    """
    if isinstance(agent_ref, dict):
        return None, agent_ref

    path = resolve_config_path(agent_ref, "agents")
    data = _load_yaml_file(path)
    return path, data


def _resolve_environment_config(
    env_ref: str | dict[str, Any],
) -> tuple[Path | None, dict[str, Any]]:
    """Resolve environment config reference to path and data.

    Args:
        env_ref: Bare name, path string, or inline dict

    Returns:
        Tuple of (path or None if inline, config data dict)
    """
    if isinstance(env_ref, dict):
        return None, env_ref

    path = resolve_config_path(env_ref, "environments")
    data = _load_yaml_file(path)
    return path, data


def _resolve_prompt(prompt_ref: str) -> tuple[Path, str]:
    """Resolve prompt reference to path and content.

    Args:
        prompt_ref: Bare name or path string

    Returns:
        Tuple of (path, prompt content string)
    """
    path = resolve_config_path(prompt_ref, "prompts")
    content = path.read_text(encoding="utf-8")
    return path, content


def _get_thinking_values(
    thinking: ThinkingPresetType | ThinkingConfig | dict[str, Any] | str,
) -> tuple[ThinkingPresetType | None, int | None]:
    """Extract thinking preset and max_tokens from various input forms.

    Args:
        thinking: The thinking config in various forms

    Returns:
        Tuple of (preset, max_tokens)
    """
    if isinstance(thinking, str):
        return thinking, None  # type: ignore[return-value]

    if isinstance(thinking, ThinkingConfig):
        return thinking.preset, thinking.max_tokens

    if isinstance(thinking, dict):
        return thinking.get("preset"), thinking.get("max_tokens")

    return None, None


def _build_interpolation_context(
    agent_data: dict[str, Any],
    env_data: dict[str, Any],
    prompt_path: Path,
    model: ModelConfig,
    thinking_preset: ThinkingPresetType | None,
) -> dict[str, Any]:
    """Build context dict for OmegaConf interpolation.

    This creates the values that will be available for ${...} interpolation
    in the output_path.

    Args:
        agent_data: Loaded agent config data
        env_data: Loaded environment config data
        prompt_path: Path to the prompt template
        model: Model configuration
        thinking_preset: The thinking preset value

    Returns:
        Dict with interpolation context
    """
    return {
        "agent": {
            "type": agent_data.get("type", "unknown"),
        },
        "env": {
            "name": env_data.get("name", "unknown"),
        },
        "prompt": prompt_path.stem,
        "model": {
            "name": model.name,
            "provider": model.provider,
        },
        "thinking": thinking_preset or "none",
    }


def _resolve_output_path(
    output_path_template: str,
    context: dict[str, Any],
) -> str:
    """Resolve output path template with interpolation.

    Args:
        output_path_template: The output path with ${...} placeholders
        context: The interpolation context dict

    Returns:
        Resolved output path string
    """
    # Create OmegaConf config with context + output_path
    cfg = OmegaConf.create({**context, "output_path": output_path_template})

    # Resolve interpolations
    OmegaConf.resolve(cfg)

    return str(cfg.output_path)


def _get_default_config() -> dict[str, Any]:
    """Get the default configuration as a dict."""
    return {
        "agent": "claude_code-2.0.51",
        "environment": "docker-python3.12-uv",
        "prompt": "just-solve",
        "model": {"provider": "anthropic", "name": "sonnet-4.5"},
        "thinking": "none",
        "pass_policy": "any",
        "problems": [],
        "one_shot": {
            "enabled": False,
            "prefix": "",
            "include_first_prefix": False,
        },
        "output_path": "outputs/${model.name}/${agent.type}_${prompt}_${thinking}_${now:%Y%m%dT%H%M}",
    }


def _normalize_problems(value: Any) -> list[str]:
    """Normalize problems config into a list of non-empty strings."""
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]

    if isinstance(value, (list, tuple)):
        problems: list[str] = []
        for item in value:
            if not isinstance(item, str):
                raise ValueError("Problems must be provided as strings")
            name = item.strip()
            if not name:
                raise ValueError("Problem names cannot be empty")
            problems.append(name)
        return problems

    raise ValueError(
        f"Invalid problems config type: {type(value).__name__} (expected list or string)"
    )


def load_run_config(
    config_path: Path | None = None,
    cli_flags: dict[str, Any] | None = None,
    cli_overrides: list[str] | None = None,
) -> ResolvedRunConfig:
    """Load and resolve run configuration with priority merging.

    Priority order (highest to lowest):
    1. CLI overrides (key=value syntax)
    2. CLI flags (--agent, --environment, etc.)
    3. Config file values
    4. Built-in defaults

    Args:
        config_path: Optional path to run configuration YAML file
        cli_flags: Dict of CLI flag values (agent, environment, prompt, model)
        cli_overrides: List of CLI overrides in "key=value" format

    Returns:
        Fully resolved ResolvedRunConfig ready for execution.

    Raises:
        FileNotFoundError: If referenced config files cannot be found.
        ValueError: If configuration is invalid.
    """
    # Ensure resolvers are registered
    register_resolvers()

    cli_flags = cli_flags or {}
    cli_overrides = cli_overrides or []

    # 1. Start with defaults
    defaults = OmegaConf.create(_get_default_config())

    # 2. Merge config file (if provided)
    if config_path is not None:
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")
        file_cfg = OmegaConf.load(config_path)
        cfg = OmegaConf.merge(defaults, file_cfg)
    else:
        cfg = defaults

    # 3. Merge CLI flags (non-None values only)
    flags_to_merge = {}
    for key, value in cli_flags.items():
        if value is not None:
            flags_to_merge[key] = value

    if flags_to_merge:
        flags_cfg = OmegaConf.create(flags_to_merge)
        cfg = OmegaConf.merge(cfg, flags_cfg)

    # 4. Apply CLI overrides
    for override in cli_overrides:
        key, value = parse_override(override)
        OmegaConf.update(cfg, key, value, merge=True)

    # Convert to container for easier manipulation
    cfg_dict = OmegaConf.to_container(cfg, resolve=False)
    if not isinstance(cfg_dict, dict):
        raise ValueError("Expected config to be a dict")

    # 5. Resolve references and load configs
    agent_path, agent_data = _resolve_agent_config(cfg_dict["agent"])
    env_path, env_data = _resolve_environment_config(cfg_dict["environment"])
    prompt_path, prompt_content = _resolve_prompt(cfg_dict["prompt"])

    # 6. Handle model config
    model_data = cfg_dict["model"]
    if isinstance(model_data, dict):
        model = ModelConfig(**model_data)
    else:
        raise ValueError(f"Invalid model config: {model_data}")

    # 7. Handle thinking config
    thinking_preset, thinking_max_tokens = _get_thinking_values(cfg_dict["thinking"])

    # 8. Handle pass_policy
    pass_policy_value = cfg_dict["pass_policy"]
    if isinstance(pass_policy_value, str):
        pass_policy = PassPolicy(pass_policy_value)
    elif isinstance(pass_policy_value, PassPolicy):
        pass_policy = pass_policy_value
    else:
        raise ValueError(f"Invalid pass_policy: {pass_policy_value}")

    # 9. Normalize problems list (optional)
    try:
        problems = _normalize_problems(cfg_dict.get("problems", []))
    except ValueError as exc:
        raise ValueError(f"Invalid problems configuration: {exc}") from exc

    # 10. Handle one_shot config
    try:
        one_shot_raw = cfg_dict.get("one_shot", {})
        if isinstance(one_shot_raw, OneShotConfig):
            one_shot = one_shot_raw
        elif isinstance(one_shot_raw, bool):
            one_shot = OneShotConfig(enabled=one_shot_raw)
        elif isinstance(one_shot_raw, dict):
            one_shot = OneShotConfig(**one_shot_raw)
        else:
            raise ValueError(
                f"Invalid one_shot config type: {type(one_shot_raw).__name__}"
            )
    except ValidationError as exc:
        raise ValueError(f"Invalid one_shot configuration: {exc}") from exc

    # 11. Build interpolation context and resolve output_path
    context = _build_interpolation_context(
        agent_data=agent_data,
        env_data=env_data,
        prompt_path=prompt_path,
        model=model,
        thinking_preset=thinking_preset,
    )
    output_path = _resolve_output_path(cfg_dict["output_path"], context)

    logger.debug(
        "Loaded run config",
        agent_path=str(agent_path) if agent_path else "inline",
        env_path=str(env_path) if env_path else "inline",
        prompt_path=str(prompt_path),
        model=f"{model.provider}/{model.name}",
        thinking=thinking_preset,
        output_path=output_path,
        problems=len(problems),
        one_shot=one_shot.enabled,
    )

    return ResolvedRunConfig(
        agent_config_path=agent_path,
        agent=agent_data,
        environment_config_path=env_path,
        environment=env_data,
        prompt_path=prompt_path,
        prompt_content=prompt_content,
        model=model,
        thinking=thinking_preset,
        thinking_max_tokens=thinking_max_tokens,
        pass_policy=pass_policy,
        problems=problems,
        output_path=output_path,
        one_shot=one_shot,
    )


def load_agent_config(
    agent_ref: str | dict[str, Any] | Path,
) -> tuple[Path | None, dict[str, Any]]:
    """Load agent config from reference.

    Public wrapper for _resolve_agent_config.

    Args:
        agent_ref: Bare name, path string, Path, or inline dict

    Returns:
        Tuple of (path or None if inline, config data dict)
    """
    if isinstance(agent_ref, Path):
        agent_ref = str(agent_ref)
    return _resolve_agent_config(agent_ref)


def load_environment_config(
    env_ref: str | dict[str, Any] | Path,
) -> tuple[Path | None, dict[str, Any]]:
    """Load environment config from reference.

    Public wrapper for _resolve_environment_config.

    Args:
        env_ref: Bare name, path string, Path, or inline dict

    Returns:
        Tuple of (path or None if inline, config data dict)
    """
    if isinstance(env_ref, Path):
        env_ref = str(env_ref)
    return _resolve_environment_config(env_ref)


def resolve_environment(
    source: Path | dict[str, Any] | str,
) -> EnvironmentSpec:
    """Resolve environment configuration to EnvironmentSpec.

    Unified function replacing all environment resolution variants.
    Handles Path, dict, and bare name. Raises typer.Exit on errors.

    Args:
        source: Environment reference (Path to YAML, dict, or bare name)

    Returns:
        Validated EnvironmentSpec (Docker or Local)

    Raises:
        typer.Exit: On file not found, YAML error, or validation error
    """
    from slop_code.execution import LocalEnvironmentSpec
    from slop_code.execution.docker_runtime import DockerEnvironmentSpec

    try:
        if isinstance(source, Path):
            source = str(source)
        _, env_data = _resolve_environment_config(source)

        env_type = env_data.get("type")
        if env_type == "docker":
            model_cls = DockerEnvironmentSpec
        elif env_type == "local":
            model_cls = LocalEnvironmentSpec
        else:
            raise ValueError(f"Invalid environment type: {env_type}")

        return model_cls.model_validate(env_data)

    except FileNotFoundError as e:
        typer.echo(typer.style(
            f"Environment configuration not found: {e}",
            fg=typer.colors.RED, bold=True,
        ))
        raise typer.Exit(1) from e
    except yaml.YAMLError as e:
        typer.echo(typer.style(
            f"YAML parsing error in environment configuration: {e}",
            fg=typer.colors.RED, bold=True,
        ))
        raise typer.Exit(1) from e
    except ValidationError as e:
        typer.echo(typer.style(
            f"Environment configuration validation failed:\n{e}",
            fg=typer.colors.RED, bold=True,
        ))
        raise typer.Exit(1) from e
    except ValueError as e:
        typer.echo(typer.style(
            f"Environment configuration error: {e}",
            fg=typer.colors.RED, bold=True,
        ))
        raise typer.Exit(1) from e
