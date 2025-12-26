"""Migrate evaluation.json files to new grouped tests format.

This command converts the old list-based tests format to the new grouped format:

Old format:
    "tests": [
        {"id": "test_foo", "checkpoint": "checkpoint_1", "group_type": "Core", "status": "passed", ...},
        ...
    ]

New format:
    "tests": {
        "checkpoint_1-Core": {"passed": ["test_foo"], "failed": ["test_bar"]},
        ...
    }
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Annotated, Any

import typer

from slop_code.entrypoints.commands import common
from slop_code.entrypoints.utils import discover_run_directories
from slop_code.logging import setup_logging


def _convert_tests_to_grouped_format(
    tests: list[dict[str, Any]],
) -> dict[str, dict[str, list[str]]]:
    """Convert list of test objects to grouped format.

    Args:
        tests: List of test dictionaries with id, checkpoint, group_type, status

    Returns:
        Dict with keys like "checkpoint_1-Core" and values like
        {"passed": ["test_id1"], "failed": ["test_id2"]}
    """
    grouped: dict[str, dict[str, list[str]]] = {}

    for test in tests:
        checkpoint = test.get("checkpoint", "unknown")
        group_type = test.get("group_type", "Core")
        test_id = test.get("id", "unknown")
        status = test.get("status", "failed")

        key = f"{checkpoint}-{group_type}"
        if key not in grouped:
            grouped[key] = {"passed": [], "failed": []}

        bucket = "passed" if status == "passed" else "failed"
        grouped[key][bucket].append(test_id)

    return grouped


def _migrate_single_file(
    eval_path: Path,
    dry_run: bool,
    logger: Any,
) -> tuple[bool, str]:
    """Migrate a single evaluation.json file.

    Args:
        eval_path: Path to evaluation.json
        dry_run: If True, don't write changes
        logger: Logger instance

    Returns:
        Tuple of (success, message)
    """
    try:
        with eval_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        return False, f"Failed to read: {e}"

    tests = data.get("tests")

    # Check if already in new format (dict) or old format (list)
    if isinstance(tests, dict):
        return True, "Already migrated"

    if not isinstance(tests, list):
        return False, f"Unexpected tests type: {type(tests)}"

    if len(tests) == 0:
        # Empty list - convert to empty dict
        data["tests"] = {}
    else:
        # Convert to grouped format
        data["tests"] = _convert_tests_to_grouped_format(tests)

    if dry_run:
        return True, f"Would migrate {len(tests)} tests"

    # Write back atomically
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
        return True, f"Migrated {len(tests)} tests"

    except OSError as e:
        return False, f"Failed to write: {e}"


def _migrate_directory(
    results_dir: Path,
    dry_run: bool,
    logger: Any,
) -> tuple[int, int, int]:
    """Migrate all evaluation.json files in a directory.

    Args:
        results_dir: Path to search for evaluation.json files
        dry_run: If True, don't write changes
        logger: Logger instance

    Returns:
        Tuple of (files_found, files_migrated, files_skipped)
    """
    files_found = 0
    files_migrated = 0
    files_skipped = 0

    # Find all evaluation.json files
    for eval_path in results_dir.rglob("evaluation.json"):
        files_found += 1

        success, message = _migrate_single_file(eval_path, dry_run, logger)

        if success:
            if "Already migrated" in message:
                files_skipped += 1
                logger.debug(
                    "Skipped (already migrated)",
                    path=str(eval_path),
                )
            else:
                files_migrated += 1
                logger.info(
                    "Migrated",
                    path=str(eval_path),
                    message=message,
                )
        else:
            logger.warning(
                "Failed to migrate",
                path=str(eval_path),
                error=message,
            )

    return files_found, files_migrated, files_skipped


def register(app: typer.Typer, name: str):
    app.command(
        name,
        help="Migrate evaluation.json files to new grouped tests format",
    )(migrate_evaluation_format)


def migrate_evaluation_format(
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
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            "-n",
            help="Show what would be done without making changes",
        ),
    ] = False,
) -> None:
    """Migrate evaluation.json files from list to grouped tests format.

    This command converts the old tests format (list of test objects) to the
    new grouped format (dict with checkpoint-GroupType keys).

    Old format:
        "tests": [{"id": "test_foo", "group_type": "Core", "status": "passed", ...}]

    New format:
        "tests": {"checkpoint_1-Core": {"passed": ["test_foo"], "failed": []}}

    Examples:
        # Migrate a single run directory
        slop-code utils migrate-eval-format outputs/run_001/

        # Migrate all runs in a collection (dry run first)
        slop-code utils migrate-eval-format --type collection -n outputs/

        # Migrate all runs in a collection
        slop-code utils migrate-eval-format --type collection outputs/
    """
    logger = setup_logging(
        log_dir=None,
        verbosity=ctx.obj.verbosity,
    )

    action = "Would migrate" if dry_run else "Migrating"
    logger.info(
        f"{action} evaluation.json files",
        results_dir=str(results_dir),
        dry_run=dry_run,
    )

    if dry_run:
        typer.echo(
            typer.style("DRY RUN - no changes will be made", fg=typer.colors.YELLOW)
        )

    total_found = 0
    total_migrated = 0
    total_skipped = 0

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

        for i, single_run_dir in enumerate(run_dirs, 1):
            typer.echo(f"\nProcessing run {i}/{len(run_dirs)}: {single_run_dir.name}")

            found, migrated, skipped = _migrate_directory(
                single_run_dir, dry_run, logger
            )
            total_found += found
            total_migrated += migrated
            total_skipped += skipped

            typer.echo(
                f"  Found: {found}, Migrated: {migrated}, Already done: {skipped}"
            )
    else:
        # Single run mode
        total_found, total_migrated, total_skipped = _migrate_directory(
            results_dir, dry_run, logger
        )

    # Summary
    typer.echo("\n" + "=" * 50)
    typer.echo(
        typer.style("Summary:", bold=True)
    )
    typer.echo(f"  Files found:    {total_found}")
    typer.echo(f"  Files migrated: {total_migrated}")
    typer.echo(f"  Already done:   {total_skipped}")
    typer.echo(f"  Failed:         {total_found - total_migrated - total_skipped}")

    if dry_run and total_migrated > 0:
        typer.echo(
            typer.style(
                "\nRun without --dry-run to apply changes",
                fg=typer.colors.YELLOW,
            )
        )
