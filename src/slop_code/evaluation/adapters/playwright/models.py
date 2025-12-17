"""Typed models used by the Playwright adapter."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from slop_code.evaluation.adapters.models import CaseResult

if TYPE_CHECKING:
    from playwright.sync_api import BrowserContext
    from playwright.sync_api import Page
    from playwright.sync_api import Playwright

StepStatus = Literal["ok", "error", "skipped"]

ActionTypeLiteral = Literal[
    "navigate",
    "click",
    "fill",
    "upload_file",
    "press",
    "capture_relative_position",
    "capture_count",
]


class PlaywrightResult(CaseResult):
    """Result from executing a Playwright case."""

    type: Literal["playwright"] = Field(default="playwright", frozen=True)  # type: ignore
    url: str | None = None
    page_title: str | None = None


class PlaywrightContext(BaseModel):
    """Wrapper around Playwright constructs with shared metadata."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)
    playwright: Playwright
    browser: BrowserContext
    page: Page
    base_url: str

    def close(self) -> None:
        """Close the playwright context."""
        self.browser.close()
