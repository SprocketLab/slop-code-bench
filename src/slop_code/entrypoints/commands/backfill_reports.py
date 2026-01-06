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

    # Backfill evaluation group types BEFORE generating reports
    # This fixes Error tests from prior checkpoints to Regression
    eval_files, eval_updated = _backfill_evaluation_group_types(
        results_dir, logger
    )
    if eval_updated > 0:
        logger.info(
            "Fixed evaluation.json group types",
            files_updated=eval_updated,
            files_processed=eval_files,
        )

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


def _recategorize_evaluation_tests_dict_format(
    data: dict, checkpoint_name: str, logger: Any
) -> bool:
    """Recategorize Error tests in new dict format (grouped by checkpoint-GroupType).

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

    if not keys_to_move:
        return False

    # Move tests from Error to Regression buckets
    for error_key, test_checkpoint in keys_to_move:
        regression_key = f"{test_checkpoint}-Regression"
        error_data = tests.pop(error_key)

        # Merge into existing Regression bucket or create new one
        if regression_key in tests:
            tests[regression_key]["passed"].extend(error_data["passed"])
            tests[regression_key]["failed"].extend(error_data["failed"])
        else:
            tests[regression_key] = error_data

        logger.debug(
            "Moved Error tests to Regression (dict format)",
            from_key=error_key,
            to_key=regression_key,
            passed=len(error_data["passed"]),
            failed=len(error_data["failed"]),
        )

    # Recalculate pass_counts and total_counts from tests dict
    pass_counts: dict[str, int] = {}
    total_counts: dict[str, int] = {}

    for key, test_data in tests.items():
        # Extract group type from key: "checkpoint_1-Regression" -> "Regression"
        group_type = key.rsplit("-", 1)[1]
        passed = len(test_data.get("passed", []))
        failed = len(test_data.get("failed", []))
        total = passed + failed

        pass_counts[group_type] = pass_counts.get(group_type, 0) + passed
        total_counts[group_type] = total_counts.get(group_type, 0) + total

    data["pass_counts"] = pass_counts
    data["total_counts"] = total_counts

    return True


def _recategorize_evaluation_tests_list_format(
    data: dict, checkpoint_name: str, logger: Any
) -> bool:
    """Recategorize Error tests in old list format (individual test objects).

    Args:
        data: Parsed evaluation.json data (modified in place).
        checkpoint_name: Current checkpoint name.
        logger: Logger instance.

    Returns:
        True if changes were made, False otherwise.
    """
    tests = data["tests"]
    changes_made = False
    updated_count = 0

    for test in tests:
        test_checkpoint = test.get("checkpoint", "")
        group_type = test.get("group_type", "")

        # If this is an Error test from a prior checkpoint, change to Regression
        if test_checkpoint != checkpoint_name and group_type == "Error":
            test["group_type"] = "Regression"
            changes_made = True
            updated_count += 1

    if not changes_made:
        return False

    logger.debug(
        "Recategorized Error tests to Regression (list format)",
        updated_count=updated_count,
    )

    # Recalculate pass_counts and total_counts from tests list
    pass_counts: dict[str, int] = {}
    total_counts: dict[str, int] = {}

    for test in tests:
        group_type = test.get("group_type", "Core")
        status = test.get("status", "failed")

        total_counts[group_type] = total_counts.get(group_type, 0) + 1
        if status == "passed":
            pass_counts[group_type] = pass_counts.get(group_type, 0) + 1

    data["pass_counts"] = pass_counts
    data["total_counts"] = total_counts

    return True


def _recategorize_evaluation_tests(eval_path: Path, logger: Any) -> bool:
    """Recategorize Error tests from prior checkpoints to Regression.

    Prior checkpoint tests with error markers should be REGRESSION, not ERROR.
    This fixes evaluation.json files created before this logic change.

    Supports both formats:
    - New format: tests is a dict grouped by "checkpoint-GroupType" keys
    - Old format: tests is a list of individual test objects

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

    # Detect format and process accordingly
    if isinstance(tests, dict):
        # New format: {"checkpoint_1-Error": {"passed": [...], "failed": [...]}}
        changes_made = _recategorize_evaluation_tests_dict_format(
            data, checkpoint_name, logger
        )
    elif isinstance(tests, list):
        # Old format: [{"id": "...", "checkpoint": "...", "group_type": "Error", ...}]
        changes_made = _recategorize_evaluation_tests_list_format(
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
    """Backfill evaluation.json files to fix Error->Regression categorization.

    Prior checkpoint tests with error markers should be REGRESSION, not ERROR.
    This function finds all evaluation.json files and recategorizes them.

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
