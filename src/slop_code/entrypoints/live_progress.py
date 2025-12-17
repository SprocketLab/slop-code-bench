"""Utilities for rendering live progress tables in CLI entrypoints."""

from __future__ import annotations

from collections.abc import Callable
from collections.abc import Iterable
from collections.abc import Iterator
from contextlib import contextmanager
from types import TracebackType

from rich.console import Console
from rich.console import Group
from rich.console import RenderableType
from rich.live import Live
from rich.text import Text

RenderableFactory = Callable[[], Iterable[RenderableType]]


class LiveProgressDisplay:
    """Manage a Rich live display using a renderable factory callback."""

    def __init__(
        self,
        renderable_factory: RenderableFactory,
        console: Console,
        *,
        refresh_per_second: float = 4.0,
        vertical_overflow: str = "visible",
        transient: bool = True,
        placeholder: RenderableType | None = None,
    ):
        self._renderable_factory = renderable_factory
        self._console = console
        self._refresh_per_second = refresh_per_second
        self._vertical_overflow = vertical_overflow
        self._transient = transient
        self._placeholder = placeholder or Text(
            "Waiting for progress updates...", style="dim"
        )
        self._live: Live | None = None

    def _build_group(self) -> Group:
        renderables = list(self._renderable_factory())
        if not renderables:
            renderables = [self._placeholder]
        return Group(*renderables)

    def __enter__(self) -> LiveProgressDisplay:
        self._live = Live(
            self._build_group(),
            refresh_per_second=self._refresh_per_second,
            console=self._console,
            vertical_overflow=self._vertical_overflow,
            transient=self._transient,
        )
        self._live.__enter__()
        return self

    def update(self) -> None:
        """Refresh the live display using the renderable factory."""
        if self._live is not None:
            self._live.update(self._build_group())

    def __exit__(
        self,
        exc_type: type | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._live is not None:
            self._live.__exit__(exc_type, exc_value, traceback)


@contextmanager
def maybe_live_progress(
    *,
    enabled: bool,
    renderable_factory: RenderableFactory,
    console: Console,
    **kwargs,
) -> Iterator[LiveProgressDisplay | None]:
    """Context manager that yields a LiveProgressDisplay when enabled."""

    if not enabled:
        yield None
        return

    with LiveProgressDisplay(
        renderable_factory=renderable_factory,
        console=console,
        **kwargs,
    ) as display:
        yield display
