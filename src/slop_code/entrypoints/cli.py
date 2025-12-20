from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from dotenv import load_dotenv
from structlog import get_logger

from slop_code import common
from slop_code.entrypoints import commands
from slop_code.entrypoints import utils
from slop_code.logging import setup_logging

logger = get_logger(__name__)

load_dotenv()

app = typer.Typer(
    help="CLI for running agents, evaluations, and the dashboard.",
    pretty_exceptions_show_locals=False,
)
commands.run_agent.register(app, "run")
commands.eval_run_dir.register(app, "eval")
commands.eval_problem_dir.register(app, "eval-problem")
commands.eval_checkpoint.register(app, "eval-snapshot")
commands.infer_problem.register(app, "infer-problem")

utils_app = typer.Typer(
    help="Utilities and other similar commands.",
)
commands.repopulate_diffs.register(utils_app, "repopulate-diffs")
commands.backfill_reports.register(utils_app, "backfill-reports")
commands.backfill_categories.register(utils_app, "backfill-categories")
commands.compress_artifacts.register(utils_app, "compress-artifacts")
commands.combine_results.register(utils_app, "combine-results")
commands.inject_canary.register(utils_app, "inject-canary")
commands.render_prompts.register(utils_app, "render-prompts")
metrics_app = typer.Typer(
    help="Commands for calculating metrics of submissions or files.",
)
commands.static.register(metrics_app, "static")
commands.judge.register(metrics_app, "judge")
commands.carry_forward.register(metrics_app, "carry-forward")
commands.variance.register(metrics_app, "variance")

app.add_typer(metrics_app, name="metrics")
app.add_typer(utils_app, name="utils")
app.add_typer(commands.docker.app, name="docker")
app.add_typer(commands.tools.app, name="tools")


@app.callback()
def main(
    ctx: typer.Context,
    verbose: int = typer.Option(
        0,
        "-v",
        "--verbose",
        count=True,
        help="Increase verbosity (repeatable)",
    ),
    seed: int = typer.Option(42, "--seed", help="Random seed"),
    problem_path: Annotated[
        Path,
        typer.Option(
            "-p",
            "--problem-path",
            help="Path to problem directory",
            exists=True,
            dir_okay=True,
            file_okay=False,
        ),
    ] = Path(__file__).parents[3] / "problems",
    overwrite: bool = typer.Option(
        False,
        "--overwrite",
        help="Overwrite existing output directory",
    ),
    debug: bool = typer.Option(
        False,
        "--debug",
        help="Enable debugging mode",
    ),
    snapshot_dir_name: str = typer.Option(
        common.SNAPSHOT_DIR_NAME,
        "--snapshot-dir-name",
        help="Name of the snapshot directory",
    ),
) -> None:
    """Common setup executed before any command."""
    ctx.obj = utils.CLIContext(
        verbosity=verbose,
        seed=seed,
        problem_path=problem_path,
        overwrite=overwrite,
        debug=debug,
        snapshot_dir_name=snapshot_dir_name,
    )
    typer.echo(
        typer.style("Starting Slop Code CLI", fg=typer.colors.GREEN, bold=True)
    )
    typer.echo(f"\tProblem path: {problem_path}")
    typer.echo(f"\tSeed: {seed}")
    typer.echo(f"\tVerbose: {verbose}")

    typer.echo("--------------------------------")
    setup_logging(verbosity=verbose)


if __name__ == "__main__":
    app()
