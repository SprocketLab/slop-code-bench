"""Tests for OmegaConf resolvers."""

from __future__ import annotations

import re
from datetime import datetime

from omegaconf import OmegaConf

from slop_code.entrypoints.config.resolvers import register_resolvers
from slop_code.entrypoints.config.resolvers import reset_resolvers


class TestNowResolver:
    def setup_method(self):
        """Reset resolvers before each test."""
        reset_resolvers()
        register_resolvers()

    def test_default_format(self):
        cfg = OmegaConf.create({"path": "${now:}"})
        OmegaConf.resolve(cfg)

        # Default format is %Y%m%dT%H%M
        assert re.match(r"^\d{8}T\d{4}$", cfg.path)

    def test_custom_format(self):
        cfg = OmegaConf.create({"path": "${now:%Y-%m-%d}"})
        OmegaConf.resolve(cfg)

        # Should match YYYY-MM-DD format
        assert re.match(r"^\d{4}-\d{2}-\d{2}$", cfg.path)

    def test_timestamp_is_current(self):
        before = datetime.now()
        cfg = OmegaConf.create({"path": "${now:%Y%m%d}"})
        OmegaConf.resolve(cfg)
        after = datetime.now()

        # The date should be today
        resolved_date = cfg.path
        assert resolved_date in [
            before.strftime("%Y%m%d"),
            after.strftime("%Y%m%d"),
        ]

    def test_resolver_is_idempotent(self):
        """Calling register_resolvers multiple times should not error."""
        register_resolvers()
        register_resolvers()
        register_resolvers()

        cfg = OmegaConf.create({"path": "${now:}"})
        OmegaConf.resolve(cfg)
        assert re.match(r"^\d{8}T\d{4}$", cfg.path)


class TestInterpolationContext:
    def setup_method(self):
        reset_resolvers()
        register_resolvers()

    def test_nested_interpolation(self):
        """Test that nested config values can be interpolated."""
        cfg = OmegaConf.create(
            {
                "model": {"name": "sonnet-4.5", "provider": "anthropic"},
                "output_path": "outputs/${model.name}/${model.provider}",
            }
        )
        OmegaConf.resolve(cfg)

        assert cfg.output_path == "outputs/sonnet-4.5/anthropic"

    def test_combined_interpolation(self):
        """Test combining multiple interpolations in one string."""
        cfg = OmegaConf.create(
            {
                "agent": {"type": "claude_code"},
                "prompt": "just-solve",
                "thinking": "medium",
                "model": {"name": "sonnet-4.5"},
                "output_path": "${agent.type}_${prompt}_${thinking}_${model.name}",
            }
        )
        OmegaConf.resolve(cfg)

        assert cfg.output_path == "claude_code_just-solve_medium_sonnet-4.5"

    def test_now_combined_with_other_interpolations(self):
        """Test ${now:} works alongside other interpolations."""
        cfg = OmegaConf.create(
            {
                "model": {"name": "test"},
                "output_path": "outputs/${model.name}/${now:%Y%m%d}",
            }
        )
        OmegaConf.resolve(cfg)

        parts = cfg.output_path.split("/")
        assert parts[0] == "outputs"
        assert parts[1] == "test"
        assert re.match(r"^\d{8}$", parts[2])
