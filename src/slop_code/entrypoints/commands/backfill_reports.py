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
from slop_code.common import QUALITY_METRIC_SAVENAME
from slop_code.entrypoints.commands import common
from slop_code.entrypoints.evaluation.metrics import create_problem_reports
from slop_code.entrypoints.evaluation.metrics import update_results_jsonl
from slop_code.entrypoints.utils import discover_run_directories
from slop_code.entrypoints.utils import display_and_save_summary
from slop_code.evaluation import ProblemConfig
from slop_code.logging import setup_logging
from slop_code.metrics.languages.python.ast_grep import RuleLookup
from slop_code.metrics.languages.python.ast_grep import (
    build_ast_grep_rules_lookup,
)


def _process_single_run_backfill(
    ctx: typer.Context,
    results_dir: Path,
    logger: Any,
) -> tuple[list[dict], list[tuple[str, str]], int]:
    """Process a single run directory for backfill.

    Args:
        ctx: Typer context with problem_path in obj.
        results_dir: Path to the run directory.
        logger: Logger instance.

    Returns:
        Tuple of (all_reports, all_errors, problems_processed)
    """

    all_errors: list[tuple[str, str]] = []
    all_reports: list[dict] = []
    problems_processed = 0

    for p_dir in results_dir.iterdir():
        if not p_dir.is_dir() or p_dir.name in {"agent", "logs"}:
            continue

        problem_name = p_dir.name

        # Try to load problem config with specific error handling
        try:
            problem = ProblemConfig.from_yaml(
                ctx.obj.problem_path / problem_name
            )
        except FileNotFoundError:
            logger.error(
                "Problem configuration not found",
                problem_name=problem_name,
                problem_path=str(ctx.obj.problem_path / problem_name),
            )
            all_errors.append(
                (
                    problem_name,
                    f"Problem config not found at {ctx.obj.problem_path / problem_name}",
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


def _update_ast_grep_jsonl(
    jsonl_path: Path,
    rules_lookup: RuleLookup,
    logger: Any,
) -> tuple[int, int]:
    """Update ast_grep.jsonl with category/subcategory/weight from rules.

    Also updates the overall_quality.json with recalculated category_counts
    and category_weighted aggregates.

    Args:
        jsonl_path: Path to the ast_grep.jsonl file.
        rules_lookup: Mapping of rule_id to category/subcategory/weight.
        logger: Logger instance.

    Returns:
        Tuple of (total_violations, violations_updated)
    """
    if not jsonl_path.exists():
        return 0, 0

    violations: list[dict] = []
    updated_count = 0

    try:
        with jsonl_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    violation = json.loads(line)
                except json.JSONDecodeError:
                    violations.append(json.loads(line) if line else {})
                    continue

                rule_id = violation.get("rule_id")
                if rule_id and rule_id in rules_lookup:
                    rule_info = rules_lookup[rule_id]
                    old_cat = violation.get("category", "")
                    old_subcat = violation.get("subcategory", "unknown")
                    old_weight = violation.get("weight", 1)

                    violation["category"] = rule_info["category"]
                    violation["subcategory"] = rule_info["subcategory"]
                    violation["weight"] = rule_info["weight"]

                    if (
                        old_cat != rule_info["category"]
                        or old_subcat != rule_info["subcategory"]
                        or old_weight != rule_info["weight"]
                    ):
                        updated_count += 1

                violations.append(violation)

    except OSError as e:
        logger.warning(
            "Failed to read ast_grep.jsonl",
            path=str(jsonl_path),
            error=str(e),
        )
        return 0, 0

    if not violations:
        return 0, 0

    # Write back atomically using temp file
    try:
        parent_dir = jsonl_path.parent
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=parent_dir,
            suffix=".jsonl.tmp",
            delete=False,
        ) as tmp:
            for violation in violations:
                tmp.write(json.dumps(violation) + "\n")
            tmp_path = Path(tmp.name)

        tmp_path.replace(jsonl_path)
    except OSError as e:
        logger.warning(
            "Failed to write updated ast_grep.jsonl",
            path=str(jsonl_path),
            error=str(e),
        )
        return len(violations), 0

    # Update overall_quality.json with new category aggregates
    overall_path = jsonl_path.parent / QUALITY_METRIC_SAVENAME
    if overall_path.exists():
        _update_overall_quality_ast_grep(overall_path, violations, logger)

    return len(violations), updated_count


def _update_overall_quality_ast_grep(
    overall_path: Path,
    violations: list[dict],
    logger: Any,
) -> None:
    """Update the ast_grep section of overall_quality.json.

    Recalculates category_counts and category_weighted from violations.
    """
    try:
        with overall_path.open("r", encoding="utf-8") as f:
            overall = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning(
            "Failed to read overall_quality.json",
            path=str(overall_path),
            error=str(e),
        )
        return

    # Recalculate category aggregates
    category_counts: dict[str, int] = {}
    category_weighted: dict[str, int] = {}
    total_weighted = 0
    rule_counts: dict[str, int] = {}

    for v in violations:
        cat = v.get("category", "")
        weight = v.get("weight", 1)
        rule_id = v.get("rule_id", "")

        if cat:
            category_counts[cat] = category_counts.get(cat, 0) + 1
            category_weighted[cat] = category_weighted.get(cat, 0) + weight
        total_weighted += weight
        if rule_id:
            rule_counts[rule_id] = rule_counts.get(rule_id, 0) + 1

    # Update ast_grep section
    if "ast_grep" not in overall:
        overall["ast_grep"] = {}

    overall["ast_grep"]["violations"] = len(violations)
    overall["ast_grep"]["weighted"] = total_weighted
    overall["ast_grep"]["category_counts"] = category_counts
    overall["ast_grep"]["category_weighted"] = category_weighted
    overall["ast_grep"]["counts"] = rule_counts

    # Write back atomically
    try:
        parent_dir = overall_path.parent
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=parent_dir,
            suffix=".json.tmp",
            delete=False,
        ) as tmp:
            json.dump(overall, tmp, indent=2, sort_keys=True)
            tmp_path = Path(tmp.name)

        tmp_path.replace(overall_path)
    except OSError as e:
        logger.warning(
            "Failed to write updated overall_quality.json",
            path=str(overall_path),
            error=str(e),
        )


def _backfill_ast_grep_for_run(
    results_dir: Path,
    rules_lookup: RuleLookup,
    logger: Any,
) -> tuple[int, int, int]:
    """Backfill ast_grep.jsonl files in all checkpoints of a run.

    Args:
        results_dir: Path to the run directory.
        rules_lookup: Mapping of rule_id to category/subcategory/weight.
        logger: Logger instance.

    Returns:
        Tuple of (files_processed, total_violations, violations_updated)
    """
    files_processed = 0
    total_violations = 0
    total_updated = 0

    # Find all ast_grep.jsonl files in checkpoint quality_analysis dirs
    pattern = "*/checkpoint_*/quality_analysis/ast_grep.jsonl"
    for jsonl_path in results_dir.glob(pattern):
        violations, updated = _update_ast_grep_jsonl(
            jsonl_path, rules_lookup, logger
        )
        if violations > 0:
            files_processed += 1
            total_violations += violations
            total_updated += updated

    return files_processed, total_violations, total_updated


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
    logger.info("Backfilling high-level reports", results_dir=results_dir)

    # Build AST-grep rules lookup for backfilling ast_grep.jsonl
    rules_lookup = build_ast_grep_rules_lookup()
    if rules_lookup:
        logger.info(
            "Loaded AST-grep rules for backfill",
            rules_count=len(rules_lookup),
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
                    _process_single_run_backfill(ctx, single_run_dir, logger)
                )

                # Save to THIS run's directory
                report_file = single_run_dir / CHECKPOINT_RESULTS_FILENAME
                update_results_jsonl(report_file, all_reports)

                typer.echo(f"Reports written to {report_file}")
                typer.echo(f"Processed {problems_processed} problem(s)")

                # Backfill ast_grep.jsonl files
                if rules_lookup:
                    sg_files, sg_violations, sg_updated = (
                        _backfill_ast_grep_for_run(
                            single_run_dir, rules_lookup, logger
                        )
                    )
                    if sg_files > 0:
                        typer.echo(
                            f"Updated {sg_updated}/{sg_violations} "
                            f"ast-grep violations in {sg_files} file(s)"
                        )

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
                display_and_save_summary(
                    report_file, single_run_dir, config, console
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
                            typer.style(f"      {line}", fg=typer.colors.BRIGHT_BLACK)
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
        ctx, results_dir, logger
    )

    report_file = results_dir / CHECKPOINT_RESULTS_FILENAME
    update_results_jsonl(report_file, all_reports)

    typer.echo(f"Reports written to {report_file}")
    typer.echo(f"Processed {problems_processed} problem(s)")

    # Backfill ast_grep.jsonl files
    if rules_lookup:
        sg_files, sg_violations, sg_updated = _backfill_ast_grep_for_run(
            results_dir, rules_lookup, logger
        )
        if sg_files > 0:
            typer.echo(
                f"Updated {sg_updated}/{sg_violations} "
                f"ast-grep violations in {sg_files} file(s)"
            )

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
    display_and_save_summary(report_file, results_dir, config, console)
