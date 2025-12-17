"""Action primitives executed by the Playwright adapter."""

from __future__ import annotations

import time
from collections.abc import Generator
from typing import Annotated, Any, Literal
from urllib.parse import urljoin

from playwright.sync_api import Error
from playwright.sync_api import FloatRect
from playwright.sync_api import Locator
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import expect
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from slop_code.evaluation.adapters.playwright.models import ActionTypeLiteral
from slop_code.evaluation.adapters.playwright.models import PlaywrightContext
from slop_code.logging import get_logger

logger = get_logger(__name__)


class LocatorSpec(BaseModel):
    """Spec for a locator."""

    target: str
    locator_type: Literal["text", "label", "role", "locator"] = "locator"

    def get_locator(self, context: PlaywrightContext) -> Locator:
        """Resolve the locator from the target selector."""
        match self.locator_type:
            case "text":
                return context.page.get_by_text(self.target)
            case "label":
                return context.page.get_by_label(self.target)
            case "role":
                return context.page.get_by_role(self.target)  # type: ignore
            case "locator":
                return context.page.locator(self.target)
            case _:
                raise ValueError(f"Invalid locator type: {self.locator_type}")


class ExtractorSpec(LocatorSpec):
    """Base class for actions that operate on a locator."""

    target: str
    locator_type: Literal["text", "label", "role", "locator"] = "locator"
    text: bool = False
    inner_html: bool = False
    visible: bool = False
    count: bool = False
    attributes: list[str] | None = None

    def get_text(self, locator: Locator) -> str | None:
        """Get the text of the locator."""
        try:
            return locator.inner_text()
        except (Error, PlaywrightTimeoutError):
            return None

    def get_inner_html(self, locator: Locator) -> str | None:
        """Get the inner html of the locator."""
        try:
            return locator.inner_html()
        except (Error, PlaywrightTimeoutError):
            return None

    def __call__(
        self, context: PlaywrightContext, prefix: str
    ) -> dict[str, Any]:
        locator = self.get_locator(context)

        out = {}
        if self.text:
            out[f"{prefix}.text"] = self.get_text(locator)
        if self.inner_html:
            out[f"{prefix}.inner_html"] = self.get_inner_html(locator)
        if self.attributes:
            out.update(self.get_attributes(locator, self.attributes, prefix))
        if self.visible:
            out[f"{prefix}.is_visible"] = self.is_visible(locator)
        if self.count:
            out[f"{prefix}.count"] = locator.count()
        return out

    def is_visible(
        self,
        locator: Locator,
    ) -> bool:
        """Ensure the locator is visible prior to performing the action."""

        try:
            expect(locator).to_be_visible()
            return True
        except AssertionError:
            return False
        except PlaywrightTimeoutError:
            return False

    @staticmethod
    def get_attributes(
        locator: Locator,
        names: list[str],
        prefix: str,
    ) -> dict[str, Any]:
        """Capture element attributes as a JSON-serializable mapping."""

        out = {}
        for name in names or []:
            try:
                out[f"{prefix}.{name}"] = locator.get_attribute(name)
            except (Error, PlaywrightTimeoutError):
                out[f"{prefix}.{name}"] = None
        return out


class PlaywrightAction(BaseModel):
    """Base class for Playwright actions."""

    type: ActionTypeLiteral
    alias: str
    target: LocatorSpec
    requires_visibility: bool = True
    pre_outputs: dict[str, ExtractorSpec] = Field(default_factory=dict)
    post_outputs: dict[str, ExtractorSpec] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    def execute(
        self,
        locator: Locator,
        context: PlaywrightContext,
    ) -> dict[str, Any]:
        """Execute the action for the given case."""
        raise NotImplementedError

    def get_outputs(
        self,
        output_dict: dict[str, Any],
        context: PlaywrightContext,
        prefix: str,
    ) -> Generator[tuple[str, Any], None, None]:
        for store_as, locator_spec in output_dict.items():
            yield from locator_spec(context, f"{prefix}_{store_as}").items()

    def __call__(self, context: PlaywrightContext) -> dict[str, Any]:
        locator = self.target.get_locator(context)
        if self.requires_visibility and not self.is_visible(locator):
            return {
                f"{self.alias}.status": "error",
                f"{self.alias}.details": "Locator is not visible.",
            }
        result = dict(self.get_outputs(self.pre_outputs, context, "pre"))
        result.update(self.execute(locator, context))
        result.update(
            dict(self.get_outputs(self.post_outputs, context, "post"))
        )
        return {f"{self.alias}.{k}": v for k, v in result.items()}

    def is_visible(self, locator: Locator) -> bool:
        """Check if the locator is visible."""
        try:
            expect(locator).to_be_visible()
            return True
        except (Error, AssertionError, PlaywrightTimeoutError):
            return False


class NavigateAction(PlaywrightAction):
    """Navigate to a URL."""

    type: Literal["navigate"] = Field(frozen=True, default="navigate")  # type: ignore[assignment]
    value: Any
    requires_visibility: bool = Field(default=False, frozen=True)

    def execute(
        self,
        locator: Locator,
        context: PlaywrightContext,
    ) -> dict[str, Any]:
        url = urljoin(context.base_url, str(self.value))
        start = time.perf_counter()
        _ = locator
        try:
            response = context.page.goto(str(url))
        except (
            Error,
            PlaywrightTimeoutError,
        ) as exc:  # pragma: no cover - surfaced in result payload
            duration_ms = (time.perf_counter() - start) * 1000
            return {
                "url": url,
                "status_code": None,
                "duration_ms": duration_ms,
                "error": str(exc),
            }

        duration_ms = (time.perf_counter() - start) * 1000
        final_url = response.url if response else context.page.url
        status_code = response.status if response else None

        data: dict[str, Any] = {"url": final_url}
        if status_code is not None:
            data["status_code"] = status_code

        return {
            "url": final_url,
            "status_code": status_code,
            "duration_ms": duration_ms,
        }


class ClickAction(PlaywrightAction):
    """Click on a resolved locator."""

    type: Literal["click"] = Field(frozen=True, default="click")  # type: ignore[assignment]
    click_kwargs: dict[str, Any] = Field(default_factory=dict)

    def execute(
        self,
        locator: Locator,
        context: PlaywrightContext,
    ) -> dict[str, Any]:
        _ = context

        try:
            locator.click(**self.click_kwargs)
        except (Error, PlaywrightTimeoutError) as exc:
            return {
                "status": "error",
                "details": str(exc),
            }

        return {}


class FillAction(PlaywrightAction):
    """Fill a field with the provided value."""

    type: Literal["fill"] = Field(frozen=True, default="fill")
    value: Any
    clear: bool = False
    fill_kwargs: dict[str, Any] = Field(default_factory=dict)
    requires_visibility: bool = Field(default=False, frozen=True)

    def execute(
        self,
        locator: Locator,
        context: PlaywrightContext,
    ) -> dict[str, Any]:
        _ = context
        text_value = "" if self.value is None else str(self.value)
        try:
            if self.clear:
                locator.clear()

            locator.fill(text_value, **self.fill_kwargs)
        except (Error, PlaywrightTimeoutError) as exc:
            return {
                "status": "error",
                "details": str(exc),
            }
        return {}


class UploadFileAction(PlaywrightAction):
    """Upload files to an input element."""

    type: Literal["upload_file"] = Field(
        frozen=True,
        default="upload_file",
    )  # type: ignore[assignment]
    files: list[str] | str
    set_input_files_kwargs: dict[str, Any] = Field(default_factory=dict)

    def execute(
        self,
        locator: Locator,
        context: PlaywrightContext,
    ) -> dict[str, Any]:
        _ = context
        file_inputs = (
            [self.files] if isinstance(self.files, str) else list(self.files)
        )
        if not file_inputs:
            return {
                "status": "error",
                "details": "Upload action requires at least one file path.",
            }

        try:
            locator.set_input_files(file_inputs, **self.set_input_files_kwargs)
        except (Error, PlaywrightTimeoutError) as exc:
            return {
                "status": "error",
                "details": str(exc),
            }

        return {}


class PressAction(PlaywrightAction):
    """Press a key on the target locator."""

    type: Literal["press"] = Field(frozen=True, default="press")  # type: ignore[assignment]
    value: str
    press_kwargs: dict[str, Any] = Field(default_factory=dict)

    def execute(
        self,
        locator: Locator,
        context: PlaywrightContext,
    ) -> dict[str, Any]:
        _ = context

        try:
            locator.press(str(self.value), **self.press_kwargs)
        except (Error, PlaywrightTimeoutError) as exc:
            return {
                "status": "error",
                "details": str(exc),
            }

        return {}


class CaptureRelativePositionAction(PlaywrightAction):
    """Capture relative positioning metrics between two locators."""

    type: Literal["capture_relative_position"] = Field(
        frozen=True,
        default="capture_relative_position",
    )  # type: ignore[assignment]
    target_selector: LocatorSpec
    reference_selector: LocatorSpec
    metrics: dict[str, Any] = Field(default_factory=dict)

    def execute(
        self,
        locator: Locator,
        context: PlaywrightContext,
    ) -> dict[str, Any]:
        reference_locator = self.reference_selector.get_locator(context)

        try:
            target_box = locator.bounding_box()
            reference_box = reference_locator.bounding_box()
        except Exception as exc:
            return {
                "status": "error",
                "details": str(exc),
            }

        if target_box is None or reference_box is None:
            return {
                "status": "error",
                "details": "Unable to resolve bounding boxes for relative position capture.",
            }

        return self._compute_relative_metrics(target_box, reference_box)

    @staticmethod
    def _compute_relative_metrics(
        target_box: FloatRect,
        reference_box: FloatRect,
    ) -> dict[str, Any]:
        """Derive deterministic relative positioning metrics."""

        is_above = (target_box["y"] + target_box["height"]) <= reference_box[
            "y"
        ]
        is_below = target_box["y"] >= (
            reference_box["y"] + reference_box["height"]
        )
        is_left = (target_box["x"] + target_box["width"]) <= reference_box["x"]
        is_right = target_box["x"] >= (
            reference_box["x"] + reference_box["width"]
        )

        return {
            "is_above": is_above,
            "is_below": is_below,
            "is_left": is_left,
            "is_right": is_right,
        }


class CaptureCountAction(PlaywrightAction):
    """Capture the number of locator matches."""

    type: Literal["capture_count"] = Field(frozen=True, default="capture_count")  # type: ignore[assignment]
    requires_visibility: bool = Field(default=False, frozen=True)

    def execute(
        self,
        locator: Locator,
        context: PlaywrightContext,
    ) -> dict[str, Any]:
        try:
            count = locator.count()
        except Exception as exc:
            return {
                "status": "error",
                "details": str(exc),
            }

        return {
            "count": count,
        }


PlaywrightActionType = Annotated[
    NavigateAction
    | ClickAction
    | FillAction
    | UploadFileAction
    | PressAction
    | CaptureRelativePositionAction
    | CaptureCountAction,
    Field(discriminator="type"),
]
