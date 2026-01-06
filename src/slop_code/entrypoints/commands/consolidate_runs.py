"""Consolidate multiple runs into analysis-friendly CSV format."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

import pandas as pd
import typer

from slop_code.common import CHECKPOINT_RESULTS_FILENAME
from slop_code.logging import get_logger, setup_logging

logger = get_logger(__name__)

# Key columns present in ALL files
KEY_COLS = ["setup", "run_id", "problem", "checkpoint"]

IDENTITY_COLS = KEY_COLS + [
    "model",
    "agent",
    "agent_version",
    "thinking",
    "prompt",
    "timestamp",
    "idx",
    "state",
    "is_first",
    "is_last",
    "started",
    "ended",
    "elapsed",
    "version",
    "path",
]

TEST_COLS = KEY_COLS + [
    "pass_rate",
    "core_pass_rate",
    "checkpoint_pass_rate",
    "duration",
    "total_tests",
    "passed_tests",
    "core_total",
    "core_passed",
    "functionality_total",
    "functionality_passed",
    "error_total",
    "error_passed",
    "regression_total",
    "regression_passed",
]

INFERENCE_COLS = KEY_COLS + [
    "cost",
    "steps",
    "cache_read",
    "cache_write",
    "input",
    "output",
    "reasoning",
]

CODE_STATS_COLS = KEY_COLS + [
    "loc",
    "total_lines",
    "single_comments",
    "files",
    "functions",
    "methods",
    "classes",
    "statements",
    "symbols_total",
    "source_file_count",
]

# Complexity cols use prefix matching
COMPLEXITY_PREFIXES = [
    "cc_",
    "nesting_",
    "branches_",
    "comparisons_",
    "control_",
    "lint_",
    "ast_grep_",
    "sg_",
]

# Mass cols (important complexity metrics - warn if missing)
MASS_PREFIX = "mass."
EXPECTED_MASS_COLS = [
    "mass.complexity",
    "mass.branches",
    "mass.comparisons",
    "mass.vars_used",
    "mass.vars_defined",
    "mass.try_scaffold",
    "mass.top50_count",
    "mass.top50_mass",
    "mass.top75_count",
    "mass.top75_mass",
    "mass.top90_count",
    "mass.top90_mass",
    "mass.high_cc",
    "mass.high_cc_pct",
]

# Delta cols use prefix matching
DELTA_PREFIXES = ["delta.", "lines_added", "lines_removed", "churn_ratio"]

REQUIRED_RESULT_FIELDS = ["model", "agent_type", "thinking", "prompt"]


def register(app: typer.Typer, name: str) -> None:
    """Register the consolidate-runs command."""
    app.command(
        name,
        help="Consolidate runs into analysis-friendly CSVs for agent-based analysis.",
    )(consolidate_runs)


def consolidate_runs(
    ctx: typer.Context,
    runs_dir: Annotated[
        Path,
        typer.Argument(
            help="Directory containing run outputs to consolidate",
            exists=True,
            file_okay=False,
            dir_okay=True,
        ),
    ],
    output_dir: Annotated[
        Path,
        typer.Argument(
            help="Output directory for consolidated CSVs",
        ),
    ],
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            "-f",
            help="Overwrite existing output directory",
        ),
    ] = False,
    skip_quality: Annotated[
        bool,
        typer.Option(
            "--skip-quality",
            help="Skip quality analysis files (files.jsonl, symbols.jsonl, ast_grep.jsonl)",
        ),
    ] = False,
    skip_rubric: Annotated[
        bool,
        typer.Option(
            "--skip-rubric",
            help="Skip rubric data processing",
        ),
    ] = False,
    skip_evaluations: Annotated[
        bool,
        typer.Option(
            "--skip-evaluations",
            help="Skip evaluation.json expansion",
        ),
    ] = False,
) -> None:
    """Consolidate multiple runs into analysis-friendly CSV format.

    Discovers runs in the given directory, validates them, and produces
    domain-specific CSV files optimized for AI agent analysis.
    """
    setup_logging(log_dir=None, verbosity=ctx.obj.verbosity)

    # Validate output directory
    if output_dir.exists() and not force:
        typer.echo(
            typer.style(
                f"Output directory already exists: {output_dir} (use --force to overwrite)",
                fg=typer.colors.RED,
                bold=True,
            )
        )
        raise typer.Exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)

    # Discover valid runs
    typer.echo(f"Discovering runs in {runs_dir}...")
    runs = list(discover_runs(runs_dir))

    if not runs:
        typer.echo(
            typer.style(
                "No valid runs found (each run needs result.json, checkpoint_results.jsonl, and valid config.yaml)",
                fg=typer.colors.RED,
                bold=True,
            )
        )
        raise typer.Exit(1)

    typer.echo(f"Found {len(runs)} valid run(s)")

    # Collect data
    all_checkpoints: list[dict[str, Any]] = []
    all_runs: list[dict[str, Any]] = []
    all_quality_files: list[dict[str, Any]] = []
    all_quality_symbols: list[dict[str, Any]] = []
    all_ast_violations: list[dict[str, Any]] = []
    all_evaluations: list[dict[str, Any]] = []
    all_rubric: list[dict[str, Any]] = []
    runs_missing_mass: set[str] = set()  # Track runs missing mass columns

    for run_dir, result in runs:
        timestamp = extract_timestamp(run_dir)
        setup, run_id = build_keys(result, timestamp)

        # Get relative path for display
        try:
            rel_path = run_dir.relative_to(runs_dir)
        except ValueError:
            rel_path = run_dir

        # Load checkpoints first to check for mass columns
        checkpoint_results_path = run_dir / CHECKPOINT_RESULTS_FILENAME
        checkpoint_records = list(
            load_checkpoint_results(checkpoint_results_path)
        )

        # Check if any checkpoint is missing mass columns - skip entire run if so
        if checkpoint_records and check_mass_columns(checkpoint_records[0]):
            typer.echo(
                typer.style(f"  SKIP: ", fg=typer.colors.YELLOW)
                + f"{rel_path} (missing mass.* columns)"
            )
            runs_missing_mass.add(run_id)
            continue

        typer.echo(f"  Processing: {run_id}")

        # Add run-level data
        run_record = flatten_result(result, setup, run_id, timestamp)
        all_runs.append(run_record)

        # Process checkpoints
        for checkpoint_record in checkpoint_records:
            # Add foreign keys
            checkpoint_record["setup"] = setup
            checkpoint_record["run_id"] = run_id
            checkpoint_record["model"] = result.get("model")
            checkpoint_record["agent"] = result.get("agent_type")
            checkpoint_record["agent_version"] = result.get("agent_version")
            checkpoint_record["thinking"] = result.get("thinking")
            checkpoint_record["prompt"] = result.get("prompt")
            checkpoint_record["timestamp"] = timestamp

            all_checkpoints.append(checkpoint_record)

            # Process quality analysis if not skipped
            if not skip_quality:
                problem = checkpoint_record.get("problem")
                checkpoint = checkpoint_record.get("checkpoint")
                problem_dir = run_dir / problem
                checkpoint_dir = problem_dir / checkpoint
                quality_dir = checkpoint_dir / "quality_analysis"

                if quality_dir.exists():
                    # Load files.jsonl
                    files_path = quality_dir / "files.jsonl"
                    if files_path.exists():
                        for record in load_jsonl(files_path):
                            record["setup"] = setup
                            record["run_id"] = run_id
                            record["problem"] = problem
                            record["checkpoint"] = checkpoint
                            all_quality_files.append(record)

                    # Load symbols.jsonl
                    symbols_path = quality_dir / "symbols.jsonl"
                    if symbols_path.exists():
                        for record in load_jsonl(symbols_path):
                            record["setup"] = setup
                            record["run_id"] = run_id
                            record["problem"] = problem
                            record["checkpoint"] = checkpoint
                            all_quality_symbols.append(record)

                    # Load ast_grep.jsonl
                    ast_grep_path = quality_dir / "ast_grep.jsonl"
                    if ast_grep_path.exists():
                        for record in load_jsonl(ast_grep_path):
                            record["setup"] = setup
                            record["run_id"] = run_id
                            record["problem"] = problem
                            record["checkpoint"] = checkpoint
                            all_ast_violations.append(record)

            # Process evaluation.json if not skipped
            if not skip_evaluations:
                problem = checkpoint_record.get("problem")
                checkpoint = checkpoint_record.get("checkpoint")
                problem_dir = run_dir / problem
                checkpoint_dir = problem_dir / checkpoint
                eval_path = checkpoint_dir / "evaluation.json"

                if eval_path.exists():
                    try:
                        eval_json = json.loads(eval_path.read_text())
                        eval_rows = expand_evaluation(
                            eval_json, setup, run_id, problem, checkpoint
                        )
                        all_evaluations.extend(eval_rows)
                    except json.JSONDecodeError:
                        logger.warning(
                            "Failed to parse evaluation.json",
                            path=str(eval_path),
                        )

            # Process rubric if not skipped
            if not skip_rubric:
                problem = checkpoint_record.get("problem")
                checkpoint = checkpoint_record.get("checkpoint")
                problem_dir = run_dir / problem
                checkpoint_dir = problem_dir / checkpoint
                rubric_path = checkpoint_dir / "rubric.jsonl"

                if rubric_path.exists():
                    for record in load_jsonl(rubric_path):
                        record["setup"] = setup
                        record["run_id"] = run_id
                        record["problem"] = problem
                        record["checkpoint"] = checkpoint
                        all_rubric.append(record)

    # Write output files
    typer.echo(f"\nWriting output to {output_dir}...")

    # Write runs.csv
    if all_runs:
        runs_df = pd.DataFrame(all_runs)
        runs_df.to_csv(output_dir / "runs.csv", index=False)
        typer.echo(f"  runs.csv: {len(runs_df)} rows")

    # Write checkpoint files
    if all_checkpoints:
        checkpoints_df = pd.DataFrame(all_checkpoints)
        domain_dfs = split_checkpoint_columns(checkpoints_df)

        for name, df in domain_dfs.items():
            if not df.empty:
                filename = f"{name}.csv"
                df.to_csv(output_dir / filename, index=False)
                typer.echo(
                    f"  {filename}: {len(df)} rows, {len(df.columns)} cols"
                )

    # Write quality files
    if all_quality_files:
        df = pd.DataFrame(all_quality_files)
        df.to_csv(output_dir / "quality_files.csv", index=False)
        typer.echo(f"  quality_files.csv: {len(df)} rows")

    if all_quality_symbols:
        df = pd.DataFrame(all_quality_symbols)
        df.to_csv(
            output_dir / "quality_symbols.csv.gz",
            index=False,
            compression="gzip",
        )
        typer.echo(f"  quality_symbols.csv.gz: {len(df)} rows (compressed)")

    if all_ast_violations:
        df = pd.DataFrame(all_ast_violations)
        df.to_csv(
            output_dir / "quality_ast_violations.csv.gz",
            index=False,
            compression="gzip",
        )
        typer.echo(
            f"  quality_ast_violations.csv.gz: {len(df)} rows (compressed)"
        )

    # Write evaluations
    if all_evaluations:
        df = pd.DataFrame(all_evaluations)
        df.to_csv(
            output_dir / "evaluations.csv.gz", index=False, compression="gzip"
        )
        typer.echo(f"  evaluations.csv.gz: {len(df)} rows (compressed)")

    # Write rubric
    if all_rubric:
        df = pd.DataFrame(all_rubric)
        df.to_csv(output_dir / "rubric.csv", index=False)
        typer.echo(f"  rubric.csv: {len(df)} rows")

    # Generate manifest
    stats = {
        "runs": len(all_runs),
        "checkpoints": len(all_checkpoints),
        "quality_files": len(all_quality_files),
        "quality_symbols": len(all_quality_symbols),
        "ast_violations": len(all_ast_violations),
        "evaluations": len(all_evaluations),
        "rubric_entries": len(all_rubric),
    }
    generate_manifest(output_dir, runs_dir, stats)
    typer.echo("  manifest.json: generated")

    # Show summary for skipped runs
    if runs_missing_mass:
        typer.echo(
            typer.style(
                f"\nSkipped {len(runs_missing_mass)} run(s) missing mass.* columns",
                fg=typer.colors.YELLOW,
            )
        )

    processed_count = len(runs) - len(runs_missing_mass)
    typer.echo(
        typer.style(
            f"\nConsolidation complete! {processed_count} runs -> {output_dir}",
            fg=typer.colors.GREEN,
            bold=True,
        )
    )


def discover_runs(runs_dir: Path) -> Iterator[tuple[Path, dict[str, Any]]]:
    """Find all valid run directories and load their result.json."""
    for result_json in runs_dir.rglob("result.json"):
        run_dir = result_json.parent
        # Get path relative to input dir for cleaner output
        try:
            rel_path = run_dir.relative_to(runs_dir)
        except ValueError:
            rel_path = run_dir

        if not (run_dir / CHECKPOINT_RESULTS_FILENAME).exists():
            continue

        # Validate result.json
        try:
            result = json.loads(result_json.read_text())
            if not all(k in result for k in REQUIRED_RESULT_FIELDS):
                missing = [k for k in REQUIRED_RESULT_FIELDS if k not in result]
                typer.echo(
                    typer.style(f"  SKIP: ", fg=typer.colors.YELLOW)
                    + f"{rel_path} (result.json missing: {', '.join(missing)})"
                )
                continue
        except json.JSONDecodeError as e:
            typer.echo(
                typer.style(f"  SKIP: ", fg=typer.colors.YELLOW)
                + f"{rel_path} (invalid result.json: {e})"
            )
            continue

        # Validate config.yaml against current schema
        config_path = run_dir / "config.yaml"
        if not validate_config(config_path, rel_path):
            continue  # Message already printed in validate_config

        yield run_dir, result


def validate_config(config_path: Path, rel_path: Path) -> bool:
    """Check if config.yaml is valid against current schema."""
    if not config_path.exists():
        typer.echo(
            typer.style(f"  SKIP: ", fg=typer.colors.YELLOW)
            + f"{rel_path} (missing config.yaml)"
        )
        return False

    try:
        from slop_code.entrypoints.config.loader import load_config_from_run_dir

        load_config_from_run_dir(config_path.parent)
        return True
    except Exception as e:
        typer.echo(
            typer.style(f"  SKIP: ", fg=typer.colors.YELLOW)
            + f"{rel_path} (config.yaml invalid: {e})"
        )
        return False


def build_keys(result: dict[str, Any], timestamp: str) -> tuple[str, str]:
    """Build setup (grouping key) and run_id (unique key) from result.json fields."""
    setup = (
        f"{result['model']}_{result['agent_type']}_"
        f"{result.get('agent_version', 'unknown')}_{result['thinking']}_{result['prompt']}"
    )
    run_id = f"{setup}_{timestamp}"
    return setup, run_id


def extract_timestamp(run_dir: Path) -> str:
    """Extract timestamp from directory name (e.g., '20251226T1952')."""
    return run_dir.name


def check_mass_columns(record: dict[str, Any]) -> bool:
    """Check if expected mass.* columns are missing. Returns True if missing."""
    present_mass_cols = [k for k in record.keys() if k.startswith("mass.")]
    missing = set(EXPECTED_MASS_COLS) - set(present_mass_cols)
    return len(missing) > 0


def flatten_result(
    result: dict[str, Any], setup: str, run_id: str, timestamp: str
) -> dict[str, Any]:
    """Flatten result.json into a single row for runs.csv."""
    flat: dict[str, Any] = {
        "setup": setup,
        "run_id": run_id,
        "timestamp": timestamp,
        "model": result.get("model"),
        "agent_type": result.get("agent_type"),
        "agent_version": result.get("agent_version"),
        "thinking": result.get("thinking"),
        "prompt": result.get("prompt"),
        "num_problems": result.get("num_problems"),
        "num_checkpoints": result.get("num_checkpoints"),
    }

    # Flatten nested cost stats
    costs = result.get("costs", {})
    if costs:
        flat["cost_total"] = costs.get("total")
        for level in ["checkpoint", "problem"]:
            if level in costs:
                for stat in ["mean", "stddev", "min", "max", "median", "count"]:
                    flat[f"cost_{level}_{stat}"] = costs[level].get(stat)

    # Flatten nested time stats
    time_stats = result.get("time", {})
    if time_stats:
        for level in ["checkpoint", "problem"]:
            if level in time_stats:
                for stat in ["mean", "stddev", "min", "max", "median", "count"]:
                    flat[f"time_{level}_{stat}"] = time_stats[level].get(stat)

    # Flatten solve metrics
    for key in [
        "checkpoints_solved",
        "checkpoints_iso_solved",
        "checkpoints_core_solved",
        "problem_solved",
        "problem_partial",
        "pct_checkpoints_solved",
        "pct_checkpoints_iso_solved",
        "pct_problems_solved",
        "pct_problems_partial",
        "pct_checkpoints_core_solved",
    ]:
        flat[key] = result.get(key)

    # Flatten pass_rates
    pass_rates = result.get("pass_rates", {})
    if pass_rates:
        for level in ["checkpoint", "problem"]:
            if level in pass_rates:
                for rate_type in [
                    "core",
                    "total",
                    "error",
                    "functionality",
                    "regression",
                ]:
                    flat[f"pass_rate_{level}_{rate_type}"] = pass_rates[
                        level
                    ].get(rate_type)

    return flat


def load_checkpoint_results(results_path: Path) -> Iterator[dict[str, Any]]:
    """Stream a checkpoint_results.jsonl file as dicts."""
    try:
        with results_path.open(encoding="utf-8") as f:
            for idx, line in enumerate(f, start=1):
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    yield json.loads(stripped)
                except json.JSONDecodeError as exc:
                    logger.warning(
                        "Skipping malformed JSONL line",
                        path=str(results_path),
                        line_number=idx,
                        error=str(exc),
                    )
    except OSError as exc:
        logger.warning(
            "Failed to read checkpoint results",
            path=str(results_path),
            error=str(exc),
        )


def load_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    """Load a JSONL file as an iterator of dicts."""
    try:
        with path.open(encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped:
                    try:
                        yield json.loads(stripped)
                    except json.JSONDecodeError:
                        pass
    except OSError:
        pass


def split_checkpoint_columns(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Split checkpoint DataFrame into domain-specific DataFrames."""
    result: dict[str, pd.DataFrame] = {}

    # Get available columns
    all_cols = set(df.columns)

    # Identity columns
    identity_cols = [c for c in IDENTITY_COLS if c in all_cols]
    if identity_cols:
        result["checkpoints_identity"] = df[identity_cols].copy()

    # Test columns
    test_cols = [c for c in TEST_COLS if c in all_cols]
    if test_cols:
        result["checkpoints_tests"] = df[test_cols].copy()

    # Inference columns
    inference_cols = [c for c in INFERENCE_COLS if c in all_cols]
    if inference_cols:
        result["checkpoints_inference"] = df[inference_cols].copy()

    # Code stats columns
    code_stats_cols = [c for c in CODE_STATS_COLS if c in all_cols]
    if code_stats_cols:
        result["checkpoints_code_stats"] = df[code_stats_cols].copy()

    # Complexity columns (prefix matching)
    complexity_cols = KEY_COLS.copy()
    for col in all_cols:
        if any(col.startswith(prefix) for prefix in COMPLEXITY_PREFIXES):
            complexity_cols.append(col)
    complexity_cols = [c for c in complexity_cols if c in all_cols]
    if len(complexity_cols) > len(KEY_COLS):
        result["checkpoints_complexity"] = df[complexity_cols].copy()

    # Mass columns (prefix matching)
    mass_cols = [c for c in KEY_COLS if c in all_cols]
    for col in all_cols:
        if col.startswith(MASS_PREFIX):
            mass_cols.append(col)
    if len(mass_cols) > len(KEY_COLS):
        result["checkpoints_mass"] = df[mass_cols].copy()

    # Delta columns (prefix matching)
    delta_cols = [c for c in KEY_COLS if c in all_cols]
    for col in all_cols:
        if any(col.startswith(prefix) for prefix in DELTA_PREFIXES):
            delta_cols.append(col)
    if len(delta_cols) > len(KEY_COLS):
        result["checkpoints_deltas"] = df[delta_cols].copy()

    return result


def expand_evaluation(
    eval_json: dict[str, Any],
    setup: str,
    run_id: str,
    problem: str,
    checkpoint: str,
) -> list[dict[str, Any]]:
    """Expand evaluation.json tests into flat rows."""
    rows: list[dict[str, Any]] = []
    for group_key, results in eval_json.get("tests", {}).items():
        # Extract group name from key like "checkpoint_1-Core"
        parts = group_key.split("-")
        group = parts[-1] if len(parts) > 1 else group_key

        for test_id in results.get("passed", []):
            rows.append(
                {
                    "setup": setup,
                    "run_id": run_id,
                    "problem": problem,
                    "checkpoint": checkpoint,
                    "group": group,
                    "test_id": test_id,
                    "passed": True,
                }
            )
        for test_id in results.get("failed", []):
            rows.append(
                {
                    "setup": setup,
                    "run_id": run_id,
                    "problem": problem,
                    "checkpoint": checkpoint,
                    "group": group,
                    "test_id": test_id,
                    "passed": False,
                }
            )
    return rows


def generate_manifest(
    output_dir: Path, runs_dir: Path, stats: dict[str, int]
) -> None:
    """Generate manifest.json with consolidation metadata."""
    manifest = {
        "version": "1.0",
        "created": datetime.now().isoformat(),
        "source_dir": str(runs_dir),
        "stats": stats,
        "key_columns": KEY_COLS,
        "files": {
            "runs.csv": {
                "description": "One row per run with aggregated metrics from result.json",
                "key_columns": ["setup", "run_id"],
            },
            "checkpoints_identity.csv": {
                "description": "Checkpoint identification and metadata",
                "key_columns": KEY_COLS,
            },
            "checkpoints_tests.csv": {
                "description": "Test pass rates and counts by group",
                "key_columns": KEY_COLS,
            },
            "checkpoints_inference.csv": {
                "description": "Cost, token usage, and inference metrics",
                "key_columns": KEY_COLS,
            },
            "checkpoints_code_stats.csv": {
                "description": "Lines of code, symbol counts, file counts",
                "key_columns": KEY_COLS,
            },
            "checkpoints_complexity.csv": {
                "description": "Cyclomatic complexity, nesting, linting metrics",
                "key_columns": KEY_COLS,
            },
            "checkpoints_mass.csv": {
                "description": "Mass complexity metrics (weighted complexity distribution)",
                "key_columns": KEY_COLS,
            },
            "checkpoints_deltas.csv": {
                "description": "Delta metrics between consecutive checkpoints",
                "key_columns": KEY_COLS,
            },
            "quality_files.csv": {
                "description": "Per-file quality metrics from files.jsonl",
                "key_columns": KEY_COLS + ["file_path"],
            },
            "quality_symbols.csv.gz": {
                "description": "Per-symbol metrics from symbols.jsonl (gzip compressed)",
                "key_columns": KEY_COLS + ["name", "type", "file_path"],
                "compressed": True,
            },
            "quality_ast_violations.csv.gz": {
                "description": "AST-grep rule violations (gzip compressed)",
                "key_columns": KEY_COLS + ["rule_id", "file_path"],
                "compressed": True,
            },
            "evaluations.csv.gz": {
                "description": "Individual test results (gzip compressed)",
                "key_columns": KEY_COLS + ["group", "test_id"],
                "compressed": True,
            },
            "rubric.csv": {
                "description": "LLM judge rubric grades if available",
                "key_columns": KEY_COLS,
            },
        },
        "usage": {
            "joining": "All checkpoint files share key columns: setup, run_id, problem, checkpoint",
            "grouping": "Use 'setup' column to group by configuration (excludes timestamp)",
            "reading_compressed": "pandas.read_csv('file.csv.gz') auto-detects gzip",
        },
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
