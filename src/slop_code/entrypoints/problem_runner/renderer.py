"""Progress rendering for problem execution display.

This module provides Rich-based rendering for displaying problem execution
progress in the terminal.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from rich.panel import Panel
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

# States shown in the problem list (hide pending/completed/error/failed)
_ACTIVE_DISPLAY_STATES = frozenset(
    {
        AgentStateEnum.INITIALIZED,
        AgentStateEnum.RUNNING,
        AgentStateEnum.EVALUATING,
    }
)

# Terminal states that count as "done"
_TERMINAL_STATES = frozenset(
    {
        AgentStateEnum.COMPLETED,
        AgentStateEnum.FAILED,
        AgentStateEnum.ERROR,
        AgentStateEnum.HIT_RATE_LIMITED,
    }
)


class ProblemProgressRenderer:
    """Render problem progress rows for live display."""

    STATE_LABEL_WIDTH = 16
    PROGRESS_BAR_WIDTH = 10
    PROBLEM_NAME_WIDTH = 30

    def __init__(
        self,
        state: ProblemStateTracker,
        run_dir: Path,
        start_time: datetime,
        total_problems: int,
        total_checkpoints: int,
    ) -> None:
        """Initialize renderer with state tracker and run metadata.

        Args:
            state: Tracker containing problem states to render
            run_dir: Output directory path for display
            start_time: When the run started for elapsed time
            total_problems: Total number of problems in the run
            total_checkpoints: Total number of checkpoints across all problems
        """
        self._state = state
        self._run_dir = run_dir
        self._start_time = start_time
        self._total_problems = total_problems
        self._total_checkpoints = total_checkpoints
        self._spinners: dict[str, Spinner] = {}
        self.placeholder = Text("Waiting for progress updates...", style="dim")

    def _build_header(self) -> Panel:
        """Build header panel with run status summary."""
        total_cost = 0.0
        problems_done = 0
        total_evaluated = 0
        total_passed = 0
        total_iso_passed = 0

        for _, state in self._state.problems():
            if state.overall_usage:
                total_cost += state.overall_usage.cost
            if state.agent_usage:
                total_cost += state.agent_usage.cost
            if state.state in _TERMINAL_STATES:
                problems_done += 1
            total_evaluated += state.total_checkpoints_evaluated
            total_passed += state.checkpoints_passed
            total_iso_passed += state.checkpoints_iso_passed

        # Format elapsed time
        elapsed = datetime.now() - self._start_time
        hours, remainder = divmod(int(elapsed.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        elapsed_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

        # Calculate percentages
        pct_solved = (
            (total_passed / total_evaluated * 100)
            if total_evaluated > 0
            else 0.0
        )
        pct_iso = (
            (total_iso_passed / total_evaluated * 100)
            if total_evaluated > 0
            else 0.0
        )

        # Build layout: output dir on its own line, then stats
        content = Table.grid(padding=(0, 0))
        content.add_column()

        # Row 1: Output directory (full width, can be long)
        content.add_row(
            Text.assemble(("Output: ", "dim"), (str(self._run_dir), "cyan")),
        )

        # Row 2: Stats in a horizontal grid
        stats_row = Table.grid(padding=(0, 3))
        stats_row.add_column()
        stats_row.add_column()
        stats_row.add_column()
        stats_row.add_column()
        stats_row.add_column()
        stats_row.add_row(
            Text.assemble(
                ("Done: ", "dim"),
                (f"{problems_done}/{self._total_problems}", "bold green"),
            ),
            Text.assemble(("Elapsed: ", "dim"), (elapsed_str, "green")),
            Text.assemble(
                ("Spend: ", "dim"), (f"${total_cost:.2f}", "bold cyan")
            ),
            Text.assemble(
                ("Solved: ", "dim"), (f"{pct_solved:.1f}%", "bold green")
            ),
            Text.assemble(
                ("Iso Solved: ", "dim"), (f"{pct_iso:.1f}%", "bold green")
            ),
        )
        content.add_row(stats_row)

        return Panel(
            content, title="[bold cyan]Run Status[/]", border_style="dim"
        )

    def render(self) -> list[Table | Panel]:
        """Render header and actively running problem rows."""
        result: list[Table | Panel] = [self._build_header()]
        for problem, state in self._state.problems():
            # Only show actively running problems
            if state.state not in _ACTIVE_DISPLAY_STATES:
                continue
            row = self._build_problem_row(problem, state)
            if row is not None:
                result.append(row)
        return result

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
