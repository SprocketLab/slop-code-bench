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


def _compute_top_n_distribution(masses: list[float]) -> dict[str, int | float]:
    """Compute how many symbols and how much mass account for top N% of total.

    Returns dict with:
    - mass.top{50,75,90}_count: number of symbols reaching threshold
    - mass.top{50,75,90}_mass: actual mass in those symbols
    """
    if not masses or sum(masses) == 0:
        return {
            "mass.top50_count": 0,
            "mass.top50_mass": 0.0,
            "mass.top75_count": 0,
            "mass.top75_mass": 0.0,
            "mass.top90_count": 0,
            "mass.top90_mass": 0.0,
        }

    # Sort descending
    sorted_masses = sorted(masses, reverse=True)
    total = sum(sorted_masses)

    result: dict[str, int | float] = {}
    for pct, count_key, mass_key in [
        (0.50, "mass.top50_count", "mass.top50_mass"),
        (0.75, "mass.top75_count", "mass.top75_mass"),
        (0.90, "mass.top90_count", "mass.top90_mass"),
    ]:
        threshold = total * pct
        cumsum = 0.0
        count = 0
        for m in sorted_masses:
            cumsum += m
            count += 1
            if cumsum >= threshold:
                break
        result[count_key] = count
        result[mass_key] = round(cumsum, 2)

    return result


def _compute_gini_coefficient(masses: list[float]) -> float:
    """Compute Gini coefficient for mass distribution.

    Measures inequality in distribution:
    - 0 = perfectly uniform (all functions have equal mass)
    - 1 = maximum concentration (all mass in one function)

    Args:
        masses: List of mass values (positive floats).

    Returns:
        Gini coefficient in [0, 1].
    """
    if len(masses) <= 1:
        return 0.0

    # Filter out zeros (don't contribute to inequality)
    non_zero = [m for m in masses if m > 1e-9]
    if len(non_zero) <= 1:
        return 0.0

    total = sum(non_zero)
    if total < 1e-9:
        return 0.0

    # Sort ascending
    sorted_masses = sorted(non_zero)
    n = len(sorted_masses)

    # Gini formula: (2 * sum(i * val[i]) - (n+1) * total) / (n * total)
    # where i is 1-indexed
    weighted_sum = sum((i + 1) * val for i, val in enumerate(sorted_masses))
    numerator = 2 * weighted_sum - (n + 1) * total
    denominator = n * total

    return numerator / denominator


def _compute_top_n_for_added_mass(
    masses: list[float],
    percentiles: list[float] | None = None,
) -> dict[str, int | float]:
    """Compute top N% distribution for added mass only.

    Args:
        masses: List of positive mass deltas (only functions with increases).
        percentiles: Percentiles to compute (default: [0.50, 0.75, 0.90]).

    Returns:
        Dict with top{N}_count and top{N}_mass keys for each percentile.
    """
    if percentiles is None:
        percentiles = [0.50, 0.75, 0.90]

    if not masses or sum(masses) < 1e-9:
        result: dict[str, int | float] = {}
        for pct in percentiles:
            pct_int = int(pct * 100)
            result[f"top{pct_int}_count"] = 0
            result[f"top{pct_int}_mass"] = 0.0
        return result

    # Sort descending (highest mass first)
    sorted_masses = sorted(masses, reverse=True)
    total = sum(sorted_masses)

    result = {}
    for pct in percentiles:
        threshold = total * pct
        cumsum = 0.0
        count = 0

        for m in sorted_masses:
            cumsum += m
            count += 1
            if cumsum >= threshold:
                break

        pct_int = int(pct * 100)
        result[f"top{pct_int}_count"] = count
        result[f"top{pct_int}_mass"] = round(cumsum, 2)

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
    """Compute mass delta between checkpoints with added/removed mass tracking.

    Args:
        prior_symbols_path: Path to prior checkpoint's symbols.jsonl (None if first).
        curr_symbols_path: Path to current checkpoint's symbols.jsonl.

    Returns:
        Dict with delta metrics:

        **Backward Compatible (Net Deltas)**:
        - delta.mass.{metric}: Net change in mass (added - removed)
        - delta.mass.top{50,75,90}_count: Change in top N% symbol counts
        - delta.symbols_added/removed/modified: Symbol change counts

        **Complexity Added Mass (Full Suite)**:
        - delta.mass.complexity_added: Total added mass
        - delta.mass.complexity_added_count: # functions with increases
        - delta.mass.complexity_added_concentration: Gini coefficient (0-1)
        - delta.mass.complexity_added_top{50,75,90}_count: # symbols for top N%
        - delta.mass.complexity_added_top{50,75,90}_mass: Mass in top N% symbols

        **Complexity Removed Mass**:
        - delta.mass.complexity_removed: Total removed mass (absolute value)
        - delta.mass.complexity_removed_count: # functions with decreases
        - delta.mass.complexity_removed_concentration: Gini coefficient (0-1)

        **Complexity Aggregate**:
        - delta.mass.complexity_gross: added + removed (total churn)
        - delta.mass.complexity_net_to_gross_ratio: (added - removed) / gross

        **Other Metrics (Top 90% Only)**:
        - delta.mass.{branches,comparisons,etc}_added_top90_count
        - delta.mass.{metric}_added_top90_mass
    """
    if prior_symbols_path is None or not prior_symbols_path.exists():
        return {}

    if not curr_symbols_path.exists():
        return {}

    before = _load_symbols(prior_symbols_path)
    after = _load_symbols(curr_symbols_path)

    if not before and not after:
        return {}

    matched_pairs, added_symbols, removed_symbols = _match_symbols(before, after)

    result: dict[str, Any] = {}

    # Track complexity masses for backward-compatible top N% distribution
    before_complexity_masses: list[float] = []
    after_complexity_masses: list[float] = []

    # Compute mass delta for each metric with added/removed tracking
    for metric in MASS_METRICS:
        baseline = BASELINES.get(metric, 0)
        key = KEY_NAMES[metric]

        # Collect per-symbol mass changes for added/removed analysis
        added_masses: list[float] = []  # Positive deltas only
        removed_masses: list[float] = []  # Negative deltas (absolute values)

        # Process matched symbols - categorize mass changes
        for before_sym, after_sym in matched_pairs:
            mass_before = calc_mass(
                before_sym.get(metric, 0),
                before_sym.get("statements", 0),
                baseline,
            )
            mass_after = calc_mass(
                after_sym.get(metric, 0),
                after_sym.get("statements", 0),
                baseline,
            )
            delta = mass_after - mass_before

            if delta > 1e-9:
                added_masses.append(delta)
            elif delta < -1e-9:
                removed_masses.append(abs(delta))

            # Track for backward-compatible top N% computation
            if metric == "complexity":
                before_complexity_masses.append(mass_before)
                after_complexity_masses.append(mass_after)

        # Process newly added symbols - all their mass is "added"
        for sym in added_symbols:
            mass = calc_mass(
                sym.get(metric, 0),
                sym.get("statements", 0),
                baseline,
            )
            if mass > 1e-9:
                added_masses.append(mass)

            if metric == "complexity":
                after_complexity_masses.append(mass)

        # Process removed symbols - all their mass is "removed"
        for sym in removed_symbols:
            mass = calc_mass(
                sym.get(metric, 0),
                sym.get("statements", 0),
                baseline,
            )
            if mass > 1e-9:
                removed_masses.append(mass)

            if metric == "complexity":
                before_complexity_masses.append(mass)

        # Compute aggregate metrics
        total_added = sum(added_masses)
        total_removed = sum(removed_masses)
        net_delta = total_added - total_removed
        gross_delta = total_added + total_removed

        # Backward compatible: net delta
        result[f"delta.mass.{key}"] = round(net_delta, 2)

        # Full suite for complexity metric
        if metric == "complexity":
            # Added mass metrics
            result[f"delta.mass.{key}_added"] = round(total_added, 2)
            result[f"delta.mass.{key}_added_count"] = len(added_masses)
            result[f"delta.mass.{key}_added_concentration"] = round(
                _compute_gini_coefficient(added_masses), 3
            )

            added_top_n = _compute_top_n_for_added_mass(
                added_masses, [0.50, 0.75, 0.90]
            )
            for pct in [50, 75, 90]:
                result[f"delta.mass.{key}_added_top{pct}_count"] = added_top_n[
                    f"top{pct}_count"
                ]
                result[f"delta.mass.{key}_added_top{pct}_mass"] = added_top_n[
                    f"top{pct}_mass"
                ]

            # Removed mass metrics
            result[f"delta.mass.{key}_removed"] = round(total_removed, 2)
            result[f"delta.mass.{key}_removed_count"] = len(removed_masses)
            result[f"delta.mass.{key}_removed_concentration"] = round(
                _compute_gini_coefficient(removed_masses), 3
            )

            # Aggregate metrics
            result[f"delta.mass.{key}_gross"] = round(gross_delta, 2)
            result[f"delta.mass.{key}_net_to_gross_ratio"] = round(
                net_delta / gross_delta if gross_delta > 1e-9 else 0.0, 3
            )

        # Top 90% only for other metrics
        else:
            added_top90 = _compute_top_n_for_added_mass(added_masses, [0.90])
            result[f"delta.mass.{key}_added_top90_count"] = added_top90["top90_count"]
            result[f"delta.mass.{key}_added_top90_mass"] = added_top90["top90_mass"]

    # Backward compatible: top N% distribution deltas (raw difference)
    before_top_n = _compute_top_n_distribution(before_complexity_masses)
    after_top_n = _compute_top_n_distribution(after_complexity_masses)
    for pct in ["50", "75", "90"]:
        count_key = f"mass.top{pct}_count"
        mass_key = f"mass.top{pct}_mass"
        result[f"delta.{count_key}"] = (
            after_top_n[count_key] - before_top_n[count_key]
        )
        result[f"delta.{mass_key}"] = round(
            after_top_n[mass_key] - before_top_n[mass_key], 2
        )

    # Count symbol changes
    result["delta.symbols_added"] = len(added_symbols)
    result["delta.symbols_removed"] = len(removed_symbols)

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
