"""Config loading pipeline with two-tier path resolution and OmegaConf merging."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer
import yaml
from omegaconf import OmegaConf
from pydantic import ValidationError

from slop_code.common import CONFIG_FILENAME
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
    searched.extend(
        [
            str(package_path),
            str(cwd_path),
            str(cwd_category_path),
        ]
    )
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
        raise ValueError(
            f"Expected YAML mapping in {path}, got {type(data).__name__}"
        )
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
            "version": agent_data.get("version"),  # Can be None
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


def _resolve_save_template(
    save_template: str,
    context: dict[str, Any],
) -> str:
    """Resolve output path template with interpolation.

    Handles the case where agent.version is None by cleaning up
    artifacts like "-None" or "None_" from the resolved string.

    Args:
        save_template: The output path template with ${...} placeholders
        context: The interpolation context dict

    Returns:
        Resolved output path string with clean version handling
    """
    # Create OmegaConf config with context + save_template
    cfg = OmegaConf.create({**context, "save_template": save_template})

    # Resolve interpolations
    OmegaConf.resolve(cfg)

    resolved = str(cfg.save_template)

    # Clean up version artifacts when version is None
    # OmegaConf renders None as the string "None"
    resolved = resolved.replace("-None", "").replace("None_", "")

    # Clean up any resulting double underscores or trailing underscores
    while "__" in resolved:
        resolved = resolved.replace("__", "_")

    # Clean up any trailing underscore before path separator or at end
    resolved = resolved.replace("_/", "/").rstrip("_")

    return resolved


def _get_default_config() -> dict[str, Any]:
    """Get the default configuration as a dict."""
    return {
        "agent": "claude_code",
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
        "save_dir": "outputs",
        "save_template": "${model.name}/${agent.type}-${agent.version}_${prompt}_${thinking}_${now:%Y%m%dT%H%M}",
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

    # 4. Separate agent-specific overrides from top-level overrides
    # Agent overrides can be specified as either "agent.key=value" or just "key=value"
    # where key is a known agent config field (version, cost_limits, etc.)
    agent_config_fields = {"version", "cost_limits", "binary", "permission_mode"}
    agent_overrides: dict[str, Any] = {}
    top_level_overrides: list[str] = []

    for override in cli_overrides:
        key, value = parse_override(override)
        if key.startswith("agent."):
            # Explicit agent prefix - strip it and store
            agent_key = key[6:]  # Remove "agent." prefix
            agent_overrides[agent_key] = value
        elif key.split(".")[0] in agent_config_fields:
            # Shorthand: version=X -> agent.version=X
            agent_overrides[key] = value
        else:
            top_level_overrides.append(override)

    # 5. Apply top-level CLI overrides
    for override in top_level_overrides:
        key, value = parse_override(override)
        OmegaConf.update(cfg, key, value, merge=True)

    # Convert to container for easier manipulation
    cfg_dict = OmegaConf.to_container(cfg, resolve=False)
    if not isinstance(cfg_dict, dict):
        raise ValueError("Expected config to be a dict")

    # 6. Resolve references and load configs
    agent_path, agent_data = _resolve_agent_config(cfg_dict["agent"])

    # 7. Merge agent overrides into loaded agent data
    if agent_overrides:
        for key, value in agent_overrides.items():
            # Handle nested keys like "cost_limits.step_limit"
            parts = key.split(".")
            target = agent_data
            for part in parts[:-1]:
                if part not in target:
                    target[part] = {}
                target = target[part]
            target[parts[-1]] = value
        logger.debug(
            "Applied agent config overrides",
            overrides=agent_overrides,
        )
    env_path, env_data = _resolve_environment_config(cfg_dict["environment"])
    prompt_path, prompt_content = _resolve_prompt(cfg_dict["prompt"])

    # 8. Handle model config
    model_data = cfg_dict["model"]
    if isinstance(model_data, dict):
        model = ModelConfig(**model_data)
    else:
        raise ValueError(f"Invalid model config: {model_data}")

    # 9. Handle thinking config
    thinking_preset, thinking_max_tokens = _get_thinking_values(
        cfg_dict["thinking"]
    )

    # 10. Handle pass_policy
    pass_policy_value = cfg_dict["pass_policy"]
    if isinstance(pass_policy_value, str):
        pass_policy = PassPolicy(pass_policy_value)
    elif isinstance(pass_policy_value, PassPolicy):
        pass_policy = pass_policy_value
    else:
        raise ValueError(f"Invalid pass_policy: {pass_policy_value}")

    # 11. Normalize problems list (optional)
    try:
        problems = _normalize_problems(cfg_dict.get("problems", []))
    except ValueError as exc:
        raise ValueError(f"Invalid problems configuration: {exc}") from exc

    # 12. Handle one_shot config
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

    # 13. Build interpolation context and resolve output_path
    context = _build_interpolation_context(
        agent_data=agent_data,
        env_data=env_data,
        prompt_path=prompt_path,
        model=model,
        thinking_preset=thinking_preset,
    )

    # 14. Resolve output path from root and template
    save_dir = cfg_dict.get("save_dir", "outputs")
    save_template_raw = cfg_dict.get(
        "save_template",
        "${model.name}/${agent.type}-${agent.version}_${prompt}_${thinking}_${now:%Y%m%dT%H%M}",
    )
    save_template = _resolve_save_template(save_template_raw, context)

    # Combine root and template, handling empty root case
    if save_dir:
        output_path = f"{save_dir}/{save_template}"
    else:
        output_path = save_template

    logger.debug(
        "Loaded run config",
        agent_path=str(agent_path) if agent_path else "inline",
        env_path=str(env_path) if env_path else "inline",
        prompt_path=str(prompt_path),
        model=f"{model.provider}/{model.name}",
        thinking=thinking_preset,
        save_dir=save_dir,
        save_template=save_template,
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
        save_dir=save_dir,
        save_template=save_template,
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
        typer.echo(
            typer.style(
                f"Environment configuration not found: {e}",
                fg=typer.colors.RED,
                bold=True,
            )
        )
        raise typer.Exit(1) from e
    except yaml.YAMLError as e:
        typer.echo(
            typer.style(
                f"YAML parsing error in environment configuration: {e}",
                fg=typer.colors.RED,
                bold=True,
            )
        )
        raise typer.Exit(1) from e
    except ValidationError as e:
        typer.echo(
            typer.style(
                f"Environment configuration validation failed:\n{e}",
                fg=typer.colors.RED,
                bold=True,
            )
        )
        raise typer.Exit(1) from e
    except ValueError as e:
        typer.echo(
            typer.style(
                f"Environment configuration error: {e}",
                fg=typer.colors.RED,
                bold=True,
            )
        )
        raise typer.Exit(1) from e


def load_config_from_run_dir(run_dir: Path) -> ResolvedRunConfig:
    """Load ResolvedRunConfig from a saved run directory.

    Loads the config.yaml file that was saved during a previous run,
    reconstructs the ResolvedRunConfig with proper Path objects, and
    returns it ready for resuming.

    Args:
        run_dir: Path to existing run directory containing config.yaml

    Returns:
        ResolvedRunConfig loaded from saved config

    Raises:
        FileNotFoundError: If config.yaml doesn't exist in run_dir
        ValueError: If config is invalid or corrupt
    """
    config_path = run_dir / CONFIG_FILENAME
    if not config_path.exists():
        raise FileNotFoundError(
            f"No config.yaml found in {run_dir}. "
            "This directory may not be a valid run directory."
        )

    try:
        with config_path.open() as f:
            config_dict = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ValueError(f"Failed to parse config.yaml: {e}") from e

    if config_dict is None:
        raise ValueError("config.yaml is empty")

    if not isinstance(config_dict, dict):
        raise ValueError(
            f"Expected config.yaml to contain a mapping, got {type(config_dict).__name__}"
        )

    # Convert string paths back to Path objects where needed
    path_fields = ["agent_config_path", "environment_config_path", "prompt_path"]
    for field in path_fields:
        if field in config_dict and config_dict[field] is not None:
            config_dict[field] = Path(config_dict[field])

    # Handle model as a nested dict -> ModelConfig
    if "model" in config_dict and isinstance(config_dict["model"], dict):
        config_dict["model"] = ModelConfig(**config_dict["model"])

    # Handle pass_policy as string -> enum
    if "pass_policy" in config_dict and isinstance(config_dict["pass_policy"], str):
        config_dict["pass_policy"] = PassPolicy(config_dict["pass_policy"])

    # Handle one_shot as dict -> OneShotConfig
    if "one_shot" in config_dict and isinstance(config_dict["one_shot"], dict):
        config_dict["one_shot"] = OneShotConfig(**config_dict["one_shot"])

    # Backward compatibility: handle old configs with only output_path
    # New configs have save_dir and save_template
    if "output_path" in config_dict and "save_dir" not in config_dict:
        # Old format - set empty strings for root/template since output_path is the full path
        config_dict["save_dir"] = ""
        config_dict["save_template"] = ""

    try:
        return ResolvedRunConfig.model_validate(config_dict)
    except ValidationError as e:
        raise ValueError(f"Invalid config.yaml: {e}") from e
