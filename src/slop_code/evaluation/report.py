"""Typed report models emitted by the evaluation runner.

The runner serializes results at multiple granularities—case, group, and
checkpoint. These Pydantic models make that structure explicit and provide
helper methods for flattening data into analytics-friendly shapes (JSON,
Parquet) while preserving enough context for downstream visualization.
"""

import json
from collections import Counter
from collections.abc import Mapping
from datetime import datetime
from enum import Enum
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from slop_code.common import EVALUATION_FILENAME
from slop_code.common import VERIFIER_REPORT_FILENAME
from slop_code.evaluation.config import GroupType
from slop_code.evaluation.verifiers import VerifierReport
from slop_code.logging import get_logger

logger = get_logger(__name__)

# Constants
DEFAULT_STAGE = "step-1"
FLATTENING_DELIMITER = "-"
PASSING_SCORE_THRESHOLD = 1.0


class PassPolicy(str, Enum):
    ANY = "any"
    ANY_CASE = "any-case"
    ALL_CASES = "all-cases"
    ALL_NON_ERROR_CASES = "all-non-error-cases"
    CORE_CASES = "core-cases"
    ANY_CORE_CASES = "any-core-cases"
    ALL_CORE_CASES = "all-core-cases"

    def check(
        self,
        pass_counts: Mapping[GroupType, int],
        total_counts: Mapping[GroupType, int],
    ) -> bool:
        """Return ``True`` when the counts satisfy the configured policy.

        Args:
            pass_counts: Number of passing cases per :class:`GroupType`.
            total_counts: Total executed cases per :class:`GroupType`.
        """
        core_passed = core_tests = 0
        non_error_passed = non_error_tests = 0
        total_passed = total_tests = 0

        for group_type in GroupType:
            if group_type == GroupType.CORE:
                core_passed += pass_counts.get(group_type, 0)
                core_tests += total_counts.get(group_type, 0)
            if group_type != GroupType.ERROR:
                non_error_passed += pass_counts.get(group_type, 0)
                non_error_tests += total_counts.get(group_type, 0)
            total_passed += pass_counts.get(group_type, 0)
            total_tests += total_counts.get(group_type, 0)

        match self:
            case PassPolicy.ANY_CASE:
                return total_passed > 0
            case PassPolicy.ALL_CASES:
                return total_passed == total_tests
            case PassPolicy.ALL_NON_ERROR_CASES:
                return non_error_passed == non_error_tests
            case PassPolicy.CORE_CASES:
                return core_passed == core_tests
            case PassPolicy.ANY_CORE_CASES:
                return core_passed > 0
            case PassPolicy.ALL_CORE_CASES:
                return core_passed == core_tests
            case _:
                return True


class GroupReport(BaseModel):
    """Aggregate pass/fail outcome for a single group."""

    duration: float
    results: dict[str, float]
    type: GroupType


class CorrectnessResults(BaseModel):
    """Data aggregator and store for correctness evaluation results.

    This class serves as the primary container for accumulating case reports
    across multiple groups within a correctness evaluation. It provides methods for:

    - **Data accumulation**: Adding group results via
      ``add_group_report()``
    - **Data access**: Querying stored case reports and metadata
    - **Aggregation**: Computing pass/fail statistics via
      ``aggregate_case_reports()``
    - **Persistence**: Saving results and evaluating policies via
      ``save()``

    The class focuses on being a clean data store/aggregator, delegating
    computation logic to helper functions for better testability and
    reusability.
    """

    model_config = ConfigDict(extra="forbid", use_enum_values=True)
    problem_name: str
    problem_version: int
    name: str
    version: int
    timestamp: datetime = Field(default_factory=datetime.now)
    duration: float = Field(default=0.0)
    reports: list[VerifierReport] = Field(default_factory=list)
    group_outcomes: dict[str, GroupReport] = Field(default_factory=dict)
    pass_counts: dict[GroupType, int] = Field(default_factory=Counter)
    total_counts: dict[GroupType, int] = Field(default_factory=Counter)

    # ========================================================================
    # Data Accumulation Methods
    # ========================================================================
    def add_group_report(
        self,
        group_name: str,
        group_type: GroupType,
        duration: float,
        reports: list[VerifierReport],
    ) -> None:
        logger.debug(
            "Adding Group Reports",
            group_name=group_name,
            num_reports=len(reports),
        )
        scores = {}
        num_passed = total = 0
        for result in reports:
            score = result.calculate_score()
            passed = result.did_pass()
            logger.info(
                f"Case '{result.id}'-> {'PASSED' if passed else 'FAILED'}",
                score=f"{score:0.2f}",
            )
            scores[result.id] = score
            self.pass_counts[group_type] += passed
            num_passed += passed
            total += 1
            self.total_counts[group_type] += 1
            self.reports.append(result)

        logger.info(f"'{group_name}' has {num_passed}/{total} passing cases.")
        self.group_outcomes[group_name] = GroupReport(
            duration=duration,
            results=scores,
            type=group_type,
        )

    def save(
        self,
        save_dir: Path,
    ):
        out = self.model_dump(mode="json")
        out.pop("reports")
        reports = [
            {
                "problem": self.problem_name,
                "checkpoint": self.name,
                "version": self.version,
                "problem_version": self.problem_version,
                **report.to_parquet_row(),
            }
            for report in self.reports
        ]

        table = pa.Table.from_pylist(reports)
        pq.write_table(
            table,
            save_dir / VERIFIER_REPORT_FILENAME,
            compression="zstd",
            compression_level=10,
        )

        with (save_dir / EVALUATION_FILENAME).open("w") as f:
            json.dump(out, f, indent=2, sort_keys=True)

    @classmethod
    def from_dir(cls, dir: Path) -> "CorrectnessResults":
        with (dir / EVALUATION_FILENAME).open("r") as f:
            data = json.load(f)

        reports = pq.read_table(dir / VERIFIER_REPORT_FILENAME).to_pylist()
        reports = [
            VerifierReport.from_parquet_row(
                {
                    k: v
                    for k, v in report.items()
                    if k
                    not in {
                        "problem",
                        "checkpoint",
                        "version",
                        "problem_version",
                    }
                }
            )
            for report in reports
        ]
        data["group_outcomes"] = {
            k: GroupReport.model_validate(v)
            for k, v in data["group_outcomes"].items()
        }
        data["pass_counts"] = {
            GroupType(k): v for k, v in data["pass_counts"].items()
        }
        data["total_counts"] = {
            GroupType(k): v for k, v in data["total_counts"].items()
        }
        data["reports"] = reports
        data["timestamp"] = datetime.fromisoformat(data["timestamp"])
        return cls.model_validate(data)
