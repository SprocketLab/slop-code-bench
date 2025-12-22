#!/usr/bin/env python3
"""Analyze code mass changes between checkpoints.

Mass formula: mass = max(0, metric - baseline) * max(1, size)^alpha
- baseline = 1 for complexity, 0 for all other metrics
- alpha = 0.5 (default)
"""

import json
import sys
from pathlib import Path
from typing import Annotated

import numpy as np
import pandas as pd
import typer
import yaml
from rich.console import Console
from rich.table import Table

app = typer.Typer()
console = Console()
err_console = Console(stderr=True)


def get_run_name(run_dir: Path) -> str:
    """Extract a readable run name from config.yaml."""
    config_path = run_dir / "config.yaml"
    if config_path.exists():
        try:
            with open(config_path) as f:
                config = yaml.safe_load(f)

            model = config.get("model", {}).get("name", "?")
            prompt = Path(config.get("prompt_path", "?")).stem
            thinking = config.get("thinking", "none")

            return f"{model} / {prompt} / {thinking}"
        except Exception:
            pass
    return run_dir.name

METRICS = [
    "complexity",
    "branches",
    "comparisons",
    "variables_used",
    "variables_defined",
    "exception_scaffold",
]
SIZE_METRICS = ["statements", "lines"]
BASELINES = {"complexity": 1}  # All others default to 0


def symbol_key(row: pd.Series) -> str:
    """Generate primary key for symbol matching."""
    parent = row.get("parent_class") or ""
    file_path = row["file_path"]
    name = row["name"]
    if parent:
        return f"{file_path}:{parent}.{name}"
    return f"{file_path}:{name}"


def calc_mass(
    metric: np.ndarray, size: np.ndarray, baseline: float, alpha: float
) -> np.ndarray:
    """Vectorized mass calculation."""
    return np.maximum(0, metric - baseline) * np.power(np.maximum(1, size), alpha)


def load_symbols(jsonl_path: Path) -> pd.DataFrame:
    """Load symbols from JSONL file."""
    df = pd.read_json(jsonl_path, lines=True)
    # Filter to functions and methods only
    df = df[df["type"].isin(["function", "method"])].copy()
    return df


def discover_checkpoints(run_dir: Path) -> dict[str, dict[int, Path]]:
    """Discover all problems and their checkpoint symbols.jsonl files.

    Returns: {problem_name: {checkpoint_num: symbols_path}}
    """
    problems = {}
    for symbols_file in run_dir.glob("*/checkpoint_*/quality_analysis/symbols.jsonl"):
        parts = symbols_file.parts
        # Find checkpoint_N in path
        for i, part in enumerate(parts):
            if part.startswith("checkpoint_"):
                checkpoint_num = int(part.split("_")[1])
                problem_name = parts[i - 1]
                if problem_name not in problems:
                    problems[problem_name] = {}
                problems[problem_name][checkpoint_num] = symbols_file
                break
    return problems


def match_symbols(
    df_before: pd.DataFrame, df_after: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Match symbols between two checkpoints.

    Returns: (matched_df, added_df, removed_df)
    - matched_df has columns from both with _before and _after suffixes
    - added_df: symbols only in after
    - removed_df: symbols only in before
    """
    # Generate primary keys
    df_before = df_before.copy()
    df_after = df_after.copy()
    df_before["_key"] = df_before.apply(symbol_key, axis=1)
    df_after["_key"] = df_after.apply(symbol_key, axis=1)

    # Primary key matching
    keys_before = set(df_before["_key"])
    keys_after = set(df_after["_key"])

    matched_keys = keys_before & keys_after
    only_before = keys_before - keys_after
    only_after = keys_after - keys_before

    # Try fallback matching for unmatched symbols
    unmatched_before = df_before[df_before["_key"].isin(only_before)].copy()
    unmatched_after = df_after[df_after["_key"].isin(only_after)].copy()

    additional_matches = []

    for hash_col in ["signature_hash", "body_hash", "structure_hash"]:
        if len(unmatched_before) == 0 or len(unmatched_after) == 0:
            break

        # Build hash lookup for remaining unmatched
        before_hashes = (
            unmatched_before[unmatched_before[hash_col].notna()]
            .set_index(hash_col)["_key"]
            .to_dict()
        )

        for idx, row in unmatched_after[unmatched_after[hash_col].notna()].iterrows():
            h = row[hash_col]
            if h in before_hashes:
                before_key = before_hashes[h]
                after_key = row["_key"]
                additional_matches.append((before_key, after_key))
                # Remove from unmatched
                unmatched_before = unmatched_before[
                    unmatched_before["_key"] != before_key
                ]
                unmatched_after = unmatched_after[unmatched_after["_key"] != after_key]
                del before_hashes[h]

    # Build matched dataframe
    matched_before = df_before[df_before["_key"].isin(matched_keys)]
    matched_after = df_after[df_after["_key"].isin(matched_keys)]

    matched = matched_before.merge(
        matched_after, on="_key", suffixes=("_before", "_after")
    )

    # Add fallback matches
    for before_key, after_key in additional_matches:
        before_row = df_before[df_before["_key"] == before_key].iloc[0]
        after_row = df_after[df_after["_key"] == after_key].iloc[0]

        row_dict = {"_key": before_key}
        for col in before_row.index:
            if col != "_key":
                row_dict[f"{col}_before"] = before_row[col]
        for col in after_row.index:
            if col != "_key":
                row_dict[f"{col}_after"] = after_row[col]

        matched = pd.concat([matched, pd.DataFrame([row_dict])], ignore_index=True)

    # Unmatched symbols
    final_only_before = set(unmatched_before["_key"])
    final_only_after = set(unmatched_after["_key"])

    added = df_after[df_after["_key"].isin(final_only_after)]
    removed = df_before[df_before["_key"].isin(final_only_before)]

    return matched, added, removed


def compute_distribution(masses: np.ndarray) -> dict:
    """Compute how many symbols account for top 50%, 75%, 90% of mass."""
    if len(masses) == 0 or masses.sum() == 0:
        return {
            "top_50_pct_symbol_count": 0,
            "top_75_pct_symbol_count": 0,
            "top_90_pct_symbol_count": 0,
            "total_symbol_count": len(masses),
        }

    sorted_masses = np.sort(masses)[::-1]
    cumsum = np.cumsum(sorted_masses)
    total = masses.sum()

    result = {"total_symbol_count": len(masses)}
    for pct, name in [(0.50, "top_50_pct"), (0.75, "top_75_pct"), (0.90, "top_90_pct")]:
        threshold = total * pct
        count = int(np.searchsorted(cumsum, threshold, side="right")) + 1
        result[f"{name}_symbol_count"] = min(count, len(masses))

    return result


def compute_high_complexity(df: pd.DataFrame, mass_col: str) -> dict:
    """Compute mass in functions with complexity > 10."""
    total_mass = df[mass_col].sum() if len(df) > 0 else 0
    high_cx = df[df["complexity"] > 10] if "complexity" in df.columns else df.iloc[:0]
    mass_high = high_cx[mass_col].sum() if len(high_cx) > 0 else 0

    return {
        "mass_in_complexity_gt_10": float(mass_high),
        "total_mass": float(total_mass),
        "pct_in_high_complexity": float(mass_high / total_mass * 100)
        if total_mass > 0
        else 0.0,
        "symbol_count_gt_10": len(high_cx),
    }


def analyze_transition(
    df_before: pd.DataFrame, df_after: pd.DataFrame, alpha: float
) -> dict:
    """Analyze a single checkpoint transition."""
    matched, added, removed = match_symbols(df_before, df_after)

    result = {"metrics": {}}

    # Compute mass for each metric/size combination
    for metric in METRICS:
        baseline = BASELINES.get(metric, 0)
        result["metrics"][metric] = {}

        for size_metric in SIZE_METRICS:
            size_key = f"by_{size_metric}"

            # Mass before (from matched + removed)
            mass_matched_before = (
                calc_mass(
                    matched[f"{metric}_before"].fillna(0).values,
                    matched[f"{size_metric}_before"].fillna(0).values,
                    baseline,
                    alpha,
                )
                if len(matched) > 0
                else np.array([])
            )
            mass_removed = (
                calc_mass(
                    removed[metric].fillna(0).values,
                    removed[size_metric].fillna(0).values,
                    baseline,
                    alpha,
                )
                if len(removed) > 0
                else np.array([])
            )

            # Mass after (from matched + added)
            mass_matched_after = (
                calc_mass(
                    matched[f"{metric}_after"].fillna(0).values,
                    matched[f"{size_metric}_after"].fillna(0).values,
                    baseline,
                    alpha,
                )
                if len(matched) > 0
                else np.array([])
            )
            mass_added = (
                calc_mass(
                    added[metric].fillna(0).values,
                    added[size_metric].fillna(0).values,
                    baseline,
                    alpha,
                )
                if len(added) > 0
                else np.array([])
            )

            total_before = float(mass_matched_before.sum() + mass_removed.sum())
            total_after = float(mass_matched_after.sum() + mass_added.sum())

            # Count modified (mass changed)
            modified_count = 0
            if len(matched) > 0:
                modified_count = int(
                    (np.abs(mass_matched_after - mass_matched_before) > 1e-9).sum()
                )

            result["metrics"][metric][size_key] = {
                "total_mass_before": total_before,
                "total_mass_after": total_after,
                "delta": total_after - total_before,
                "symbols_added": len(added),
                "symbols_removed": len(removed),
                "symbols_modified": modified_count,
            }

    # Distribution analysis (using complexity mass by statements as representative)
    baseline = BASELINES.get("complexity", 0)
    all_after_mass = np.concatenate(
        [
            calc_mass(
                matched["complexity_after"].fillna(0).values
                if len(matched) > 0
                else np.array([]),
                matched["statements_after"].fillna(0).values
                if len(matched) > 0
                else np.array([]),
                baseline,
                alpha,
            ),
            calc_mass(
                added["complexity"].fillna(0).values if len(added) > 0 else np.array([]),
                added["statements"].fillna(0).values if len(added) > 0 else np.array([]),
                baseline,
                alpha,
            ),
        ]
    )
    result["distribution"] = compute_distribution(all_after_mass)

    # High complexity analysis
    # Build df_after with mass column for high complexity analysis
    df_after_with_mass = df_after.copy()
    df_after_with_mass["_mass"] = calc_mass(
        df_after_with_mass["complexity"].fillna(0).values,
        df_after_with_mass["statements"].fillna(0).values,
        baseline,
        alpha,
    )
    result["high_complexity"] = compute_high_complexity(df_after_with_mass, "_mass")

    return result


def analyze_problem(checkpoints: dict[int, Path], alpha: float) -> dict:
    """Analyze all transitions for a problem."""
    # Load all checkpoint data
    checkpoint_data = {}
    for num, path in sorted(checkpoints.items()):
        try:
            checkpoint_data[num] = load_symbols(path)
        except Exception as e:
            typer.echo(f"Warning: Failed to load {path}: {e}", err=True)
            continue

    if len(checkpoint_data) < 2:
        return {"transitions": {}}

    result = {"transitions": {}}
    sorted_nums = sorted(checkpoint_data.keys())

    for i in range(len(sorted_nums) - 1):
        before_num = sorted_nums[i]
        after_num = sorted_nums[i + 1]

        df_before = checkpoint_data[before_num]
        df_after = checkpoint_data[after_num]

        transition_key = f"{before_num}->{after_num}"
        result["transitions"][transition_key] = analyze_transition(
            df_before, df_after, alpha
        )

    return result


def aggregate_transitions(problems: dict) -> dict:
    """Compute mean statistics across all transitions in all problems."""
    # Collect all transition data
    all_metrics_data = {metric: {f"by_{size}": [] for size in SIZE_METRICS} for metric in METRICS}
    all_distribution = []
    all_high_complexity = []

    for problem_name, problem_data in problems.items():
        for trans_key, trans_data in problem_data.get("transitions", {}).items():
            # Collect metric data
            for metric in METRICS:
                if metric in trans_data.get("metrics", {}):
                    for size_key in [f"by_{s}" for s in SIZE_METRICS]:
                        if size_key in trans_data["metrics"][metric]:
                            all_metrics_data[metric][size_key].append(
                                trans_data["metrics"][metric][size_key]
                            )

            # Collect distribution data
            if "distribution" in trans_data:
                all_distribution.append(trans_data["distribution"])

            # Collect high complexity data
            if "high_complexity" in trans_data:
                all_high_complexity.append(trans_data["high_complexity"])

    # Compute means
    result = {
        "transition_count": sum(
            len(p.get("transitions", {})) for p in problems.values()
        ),
        "problem_count": len(problems),
        "metrics": {},
        "distribution": {},
        "high_complexity": {},
    }

    # Aggregate metrics
    for metric in METRICS:
        result["metrics"][metric] = {}
        for size_key in [f"by_{s}" for s in SIZE_METRICS]:
            data_list = all_metrics_data[metric][size_key]
            if data_list:
                result["metrics"][metric][size_key] = {
                    "mean_mass_before": float(np.mean([d["total_mass_before"] for d in data_list])),
                    "mean_mass_after": float(np.mean([d["total_mass_after"] for d in data_list])),
                    "mean_delta": float(np.mean([d["delta"] for d in data_list])),
                    "std_delta": float(np.std([d["delta"] for d in data_list])),
                    "total_delta": float(sum(d["delta"] for d in data_list)),
                    "mean_symbols_added": float(np.mean([d["symbols_added"] for d in data_list])),
                    "mean_symbols_removed": float(np.mean([d["symbols_removed"] for d in data_list])),
                    "mean_symbols_modified": float(np.mean([d["symbols_modified"] for d in data_list])),
                }

    # Aggregate distribution
    if all_distribution:
        result["distribution"] = {
            "mean_top_50_pct_symbol_count": float(np.mean([d["top_50_pct_symbol_count"] for d in all_distribution])),
            "mean_top_75_pct_symbol_count": float(np.mean([d["top_75_pct_symbol_count"] for d in all_distribution])),
            "mean_top_90_pct_symbol_count": float(np.mean([d["top_90_pct_symbol_count"] for d in all_distribution])),
            "mean_total_symbol_count": float(np.mean([d["total_symbol_count"] for d in all_distribution])),
        }

    # Aggregate high complexity
    if all_high_complexity:
        result["high_complexity"] = {
            "mean_mass_in_complexity_gt_10": float(np.mean([d["mass_in_complexity_gt_10"] for d in all_high_complexity])),
            "mean_total_mass": float(np.mean([d["total_mass"] for d in all_high_complexity])),
            "mean_pct_in_high_complexity": float(np.mean([d["pct_in_high_complexity"] for d in all_high_complexity])),
            "mean_symbol_count_gt_10": float(np.mean([d["symbol_count_gt_10"] for d in all_high_complexity])),
        }

    return result


def compare_runs(runs_data: dict[str, dict]) -> dict:
    """Compare aggregated statistics across multiple runs."""
    comparison = {"runs": {}}

    for run_name, run_data in runs_data.items():
        comparison["runs"][run_name] = aggregate_transitions(run_data["problems"])

    # If multiple runs, compute deltas between them
    run_names = list(runs_data.keys())
    if len(run_names) >= 2:
        comparison["pairwise_comparisons"] = {}
        for i, run_a in enumerate(run_names):
            for run_b in run_names[i + 1:]:
                agg_a = comparison["runs"][run_a]
                agg_b = comparison["runs"][run_b]

                pair_key = f"{run_a} vs {run_b}"
                comparison["pairwise_comparisons"][pair_key] = {
                    "metrics": {}
                }

                for metric in METRICS:
                    comparison["pairwise_comparisons"][pair_key]["metrics"][metric] = {}
                    for size_key in [f"by_{s}" for s in SIZE_METRICS]:
                        if (
                            metric in agg_a.get("metrics", {})
                            and size_key in agg_a["metrics"].get(metric, {})
                            and metric in agg_b.get("metrics", {})
                            and size_key in agg_b["metrics"].get(metric, {})
                        ):
                            delta_a = agg_a["metrics"][metric][size_key]["mean_delta"]
                            delta_b = agg_b["metrics"][metric][size_key]["mean_delta"]
                            comparison["pairwise_comparisons"][pair_key]["metrics"][metric][size_key] = {
                                f"{run_a}_mean_delta": delta_a,
                                f"{run_b}_mean_delta": delta_b,
                                "difference": delta_b - delta_a,
                            }

                # Compare high complexity
                if agg_a.get("high_complexity") and agg_b.get("high_complexity"):
                    comparison["pairwise_comparisons"][pair_key]["high_complexity"] = {
                        f"{run_a}_mean_pct": agg_a["high_complexity"]["mean_pct_in_high_complexity"],
                        f"{run_b}_mean_pct": agg_b["high_complexity"]["mean_pct_in_high_complexity"],
                        "difference": (
                            agg_b["high_complexity"]["mean_pct_in_high_complexity"]
                            - agg_a["high_complexity"]["mean_pct_in_high_complexity"]
                        ),
                    }

    return comparison


def flatten_transition(
    run: str, problem: str, transition: str, data: dict
) -> dict:
    """Flatten a transition's nested data into a single row."""
    row = {
        "run": run,
        "problem": problem,
        "transition": transition,
    }

    # Flatten metrics
    for metric, metric_data in data.get("metrics", {}).items():
        for size_key, size_data in metric_data.items():
            prefix = f"{metric}_{size_key}"
            for key, value in size_data.items():
                row[f"{prefix}_{key}"] = value

    # Flatten distribution
    for key, value in data.get("distribution", {}).items():
        row[f"dist_{key}"] = value

    # Flatten high complexity
    for key, value in data.get("high_complexity", {}).items():
        row[f"high_cx_{key}"] = value

    return row


def flatten_aggregate(run: str, data: dict) -> dict:
    """Flatten aggregated run data into a single row."""
    row = {
        "run": run,
        "transition_count": data.get("transition_count", 0),
        "problem_count": data.get("problem_count", 0),
    }

    # Flatten metrics
    for metric, metric_data in data.get("metrics", {}).items():
        for size_key, size_data in metric_data.items():
            prefix = f"{metric}_{size_key}"
            for key, value in size_data.items():
                row[f"{prefix}_{key}"] = value

    # Flatten distribution
    for key, value in data.get("distribution", {}).items():
        row[f"dist_{key}"] = value

    # Flatten high complexity
    for key, value in data.get("high_complexity", {}).items():
        row[f"high_cx_{key}"] = value

    return row


def render_comparison_table(rows: list[dict], size_metric: str = "statements") -> Table:
    """Render comparison table with metrics as rows, runs as columns."""
    table = Table(title=f"Mass Delta Comparison (size={size_metric})", expand=True)

    # First column is metric name
    table.add_column("Metric", style="white")

    # Add a column for each run
    for row in rows:
        table.add_column(row["run"], justify="right", style="cyan")

    # Add delta column if exactly 2 runs
    if len(rows) == 2:
        table.add_column("Δ", justify="right", style="yellow")

    # Compute concentration ratios for each row
    for row in rows:
        total = row.get("dist_mean_total_symbol_count", 1)
        if total > 0:
            row["_top50_pct"] = 100 * row.get("dist_mean_top_50_pct_symbol_count", 0) / total
            row["_top75_pct"] = 100 * row.get("dist_mean_top_75_pct_symbol_count", 0) / total
            row["_top90_pct"] = 100 * row.get("dist_mean_top_90_pct_symbol_count", 0) / total

    s = f"by_{size_metric}"

    # Define metrics to show
    metrics = [
        ("Transitions", "transition_count", "{:.0f}"),
        ("μ Δ Complexity", f"complexity_{s}_mean_delta", "{:.1f}"),
        ("σ Δ Complexity", f"complexity_{s}_std_delta", "{:.1f}"),
        ("μ Δ Branches", f"branches_{s}_mean_delta", "{:.1f}"),
        ("μ Δ Comparisons", f"comparisons_{s}_mean_delta", "{:.1f}"),
        ("μ Δ Vars Used", f"variables_used_{s}_mean_delta", "{:.1f}"),
        ("μ Δ Vars Defined", f"variables_defined_{s}_mean_delta", "{:.1f}"),
        ("μ Δ Exc Scaffold", f"exception_scaffold_{s}_mean_delta", "{:.1f}"),
        ("μ Symbols Added", f"complexity_{s}_mean_symbols_added", "{:.1f}"),
        ("μ Func/Method Count", "dist_mean_total_symbol_count", "{:.1f}"),
        ("50% mass in N% funcs", "_top50_pct", "{:.1f}%"),
        ("75% mass in N% funcs", "_top75_pct", "{:.1f}%"),
        ("90% mass in N% funcs", "_top90_pct", "{:.1f}%"),
        ("μ % in High Cx", "high_cx_mean_pct_in_high_complexity", "{:.1f}%"),
        ("μ High Cx Count", "high_cx_mean_symbol_count_gt_10", "{:.1f}"),
    ]

    for label, key, fmt in metrics:
        values = [row.get(key, 0) for row in rows]
        row_data = [label]

        for v in values:
            if "%" in fmt:
                row_data.append(fmt.format(v))
            else:
                row_data.append(fmt.format(v))

        # Add delta for 2-run comparison
        if len(rows) == 2:
            delta = values[1] - values[0]
            sign = "+" if delta > 0 else ""
            if "%" in fmt:
                row_data.append(f"{sign}{delta:.1f}%")
            else:
                row_data.append(f"{sign}{delta:.1f}")

        table.add_row(*row_data)

    return table


@app.command()
def main(
    run_dirs: Annotated[
        list[Path], typer.Argument(help="Run directories to analyze")
    ],
    alpha: Annotated[
        float, typer.Option(help="Size exponent for mass formula")
    ] = 0.5,
    size: Annotated[
        str, typer.Option(help="Size metric: statements or lines")
    ] = "statements",
    output: Annotated[
        Path | None, typer.Option(help="Output JSON file (shows table if not specified)")
    ] = None,
):
    """Analyze and compare code mass changes between checkpoints across runs."""
    runs_data: dict[str, dict] = {}

    for run_dir in run_dirs:
        if not run_dir.exists():
            err_console.print(f"[yellow]Warning: {run_dir} does not exist[/yellow]")
            continue

        run_name = get_run_name(run_dir)
        problems = discover_checkpoints(run_dir)

        if not problems:
            err_console.print(f"[yellow]Warning: No problems found in {run_dir}[/yellow]")
            continue

        runs_data[run_name] = {"problems": {}}

        for problem in sorted(problems.keys()):
            err_console.print(f"[dim]Analyzing {run_name}/{problem}...[/dim]")
            problem_result = analyze_problem(problems[problem], alpha)
            runs_data[run_name]["problems"][problem] = problem_result

    if not runs_data:
        err_console.print("[red]No runs found in the specified directories[/red]")
        raise typer.Exit(1)

    # Aggregate per run
    summary_rows = []
    for run_name, run_data in runs_data.items():
        agg = aggregate_transitions(run_data["problems"])
        summary_rows.append(flatten_aggregate(run_name, agg))

    # Output
    if output:
        output.write_text(json.dumps(summary_rows, indent=2))
        err_console.print(f"[green]Results written to {output}[/green]")
    else:
        console.print(render_comparison_table(summary_rows, size))


if __name__ == "__main__":
    app()
