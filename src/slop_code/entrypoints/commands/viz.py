"""Visualization commands."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

import slop_code.visualization
from slop_code.logging import get_logger

logger = get_logger(__name__)
console = Console()


def register(app: typer.Typer, name: str) -> None:
    app.command(
        name,
        help="Launch the diff viewer visualization.",
    )(diff)


def diff(
    ctx: typer.Context,
    run_dir: Annotated[
        Path | None,
        typer.Argument(
            help="Path to the run directory to visualize",
            exists=True,
            dir_okay=True,
            file_okay=False,
        ),
    ] = None,
) -> None:
    """Launch the Streamlit diff viewer."""
    viz_dir = Path(slop_code.visualization.__file__).parent
    app_path = viz_dir / "diff_viewer.py"

    if not app_path.exists():
        console.print(f"[red]Could not find diff viewer app at {app_path}[/red]")
        raise typer.Exit(1)

    cmd = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(app_path),
    ]

    if run_dir:
        cmd.extend(["--", "--run-dir", str(run_dir)])

    console.print(
        f"[green]Launching diff viewer for {run_dir or 'default'}...[/green]"
    )
    console.print("[dim](Press Ctrl+C to stop)[/dim]")

    try:
        subprocess.run(cmd, check=True)
    except KeyboardInterrupt:
        pass
