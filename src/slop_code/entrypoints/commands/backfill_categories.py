"""Backfill category information into existing rubric.jsonl files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from slop_code.common import RUBRIC_FILENAME
from slop_code.entrypoints.commands import common
from slop_code.entrypoints.utils import discover_run_directories
from slop_code.logging import setup_logging
from slop_code.metrics.driver import annotate_grades_with_category
from slop_code.metrics.driver import build_category_map
from slop_code.metrics.driver import build_type_map


def _load_rubric_items(rubric_path: Path) -> list[dict]:
    """Load rubric items from JSONL file."""
    return [
        json.loads(ln)
        for ln in rubric_path.read_text().splitlines()
        if ln.strip()
    ]


def _load_grades(rubric_file: Path) -> list[dict]:
    """Load grades from rubric.jsonl file."""
    grades = []
    for line in rubric_file.read_text().splitlines():
        if line.strip():
            grades.append(json.loads(line))
    return grades


def _save_grades(rubric_file: Path, grades: list[dict]) -> None:
    """Save grades to rubric.jsonl file."""
    with rubric_file.open("w") as f:
        for g in grades:
            f.write(json.dumps(g) + "\n")


def _process_single_run(
    run_dir: Path,
    category_map: dict[str, str],
    type_map: dict[str, str],
    logger,
) -> tuple[int, int, int]:
    """Process a single run directory.

    Args:
        run_dir: Path to the run directory.
        category_map: Dict mapping criteria name to category.
        type_map: Dict mapping criteria name to type.
        logger: Logger instance.

    Returns:
        Tuple of (checkpoints_processed, grades_updated, checkpoints_skipped)
    """
    checkpoints_processed = 0
    grades_updated = 0
    checkpoints_skipped = 0

    for problem_dir in run_dir.iterdir():
        if not problem_dir.is_dir() or problem_dir.name in {"agent", "logs"}:
            continue

        for checkpoint_dir in sorted(problem_dir.iterdir()):
            if not checkpoint_dir.is_dir():
                continue
            if not checkpoint_dir.name.startswith("checkpoint_"):
                continue

            rubric_file = checkpoint_dir / RUBRIC_FILENAME
            if not rubric_file.exists():
                checkpoints_skipped += 1
                logger.debug(
                    "Skipping checkpoint (no rubric file)",
                    problem=problem_dir.name,
                    checkpoint=checkpoint_dir.name,
                )
                continue

            grades = _load_grades(rubric_file)
            if not grades:
                checkpoints_skipped += 1
                logger.debug(
                    "Skipping checkpoint (no grades)",
                    problem=problem_dir.name,
                    checkpoint=checkpoint_dir.name,
                )
                continue

            # Count grades that need updating
            grades_needing_update = sum(
                1
                for g in grades
                if (
                    "category" not in g
                    and g.get("criteria", "") in category_map
                )
                or "type" not in g
            )

            if grades_needing_update == 0:
                checkpoints_skipped += 1
                logger.debug(
                    "Skipping checkpoint (all grades have categories)",
                    problem=problem_dir.name,
                    checkpoint=checkpoint_dir.name,
                )
                continue

            # Annotate and save
            annotate_grades_with_category(grades, category_map, type_map)
            _save_grades(rubric_file, grades)

            checkpoints_processed += 1
            grades_updated += grades_needing_update

            logger.info(
                "Updated checkpoint",
                problem=problem_dir.name,
                checkpoint=checkpoint_dir.name,
                grades_updated=grades_needing_update,
            )

    return checkpoints_processed, grades_updated, checkpoints_skipped


def register(app: typer.Typer, name: str) -> None:
    """Register the backfill-categories command."""
    app.command(
        name,
        help="Backfill category information into existing rubric.jsonl files",
    )(backfill_categories)


def backfill_categories(
    ctx: typer.Context,
    results_dir: Annotated[
        Path,
        typer.Argument(
            help="Path to the run directory or collection directory",
            exists=True,
            dir_okay=True,
            file_okay=False,
        ),
    ],
    rubric: Annotated[
        Path,
        typer.Option(
            "--rubric",
            "-r",
            help="Path to rubric JSONL file with category definitions",
            exists=True,
            file_okay=True,
            dir_okay=False,
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
    """Add category field to grades in existing rubric.jsonl files.

    This command reads rubric definitions from the specified JSONL file and
    adds the 'category' field to each grade in rubric.jsonl files based on
    matching the 'criteria' field to the rubric item 'name'.

    Grades that already have a 'category' field are not modified.

    Example:
        slop-code utils backfill-categories \\
            --rubric configs/rubrics/llm_judge.jsonl \\
            outputs/run_name

        slop-code utils backfill-categories \\
            --rubric configs/rubrics/llm_judge.jsonl \\
            --type collection \\
            outputs/
    """
    logger = setup_logging(
        log_dir=None,
        verbosity=ctx.obj.verbosity,
    )

    # Load rubric and build category/type maps
    rubric_items = _load_rubric_items(rubric)
    category_map = build_category_map(rubric_items)
    type_map = build_type_map(rubric_items)
    typer.echo(f"Loaded {len(rubric_items)} rubric items from {rubric}")

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

        total_checkpoints = 0
        total_grades = 0
        total_skipped = 0

        for i, run_dir in enumerate(run_dirs, 1):
            typer.echo(f"\nProcessing run {i}/{len(run_dirs)}: {run_dir.name}")

            checkpoints, grades, skipped = _process_single_run(
                run_dir, category_map, type_map, logger
            )
            total_checkpoints += checkpoints
            total_grades += grades
            total_skipped += skipped

            typer.echo(
                f"  Updated {checkpoints} checkpoint(s), "
                f"{grades} grade(s), skipped {skipped}"
            )

        typer.echo(
            f"\nTotal: {total_checkpoints} checkpoints, "
            f"{total_grades} grades updated, {total_skipped} skipped"
        )
        return

    # Single run mode
    checkpoints, grades, skipped = _process_single_run(
        results_dir, category_map, type_map, logger
    )

    typer.echo(
        f"Updated {checkpoints} checkpoint(s), "
        f"{grades} grade(s), skipped {skipped}"
    )
