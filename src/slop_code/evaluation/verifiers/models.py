from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Generator
from datetime import datetime
from typing import (
    TYPE_CHECKING,
    Protocol,
    runtime_checkable,
)

import deepdiff
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import JsonValue

from slop_code.evaluation.adapters import BaseCase
from slop_code.evaluation.adapters import CaseResult
from slop_code.evaluation.config import GroupType
from slop_code.evaluation.utils import ensure_json_string

# Forward declarations for type hints
if TYPE_CHECKING:
    from slop_code.evaluation.config import CheckpointConfig


class VerificationResult(BaseModel):
    """Core abstraction for verification of a single attribute of a case.

    Attributes:
        diff: The difference between the actual and expected values.
        is_correct: Whether the actual value is correct.
        weight: The weight of the verification result.
    """

    model_config = ConfigDict(extra="forbid")
    diff: JsonValue
    is_correct: bool
    weight: float = Field(default=1.0, gt=0.0)

    def __repr__(self) -> str:
        return f"{'PASSED' if self.is_correct else 'FAILED'}(diff={self.diff}, weight={self.weight})"

    @classmethod
    def create(
        cls,
        diff: deepdiff.DeepDiff | JsonValue,
        is_correct: bool,
        weight: float = 1.0,
    ):
        """Create a VerificationResult from a diff and a weight.

        Args:
            diff: The difference between the actual and expected values.
            is_correct: Whether the actual value is correct.
            weight: The weight of the verification result.

        Returns:
            A VerificationResult object.
        """
        diff_value = diff
        if isinstance(diff, deepdiff.DeepDiff):
            # Convert it back to a dict from json b/c deepdiff does not easily
            # let you make it a dictionary with json compatible types
            diff_value = json.loads(diff.to_json())

        return cls(diff=diff_value, is_correct=is_correct, weight=weight)


def _maybe_json_loads(value: str | None) -> JsonValue:
    if value is None:
        return value
    try:
        return json.loads(value)
    except:  # noqa: E722
        return value


class AttributeResult(BaseModel):
    attribute: str
    actual: JsonValue
    expected: JsonValue
    diff: JsonValue = None
    is_correct: bool | None = None
    weight: float = Field(default=1.0, ge=0.0)

    def __repr__(self) -> str:
        if self.is_correct is None or math.isclose(self.weight, 0.0):
            return self.attribute
        return f"{self.attribute}(correct={self.is_correct})"

    def to_parquet_safe(self) -> dict[str, JsonValue]:
        return {
            "attribute": self.attribute,
            "actual": ensure_json_string(self.actual),
            "expected": ensure_json_string(self.expected),
            "diff": ensure_json_string(self.diff),
            "is_correct": self.is_correct,
            "weight": self.weight,
        }

    @classmethod
    def from_parquet_row(cls, row) -> AttributeResult:
        row["actual"] = _maybe_json_loads(row["actual"])
        row["expected"] = _maybe_json_loads(row["expected"])
        row["diff"] = _maybe_json_loads(row["diff"])
        return cls.model_validate(row)


class VerifierReport(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=True)
    id: str
    group: str
    type: GroupType
    timestamp: datetime = Field(default_factory=datetime.now)
    duration: float
    results: dict[str, AttributeResult] = Field(min_length=1)
    case: dict[str, JsonValue] = Field(default_factory=dict)
    original_checkpoint: str | None = None
    original_group: str | None = None

    def calculate_score(self) -> float:
        """Return the weighted average of verifier scores."""
        total_weight = 0
        weighted_sum = 0
        for v in self.results.values():
            if v.is_correct is None:
                continue
            total_weight += v.weight
            weighted_sum += v.is_correct * v.weight
        return weighted_sum / total_weight

    def __repr__(self) -> str:
        return f"Report-{self.id}(score={self.calculate_score()})"

    def did_pass(self) -> bool:
        return all(
            v.is_correct for v in self.results.values() if v.is_correct is not None
        )

    def get_verified_attributes(self) -> Generator[AttributeResult, None, None]:
        for result in self.results.values():
            if result.is_correct is None:
                continue
            yield result

    def format_result(self) -> dict[str, str]:
        out = {}
        for result in self.get_verified_attributes():
            out[result.attribute] = "P" if result.is_correct else "F"

        return out

    @staticmethod
    def _parquet_safe_case(case: BaseCase) -> dict[str, JsonValue]:
        out = {}
        for k, v in case.model_dump().items():
            if k == "input_files":
                val = json.dumps(
                    [
                        {
                            "path": str(input_file.path),
                            "content": ensure_json_string(input_file.content),
                            "file_type": input_file.file_type.value,
                            "compression": input_file.compression.value,
                        }
                        for input_file in case.input_files
                    ]
                )
            else:
                val = ensure_json_string(v)
            out[k] = val
        out["type"] = "api" if "api" in type(case).__name__.lower() else "cli"
        return out

    def to_parquet_row(self) -> dict:
        out = self.model_dump(mode="json")
        out["results"] = [r.to_parquet_safe() for r in self.results.values()]
        out["case"] = [{"attribute": k, "value": v} for k, v in self.case.items()]
        return out

    @classmethod
    def from_parquet_row(cls, row) -> VerifierReport:
        row["case"] = {
            v["attribute"]: _maybe_json_loads(v["value"]) for v in row.get("case", [])
        }
        row["results"] = {
            v["attribute"]: AttributeResult.from_parquet_row(v) for v in row["results"]
        }
        return cls.model_validate(row)

    @classmethod
    def from_verifier_result(
        cls,
        case: BaseCase,
        duration: float,
        actual_result: CaseResult,
        expected_result: CaseResult,
        raw_results: dict[str, VerificationResult],
    ):
        results = {}
        actual = actual_result.model_dump()
        expected = expected_result.model_dump()
        # TODO: combine this into a single helper function.

        for k in set(actual.keys()).union(set(expected.keys())):
            if k == "files":
                continue
            result = raw_results.get(k)
            results[k] = AttributeResult(
                attribute=k,
                actual=actual.get(k, None),
                expected=expected.get(k, None),
                diff=result.diff if result is not None else None,
                is_correct=result.is_correct if result else None,
                weight=result.weight if result else 0.0,
            )
        for k in set(actual["files"].keys()).union(set(expected["files"].keys())):
            actual_file = actual["files"].get(k, None)
            if isinstance(actual_file, bytes):
                try:
                    actual_file = actual_file.decode("utf-8")
                except:
                    actual_file = f"sha256:{hashlib.sha256(actual_file).hexdigest()}"
            expected_file = expected["files"].get(k, None)
            if isinstance(expected_file, bytes):
                try:
                    expected_file = expected_file.decode("utf-8")
                except:
                    expected_file = (
                        f"sha256:{hashlib.sha256(expected_file).hexdigest()}"
                    )
            result = raw_results.get(f"files-{k}")
            results[f"files-{k}"] = AttributeResult(
                attribute=f"files-{k}",
                actual=actual_file,
                expected=expected_file,
                diff=result.diff if result is not None else None,
                is_correct=result.is_correct if result is not None else None,
                weight=result.weight if result is not None else 0.0,
            )

        return cls(
            id=case.id,
            group=case.group,
            type=case.group_type,
            original_checkpoint=case.original_checkpoint,
            original_group=case.original_group,
            duration=duration,
            results=results,
            case=VerifierReport._parquet_safe_case(case),
        )


# Type alias for verifier result dictionary
VerifierReturnType = dict[str, VerificationResult]


@runtime_checkable
class VerifierProtocol(Protocol):
    """Protocol defining the problem-level verifier class signature.

    Users must implement a class matching this protocol for each problem.
    The class is instantiated once per checkpoint run and receives checkpoint
    context. The __call__ method is invoked for each case with group and case
    context, returning a dictionary of per-attribute verification results.

    The __init__ method receives:
        checkpoint_config: Configuration for the checkpoint

    The __call__ method receives:
        group_name: Name of the group within the checkpoint
        case_name: Identifier for the case being verified
        actual: Raw execution result from the adapter (CaseResult)
        expected: Expected result values as a CaseResult

    Returns:
        Dictionary mapping attribute names to VerifierResult objects.
        Keys must be either:
        - An attribute on the CaseResult (e.g., "output", "status_code")
        - A file verification in the form "files-<filename>"
    """

    def __init__(
        self,
        checkpoint_config: CheckpointConfig,
    ): ...

    def __call__(
        self,
        group_name: str,
        case_name: str,
        actual: CaseResult,
        expected: CaseResult,
    ) -> VerifierReturnType:
        """Execute verification and return per-attribute results."""
        ...
