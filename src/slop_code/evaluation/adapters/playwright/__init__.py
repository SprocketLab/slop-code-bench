"""Playwright-based adapter for browser-oriented evaluation cases."""

from slop_code.evaluation.adapters.playwright.actions import ClickAction
from slop_code.evaluation.adapters.playwright.actions import FillAction
from slop_code.evaluation.adapters.playwright.actions import NavigateAction
from slop_code.evaluation.adapters.playwright.actions import PlaywrightAction
from slop_code.evaluation.adapters.playwright.actions import PressAction
from slop_code.evaluation.adapters.playwright.adapter import PlaywrightAdapter
from slop_code.evaluation.adapters.playwright.adapter import (
    PlaywrightAdapterConfig,
)
from slop_code.evaluation.adapters.playwright.adapter import PlaywrightCase
from slop_code.evaluation.adapters.playwright.models import PlaywrightContext
from slop_code.evaluation.adapters.playwright.models import PlaywrightResult

__all__ = [
    "PlaywrightAdapter",
    "PlaywrightAdapterConfig",
    "PlaywrightCase",
    "PlaywrightResult",
    "PlaywrightAction",
    "PlaywrightContext",
]
