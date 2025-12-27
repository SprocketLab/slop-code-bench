"""LLM-based rubric grading for snapshots.

This module provides functions for grading code snapshots using LLM APIs
(via OpenRouter or AWS Bedrock). It supports both single-snapshot and batch
grading modes.

Public API:
- llm_judge_snapshot: Grade a single snapshot
- llm_judge_snapshot_batch: Grade multiple checkpoints concurrently
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

from slop_code.common import RUBRIC_FILENAME
from slop_code.common import replace_spec_placeholders
from slop_code.common.render import render_criteria_text
from slop_code.common.render import render_multi_file_prefix
from slop_code.execution import EnvironmentSpec
from slop_code.logging import get_logger
from slop_code.metrics.driver import aggregate_usage
from slop_code.metrics.driver import annotate_grades_with_category
from slop_code.metrics.driver import batch_files_by_size
from slop_code.metrics.driver import build_category_map
from slop_code.metrics.driver import build_type_map
from slop_code.metrics.driver import measure_snapshot_quality
from slop_code.metrics.driver import save_rubric_results
from slop_code.metrics.languages import get_language_for_extension
from slop_code.metrics.quality_io import save_quality_metrics
from slop_code.metrics.rubric import RubricProvider
from slop_code.metrics.rubric import carry_forward_all_files
from slop_code.metrics.rubric.llm_grade import OPENROUTER_API_KEY_ENV
from slop_code.metrics.rubric.router import grade_file_async

if TYPE_CHECKING:
    from slop_code.evaluation import ProblemConfig

logger = get_logger(__name__)

# Snapshot directory name (matches agent_runner.reporting.SNAPSHOT_DIR_NAME)
SNAPSHOT_DIR_NAME = "snapshot"

# Rubric grading defaults
DEFAULT_CHECKPOINT_CONCURRENCY = 30
DEFAULT_MAX_BATCH_LINES = 1000
DEFAULT_MAX_BATCH_FILES = 5


def _run_async(coro):
    """Run async coroutine from sync context.

    Handles the case where we may or may not already be in an event loop.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    else:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()


def _build_spec_and_files(
    problem: ProblemConfig,
    checkpoint_name: str,
    snapshot_dir: Path,
    environment: EnvironmentSpec,
) -> tuple[str, list[Path]]:
    """Build spec text and find matching files for grading.

    Args:
        problem: Problem configuration.
        checkpoint_name: Name of checkpoint to grade.
        snapshot_dir: Path to snapshot directory.
        environment: Environment specification.

    Returns:
        Tuple of (spec text, list of matching files).
    """
    chkpt = problem.checkpoints[checkpoint_name]
    entry_file = environment.format_entry_file(problem.entry_file)
    entry_cmd = environment.get_command(problem.entry_file, is_agent_run=True)
    spec = replace_spec_placeholders(
        problem.get_checkpoint_spec(checkpoint_name), entry_file, entry_cmd
    )

    pattern = (
        f"**/*{Path(entry_file).suffix}" if Path(entry_file).suffix else "*"
    )
    files = [f for f in snapshot_dir.rglob(pattern) if f.is_file()]

    return spec, files


async def _llm_judge_checkpoint_async(
    problem: ProblemConfig,
    checkpoint_name: str,
    snapshot_dir: Path,
    rubric_items: list[dict],
    environment: EnvironmentSpec,
    model: str,
    temperature: float = 0.0,
    thinking_tokens: int | None = None,
    prefix_template: Path | None = None,
    criteria_template: Path | None = None,
    max_items: int | None = None,
    max_batch_lines: int = DEFAULT_MAX_BATCH_LINES,
    max_batch_files: int = DEFAULT_MAX_BATCH_FILES,
    api_key_env: str = OPENROUTER_API_KEY_ENV,
    provider: RubricProvider = RubricProvider.OPENROUTER,
) -> tuple[list[dict], dict[str, Any]]:
    """Grade a checkpoint using LLM API (OpenRouter or Bedrock).

    Items are processed sequentially within a checkpoint to benefit from
    prompt caching - the prompt prefix (spec + file content) is cached
    between requests for the same file.

    Files are always batched together using the multi-file format, with
    batching controlled by max_batch_lines and max_batch_files.
    """
    start_time = time.perf_counter()

    spec, files = _build_spec_and_files(
        problem, checkpoint_name, snapshot_dir, environment
    )

    # Always batch files using line/file limits
    file_batches = batch_files_by_size(files, max_batch_lines, max_batch_files)

    logger.info(
        "Starting LLM checkpoint grading",
        problem=problem.name,
        checkpoint=checkpoint_name,
        file_count=len(files),
        batch_count=len(file_batches),
        rubric_items=len(rubric_items),
        model=model,
        temperature=temperature,
    )
    logger.info(
        "Prepared file batches",
        problem=problem.name,
        checkpoint=checkpoint_name,
        batch_sizes=[len(b) for b in file_batches],
        max_batch_lines=max_batch_lines,
        max_batch_files=max_batch_files,
    )

    if not files:
        logger.info(
            "No files found matching pattern for checkpoint",
            problem=problem.name,
            checkpoint=checkpoint_name,
        )
        return [], {}
    if not rubric_items:
        logger.info(
            "No rubric items provided for grading",
            problem=problem.name,
            checkpoint=checkpoint_name,
        )
        return [], {}

    # Group rubric items by category or max_items
    if max_items is not None:
        sorted_items = sorted(rubric_items, key=lambda x: x["name"])
        num_batches = (len(sorted_items) + max_items - 1) // max_items
        logger.info(
            "Grouping rubric items by max_items",
            batching="max_items",
            max_items=max_items,
            num_batches=num_batches,
            total_items=len(sorted_items),
            thinking_tokens=thinking_tokens,
        )
    else:
        grouped_rubric: dict[str, list[dict]] = defaultdict(list)
        for item in rubric_items:
            grouped_rubric[item["category"]].append(item)
        logger.info(
            "Grouping rubric items by category",
            batching="category",
            num_categories=len(grouped_rubric),
            categories=sorted(grouped_rubric.keys()),
            thinking_tokens=thinking_tokens,
        )

    all_grades: list[dict] = []
    raw_results: dict[str, list] = defaultdict(list)

    # Create appropriate client based on provider
    # For OpenRouter, use httpx.AsyncClient for connection pooling
    # For Bedrock, client is created per-call (boto3 handles pooling internally)
    async_client = (
        httpx.AsyncClient()
        if provider == RubricProvider.OPENROUTER
        else None
    )

    try:
        for file_batch in file_batches:
            # Always use multi-file format
            batch_key = ",".join(
                f.relative_to(snapshot_dir).as_posix() for f in file_batch
            )
            relative_files = [
                f.relative_to(snapshot_dir).as_posix() for f in file_batch
            ]
            logger.info(
                "Preparing file batch for LLM grading",
                problem=problem.name,
                checkpoint=checkpoint_name,
                file_count=len(file_batch),
                files=relative_files,
            )
            prefix = render_multi_file_prefix(
                spec=spec,
                snapshot_dir=snapshot_dir,
                source_files=file_batch,
                prefix_template=prefix_template,
                language_resolver=get_language_for_extension,
            )
            # file_name is extracted from response blocks, not passed to API
            file_name_for_api = None

            # Build criteria batches by max_items or category
            if max_items is not None:
                criteria_batches = [
                    (
                        f"batch_{i // max_items}",
                        render_criteria_text(
                            sorted_items[i : i + max_items],
                            criteria_template,
                        ),
                    )
                    for i in range(0, len(sorted_items), max_items)
                ]
            else:
                criteria_batches = [
                    (
                        category,
                        render_criteria_text(
                            sorted(items, key=lambda x: x["name"]),
                            criteria_template,
                        ),
                    )
                    for category, items in grouped_rubric.items()
                ]

            if not criteria_batches:
                continue

            # First batch: blocking call to populate cache
            first_category, first_criteria = criteria_batches[0]
            first_grades, first_raw = await grade_file_async(
                prompt_prefix=prefix,
                criteria_text=first_criteria,
                file_name=file_name_for_api,
                model=model,
                temperature=temperature,
                provider=provider,
                thinking_tokens=thinking_tokens,
                client=async_client,
                api_key=os.getenv(api_key_env) if api_key_env else None,
                api_key_env=api_key_env,
            )

            all_grades.extend(first_grades)
            raw_results[batch_key].append(first_raw)
            first_usage = aggregate_usage({batch_key: [first_raw]})
            logger.info(
                "Received grading response for batch",
                problem=problem.name,
                checkpoint=checkpoint_name,
                batch_key=batch_key,
                criteria_group=first_category,
                grades=len(first_grades),
                prompt_tokens=first_usage["prompt_tokens"],
                completion_tokens=first_usage["completion_tokens"],
                cache_read_tokens=first_usage["cache_read_tokens"],
                cache_write_tokens=first_usage["cache_write_tokens"],
                cost=first_usage["cost"],
            )

            # Remaining batches: concurrent calls (cache is now populated)
            if len(criteria_batches) > 1:
                remaining_batches = criteria_batches[1:]
                categories = [category for category, _ in remaining_batches]
                tasks = [
                    grade_file_async(
                        prompt_prefix=prefix,
                        criteria_text=criteria,
                        file_name=file_name_for_api,
                        model=model,
                        temperature=temperature,
                        provider=provider,
                        thinking_tokens=thinking_tokens,
                        client=async_client,
                        api_key=os.getenv(api_key_env) if api_key_env else None,
                        api_key_env=api_key_env,
                    )
                    for _, criteria in remaining_batches
                ]
                results = await asyncio.gather(*tasks)
                for (grades, raw), category in zip(results, categories):
                    all_grades.extend(grades)
                    raw_results[batch_key].append(raw)
                    batch_usage = aggregate_usage({batch_key: [raw]})
                    logger.info(
                        "Received grading response for batch",
                        problem=problem.name,
                        checkpoint=checkpoint_name,
                        batch_key=batch_key,
                        criteria_group=category,
                        grades=len(grades),
                        prompt_tokens=batch_usage["prompt_tokens"],
                        completion_tokens=batch_usage["completion_tokens"],
                        cache_read_tokens=batch_usage["cache_read_tokens"],
                        cache_write_tokens=batch_usage["cache_write_tokens"],
                        cost=batch_usage["cost"],
                    )
    finally:
        if async_client is not None:
            await async_client.aclose()

    elapsed = time.perf_counter() - start_time
    usage = aggregate_usage(raw_results)

    logger.info(
        "LLM checkpoint grading complete",
        problem=problem.name,
        cost=usage["cost"],
        checkpoint=checkpoint_name,
        grade_count=len(all_grades),
        elapsed_seconds=round(elapsed, 2),
        prompt_tokens=usage["prompt_tokens"],
        completion_tokens=usage["completion_tokens"],
        total_tokens=usage["total_tokens"],
        cache_read_tokens=usage["cache_read_tokens"],
        cache_write_tokens=usage["cache_write_tokens"],
    )

    return all_grades, dict(raw_results)


def llm_judge_snapshot(
    problem: ProblemConfig,
    checkpoint_name: str,
    snapshot_dir: Path,
    rubric_path: Path,
    environment: EnvironmentSpec,
    model: str,
    temperature: float = 0.0,
    thinking_tokens: int | None = None,
    prefix_template: Path | None = None,
    criteria_template: Path | None = None,
    max_items: int | None = None,
    *,
    max_batch_lines: int = DEFAULT_MAX_BATCH_LINES,
    max_batch_files: int = DEFAULT_MAX_BATCH_FILES,
    api_key_env: str = OPENROUTER_API_KEY_ENV,
    provider: RubricProvider = RubricProvider.OPENROUTER,
) -> tuple[list[dict], dict[str, Any]]:
    """Judge a snapshot using LLM API (OpenRouter or Bedrock).

    Args:
        problem: Problem configuration.
        checkpoint_name: Name of checkpoint to grade.
        snapshot_dir: Path to snapshot directory.
        rubric_path: Path to rubric JSONL file.
        environment: Environment specification.
        model: Model ID in provider-specific format.
        temperature: Sampling temperature for the model.
        thinking_tokens: Extended thinking token budget (None or 0 to disable).
        prefix_template: Optional path to custom prefix template (unused).
        criteria_template: Optional path to custom criteria template.
        max_items: Max items per batch (None uses category-based grouping).
        max_batch_lines: Max combined lines per file batch.
        max_batch_files: Max files per batch.
        api_key_env: Environment variable for API key (OpenRouter only).
        provider: LLM provider to use (openrouter or bedrock).

    Returns:
        Tuple of (grades list, raw responses dict).
    """
    items = [
        json.loads(ln) for ln in rubric_path.read_text().splitlines() if ln
    ]

    logger.info(
        "Loaded rubric items for LLM grading",
        rubric_path=rubric_path.name,
        item_count=len(items),
        model=model,
        temperature=temperature,
        thinking_tokens=thinking_tokens,
        provider=provider.value,
    )

    return _run_async(
        _llm_judge_checkpoint_async(
            problem=problem,
            checkpoint_name=checkpoint_name,
            snapshot_dir=snapshot_dir,
            rubric_items=items,
            environment=environment,
            model=model,
            temperature=temperature,
            thinking_tokens=thinking_tokens,
            prefix_template=prefix_template,
            criteria_template=criteria_template,
            max_items=max_items,
            max_batch_lines=max_batch_lines,
            max_batch_files=max_batch_files,
            api_key_env=api_key_env,
            provider=provider,
        )
    )


def _load_diff_file(diff_path: Path) -> dict[str, str]:
    """Load diff.json and extract diff_text per file."""
    if not diff_path.exists():
        return {}

    diff_data = json.loads(diff_path.read_text())
    file_diffs: dict[str, str] = {}

    for file_name, file_diff in diff_data.get("file_diffs", {}).items():
        diff_text = file_diff.get("diff_text", "")
        if diff_text:
            file_diffs[file_name] = diff_text

    return file_diffs


def _carry_forward_batch(
    run_dir: Path,
    results: dict[str, dict[str, tuple[list[dict], dict]]],
) -> int:
    """Carry forward grades from previous checkpoints within each problem.

    Args:
        run_dir: Directory containing run results.
        results: Grading results by problem and checkpoint.

    Returns:
        Total number of grades carried forward across all checkpoints.
    """
    total_carried = 0

    for prob_name, checkpoints in results.items():
        # Sort checkpoints by number
        chkpt_pattern = re.compile(r"^checkpoint_(\d+)$")
        sorted_chkpts = sorted(
            checkpoints.keys(),
            key=lambda x: int(chkpt_pattern.match(x).group(1))
            if chkpt_pattern.match(x)
            else 0,
        )

        prev_checkpoint_name: str | None = None
        prev_grades: list[dict] | None = None

        for chkpt_name in sorted_chkpts:
            chkpt_dir = run_dir / prob_name / chkpt_name
            rubric_path = chkpt_dir / "rubric.jsonl"
            diff_path = chkpt_dir / "diff.json"

            # Load current grades
            current_grades, _ = results[prob_name][chkpt_name]

            if prev_grades is None or prev_checkpoint_name is None:
                # First checkpoint - nothing to carry forward
                prev_grades = current_grades
                prev_checkpoint_name = chkpt_name
                continue

            # Load diff
            file_diffs = _load_diff_file(diff_path)

            # Carry forward grades
            carried = carry_forward_all_files(
                prev_grades=prev_grades,
                new_grades=current_grades,
                file_diffs=file_diffs,
                prev_checkpoint_name=prev_checkpoint_name,
            )

            if carried:
                # Merge and save
                merged = current_grades + carried
                with rubric_path.open("w") as f:
                    for g in merged:
                        f.write(json.dumps(g) + "\n")

                logger.info(
                    "Carried forward grades",
                    problem=prob_name,
                    checkpoint=chkpt_name,
                    carried_count=len(carried),
                )
                total_carried += len(carried)

            # Update for next iteration
            prev_grades = current_grades + carried
            prev_checkpoint_name = chkpt_name

    return total_carried


def llm_judge_snapshot_batch(
    problems: list[ProblemConfig],
    run_dir: Path,
    rubric_path: Path,
    environment: EnvironmentSpec,
    model: str,
    temperature: float = 0.0,
    thinking_tokens: int | None = None,
    max_checkpoint_concurrency: int = DEFAULT_CHECKPOINT_CONCURRENCY,
    prefix_template: Path | None = None,
    criteria_template: Path | None = None,
    max_items: int | None = None,
    *,
    max_batch_lines: int = DEFAULT_MAX_BATCH_LINES,
    max_batch_files: int = DEFAULT_MAX_BATCH_FILES,
    checkpoints_filter: set[tuple[str, str]] | None = None,
    on_checkpoint_start: Callable[[str, str], None] | None = None,
    on_checkpoint_complete: Callable[[str, str, int], None] | None = None,
    on_checkpoint_saved: Callable[[str, str], None] | None = None,
    api_key_env: str = OPENROUTER_API_KEY_ENV,
    provider: RubricProvider = RubricProvider.OPENROUTER,
    max_parallel_checkpoints: int | None = None,
) -> dict[str, dict[str, tuple[list[dict], dict]]]:
    """Run LLM rubric grading across checkpoints concurrently.

    Checkpoints are processed concurrently (up to max_checkpoint_concurrency),
    but within each checkpoint, rubric items are grouped by category with
    each category processed as a separate API call.

    Args:
        problems: List of problem configurations.
        run_dir: Directory containing run results.
        rubric_path: Path to rubric JSONL file.
        environment: Environment specification.
        model: Model ID in provider-specific format.
        temperature: Sampling temperature for the model.
        thinking_tokens: Extended thinking token budget (None or 0 to disable).
        max_checkpoint_concurrency: Max concurrent checkpoint evaluations.
        prefix_template: Optional path to custom prefix template (unused).
        criteria_template: Optional path to custom criteria template.
        max_items: Max items per batch (None uses category-based grouping).
        max_batch_lines: Max combined lines per file batch.
        max_batch_files: Max files per batch.
        checkpoints_filter: Optional set of (problem_name, checkpoint_name)
            tuples to grade. If provided, only these checkpoints are graded.
        on_checkpoint_start: Callback called when a checkpoint starts grading.
            Receives (problem_name, checkpoint_name).
        on_checkpoint_complete: Callback called when a checkpoint completes.
            Receives (problem_name, checkpoint_name, grade_count).
        on_checkpoint_saved: Callback called after checkpoint data is saved.
            Receives (problem_name, checkpoint_name).
        api_key_env: Environment variable for API key (OpenRouter only).
        provider: LLM provider to use (openrouter or bedrock).
        max_parallel_checkpoints: Limit on number of checkpoints to launch
            at once; tasks are chunked without changing per-chunk concurrency.

    Returns:
        Dict mapping problem names to checkpoint results.
    """
    batch_start = time.perf_counter()

    items = [
        json.loads(ln) for ln in rubric_path.read_text().splitlines() if ln
    ]
    category_map = build_category_map(items)
    type_map = build_type_map(items)

    # Build list of checkpoints to grade
    checkpoints_to_grade: list[tuple[ProblemConfig, str, Path, Path]] = []
    skipped_count = 0

    for prob in problems:
        for chkpt_name in prob.checkpoints:
            # Skip if filter is provided and checkpoint not in filter
            if (
                checkpoints_filter is not None
                and (prob.name, chkpt_name) not in checkpoints_filter
            ):
                skipped_count += 1
                continue

            snap = run_dir / prob.name / chkpt_name / SNAPSHOT_DIR_NAME
            chkpt_dir = run_dir / prob.name / chkpt_name
            if not snap.exists():
                logger.info(
                    "Skipping checkpoint (no snapshot)",
                    problem=prob.name,
                    checkpoint=chkpt_name,
                )
                skipped_count += 1
                continue
            checkpoints_to_grade.append((prob, chkpt_name, snap, chkpt_dir))

    total_checkpoints = len(checkpoints_to_grade) + skipped_count
    logger.info(
        "Starting LLM rubric batch",
        problem_count=len(problems),
        total_checkpoints=total_checkpoints,
        checkpoints_to_grade=len(checkpoints_to_grade),
        rubric_items=len(items),
        model=model,
        temperature=temperature,
        max_checkpoint_concurrency=max_checkpoint_concurrency,
    )
    logger.info(
        "Queued checkpoints for grading",
        checkpoints=[
            f"{prob.name}/{chkpt}" for prob, chkpt, _, _ in checkpoints_to_grade
        ],
        skipped_count=skipped_count,
    )

    async def _run_all(
        chunk: list[tuple[ProblemConfig, str, Path, Path]]
    ) -> list[tuple[str, str, list[dict], dict, Path]]:
        semaphore = asyncio.Semaphore(max_checkpoint_concurrency)

        async def _grade_single(
            prob: ProblemConfig,
            chkpt_name: str,
            snap: Path,
            chkpt_dir: Path,
        ) -> tuple[str, str, list[dict], dict, Path]:
            async with semaphore:
                # Call start callback
                if on_checkpoint_start is not None:
                    on_checkpoint_start(prob.name, chkpt_name)

                grades, raw = await _llm_judge_checkpoint_async(
                    problem=prob,
                    checkpoint_name=chkpt_name,
                    snapshot_dir=snap,
                    rubric_items=items,
                    environment=environment,
                    model=model,
                    temperature=temperature,
                    thinking_tokens=thinking_tokens,
                    prefix_template=prefix_template,
                    criteria_template=criteria_template,
                    max_items=max_items,
                    max_batch_lines=max_batch_lines,
                    max_batch_files=max_batch_files,
                    api_key_env=api_key_env,
                    provider=provider,
                )
                usage = aggregate_usage(raw)
                logger.info(
                    "Finished checkpoint grading",
                    problem=prob.name,
                    checkpoint=chkpt_name,
                    grade_count=len(grades),
                    prompt_tokens=usage["prompt_tokens"],
                    completion_tokens=usage["completion_tokens"],
                    cache_read_tokens=usage["cache_read_tokens"],
                    cache_write_tokens=usage["cache_write_tokens"],
                    cost=usage["cost"],
                )
                return prob.name, chkpt_name, grades, raw, chkpt_dir

        tasks = [
            asyncio.create_task(
                _grade_single(prob, chkpt_name, snap, chkpt_dir)
            )
            for prob, chkpt_name, snap, chkpt_dir in chunk
        ]

        results: list[tuple[str, str, list[dict], dict, Path]] = []
        for coro in asyncio.as_completed(tasks):
            result = await coro
            prob_name, chkpt_name, grades, raw, chkpt_dir = result

            # Annotate grades with category and type before saving
            annotate_grades_with_category(grades, category_map, type_map)

            # Save rubric results immediately
            save_rubric_results(chkpt_dir, grades, raw)
            logger.info(
                "Saved rubric artifacts",
                problem=prob_name,
                checkpoint=chkpt_name,
                rubric_path=str(chkpt_dir / RUBRIC_FILENAME),
                raw_path=str(chkpt_dir / "raw_rubric.json"),
                grade_count=len(grades),
            )

            # Calculate and save quality metrics
            snap_dir = chkpt_dir / SNAPSHOT_DIR_NAME
            if snap_dir.exists():
                # Find the problem config for this checkpoint
                problem = next(p for p in problems if p.name == prob_name)
                entry_file = environment.format_entry_file(problem.entry_file)

                quality_result, file_metrics_list = measure_snapshot_quality(
                    entry_file, snap_dir
                )

                # Save quality metrics to flat files
                save_quality_metrics(
                    chkpt_dir, quality_result, file_metrics_list
                )
                logger.info(
                    "Saved quality metrics",
                    problem=prob_name,
                    checkpoint=chkpt_name,
                    files_scored=len(file_metrics_list),
                )

            # Call saved callback (after all data is written)
            if on_checkpoint_saved is not None:
                on_checkpoint_saved(prob_name, chkpt_name)

            # Call complete callback
            if on_checkpoint_complete is not None:
                on_checkpoint_complete(prob_name, chkpt_name, len(grades))

            results.append(result)

        return results

    def _chunked(
        seq: list[tuple[ProblemConfig, str, Path, Path]], size: int
    ):
        for i in range(0, len(seq), size):
            yield seq[i : i + size]

    if max_parallel_checkpoints is not None and max_parallel_checkpoints <= 0:
        logger.warning(
            "Ignoring non-positive max_parallel_checkpoints, using full batch",
            max_parallel_checkpoints=max_parallel_checkpoints,
        )
        chunk_size = len(checkpoints_to_grade)
    else:
        chunk_size = max_parallel_checkpoints or len(checkpoints_to_grade)
    grading_results: list[tuple[str, str, list[dict], dict, Path]] = []
    chunk_index = 0

    for chunk in _chunked(checkpoints_to_grade, chunk_size):
        chunk_index += 1
        logger.info(
            "Starting checkpoint chunk",
            chunk_index=chunk_index,
            chunk_size=len(chunk),
            chunk_limit=max_parallel_checkpoints,
        )
        chunk_results = _run_async(_run_all(chunk))
        grading_results.extend(chunk_results)
        logger.info(
            "Finished checkpoint chunk",
            chunk_index=chunk_index,
            chunk_size=len(chunk),
            chunk_limit=max_parallel_checkpoints,
        )

    # Process results and save
    results: dict[str, dict[str, tuple[list[dict], dict]]] = {}
    total_grades = 0
    total_tokens = 0
    total_cache_read = 0
    total_cache_write = 0

    for prob_name, chkpt_name, grades, raw, chkpt_dir in grading_results:
        results.setdefault(prob_name, {})[chkpt_name] = (grades, raw)
        total_grades += len(grades)
        usage = aggregate_usage(raw)
        total_tokens += usage["total_tokens"]
        total_cache_read += usage["cache_read_tokens"]
        total_cache_write += usage["cache_write_tokens"]

    # Carry forward grades from previous checkpoints
    total_carried = _carry_forward_batch(run_dir, results)

    batch_elapsed = time.perf_counter() - batch_start
    logger.info(
        "LLM rubric batch complete",
        checkpoints_graded=len(checkpoints_to_grade),
        checkpoints_skipped=skipped_count,
        total_grades=total_grades,
        total_carried=total_carried,
        total_tokens=total_tokens,
        cache_read_tokens=total_cache_read,
        cache_write_tokens=total_cache_write,
        elapsed_seconds=round(batch_elapsed, 2),
    )

    return results
