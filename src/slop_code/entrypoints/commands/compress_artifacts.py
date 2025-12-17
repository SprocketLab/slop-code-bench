"""Command to compress agent artifact directories into tar.gz files."""

from __future__ import annotations

import shutil
import tarfile
from pathlib import Path
from typing import Annotated

import typer

from slop_code.common import AGENT_DIR_NAME
from slop_code.common import AGENT_TAR_FILENAME
from slop_code.entrypoints.commands import common
from slop_code.entrypoints.utils import discover_run_directories
from slop_code.logging import setup_logging


def _compress_agent_dir(agent_dir: Path) -> tuple[bool, str | None]:
    """Compress an agent directory to a tar.gz file.

    Args:
        agent_dir: Path to the agent directory to compress.

    Returns:
        Tuple of (success, error_message).
    """
    if not agent_dir.is_dir():
        return False, f"Not a directory: {agent_dir}"

    tar_path = agent_dir.parent / AGENT_TAR_FILENAME

    # Skip if tar already exists
    if tar_path.exists():
        return False, f"Tar file already exists: {tar_path}"

    try:
        with tarfile.open(tar_path, "w:gz") as tar:
            for item in agent_dir.iterdir():
                tar.add(item, arcname=item.name)

        # Remove the original directory
        shutil.rmtree(agent_dir)
        return True, None

    except (OSError, tarfile.TarError) as e:
        # Clean up partial tar file if it was created
        if tar_path.exists():
            tar_path.unlink()
        return False, str(e)


def _find_agent_dirs(run_dir: Path) -> list[Path]:
    """Find all uncompressed agent directories in a run directory.

    Args:
        run_dir: Path to the run directory.

    Returns:
        List of paths to agent directories.
    """
    agent_dirs = []

    # Look for agent directories in checkpoint directories
    # Structure: run_dir/problem_name/checkpoint_name/agent/
    for problem_dir in run_dir.iterdir():
        if not problem_dir.is_dir():
            continue
        # Skip non-problem directories
        if problem_dir.name in {"logs", "agent"}:
            continue

        for checkpoint_dir in problem_dir.iterdir():
            if not checkpoint_dir.is_dir():
                continue

            agent_dir = checkpoint_dir / AGENT_DIR_NAME
            if agent_dir.is_dir():
                agent_dirs.append(agent_dir)

    return agent_dirs


def _process_single_run(run_dir: Path) -> tuple[int, int, list[tuple[Path, str]]]:
    """Process a single run directory.

    Args:
        run_dir: Path to the run directory.

    Returns:
        Tuple of (compressed_count, skipped_count, errors).
    """
    agent_dirs = _find_agent_dirs(run_dir)
    compressed = 0
    skipped = 0
    errors: list[tuple[Path, str]] = []

    for agent_dir in agent_dirs:
        success, error = _compress_agent_dir(agent_dir)
        if success:
            compressed += 1
        elif error:
            if "already exists" in error:
                skipped += 1
            else:
                errors.append((agent_dir, error))

    return compressed, skipped, errors


def register(app: typer.Typer, name: str):
    """Register the compress-artifacts command."""
    app.command(
        name,
        help="Compress agent artifact directories into tar.gz files",
    )(compress_artifacts)


def compress_artifacts(
    ctx: typer.Context,
    results_dir: Annotated[
        Path,
        typer.Argument(
            help="Path to the results directory or collection directory",
            exists=True,
            dir_okay=True,
            file_okay=False,
        ),
    ],
    path_type: Annotated[
        common.PathType,
        typer.Option(
            "--type",
            "-t",
            help="Type of path: 'run' for single run, 'collection' for multiple runs",
        ),
    ] = common.PathType.RUN,
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        "-n",
        help="Show what would be compressed without actually doing it",
    ),
) -> None:
    """Compress agent artifact directories into tar.gz files.

    This command finds all uncompressed agent directories (named 'agent')
    within checkpoint directories, compresses them into 'agent.tar.gz',
    and removes the original directories.

    Examples:
        # Compress artifacts in a single run directory
        slop-code utils compress-artifacts ./outputs/my_run

        # Compress artifacts across all runs in a collection
        slop-code utils compress-artifacts ./outputs --type collection

        # Preview what would be compressed
        slop-code utils compress-artifacts ./outputs --dry-run
    """
    logger = setup_logging(
        log_dir=None,
        verbosity=ctx.obj.verbosity,
    )
    logger.info(
        "Compressing agent artifacts",
        results_dir=str(results_dir),
        path_type=path_type.value,
        dry_run=dry_run,
    )

    if not results_dir.exists():
        typer.echo(
            typer.style(
                f"Results directory '{results_dir}' does not exist.",
                fg=typer.colors.RED,
                bold=True,
            )
        )
        raise typer.Exit(1)

    # Determine which run directories to process
    if path_type == common.PathType.COLLECTION:
        run_dirs = discover_run_directories(results_dir)
        if not run_dirs:
            typer.echo(
                typer.style(
                    f"No run directories found in {results_dir}",
                    fg=typer.colors.RED,
                    bold=True,
                )
            )
            raise typer.Exit(1)
        typer.echo(f"Discovered {len(run_dirs)} run(s) in collection")
    else:
        run_dirs = [results_dir]

    total_compressed = 0
    total_skipped = 0
    total_errors: list[tuple[Path, str]] = []

    for run_dir in run_dirs:
        if path_type == common.PathType.COLLECTION:
            typer.echo(f"\nProcessing: {run_dir.name}")

        agent_dirs = _find_agent_dirs(run_dir)

        if dry_run:
            typer.echo(f"  Would compress {len(agent_dirs)} agent directory(ies):")
            for agent_dir in agent_dirs:
                tar_path = agent_dir.parent / AGENT_TAR_FILENAME
                if tar_path.exists():
                    typer.echo(
                        typer.style(
                            f"    [SKIP] {agent_dir.relative_to(run_dir)} "
                            "(tar already exists)",
                            fg=typer.colors.YELLOW,
                        )
                    )
                    total_skipped += 1
                else:
                    typer.echo(f"    {agent_dir.relative_to(run_dir)}")
                    total_compressed += 1
        else:
            compressed, skipped, errors = _process_single_run(run_dir)
            total_compressed += compressed
            total_skipped += skipped
            total_errors.extend(errors)

            if compressed > 0:
                typer.echo(
                    typer.style(
                        f"  Compressed {compressed} directory(ies)",
                        fg=typer.colors.GREEN,
                    )
                )
            if skipped > 0:
                typer.echo(
                    typer.style(
                        f"  Skipped {skipped} (tar already exists)",
                        fg=typer.colors.YELLOW,
                    )
                )
            if errors:
                for path, error in errors:
                    typer.echo(
                        typer.style(
                            f"  Error: {path.relative_to(run_dir)}: {error}",
                            fg=typer.colors.RED,
                        )
                    )

    # Summary
    typer.echo("\n" + "=" * 50)
    if dry_run:
        typer.echo(
            typer.style("DRY RUN - No changes made", fg=typer.colors.CYAN, bold=True)
        )
        typer.echo(f"Would compress: {total_compressed}")
        typer.echo(f"Would skip: {total_skipped}")
    else:
        typer.echo(
            typer.style(
                f"Compressed: {total_compressed}", fg=typer.colors.GREEN, bold=True
            )
        )
        typer.echo(f"Skipped: {total_skipped}")
        if total_errors:
            typer.echo(
                typer.style(
                    f"Errors: {len(total_errors)}", fg=typer.colors.RED, bold=True
                )
            )
