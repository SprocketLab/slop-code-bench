
from slop_code.evaluation import CheckpointConfig
from slop_code.evaluation import verifier
from slop_code.evaluation.adapters import cli


class Verifier:
    def __init__(self, checkpoint_config: CheckpointConfig) -> None:
        self.checkpoint_config = checkpoint_config

    def verify_output(
        self, actual: cli.CLIResult, expected: cli.CLIResult
    ) -> verifier.VerificationResult:
        actual_config = verifier.parse_yaml_file(
            actual, "result.yaml", allow_missing=True
        )
        expected_config = verifier.parse_yaml_file(expected, "result.yaml")
        return verifier.deepdiff_verify(actual_config, expected_config)

    def __call__(
        self,
        group_name: str,
        case_name: str,
        actual: cli.CLIResult,
        expected: cli.CLIResult,
    ) -> verifier.VerifierReturnType:
        return {
            "status_code": verifier.matches_status_code(
                actual.status_code, expected.status_code, weight=0.25
            ),
            "files-result.yaml": self.verify_output(actual, expected),
        }
