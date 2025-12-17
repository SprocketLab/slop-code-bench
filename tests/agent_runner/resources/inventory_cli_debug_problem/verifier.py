from __future__ import annotations

import json
from json import JSONDecodeError

from slop_code.evaluation import CheckpointConfig
from slop_code.evaluation import verifiers
from slop_code.evaluation.adapters import cli


class Verifier:
    """Verifier for the inventory CLI debug problem."""

    def __init__(self, checkpoint_config: CheckpointConfig) -> None:
        self._checkpoint_config = checkpoint_config

    def __call__(
        self,
        group_name: str,
        case_name: str,
        actual: cli.CLIResult,
        expected: cli.CLIResult,
    ) -> verifiers.VerifierReturnType:
        results: verifiers.VerifierReturnType = {}

        results["status_code"] = verifiers.matches_status_code(
            actual.status_code,
            expected.status_code,
        )

        if expected.output is None:
            return results

        raw_output = actual.output or ""
        try:
            parsed_output = json.loads(raw_output)
        except (JSONDecodeError, TypeError) as exc:
            diff = {
                "error": f"Invalid JSON output: {exc}",
                "output": raw_output,
            }
            results["output"] = verifiers.VerificationResult.create(
                diff=diff,
                is_correct=False,
            )
            return results

        results["output"] = verifiers.deepdiff_verify(
            parsed_output,
            expected.output,
        )
        return results
