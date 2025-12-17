"""Progress rendering for problem execution display.

This module provides Rich-based rendering for displaying problem execution
progress in the terminal.
"""

from __future__ import annotations

from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

from slop_code.agent_runner import AgentStateEnum
from slop_code.entrypoints.problem_runner.models import ProblemState
from slop_code.entrypoints.problem_runner.state import ProblemStateTracker
from slop_code.logging import get_logger

logger = get_logger(__name__)

STATE_STYLES: dict[AgentStateEnum, str] = {
    AgentStateEnum.PENDING: "grey50",
    AgentStateEnum.INITIALIZED: "cyan",
    AgentStateEnum.RUNNING: "green",
    AgentStateEnum.EVALUATING: "magenta",
    AgentStateEnum.COMPLETED: "bold green",
    AgentStateEnum.FAILED: "yellow",
    AgentStateEnum.ERROR: "bold red",
    AgentStateEnum.HIT_RATE_LIMITED: "bold yellow",
}

_ACTIVE_SPINNER_STATES = frozenset(
    {
        AgentStateEnum.RUNNING,
        AgentStateEnum.EVALUATING,
    }
)


class ProblemProgressRenderer:
    """Render problem progress rows for live display."""

    STATE_LABEL_WIDTH = 16
    PROGRESS_BAR_WIDTH = 10
    PROBLEM_NAME_WIDTH = 30

    def __init__(self, state: ProblemStateTracker) -> None:
        """Initialize renderer with state tracker.

        Args:
            state: Tracker containing problem states to render
        """
        self._state = state
        self._spinners: dict[str, Spinner] = {}
        self.placeholder = Text("Waiting for progress updates...", style="dim")

    def render(self) -> list[Table]:
        """Render all problem rows as Rich tables."""
        rows: list[Table] = []
        for problem, state in self._state.problems():
            row = self._build_problem_row(problem, state)
            if row is not None:
                rows.append(row)
        return rows

    def _render_progress_bar(self, completed: int, total: int) -> str:
        """Render a text progress bar."""
        if total <= 0:
            placeholder = "?" * self.PROGRESS_BAR_WIDTH
            return f"[{placeholder}] 0/0"

        fraction = min(max(completed / total, 0.0), 1.0)
        filled = int(fraction * self.PROGRESS_BAR_WIDTH)
        if completed >= total:
            filled = self.PROGRESS_BAR_WIDTH
        bar = "#" * filled + "-" * (self.PROGRESS_BAR_WIDTH - filled)
        return f"[{bar}] {completed}/{total}"

    def _get_spinner(
        self, problem_name: str, state: ProblemState
    ) -> Spinner | Text:
        """Get or create spinner for a problem, or return empty text."""
        if state.state in _ACTIVE_SPINNER_STATES:
            spinner = self._spinners.get(problem_name)
            if spinner is None:
                spinner = Spinner("dots", style="cyan")
                self._spinners[problem_name] = spinner
            return spinner

        self._spinners.pop(problem_name, None)
        return Text("  ")

    def _build_row(self, spinner: Spinner | Text, content: Text) -> Table:
        """Build a table row with spinner and content."""
        table = Table.grid(padding=(0, 1))
        table.add_column(width=2, no_wrap=True)
        table.add_column(ratio=1)
        table.add_row(spinner, content)
        return table

    def _format_state_label(
        self, state_value: AgentStateEnum | str
    ) -> tuple[str, str]:
        """Format a state value as a label with style."""
        if isinstance(state_value, AgentStateEnum):
            enum_value = state_value
            label = enum_value.value.replace("_", " ").upper()
            style = STATE_STYLES.get(enum_value, "white")
        else:
            label = str(state_value).replace("_", " ").upper()
            style = "white"

        return f"{label:>{self.STATE_LABEL_WIDTH}}", style

    def _build_problem_row(
        self, problem_name: str, state: ProblemState
    ) -> Table | None:
        """Build a rendered row for a single problem."""
        completed, total = state.get_checkpoint_progress()
        progress_bar = self._render_progress_bar(completed, total)
        state_label, state_style = self._format_state_label(state.state)

        if state.started is None or state.agent_usage is None:
            text = Text()
            text.append(
                f"{problem_name:>{self.PROBLEM_NAME_WIDTH}} ", style="cyan"
            )
            text.append(state_label, style=state_style)
            text.append(": ", style="cyan")
            text.append("0 step(s) ", style="yellow")
            text.append("00:00 ", style="green")
            text.append(progress_bar, style="white")
            text.append(" net=$0.00000", style="cyan")
            spinner = self._get_spinner(problem_name, state)
            return self._build_row(spinner, text)

        if state.overall_usage is None:
            logger.warning(
                "Overall usage is not set",
                problem_name=problem_name,
                state=state.model_dump_json(),
            )
            return None

        total_cost = state.overall_usage.cost + (state.agent_usage.cost or 0.0)
        steps = state.agent_usage.steps or 0
        checkpoint_elapsed = state.get_checkpoint_elapsed_time()
        elapsed_mins = int(checkpoint_elapsed // 60)
        elapsed_secs = int(checkpoint_elapsed % 60)

        text = Text()
        text.append(f"{problem_name:>{self.PROBLEM_NAME_WIDTH}} ", style="cyan")
        text.append(state_label, style=state_style)
        text.append(": ", style="cyan")
        text.append(f"{steps:>4d} step(s) ", style="yellow")
        text.append(f"{elapsed_mins:02d}:{elapsed_secs:02d} ", style="green")
        text.append(progress_bar, style="white")
        text.append(f" net=${total_cost:.5f}", style="cyan")
        spinner = self._get_spinner(problem_name, state)
        return self._build_row(spinner, text)
