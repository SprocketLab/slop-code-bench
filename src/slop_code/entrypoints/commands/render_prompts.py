"""Render prompt templates for problems to an output directory."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from slop_code.common.render import render_prompt
from slop_code.entrypoints.commands.common import load_problem_config_or_exit
from slop_code.entrypoints.config.loader import resolve_config_path
from slop_code.entrypoints.config.loader import resolve_environment
from slop_code.evaluation import ProblemConfig
from slop_code.execution.models import EnvironmentSpec
from slop_code.logging import get_logger

logger = get_logger(__name__)


def register(app: typer.Typer, name: str) -> None:
    """Register the render-prompts command with the CLI app."""
    app.command(
        name,
        help="Render prompt templates for problems to an output directory.",
    )(render_prompts)


def _load_prompt_template(prompt_ref: str) -> str:
    """Load prompt template content from reference.

    Args:
        prompt_ref: Bare name or path to prompt template.

    Returns:
        Template content as string.
    """
    prompt_path = resolve_config_path(prompt_ref, "prompts")
    return prompt_path.read_text(encoding="utf-8")


def _render_checkpoint_prompt(
    spec_text: str,
    prompt_template: str,
    environment: EnvironmentSpec,
    entry_file: str,
    *,
    is_continuation: bool,
) -> str:
    """Render a single checkpoint prompt.

    Args:
        spec_text: Checkpoint specification text.
        prompt_template: Jinja2 template string.
        environment: Environment spec for entry file formatting.
        entry_file: Problem's entry file name.
        is_continuation: Whether this is a continuation checkpoint.

    Returns:
        Rendered prompt string.
    """
    formatted_entry_file = environment.format_entry_file(entry_file)
    entry_command = environment.get_command(entry_file, is_agent_run=True)

    return render_prompt(
        spec_text=spec_text,
        context={"is_continuation": is_continuation},
        prompt_template=prompt_template,
        entry_file=formatted_entry_file,
        entry_command=entry_command,
    )


def _process_problem(
    problem_config: ProblemConfig,
    prompt_template: str,
    environment: EnvironmentSpec,
    output_dir: Path,
) -> int:
    """Process a single problem, rendering prompts for all checkpoints.

    Args:
        problem_config: Problem configuration.
        prompt_template: Jinja2 template string.
        environment: Environment spec.
        output_dir: Base output directory.

    Returns:
        Number of checkpoints rendered.
    """
    problem_output_dir = output_dir / problem_config.name
    problem_output_dir.mkdir(parents=True, exist_ok=True)

    checkpoint_count = 0
    for idx, checkpoint in enumerate(problem_config.iterate_checkpoints()):
        is_continuation = idx > 0
        spec_text = checkpoint.get_spec_text()

        rendered = _render_checkpoint_prompt(
            spec_text=spec_text,
            prompt_template=prompt_template,
            environment=environment,
            entry_file=problem_config.entry_file,
            is_continuation=is_continuation,
        )

        # Output as part_N.md (1-indexed for user friendliness)
        output_file = problem_output_dir / f"part_{idx + 1}.md"
        output_file.write_text(rendered, encoding="utf-8")

        logger.debug(
            "Rendered checkpoint prompt",
            problem=problem_config.name,
            checkpoint=checkpoint.name,
            output=str(output_file),
        )
        checkpoint_count += 1

    return checkpoint_count


def render_prompts(
    ctx: typer.Context,
    prompt: Annotated[
        str,
        typer.Option(
            "-p",
            "--prompt",
            help=(
                "Prompt template name or path "
                "(e.g., 'simple' or 'path/to/template.jinja')"
            ),
        ),
    ],
    environment: Annotated[
        str,
        typer.Option(
            "-e",
            "--environment",
            help="Environment config name or path (e.g., 'docker-python3.12-uv')",
        ),
    ],
    output_dir: Annotated[
        Path,
        typer.Option(
            "-o",
            "--output-dir",
            help="Output directory for rendered prompts",
        ),
    ],
    problem: Annotated[
        list[str] | None,
        typer.Option(
            "--problem",
            help="Problem name(s) to render (repeatable). Renders all if omitted.",
        ),
    ] = None,
) -> None:
    """Render prompt templates for problems and save to output directory.

    For each problem, iterates through all checkpoints and renders the prompt
    template with the checkpoint's spec text and appropriate context.

    Output structure:
        output_dir/
            problem_name/
                part_1.md
                part_2.md
                ...
    """
    console = Console()

    # Load prompt template
    try:
        prompt_template = _load_prompt_template(prompt)
    except FileNotFoundError as e:
        console.print(f"[red]Prompt template not found: {e}[/red]")
        raise typer.Exit(1) from e

    # Load environment config
    try:
        env_spec = resolve_environment(environment)
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]Environment config error: {e}[/red]")
        raise typer.Exit(1) from e

    # Discover problems
    problem_path: Path = ctx.obj.problem_path
    all_problem_dirs = sorted(
        d for d in problem_path.iterdir()
        if d.is_dir() and (d / "config.yaml").exists()
    )

    if not all_problem_dirs:
        console.print(f"[red]No problems found in {problem_path}[/red]")
        raise typer.Exit(1)

    # Filter by specified problem names
    if problem:
        problem_set = set(problem)
        filtered_dirs = [d for d in all_problem_dirs if d.name in problem_set]

        # Check for unknown problems
        found_names = {d.name for d in filtered_dirs}
        unknown = problem_set - found_names
        if unknown:
            console.print(
                f"[yellow]Warning: Unknown problem(s): "
                f"{', '.join(sorted(unknown))}[/yellow]"
            )

        if not filtered_dirs:
            console.print("[red]No matching problems found[/red]")
            raise typer.Exit(1)

        all_problem_dirs = filtered_dirs

    console.print(f"[green]Found {len(all_problem_dirs)} problem(s)[/green]")

    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)

    # Process each problem
    total_checkpoints = 0
    errors: list[tuple[str, str]] = []

    for problem_dir in all_problem_dirs:
        problem_config = load_problem_config_or_exit(
            problem_dir, problem_dir.name
        )

        try:
            count = _process_problem(
                problem_config=problem_config,
                prompt_template=prompt_template,
                environment=env_spec,
                output_dir=output_dir,
            )
            total_checkpoints += count
            console.print(
                f"  [green]Rendered {count} checkpoint(s) for "
                f"{problem_dir.name}[/green]"
            )
        except Exception as e:
            logger.exception(
                "Failed to process problem",
                problem=problem_dir.name,
                error=str(e),
            )
            errors.append((problem_dir.name, str(e)))

    # Summary
    console.print(
        f"\n[bold]Summary: Rendered {total_checkpoints} prompts "
        f"to {output_dir}[/bold]"
    )

    if errors:
        console.print(f"[yellow]{len(errors)} error(s):[/yellow]")
        for name, error_msg in errors:
            console.print(f"  [red]{name}: {error_msg}[/red]")
        raise typer.Exit(1)
