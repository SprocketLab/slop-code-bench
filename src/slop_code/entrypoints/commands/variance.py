from __future__ import annotations

import json
import math
import statistics
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import typer
import yaml
from rich import box
from rich.console import Console
from rich.table import Table

from slop_code.common import CHECKPOINT_RESULTS_FILENAME
from slop_code.common import CONFIG_FILENAME
from slop_code.entrypoints.utils import ensure_dir_exists
from slop_code.metrics import load_checkpoint_data


class VariancePreset(str, Enum):
    BASE = "base"
    TESTS = "tests"
    QUALITY = "quality"


_T_CRIT_95: dict[int, float] = {
    1: 12.706,
    2: 4.303,
    3: 3.182,
    4: 2.776,
    5: 2.571,
    6: 2.447,
    7: 2.365,
    8: 2.306,
    9: 2.262,
    10: 2.228,
    11: 2.201,
    12: 2.179,
    13: 2.16,
    14: 2.145,
    15: 2.131,
    16: 2.12,
    17: 2.11,
    18: 2.101,
    19: 2.093,
    20: 2.086,
    21: 2.08,
    22: 2.074,
    23: 2.069,
    24: 2.064,
    25: 2.06,
    26: 2.056,
    27: 2.052,
    28: 2.048,
    29: 2.045,
    30: 2.042,
}


CV_SUMMARY_METRICS: dict[str, str] = {
    "Pass rate": "pass_rate.cv",
    "Lint": "lint_per_loc.cv",
    "Slop": "ast_grep_per_loc.cv",
    "Lint+Slop": "normalized.lint_slop_per_loc.cv",
    "LOC": "lines.loc.cv",
    "High CC count": "cc.high_count.cv",
}

CORE_METRIC_BASES: set[str] = {
    metric.removesuffix(".cv") for metric in CV_SUMMARY_METRICS.values()
}
CORE_METRIC_LABELS: dict[str, str] = {
    metric.removesuffix(".cv"): label
    for label, metric in CV_SUMMARY_METRICS.items()
}
CORE_CI_DERIVATIONS: set[str] = {
    "first",
    "final",
    "mean_across_checkpoints",
}

DELTA_CI_METRICS: dict[str, str] = {
    "delta.loc": "LOC delta",
    "delta.ast_grep_violations": "Slop delta",
    "delta.lint_errors": "Lint delta",
    "delta.new_violations_per_loc": "Lint+Slop delta",
}
CI_METRIC_LABELS: dict[str, str] = {
    **CORE_METRIC_LABELS,
    **DELTA_CI_METRICS,
    "cc.high_count": "High CC count",
}
CI_METRIC_BASES: set[str] = set(DELTA_CI_METRICS.keys()) | {"cc.high_count"}
PROBLEM_CI_METRICS: set[str] = {"cc.high_count"}
CHECKPOINT_DELTA_METRICS: set[str] = set(DELTA_CI_METRICS.keys())


def _t_crit_95(df: int) -> float:
    if df <= 0:
        return float("nan")
    return _T_CRIT_95.get(df, 1.96)


def _is_number(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if not isinstance(value, (int, float)):
        return False
    return math.isfinite(float(value))


def _stats(values: list[float]) -> dict[str, float | int | None]:
    n = len(values)
    if n < 2:
        return {}
    mean = statistics.mean(values)
    stddev = statistics.stdev(values)
    se = stddev / math.sqrt(n)
    margin = _t_crit_95(n - 1) * se
    return {
        "n": n,
        "mean": mean,
        "stddev": stddev,
        "cv": (stddev / abs(mean)) if mean != 0 else None,
        "ci95_low": mean - margin,
        "ci95_high": mean + margin,
    }


@dataclass(frozen=True)
class RunGroupKey:
    model: str
    prompt_path: str
    thinking: str
    agent_type: str
    agent_version: str

    def as_dict(self) -> dict[str, str]:
        return {
            "model": self.model,
            "prompt_path": self.prompt_path,
            "thinking": self.thinking,
            "agent_type": self.agent_type,
            "agent_version": self.agent_version,
        }


@dataclass
class RunData:
    run_dir: Path
    group_key: RunGroupKey
    rows_by_problem_checkpoint: dict[tuple[str, str], dict[str, Any]]
    checkpoints_by_problem: dict[str, set[str]]

    @property
    def problems_attempted(self) -> set[str]:
        return set(self.checkpoints_by_problem.keys())


@dataclass
class RunGroup:
    key: RunGroupKey
    runs: list[RunData]

    @property
    def run_count(self) -> int:
        return len(self.runs)

    @property
    def common_problems(self) -> set[str]:
        if not self.runs:
            return set()
        return set.intersection(*(run.problems_attempted for run in self.runs))

    def common_checkpoints(self, problem: str) -> set[str]:
        if not self.runs:
            return set()
        checkpoints = [
            run.checkpoints_by_problem.get(problem, set()) for run in self.runs
        ]
        if not checkpoints:
            return set()
        return set.intersection(*checkpoints)


@dataclass(frozen=True)
class MetricSpec:
    name: str
    requires_rubric: bool = False


@dataclass
class ConfidenceIntervalEntry:
    problem: str
    metric: str
    mean: float | None
    ci95_low: float
    ci95_high: float
    width: float
    runs: int
    group: RunGroupKey


def _get_nested_str(data: Any, *path: str, default: str = "unknown") -> str:
    cur: Any = data
    for part in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(part)
    if cur is None:
        return default
    if isinstance(cur, str):
        return cur or default
    return str(cur)


def _load_group_key(run_dir: Path) -> RunGroupKey:
    cfg_path = run_dir / CONFIG_FILENAME
    cfg: dict[str, Any] = {}
    if cfg_path.exists():
        try:
            cfg = yaml.safe_load(cfg_path.read_text()) or {}
        except (OSError, yaml.YAMLError):
            cfg = {}

    return RunGroupKey(
        model=_get_nested_str(cfg, "model", "name"),
        prompt_path=_get_nested_str(cfg, "prompt_path"),
        thinking=_get_nested_str(cfg, "thinking"),
        agent_type=_get_nested_str(cfg, "agent", "type"),
        agent_version=_get_nested_str(cfg, "agent", "version"),
    )


def _discover_run_dirs(runs_dir: Path) -> list[Path]:
    if (runs_dir / CHECKPOINT_RESULTS_FILENAME).exists():
        return [runs_dir]

    run_dirs: set[Path] = set()
    for results_file in runs_dir.rglob(CHECKPOINT_RESULTS_FILENAME):
        run_dirs.add(results_file.parent)
    return sorted(run_dirs)


def _load_run(run_dir: Path) -> RunData | None:
    results_path = run_dir / CHECKPOINT_RESULTS_FILENAME
    if not results_path.exists():
        return None

    checkpoint_rows = load_checkpoint_data(results_path)
    rows_by_problem_checkpoint: dict[tuple[str, str], dict[str, Any]] = {}
    checkpoints_by_problem: dict[str, set[str]] = defaultdict(set)

    for row in checkpoint_rows:
        problem = row.get("problem")
        checkpoint = row.get("checkpoint")
        if not isinstance(problem, str) or not isinstance(checkpoint, str):
            continue
        key = (problem, checkpoint)
        rows_by_problem_checkpoint[key] = row
        checkpoints_by_problem[problem].add(checkpoint)

    if not rows_by_problem_checkpoint:
        return None

    return RunData(
        run_dir=run_dir,
        group_key=_load_group_key(run_dir),
        rows_by_problem_checkpoint=rows_by_problem_checkpoint,
        checkpoints_by_problem=dict(checkpoints_by_problem),
    )


def _group_runs(runs: list[RunData]) -> list[RunGroup]:
    grouped: dict[RunGroupKey, list[RunData]] = defaultdict(list)
    for run in runs:
        grouped[run.group_key].append(run)

    return [
        RunGroup(key=key, runs=group_runs)
        for key, group_runs in grouped.items()
        if len(group_runs) >= 2
    ]


def _metric_value(row: dict[str, Any], name: str) -> float | None:
    if name == "rubric.flags_per_loc":
        flags = row.get("rubric_total_flags")
        loc = row.get("loc")
        if not _is_number(flags) or not _is_number(loc):
            return None
        if float(loc) <= 0:
            return None
        return float(flags) / float(loc)

    if name == "normalized.lint_slop_per_loc":
        lint = row.get("lint_per_loc")
        slop = row.get("ast_grep_per_loc")
        if not _is_number(lint) or not _is_number(slop):
            return None
        return float(lint) + float(slop)

    if name.startswith("tests.") and name.endswith(".pass_rate"):
        bucket = name.split(".")[1]
        if bucket == "total":
            passed = row.get("passed_tests")
            total = row.get("total_tests")
        else:
            passed = row.get(f"tests.{bucket}.passed")
            total = row.get(f"tests.{bucket}.total")
        if not _is_number(passed) or not _is_number(total):
            return None
        if float(total) <= 0:
            return None
        return float(passed) / float(total)

    value = row.get(name)
    if not _is_number(value):
        return None
    return float(value)


def _derived_metric_value(
    derived_name: str, rows: list[dict[str, Any]]
) -> float | None:
    if not rows:
        return None

    if derived_name.startswith("total."):
        key = derived_name.removeprefix("total.")
        values = [row.get(key) for row in rows]
        if any(not _is_number(v) for v in values):
            return None
        return float(sum(float(v) for v in values))

    if derived_name.endswith(".mean_across_checkpoints"):
        metric = derived_name.removesuffix(".mean_across_checkpoints")
        metric_values = []
        for row in rows:
            value = _metric_value(row, metric)
            if value is None:
                metric_values = []
                break
            metric_values.append(value)
        if not metric_values:
            return None
        return float(statistics.mean(metric_values))

    if derived_name.endswith(".final"):
        metric = derived_name.removesuffix(".final")
        final_row = max(rows, key=lambda r: r.get("idx", 0))
        return _metric_value(final_row, metric)

    if derived_name.startswith("first."):
        metric = derived_name.removeprefix("first.")
        first_row = min(rows, key=lambda r: r.get("idx", 0))
        return _metric_value(first_row, metric)

    if derived_name.startswith("final."):
        metric = derived_name.removeprefix("final.")
        final_row = max(rows, key=lambda r: r.get("idx", 0))
        return _metric_value(final_row, metric)

    return None


def _checkpoint_bounds(
    rows: list[dict[str, Any]],
) -> tuple[str | None, str | None]:
    if not rows:
        return None, None
    first_row = min(rows, key=lambda r: r.get("idx", 0))
    final_row = max(rows, key=lambda r: r.get("idx", 0))
    first = first_row.get("checkpoint")
    final = final_row.get("checkpoint")
    return (
        first if isinstance(first, str) else None,
        final if isinstance(final, str) else None,
    )


def _build_metric_specs(
    preset: VariancePreset, available_numeric_keys: set[str]
) -> list[MetricSpec]:
    if preset == VariancePreset.BASE:
        base_keys = [
            "pass_rate",
            "core_pass_rate",
            "checkpoint_pass_rate",
            "cost",
            "elapsed",
            "duration",
            "steps",
            "lint_per_loc",
            "ast_grep_per_loc",
            "loc",
            "lines.churn",
            "lines.added",
            "lines.removed",
            "cc_mean",
            "cc_max",
            "cc.high_count",
            "delta.cc_mean",
            "delta.cc_max",
            "delta.loc",
            "delta.lint_errors",
            "delta.ast_grep_violations",
            "delta.churn_ratio",
            "delta.new_violations_per_loc",
            "lint_errors",
            "ast_grep_violations",
            "rubric_total_flags",
        ]
        specs = [MetricSpec(name=k) for k in base_keys]
        specs.append(
            MetricSpec(name="rubric.flags_per_loc", requires_rubric=True)
        )
    elif preset == VariancePreset.TESTS:
        test_keys = sorted(
            k for k in available_numeric_keys if k.startswith("tests.")
        )
        specs = [
            MetricSpec(name="pass_rate"),
            MetricSpec(name="core_pass_rate"),
            MetricSpec(name="checkpoint_pass_rate"),
        ]
        specs.extend(MetricSpec(name=k) for k in test_keys)
        for bucket in ["total", "core", "error", "functionality", "regression"]:
            specs.append(MetricSpec(name=f"tests.{bucket}.pass_rate"))
    else:
        prefixes = (
            "",
            "slop.",
            "rubric.",
            "cc.",
            "branches.",
            "control_blocks.",
            "nesting.",
            "symbol_lines.",
            "symbols.",
            "waste.",
            "redundancy.",
            "lines.",
            "imports.",
            "globals.",
            "normalized.",
            "delta.",
        )
        specs = [
            MetricSpec(name=k)
            for k in sorted(available_numeric_keys)
            if k.startswith(prefixes)
        ]
        specs.append(
            MetricSpec(name="rubric.flags_per_loc", requires_rubric=True)
        )

    existing = {spec.name for spec in specs}
    for metric in CORE_METRIC_BASES:
        if metric not in existing:
            specs.append(MetricSpec(name=metric))
    return specs


def _build_derived_metric_names(
    preset: VariancePreset, specs: list[MetricSpec]
) -> list[str]:
    additive_keys = [
        "cost",
        "elapsed",
        "duration",
        "steps",
        "input",
        "output",
        "cache_read",
        "cache_write",
        "reasoning",
    ]

    derived = [f"total.{k}" for k in additive_keys]
    for metric in ["pass_rate", "core_pass_rate", "checkpoint_pass_rate"]:
        derived.append(f"{metric}.mean_across_checkpoints")
        derived.append(f"{metric}.final")

    if preset == VariancePreset.TESTS:
        for bucket in ["total", "core", "error", "functionality", "regression"]:
            derived.append(f"tests.{bucket}.pass_rate.mean_across_checkpoints")
            derived.append(f"tests.{bucket}.pass_rate.final")

    for spec in specs:
        derived.append(f"first.{spec.name}")
        derived.append(f"final.{spec.name}")
        if spec.name in CORE_METRIC_BASES:
            derived.append(f"{spec.name}.mean_across_checkpoints")

    return list(dict.fromkeys(derived))


def _collect_metric_values(
    group: RunGroup,
    problem: str,
    checkpoints: Iterable[str],
    metric: str,
    only_checkpoint: str | None = None,
) -> list[float]:
    values: list[float] = []
    for checkpoint in checkpoints:
        if only_checkpoint and checkpoint != only_checkpoint:
            continue
        for run in group.runs:
            row = run.rows_by_problem_checkpoint.get((problem, checkpoint))
            if row is None:
                continue
            value = _metric_value(row, metric)
            if value is None:
                continue
            values.append(value)
    return values


def _compute_problem_cv_summary(
    groups: list[RunGroup],
) -> tuple[
    dict[str, dict[str, list[float]]],
    dict[str, dict[str, list[float]]],
    dict[str, dict[str, list[float]]],
]:
    overall: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: defaultdict(list)
    )
    first: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: defaultdict(list)
    )
    final: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: defaultdict(list)
    )

    for group in groups:
        for problem in group.common_problems:
            checkpoints = sorted(group.common_checkpoints(problem))
            if not checkpoints:
                continue

            first_row = group.runs[0].rows_by_problem_checkpoint.get(
                (problem, checkpoints[0])
            )
            ordered_rows = [
                group.runs[0].rows_by_problem_checkpoint[(problem, ck)]
                for ck in checkpoints
                if (problem, ck) in group.runs[0].rows_by_problem_checkpoint
            ]
            first_ck, final_ck = _checkpoint_bounds(ordered_rows)

            for label, metric_with_cv in CV_SUMMARY_METRICS.items():
                metric = metric_with_cv.removesuffix(".cv")
                stats = _stats(
                    _collect_metric_values(group, problem, checkpoints, metric)
                )
                if stats.get("cv") is not None:
                    overall[problem][label].append(float(stats["cv"]))

                if first_ck:
                    stats_first = _stats(
                        _collect_metric_values(
                            group,
                            problem,
                            checkpoints,
                            metric,
                            only_checkpoint=first_ck,
                        )
                    )
                    if stats_first.get("cv") is not None:
                        first[problem][label].append(float(stats_first["cv"]))

                if final_ck:
                    stats_final = _stats(
                        _collect_metric_values(
                            group,
                            problem,
                            checkpoints,
                            metric,
                            only_checkpoint=final_ck,
                        )
                    )
                    if stats_final.get("cv") is not None:
                        final[problem][label].append(float(stats_final["cv"]))

    return overall, first, final


def _normalize_ci_metric_name(metric: str) -> tuple[str, str | None]:
    if metric.startswith(("first.", "final.")):
        derivation, base = metric.split(".", 1)
        return base, derivation
    if metric.endswith(".mean_across_checkpoints"):
        return metric.removesuffix(
            ".mean_across_checkpoints"
        ), "mean_across_checkpoints"
    if metric.endswith(".final"):
        return metric.removesuffix(".final"), "final"
    return metric, None


def _format_ci_metric_key(base: str, derivation: str | None) -> str:
    if derivation in {"first", "final"}:
        return f"{derivation}.{base}"
    if derivation:
        return f"{base}.{derivation}"
    return base


def _format_ci_metric_label(base: str, derivation: str | None) -> str:
    base_label = CI_METRIC_LABELS.get(base, base)
    if derivation == "mean_across_checkpoints":
        return f"{base_label} (overall)"
    if derivation in {"first", "final"}:
        return f"{base_label} ({derivation})"
    return base_label


def _collect_ci_entries(
    record: dict[str, Any],
    group_key: RunGroupKey,
    min_width: float,
    allowed_metrics: set[str] | None = None,
) -> list[ConfidenceIntervalEntry]:
    entries: list[ConfidenceIntervalEntry] = []
    problem = (
        record["problem"]
        if isinstance(record.get("problem"), str)
        else "unknown"
    )
    run_count = (
        int(record["run_count"]) if _is_number(record.get("run_count")) else 0
    )
    allowed_bases = allowed_metrics or CI_METRIC_BASES
    allowed_derivations: set[str | None] = set(CORE_CI_DERIVATIONS)
    allowed_derivations.add(None)
    seen: set[tuple[str, str | None]] = set()

    for key, value in record.items():
        if not key.endswith(".ci95_low") or not _is_number(value):
            continue
        metric = key.removesuffix(".ci95_low")
        base_metric, derivation = _normalize_ci_metric_name(metric)
        if (
            base_metric not in allowed_bases
            or derivation not in allowed_derivations
        ):
            continue
        if (base_metric, derivation) in seen:
            continue

        ci_high = record.get(f"{metric}.ci95_high")
        if not _is_number(ci_high):
            continue
        width = float(ci_high) - float(value)
        if width < min_width:
            continue

        canonical_metric = _format_ci_metric_key(base_metric, derivation)
        mean = record.get(f"{metric}.mean") or record.get(
            f"{canonical_metric}.mean"
        )
        entries.append(
            ConfidenceIntervalEntry(
                problem=problem,
                metric=_format_ci_metric_label(base_metric, derivation),
                mean=float(mean) if _is_number(mean) else None,
                ci95_low=float(value),
                ci95_high=float(ci_high),
                width=width,
                runs=run_count,
                group=group_key,
            )
        )
        seen.add((base_metric, derivation))

    return entries


def _render_problem_cv_summary(
    console: Console,
    overall: dict[str, dict[str, list[float]]],
    first: dict[str, dict[str, list[float]]],
    final: dict[str, dict[str, list[float]]],
) -> None:
    if not overall:
        console.print("[yellow]No CV summary to display.[/yellow]")
        return

    def _table(title: str) -> Table:
        table = Table(
            box=box.SIMPLE_HEAVY, header_style="bold", show_lines=False
        )
        table.add_column("Problem", style="cyan", no_wrap=True)
        for label in CV_SUMMARY_METRICS:
            table.add_column(
                title.format(label=label), justify="right", style="yellow"
            )
        return table

    overall_table = _table("{label} overall CV")
    first_final_table = _table("{label} first CV")
    for label in CV_SUMMARY_METRICS:
        first_final_table.add_column(
            f"{label} final CV", justify="right", style="yellow"
        )

    for problem in sorted(overall):
        per_problem = overall[problem]
        per_first = first.get(problem, {})
        per_final = final.get(problem, {})

        overall_row = [problem]
        first_final_row = [problem]
        for label in CV_SUMMARY_METRICS:
            cv_values = per_problem.get(label, [])
            first_values = per_first.get(label, [])
            final_values = per_final.get(label, [])
            overall_row.append(
                f"{statistics.mean(cv_values):.2f}" if cv_values else "-"
            )
            first_final_row.append(
                f"{statistics.mean(first_values):.2f}" if first_values else "-"
            )
            first_final_row.append(
                f"{statistics.mean(final_values):.2f}" if final_values else "-"
            )

        overall_table.add_row(*overall_row)
        first_final_table.add_row(*first_final_row)

    console.print(
        "\n[bold]Average CV by problem (overall across checkpoints)[/bold]"
    )
    console.print(overall_table)
    console.print(
        "\n[bold]Average CV by problem (first vs final checkpoints)[/bold]"
    )
    console.print(first_final_table)


def _render_confidence_interval_table(
    console: Console,
    entries: list[ConfidenceIntervalEntry],
    min_width: float,
    top_n: int,
) -> None:
    if not entries:
        console.print("[green]No confidence intervals to display[/green]")
        return

    grouped: dict[str, list[ConfidenceIntervalEntry]] = defaultdict(list)
    for entry in entries:
        if entry.width >= min_width:
            grouped[entry.metric].append(entry)

    aggregated: list[
        tuple[str, float | None, float, float, float, int, float | None]
    ] = []
    for metric, metric_entries in grouped.items():
        widths = [e.width for e in metric_entries if _is_number(e.width)]
        if not widths:
            continue
        lows = [e.ci95_low for e in metric_entries if _is_number(e.ci95_low)]
        highs = [e.ci95_high for e in metric_entries if _is_number(e.ci95_high)]
        means = [e.mean for e in metric_entries if _is_number(e.mean)]
        runs = [e.runs for e in metric_entries if _is_number(e.runs)]
        aggregated.append(
            (
                metric,
                statistics.mean(means) if means else None,
                statistics.mean(lows) if lows else float("nan"),
                statistics.mean(highs) if highs else float("nan"),
                statistics.mean(widths),
                len(metric_entries),
                statistics.mean(runs) if runs else None,
            )
        )

    ordered = sorted(aggregated, key=lambda e: e[4], reverse=True)
    if top_n > 0:
        ordered = ordered[:top_n]

    table = Table(box=None, header_style="bold")
    table.add_column("Metric", style="magenta")
    table.add_column("Mean", justify="right")
    table.add_column("CI95 (avg)", justify="right", style="yellow")
    table.add_column("Width (avg)", justify="right", style="yellow")
    table.add_column("Problems", justify="right")
    table.add_column("Runs (avg)", justify="right")

    for metric, mean, ci_low, ci_high, width, problem_count, runs in ordered:
        table.add_row(
            metric,
            f"{mean:.2f}" if mean is not None else "-",
            f"[{ci_low:.2f}, {ci_high:.2f}]",
            f"{width:.2f}",
            str(problem_count),
            f"{runs:.1f}" if runs is not None else "-",
        )

    console.print(
        "\n[bold]Confidence intervals (95%) averaged across problems[/bold]"
    )
    console.print(table)


def _iter_checkpoint_records(
    group: RunGroup, specs: list[MetricSpec], preset: VariancePreset
) -> Iterable[dict[str, Any]]:
    for problem in sorted(group.common_problems):
        checkpoints = sorted(group.common_checkpoints(problem))
        if not checkpoints:
            continue

        for checkpoint in checkpoints:
            record: dict[str, Any] = {
                **group.key.as_dict(),
                "preset": preset.value,
                "run_count": group.run_count,
                "problem": problem,
                "checkpoint": checkpoint,
            }

            first_row = group.runs[0].rows_by_problem_checkpoint.get(
                (problem, checkpoint), {}
            )
            if isinstance(first_row.get("idx"), int):
                record["checkpoint_idx"] = first_row["idx"]

            wrote_metric = False
            for spec in specs:
                values: list[float] = []
                for run in group.runs:
                    row = run.rows_by_problem_checkpoint.get(
                        (problem, checkpoint)
                    )
                    if row is None:
                        continue
                    if spec.requires_rubric and "rubric_total_flags" not in row:
                        continue
                    value = _metric_value(row, spec.name)
                    if value is not None:
                        values.append(value)

                stats = _stats(values)
                for stat_name, stat_value in stats.items():
                    record[f"{spec.name}.{stat_name}"] = stat_value
                wrote_metric = wrote_metric or bool(stats)

            if wrote_metric:
                yield record


def _iter_problem_records(
    group: RunGroup, specs: list[MetricSpec], preset: VariancePreset
) -> Iterable[dict[str, Any]]:
    derived_specs = _build_derived_metric_names(preset, specs)

    for problem in sorted(group.common_problems):
        checkpoints = sorted(group.common_checkpoints(problem))
        if not checkpoints:
            continue

        record: dict[str, Any] = {
            **group.key.as_dict(),
            "preset": preset.value,
            "run_count": group.run_count,
            "problem": problem,
            "checkpoint_count": len(checkpoints),
        }

        rows_first_run = [
            group.runs[0].rows_by_problem_checkpoint[(problem, ck)]
            for ck in checkpoints
            if (problem, ck) in group.runs[0].rows_by_problem_checkpoint
        ]
        first_ck, final_ck = _checkpoint_bounds(rows_first_run)
        if first_ck:
            record["first_checkpoint"] = first_ck
        if final_ck:
            record["final_checkpoint"] = final_ck

        wrote_metric = False
        for derived_name in derived_specs:
            values: list[float] = []
            for run in group.runs:
                rows = [
                    run.rows_by_problem_checkpoint.get((problem, ck))
                    for ck in checkpoints
                ]
                rows = [row for row in rows if row is not None]
                if not rows:
                    continue
                value = _derived_metric_value(derived_name, rows)
                if value is not None:
                    values.append(value)

            stats = _stats(values)
            for stat_name, stat_value in stats.items():
                record[f"{derived_name}.{stat_name}"] = stat_value
            wrote_metric = wrote_metric or bool(stats)

        if wrote_metric:
            yield record


def _group_sort_key(group: RunGroup) -> tuple[str, str, str, str, str]:
    key = group.key
    return (
        key.model,
        key.prompt_path,
        key.thinking,
        key.agent_type,
        key.agent_version,
    )


def register(app: typer.Typer, name: str) -> None:
    app.command(
        name,
        help=(
            "Compute variance across multiple runs, grouped by model/prompt/"
            "thinking/agent version, writing JSONL variance reports."
        ),
    )(variance_report)


def variance_report(
    ctx: typer.Context,
    preset: VariancePreset = typer.Argument(
        ...,
        help="Metric preset: base, tests, or quality.",
    ),
    runs_dir: Path = typer.Argument(
        ...,
        help="Directory containing multiple run directories.",
        exists=True,
        dir_okay=True,
        file_okay=False,
    ),
    output_dir: Path = typer.Option(
        Path("outputs/variance"),
        "--output-dir",
        "-o",
        help="Directory to write problem_var.jsonl and checkpoint_var.jsonl.",
    ),
    ci_width_threshold: float = typer.Option(
        0.25,
        "--ci-width-threshold",
        "--ci-threshold",
        "--cv-threshold",
        help="Minimum 95% CI width to include in the summary table.",
        min=0.0,
    ),
    top_n: int = typer.Option(
        12,
        "--top-n",
        help="Maximum number of confidence interval rows to display (<=0 to show all).",
        min=-1,
    ),
) -> None:
    _ = ctx
    console = Console()
    ensure_dir_exists(output_dir, create=True)

    run_dirs = _discover_run_dirs(runs_dir)
    if not run_dirs:
        console.print(f"[red]No runs found in {runs_dir}[/red]")
        raise typer.Exit(1)

    runs: list[RunData] = []
    for run_dir in run_dirs:
        run = _load_run(run_dir)
        if run:
            runs.append(run)
    if not runs:
        console.print(f"[red]No readable runs found in {runs_dir}[/red]")
        raise typer.Exit(1)

    groups = _group_runs(runs)
    if not groups:
        console.print(
            "[yellow]No groups with >=2 runs; nothing to report.[/yellow]"
        )
        return

    console.print(f"Discovered {len(runs)} run(s)")

    checkpoint_out = output_dir / "checkpoint_var.jsonl"
    problem_out = output_dir / "problem_var.jsonl"

    ci_entries: list[ConfidenceIntervalEntry] = []
    problem_cv_summary, problem_first_cv_summary, problem_final_cv_summary = (
        _compute_problem_cv_summary(groups)
    )

    with checkpoint_out.open("w") as chk_fp, problem_out.open("w") as prob_fp:
        for group in sorted(groups, key=_group_sort_key):
            available_keys = {
                k
                for run in group.runs
                for row in run.rows_by_problem_checkpoint.values()
                for k, v in row.items()
                if _is_number(v)
            }
            specs = _build_metric_specs(preset, available_keys)

            for record in _iter_checkpoint_records(group, specs, preset):
                chk_fp.write(json.dumps(record, sort_keys=True) + "\n")
                ci_entries.extend(
                    _collect_ci_entries(
                        record,
                        group.key,
                        min_width=0.0,
                        allowed_metrics=CHECKPOINT_DELTA_METRICS,
                    )
                )

            for record in _iter_problem_records(group, specs, preset):
                prob_fp.write(json.dumps(record, sort_keys=True) + "\n")
                ci_entries.extend(
                    _collect_ci_entries(
                        record,
                        group.key,
                        min_width=0.0,
                        allowed_metrics=PROBLEM_CI_METRICS,
                    )
                )

    _render_problem_cv_summary(
        console,
        overall=problem_cv_summary,
        first=problem_first_cv_summary,
        final=problem_final_cv_summary,
    )
    _render_confidence_interval_table(
        console=console,
        entries=ci_entries,
        min_width=ci_width_threshold,
        top_n=top_n,
    )
    console.print(f"[green]Wrote {checkpoint_out}[/green]")
    console.print(f"[green]Wrote {problem_out}[/green]")
