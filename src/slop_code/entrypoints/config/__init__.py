"""Unified run configuration system using Pydantic + OmegaConf.

This package provides a hydra-esque configuration system for the run_agent command.
Users can specify a config file and override values via `key=value` syntax.

Priority order (highest to lowest):
1. CLI overrides: key=value or key.nested=value
2. CLI flags: --agent, --environment, --prompt, --model
3. Config file values
4. Built-in defaults
"""

from __future__ import annotations

from slop_code.entrypoints.config.loader import load_run_config
from slop_code.entrypoints.config.resolvers import register_resolvers
from slop_code.entrypoints.config.run_config import ModelConfig
from slop_code.entrypoints.config.run_config import OneShotConfig
from slop_code.entrypoints.config.run_config import ResolvedRunConfig
from slop_code.entrypoints.config.run_config import RunConfig

__all__ = [
    "ModelConfig",
    "OneShotConfig",
    "ResolvedRunConfig",
    "RunConfig",
    "load_run_config",
    "register_resolvers",
]
