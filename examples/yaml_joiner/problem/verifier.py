from slop_code.evaluation import CheckpointConfig
from slop_code.evaluation.adapters import cli
from slop_code.evaluation.verifiers import VerificationResult
from slop_code.evaluation.verifiers import VerifierReturnType
from slop_code.evaluation.verifiers import parsers
from slop_code.evaluation.verifiers import verifiers


class Verifier:
    def __init__(self, checkpoint_config: CheckpointConfig) -> None:
        self.checkpoint_config = checkpoint_config

    def verify_output(
        self, actual: cli.CLIResult, expected: cli.CLIResult
    ) -> VerificationResult:
        actual_config = parsers.parse_yaml_file(
            actual, "result.yaml", allow_missing=True
        )
        return verifiers.deepdiff_verify(actual_config, expected.files["result.yaml"])

    def __call__(
        self,
        group_name: str,
        case_name: str,
        actual: cli.CLIResult,
        expected: cli.CLIResult,
    ) -> VerifierReturnType:
        if "error" in group_name:
            expected_stderr = parsers.ensure_expected_is_not_none(expected.stderr)

            return {
                "stderr": verifiers.matches_regex(actual.stderr, expected_stderr),
                "status_code": verifiers.matches_status_code(
                    actual.status_code, expected.status_code
                ),
            }

        return {
            "status_code": verifiers.matches_status_code(
                actual.status_code, expected.status_code, weight=0.25
            ),
            "files-result.yaml": self.verify_output(actual, expected),
        }
