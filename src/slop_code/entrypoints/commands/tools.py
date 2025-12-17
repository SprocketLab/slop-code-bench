from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Annotated

import typer

from slop_code.entrypoints.commands import run_case

app = typer.Typer(
    help="Utilities for launching interactive tools (Streamlit apps).",
)
run_case.register(app, "run-case")


def _run_streamlit(script_path: Path, args: list[str]) -> None:
    cmd = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(script_path),
        "--",
        *args,
    ]
    raise_on_error = True
    subprocess.run(cmd, check=raise_on_error)


@app.command(
    "snapshot-eval",
    help="Launch the Snapshot Evaluator (Streamlit).",
)
def snapshot_eval() -> None:
    script_path = Path(__file__).resolve().parents[1] / "snapshot_eval.py"
    _run_streamlit(script_path, [])


@app.command(
    "report-viewer",
    help="Launch the Verifier Report Viewer (Streamlit).",
)
def report_viewer(
    directory: Annotated[
        Path,
        typer.Argument(
            help="Path to a run directory (or snapshots dir) to browse.",
            exists=True,
            dir_okay=True,
            file_okay=False,
            resolve_path=True,
        ),
    ],
) -> None:
    script_path = Path(__file__).resolve().parents[1] / "report_viewer.py"
    _run_streamlit(script_path, [str(directory)])


