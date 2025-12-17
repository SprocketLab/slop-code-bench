"""Playwright adapter for browser-based evaluation cases."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal
from urllib.parse import urljoin

from playwright.sync_api import Browser
from playwright.sync_api import BrowserContext
from playwright.sync_api import Page
from playwright.sync_api import sync_playwright
from pydantic import Field

from slop_code.evaluation.adapters.api import APIAdapter
from slop_code.evaluation.adapters.api import APIAdapterConfig
from slop_code.evaluation.adapters.base import ADAPTER_REGISTRY
from slop_code.evaluation.adapters.models import BaseCase
from slop_code.evaluation.adapters.playwright.actions import (
    PlaywrightActionType,
)
from slop_code.evaluation.adapters.playwright.models import PlaywrightContext
from slop_code.evaluation.adapters.playwright.models import PlaywrightResult
from slop_code.logging import get_logger

logger = get_logger(__name__)

ArtifactPolicy = Literal["off", "retain-on-failure", "always"]


class PlaywrightCase(BaseCase):
    """Case specification for Playwright-driven browser interactions."""

    reset_context: bool = False
    steps: list[PlaywrightActionType]


class PlaywrightAdapterConfig(APIAdapterConfig):
    """Configuration for the Playwright adapter."""

    type: Literal["playwright"] = "playwright"
    browser_channel: Literal["chrome", "chrome-beta", "msedge"] = "chrome"
    start_page: str = ""
    default_timeout_ms: int = 30_000
    screenshot: ArtifactPolicy = "retain-on-failure"
    trace: ArtifactPolicy = "retain-on-failure"
    video: ArtifactPolicy = "off"
    storage_state: Path | None = None
    browser_kwargs: dict[str, Any] = Field(default_factory=dict)


@ADAPTER_REGISTRY.register("playwright")
class PlaywrightAdapter(APIAdapter):
    """Adapter for executing browser-based test cases via Playwright."""

    case_class = PlaywrightCase
    result_class = PlaywrightResult
    config_class = PlaywrightAdapterConfig

    def __init__(
        self,
        *args,
        **kwargs,
    ) -> None:
        """Initialize the adapter with the API adapter's wiring."""
        super().__init__(*args, **kwargs)
        self.cfg: PlaywrightAdapterConfig
        self._playwright: Any = None
        self._context: PlaywrightContext | None = None

    @property
    def context(self) -> PlaywrightContext:
        if self._context is None:
            raise RuntimeError("Context is not initialized")
        return self._context

    def _on_enter(self) -> None:
        """Start the API server (via super) and boot the headless browser."""
        super()._on_enter()
        self._context = self._start_browser()

    def _on_exit(self, exc_type, exc, tb) -> None:
        """Tear down browser resources before delegating to the base adapter."""
        logger.debug("Tearing down playwright resources")
        if self._context is not None:
            self._context.close()
        super()._on_exit(exc_type, exc, tb)

    @staticmethod
    def make_case(
        case_dict: dict[str, Any],
    ) -> tuple[PlaywrightCase, PlaywrightResult]:  # type: ignore
        """Create a PlaywrightCase and expected payload from a raw dictionary."""
        payload = dict(case_dict)
        expected_payload = payload.pop("expected", {})

        case = PlaywrightCase.model_validate(payload)
        if isinstance(expected_payload, PlaywrightResult):
            expected = expected_payload
        else:
            expected = PlaywrightResult.model_validate(expected_payload)
        return case, expected

    def run_case(self, case: PlaywrightCase) -> PlaywrightResult:  # type: ignore
        """Execute a single Playwright case.

        Args:
            case: The case to execute.

        Returns:
            PlaywrightResult containing execution details.
        """
        # Resolve placeholders in case fields before execution
        resolved_case = self._resolve_case_placeholders(case)

        logger.debug("Running playwright case", case_id=resolved_case.id)
        if resolved_case.reset_context or self._context is None:
            if self._context is not None:
                logger.debug("Closing existing context")
                self._context.close()
            logger.debug("Resetting playwright context")
            try:
                self._context = self._start_browser()
            # TODO: Narrow down the exception to only the one we care about
            except Exception as e:
                logger.debug("Unable to reset playwright context", error=e)
                return PlaywrightResult(
                    type="playwright",
                    resource_path=str(self.session.working_dir),
                    adapter_error=True,
                    stderr=str(e),
                    url=self.base_url,
                    page_title=self.context.page.title(),
                )
        step_results: dict[str, Any] = {}

        for step in resolved_case.steps:
            result = step(self._context)
            step_results.update(result)

        result = PlaywrightResult(
            type="playwright",
            output=step_results,
            resource_path=str(self.session.working_dir),
            url=self._context.page.url,
            page_title=self._context.page.title(),
        )

        return result

    def _resolve_case_placeholders(
        self, case: PlaywrightCase
    ) -> PlaywrightCase:
        """Resolve static asset placeholders in case fields.

        Args:
            case: Original case with potential placeholders.

        Returns:
            New case instance with placeholders resolved.
        """
        case_dict = case.model_dump()
        resolved_dict = self.session.resolve_static_placeholders(case_dict)
        return PlaywrightCase.model_validate(resolved_dict)

    def _start_browser(self) -> PlaywrightContext:
        """Launch the browser instance."""

        base_url = self.base_url
        if self.cfg.start_page:
            start_page = urljoin(base_url, self.cfg.start_page)
        else:
            start_page = base_url
        logger.debug(
            "Starting browser",
            browser_channel=self.cfg.browser_channel,
            browser_kwargs=self.cfg.browser_kwargs,
            base_url=base_url,
            start_page=start_page,
        )

        playwright = sync_playwright().start()

        # TODO: Support other browser channels
        browser: Browser = playwright.chromium.launch(
            channel=self.cfg.browser_channel,
            headless=True,
        )
        context: BrowserContext = browser.new_context(
            **{
                "viewport": {"width": 1280, "height": 720},
                **self.cfg.browser_kwargs,
            },
        )

        context.set_default_timeout(self.cfg.default_timeout_ms)
        page: Page = context.new_page()
        page.goto(start_page)
        return PlaywrightContext(
            playwright=playwright,
            browser=context,
            page=page,
            base_url=base_url,
        )
