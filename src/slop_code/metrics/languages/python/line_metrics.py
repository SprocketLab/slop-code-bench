"""Line count and maintainability index metrics."""

from __future__ import annotations

from pathlib import Path

import radon.metrics
import radon.raw

from slop_code.metrics.languages.python.utils import read_python_code
from slop_code.metrics.models import LineCountMetrics


def calculate_mi(source: Path) -> float:
    """Calculate the maintainability index for a Python file."""
    code = read_python_code(source)
    return radon.metrics.mi_visit(code, multi=False)


def calculate_line_metrics(source: Path) -> LineCountMetrics:
    """Calculate line count metrics for a Python file."""
    # Get raw metrics from radon
    raw_metrics = radon.raw.analyze(read_python_code(source))

    # Map radon metrics to our LineCountMetrics model
    return LineCountMetrics(
        total_lines=raw_metrics.loc,  # Total lines
        loc=raw_metrics.sloc,  # Source lines of code
        comments=raw_metrics.comments,  # Total comment lines
        multi_comment=raw_metrics.multi,
        single_comment=raw_metrics.single_comments,  # Single-line comments
    )
