from __future__ import annotations

import collections.abc
import json
import time
from collections.abc import Callable
from collections.abc import Generator
from collections.abc import Mapping
from dataclasses import dataclass

from slop_code.agent_runner.agent import StreamParser
from slop_code.agent_runner.trajectory import StepRole
from slop_code.agent_runner.trajectory import TrajectoryStep
from slop_code.common.llms import TokenUsage
from slop_code.execution import Session
from slop_code.execution.runtime import RuntimeResult
from slop_code.execution.runtime import SubmissionRuntime
from slop_code.logging import get_logger

log = get_logger(__name__)


__all__ = [
    "AgentCommandResult",
    "StreamParser",
    "format_command",
    "decode_jsonl_stream",
    "run_cli_command",
    "run_streaming_cli_command",
    "shell_preamble",
    "ensure_bun_available",
    "ensure_cli_installed",
    "ensure_node_from_bun",
    "docker_prerequisite_snippet",
]


def shell_preamble() -> str:
    return "set -euo pipefail"


def ensure_bun_available(bun_install_path: str | None = None) -> str:
    bun_install_expr = bun_install_path or '"${HOME:-/tmp}/.bun"'
    return f"""if ! command -v bun >/dev/null 2>&1; then
    export BUN_INSTALL={bun_install_expr}
    export PATH="$BUN_INSTALL/bin:$PATH"
    curl -fsSL https://bun.sh/install | bash
fi
"""


def ensure_cli_installed(binary: str, install_command: str) -> str:
    return f"""if ! command -v {binary} >/dev/null 2>&1; then {install_command}; fi
export PATH="$BUN_INSTALL/bin:$PATH"
"""


def ensure_node_from_bun() -> str:
    return """if ! command -v node >/dev/null 2>&1; then
    if command -v bun >/dev/null 2>&1; then
        mkdir -p "$BUN_INSTALL/bin"
        ln -sf "$(command -v bun)" "$BUN_INSTALL/bin/node"
    fi
fi
"""


def docker_prerequisite_snippet() -> str:
    return """if ! command -v curl >/dev/null 2>&1 || ! command -v unzip >/dev/null 2>&1; then
    if command -v apt-get >/dev/null 2>&1; then
        if ! (apt-get update >/dev/null 2>&1 && apt-get install -y curl unzip >/dev/null 2>&1); then
            echo "error: failed to install curl/unzip via apt-get" >&2
            exit 127
        fi
    elif command -v apk >/dev/null 2>&1; then
        if ! apk add --no-cache curl unzip >/dev/null 2>&1; then
            echo "error: failed to install curl/unzip via apk" >&2
            exit 127
        fi
    else
        echo "error: curl and unzip are required, but no known package manager was found" >&2
        exit 127
    fi
fi
"""


def format_command(command: collections.abc.Sequence[str] | str) -> str:
    if isinstance(command, str):
        return command
    return " ".join(command)


def decode_jsonl_stream(
    buffer: str,
    chunk: str,
) -> tuple[list[dict[str, object]], str]:
    """Return decoded JSON objects and the leftover buffer."""
    if not chunk:
        return [], buffer

    data = buffer + chunk
    lines = data.split("\n")
    buffer = lines.pop()

    parsed: list[dict[str, object]] = []
    for line in lines:
        candidate = line.strip()
        if not candidate:
            continue
        try:
            obj = json.loads(candidate)
        except json.JSONDecodeError:
            log.error("Failed to decode JSON line", line=candidate)
            continue
        if isinstance(obj, dict):
            parsed.append(obj)
    return parsed, buffer


@dataclass(slots=True)
class AgentCommandResult:
    result: RuntimeResult | None
    steps: list[TrajectoryStep]
    usage_totals: dict[str, int]
    stdout: str | None
    stderr: str | None
    had_error: bool = False
    error_message: str | None = None


def run_cli_command(
    session: Session,
    command: str,
    env: Mapping[str, str] | None = None,
    timeout: float | None = None,
) -> AgentCommandResult:
    env = dict(env or {})
    runtime: SubmissionRuntime | None = None
    try:
        runtime = session.spawn()
        result = runtime.execute(
            command=command,
            env=env,
            stdin=None,
            timeout=timeout,
        )
        return AgentCommandResult(
            result=result,
            steps=[],
            usage_totals={},
            stdout=result.stdout or "",
            stderr=result.stderr or "",
        )
    finally:
        if runtime is not None:
            runtime.cleanup()


def run_streaming_cli_command(
    runtime: SubmissionRuntime,
    command: str,
    parser: StreamParser,
    env: Mapping[str, str] | None = None,
    timeout: float | None = None,
) -> Generator[TrajectoryStep, None, RuntimeResult | None]:
    env = dict(env or {})

    run_result: RuntimeResult | None = None
    full_stderr = full_stdout = ""

    for event in runtime.stream(
        command=command,
        env=env,
        stdin=None,
        timeout=timeout,
    ):
        log.debug("Received event", ev=event)
        parser.consume(event)
        produced_steps = tuple(parser.drain_steps())
        yield from produced_steps
        if event.kind == "finished":
            log.debug(
                "RECEIVED FINISH EVENT",
                stdout=run_result.stdout if run_result else None,
                stderr=run_result.stderr if run_result else None,
            )
            # breakpoint()
            run_result = event.result

            break

    finished_steps = tuple(parser.finish())
    yield from finished_steps
    return run_result


def stream_cli_command(
    runtime: SubmissionRuntime,
    command: str,
    parser: Callable[[str], tuple[float | None, TokenUsage | None, dict]],
    env: Mapping[str, str] | None = None,
    timeout: float | None = None,
    *,
    parse_stderr: bool = False,
) -> Generator[
    tuple[float | None, TokenUsage | None, dict] | RuntimeResult | None,
    None,
    None,
]:
    """Stream CLI command output and parse lines through the provided parser.

    Args:
        runtime: The submission runtime to execute the command
        command: The command to execute
        parser: Callable that parses a line and returns (cost, tokens, payload)
        env: Environment variables for the command
        timeout: Optional timeout in seconds
        parse_stderr: If True, also parse stderr lines through the parser
    """
    env = dict(env or {})
    stdout_buffer = ""
    stderr_buffer = ""
    stdout = stderr = ""
    start = time.monotonic()
    result: RuntimeResult | None = None
    for event in runtime.stream(
        command=command, env=env, stdin=None, timeout=timeout
    ):
        if event.kind == "stdout":
            stdout += event.text or ""
            stdout_buffer += event.text or ""
            while "\n" in stdout_buffer:
                line, stdout_buffer = stdout_buffer.split("\n", 1)
                line = line.strip()
                if not line:
                    continue
                yield parser(line)
        elif event.kind == "stderr":
            stderr += event.text or ""
            if parse_stderr:
                stderr_buffer += event.text or ""
                while "\n" in stderr_buffer:
                    line, stderr_buffer = stderr_buffer.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    yield parser(line)
        elif event.kind == "finished":
            result = event.result
            break

    # Flush remaining stdout buffer
    for line in stdout_buffer.split("\n"):
        line = line.strip()
        if not line:
            continue
        yield parser(line)

    # Flush remaining stderr buffer if parsing stderr
    if parse_stderr:
        for line in stderr_buffer.split("\n"):
            line = line.strip()
            if not line:
                continue
            yield parser(line)

    if result is None:
        result = RuntimeResult(
            exit_code=0,
            stdout=stdout,
            stderr=stderr,
            setup_stdout="",
            setup_stderr="",
            elapsed=time.monotonic() - start,
            timed_out=False,
        )
    yield result


def normalize_step_role(step_role: StepRole | str):
    if hasattr(step_role, "value"):
        return step_role.value
    return step_role
