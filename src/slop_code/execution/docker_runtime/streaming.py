"""Docker-based streaming runtime for interactive agent execution.

This runtime uses a persistent container with `sleep infinity` and executes
multiple commands via `docker exec` for streaming output.
"""

from __future__ import annotations

import contextlib
import queue
import subprocess
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING

import docker
from docker.errors import APIError
from docker.errors import DockerException

from slop_code.execution.assets import ResolvedStaticAsset
from slop_code.execution.docker_runtime.models import DockerEnvironmentSpec
from slop_code.execution.models import EnvironmentSpec
from slop_code.execution.protocols import StreamingRuntime
from slop_code.execution.runtime import RuntimeEvent
from slop_code.execution.runtime import RuntimeResult
from slop_code.execution.runtime import SolutionRuntimeError
from slop_code.execution.shared import HANDLE_ENTRY_NAME
from slop_code.execution.shared import SPLIT_STRING
from slop_code.execution.shared import write_entry_script
from slop_code.execution.stream_processor import process_stream
from slop_code.logging import get_logger

if TYPE_CHECKING:
    from docker.models.containers import Container as DockerContainer

logger = get_logger(__name__)


class DockerStreamingRuntime(StreamingRuntime):
    """Docker-based streaming runtime for agent execution.

    Uses a persistent container with `sleep infinity` and `docker exec`
    to run multiple commands over the session lifetime.
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
        """Initialize Docker streaming runtime.

        Args:
            spec: Docker environment specification
            working_dir: Directory to mount as workspace in container
            static_assets: Optional static assets to mount in container
            is_evaluation: Whether this is an evaluation context
            ports: Extra ports to use
            mounts: Extra mounts to use
            env_vars: Extra environment variables to use
            setup_command: Setup command to use in addition to the spec commands
            user: User to run the runtime as
            disable_setup: Whether to disable setup commands
            image: Override image name
        """
        logger.debug(
            "Initializing Docker streaming runtime",
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
        """Get Docker client instance."""
        return self._client

    @property
    def container(self) -> DockerContainer:
        """Get the running container."""
        if self._container is None:
            raise SolutionRuntimeError("Container not created")
        return self._container

    @property
    def user(self) -> str | None:
        """Get the user to run commands as."""
        if self._user is not None:
            return self._user
        if self._is_evaluation:
            return self.spec.get_eval_user()
        return self.spec.get_actual_user()

    def _get_setup_commands(self) -> list[str]:
        """Get list of setup commands to run."""
        commands = list(
            self.spec.get_setup_commands(is_evaluation=self._is_evaluation)
        )
        if self._setup_command:
            commands.append(self._setup_command)
        return commands

    def _container_workdir(self) -> str:
        """Get the working directory path inside the container."""
        return str(Path(self.spec.docker.workdir))

    def _merge_env(self, env: dict[str, str]) -> dict[str, str]:
        """Merge environment variables with instance env_vars."""
        merged: dict[str, str] = dict(self._env_vars)
        merged.update(env)
        return merged

    def _resolve_ports(
        self,
        extra_ports: dict[int, int] | None,
    ) -> dict[int, int] | None:
        """Resolve port mappings, handling network mode."""
        if self._network_mode == "host":
            return None
        resolved: dict[int, int] = dict(self._ports)
        if extra_ports:
            resolved.update(extra_ports)
        return resolved or None

    def _build_volumes(self) -> dict[str, dict[str, str]]:
        """Build volume mappings for the container."""
        volumes: dict[str, dict[str, str]] = {}

        # Mount workspace
        if self.spec.docker.mount_workspace:
            volumes[str(self.cwd)] = {
                "bind": self.spec.docker.workdir,
                "mode": "rw",
            }

        # Add spec mounts
        for host_path, container_path in self.spec.docker.extra_mounts.items():
            host = Path(host_path)
            if not host.is_absolute():
                host = (self.cwd / host).resolve()
            if isinstance(container_path, str):
                if container_path.startswith(self.spec.docker.workdir):
                    raise ValueError(
                        f"Container path {container_path} cannot be a "
                        f"subdirectory of {self.spec.docker.workdir}"
                    )
                volumes[str(host)] = {"bind": container_path, "mode": "ro"}
            else:
                volumes[str(host)] = container_path

        # Add runtime mounts
        for host_path, container_mapping in self._mounts.items():
            if isinstance(container_mapping, str):
                volumes[host_path] = {"bind": container_mapping, "mode": "ro"}
            else:
                volumes[host_path] = container_mapping

        # Add static assets
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

        logger.debug(
            "Built container volumes",
            workspace_mounted=self.spec.docker.mount_workspace,
            extra_mounts=len(self.spec.docker.extra_mounts),
            total_volumes=len(volumes),
            verbose=True,
        )
        return volumes

    def _stop_and_remove_container(self, container: DockerContainer) -> None:
        """Stop and remove a Docker container safely."""
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
        kwargs = {
            "volumes": self._build_volumes(),
            "user": self.user,
            "network_mode": self._network_mode,
            "working_dir": self._container_workdir(),
            "ports": self._resolve_ports(None),
        }
        container = self.client.containers.create(
            self._image,
            command="sleep infinity",
            tty=False,
            detach=True,
            stdin_open=False,
            environment=container_env,
            **kwargs,
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
        """Prepare command for execution, writing entry script if needed."""
        if self._disable_setup:
            return command
        write_entry_script(self.cwd, command, self._get_setup_commands())
        return f"bash -l {HANDLE_ENTRY_NAME}"

    def _build_exec_command(
        self,
        command: str,
        env: dict[str, str],
    ) -> list[str]:
        """Build docker exec command arguments."""
        container = self._ensure_container_running()
        exec_env = self.spec.get_full_env(self._merge_env(env))
        args: list[str] = [self.spec.docker.binary, "exec"]
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
    ) -> subprocess.Popen[bytes]:
        """Start a docker exec process."""
        prepared_command = self._prepare_command(command)
        exec_args = self._build_exec_command(prepared_command, env)
        logger.debug(
            "Launching docker exec process",
            command=prepared_command[:200],
            verbose=True,
        )
        try:
            proc = subprocess.Popen(
                exec_args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=None,
            )
        except OSError as exc:
            raise SolutionRuntimeError("Failed to launch docker exec") from exc
        self._active_exec_process = proc
        self._exit_code = None
        return proc

    def _iter_exec_output(
        self, proc: subprocess.Popen[bytes]
    ) -> Iterator[tuple[str | bytes, str | bytes]]:
        """Iterate over docker exec output, yielding (stdout, stderr) tuples."""
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

    def _stop_active_exec_process(self) -> None:
        """Stop the active docker exec process if running."""
        proc = self._active_exec_process
        if proc is None:
            return
        logger.debug("Stopping active docker exec process", verbose=True)
        with contextlib.suppress(Exception):
            proc.kill()
        with contextlib.suppress(Exception):
            proc.wait(timeout=5)
        self._active_exec_process = None

    def stream(
        self,
        command: str,
        env: dict[str, str],
        timeout: float | None,
    ) -> Iterator[RuntimeEvent]:
        """Stream execution of a command in the container.

        Args:
            command: Command to execute
            env: Environment variables
            timeout: Optional timeout in seconds

        Yields:
            RuntimeEvent objects for stdout, stderr, and completion
        """
        proc = self._start_exec_process(command, env)
        stream = self._iter_exec_output(proc)

        logger.debug(
            "Starting containerized execution",
            command=command[:200],
            timeout=timeout,
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

    def poll(self) -> int | None:
        """Check if the process is still running."""
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
        logger.debug("Cleaning up Docker streaming runtime", verbose=True)
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
        **_runtime_kwargs,
    ) -> DockerStreamingRuntime:
        """Spawn a new Docker streaming runtime instance.

        Args:
            environment: Environment specification
            working_dir: Working directory path
            static_assets: Optional static assets to mount
            ports: Optional port mappings
            mounts: Optional volume mounts
            env_vars: Optional environment variables
            setup_command: Optional setup command
            image: Optional image name override
            user: Optional user to run as
            is_evaluation: Whether this is an evaluation context
            disable_setup: Whether to disable setup commands

        Returns:
            New DockerStreamingRuntime instance

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
