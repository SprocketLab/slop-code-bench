"""Code quality and rubric metrics module.

This module provides functionality for measuring code quality metrics
and performing LLM-based rubric grading. It is independent of the
evaluation framework and can be used standalone.

Public API:
- Quality metrics: measure_snapshot_quality, measure_files
- Models: LineCountMetrics, LintMetrics, SymbolMetrics, FileMetrics,
          SnapshotMetrics, SnapshotQualityReport, LanguageSpec
- Rubric grading: grade_file, grade_file_async, carry_forward_grades
"""

# Checkpoint results (metric extraction)
from slop_code.metrics.checkpoint import compute_checkpoint_delta
from slop_code.metrics.checkpoint import get_checkpoint_metrics
from slop_code.metrics.checkpoint import get_evaluation_metrics
from slop_code.metrics.checkpoint import get_inference_metrics
from slop_code.metrics.checkpoint import get_quality_metrics
from slop_code.metrics.checkpoint import get_rubric_metrics
from slop_code.metrics.driver import batch_files_by_size
from slop_code.metrics.driver import measure_snapshot_quality
from slop_code.metrics.driver import process_problem_quality
from slop_code.metrics.grade import llm_judge_snapshot
from slop_code.metrics.grade import llm_judge_snapshot_batch

# Language registry
from slop_code.metrics.languages import get_language
from slop_code.metrics.languages import get_language_by_extension
from slop_code.metrics.models import AstGrepMetrics
from slop_code.metrics.models import AstGrepViolation

# Models - Summary
from slop_code.metrics.models import CostsStats
from slop_code.metrics.models import CyclomaticComplexityStats
from slop_code.metrics.models import DeltaStats

# Models - Quality
from slop_code.metrics.models import FileMetrics
from slop_code.metrics.models import LineCountMetrics
from slop_code.metrics.models import LintMetrics
from slop_code.metrics.models import MetricStats
from slop_code.metrics.models import PassRatesByType
from slop_code.metrics.models import PassRatesStats
from slop_code.metrics.models import RatiosStats
from slop_code.metrics.models import RunSummary
from slop_code.metrics.models import SnapshotMetrics
from slop_code.metrics.models import SnapshotQualityReport
from slop_code.metrics.models import StepsStats
from slop_code.metrics.models import SymbolMetrics
from slop_code.metrics.models import TimeStats
from slop_code.metrics.models import TokenMeans
from slop_code.metrics.models import TokenStats
from slop_code.metrics.rubric import RubricProvider
from slop_code.metrics.rubric import carry_forward_grades
from slop_code.metrics.rubric import process_problem_carry_forward

# Summary (aggregation)
from slop_code.metrics.summary import compute_run_summary
from slop_code.metrics.summary import load_checkpoint_data
from slop_code.metrics.summary import save_summary_json
from slop_code.metrics.utils import MetricsError

# Rubric grades output filename
RUBRIC_GRADES_SAVENAME = "rubric_grades.json"


__all__ = [
    "batch_files_by_size",
    "measure_snapshot_quality",
    "process_problem_quality",
    # Checkpoint results
    "compute_checkpoint_delta",
    "get_checkpoint_metrics",
    "get_evaluation_metrics",
    "get_inference_metrics",
    "get_quality_metrics",
    "get_rubric_metrics",
    # Summary
    "compute_run_summary",
    "load_checkpoint_data",
    "save_summary_json",
    # Models - Quality
    "AstGrepMetrics",
    "AstGrepViolation",
    "FileMetrics",
    "LineCountMetrics",
    "LintMetrics",
    "SnapshotMetrics",
    "SnapshotQualityReport",
    "SymbolMetrics",
    # Models - Summary
    "CostsStats",
    "CyclomaticComplexityStats",
    "DeltaStats",
    "MetricStats",
    "PassRatesByType",
    "PassRatesStats",
    "RatiosStats",
    "RunSummary",
    "StepsStats",
    "TimeStats",
    "TokenMeans",
    "TokenStats",
    # Language
    "get_language",
    "get_language_by_extension",
    # Rubric
    "carry_forward_grades",
    "process_problem_carry_forward",
    "RubricProvider",
    # LLM judge
    "llm_judge_snapshot",
    "llm_judge_snapshot_batch",
    "MetricsError",
]
_GRADE_EXPORTS = {
    "DEFAULT_CHECKPOINT_CONCURRENCY",
    "DEFAULT_MAX_BATCH_FILES",
    "DEFAULT_MAX_BATCH_LINES",
    "llm_judge_snapshot",
    "llm_judge_snapshot_batch",
}
