"""Pytest-based checkpoint evaluation."""

from __future__ import annotations

import json
import re
import shlex
from collections import Counter
from pathlib import Path
from typing import Literal, TypedDict

from slop_code.common import WORKSPACE_TEST_DIR
from slop_code.evaluation.config import CheckpointConfig
from slop_code.evaluation.config import ProblemConfig
from slop_code.evaluation.report import CorrectnessResults
from slop_code.evaluation.report import GroupType
from slop_code.evaluation.report import TestResult
from slop_code.execution.assets import resolve_static_assets
from slop_code.execution.models import EnvironmentSpec
from slop_code.execution.session import Session
from slop_code.logging import get_logger

logger = get_logger(__name__)

# Pytest exit codes:
# https://docs.pytest.org/en/stable/reference/exit-codes.html
EXIT_OK = 0  # All tests passed
EXIT_TESTSFAILED = 1  # Some tests failed
EXIT_INTERRUPTED = 2  # Test execution interrupted
EXIT_INTERNALERROR = 3  # Internal error
EXIT_USAGEERROR = 4  # Pytest usage error
EXIT_NOTESTSCOLLECTED = 5  # No tests collected

# Valid exit codes (tests ran, some may have failed)
VALID_EXIT_CODES = {EXIT_OK, EXIT_TESTSFAILED}

# Infrastructure failure codes (pytest itself failed)
INFRA_FAILURE_CODES = {
    EXIT_INTERRUPTED,
    EXIT_INTERNALERROR,
    EXIT_USAGEERROR,
    EXIT_NOTESTSCOLLECTED,
}

MAX_LOG_OUTPUT = 4000
PYTEST_REPORT_REL_PATH = ".scbench/pytest-report.json"
CTRF_REPORT_REL_PATH = ".scbench/ctrf-report.json"

type _JsonObject = dict[str, object]
type _TestStatus = Literal["passed", "failed", "skipped", "error"]


class _CtrfTest(TypedDict, total=False):
    name: str
    status: str
    duration: int | float
    filePath: str
    tags: list[str]
    message: str | None


class _PytestPhaseData(TypedDict, total=False):
    outcome: str
    longreprtext: object
    longrepr: object
    crash: object
    message: object
    duration: int | float


class _PytestReportTest(TypedDict, total=False):
    nodeid: str
    outcome: str
    keywords: list[str]
    setup: _PytestPhaseData
    call: _PytestPhaseData
    teardown: _PytestPhaseData


STATUS_MAP: dict[str, _TestStatus] = {
    "passed": "passed",
    "failed": "failed",
    "skipped": "skipped",
    "error": "error",
    "xfailed": "skipped",
    "xpassed": "passed",
}
COLLECTION_LINE_PATTERN = re.compile(r"collected (\d+) items?")


def _as_dict(value: object) -> _JsonObject | None:
    if isinstance(value, dict):
        return value
    return None


def _as_str_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _truncate_output(text: str | None, limit: int = MAX_LOG_OUTPUT) -> str:
    if text is None:
        return ""
    if len(text) <= limit:
        return text
    return f"{text[:limit]}...<truncated {len(text) - limit} chars>"


class PytestRunner:
    """Execute pytest for one checkpoint and build `CorrectnessResults`."""

    def __init__(
        self,
        problem: ProblemConfig,
        checkpoint: CheckpointConfig,
        environment: EnvironmentSpec,
        submission_path: Path,
    ):
        """Initialize the runner for one checkpoint execution."""
        self.problem = problem
        self.checkpoint = checkpoint
        self.environment = environment
        self.submission_path = submission_path

    def _get_entrypoint_command(self) -> str:
        """Build the command used by tests to execute the submission."""
        return self.environment.get_command(
            self.problem.entry_file,
            is_agent_run=False,  # Evaluation, not agent inference
        )

    def _copy_tests_from_problem(self, workspace_path: Path) -> None:
        """Copy checkpoint-relevant tests into the workspace."""
        import shutil

        workspace_tests = workspace_path / WORKSPACE_TEST_DIR
        problem_tests = self.problem.path / "tests"

        if workspace_tests.exists():
            logger.debug(
                "Workspace already has tests directory",
                workspace_tests=str(workspace_tests),
            )
            return

        if not problem_tests.exists():
            raise RuntimeError(
                f"No tests directory found.\n"
                f"  Checked workspace: {workspace_tests}\n"
                f"  Checked problem: {problem_tests}\n"
                f"Expected tests/ directory with test files in one of these locations."
            )

        # Get test files based on include_prior_tests setting
        checkpoint_files: set[str] = set()
        if self.checkpoint.include_prior_tests:
            # Include all checkpoints 0..N
            for checkpoint_name, _ in self.problem.iterate_checkpoint_items():
                checkpoint_files.add(f"test_{checkpoint_name}.py")
                if checkpoint_name == self.checkpoint.name:
                    break
        else:
            # Only include current checkpoint
            checkpoint_files.add(f"test_{self.checkpoint.name}.py")

        logger.debug(
            "Selectively copying tests from problem directory",
            source=str(problem_tests),
            dest=str(workspace_tests),
            checkpoint_files=list(checkpoint_files),
        )

        # Create tests directory
        workspace_tests.mkdir(parents=True, exist_ok=True)

        # Copy files selectively
        for item in problem_tests.iterdir():
            if item.is_file():
                # Check if this is a checkpoint test file
                is_checkpoint_test = (
                    item.name.startswith("test_")
                    and item.name.endswith(".py")
                    and item.name != "conftest.py"
                )

                if item.name == "conftest.py":
                    # Always copy conftest.py
                    shutil.copy2(item, workspace_tests / item.name)
                    logger.debug(
                        "Copying conftest.py",
                        source=str(item),
                        dest=str(workspace_tests / item.name),
                    )
                elif is_checkpoint_test:
                    # Only copy checkpoint test files for checkpoints 0..N
                    if item.name in checkpoint_files:
                        logger.debug(
                            "Copying checkpoint test file",
                            source=str(item),
                            dest=str(workspace_tests / item.name),
                        )
                        shutil.copy2(item, workspace_tests / item.name)
                else:
                    # Copy non-test files (helpers, __init__.py, etc.)
                    logger.debug(
                        "Copying non-test file",
                        source=str(item),
                        dest=str(workspace_tests / item.name),
                    )
                    shutil.copy2(item, workspace_tests / item.name)
            elif item.is_dir():
                if item.name == "__pycache__":
                    continue
                # Copy subdirectories (e.g., fixtures, data)
                logger.debug(
                    "Copying subdirectory",
                    source=str(item),
                    dest=str(workspace_tests / item.name),
                )
                shutil.copytree(item, workspace_tests / item.name)

    # Built-in markers that are always registered
    # Maps marker name -> (description, GroupType)
    BUILTIN_MARKERS: dict[str, tuple[str, GroupType]] = {
        "error": ("error-handling / edge-case tests", GroupType.ERROR),
        "functionality": (
            "non-core / nice-to-have tests",
            GroupType.FUNCTIONALITY,
        ),
        "regression": (
            "regression tests from prior checkpoints",
            GroupType.REGRESSION,
        ),
    }

    def _generate_pytest_ini(self, workspace_path: Path) -> None:
        """Generate `pytest.ini` for marker registration and test discovery."""
        markers_lines = []
        for marker_name, (marker_desc, _) in self.BUILTIN_MARKERS.items():
            markers_lines.append(f"    {marker_name}: {marker_desc}")
        for marker_name, marker_config in self.problem.markers.items():
            if marker_name not in self.BUILTIN_MARKERS:
                markers_lines.append(
                    f"    {marker_name}: {marker_config.description}"
                )

        markers_section = "\n".join(markers_lines)

        content = f"""[pytest]
testpaths = tests
markers =
{markers_section}
"""

        pytest_ini_path = workspace_path / "pytest.ini"
        pytest_ini_path.write_text(content)

        logger.debug("Generated pytest.ini", path=str(pytest_ini_path))

    # Test dependencies installed via uvx for isolated execution
    TEST_DEPENDENCIES = [
        "pytest",  # Test framework
        "pytest-json-ctrf",  # CTRF JSON report plugin
        "pytest-json-report",  # Detailed failure reports
        "pytest-timeout",  # Session-level timeout support
        "jsonschema",  # JSON schema validation (for test cases)
        "deepdiff",  # Deep comparison utilities
    ]

    def _build_with_flags(self) -> list[str]:
        all_deps = list(self.TEST_DEPENDENCIES) + list(
            self.problem.test_dependencies or []
        )
        return [f"--with={dep}" for dep in all_deps]

    def _build_pytest_base_parts(self) -> list[str]:
        return ["uvx", *self._build_with_flags(), "pytest"]

    def _build_common_pytest_args(self) -> list[str]:
        return [
            f"--entrypoint={shlex.quote(self._get_entrypoint_command())}",
            f"--checkpoint={shlex.quote(self.checkpoint.name)}",
        ]

    def _quote_args(self, extra_args: list[str] | None) -> list[str]:
        return [shlex.quote(arg) for arg in extra_args or []]

    def _build_pytest_command(
        self,
        extra_args: list[str] | None = None,
        timeout: float | None = None,
    ) -> str:
        """Build the pytest execution command."""
        timeout_args = []
        if timeout is not None:
            timeout_args = [f"--timeout={int(timeout)}"]

        cmd_parts = [
            *self._build_pytest_base_parts(),
            *timeout_args,
            *self._build_common_pytest_args(),
            # Limit conftest discovery to the eval test dir so an agent-authored
            # conftest.py at the workspace root can't break collection (SCBench's
            # own conftest lives inside WORKSPACE_TEST_DIR and still loads).
            f"--confcutdir={WORKSPACE_TEST_DIR}",
            f"--ctrf={CTRF_REPORT_REL_PATH}",
            "--json-report",
            f"--json-report-file={PYTEST_REPORT_REL_PATH}",
            "--json-report-omit=traceback",
            "--json-report-omit=streams",
            "--json-report-omit=log",
            "--json-report-omit=collectors",
            "--json-report-omit=warnings",
            "-vv",
            *self._quote_args(extra_args),
            WORKSPACE_TEST_DIR,
        ]

        return " ".join(cmd_parts)

    def _load_json_report(
        self,
        path: Path,
        *,
        missing_level: Literal["debug", "warning", "error"],
        missing_message: str,
        parse_error_message: str,
        read_error_message: str,
    ) -> _JsonObject | None:
        if not path.exists():
            log_method = getattr(logger, missing_level)
            log_method(missing_message, path=str(path))
            return None

        try:
            with path.open() as handle:
                loaded = json.load(handle)
        except json.JSONDecodeError as e:
            logger.error(
                parse_error_message,
                path=str(path),
                error=str(e),
                exc_info=True,
            )
            return None
        except (OSError, UnicodeDecodeError) as e:
            logger.error(
                read_error_message,
                path=str(path),
                error=str(e),
                exc_info=True,
            )
            return None

        data = _as_dict(loaded)
        if data is None:
            logger.error(
                "Report root must be a JSON object",
                path=str(path),
                root_type=type(loaded).__name__,
            )
            return None
        return data

    def _parse_ctrf_tests(self, value: object) -> list[_CtrfTest]:
        if not isinstance(value, list):
            return []

        parsed_tests: list[_CtrfTest] = []
        for entry in value:
            entry_dict = _as_dict(entry)
            if entry_dict is None:
                continue
            parsed_test: _CtrfTest = {}
            for key in ("name", "status", "filePath"):
                field_value = entry_dict.get(key)
                if isinstance(field_value, str):
                    parsed_test[key] = field_value

            duration_value = entry_dict.get("duration")
            if isinstance(duration_value, int | float):
                parsed_test["duration"] = duration_value

            tags = _as_str_list(entry_dict.get("tags"))
            if tags:
                parsed_test["tags"] = tags

            message_value = entry_dict.get("message")
            if isinstance(message_value, str):
                parsed_test["message"] = message_value

            parsed_tests.append(parsed_test)
        return parsed_tests

    def _parse_ctrf_report(
        self, ctrf_path: Path
    ) -> tuple[list[_CtrfTest], _JsonObject | None]:
        """Parse CTRF results generated by `pytest-json-ctrf`."""
        data = self._load_json_report(
            ctrf_path,
            missing_level="error",
            missing_message="CTRF report not found",
            parse_error_message="Failed to parse CTRF report as JSON",
            read_error_message="Failed to read CTRF report",
        )
        if data is None:
            return [], None

        results = _as_dict(data.get("results"))
        tests = self._parse_ctrf_tests(
            results.get("tests") if results else None
        )
        logger.info(
            "Parsed CTRF report",
            test_count=len(tests),
            path=str(ctrf_path),
        )
        return tests, data

    def _infer_checkpoint_from_file(self, file_path: str) -> str:
        """Extract checkpoint name from a test file path."""
        match = re.search(r"test_([^/]+)\.py", file_path)

        if match:
            return match.group(1)

        logger.warning(
            "Could not infer checkpoint from file path, using current checkpoint",
            file_path=file_path,
            fallback=self.checkpoint.name,
        )
        return self.checkpoint.name

    def _determine_group_type(
        self,
        test_checkpoint: str,
        markers: list[str],
        current_checkpoint: str,
    ) -> GroupType:
        """Assign `GroupType` from checkpoint provenance and markers."""
        is_current = test_checkpoint == current_checkpoint

        if not is_current:
            return GroupType.REGRESSION

        if "error" in markers:
            return GroupType.ERROR

        if "regression" in markers:
            return GroupType.REGRESSION

        for marker in markers:
            if marker in self.problem.markers:
                return self.problem.markers[marker].group

        if "functionality" in markers:
            return GroupType.FUNCTIONALITY

        return GroupType.CORE

    def _parse_pytest_json_report(
        self, report_path: Path
    ) -> _JsonObject | None:
        return self._load_json_report(
            report_path,
            missing_level="debug",
            missing_message="Pytest JSON report not found",
            parse_error_message="Failed to parse pytest JSON report as JSON",
            read_error_message="Failed to read pytest JSON report",
        )

    def _stringify_failure_detail(self, value: object) -> str:
        if isinstance(value, str):
            return value

        value_dict = _as_dict(value)
        if value_dict is not None:
            repr_crash = _as_dict(value_dict.get("reprcrash"))
            if repr_crash is not None:
                message = repr_crash.get("message")
                path = repr_crash.get("path")
                lineno = repr_crash.get("lineno")
                parts = []
                if isinstance(path, str) and lineno is not None:
                    parts.append(f"{path}:{lineno}")
                if message:
                    parts.append(str(message))
                if parts:
                    return "\n".join(parts)

        return json.dumps(value, indent=2, ensure_ascii=True)

    def _extract_failure_message(
        self, report_test: _PytestReportTest
    ) -> str | None:
        for phase in ("call", "setup", "teardown"):
            phase_data = report_test.get(phase)
            if not isinstance(phase_data, dict):
                continue
            if phase_data.get("outcome") not in {"failed", "error"}:
                continue
            for key in ("longreprtext", "longrepr", "crash", "message"):
                value = phase_data.get(key)
                if value:
                    return self._stringify_failure_detail(value)
        return None

    def _build_failure_index(self, report_data: _JsonObject) -> dict[str, str]:
        failure_index: dict[str, str] = {}
        for test_entry in self._parse_pytest_report_tests(report_data):
            node_id = test_entry.get("nodeid")
            if not isinstance(node_id, str) or not node_id:
                continue
            message = self._extract_failure_message(test_entry)
            if message:
                failure_index[node_id] = message
        return failure_index

    def _lookup_failure_message(
        self,
        test_data: _CtrfTest,
        failure_index: dict[str, str],
    ) -> str | None:
        name = test_data.get("name") or ""
        file_path = test_data.get("filePath") or ""
        candidates = [name]
        if file_path and name and "::" not in name:
            candidates.append(f"{file_path}::{name}")

        for candidate in candidates:
            if candidate in failure_index:
                return failure_index[candidate]

        if not name:
            return None

        suffix = f"::{name}"
        matches = []
        for node_id, message in failure_index.items():
            if file_path and not node_id.startswith(f"{file_path}::"):
                continue
            if node_id.endswith(suffix):
                matches.append(message)

        if len(matches) == 1:
            return matches[0]
        return None

    def _merge_failure_messages(
        self, existing: str | None, message: str
    ) -> str:
        if not existing:
            return message
        if message in existing:
            return existing
        if existing in message:
            return message
        return f"{existing}\n\n{message}"

    def _augment_ctrf_with_failures(
        self,
        ctrf_tests: list[_CtrfTest],
        failure_index: dict[str, str],
    ) -> None:
        if not failure_index:
            return

        updated = 0
        for test_data in ctrf_tests:
            if test_data.get("status") not in {"failed", "error"}:
                continue
            message = self._lookup_failure_message(test_data, failure_index)
            if not message:
                continue
            test_data["message"] = self._merge_failure_messages(
                test_data.get("message"), message
            )
            updated += 1

        if updated:
            logger.debug("Augmented CTRF failures", count=updated)

    def _convert_ctrf_test_to_result(self, test_data: _CtrfTest) -> TestResult:
        """Convert one CTRF test payload into a `TestResult`."""
        test_name = test_data.get("name", "unknown")
        file_path = test_data.get("filePath", "")
        if not file_path and "::" in test_name:
            file_path = test_name.split("::", 1)[0]

        test_checkpoint = self._infer_checkpoint_from_file(file_path)
        markers = _as_str_list(test_data.get("tags"))
        group_type = self._determine_group_type(
            test_checkpoint=test_checkpoint,
            markers=markers,
            current_checkpoint=self.checkpoint.name,
        )
        status = self._normalize_status(
            test_data.get("status", "error"),
            default="error",
        )
        duration_value = test_data.get("duration", 0)
        duration_ms = (
            float(duration_value)
            if isinstance(duration_value, int | float)
            else 0.0
        )
        message = test_data.get("message")
        failure_message = message if isinstance(message, str) else None

        return TestResult(
            id=test_name,
            checkpoint=test_checkpoint,
            group_type=group_type,
            status=status,
            duration_ms=duration_ms,
            file_path=file_path,
            markers=markers,
            failure_message=failure_message,
        )

    def _convert_pytest_report_test_to_result(
        self, test_data: _PytestReportTest
    ) -> TestResult:
        """Convert one pytest-json-report test payload into a `TestResult`."""
        nodeid = test_data.get("nodeid", "")
        file_path = nodeid.split("::", 1)[0] if "::" in nodeid else ""

        test_checkpoint = self._infer_checkpoint_from_file(file_path)
        keywords = _as_str_list(test_data.get("keywords"))
        known_markers = set(self.BUILTIN_MARKERS.keys())
        known_markers.update(self.problem.markers.keys())
        markers = [kw for kw in keywords if kw in known_markers]
        group_type = self._determine_group_type(
            test_checkpoint=test_checkpoint,
            markers=markers,
            current_checkpoint=self.checkpoint.name,
        )

        status = self._normalize_status(
            test_data.get("outcome", "error"),
            default="error",
        )
        failure_message = self._extract_failure_message(test_data)

        duration_seconds = 0.0
        for phase in ("setup", "call", "teardown"):
            phase_data = test_data.get(phase)
            if isinstance(phase_data, dict):
                phase_duration = phase_data.get("duration")
                if isinstance(phase_duration, int | float):
                    duration_seconds += float(phase_duration)
        duration_ms = duration_seconds * 1000

        test_id = nodeid.split("::", 1)[-1] if "::" in nodeid else nodeid

        return TestResult(
            id=test_id,
            checkpoint=test_checkpoint,
            group_type=group_type,
            status=status,
            duration_ms=duration_ms,
            file_path=file_path,
            markers=markers,
            failure_message=failure_message,
        )

    def _parse_pytest_report_tests(
        self, report_data: _JsonObject | None
    ) -> list[_PytestReportTest]:
        """Normalize pytest-json-report test entries."""
        if report_data is None:
            return []

        tests = report_data.get("tests", [])
        if not isinstance(tests, list):
            return []

        parsed_tests: list[_PytestReportTest] = []
        for entry in tests:
            entry_dict = _as_dict(entry)
            if entry_dict is None:
                continue

            parsed_test: _PytestReportTest = {}
            nodeid = entry_dict.get("nodeid")
            if isinstance(nodeid, str):
                parsed_test["nodeid"] = nodeid

            outcome = entry_dict.get("outcome")
            if isinstance(outcome, str):
                parsed_test["outcome"] = outcome

            keywords = _as_str_list(entry_dict.get("keywords"))
            if keywords:
                parsed_test["keywords"] = keywords

            for phase in ("setup", "call", "teardown"):
                phase_dict = _as_dict(entry_dict.get(phase))
                if phase_dict is None:
                    continue
                phase_data: _PytestPhaseData = {}
                phase_outcome = phase_dict.get("outcome")
                if isinstance(phase_outcome, str):
                    phase_data["outcome"] = phase_outcome
                for key in ("longreprtext", "longrepr", "crash", "message"):
                    if key in phase_dict:
                        phase_data[key] = phase_dict[key]
                phase_duration = phase_dict.get("duration")
                if isinstance(phase_duration, int | float):
                    phase_data["duration"] = phase_duration
                parsed_test[phase] = phase_data

            parsed_tests.append(parsed_test)

        return parsed_tests

    def _normalize_status(
        self, status: str, default: _TestStatus
    ) -> _TestStatus:
        return STATUS_MAP.get(status, default)

    def _check_collection_line(self, stdout: str) -> tuple[bool, int]:
        """Parse pytest stdout for the collected test count."""
        match = COLLECTION_LINE_PATTERN.search(stdout)

        if not match:
            logger.warning("Collection line not found in pytest stdout")
            return False, 0

        num_collected = int(match.group(1))

        if num_collected == 0:
            logger.warning("Pytest collected 0 tests")
            return False, 0

        logger.debug(
            "Pytest collection successful", num_collected=num_collected
        )
        return True, num_collected

    def run(
        self,
        pytest_args: list[str] | None = None,
    ) -> CorrectnessResults:
        """Execute pytest and return aggregated correctness results."""
        logger.info(
            "Starting pytest evaluation",
            problem=self.problem.name,
            checkpoint=self.checkpoint.name,
            environment=self.environment.type,
            submission_path=str(self.submission_path),
        )

        resolved_assets = resolve_static_assets(
            base_path=self.problem.path,
            assets=self.problem.static_assets,
        )

        session = Session.from_environment_spec(
            spec=self.environment,
            base_dir=self.submission_path,
            static_assets=resolved_assets,
            is_agent_infer=False,
        )

        try:
            session.prepare()
            workspace_path = session.workspace.working_dir
            logger.debug("Workspace prepared", path=str(workspace_path))

            logger.debug("Copying tests from problem directory if needed")
            self._copy_tests_from_problem(workspace_path)

            materialized_assets = (
                session.workspace.materialize_static_assets_for_tests()
            )

            asset_env_vars: dict[str, str] = {}
            if materialized_assets:
                assets_dir = Path(WORKSPACE_TEST_DIR, "assets")
                asset_env_vars["SCBENCH_ASSETS_DIR"] = str(assets_dir)
                for name in materialized_assets:
                    env_key = f"SCBENCH_ASSET_{name.upper()}"
                    asset_env_vars[env_key] = str(assets_dir / name)
                logger.info(
                    "Static assets materialized",
                    asset_count=len(materialized_assets),
                    assets=list(materialized_assets.keys()),
                )
                logger.debug(
                    "Static asset env vars",
                    env_vars=asset_env_vars,
                    verbose=True,
                )

            logger.debug("Generating pytest.ini")
            self._generate_pytest_ini(workspace_path)

            full_env = {
                **self.environment.get_full_env(self.checkpoint.env),
                **asset_env_vars,
            }

            pytest_cmd = self._build_pytest_command(
                pytest_args,
                timeout=self.checkpoint.timeout,
            )
            logger.debug("Pytest command", command=pytest_cmd)

            logger.info("Executing pytest")
            runtime = session.exec(command=pytest_cmd)
            try:
                exec_result = runtime.execute(
                    full_env,
                    None,
                    None,
                )
            finally:
                runtime.cleanup()

            logger.info(
                "Pytest execution complete",
                exit_code=exec_result.exit_code,
                duration=exec_result.elapsed,
            )
            if exec_result.exit_code != EXIT_OK:
                logger.debug(
                    "Pytest execution reported failure",
                    exit_code=exec_result.exit_code,
                    stdout=_truncate_output(exec_result.stdout),
                    stderr=_truncate_output(exec_result.stderr),
                )
            else:
                logger.debug(
                    "Pytest stdout/stderr",
                    stdout=_truncate_output(exec_result.stdout),
                    stderr=_truncate_output(exec_result.stderr),
                    verbose=True,
                )

            # Prefer pytest-json-report because it expands parametrized cases.
            pytest_report_path = workspace_path / PYTEST_REPORT_REL_PATH
            pytest_report = self._parse_pytest_json_report(pytest_report_path)
            pytest_report_tests = self._parse_pytest_report_tests(pytest_report)

            ctrf_path = workspace_path / CTRF_REPORT_REL_PATH
            ctrf_tests, ctrf_report = self._parse_ctrf_report(ctrf_path)

            if pytest_report_tests:
                logger.debug(
                    "Using pytest-json-report as primary test source",
                    num_tests=len(pytest_report_tests),
                )
            elif ctrf_tests:
                logger.debug(
                    "Falling back to CTRF report",
                    num_tests=len(ctrf_tests),
                )

            collection_ok, num_collected = self._check_collection_line(
                exec_result.stdout
            )
            if num_collected == 0:
                if pytest_report_tests:
                    num_collected = len(pytest_report_tests)
                elif ctrf_tests:
                    num_collected = len(ctrf_tests)

            infrastructure_failure = (
                exec_result.exit_code in INFRA_FAILURE_CODES
                or exec_result.exit_code not in VALID_EXIT_CODES
                or (
                    not collection_ok
                    and not pytest_report_tests
                    and not ctrf_tests
                )
            )

            if infrastructure_failure:
                logger.error(
                    "Pytest infrastructure failure detected",
                    exit_code=exec_result.exit_code,
                    collected=num_collected,
                    exit_code_meaning=(
                        "EXIT_NOTESTSCOLLECTED"
                        if exec_result.exit_code == 5
                        else "EXIT_INTERRUPTED"
                        if exec_result.exit_code == 2
                        else "EXIT_INTERNALERROR"
                        if exec_result.exit_code == 3
                        else "EXIT_USAGEERROR"
                        if exec_result.exit_code == 4
                        else "UNKNOWN"
                    ),
                )

            results = CorrectnessResults(
                problem_name=self.problem.name,
                problem_version=self.problem.version,
                checkpoint_name=self.checkpoint.name,
                checkpoint_version=self.checkpoint.version,
                duration=exec_result.elapsed,
                entrypoint=self._get_entrypoint_command(),
                pytest_exit_code=exec_result.exit_code,
                pytest_collected=num_collected,
                infrastructure_failure=infrastructure_failure,
                stdout=exec_result.stdout,
                stderr=exec_result.stderr,
                pytest_ctrf_report=ctrf_report,
                pytest_json_report=pytest_report,
            )
            for group_type in GroupType:
                results.total_counts.setdefault(group_type, 0)
                results.pass_counts.setdefault(group_type, 0)

            if pytest_report_tests:
                for report_test in pytest_report_tests:
                    test_result = self._convert_pytest_report_test_to_result(
                        report_test
                    )
                    results.add_test_result(test_result)
            else:
                for ctrf_test in ctrf_tests:
                    test_result = self._convert_ctrf_test_to_result(ctrf_test)
                    results.add_test_result(test_result)

            counted_total = len(results.tests)
            if num_collected > counted_total:
                missing_count = num_collected - counted_total
                if not results.infrastructure_failure:
                    results.infrastructure_failure = True
                    logger.error(
                        "Collected/count mismatch without explicit infra failure",
                        collected=num_collected,
                        counted=counted_total,
                        missing=missing_count,
                        exit_code=exec_result.exit_code,
                    )
                logger.warning(
                    "Collected/results mismatch",
                    collected=num_collected,
                    counted=counted_total,
                    missing=missing_count,
                )

            status_counts = Counter(
                test_result.status for test_result in results.tests
            )
            logger.info(
                "Pytest evaluation complete",
                problem=self.problem.name,
                checkpoint=self.checkpoint.name,
                infrastructure_failure=infrastructure_failure,
                status_counts=dict(status_counts),
            )

            return results

        finally:
            session.cleanup()


def run_checkpoint_pytest(
    submission_path: Path,
    problem: ProblemConfig,
    checkpoint: CheckpointConfig,
    env_spec: EnvironmentSpec,
    pytest_args: list[str] | None = None,
) -> CorrectnessResults:
    """Public entrypoint for checkpoint pytest evaluation."""
    from slop_code.evaluation.collection import run_checkpoint_with_collection

    return run_checkpoint_with_collection(
        submission_path=submission_path,
        problem=problem,
        checkpoint=checkpoint,
        env_spec=env_spec,
        pytest_args=pytest_args,
    )
