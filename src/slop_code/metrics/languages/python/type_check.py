"""Type checking metrics via ty."""

from __future__ import annotations

import json
import subprocess
from collections import Counter
from pathlib import Path

from slop_code.logging import get_logger
from slop_code.metrics.models import TypeCheckMetrics

logger = get_logger(__name__)

_EMPTY = TypeCheckMetrics(errors=0, warnings=0, counts={})

# ty gitlab format maps severity to these strings
_ERROR_SEVERITIES = frozenset({"major", "critical", "blocker"})


def calculate_type_check_metrics(source: Path) -> TypeCheckMetrics:
    """Run ty type checker on a single file and return metrics."""
    cmd = [
        "uv",
        "run",
        "ty",
        "check",
        "--output-format",
        "gitlab",
        str(source.absolute()),
    ]
    try:
        result = subprocess.run(  # noqa: S603 - invokes the configured Ty binary.
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        logger.debug("ty not available")
        return _EMPTY

    stdout = result.stdout.strip()
    if not stdout:
        return _EMPTY

    try:
        diagnostics = json.loads(stdout)
    except json.JSONDecodeError:
        logger.warning(
            "Failed to parse ty output",
            source=str(source),
            stdout=stdout[:200],
        )
        return _EMPTY

    if not isinstance(diagnostics, list):
        return _EMPTY

    errors = 0
    warnings = 0
    counts: Counter[str] = Counter()

    for diag in diagnostics:
        severity = diag.get("severity", "").lower()
        rule = diag.get("check_name", "unknown")
        counts[rule] += 1
        if severity in _ERROR_SEVERITIES:
            errors += 1
        else:
            warnings += 1

    return TypeCheckMetrics(
        errors=errors, warnings=warnings, counts=dict(counts)
    )
