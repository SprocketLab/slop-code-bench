"""Ruff-based lint metrics."""

from __future__ import annotations

import json
import subprocess
from collections import Counter
from pathlib import Path

from slop_code.logging import get_logger
from slop_code.metrics.languages.python.constants import RUFF_SELECT_FLAGS
from slop_code.metrics.models import LintMetrics

logger = get_logger(__name__)


def calculate_lint_metrics(source: Path) -> LintMetrics:
    """Calculate lint metrics for a Python file using ruff."""
    cmd = [
        "uv",
        "run",
        "ruff",
        "check",
        "--statistics",
        "--output-format",
        "json",
        "--isolated",
        "--preview",
        *RUFF_SELECT_FLAGS,
        str(source.absolute()),
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
    except subprocess.CalledProcessError as e:
        logger.error(
            "Failed to calculate lint metrics",
            source=str(source),
            error=str(e),
        )
        return LintMetrics(errors=0, fixable=0, counts={})

    stats = None
    stdout = result.stdout
    while stats is None and stdout:
        try:
            stats = json.loads(stdout)
            break
        except json.JSONDecodeError:
            stdout = stdout.split("\n", 1)[1]

    if not stats:
        logger.warning(
            "Failed to parse lint statistics",
            source=str(source),
            stdout=stdout,
        )
        return LintMetrics(errors=0, fixable=0, counts={})

    counts = Counter()
    fixable = total = 0

    for item in stats:
        if not isinstance(item["code"], str):
            continue
        counts[item["code"]] += item["count"]
        total += item["count"]
        if item["fixable"]:
            fixable += item["count"]

    return LintMetrics(errors=total, fixable=fixable, counts=counts)
