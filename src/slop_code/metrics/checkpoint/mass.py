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


def _compute_top_n_distribution(
    masses: list[float],
    percentiles: list[float] | None = None,
    key_prefix: str = "mass",
) -> dict[str, int | float]:
    """Compute how many symbols and how much mass account for top N% of total.

    Args:
        masses: List of mass values.
        percentiles: Percentiles to compute (default: [0.50, 0.75, 0.90]).
        key_prefix: Prefix for result keys (e.g., "mass" or empty string).

    Returns:
        Dict with {prefix}.top{N}_count and {prefix}.top{N}_mass keys,
        or top{N}_count/top{N}_mass if prefix is empty.
    """
    if percentiles is None:
        percentiles = [0.50, 0.75, 0.90]

    separator = "." if key_prefix else ""

    if not masses or sum(masses) < 1e-9:
        result: dict[str, int | float] = {}
        for pct in percentiles:
            pct_int = int(pct * 100)
            result[f"{key_prefix}{separator}top{pct_int}_count"] = 0
            result[f"{key_prefix}{separator}top{pct_int}_mass"] = 0.0
        return result

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
        result[f"{key_prefix}{separator}top{pct_int}_count"] = count
        result[f"{key_prefix}{separator}top{pct_int}_mass"] = round(cumsum, 2)

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
    non_zero = [m for m in masses if m > 1e-9]

    if len(non_zero) <= 1 or sum(non_zero) < 1e-9:
        return 0.0

    sorted_masses = sorted(non_zero)
    n = len(sorted_masses)
    total = sum(sorted_masses)

    # Gini formula: (2 * sum(i * val[i]) - (n+1) * total) / (n * total)
    weighted_sum = sum((i + 1) * val for i, val in enumerate(sorted_masses))
    return (2 * weighted_sum - (n + 1) * total) / (n * total)




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
    file_path = sym["file_path"]
    name = sym["name"]
    parent = sym.get("parent_class")
    return f"{file_path}:{parent}.{name}" if parent else f"{file_path}:{name}"


def _load_symbols(path: Path) -> list[dict[str, Any]]:
    """Load symbols from JSONL file, filtering to functions/methods."""
    if not path.exists():
        return []

    symbols = []
    with path.open() as f:
        for line in f:
            if line := line.strip():
                sym = json.loads(line)
                if sym.get("type") in {"function", "method"}:
                    symbols.append(sym)
    return symbols


def _match_symbols_by_hash(
    unmatched_before: dict[str, dict],
    unmatched_after: dict[str, dict],
    hash_col: str,
) -> list[tuple[dict, dict]]:
    """Match unmatched symbols using a hash column.

    Args:
        unmatched_before: Dict of key -> symbol for unmatched before symbols.
        unmatched_after: Dict of key -> symbol for unmatched after symbols.
        hash_col: Hash column name to match on.

    Returns:
        List of (before_sym, after_sym) matched pairs.
    """
    # Build hash to key lookup for before symbols
    before_hashes = {
        sym.get(hash_col): key
        for key, sym in unmatched_before.items()
        if sym.get(hash_col)
    }

    matched_pairs = []
    matched_keys_before = set()
    matched_keys_after = set()

    for key, sym in unmatched_after.items():
        hash_val = sym.get(hash_col)
        if hash_val and hash_val in before_hashes:
            before_key = before_hashes[hash_val]
            matched_pairs.append((unmatched_before[before_key], sym))
            matched_keys_before.add(before_key)
            matched_keys_after.add(key)

    # Remove matched symbols from unmatched dicts
    for k in matched_keys_before:
        del unmatched_before[k]
    for k in matched_keys_after:
        del unmatched_after[k]

    return matched_pairs


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
    before_by_key = {_symbol_key(s): s for s in before}
    after_by_key = {_symbol_key(s): s for s in after}

    matched_keys = set(before_by_key.keys()) & set(after_by_key.keys())
    unmatched_before = {
        k: v for k, v in before_by_key.items() if k not in matched_keys
    }
    unmatched_after = {
        k: v for k, v in after_by_key.items() if k not in matched_keys
    }

    # Primary key matches
    matched_pairs = [
        (before_by_key[k], after_by_key[k]) for k in matched_keys
    ]

    # Fallback hash matching for unmatched symbols
    for hash_col in ["signature_hash", "body_hash", "structure_hash"]:
        if not unmatched_before or not unmatched_after:
            break
        hash_matches = _match_symbols_by_hash(
            unmatched_before, unmatched_after, hash_col
        )
        matched_pairs.extend(hash_matches)

    return matched_pairs, list(unmatched_after.values()), list(unmatched_before.values())


def _calc_symbol_mass(sym: dict[str, Any], metric: str, baseline: int) -> float:
    """Calculate mass for a single symbol and metric."""
    return calc_mass(sym.get(metric, 0), sym.get("statements", 0), baseline)


def _process_mass_deltas(
    matched_pairs: list[tuple[dict, dict]],
    added_symbols: list[dict],
    removed_symbols: list[dict],
    metric: str,
    baseline: int,
) -> tuple[list[float], list[float], list[float], list[float]]:
    """Process mass changes for a metric across matched, added, and removed symbols.

    Returns:
        (added_masses, removed_masses, before_masses, after_masses)
    """
    added_masses = []
    removed_masses = []
    before_masses = []
    after_masses = []

    # Process matched symbols
    for before_sym, after_sym in matched_pairs:
        mass_before = _calc_symbol_mass(before_sym, metric, baseline)
        mass_after = _calc_symbol_mass(after_sym, metric, baseline)
        delta = mass_after - mass_before

        if delta > 1e-9:
            added_masses.append(delta)
        elif delta < -1e-9:
            removed_masses.append(abs(delta))

        before_masses.append(mass_before)
        after_masses.append(mass_after)

    # Added symbols contribute their full mass
    for sym in added_symbols:
        mass = _calc_symbol_mass(sym, metric, baseline)
        if mass > 1e-9:
            added_masses.append(mass)
        after_masses.append(mass)

    # Removed symbols contribute their full mass as removed
    for sym in removed_symbols:
        mass = _calc_symbol_mass(sym, metric, baseline)
        if mass > 1e-9:
            removed_masses.append(mass)
        before_masses.append(mass)

    return added_masses, removed_masses, before_masses, after_masses


def _add_complexity_metrics(
    result: dict[str, Any],
    key: str,
    added_masses: list[float],
    removed_masses: list[float],
    total_added: float,
    total_removed: float,
    gross_delta: float,
    net_delta: float,
) -> None:
    """Add full suite of complexity metrics to result dict (mutates in place)."""
    result[f"delta.mass.{key}_added"] = round(total_added, 2)
    result[f"delta.mass.{key}_added_count"] = len(added_masses)
    result[f"delta.mass.{key}_added_concentration"] = round(
        _compute_gini_coefficient(added_masses), 3
    )

    # Top N distribution for added mass
    added_top_n = _compute_top_n_distribution(
        added_masses, percentiles=[0.50, 0.75, 0.90], key_prefix=""
    )
    for pct in [50, 75, 90]:
        result[f"delta.mass.{key}_added_top{pct}_count"] = added_top_n[f"top{pct}_count"]
        result[f"delta.mass.{key}_added_top{pct}_mass"] = added_top_n[f"top{pct}_mass"]

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

        **Net Deltas**:
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
    if not prior_symbols_path or not prior_symbols_path.exists() or not curr_symbols_path.exists():
        return {}

    before = _load_symbols(prior_symbols_path)
    after = _load_symbols(curr_symbols_path)

    if not before and not after:
        return {}

    matched_pairs, added_symbols, removed_symbols = _match_symbols(before, after)
    result: dict[str, Any] = {}

    # Track complexity masses for top N% distribution
    before_complexity_masses = []
    after_complexity_masses = []

    # Compute mass delta for each metric
    for metric in MASS_METRICS:
        baseline = BASELINES.get(metric, 0)
        key = KEY_NAMES[metric]

        added_masses, removed_masses, before_masses, after_masses = _process_mass_deltas(
            matched_pairs, added_symbols, removed_symbols, metric, baseline
        )

        if metric == "complexity":
            before_complexity_masses = before_masses
            after_complexity_masses = after_masses

        # Compute aggregates
        total_added = sum(added_masses)
        total_removed = sum(removed_masses)
        net_delta = total_added - total_removed
        gross_delta = total_added + total_removed

        result[f"delta.mass.{key}"] = round(net_delta, 2)

        # Full suite for complexity
        if metric == "complexity":
            _add_complexity_metrics(
                result, key, added_masses, removed_masses,
                total_added, total_removed, gross_delta, net_delta
            )
        else:
            # Top 90% only for other metrics
            added_top90 = _compute_top_n_distribution(
                added_masses, percentiles=[0.90], key_prefix=""
            )
            result[f"delta.mass.{key}_added_top90_count"] = added_top90["top90_count"]
            result[f"delta.mass.{key}_added_top90_mass"] = added_top90["top90_mass"]

    # Top N% distribution deltas
    before_top_n = _compute_top_n_distribution(before_complexity_masses)
    after_top_n = _compute_top_n_distribution(after_complexity_masses)
    for pct in ["50", "75", "90"]:
        count_key = f"mass.top{pct}_count"
        mass_key = f"mass.top{pct}_mass"
        result[f"delta.{count_key}"] = after_top_n[count_key] - before_top_n[count_key]
        result[f"delta.{mass_key}"] = round(after_top_n[mass_key] - before_top_n[mass_key], 2)

    # Symbol change counts
    result["delta.symbols_added"] = len(added_symbols)
    result["delta.symbols_removed"] = len(removed_symbols)

    # Count modified symbols (complexity mass changed)
    baseline = BASELINES.get("complexity", 0)
    modified_count = sum(
        1 for before_sym, after_sym in matched_pairs
        if abs(_calc_symbol_mass(after_sym, "complexity", baseline) -
               _calc_symbol_mass(before_sym, "complexity", baseline)) > 1e-9
    )
    result["delta.symbols_modified"] = modified_count

    return result
