from __future__ import annotations

import json
import tempfile
import traceback
from pathlib import Path
from typing import Annotated, Any

import typer
import yaml
from pydantic import ValidationError
from rich.console import Console

from slop_code.common import CHECKPOINT_RESULTS_FILENAME
from slop_code.common import CONFIG_FILENAME
from slop_code.common import QUALITY_DIR
from slop_code.common import QUALITY_METRIC_SAVENAME
from slop_code.common import SYMBOLS_QUALITY_SAVENAME
from slop_code.entrypoints.commands import common
from slop_code.entrypoints.evaluation.metrics import create_problem_reports
from slop_code.entrypoints.evaluation.metrics import update_results_jsonl
from slop_code.entrypoints.utils import count_expected_checkpoints
from slop_code.entrypoints.utils import discover_run_directories
from slop_code.entrypoints.utils import display_and_save_summary
from slop_code.evaluation import ProblemConfig
from slop_code.logging import setup_logging


def _backfill_top20_share(
    results_dir: Path,
    logger: Any,
) -> tuple[int, int]:
    """Backfill *_top20 fields into overall_quality.json from symbols.jsonl.

    Reads per-function metrics from symbols.jsonl, computes top-20% share
    for each metric family, and patches the functions section of
    overall_quality.json.

    Returns:
        Tuple of (files_processed, files_updated).
    """
    from slop_code.metrics.checkpoint.mass import compute_top20_share

    metric_fields = {"complexity": "cc_top20"}

    files_processed = 0
    files_updated = 0

    for quality_dir in results_dir.glob(f"*/checkpoint_*/{QUALITY_DIR}"):
        symbols_path = quality_dir / SYMBOLS_QUALITY_SAVENAME
        overall_path = quality_dir / QUALITY_METRIC_SAVENAME

        if not symbols_path.exists() or not overall_path.exists():
            continue

        files_processed += 1

        # Collect per-function values from symbols.jsonl
        value_lists: dict[str, list[float]] = {k: [] for k in metric_fields}
        try:
            with symbols_path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    sym = json.loads(line)
                    if sym.get("type") not in {"function", "method"}:
                        continue
                    for field in metric_fields:
                        value_lists[field].append(float(sym.get(field, 0)))
        except (OSError, json.JSONDecodeError) as e:
            logger.warning(
                "Failed to read symbols.jsonl",
                path=str(symbols_path),
                error=str(e),
            )
            continue

        # Compute top-20% shares
        top20_values = {
            target: round(compute_top20_share(value_lists[source]), 3)
            for source, target in metric_fields.items()
        }

        # Patch overall_quality.json
        try:
            with overall_path.open("r", encoding="utf-8") as f:
                overall = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            logger.warning(
                "Failed to read overall_quality.json",
                path=str(overall_path),
                error=str(e),
            )
            continue

        functions = overall.get("functions", {})
        needs_update = any(
            functions.get(k) != v for k, v in top20_values.items()
        )

        if not needs_update:
            continue

        functions.update(top20_values)
        overall["functions"] = functions

        # Write back atomically
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=quality_dir,
                suffix=".json.tmp",
                delete=False,
            ) as tmp:
                json.dump(overall, tmp, indent=2, sort_keys=True)
                tmp_path = Path(tmp.name)
            tmp_path.replace(overall_path)
            files_updated += 1
        except OSError as e:
            logger.warning(
                "Failed to write updated overall_quality.json",
                path=str(overall_path),
                error=str(e),
            )

    return files_processed, files_updated


def _process_single_run_backfill(
    problem_root: Path,
    results_dir: Path,
    logger: Any,
) -> tuple[list[dict], list[tuple[str, str]], int]:
    """Process a single run directory for backfill.

    Args:
        problem_root: Path to the managed problem catalog.
        results_dir: Path to the run directory.
        logger: Logger instance.

    Returns:
        Tuple of (all_reports, all_errors, problems_processed)
    """

    all_errors: list[tuple[str, str]] = []
    all_reports: list[dict] = []
    problems_processed = 0

    # Backfill top-20% share into overall_quality.json BEFORE reports
    t20_files, t20_updated = _backfill_top20_share(results_dir, logger)
    if t20_updated > 0:
        logger.info(
            "Backfilled top-20% share metrics",
            files_updated=t20_updated,
            files_processed=t20_files,
        )

    # Backfill evaluation group types BEFORE generating reports
    # This fixes Error tests from prior checkpoints to Regression
    eval_files, eval_updated = _backfill_evaluation_group_types(
        results_dir, logger
    )
    if eval_updated > 0:
        logger.info(
            "Backfilled evaluation.json test metadata",
            files_updated=eval_updated,
            files_processed=eval_files,
        )

    for p_dir in results_dir.iterdir():
        if not p_dir.is_dir() or p_dir.name in {"agent", "logs"}:
            continue

        problem_name = p_dir.name

        # Try to load problem config with specific error handling
        try:
            problem = ProblemConfig.from_yaml(problem_root / problem_name)
        except FileNotFoundError:
            logger.error(
                "Problem configuration not found",
                problem_name=problem_name,
                problem_path=str(problem_root / problem_name),
            )
            all_errors.append(
                (
                    problem_name,
                    f"Problem config not found at {problem_root / problem_name}",
                )
            )
            continue
        except (yaml.YAMLError, ValidationError) as e:
            logger.error(
                "Invalid problem configuration",
                problem_name=problem_name,
                error=str(e),
            )
            all_errors.append((problem_name, f"Invalid config: {e}"))
            continue

        reports, errors = create_problem_reports(p_dir, problem)
        all_reports.extend(reports)

        # Collect errors with problem context
        for checkpoint_name, error_msg in errors:
            all_errors.append((f"{problem_name}/{checkpoint_name}", error_msg))

        problems_processed += 1

    return all_reports, all_errors, problems_processed


def _recalculate_evaluation_counts_dict(data: dict) -> bool:
    """Recalculate pass/total counts from grouped tests, excluding skipped."""
    pass_counts: dict[str, int] = {}
    total_counts: dict[str, int] = {}

    for key, test_data in data["tests"].items():
        # Extract group type from key: "checkpoint_1-Regression" -> "Regression"
        group_type = key.rsplit("-", 1)[1]
        passed = len(test_data.get("passed", []))
        failed = len(test_data.get("failed", []))
        total = passed + failed

        pass_counts[group_type] = pass_counts.get(group_type, 0) + passed
        total_counts[group_type] = total_counts.get(group_type, 0) + total

    old_counts = (data.get("pass_counts", {}), data.get("total_counts", {}))
    new_counts = (pass_counts, total_counts)
    data["pass_counts"] = pass_counts
    data["total_counts"] = total_counts
    return old_counts != new_counts


def _recategorize_evaluation_tests_dict_format(
    data: dict, checkpoint_name: str, logger: Any
) -> bool:
    """Recategorize Error tests and refresh counts for grouped tests.

    Args:
        data: Parsed evaluation.json data (modified in place).
        checkpoint_name: Current checkpoint name.
        logger: Logger instance.

    Returns:
        True if changes were made, False otherwise.
    """
    tests = data["tests"]

    # Find Error groups from prior checkpoints
    keys_to_move: list[tuple[str, str]] = []

    for key in list(tests.keys()):
        if not key.endswith("-Error"):
            continue

        # Extract checkpoint from key: "checkpoint_1-Error" -> "checkpoint_1"
        test_checkpoint = key.rsplit("-", 1)[0]

        if test_checkpoint != checkpoint_name:
            # This Error group is from a prior checkpoint - should be Regression
            keys_to_move.append((key, test_checkpoint))

    # Move tests from Error to Regression buckets
    for error_key, test_checkpoint in keys_to_move:
        regression_key = f"{test_checkpoint}-Regression"
        error_data = tests.pop(error_key)

        # Merge into existing Regression bucket or create new one
        if regression_key in tests:
            tests[regression_key]["passed"].extend(error_data["passed"])
            tests[regression_key]["failed"].extend(error_data["failed"])
            tests[regression_key].setdefault("skipped", []).extend(
                error_data.get("skipped", [])
            )
        else:
            tests[regression_key] = error_data

        logger.debug(
            "Moved Error tests to Regression (dict format)",
            from_key=error_key,
            to_key=regression_key,
            passed=len(error_data["passed"]),
            failed=len(error_data["failed"]),
        )

    counts_changed = _recalculate_evaluation_counts_dict(data)
    return bool(keys_to_move or counts_changed)


def _recategorize_evaluation_tests(eval_path: Path, logger: Any) -> bool:
    """Recategorize Error tests and refresh pass/total counts.

    Prior checkpoint tests with error markers should be REGRESSION, not ERROR.
    Pass/total counts are recalculated so skipped tests are excluded from
    pass-rate denominators.

    Args:
        eval_path: Path to the evaluation.json file.
        logger: Logger instance.

    Returns:
        True if changes were made, False otherwise.
    """
    try:
        with eval_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning(
            "Failed to read evaluation.json",
            path=str(eval_path),
            error=str(e),
        )
        return False

    checkpoint_name = data.get("checkpoint_name")
    if not checkpoint_name:
        logger.warning(
            "evaluation.json missing checkpoint_name",
            path=str(eval_path),
        )
        return False

    tests = data.get("tests")
    if tests is None:
        logger.warning(
            "evaluation.json missing tests field",
            path=str(eval_path),
        )
        return False

    if isinstance(tests, dict):
        changes_made = _recategorize_evaluation_tests_dict_format(
            data, checkpoint_name, logger
        )
    else:
        logger.warning(
            "evaluation.json has invalid tests format",
            path=str(eval_path),
            tests_type=type(tests).__name__,
        )
        return False

    if not changes_made:
        return False

    # Write atomically using temp file
    try:
        parent_dir = eval_path.parent
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=parent_dir,
            suffix=".json.tmp",
            delete=False,
        ) as tmp:
            json.dump(data, tmp, indent=2)
            tmp_path = Path(tmp.name)

        tmp_path.replace(eval_path)
    except OSError as e:
        logger.warning(
            "Failed to write updated evaluation.json",
            path=str(eval_path),
            error=str(e),
        )
        return False

    return True


def _backfill_evaluation_group_types(
    results_dir: Path, logger: Any
) -> tuple[int, int]:
    """Backfill evaluation.json group types and pass/total counts.

    Prior checkpoint tests with error markers should be REGRESSION, not ERROR.
    This function also recalculates counts so skipped tests are excluded from
    pass-rate denominators.

    Args:
        results_dir: Path to the run directory.
        logger: Logger instance.

    Returns:
        Tuple of (files_processed, files_updated).
    """
    files_processed = 0
    files_updated = 0

    # Find all evaluation.json files in checkpoint directories
    pattern = "*/checkpoint_*/evaluation.json"
    for eval_path in results_dir.glob(pattern):
        files_processed += 1
        if _recategorize_evaluation_tests(eval_path, logger):
            files_updated += 1

    return files_processed, files_updated


def register(app: typer.Typer, name: str):
    app.command(
        name,
        help="Backfill reports for all problems in a results directory",
    )(backfill_reports)


def backfill_reports(
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
    recalculate_costs: bool = typer.Option(  # noqa: FBT001, FBT002
        True,  # noqa: FBT003
        "--recalculate-costs/--no-recalculate-costs",
        help=(
            "Deprecated no-op. Backfill preserves costs reported in "
            "inference_result.json."
        ),
    ),
) -> None:
    """Generate checkpoint reports for all problems in a results directory.

    This command scans the results directory for all problem runs and generates
    a single report.jsonl file with one line per checkpoint.
    Each line contains problem metadata + individual checkpoint data.

    When --type collection is specified, discovers all run directories within
    the provided path and processes each independently.
    """

    logger = setup_logging(
        log_dir=None,
        verbosity=ctx.obj.verbosity,
    )
    problem_root = common.resolve_problem_catalog_root(ctx)
    if logger is None:
        raise RuntimeError("backfill-reports requires standard logging")
    logger.info("Backfilling high-level reports", results_dir=results_dir)

    if not results_dir.exists():
        typer.echo(
            typer.style(
                f"Results directory '{results_dir}' does not exist.",
                fg=typer.colors.RED,
                bold=True,
            )
        )
        raise typer.Exit(1)

    # Handle collection mode
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

        total_runs_processed = 0
        total_errors = 0
        run_failures: list[tuple[Path, str, str | None]] = []

        for i, single_run_dir in enumerate(run_dirs, 1):
            typer.echo(
                f"\nProcessing run {i}/{len(run_dirs)}: {single_run_dir.name}"
            )

            try:
                all_reports, all_errors, problems_processed = (
                    _process_single_run_backfill(
                        problem_root, single_run_dir, logger
                    )
                )

                with (single_run_dir / CONFIG_FILENAME).open("r") as f:
                    config = yaml.safe_load(f)

                if recalculate_costs:
                    logger.info(
                        "Preserved checkpoint costs from inference results",
                        run_dir=str(single_run_dir),
                    )

                # Save to THIS run's directory
                report_file = single_run_dir / CHECKPOINT_RESULTS_FILENAME
                update_results_jsonl(report_file, all_reports)

                typer.echo(f"Reports written to {report_file}")
                typer.echo(f"Processed {problems_processed} problem(s)")

                # Display errors for this run
                if all_errors:
                    typer.echo(
                        typer.style(
                            f"{len(all_errors)} error(s) in this run:",
                            fg=typer.colors.YELLOW,
                        )
                    )
                    for identifier, error_msg in all_errors:
                        typer.echo(
                            typer.style(
                                f"  - {identifier}: {error_msg}",
                                fg=typer.colors.RED,
                            )
                        )
                    total_errors += len(all_errors)

                # Display and save summary for this specific run
                console = Console()
                with (single_run_dir / CONFIG_FILENAME).open("r") as f:
                    config = yaml.safe_load(f)
                expected_checkpoints = count_expected_checkpoints(
                    config, problem_root
                )
                display_and_save_summary(
                    report_file,
                    single_run_dir,
                    config,
                    console,
                    expected_checkpoints,
                )

                total_runs_processed += 1

            except Exception as e:
                tb_str = traceback.format_exc()
                logger.error(
                    "Failed to process run",
                    run_dir=str(single_run_dir),
                    error=str(e),
                    error_type=type(e).__name__,
                    exc_info=True,
                )
                run_failures.append((single_run_dir, str(e), tb_str))
                typer.echo(
                    typer.style(
                        f"Failed to process {single_run_dir.name}: {e}",
                        fg=typer.colors.RED,
                    )
                )
                continue

        typer.echo(
            f"\nCompleted {total_runs_processed} of {len(run_dirs)} run(s)"
        )

        if run_failures:
            typer.echo(
                typer.style(
                    f"{len(run_failures)} run(s) failed:",
                    fg=typer.colors.YELLOW,
                    bold=True,
                )
            )
            for failed_dir, error, tb in run_failures:
                typer.echo(
                    typer.style(
                        f"  - {failed_dir.name}: {error}",
                        fg=typer.colors.RED,
                    )
                )
                if tb:
                    # Show last few lines of traceback for debugging
                    tb_lines = tb.strip().split("\n")[-3:]
                    for line in tb_lines:
                        typer.echo(
                            typer.style(
                                f"      {line}", fg=typer.colors.BRIGHT_BLACK
                            )
                        )

        if total_errors > 0:
            typer.echo(
                typer.style(
                    f"Total errors across all runs: {total_errors}",
                    fg=typer.colors.YELLOW,
                )
            )

        return

    # Single run mode (default)
    all_reports, all_errors, problems_processed = _process_single_run_backfill(
        problem_root, results_dir, logger
    )

    with (results_dir / CONFIG_FILENAME).open("r") as f:
        config = yaml.safe_load(f)

    if recalculate_costs:
        logger.info(
            "Preserved checkpoint costs from inference results",
            run_dir=str(results_dir),
        )

    report_file = results_dir / CHECKPOINT_RESULTS_FILENAME
    update_results_jsonl(report_file, all_reports)

    typer.echo(f"Reports written to {report_file}")
    typer.echo(f"Processed {problems_processed} problem(s)")

    # Display error summary at end
    if all_errors:
        typer.echo(
            typer.style(
                f"\n{len(all_errors)} error(s) encountered:",
                fg=typer.colors.YELLOW,
                bold=True,
            )
        )
        for identifier, error_msg in all_errors:
            typer.echo(
                typer.style(
                    f"  - {identifier}: {error_msg}", fg=typer.colors.RED
                )
            )

    # Display and save summary statistics
    console = Console()
    with (results_dir / CONFIG_FILENAME).open("r") as f:
        config = yaml.safe_load(f)
    expected_checkpoints = count_expected_checkpoints(config, problem_root)
    display_and_save_summary(
        report_file, results_dir, config, console, expected_checkpoints
    )
