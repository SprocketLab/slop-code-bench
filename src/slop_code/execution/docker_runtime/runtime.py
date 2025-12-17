"""Docker-based runtime implementation for executing submission code."""

from __future__ import annotations

import contextlib
import queue
import subprocess
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import docker
from docker.errors import APIError
from docker.errors import DockerException

from slop_code.execution.assets import ResolvedStaticAsset
from slop_code.execution.docker_runtime.models import DockerEnvironmentSpec
from slop_code.execution.models import EnvironmentSpec
from slop_code.execution.runtime import RuntimeEvent
from slop_code.execution.runtime import RuntimeResult
from slop_code.execution.runtime import SolutionRuntimeError
from slop_code.execution.runtime import SubmissionRuntime
from slop_code.execution.runtime import register_runtime
from slop_code.execution.stream_processor import process_stream
from slop_code.logging import get_logger

if TYPE_CHECKING:
    from docker.models.containers import Container as DockerContainer

logger = get_logger(__name__)


HANDLE_ENTRY_NAME = "HANDLE_ENTRY.sh"

SPLIT_STRING = "_____STARTING COMMAND_____"
HANDLE_ENTRY_TEMPLATE = f"""#!/bin/sh
{{setup_commands}}
echo "\n\n{SPLIT_STRING}\n" >&2
echo "\n\n{SPLIT_STRING}\n"
{{command}}
"""


@register_runtime("docker")
class DockerRuntime(SubmissionRuntime):
    """Docker-based runtime implementation for executing submission code.

    This runtime manages Docker containers to execute code in isolated environments
    with proper resource management, streaming I/O, and cleanup handling.
    """

    def __init__(
        self,
        spec: DockerEnvironmentSpec,
        working_dir: Path,
        static_assets: dict[str, ResolvedStaticAsset],
        is_evaluation: bool,
        ports: dict[int, int],
        mounts: dict[str, dict[str, str] | str],
        env_vars: dict[str, str],
        setup_command: str | None,
        user: str | None = None,
        disable_setup: bool = False,
        image: str | None = None,
    ) -> None:
        """Initialize Docker runtime.

        Args:
            spec: Docker environment specification
            working_dir: Directory to mount as workspace in container
            static_assets: Optional static assets to mount in container
            is_evaluation: Whether this is an evaluation context
            ports: Extra ports to use
            mounts: Extra mounts to use
            env_vars: Extra environment variables to use
            setup_command: Setup command to use in addition to the spec commands.
            user: User to run the runtime as.
        """
        logger.debug(
            "Initializing Docker runtime",
            working_dir=working_dir,
            image=spec.docker.image,
            static_assets=list((static_assets or {}).keys()),
            is_evaluation=is_evaluation,
            verbose=True,
        )
        self.spec = spec
        self.cwd = working_dir
        self._client = docker.from_env()
        self._container: DockerContainer | None = None
        self._exit_code: int | None = None
        self._static_assets = static_assets or {}
        self._is_evaluation = is_evaluation
        self._setup_command = setup_command
        self._ports = dict(ports or {})
        self._mounts = dict(mounts or {})
        self._env_vars = dict(env_vars or {})
        self._user = user
        self._image = image or spec.get_base_image()
        self._disable_setup = disable_setup
        self._network_mode = self.spec.effective_network_mode()
        self._active_exec_process: subprocess.Popen[bytes] | None = None

    @property
    def client(self) -> docker.DockerClient:
        """Get or create Docker client instance."""
        if self._client is None:
            logger.debug("Creating Docker client", verbose=True)

        return cast("docker.DockerClient", self._client)

    @property
    def container(self) -> DockerContainer:
        if self._container is None:
            raise SolutionRuntimeError("Container not created")
        return self._container

    @property
    def user(self) -> str | None:
        if self._user is not None:
            return self._user
        if self._is_evaluation:
            return self.spec.get_eval_user()
        return self.spec.get_actual_user()

    def _format_setup_section(self) -> str:
        """Format setup commands for entry script.

        Returns:
            Formatted setup commands string or empty string if no commands
        """
        commands = list(
            self.spec.get_setup_commands(is_evaluation=self._is_evaluation)
        )
        if self._setup_command:
            commands.append(self._setup_command)
        if not commands:
            logger.debug("No setup commands to format", verbose=True)
            return ""
        joined = "\n".join(commands)
        logger.debug(
            "Formatted setup commands",
            num_commands=len(commands),
            verbose=True,
        )
        return f"{joined}\n\n"

    def _write_entry_script(self, command: str) -> Path:
        """Write the entry script that will be executed in the container.

        Args:
            command: Command to execute in the container

        Returns:
            Path to the written entry script
        """
        script_path = self.cwd / HANDLE_ENTRY_NAME
        logger.debug(
            "Writing entry script",
            script_path=script_path,
            verbose=True,
        )
        script_path.write_text(
            HANDLE_ENTRY_TEMPLATE.format(
                setup_commands=self._format_setup_section(),
                command=command,
            ),
            encoding="utf-8",
        )
        script_path.chmod(0o755)
        return script_path

    def _container_workdir(self) -> str:
        """Get the working directory path inside the container.

        Returns:
            Container working directory as string
        """
        return str(Path(self.spec.docker.workdir))

    def _merge_env(self, env: dict[str, str]) -> dict[str, str]:
        merged: dict[str, str] = dict(self._env_vars)
        merged.update(env)
        return merged

    def _resolve_ports(
        self,
        extra_ports: dict[int, int] | None,
    ) -> dict[int, int] | None:
        if self._network_mode == "host":
            return None
        resolved: dict[int, int] = dict(self._ports)
        if extra_ports:
            resolved.update(extra_ports)
        return resolved or None

    def _container_common_kwargs(
        self, ports: dict[int, int] | None = None
    ) -> dict[str, Any]:
        """Build common kwargs for container creation.

        Args:
            env: Environment variables for the container
            ports: Optional port mappings

        Returns:
            Dictionary of container creation arguments
        """
        kwargs = {
            "volumes": self._build_volumes(),
            "user": self.user,
            "network_mode": self._network_mode,
            "working_dir": self._container_workdir(),
        }
        resolved_ports = self._resolve_ports(ports)

        logger.debug(
            "Built container kwargs",
            network_mode=self._network_mode,
            user=kwargs["user"],
            has_ports=bool(resolved_ports),
            verbose=True,
        )
        kwargs["ports"] = resolved_ports
        return kwargs

    def _stop_and_remove_container(self, container: DockerContainer) -> None:
        """Stop and remove a Docker container safely.

        Args:
            container: Docker container instance to clean up
        """
        logger.debug(
            "Stopping and removing container",
            container_id=container.id[:12],
            verbose=True,
        )
        try:
            container.stop(timeout=1)
        except (DockerException, APIError):
            logger.warning(
                "Failed to stop container",
                container_id=container.id[:12],
                verbose=True,
            )
            container.kill()
        with contextlib.suppress(DockerException, APIError):
            container.remove(force=True)

    # --- container lifecycle helpers ---
    def _maybe_mount_workspace(
        self,
        volumes: dict[str, dict[str, str]],
    ) -> None:
        if not self.spec.docker.mount_workspace:
            return
        volumes[str(self.cwd)] = {
            "bind": self.spec.docker.workdir,
            "mode": "rw",
        }

    def _resolve_host_path(self, host_path: str) -> Path:
        host = Path(host_path)
        if host.is_absolute():
            return host
        return (self.cwd / host).resolve()

    def _add_spec_mounts(
        self,
        volumes: dict[str, dict[str, str]],
    ) -> None:
        for host_path, container_path in self.spec.docker.extra_mounts.items():
            host = self._resolve_host_path(host_path)
            if isinstance(container_path, str):
                if container_path.startswith(self.spec.docker.workdir):
                    raise ValueError(
                        f"Container path {container_path} cannot be a subdirectory of {self.spec.docker.workdir}"
                    )
                volumes[str(host)] = {"bind": container_path, "mode": "ro"}
                continue
            volumes[str(host)] = container_path

    def _add_runtime_mounts(
        self,
        volumes: dict[str, dict[str, str]],
    ) -> None:
        for host_path, container_mapping in self._mounts.items():
            if isinstance(container_mapping, str):
                volumes[host_path] = {"bind": container_mapping, "mode": "ro"}
                continue
            volumes[host_path] = container_mapping

    def _add_static_assets(
        self,
        volumes: dict[str, dict[str, str]],
    ) -> int:
        asset_count = 0
        for asset in self._static_assets.values():
            absolute_path = getattr(asset, "absolute_path", None)
            save_path = getattr(asset, "save_path", None)
            if absolute_path is None or save_path is None:
                continue
            container_target = (Path("/static") / save_path).as_posix()
            volumes[str(absolute_path)] = {
                "bind": container_target,
                "mode": "ro",
            }
            asset_count += 1
        return asset_count

    def _build_volumes(self) -> dict[str, dict[str, str]]:
        """Build volume mappings for the container.

        Returns:
            Dictionary mapping host paths to container volume specifications
        """
        volumes: dict[str, dict[str, str]] = {}
        self._maybe_mount_workspace(volumes)
        self._add_spec_mounts(volumes)
        self._add_runtime_mounts(volumes)
        static_asset_count = self._add_static_assets(volumes)

        logger.debug(
            "Built container volumes",
            workspace_mounted=self.spec.docker.mount_workspace,
            extra_mounts=len(self.spec.docker.extra_mounts),
            static_assets=static_asset_count,
            total_volumes=len(volumes),
            verbose=True,
        )
        return volumes

    def _ensure_container_running(self) -> DockerContainer:
        """Ensure the long-lived container exists and is running."""
        container = self._container
        if container is not None:
            try:
                container.reload()
            except (DockerException, APIError):
                logger.warning(
                    "Failed to reload container; recreating",
                    container_id=container.id[:12],
                    verbose=True,
                )
            else:
                state = container.attrs.get("State", {})
                if state.get("Status") == "running":
                    return container
            logger.debug("Recreating Docker container", verbose=True)
            self._stop_and_remove_container(container)
            self._container = None
        logger.debug("Creating base container")
        return self._create_base_container()

    def _create_base_container(self) -> DockerContainer:
        """Create and start the base container that runs sleep infinity."""
        logger.debug(
            "Creating base Docker container",
            image=self._image,
            verbose=True,
        )
        container_env = self.spec.get_full_env(self._merge_env({}))
        container = self.client.containers.create(  # type: ignore
            self._image,
            command="sleep infinity",
            tty=False,
            detach=True,
            stdin_open=False,
            environment=container_env,
            **self._container_common_kwargs(),
        )
        if container is None:
            raise SolutionRuntimeError("Failed to create container")
        container.start()
        self._container = container
        logger.debug(
            "Started Docker container",
            container_id=container.id[:12],
            verbose=True,
        )
        return container

    def _prepare_command(self, command: str) -> str:
        if self._disable_setup:
            return command
        self._write_entry_script(command)
        return f"bash -l {HANDLE_ENTRY_NAME}"

    def _build_exec_command(
        self,
        command: str,
        env: dict[str, str],
        *,
        needs_stdin: bool,
    ) -> list[str]:
        """Compose the docker exec command for the provided payload."""
        container = self._ensure_container_running()
        exec_env = self.spec.get_full_env(self._merge_env(env))
        args: list[str] = [self.spec.docker.binary, "exec"]
        if needs_stdin:
            args.append("-i")
        args.extend(["--workdir", self._container_workdir()])
        if self.user:
            args.extend(["--user", self.user])
        for key, value in exec_env.items():
            args.extend(["--env", f"{key}={value}"])
        args.append(container.id)
        args.extend(["/bin/sh", "-c", command])
        logger.debug(
            "Built docker exec command",
            args=args,
            verbose=True,
        )
        return args

    def _start_exec_process(
        self,
        command: str,
        env: dict[str, str],
        *,
        needs_stdin: bool,
    ) -> subprocess.Popen[bytes]:
        prepared_command = self._prepare_command(command)
        exec_args = self._build_exec_command(
            prepared_command,
            env,
            needs_stdin=needs_stdin,
        )
        logger.debug(
            "Launching docker exec process",
            command=prepared_command[:200],
            needs_stdin=needs_stdin,
            verbose=True,
        )
        try:
            proc = subprocess.Popen(
                exec_args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE if needs_stdin else None,
            )
        except OSError as exc:  # pragma: no cover - defensive
            raise SolutionRuntimeError("Failed to launch docker exec") from exc
        self._active_exec_process = proc
        self._exit_code = None
        return proc

    def _iter_exec_output(
        self, proc: subprocess.Popen[bytes]
    ) -> Iterator[tuple[str | bytes, str | bytes]]:
        stdout = proc.stdout
        stderr = proc.stderr
        if stdout is None or stderr is None:
            raise SolutionRuntimeError("docker exec process missing pipes")

        output_queue: queue.Queue[tuple[str, bytes | None]] = queue.Queue()

        def pump(pipe, label: str) -> None:
            read_fn = getattr(pipe, "read1", None)
            if read_fn is None:
                read_fn = pipe.read
            try:
                while True:
                    chunk = read_fn(4096)
                    if not chunk:
                        break
                    output_queue.put((label, chunk))
            finally:
                output_queue.put((label, None))

        stdout_thread = threading.Thread(
            target=pump,
            args=(stdout, "stdout"),
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=pump,
            args=(stderr, "stderr"),
            daemon=True,
        )
        stdout_thread.start()
        stderr_thread.start()

        finished_streams = 0
        while finished_streams < 2:
            label, payload = output_queue.get()
            if payload is None:
                finished_streams += 1
                continue
            if label == "stdout":
                yield payload, b""
            else:
                yield b"", payload

        stdout_thread.join(timeout=0.1)
        stderr_thread.join(timeout=0.1)

    def _write_exec_stdin(
        self,
        proc: subprocess.Popen[bytes],
        stdin: str | list[str],
    ) -> None:
        payloads = stdin if isinstance(stdin, list) else [stdin]
        pipe = proc.stdin
        if pipe is None:
            raise SolutionRuntimeError("stdin requested but pipe is missing")

        total = 0
        try:
            for payload in payloads:
                data = payload.encode("utf-8")
                pipe.write(data)
                total += len(data)
            if payloads:
                pipe.flush()
        except OSError as exc:  # pragma: no cover - defensive
            raise SolutionRuntimeError(
                "Failed to write stdin to docker exec"
            ) from exc
        finally:
            with contextlib.suppress(Exception):
                pipe.close()
            # Avoid communicate() flushing an already-closed stdin pipe.
            proc.stdin = None
        logger.debug("Sent stdin payload", bytes_written=total, verbose=True)

    def _stop_active_exec_process(self) -> None:
        proc = self._active_exec_process
        if proc is None:
            return
        logger.debug("Stopping active docker exec process", verbose=True)
        with contextlib.suppress(Exception):
            proc.kill()
        with contextlib.suppress(Exception):
            proc.wait(timeout=5)
        self._active_exec_process = None

    # --- Implementation of SubmissionRuntime methods ---

    def stream(
        self,
        command: str,
        env: dict[str, str],
        stdin: str | list[str] | None,
        timeout: float | None,
    ) -> Iterator[RuntimeEvent]:
        """Stream execution of a command in the container.

        Args:
            command: Command to execute
            env: Environment variables
            stdin: Optional stdin input
            timeout: Optional timeout in seconds

        Yields:
            RuntimeEvent objects for stdout, stderr, and completion
        """
        if stdin is not None:
            raise ValueError("stdin is not supported for stream()")

        proc = self._start_exec_process(
            command,
            env,
            needs_stdin=False,
        )
        stream = self._iter_exec_output(proc)

        logger.debug(
            "Starting containerized execution",
            command=command[:200],
            timeout=timeout,
            has_stdin=stdin is not None,
            verbose=True,
        )

        result = yield from process_stream(
            stream,
            timeout,
            lambda: self.poll(),
            yield_only_after=SPLIT_STRING if not self._disable_setup else None,
        )

        if result.timed_out:
            self._stop_active_exec_process()

        if self._active_exec_process is proc:
            self._active_exec_process = None

        self._exit_code = result.exit_code

        logger.debug(
            "Container execution completed",
            exit_code=self._exit_code,
            verbose=True,
        )
        # Yield finished event with correct exit code
        final_result = RuntimeResult(
            exit_code=result.exit_code,
            stdout=result.stdout,
            stderr=result.stderr,
            setup_stdout=result.setup_stdout,
            setup_stderr=result.setup_stderr,
            elapsed=result.elapsed,
            timed_out=result.timed_out,
        )
        yield RuntimeEvent(kind="finished", result=final_result)

    def execute(
        self,
        command: str,
        env: dict[str, str],
        stdin: str | list[str] | None,
        timeout: float | None,
    ) -> RuntimeResult:
        """Execute a command and return the result.

        Args:
            command: Command to execute
            env: Environment variables
            stdin: Optional stdin input
            timeout: Optional timeout in seconds

        Returns:
            RuntimeResult with execution details
        """
        proc = self._start_exec_process(
            command,
            env,
            needs_stdin=stdin is not None,
        )
        if stdin is not None:
            self._write_exec_stdin(proc, stdin)
        elif proc.stdin is not None:
            proc.stdin.close()

        timed_out = False
        start_time = time.time()
        try:
            stdout_bytes, stderr_bytes = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            self._stop_active_exec_process()
            stdout_bytes, stderr_bytes = proc.communicate()
        finally:
            if self._active_exec_process is proc:
                self._active_exec_process = None

            if proc.stdin:
                proc.stdin.close()

        exit_code = proc.returncode if proc.returncode is not None else -1
        elapsed = time.time() - start_time
        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")
        try:
            *setup_stdout, stdout = stdout.split(SPLIT_STRING)
            setup_stdout = "\n".join(setup_stdout)
        except ValueError:
            setup_stdout = ""
        try:
            *setup_stderr, stderr = stderr.split(SPLIT_STRING)
            setup_stderr = "\n".join(setup_stderr)
        except ValueError:
            setup_stderr = ""
        self._exit_code = exit_code
        return RuntimeResult(
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            setup_stdout=setup_stdout,
            setup_stderr=setup_stderr,
            elapsed=elapsed,
            timed_out=timed_out,
        )

    def poll(self) -> int | None:
        """Check if the container is still running.

        Returns:
            Exit code if container has finished, None if still running
        """
        proc = self._active_exec_process
        if proc is None:
            return self._exit_code
        exit_code = proc.poll()
        if exit_code is None:
            return None
        self._active_exec_process = None
        self._exit_code = exit_code
        logger.debug("docker exec finished", exit_code=exit_code, verbose=True)
        return exit_code

    def kill(self) -> None:
        """Kill the running container."""
        self._stop_active_exec_process()
        container = self._container
        if container is None:
            return
        logger.debug(
            "Killing container",
            container_id=container.id[:12],
            verbose=True,
        )
        self._stop_and_remove_container(container)
        self._container = None

    def cleanup(self) -> None:
        """Clean up all resources used by the runtime."""
        logger.debug("Cleaning up Docker runtime resources", verbose=True)
        self.kill()
        if self._client is not None:
            with contextlib.suppress(Exception):
                self._client.close()
            self._client = None

    @classmethod
    def spawn(
        cls,
        environment: EnvironmentSpec,
        working_dir: Path,
        static_assets: dict[str, ResolvedStaticAsset] | None = None,
        ports: dict[int, int] | None = None,
        mounts: dict[str, dict[str, str] | str] | None = None,
        env_vars: dict[str, str] | None = None,
        setup_command: str | None = None,
        image: str | None = None,
        user: str | None = None,
        *,
        is_evaluation: bool = False,
        disable_setup: bool = False,
    ) -> DockerRuntime:
        """Spawn a new Docker runtime instance.

        Args:
            spec: Launch specification containing environment and settings

        Returns:
            New DockerRuntime instance

        Raises:
            ValueError: If environment spec is not for Docker
        """
        if not isinstance(environment, DockerEnvironmentSpec):
            raise ValueError("Invalid environment spec for docker runtime")
        return cls(
            working_dir=working_dir,
            spec=environment,
            static_assets=static_assets or {},
            ports=ports or {},
            mounts=mounts or {},
            env_vars=env_vars or {},
            setup_command=setup_command,
            is_evaluation=is_evaluation,
            image=image,
            disable_setup=disable_setup,
            user=user,
        )
