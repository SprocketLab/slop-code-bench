"""Static code quality metrics command."""

from __future__ import annotations

import traceback
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import Annotated

import typer
import yaml
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from slop_code.common import CHECKPOINT_RESULTS_FILENAME
from slop_code.common import CONFIG_FILENAME
from slop_code.common import SUMMARY_FILENAME
from slop_code.entrypoints.commands import common
from slop_code.entrypoints.evaluation.metrics import create_problem_reports
from slop_code.entrypoints.evaluation.metrics import update_results_jsonl
from slop_code.entrypoints.utils import discover_checkpoints
from slop_code.entrypoints.utils import discover_problems
from slop_code.entrypoints.utils import discover_run_directories
from slop_code.entrypoints.utils import display_and_save_summary
from slop_code.logging import get_logger
from slop_code.logging import setup_logging
from slop_code.metrics import FileMetrics
from slop_code.metrics import SnapshotMetrics
from slop_code.metrics import get_language_by_extension
from slop_code.metrics import measure_snapshot_quality
from slop_code.metrics import process_problem_quality
from slop_code.metrics.quality_io import save_quality_metrics

logger = get_logger(__name__)


@dataclass
class RunProcessingResult:
    """Result of processing a single run directory."""

    run_dir: Path
    success: bool
    slop_rule_counts: Counter[str] = field(default_factory=Counter)
    slop_rows: list[tuple[str, str, int, int]] = field(default_factory=list)
    all_reports: list[dict] = field(default_factory=list)
    report_errors: list[tuple[str, str]] = field(default_factory=list)
    total_checkpoints: int = 0
    total_files_saved: int = 0
    error_type: str | None = None
    error_message: str | None = None
    error_traceback: str | None = None


def _process_single_run_worker(
    problem_path: Path,
    run_dir: Path,
    problem_name: str | None,
) -> RunProcessingResult:
    """Worker function for parallel processing of run directories.

    This function is meant to be called in ProcessPoolExecutor workers.
    It sets up logging and processes a single run directory.

    Args:
        problem_path: Path to the problems directory.
        run_dir: Path to the run directory to process.
        problem_name: Optional filter for specific problem.

    Returns:
        RunProcessingResult capturing success or failure with full context.
    """
    # Set up logging for this worker process
    log = setup_logging(log_dir=None, verbosity=0)

    try:
        slop_rule_counts: Counter[str] = Counter()
        slop_rows: list[tuple[str, str, int, int]] = []
        all_reports: list[dict] = []
        report_errors: list[tuple[str, str]] = []
        total_checkpoints = 0
        total_files_saved = 0

        # Discover problems
        problems = discover_problems(run_dir)

        if not problems:
            return RunProcessingResult(
                run_dir=run_dir,
                success=True,
                error_message=f"No problems found in {run_dir}",
            )

        # Filter by problem name if specified
        if problem_name is not None:
            problems = [p for p in problems if p.name == problem_name]
            if not problems:
                return RunProcessingResult(
                    run_dir=run_dir,
                    success=True,
                    error_message=f"Problem '{problem_name}' not found",
                )

        # Process each problem
        for problem_dir in problems:
            try:
                problem_config = common.load_problem_config(
                    problem_path / problem_dir.name
                )
                entry_file = problem_config.entry_file
            except (FileNotFoundError, yaml.YAMLError, ValidationError) as e:
                log.warning(
                    "Failed to load problem config",
                    problem=problem_dir.name,
                    error=str(e),
                )
                continue

            checkpoint_results, files_saved = process_problem_quality(
                problem_dir, entry_file, discover_checkpoints
            )
            reports, errors = create_problem_reports(problem_dir, problem_config)
            all_reports.extend(reports)
            for checkpoint_name, error_msg in errors:
                report_errors.append(
                    (f"{problem_dir.name}/{checkpoint_name}", error_msg)
                )

            if not checkpoint_results:
                continue

            total_checkpoints += len(checkpoint_results)
            total_files_saved += files_saved

            for checkpoint_name, metrics in checkpoint_results.items():
                slop_rule_counts.update(metrics.ast_grep.counts)
                slop_rows.append(
                    (
                        problem_dir.name,
                        checkpoint_name,
                        metrics.ast_grep.violations,
                        metrics.ast_grep.rules_checked,
                    )
                )

        return RunProcessingResult(
            run_dir=run_dir,
            success=True,
            slop_rule_counts=slop_rule_counts,
            slop_rows=slop_rows,
            all_reports=all_reports,
            report_errors=report_errors,
            total_checkpoints=total_checkpoints,
            total_files_saved=total_files_saved,
        )

    except Exception as e:
        tb_str = traceback.format_exc()
        log.error(
            "Error processing run",
            run_dir=str(run_dir),
            error=str(e),
            error_type=type(e).__name__,
            exc_info=True,
        )
        return RunProcessingResult(
            run_dir=run_dir,
            success=False,
            error_type=type(e).__name__,
            error_message=str(e),
            error_traceback=tb_str,
        )


def _process_single_run(
    ctx: typer.Context,
    run_dir: Path,
    problem_name: str | None,
    console: Console,
) -> tuple[
    Counter[str],
    list[tuple[str, str, int, int]],
    list[dict],
    list[tuple[str, str]],
    int,
    int,
]:
    """Process a single run directory and return metrics.

    Args:
        ctx: Typer context with problem_path in obj.
        run_dir: Path to the run directory.
        problem_name: Optional filter for specific problem.
        console: Rich console for output.

    Returns:
        Tuple of (slop_rule_counts, slop_rows, all_reports, report_errors,
                  total_checkpoints, total_files_saved)
    """
    slop_rule_counts: Counter[str] = Counter()
    slop_rows: list[tuple[str, str, int, int]] = []
    all_reports: list[dict] = []
    report_errors: list[tuple[str, str]] = []
    total_checkpoints = 0
    total_files_saved = 0

    # Discover problems
    problems = discover_problems(run_dir)

    if not problems:
        console.print(f"[red]No problems found in {run_dir}[/red]")
        return (
            slop_rule_counts,
            slop_rows,
            all_reports,
            report_errors,
            total_checkpoints,
            total_files_saved,
        )

    # Filter by problem name if specified
    if problem_name is not None:
        problems = [p for p in problems if p.name == problem_name]
        if not problems:
            console.print(
                f"[red]Problem '{problem_name}' not found in {run_dir}[/red]"
            )
            return (
                slop_rule_counts,
                slop_rows,
                all_reports,
                report_errors,
                total_checkpoints,
                total_files_saved,
            )

    console.print(f"Processing {len(problems)} problem(s)...")

    # Process each problem
    for problem_dir in problems:
        # Load problem config to get the entry file
        try:
            problem_config = common.load_problem_config(
                ctx.obj.problem_path / problem_dir.name
            )
            entry_file = problem_config.entry_file
        except (FileNotFoundError, yaml.YAMLError, ValidationError) as e:
            console.print(
                f"  [red]{problem_dir.name}: failed to load config - {e}[/red]"
            )
            continue

        checkpoint_results, files_saved = process_problem_quality(
            problem_dir, entry_file, discover_checkpoints
        )
        reports, errors = create_problem_reports(problem_dir, problem_config)
        all_reports.extend(reports)
        for checkpoint_name, error_msg in errors:
            report_errors.append(
                (f"{problem_dir.name}/{checkpoint_name}", error_msg)
            )

        if not checkpoint_results:
            console.print(
                f"  [yellow]{problem_dir.name}: no checkpoints found[/yellow]"
            )
            continue

        total_checkpoints += len(checkpoint_results)
        total_files_saved += files_saved

        console.print(
            f"  {problem_dir.name}: {len(checkpoint_results)} checkpoints, "
            f"{files_saved} files saved"
        )

        for checkpoint_name, metrics in checkpoint_results.items():
            slop_rule_counts.update(metrics.ast_grep.counts)
            slop_rows.append(
                (
                    problem_dir.name,
                    checkpoint_name,
                    metrics.ast_grep.violations,
                    metrics.ast_grep.rules_checked,
                )
            )

    return (
        slop_rule_counts,
        slop_rows,
        all_reports,
        report_errors,
        total_checkpoints,
        total_files_saved,
    )


def register(app: typer.Typer, name: str):
    app.command(
        name,
        help="Calculate and save static code quality metrics for all problems in a run.",
    )(static_metrics)


def static_metrics(
    ctx: typer.Context,
    run_dir: Annotated[
        Path,
        typer.Argument(
            help="Path to the run directory or collection directory",
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
    problem_name: Annotated[
        str | None,
        typer.Option(
            "-p",
            "--problem-name",
            help="Filter to a specific problem name.",
        ),
    ] = None,
    just_static_extension: Annotated[
        str | None,
        typer.Option(
            "--just-static",
            help=(
                "Bypass problem discovery and scan this run directory as a "
                "single snapshot, restricting to the extension provided "
                "(e.g. --just-static py)."
            ),
        ),
    ] = None,
    num_workers: Annotated[
        int,
        typer.Option(
            "-w",
            "--workers",
            help="Number of parallel workers for collection mode.",
        ),
    ] = 4,
) -> None:
    """Calculate and save static code quality metrics for all problems in a run.

    This command scans the run directory for all problem runs, calculates
    quality metrics (lines, LOC, comments, MI, CC) for each checkpoint,
    and saves them to overall_quality.json in each checkpoint directory.

    It also backfills reports/results.jsonl and writes a result.json summary
    for the run based on the collected metrics.

    The entry file for each problem is automatically read from the problem's
    config.yaml file.

    When --type collection is specified, discovers all run directories within
    the provided path and processes each independently.
    """
    console = Console()

    # Handle --just-static mode (only valid for single run)
    if just_static_extension:
        if path_type == common.PathType.COLLECTION:
            console.print(
                "[red]--just-static is not compatible with --type collection[/red]"
            )
            raise typer.Exit(1)

        slop_rule_counts: Counter[str] = Counter()
        slop_rows: list[tuple[str, str, int, int]] = []
        _run_extension_scan(
            console,
            run_dir,
            just_static_extension,
            slop_rule_counts,
            slop_rows,
        )
        console.print(
            "[green]Done. Saved quality metrics for 1 snapshot "
            "(2 files).[/green]"
        )
        _print_slop_summary(console, slop_rows, slop_rule_counts)
        return

    # Handle collection mode
    if path_type == common.PathType.COLLECTION:
        run_dirs = discover_run_directories(run_dir)
        if not run_dirs:
            console.print(f"[red]No run directories found in {run_dir}[/red]")
            raise typer.Exit(1)

        console.print(
            f"Discovered {len(run_dirs)} run(s) in collection, "
            f"processing with {num_workers} workers"
        )
        run_failures: list[tuple[Path, str, str | None]] = []
        completed_count = 0

        # Submit all runs to the process pool
        with ProcessPoolExecutor(max_workers=num_workers) as executor:
            futures = {
                executor.submit(
                    _process_single_run_worker,
                    ctx.obj.problem_path,
                    single_run_dir,
                    problem_name,
                ): single_run_dir
                for single_run_dir in run_dirs
            }

            for future in futures:
                single_run_dir = futures[future]
                try:
                    result = future.result()
                except Exception as e:
                    # Handle executor-level errors
                    tb_str = traceback.format_exc()
                    logger.error(
                        "Failed to process run (executor error)",
                        run_dir=str(single_run_dir),
                        error=str(e),
                        error_type=type(e).__name__,
                        exc_info=True,
                    )
                    run_failures.append((single_run_dir, str(e), tb_str))
                    console.print(
                        f"[red]Failed to process {single_run_dir.name}: {e}[/red]"
                    )
                    continue

                completed_count += 1

                if not result.success:
                    run_failures.append(
                        (result.run_dir, result.error_message or "Unknown error",
                         result.error_traceback)
                    )
                    console.print(
                        f"[red]Failed to process {single_run_dir.name}: "
                        f"{result.error_message}[/red]"
                    )
                    continue

                # Process successful result
                console.print(
                    f"\n[bold]Completed {single_run_dir.name}[/bold]"
                )

                # Save results to THIS run's directory
                report_file = single_run_dir / CHECKPOINT_RESULTS_FILENAME

                console.print(
                    f"[green]Saved quality metrics for {result.total_checkpoints} "
                    f"checkpoints ({result.total_files_saved} files).[/green]"
                )
                _print_slop_summary(
                    console, result.slop_rows, result.slop_rule_counts
                )

                update_results_jsonl(report_file, result.all_reports)
                console.print(
                    f"Backfilled reports for {len(result.all_reports)} "
                    f"checkpoint(s) at {report_file}"
                )

                if result.report_errors:
                    console.print(
                        f"[yellow]{len(result.report_errors)} error(s) encountered "
                        "during report generation:[/yellow]"
                    )
                    for identifier, error_msg in result.report_errors:
                        console.print(f"  - {identifier}: {error_msg}")

                try:
                    with (single_run_dir / CONFIG_FILENAME).open("r") as f:
                        config = yaml.safe_load(f)
                    summary = display_and_save_summary(
                        report_file, single_run_dir, config, console
                    )
                    if summary is None:
                        console.print(
                            f"[yellow]No checkpoint data available; "
                            f"{SUMMARY_FILENAME} not created.[/yellow]"
                        )
                    else:
                        console.print(
                            f"[green]Saved summary to "
                            f"{single_run_dir / SUMMARY_FILENAME}[/green]"
                        )
                except (FileNotFoundError, yaml.YAMLError, OSError) as e:
                    console.print(
                        f"[yellow]Failed to save summary for "
                        f"{single_run_dir.name}: {e}[/yellow]"
                    )

        console.print(
            f"\n[bold green]Processed {len(run_dirs) - len(run_failures)} "
            f"of {len(run_dirs)} run(s)[/bold green]"
        )

        if run_failures:
            console.print(
                f"[yellow]{len(run_failures)} run(s) failed:[/yellow]"
            )
            for failed_dir, error, tb in run_failures:
                console.print(f"  - {failed_dir.name}: {error}")
                if tb:
                    # Show last few lines of traceback for debugging
                    tb_lines = tb.strip().split("\n")[-3:]
                    for line in tb_lines:
                        console.print(f"      [dim]{line}[/dim]")

        return

    # Single run mode (default)
    (
        slop_rule_counts,
        slop_rows,
        all_reports,
        report_errors,
        total_checkpoints,
        total_files_saved,
    ) = _process_single_run(ctx, run_dir, problem_name, console)

    if total_checkpoints == 0 and not all_reports:
        # No problems found - exit was already handled in helper
        raise typer.Exit(1)

    report_file = run_dir / "results.jsonl"

    console.print(
        f"[green]Done. Saved quality metrics for {total_checkpoints} "
        f"checkpoints ({total_files_saved} files).[/green]"
    )
    _print_slop_summary(console, slop_rows, slop_rule_counts)

    update_results_jsonl(report_file, all_reports)
    console.print(
        f"Backfilled reports for {len(all_reports)} checkpoint(s) at "
        f"{report_file}"
    )

    if report_errors:
        console.print(
            f"[yellow]{len(report_errors)} error(s) encountered during report "
            "generation:[/yellow]"
        )
        for identifier, error_msg in report_errors:
            console.print(f"  - {identifier}: {error_msg}")

    with (run_dir / CONFIG_FILENAME).open("r") as f:
        config = yaml.safe_load(f)
    summary = display_and_save_summary(report_file, run_dir, config, console)
    if summary is None:
        console.print(
            f"[yellow]No checkpoint data available; {SUMMARY_FILENAME} not created."
            "[/yellow]"
        )
    else:
        console.print(
            f"[green]Saved summary to {run_dir / SUMMARY_FILENAME}[/green]"
        )


def _normalize_extension(raw_ext: str) -> str:
    ext = raw_ext.strip()
    if not ext:
        raise typer.BadParameter("Extension cannot be empty.")
    return ext if ext.startswith(".") else f".{ext}"


def _save_snapshot_outputs(
    base_dir: Path,
    quality_result: SnapshotMetrics,
    file_metrics_list: list[FileMetrics],
) -> None:
    save_quality_metrics(base_dir, quality_result, file_metrics_list)


def _run_extension_scan(
    console: Console,
    run_dir: Path,
    raw_extension: str,
    slop_rule_counts: Counter[str],
    slop_rows: list[tuple[str, str, int, int]],
) -> None:
    extension = _normalize_extension(raw_extension)
    language = get_language_by_extension(extension)
    if language is None:
        console.print(
            f"[red]Unsupported extension '{extension}'.[/red] "
            "Provide an extension with a registered language."
        )
        raise typer.Exit(1)

    matches = sorted(
        path
        for path in run_dir.rglob(f"*{extension}")
        if path.is_file() and not path.name.startswith(".")
    )
    if not matches:
        console.print(
            f"[red]No files with extension '{extension}' found in {run_dir}."
            "[/red]"
        )
        raise typer.Exit(1)

    entry_file = matches[0]
    quality_result, file_metrics_list = measure_snapshot_quality(
        entry_file, run_dir
    )
    _save_snapshot_outputs(run_dir, quality_result, file_metrics_list)

    console.print(
        f"Scanned snapshot at {run_dir} "
        f"({len(file_metrics_list)} files, entry {entry_file.name})"
    )

    slop_rule_counts.update(quality_result.ast_grep.counts)
    slop_rows.append(
        (
            run_dir.name,
            "snapshot",
            quality_result.ast_grep.violations,
            quality_result.ast_grep.rules_checked,
        )
    )


def _print_slop_summary(
    console: Console,
    slop_rows: list[tuple[str, str, int, int]],
    slop_rule_counts: Counter[str],
) -> None:
    if slop_rule_counts:
        table = Table(title="Slop Violations by Rule")
        table.add_column("Rule")
        table.add_column("Count", justify="right")
        for rule_id, count in sorted(
            slop_rule_counts.items(), key=lambda item: (-item[1], item[0])
        ):
            table.add_row(rule_id, str(count))
        console.print(table)
    else:
        console.print("[green]No slop violations detected.[/green]")

    if slop_rows:
        table = Table(title="Slop Violations by Checkpoint")
        table.add_column("Problem")
        table.add_column("Checkpoint")
        table.add_column("Violations", justify="right")
        table.add_column("Rules Checked", justify="right")
        for problem, checkpoint, violations, rules_checked in slop_rows:
            table.add_row(
                problem,
                checkpoint,
                str(violations),
                str(rules_checked),
            )
        console.print(table)
