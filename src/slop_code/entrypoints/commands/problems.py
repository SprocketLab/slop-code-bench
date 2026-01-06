from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated

import typer
import yaml
from rich.console import Console
from rich.table import Table

from slop_code.evaluation import get_available_problems

app = typer.Typer(
    help="Commands for managing and inspecting problems.",
)

console = Console()


@app.command("ls", help="List all available problems.")
def list_problems(ctx: typer.Context) -> None:
    """List all problems with metadata in a table format."""
    problems = get_available_problems(ctx.obj.problem_path)

    table = Table(title="Available Problems")
    table.add_column("Name", style="cyan", no_wrap=True)
    table.add_column("Checkpoints", justify="center")
    table.add_column("Difficulty", style="magenta")
    table.add_column("Description")

    for name in sorted(problems.keys()):
        problem = problems[name]
        num_checkpoints = len(problem.checkpoints)
        difficulty = problem.difficulty
        description = problem.description.strip().replace("\n", " ")
        if len(description) > 60:
            description = description[:57] + "..."

        table.add_row(name, str(num_checkpoints), difficulty, description)

    console.print(table)


@app.command(
    "status", help="Check if a problem has been converted to the new format."
)
def problem_status(
    ctx: typer.Context,
    problem_name: Annotated[str, typer.Argument(help="Problem name to check")],
) -> None:
    """Check problem conversion status and show test coverage per checkpoint."""
    problem_path = ctx.obj.problem_path / problem_name

    if not problem_path.exists():
        console.print(
            f"[red]Problem '{problem_name}' not found at {problem_path}[/red]"
        )
        raise typer.Exit(1)

    config_path = problem_path / "config.yaml"
    if not config_path.exists():
        console.print(f"[red]No config.yaml found at {config_path}[/red]")
        raise typer.Exit(1)

    # Load raw YAML to get basic info (works for both old and new format)
    with config_path.open() as f:
        raw_config = yaml.safe_load(f)

    problem_name_from_config = raw_config.get("name", problem_name)
    description = raw_config.get("description", "No description")
    checkpoint_names = list(raw_config.get("checkpoints", {}).keys())

    console.print(f"\n[bold]Problem: {problem_name_from_config}[/bold]")
    console.print(f"Description: {description.strip()[:100]}...")
    console.print(f"Checkpoints: {len(checkpoint_names)}")
    console.print()

    # Check overall structure
    structure_checks = _check_structure_raw(problem_path, checkpoint_names)
    _print_structure_status(structure_checks)

    if not structure_checks["is_converted"]:
        console.print(
            "\n[yellow]Problem is NOT fully converted to new format.[/yellow]"
        )
        return

    console.print(
        "\n[green]Problem is fully converted to new format.[/green]\n"
    )

    # Show test counts per checkpoint
    _print_test_counts_raw(problem_path, checkpoint_names)


def _check_structure_raw(
    problem_path: Path, checkpoint_names: list[str]
) -> dict:
    """Check if problem has the expected new format structure."""
    tests_dir = problem_path / "tests"
    solutions_dir = problem_path / "solutions"

    checks = {
        "tests_dir": tests_dir.exists(),
        "conftest": (tests_dir / "conftest.py").exists(),
        "no_loader": not (problem_path / "loader.py").exists(),
        "no_verifier": not (problem_path / "verifier.py").exists(),
        "checkpoints": {},
    }

    for cp_name in checkpoint_names:
        cp_checks = {
            "test_file": (tests_dir / f"test_{cp_name}.py").exists(),
            "solution_dir": (solutions_dir / cp_name).exists(),
            "spec_file": (problem_path / f"{cp_name}.md").exists(),
        }
        checks["checkpoints"][cp_name] = cp_checks

    # Determine if fully converted
    checks["is_converted"] = (
        checks["tests_dir"]
        and checks["conftest"]
        and checks["no_loader"]
        and checks["no_verifier"]
        and all(all(cp.values()) for cp in checks["checkpoints"].values())
    )

    return checks


def _print_structure_status(checks: dict) -> None:
    """Print structure check results."""

    def status(ok: bool) -> str:
        return "[green]OK[/green]" if ok else "[red]MISSING[/red]"

    console.print("[bold]Structure Checks:[/bold]")
    console.print(f"  tests/ directory: {status(checks['tests_dir'])}")
    console.print(f"  tests/conftest.py: {status(checks['conftest'])}")
    console.print(f"  No loader.py (old format): {status(checks['no_loader'])}")
    console.print(
        f"  No verifier.py (old format): {status(checks['no_verifier'])}"
    )

    if checks["checkpoints"]:
        console.print("\n[bold]Checkpoint Files:[/bold]")
        for cp_name, cp_checks in checks["checkpoints"].items():
            console.print(f"  {cp_name}:")
            console.print(f"    test file: {status(cp_checks['test_file'])}")
            console.print(
                f"    solution dir: {status(cp_checks['solution_dir'])}"
            )
            console.print(f"    spec file: {status(cp_checks['spec_file'])}")


def _print_test_counts_raw(
    problem_path: Path, checkpoint_names: list[str]
) -> None:
    """Print test counts per checkpoint."""
    tests_dir = problem_path / "tests"

    table = Table(title="Test Counts by Checkpoint")
    table.add_column("Checkpoint", style="cyan")
    table.add_column("Core", justify="right")
    table.add_column("Functionality", justify="right")
    table.add_column("Error", justify="right")
    table.add_column("Total", justify="right", style="bold")

    for cp_name in sorted(checkpoint_names):
        test_file = tests_dir / f"test_{cp_name}.py"
        if not test_file.exists():
            table.add_row(cp_name, "-", "-", "-", "-")
            continue

        counts = _count_tests_in_file(test_file)
        table.add_row(
            cp_name,
            str(counts["core"]),
            str(counts["functionality"]),
            str(counts["error"]),
            str(counts["total"]),
        )

    console.print(table)


def _count_tests_in_file(test_file: Path) -> dict:
    """Count tests by type in a test file using regex."""
    content = test_file.read_text()

    # Find all test function definitions
    test_pattern = re.compile(r"^def (test_\w+)\s*\(", re.MULTILINE)
    all_tests = test_pattern.findall(content)
    total = len(all_tests)

    # Count marked tests by looking for marker + function pattern
    # Look for @pytest.mark.X followed by def test_
    functionality_pattern = re.compile(
        r"@pytest\.mark\.functionality\s*\n(?:@[\w\.]+\([^)]*\)\s*\n)*def test_\w+",
        re.MULTILINE,
    )
    error_pattern = re.compile(
        r"@pytest\.mark\.error\s*\n(?:@[\w\.]+\([^)]*\)\s*\n)*def test_\w+",
        re.MULTILINE,
    )

    functionality_count = len(functionality_pattern.findall(content))
    error_count = len(error_pattern.findall(content))
    core_count = total - functionality_count - error_count

    return {
        "total": total,
        "core": core_count,
        "functionality": functionality_count,
        "error": error_count,
    }
