from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
import yaml
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from slop_code.common import CHECKPOINT_RESULTS_FILENAME
from slop_code.common import CONFIG_FILENAME
from slop_code.common import RUBRIC_FILENAME
from slop_code.common import SNAPSHOT_DIR_NAME
from slop_code.common import SUMMARY_FILENAME
from slop_code.entrypoints.commands import common
from slop_code.entrypoints.config import loader as config_loader
from slop_code.entrypoints.evaluation.metrics import create_problem_reports
from slop_code.entrypoints.evaluation.metrics import update_results_jsonl
from slop_code.entrypoints.utils import display_and_save_summary
from slop_code.evaluation import ProblemConfig
from slop_code.evaluation import get_available_problems
from slop_code.logging import get_logger
from slop_code.metrics import RubricProvider
from slop_code.metrics import llm_judge_snapshot_batch
from slop_code.metrics.rubric import OPENROUTER_API_KEY_ENV


def register(app: typer.Typer, name: str) -> None:
    app.command(
        name,
        help="Run LLM judge evaluation on a run directory.",
    )(judge_evaluate)


def judge_evaluate(
    ctx: typer.Context,
    run_dir: Annotated[
        Path,
        typer.Argument(
            help="Path to the agent run directory",
            exists=True,
            dir_okay=True,
            file_okay=False,
        ),
    ],
    rubric_path: Annotated[
        Path,
        typer.Option(
            "--rubric",
            "-r",
            help="Path to rubric JSONL file",
            exists=True,
            file_okay=True,
            dir_okay=False,
        ),
    ],
    model: Annotated[
        str,
        typer.Option(
            "--model",
            "-m",
            help="Anthropic model ID for grading",
        ),
    ],
    temperature: Annotated[
        float,
        typer.Option(
            "--temperature",
            help="Sampling temperature for rubric grading (default: 0).",
        ),
    ] = 0.0,
    openrouter_key_env: Annotated[
        str,
        typer.Option(
            "--key",
            "-k",
            help="Environment variable name for the API key (OpenRouter only)",
        ),
    ] = OPENROUTER_API_KEY_ENV,
    provider: Annotated[
        RubricProvider,
        typer.Option(
            "--provider",
            help="LLM provider for rubric grading",
            case_sensitive=False,
        ),
    ] = RubricProvider.OPENROUTER,
    problem_names: Annotated[
        list[str],
        typer.Option(
            "--problem",
            "-p",
            help="Filter to specific problem names (repeatable)",
        ),
    ] = [],
    thinking_tokens: Annotated[
        int | None,
        typer.Option(
            "--thinking-tokens",
            "-t",
            help="Extended thinking token budget (omit or 0 to disable)",
        ),
    ] = None,
    env_config: Annotated[
        Path | None,
        typer.Option(
            "--env-config",
            "-e",
            help="Override environment config path",
            exists=True,
            file_okay=True,
            dir_okay=False,
        ),
    ] = None,
    prefix_template: Annotated[
        Path | None,
        typer.Option(
            "--prefix-template",
            help="Path to custom prefix template (Jinja2)",
            exists=True,
            file_okay=True,
            dir_okay=False,
        ),
    ] = None,
    criteria_template: Annotated[
        Path | None,
        typer.Option(
            "--criteria-template",
            help="Path to custom criteria template (Jinja2)",
            exists=True,
            file_okay=True,
            dir_okay=False,
        ),
    ] = None,
    overwrite: Annotated[  # noqa: FBT002
        bool,
        typer.Option(
            "--overwrite",
            "-w",
            help="Re-grade checkpoints that already have rubric results",
        ),
    ] = False,
    max_items: Annotated[
        int | None,
        typer.Option(
            "--max-items",
            help="Max items per batch (uses count-based batching instead of "
            "category-based)",
        ),
    ] = None,
    max_batch_lines: Annotated[
        int,
        typer.Option(
            "--max-batch-lines",
            help="Max combined lines per file batch (default: 1000)",
        ),
    ] = 1000,
    max_batch_files: Annotated[
        int,
        typer.Option(
            "--max-batch-files",
            help="Max files per batch (default: 5)",
        ),
    ] = 5,
    max_concurrency: Annotated[
        int,
        typer.Option(
            "--max-concurrency",
            "-c",
            help="Max concurrent checkpoint evaluations (default: 30)",
        ),
    ] = 30,
    max_parallel_checkpoints: Annotated[
        int | None,
        typer.Option(
            "--max-parallel-checkpoints",
            help="Limit number of checkpoints launched at a time "
            "(chunks tasks without changing per-chunk concurrency)",
            min=1,
        ),
    ] = None,
) -> None:
    """Run LLM judge evaluation on all problems in a run directory."""
    console = Console()
    common.setup_command_logging(
        log_dir=run_dir,
        verbosity=ctx.obj.verbosity,
        log_file_name="judge.log",
        console=console,
    )
    logger = get_logger(__name__)

    # Resolve environment
    env_path = env_config or (run_dir / "environment.yaml")
    logger.info(
        "Resolved environment path for grading run",
        run_directory=str(run_dir),
        environment_path=str(env_path),
    )
    # Using the original behavior of just printing error for consistency with original code
    # However, common utility can be used if we want to standardize
    if not env_path.exists():
        console.print(f"[red]Environment config not found: {env_path}[/red]")
        raise typer.Exit(1)

    environment = config_loader.resolve_environment(env_path)

    # Get available problems
    valid_problems = get_available_problems(ctx.obj.problem_path)
    logger.info(
        "Discovered problems",
        count=len(valid_problems),
        names=sorted(valid_problems.keys()),
    )

    # Collect problems to evaluate
    problems_to_eval: list[ProblemConfig] = []
    for name in problem_names or valid_problems.keys():
        if name not in valid_problems:
            continue
        if not (run_dir / name).exists():
            continue
        problems_to_eval.append(valid_problems[name])

    if not problems_to_eval:
        console.print("[red]No problems found to evaluate[/red]")
        raise typer.Exit(1)
    logger.info(
        "Problems selected for grading",
        selected=[p.name for p in problems_to_eval],
        requested=problem_names or "all",
    )

    # Load rubric items
    items = [
        json.loads(ln) for ln in rubric_path.read_text().splitlines() if ln
    ]
    console.print(
        f"[blue]Loaded {len(items)} rubric items from {rubric_path}[/blue]"
    )
    console.print(
        "[blue]"
        f"Model: {model}, Temperature: {temperature}, "
        f"Thinking tokens: {thinking_tokens or 0}"
        "[/blue]"
    )
    console.print(f"[blue]Provider: {provider.value}[/blue]")
    if provider == RubricProvider.OPENROUTER:
        console.print(f"[blue]API key env: {openrouter_key_env}[/blue]")
    console.print(
        f"[blue]File batching: max {max_batch_lines} lines, "
        f"{max_batch_files} files/batch[/blue]"
    )
    if max_parallel_checkpoints:
        console.print(
            f"[blue]Checkpoint chunking: up to "
            f"{max_parallel_checkpoints} at a time[/blue]"
        )

    # Build filter set of checkpoints to grade (pre-filter for overwrite)
    checkpoints_filter: set[tuple[str, str]] = set()
    skipped_existing = 0
    no_snapshot_count = 0

    for prob in problems_to_eval:
        for chkpt_name in prob.checkpoints:
            snap = run_dir / prob.name / chkpt_name / SNAPSHOT_DIR_NAME
            chkpt_dir = run_dir / prob.name / chkpt_name

            if not snap.exists():
                logger.warning(
                    "Skipping checkpoint (no snapshot)",
                    problem=prob.name,
                    checkpoint=chkpt_name,
                    snapshot_dir=str(snap),
                )
                no_snapshot_count += 1
                continue
            rubric_file = chkpt_dir / RUBRIC_FILENAME
            if rubric_file.exists() and not overwrite:
                skipped_existing += 1
                logger.info(
                    "Skipping checkpoint with existing grades",
                    problem=prob.name,
                    checkpoint=chkpt_name,
                )
                continue

            checkpoints_filter.add((prob.name, chkpt_name))

    if not checkpoints_filter and skipped_existing == 0:
        console.print("[red]No checkpoints found[/red]")
        raise typer.Exit(1)

    if not checkpoints_filter and skipped_existing > 0:
        logger.info(
            "All checkpoints already graded",
            skipped_existing=skipped_existing,
            overwrite_requested=overwrite,
        )
        console.print(
            f"[yellow]All {skipped_existing} checkpoint(s) already have grades "
            f"(use --overwrite to re-grade)[/yellow]"
        )
        return

    # Log problems being evaluated
    prob_counts: dict[str, int] = {}
    for prob_name, _ in checkpoints_filter:
        prob_counts[prob_name] = prob_counts.get(prob_name, 0) + 1
    console.print(
        f"[green]Evaluating {len(checkpoints_filter)} checkpoints "
        f"across {len(prob_counts)} problems (concurrency: {max_concurrency})"
        f"[/green]"
    )
    for prob_name, count in sorted(prob_counts.items()):
        console.print(f"  [dim]• {prob_name}: {count} checkpoint(s)[/dim]")

    if skipped_existing > 0:
        console.print(
            f"[yellow]Skipping {skipped_existing} checkpoint(s) with "
            f"existing grades (use --overwrite to re-grade)[/yellow]"
        )

    # Progress tracking state
    in_progress: set[str] = set()
    completed: list[tuple[str, int]] = []
    total_to_grade = len(checkpoints_filter)

    def build_progress_panel() -> Panel:
        """Build a Rich panel showing progress."""
        lines = []

        # Header with counts
        done_count = len(completed)
        lines.append(
            f"[bold]Grading [{done_count}/{total_to_grade}] checkpoints[/bold]"
        )
        lines.append("")

        # In-progress section
        if in_progress:
            lines.append("[cyan]In progress:[/cyan]")
            for chkpt in sorted(in_progress):
                lines.append(f"  • {chkpt}")
            lines.append("")

        # Completed section (show last 10)
        if completed:
            lines.append("[green]Completed:[/green]")
            for chkpt, grades in completed[-10:]:
                lines.append(f"  ✓ {chkpt} ({grades} grades)")

        content = Text.from_markup("\n".join(lines))
        return Panel(content, title="LLM Judge Progress", border_style="blue")

    def on_start(prob_name: str, chkpt_name: str) -> None:
        """Callback when a checkpoint starts grading."""
        in_progress.add(f"{prob_name}/{chkpt_name}")
        logger.info(
            "Started grading checkpoint",
            problem=prob_name,
            checkpoint=chkpt_name,
            in_progress=len(in_progress),
        )
        live.update(build_progress_panel())

    def on_complete(prob_name: str, chkpt_name: str, grade_count: int) -> None:
        """Callback when a checkpoint completes grading."""
        key = f"{prob_name}/{chkpt_name}"
        in_progress.discard(key)
        completed.append((key, grade_count))
        logger.info(
            "Completed grading checkpoint",
            problem=prob_name,
            checkpoint=chkpt_name,
            grade_count=grade_count,
            completed=len(completed),
        )
        live.update(build_progress_panel())

    # Build problem lookup dict for callback
    problems_dict = {p.name: p for p in problems_to_eval}

    # Load problem versions (needed for reports)
    problem_versions: dict[str, str] = {}
    for prob in problems_to_eval:
        problem_yaml = run_dir / prob.name / "problem.yaml"
        if problem_yaml.exists():
            with problem_yaml.open("r") as f:
                problem_cfg = yaml.safe_load(f)
                problem_versions[prob.name] = problem_cfg.get(
                    "version", "unknown"
                )

    results_file = run_dir / CHECKPOINT_RESULTS_FILENAME

    console.print()  # Add spacing before progress
    with Live(
        build_progress_panel(), console=console, refresh_per_second=4
    ) as live:
        results = llm_judge_snapshot_batch(
            problems=problems_to_eval,
            run_dir=run_dir,
            rubric_path=rubric_path,
            environment=environment,
            model=model,
            temperature=temperature,
            thinking_tokens=thinking_tokens,
            max_checkpoint_concurrency=max_concurrency,
            prefix_template=prefix_template,
            criteria_template=criteria_template,
            max_items=max_items,
            max_batch_lines=max_batch_lines,
            max_batch_files=max_batch_files,
            checkpoints_filter=checkpoints_filter,
            on_checkpoint_start=on_start,
            on_checkpoint_complete=on_complete,
            api_key_env=openrouter_key_env,
            provider=provider,
            max_parallel_checkpoints=max_parallel_checkpoints,
        )

    # Update run-level results.jsonl (batch update as fallback)
    console.print("[blue]Updating results.jsonl...[/blue]")
    all_reports: list[dict] = []
    for prob in problems_to_eval:
        submission_dir = run_dir / prob.name
        if submission_dir.exists():
            reports, errors = create_problem_reports(submission_dir, prob)
            all_reports.extend(reports)
            for chkpt_name, error_msg in errors:
                logger.warning(
                    "Metrics error",
                    problem=prob.name,
                    checkpoint=chkpt_name,
                    error=error_msg,
                )
    if all_reports:
        update_results_jsonl(results_file, all_reports)
        console.print(
            f"[green]Updated results.jsonl with {len(all_reports)} entries[/green]"
        )
        logger.info(
            "Batch results.jsonl update complete",
            report_count=len(all_reports),
            run_directory=str(run_dir),
        )

    with (run_dir / CONFIG_FILENAME).open("r") as f:
        config = yaml.safe_load(f)
    # Display and save summary statistics (updates result.json)
    summary = display_and_save_summary(results_file, run_dir, config, console)
    if summary is None:
        console.print(
            f"[yellow]No checkpoint data available; {SUMMARY_FILENAME} not created.[/yellow]"
        )
        logger.info(
            "No summary generated (no checkpoint data)",
            run_directory=str(run_dir),
        )
    else:
        console.print(
            f"[green]Saved summary to {run_dir / SUMMARY_FILENAME}[/green]"
        )
        logger.info(
            "Saved summary file",
            summary_path=str(run_dir / SUMMARY_FILENAME),
            checkpoint_count=sum(len(c) for c in results.values()),
        )

    # Calculate costs per checkpoint and total
    def calc_checkpoint_cost(raw: dict) -> float:
        """Sum costs from raw API responses."""
        return sum(
            msg.get("usage", {}).get("cost", 0)
            for msgs in raw.values()
            for msg in msgs
        )

    total_grades = 0
    total_cost = 0.0
    checkpoint_costs: list[tuple[str, str, int, float]] = []

    for prob_name, checkpoints in results.items():
        for chkpt, (grades, raw) in checkpoints.items():
            cost = calc_checkpoint_cost(raw)
            total_grades += len(grades)
            total_cost += cost
            checkpoint_costs.append((prob_name, chkpt, len(grades), cost))

    console.print(
        f"\n[green]Done! Total grades: {total_grades:,}, "
        f"Total cost: ${total_cost:.4f}[/green]"
    )

    # Display summary table with costs
    if checkpoint_costs:
        table = Table(title="Results")
        table.add_column("Problem")
        table.add_column("Checkpoint")
        table.add_column("Grades", justify="right")
        table.add_column("Cost", justify="right")

        for prob_name, chkpt, grades, cost in sorted(checkpoint_costs):
            table.add_row(prob_name, chkpt, str(grades), f"${cost:.4f}")

        # Add total row
        table.add_section()
        table.add_row(
            "[bold]Total[/bold]",
            "",
            f"[bold]{total_grades}[/bold]",
            f"[bold]${total_cost:.4f}[/bold]",
        )

        console.print(table)
