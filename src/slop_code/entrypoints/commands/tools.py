from __future__ import annotations

import typer

app = typer.Typer(
    help="Utilities for launching interactive tools (Streamlit apps).",
)

# Note: All tools (run-case, snapshot-eval, report-viewer) removed during pytest migration cleanup
