"""Mass metrics: size-weighted metrics for cognitive load measurement.

Mass formula: mass = max(0, metric - baseline) * sqrt(statements)

This captures the total "cognitive load" of code, accounting for both
the metric value (e.g., complexity) and the function size.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterator
from pathlib import Path
from typing import Any

# Constants
ALPHA = 0.5  # Size exponent for mass formula
HIGH_CC_THRESHOLD = 10  # Threshold for "high complexity"

# Baselines: metric must exceed baseline to contribute mass
BASELINES: dict[str, int] = {
    "complexity": 1,  # CC=1 is minimal complexity
    # All others default to 0
}

# Metrics to compute mass for
MASS_METRICS = [
    "complexity",
    "branches",
    "comparisons",
    "variables_used",
    "variables_defined",
    "exception_scaffold",
]

# Key name mappings for cleaner output
KEY_NAMES = {
    "complexity": "complexity",
    "branches": "branches",
    "comparisons": "comparisons",
    "variables_used": "vars_used",
    "variables_defined": "vars_defined",
    "exception_scaffold": "try_scaffold",
}


def calc_mass(value: int, statements: int, baseline: int = 0) -> float:
    """Compute mass for a single function/method.

    Args:
        value: Metric value (complexity, branches, etc.)
        statements: Number of statements in the function.
        baseline: Minimum value before mass accrues (default 0).

    Returns:
        Mass value: (value - baseline)^+ * statements^0.5
    """
    excess = max(0, value - baseline)
    size_factor = math.pow(max(1, statements), ALPHA)
    return excess * size_factor


def _compute_top_n_distribution(masses: list[float]) -> dict[str, int]:
    """Compute how many symbols account for top N% of mass.

    Returns dict with mass.top50_count, mass.top75_count, mass.top90_count.
    """
    if not masses or sum(masses) == 0:
        return {
            "mass.top50_count": 0,
            "mass.top75_count": 0,
            "mass.top90_count": 0,
        }

    # Sort descending
    sorted_masses = sorted(masses, reverse=True)
    total = sum(sorted_masses)

    result = {}
    for pct, key in [
        (0.50, "mass.top50_count"),
        (0.75, "mass.top75_count"),
        (0.90, "mass.top90_count"),
    ]:
        threshold = total * pct
        cumsum = 0.0
        count = 0
        for m in sorted_masses:
            cumsum += m
            count += 1
            if cumsum >= threshold:
                break
        result[key] = count

    return result


def compute_mass_metrics(symbol_iter: Iterator[dict[str, Any]]) -> dict[str, Any]:
    """Compute mass metrics from symbol-level data.

    Args:
        symbol_iter: Iterator over symbol metrics (from symbols.jsonl).

    Returns:
        Dict with mass metrics:
        - mass.{metric}: Total mass for each metric type
        - mass.top50_count, mass.top75_count, mass.top90_count: Distribution
        - mass.high_cc: Mass in functions with CC > 10
        - mass.high_cc_pct: Percentage of mass in high CC functions
    """
    # Collect mass per metric
    mass_totals: dict[str, float] = dict.fromkeys(MASS_METRICS, 0.0)
    complexity_masses: list[float] = []
    high_cc_mass = 0.0

    for sym in symbol_iter:
        if sym.get("type") not in {"function", "method"}:
            continue

        statements = sym.get("statements", 0)
        complexity = sym.get("complexity", 1)

        # Compute mass for each metric
        for metric in MASS_METRICS:
            value = sym.get(metric, 0)
            baseline = BASELINES.get(metric, 0)
            mass = calc_mass(value, statements, baseline)
            mass_totals[metric] += mass

            # Track complexity specifically for distribution
            if metric == "complexity":
                complexity_masses.append(mass)
                if complexity > HIGH_CC_THRESHOLD:
                    high_cc_mass += mass

    total_complexity_mass = mass_totals["complexity"]

    # Build result with clean key names
    result: dict[str, Any] = {}
    for metric in MASS_METRICS:
        key = KEY_NAMES[metric]
        result[f"mass.{key}"] = round(mass_totals[metric], 2)

    # Add distribution metrics
    result.update(_compute_top_n_distribution(complexity_masses))

    # Add high complexity metrics
    result["mass.high_cc"] = round(high_cc_mass, 2)
    result["mass.high_cc_pct"] = round(
        (high_cc_mass / total_complexity_mass * 100)
        if total_complexity_mass > 0
        else 0.0,
        1,
    )

    return result


def _symbol_key(sym: dict[str, Any]) -> str:
    """Generate primary key for symbol matching."""
    parent = sym.get("parent_class") or ""
    file_path = sym["file_path"]
    name = sym["name"]
    if parent:
        return f"{file_path}:{parent}.{name}"
    return f"{file_path}:{name}"


def _load_symbols(path: Path) -> list[dict[str, Any]]:
    """Load symbols from JSONL file, filtering to functions/methods."""
    symbols = []
    if not path.exists():
        return symbols

    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            sym = json.loads(line)
            if sym.get("type") in {"function", "method"}:
                symbols.append(sym)
    return symbols


def _match_symbols(
    before: list[dict[str, Any]], after: list[dict[str, Any]]
) -> tuple[list[tuple[dict, dict]], list[dict], list[dict]]:
    """Match symbols between two checkpoints.

    Returns:
        (matched_pairs, added, removed)
        - matched_pairs: List of (before_sym, after_sym) tuples
        - added: Symbols only in after
        - removed: Symbols only in before
    """
    # Generate primary keys
    before_by_key = {_symbol_key(s): s for s in before}
    after_by_key = {_symbol_key(s): s for s in after}

    keys_before = set(before_by_key.keys())
    keys_after = set(after_by_key.keys())

    matched_keys = keys_before & keys_after
    only_before_keys = keys_before - keys_after
    only_after_keys = keys_after - keys_before

    # Primary matches
    matched_pairs = [
        (before_by_key[k], after_by_key[k]) for k in matched_keys
    ]

    # Try fallback hash matching for unmatched symbols
    unmatched_before = {k: before_by_key[k] for k in only_before_keys}
    unmatched_after = {k: after_by_key[k] for k in only_after_keys}

    for hash_col in ["signature_hash", "body_hash", "structure_hash"]:
        if not unmatched_before or not unmatched_after:
            break

        # Build hash lookup
        before_hashes: dict[str, str] = {}
        for key, sym in unmatched_before.items():
            h = sym.get(hash_col)
            if h:
                before_hashes[h] = key

        to_remove_before = []
        to_remove_after = []

        for key, sym in unmatched_after.items():
            h = sym.get(hash_col)
            if h and h in before_hashes:
                before_key = before_hashes[h]
                matched_pairs.append((unmatched_before[before_key], sym))
                to_remove_before.append(before_key)
                to_remove_after.append(key)
                del before_hashes[h]

        for k in to_remove_before:
            del unmatched_before[k]
        for k in to_remove_after:
            del unmatched_after[k]

    added = list(unmatched_after.values())
    removed = list(unmatched_before.values())

    return matched_pairs, added, removed


def compute_mass_delta(
    prior_symbols_path: Path | None,
    curr_symbols_path: Path,
) -> dict[str, Any]:
    """Compute mass delta between checkpoints with symbol matching.

    Args:
        prior_symbols_path: Path to prior checkpoint's symbols.jsonl (None if first).
        curr_symbols_path: Path to current checkpoint's symbols.jsonl.

    Returns:
        Dict with delta metrics:
        - delta.mass.{metric}: Change in mass for each metric type
        - delta.symbols_added: Count of new functions/methods
        - delta.symbols_removed: Count of deleted functions/methods
        - delta.symbols_modified: Count of changed functions/methods
    """
    if prior_symbols_path is None or not prior_symbols_path.exists():
        return {}

    if not curr_symbols_path.exists():
        return {}

    before = _load_symbols(prior_symbols_path)
    after = _load_symbols(curr_symbols_path)

    if not before and not after:
        return {}

    matched_pairs, added, removed = _match_symbols(before, after)

    result: dict[str, Any] = {}

    # Compute mass delta for each metric
    for metric in MASS_METRICS:
        baseline = BASELINES.get(metric, 0)

        # Mass from matched symbols (before and after)
        mass_matched_before = sum(
            calc_mass(s.get(metric, 0), s.get("statements", 0), baseline)
            for s, _ in matched_pairs
        )
        mass_matched_after = sum(
            calc_mass(s.get(metric, 0), s.get("statements", 0), baseline)
            for _, s in matched_pairs
        )

        # Mass from removed symbols (was in before, not in after)
        mass_removed = sum(
            calc_mass(s.get(metric, 0), s.get("statements", 0), baseline)
            for s in removed
        )

        # Mass from added symbols (in after, not in before)
        mass_added = sum(
            calc_mass(s.get(metric, 0), s.get("statements", 0), baseline)
            for s in added
        )

        total_before = mass_matched_before + mass_removed
        total_after = mass_matched_after + mass_added
        delta = total_after - total_before

        key = KEY_NAMES[metric]
        result[f"delta.mass.{key}"] = round(delta, 2)

    # Count symbol changes
    result["delta.symbols_added"] = len(added)
    result["delta.symbols_removed"] = len(removed)

    # Count modified (mass changed for complexity)
    baseline = BASELINES.get("complexity", 0)
    modified_count = 0
    for before_sym, after_sym in matched_pairs:
        mass_before = calc_mass(
            before_sym.get("complexity", 0),
            before_sym.get("statements", 0),
            baseline,
        )
        mass_after = calc_mass(
            after_sym.get("complexity", 0),
            after_sym.get("statements", 0),
            baseline,
        )
        if abs(mass_after - mass_before) > 1e-9:
            modified_count += 1

    result["delta.symbols_modified"] = modified_count

    return result
