"""Docker-based execution runtime for one-shot command execution.

This runtime uses `docker run --rm` for single-shot command execution
with buffered output, suitable for evaluation and testing.
"""

from __future__ import annotations

import contextlib
import subprocess
import time
from pathlib import Path

import docker

from slop_code.execution.assets import ResolvedStaticAsset
from slop_code.execution.docker_runtime.models import DockerEnvironmentSpec
from slop_code.execution.models import EnvironmentSpec
from slop_code.execution.protocols import ExecRuntime
from slop_code.execution.runtime import RuntimeResult
from slop_code.execution.runtime import SolutionRuntimeError
from slop_code.execution.shared import HANDLE_ENTRY_NAME
from slop_code.execution.shared import split_setup_output
from slop_code.execution.shared import write_entry_script
from slop_code.logging import get_logger

logger = get_logger(__name__)


class DockerExecRuntime(ExecRuntime):
    """Docker-based execution runtime for evaluation.

    Uses `docker run --rm` for single-shot command execution.
    The command is set at construction and cannot be changed.
    """

    def __init__(
        self,
        spec: DockerEnvironmentSpec,
        working_dir: Path,
        command: str,
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
        """Initialize Docker exec runtime.

        Args:
            spec: Docker environment specification
            working_dir: Directory to mount as workspace in container
            command: Command to execute (immutable)
            static_assets: Optional static assets to mount in container
            is_evaluation: Whether this is an evaluation context
            ports: Extra ports to use
            mounts: Extra mounts to use
            env_vars: Extra environment variables to use
            setup_command: Setup command to use in addition to spec commands
            user: User to run the runtime as
            disable_setup: Whether to disable setup commands
            image: Override image name
        """
        logger.debug(
            "Initializing Docker exec runtime",
            working_dir=working_dir,
            command=command[:100],
            image=spec.docker.image,
            verbose=True,
        )
        self.spec = spec
        self.cwd = working_dir
        self._command = command
        self._client = docker.from_env()
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
        self._process: subprocess.Popen[bytes] | None = None

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

    def _resolve_ports(self) -> dict[int, int] | None:
        """Resolve port mappings, handling network mode."""
        if self._network_mode == "host":
            return None
        return self._ports or None

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

        return volumes

    def _build_docker_run_command(self, env: dict[str, str]) -> list[str]:
        """Build docker run command for single-shot execution."""
        # Write entry script with setup commands + actual command
        if not self._disable_setup:
            write_entry_script(
                self.cwd, self._command, self._get_setup_commands()
            )
            prepared_command = f"bash -l {HANDLE_ENTRY_NAME}"
        else:
            prepared_command = self._command

        full_env = self.spec.get_full_env(self._merge_env(env))
        args: list[str] = [self.spec.docker.binary, "run", "--rm"]

        # Add volumes
        for host_path, container_spec in self._build_volumes().items():
            bind = container_spec["bind"]
            mode = container_spec.get("mode", "rw")
            args.extend(["-v", f"{host_path}:{bind}:{mode}"])

        # Add user
        if self.user:
            args.extend(["--user", self.user])

        # Add network mode
        args.extend(["--network", self._network_mode])

        # Add working directory
        args.extend(["--workdir", self._container_workdir()])

        # Add environment variables
        for key, value in full_env.items():
            args.extend(["-e", f"{key}={value}"])

        # Add ports (only for bridge networking)
        resolved_ports = self._resolve_ports()
        if resolved_ports:
            for host_port, container_port in resolved_ports.items():
                args.extend(["-p", f"{host_port}:{container_port}"])

        # Add image
        args.append(self._image)

        # Add shell command
        args.extend(["/bin/sh", "-c", prepared_command])

        logger.debug(
            "Built docker run command",
            args=args,
            verbose=True,
        )
        return args

    def _write_stdin(
        self,
        proc: subprocess.Popen[bytes],
        stdin: str | list[str],
    ) -> None:
        """Write stdin data to process."""
        payloads = stdin if isinstance(stdin, list) else [stdin]
        pipe = proc.stdin
        if pipe is None:
            raise SolutionRuntimeError("stdin requested but pipe is missing")

        try:
            for payload in payloads:
                data = payload.encode("utf-8")
                pipe.write(data)
            if payloads:
                pipe.flush()
        except OSError as exc:
            raise SolutionRuntimeError(
                "Failed to write stdin to docker run"
            ) from exc
        finally:
            with contextlib.suppress(Exception):
                pipe.close()
            proc.stdin = None

    def execute(
        self,
        env: dict[str, str],
        stdin: str | list[str] | None,
        timeout: float | None,
    ) -> RuntimeResult:
        """Execute the command via docker run --rm.

        Args:
            env: Environment variables
            stdin: Optional stdin input
            timeout: Optional timeout in seconds

        Returns:
            RuntimeResult with execution details
        """
        run_args = self._build_docker_run_command(env)

        # Add -i flag for stdin support (must be before the image name)
        if stdin is not None:
            # Find the image position and insert -i before it
            image_idx = run_args.index(self._image)
            run_args.insert(image_idx, "-i")

        logger.debug(
            "Executing single-shot docker run",
            command=self._command[:200],
            timeout=timeout,
            has_stdin=stdin is not None,
            verbose=True,
        )

        start_time = time.time()
        timed_out = False

        try:
            proc = subprocess.Popen(
                run_args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE if stdin is not None else None,
            )
            self._process = proc
        except OSError as exc:
            raise SolutionRuntimeError("Failed to launch docker run") from exc

        try:
            # Handle stdin if provided
            if stdin is not None:
                self._write_stdin(proc, stdin)
            elif proc.stdin is not None:
                proc.stdin.close()

            # Wait for completion
            try:
                stdout_bytes, stderr_bytes = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                proc.kill()
                stdout_bytes, stderr_bytes = proc.communicate()
        finally:
            self._process = None
            if proc.stdin:
                with contextlib.suppress(Exception):
                    proc.stdin.close()

        elapsed = time.time() - start_time
        exit_code = proc.returncode if proc.returncode is not None else -1

        # Parse output (split setup from command output)
        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")

        if self._disable_setup:
            setup_stdout = ""
            setup_stderr = ""
        else:
            setup_stdout, stdout, setup_stderr, stderr = split_setup_output(
                stdout, stderr
            )

        self._exit_code = exit_code

        logger.debug(
            "Single-shot docker run completed",
            exit_code=exit_code,
            elapsed=elapsed,
            timed_out=timed_out,
            verbose=True,
        )

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
        """Check if the process is still running."""
        proc = self._process
        if proc is not None:
            exit_code = proc.poll()
            if exit_code is not None:
                self._process = None
                self._exit_code = exit_code
            return exit_code
        return self._exit_code

    def kill(self) -> None:
        """Kill the running process."""
        proc = self._process
        if proc is not None:
            with contextlib.suppress(Exception):
                proc.kill()
            with contextlib.suppress(Exception):
                proc.wait(timeout=5)
            self._process = None

    def cleanup(self) -> None:
        """Clean up all resources used by the runtime."""
        logger.debug("Cleaning up Docker exec runtime", verbose=True)
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
        command: str,
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
    ) -> DockerExecRuntime:
        """Spawn a new Docker exec runtime instance.

        Args:
            environment: Environment specification
            working_dir: Working directory path
            command: Command to execute (immutable)
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
            New DockerExecRuntime instance

        Raises:
            ValueError: If environment spec is not for Docker
        """
        if not isinstance(environment, DockerEnvironmentSpec):
            raise ValueError("Invalid environment spec for docker runtime")

        return cls(
            working_dir=working_dir,
            spec=environment,
            command=command,
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
