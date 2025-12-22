"""Unit tests for DockerRuntime and associated helpers."""

from __future__ import annotations

import contextlib
import shutil
import subprocess
from pathlib import Path
from types import MethodType
from unittest.mock import MagicMock
from unittest.mock import call

import docker
import pytest
from docker.errors import DockerException

from slop_code.execution.assets import ResolvedStaticAsset
from slop_code.execution.docker_runtime import DockerEnvironmentSpec
from slop_code.execution.docker_runtime import DockerRuntime
from slop_code.execution.docker_runtime import network_mode_for_address
from slop_code.execution.docker_runtime.models import DockerConfig
from slop_code.execution.docker_runtime.runtime import HANDLE_ENTRY_NAME
from slop_code.execution.docker_runtime.runtime import SPLIT_STRING
from slop_code.execution.models import SetupConfig
from slop_code.execution.runtime import LaunchSpec
from slop_code.execution.runtime import SolutionRuntimeError

INTEGRATION_IMAGE = "slop-code:python3.12"


def _docker_image_available(image: str) -> bool:
    docker_bin = shutil.which("docker")
    if not docker_bin:
        return False
    result = subprocess.run(
        [docker_bin, "image", "inspect", image],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


@pytest.fixture
def runtime(tmp_path: Path) -> DockerRuntime:
    spec = DockerEnvironmentSpec(
        name="unit-test",
        type="docker",
        docker=DockerConfig(image="sample", workdir="/workspace"),
    )
    runtime = DockerRuntime.__new__(DockerRuntime)
    runtime.spec = spec
    runtime.cwd = tmp_path
    runtime._client = MagicMock()
    runtime._container = None
    runtime._exit_code = None
    runtime._active_exec_process = None
    runtime._static_assets = {}
    runtime._is_evaluation = False
    runtime._setup_command = None
    runtime._ports = {}
    runtime._mounts = {}
    runtime._env_vars = {}
    runtime._user = None
    runtime._image = "sample"
    runtime._disable_setup = False
    runtime._network_mode = "bridge"
    runtime._single_shot_mode = False
    runtime._single_shot_command = None
    runtime._single_shot_process = None
    return runtime


@pytest.fixture(scope="module")
def real_docker_client():
    try:
        client = docker.from_env()
        client.ping()
    except DockerException as exc:
        pytest.skip(f"Docker daemon unavailable: {exc}")
    else:
        yield client
        with contextlib.suppress(Exception):
            client.close()


@pytest.fixture
def integration_runtime(tmp_path: Path) -> DockerRuntime:
    if not _docker_image_available(INTEGRATION_IMAGE):
        pytest.skip(f"Docker or {INTEGRATION_IMAGE} image not available")
    spec = DockerEnvironmentSpec(
        type="docker",
        name="test",
        docker=DockerConfig(image=INTEGRATION_IMAGE, workdir="/workspace"),
    )
    runtime = DockerRuntime.spawn(
        environment=spec,
        working_dir=tmp_path,
        static_assets={},
        ports={},
        mounts={},
        env_vars={},
        image=INTEGRATION_IMAGE,
    )
    yield runtime
    runtime.cleanup()


@pytest.fixture
def integration_runtime_nobody(tmp_path: Path) -> DockerRuntime:
    if not _docker_image_available(INTEGRATION_IMAGE):
        pytest.skip(f"Docker or {INTEGRATION_IMAGE} image not available")
    # Make tmp_path writable by nobody user (65534:65534)
    tmp_path.chmod(0o777)
    spec = DockerEnvironmentSpec(
        type="docker",
        name="test",
        docker=DockerConfig(
            image=INTEGRATION_IMAGE,
            workdir="/workspace",
            user="65534:65534",
        ),
    )
    runtime = DockerRuntime.spawn(
        environment=spec,
        working_dir=tmp_path,
        static_assets={},
        ports={},
        mounts={},
        env_vars={},
        image=INTEGRATION_IMAGE,
    )
    yield runtime
    runtime.cleanup()


@pytest.fixture
def mock_docker(monkeypatch):
    """Fixture to mock docker.from_env for tests that use spawn()."""
    mock_client = MagicMock()
    mock_container = MagicMock()
    mock_container.id = "test123"
    mock_client.containers.create.return_value = mock_container

    import docker as docker_module

    monkeypatch.setattr(docker_module, "from_env", lambda: mock_client)
    return mock_client


class TestDockerRuntime:
    def test_loopback_returns_host(self) -> None:
        assert network_mode_for_address("127.0.0.1") == "host"
        assert network_mode_for_address("localhost") == "host"

    def test_default_returns_bridge(self) -> None:
        assert network_mode_for_address("0.0.0.0") == "bridge"
        assert network_mode_for_address("10.0.0.5") == "bridge"

    def test_get_actual_user_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("HUID", raising=False)
        monkeypatch.delenv("HGID", raising=False)
        spec = DockerEnvironmentSpec(
            type="docker", name="test", docker=DockerConfig(image="sample")
        )
        assert spec.get_actual_user() == "0:0"

    def test_get_actual_user_from_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HUID", "1234")
        monkeypatch.setenv("HGID", "4321")
        spec = DockerEnvironmentSpec(
            type="docker", name="test", docker=DockerConfig(image="sample")
        )
        assert spec.get_actual_user() == "1234:4321"

    def test_get_effective_address_bridge_loopback(self) -> None:
        spec = DockerEnvironmentSpec(
            type="docker", name="test", docker=DockerConfig(image="sample")
        )
        assert spec.effective_network_mode() == "bridge"
        assert spec.get_effective_address("127.0.0.1") == "0.0.0.0"

    def test_effective_network_mode_non_linux(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        spec = DockerEnvironmentSpec(
            type="docker",
            name="test",
            docker=DockerConfig(image="sample", network="host"),
        )
        monkeypatch.setattr("platform.system", lambda: "Darwin")
        assert spec.effective_network_mode() == "bridge"

    def test_mounts_workspace_extra_and_assets(self, tmp_path: Path) -> None:
        extra_dir = tmp_path / "extra"
        extra_dir.mkdir()
        asset_file = tmp_path / "asset.txt"
        asset_file.write_text("content", encoding="utf-8")
        spec = DockerEnvironmentSpec(
            type="docker",
            name="test",
            docker=DockerConfig(
                image="sample",
                workdir="/workspace",
                extra_mounts={str(extra_dir): "/data/extra"},
            ),
        )
        launch_spec = LaunchSpec(
            working_dir=tmp_path,
            environment=spec,
            static_assets={
                "asset": ResolvedStaticAsset(
                    name="asset",
                    absolute_path=asset_file,
                    save_path=Path("assets/asset.txt"),
                )
            },
        )

        # Create runtime without calling __init__ to avoid container creation
        runtime = DockerRuntime.__new__(DockerRuntime)
        runtime.spec = spec
        runtime.cwd = tmp_path
        runtime._static_assets = launch_spec.static_assets or {}
        runtime._is_evaluation = launch_spec.is_evaluation
        runtime._ports = launch_spec.ports or {}
        runtime._mounts = launch_spec.mounts or {}
        runtime._env_vars = launch_spec.env_vars or {}
        runtime._user = None
        runtime._image = "sample"
        runtime._disable_setup = False
        runtime._network_mode = spec.effective_network_mode()

        volumes = runtime._build_volumes()

        assert volumes[str(tmp_path)] == {
            "bind": runtime.spec.docker.workdir,
            "mode": "rw",
        }
        assert volumes[str(extra_dir)] == {
            "bind": "/data/extra",
            "mode": "ro",
        }
        asset_bind = (Path("/static") / Path("assets/asset.txt")).as_posix()
        assert volumes[str(asset_file)] == {"bind": asset_bind, "mode": "ro"}

    def test_container_common_kwargs(self, runtime: DockerRuntime) -> None:
        kwargs = runtime._container_common_kwargs()
        assert kwargs["working_dir"] == runtime.spec.docker.workdir
        assert kwargs["network_mode"] == runtime.spec.effective_network_mode()
        assert kwargs["user"] == runtime.spec.get_actual_user()
        assert (
            kwargs["volumes"][str(runtime.cwd)]["bind"]
            == runtime.spec.docker.workdir
        )

    def test_entry_script_written(self, runtime: DockerRuntime) -> None:
        script_path = runtime._write_entry_script("echo hello")
        assert script_path.name == HANDLE_ENTRY_NAME
        content = script_path.read_text(encoding="utf-8")
        assert "echo hello\n" in content
        assert script_path.stat().st_mode & 0o111

    def test_includes_setup_commands(self, tmp_path: Path, monkeypatch) -> None:
        spec = DockerEnvironmentSpec(
            type="docker",
            name="test",
            docker=DockerConfig(image="sample"),
            setup=SetupConfig(commands=["echo setup"]),
        )

        # Mock Docker client to avoid container creation
        mock_docker = MagicMock()
        mock_container = MagicMock()
        mock_container.id = "test123"
        mock_docker.from_env.return_value = MagicMock()
        mock_docker.from_env.return_value.containers.create.return_value = (
            mock_container
        )

        import docker as docker_module

        monkeypatch.setattr(docker_module, "from_env", mock_docker.from_env)

        runtime = DockerRuntime.spawn(
            environment=spec,
            working_dir=tmp_path,
            static_assets={},
            ports={},
            mounts={},
            env_vars={},
        )
        script_path = runtime._write_entry_script("echo main")
        content = script_path.read_text(encoding="utf-8")
        assert "echo setup\n\n" in content

    def test_includes_eval_commands_when_flagged(self, tmp_path: Path) -> None:
        spec = DockerEnvironmentSpec(
            type="docker",
            name="test",
            docker=DockerConfig(image="sample"),
            setup=SetupConfig(
                commands=["echo setup"], eval_commands=["echo eval"]
            ),
        )
        runtime = DockerRuntime.spawn(
            environment=spec,
            working_dir=tmp_path,
            static_assets={},
            ports={},
            mounts={},
            env_vars={},
            is_evaluation=True,
        )
        script_path = runtime._write_entry_script("echo main")
        content = script_path.read_text(encoding="utf-8")
        assert "echo setup\necho eval" in content

    def test_kill_without_container(self, runtime: DockerRuntime) -> None:
        runtime.kill()
        assert runtime._container is None

    def test_kill_stops_active_exec_process(
        self, runtime: DockerRuntime
    ) -> None:
        called = {"stop": False}

        def fake_stop(self: DockerRuntime) -> None:
            called["stop"] = True

        runtime._stop_active_exec_process = MethodType(fake_stop, runtime)
        runtime.kill()
        assert called["stop"] is True

    def test_kill_stops_and_removes(self, runtime: DockerRuntime) -> None:
        mock_container = MagicMock()
        runtime._container = mock_container
        runtime.kill()
        mock_container.stop.assert_called_once()
        mock_container.remove.assert_called_once_with(force=True)
        assert runtime._container is None

    def test_spawn_sets_evaluation_flag(self, tmp_path: Path) -> None:
        spec = DockerEnvironmentSpec(
            type="docker",
            name="test",
            docker=DockerConfig(image="sample"),
            setup=SetupConfig(
                commands=["echo setup"], eval_commands=["echo eval"]
            ),
        )

        runtime = DockerRuntime.spawn(
            environment=spec,
            working_dir=tmp_path,
            static_assets={},
            ports={},
            mounts={},
            env_vars={},
            is_evaluation=True,
        )

        assert isinstance(runtime, DockerRuntime)
        section = runtime._format_setup_section()
        assert section.startswith("echo setup")

    def test_spawn_with_ports(self, tmp_path: Path) -> None:
        """Test that spawn handles ports correctly."""
        spec = DockerEnvironmentSpec(
            type="docker", name="test", docker=DockerConfig(image="sample")
        )

        runtime = DockerRuntime.spawn(
            environment=spec,
            working_dir=tmp_path,
            static_assets={},
            ports={},
            mounts={},
            env_vars={},
        )
        assert isinstance(runtime, DockerRuntime)

    def test_spawn_with_mounts(self, tmp_path: Path) -> None:
        """Test that spawn handles mounts correctly."""
        spec = DockerEnvironmentSpec(
            type="docker", name="test", docker=DockerConfig(image="sample")
        )
        mounts: dict[str, dict[str, str] | str] = {
            "/host/path": "/container/path"
        }
        runtime = DockerRuntime.spawn(
            environment=spec,
            working_dir=tmp_path,
            static_assets={},
            ports={},
            mounts=mounts,
            env_vars={},
        )
        assert isinstance(runtime, DockerRuntime)

    def test_spawn_with_env_vars(self, tmp_path: Path) -> None:
        """Test that spawn handles environment variables correctly."""
        spec = DockerEnvironmentSpec(
            type="docker", name="test", docker=DockerConfig(image="sample")
        )
        runtime = DockerRuntime.spawn(
            environment=spec,
            working_dir=tmp_path,
            static_assets={},
            ports={},
            mounts={},
            env_vars={"TEST_VAR": "test_value"},
        )
        assert isinstance(runtime, DockerRuntime)

    def test_spawn_with_setup_command(self, tmp_path: Path) -> None:
        """Test that spawn handles setup command correctly."""
        spec = DockerEnvironmentSpec(
            type="docker", name="test", docker=DockerConfig(image="sample")
        )
        runtime = DockerRuntime.spawn(
            environment=spec,
            working_dir=tmp_path,
            static_assets={},
            ports={},
            mounts={},
            env_vars={},
            setup_command="echo custom setup",
        )
        assert isinstance(runtime, DockerRuntime)

    def test_format_setup_section_includes_setup_command(
        self, tmp_path: Path
    ) -> None:
        """Test that _format_setup_section includes setup command."""
        spec = DockerEnvironmentSpec(
            type="docker", name="test", docker=DockerConfig(image="sample")
        )
        launch_spec = LaunchSpec(
            working_dir=tmp_path,
            environment=spec,
            setup_command="echo custom setup",
        )
        runtime = DockerRuntime(
            spec,
            tmp_path,
            launch_spec.static_assets or {},
            launch_spec.is_evaluation,
            launch_spec.ports,
            launch_spec.mounts,
            launch_spec.env_vars,
            launch_spec.setup_command,
        )

        section = runtime._format_setup_section()
        assert "echo custom setup" in section

    def test_container_kwargs_includes_ports(self, tmp_path: Path) -> None:
        """Test that _container_common_kwargs includes ports."""
        spec = DockerEnvironmentSpec(
            type="docker",
            name="test",
            docker=DockerConfig(image="sample", network="bridge"),
        )
        launch_spec = LaunchSpec(
            working_dir=tmp_path,
            environment=spec,
            ports={8080: 8081},
        )
        runtime = DockerRuntime(
            spec,
            tmp_path,
            launch_spec.static_assets or {},
            launch_spec.is_evaluation,
            launch_spec.ports,
            launch_spec.mounts,
            launch_spec.env_vars,
            launch_spec.setup_command,
        )

        kwargs = runtime._container_common_kwargs()
        assert kwargs["ports"] == {8080: 8081}

    def test_ensure_container_running_reuses_container(
        self, runtime: DockerRuntime
    ) -> None:
        """Ensure container is reused when already running."""
        mock_container = MagicMock()
        mock_container.attrs = {"State": {"Status": "running"}}
        runtime._container = mock_container

        container = runtime._ensure_container_running()

        assert container is mock_container
        mock_container.reload.assert_called_once()

    def test_ensure_container_running_recreates_stopped_container(
        self, runtime: DockerRuntime
    ) -> None:
        """Ensure a stopped container is torn down and recreated."""
        stopped_container = MagicMock()
        stopped_container.attrs = {"State": {"Status": "exited"}}
        runtime._container = stopped_container
        new_container = MagicMock()
        new_container.id = "new123"
        runtime._client.containers.create.return_value = new_container

        container = runtime._ensure_container_running()

        assert container is new_container
        runtime._client.containers.create.assert_called_once()
        new_container.start.assert_called_once()

    def test_stream_yields_stdout_events(
        self, runtime: DockerRuntime, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that streaming yields stdout RuntimeEvents."""
        fake_proc = MagicMock()
        fake_proc.poll.side_effect = [None, 0]
        fake_proc.returncode = 0

        def fake_start(
            self: DockerRuntime,
            command: str,
            env: dict[str, str],
            needs_stdin: bool,
        ):
            self._active_exec_process = fake_proc
            return fake_proc

        def fake_iter(self: DockerRuntime, proc):
            start = f"\n\n{SPLIT_STRING}\n".encode()
            return iter([(start, start), (b"hello\n", b""), (b"world\n", b"")])

        monkeypatch.setattr(
            runtime, "_start_exec_process", MethodType(fake_start, runtime)
        )
        monkeypatch.setattr(
            runtime, "_iter_exec_output", MethodType(fake_iter, runtime)
        )

        events = list(runtime.stream("echo hello", {}, None, None))

        stdout_events = [e for e in events if e.kind == "stdout"]
        assert len(stdout_events) >= 1
        assert any("hello" in (e.text or "") for e in stdout_events)

    def test_stream_yields_stderr_events(
        self, runtime: DockerRuntime, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that streaming yields stderr RuntimeEvents."""
        fake_proc = MagicMock()
        fake_proc.poll.side_effect = [None, 0]
        fake_proc.returncode = 0

        def fake_start(
            self: DockerRuntime,
            command: str,
            env: dict[str, str],
            needs_stdin: bool,
        ):
            self._active_exec_process = fake_proc
            return fake_proc

        def fake_iter(self: DockerRuntime, proc):
            start = f"\n\n{SPLIT_STRING}\n".encode()
            return iter([(start, start), (b"", b"error message\n")])

        monkeypatch.setattr(
            runtime, "_start_exec_process", MethodType(fake_start, runtime)
        )
        monkeypatch.setattr(
            runtime, "_iter_exec_output", MethodType(fake_iter, runtime)
        )

        events = list(runtime.stream("command", {}, None, None))

        stderr_events = [e for e in events if e.kind == "stderr"]
        assert len(stderr_events) >= 1
        assert any("error message" in (e.text or "") for e in stderr_events)

    def test_stream_rejects_stdin(self, runtime: DockerRuntime) -> None:
        """Test that stream() raises error when stdin is provided."""
        mock_container = MagicMock()
        mock_container.id = "test123"
        runtime._container = mock_container

        with pytest.raises(ValueError, match="stdin is not supported"):
            list(runtime.stream("echo hi", {}, ["input"], None))

    def test_stream_yields_finished_event(
        self, runtime: DockerRuntime, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that streaming yields a finished RuntimeEvent with RuntimeResult."""
        fake_proc = MagicMock()
        fake_proc.poll.side_effect = [None, 42]
        fake_proc.returncode = 42

        def fake_start(
            self: DockerRuntime,
            command: str,
            env: dict[str, str],
            needs_stdin: bool,
        ):
            self._active_exec_process = fake_proc
            return fake_proc

        def fake_iter(self: DockerRuntime, proc):
            start = f"\n\n{SPLIT_STRING}\n".encode()
            return iter([(start, start), (b"output\n", b"")])

        monkeypatch.setattr(
            runtime, "_start_exec_process", MethodType(fake_start, runtime)
        )
        monkeypatch.setattr(
            runtime, "_iter_exec_output", MethodType(fake_iter, runtime)
        )

        events = list(runtime.stream("command", {}, None, None))
        finished = [e for e in events if e.kind == "finished"]
        assert len(finished) == 1
        assert finished[0].result is not None
        assert finished[0].result.exit_code == 42

    def test_stream_yields_both_stdout_and_stderr(
        self, runtime: DockerRuntime, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that streaming yields both stdout and stderr events."""
        fake_proc = MagicMock()
        fake_proc.poll.side_effect = [None, 0]
        fake_proc.returncode = 0

        def fake_start(
            self: DockerRuntime,
            command: str,
            env: dict[str, str],
            needs_stdin: bool,
        ):
            self._active_exec_process = fake_proc
            return fake_proc

        def fake_iter(self: DockerRuntime, proc):
            start = f"\n\n{SPLIT_STRING}\n".encode()
            return iter(
                [
                    (start, start),
                    (b"stdout1\n", b"stderr1\n"),
                    (b"stdout2\n", b""),
                    (b"", b"stderr2\n"),
                ]
            )

        monkeypatch.setattr(
            runtime, "_start_exec_process", MethodType(fake_start, runtime)
        )
        monkeypatch.setattr(
            runtime, "_iter_exec_output", MethodType(fake_iter, runtime)
        )

        events = list(runtime.stream("command", {}, None, None))
        stdout_events = [e for e in events if e.kind == "stdout"]
        stderr_events = [e for e in events if e.kind == "stderr"]

        assert stdout_events
        assert stderr_events

    def test_stream_returns_exit_code_from_poll(
        self, runtime: DockerRuntime, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Stream should propagate the exit code reported by poll()."""
        fake_proc = MagicMock()
        fake_proc.poll.side_effect = [None, None, 123]
        fake_proc.returncode = 123

        def fake_start(
            self: DockerRuntime,
            command: str,
            env: dict[str, str],
            needs_stdin: bool,
        ):
            self._active_exec_process = fake_proc
            return fake_proc

        def fake_iter(self: DockerRuntime, proc):
            start = f"\n\n{SPLIT_STRING}\n".encode()
            return iter([(start, start), (b"work complete\n", b"")])

        monkeypatch.setattr(
            runtime, "_start_exec_process", MethodType(fake_start, runtime)
        )
        monkeypatch.setattr(
            runtime, "_iter_exec_output", MethodType(fake_iter, runtime)
        )

        events = list(runtime.stream("command", {}, None, None))
        finished_events = [e for e in events if e.kind == "finished"]
        assert len(finished_events) == 1
        assert finished_events[0].result is not None
        assert finished_events[0].result.exit_code == 123

    def test_stream_handles_timeout(
        self, runtime: DockerRuntime, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that streaming properly handles timeout."""
        fake_proc = MagicMock()
        fake_proc.poll.return_value = None
        fake_proc.returncode = None

        def fake_start(
            self: DockerRuntime,
            command: str,
            env: dict[str, str],
            needs_stdin: bool,
        ):
            self._active_exec_process = fake_proc
            return fake_proc

        def slow_stream(self: DockerRuntime, proc):
            import time

            start = f"\n\n{SPLIT_STRING}\n".encode()
            yield (start, start)
            yield (b"start\n", b"")
            while True:
                time.sleep(0.2)
                yield (b"", b"")

        stop_called = {"value": False}

        def fake_stop(self: DockerRuntime) -> None:
            stop_called["value"] = True

        monkeypatch.setattr(
            runtime, "_start_exec_process", MethodType(fake_start, runtime)
        )
        monkeypatch.setattr(
            runtime, "_iter_exec_output", MethodType(slow_stream, runtime)
        )
        monkeypatch.setattr(
            runtime, "_stop_active_exec_process", MethodType(fake_stop, runtime)
        )

        timeout = 0.1
        events = list(runtime.stream("command", {}, None, timeout=timeout))

        finished_events = [e for e in events if e.kind == "finished"]
        assert len(finished_events) == 1
        assert finished_events[0].result is not None
        assert finished_events[0].result.timed_out
        assert stop_called["value"] is True

    def test_write_exec_stdin_single_string(
        self, runtime: DockerRuntime
    ) -> None:
        """Test sending a single string as stdin to docker exec."""
        proc = MagicMock()
        pipe = MagicMock()
        proc.stdin = pipe

        runtime._write_exec_stdin(proc, "hello world")

        pipe.write.assert_called_once_with(b"hello world")
        pipe.flush.assert_called_once()
        pipe.close.assert_called_once()

    def test_write_exec_stdin_unicode_characters(
        self, runtime: DockerRuntime
    ) -> None:
        """Test sending unicode/multi-byte characters as stdin."""
        proc = MagicMock()
        pipe = MagicMock()
        proc.stdin = pipe

        unicode_text = "Hello 世界 🌍"
        runtime._write_exec_stdin(proc, unicode_text)

        # Verify UTF-8 encoding is respected
        expected_data = unicode_text.encode("utf-8")
        pipe.write.assert_called_once_with(expected_data)
        pipe.flush.assert_called_once()
        pipe.close.assert_called_once()

    def test_write_exec_stdin_multiple_payloads(
        self, runtime: DockerRuntime
    ) -> None:
        """Test sending multiple stdin payloads."""
        proc = MagicMock()
        pipe = MagicMock()
        proc.stdin = pipe
        payloads = ["first\n", "second\n", "third\n"]

        runtime._write_exec_stdin(proc, payloads)

        expected_calls = [call(payload.encode("utf-8")) for payload in payloads]
        assert pipe.write.call_args_list == expected_calls
        pipe.flush.assert_called_once()
        pipe.close.assert_called_once()

    def test_write_exec_stdin_large_payload(
        self, runtime: DockerRuntime
    ) -> None:
        """Test sending a large payload as stdin."""
        proc = MagicMock()
        pipe = MagicMock()
        proc.stdin = pipe
        payload = "x" * 10240

        runtime._write_exec_stdin(proc, payload)

        pipe.write.assert_called_once_with(payload.encode("utf-8"))

    def test_write_exec_stdin_detaches_pipe(
        self, runtime: DockerRuntime
    ) -> None:
        """stdin pipe should be detached to avoid communicate() flush errors."""
        proc = MagicMock()
        pipe = MagicMock()
        proc.stdin = pipe

        runtime._write_exec_stdin(proc, "payload")

        assert proc.stdin is None

    def test_write_exec_stdin_empty_list(self, runtime: DockerRuntime) -> None:
        """Test that empty list closes stdin without writing."""
        proc = MagicMock()
        pipe = MagicMock()
        proc.stdin = pipe

        runtime._write_exec_stdin(proc, [])

        pipe.write.assert_not_called()
        pipe.flush.assert_not_called()
        pipe.close.assert_called_once()

    def test_write_exec_stdin_missing_pipe_raises(
        self, runtime: DockerRuntime
    ) -> None:
        """Test that requesting stdin without a pipe is an error."""
        proc = MagicMock()
        proc.stdin = None

        with pytest.raises(SolutionRuntimeError):
            runtime._write_exec_stdin(proc, "payload")

    def test_poll_reads_exec_process_state(
        self, runtime: DockerRuntime
    ) -> None:
        """Test that poll inspects the active exec process."""
        proc = MagicMock()
        proc.poll.return_value = 42
        runtime._active_exec_process = proc

        exit_code = runtime.poll()

        assert exit_code == 42
        assert runtime._active_exec_process is None

    def test_poll_returns_none_when_process_running(
        self, runtime: DockerRuntime
    ) -> None:
        """Test that poll returns None when the exec process is still running."""
        proc = MagicMock()
        proc.poll.return_value = None
        runtime._active_exec_process = proc

        assert runtime.poll() is None
        assert runtime._active_exec_process is proc


@pytest.mark.skipif(
    not _docker_image_available(INTEGRATION_IMAGE),
    reason=f"Docker or {INTEGRATION_IMAGE} image not available",
)
class TestDockerRuntimeIntegration:
    def test_execute_reuses_persistent_container(
        self,
        integration_runtime: DockerRuntime,
    ) -> None:
        first = integration_runtime.execute(
            command="python -c \"print('first')\"",
            env={},
            stdin=None,
            timeout=60.0,
        )
        container_id = integration_runtime.container.id
        second = integration_runtime.execute(
            command="python -c \"print('second')\"",
            env={},
            stdin=None,
            timeout=60.0,
        )

        assert integration_runtime.container.id == container_id
        assert "first" in first.stdout
        assert "second" in second.stdout

    def test_persistence_with_custom_user_and_env(
        self,
        integration_runtime_nobody: DockerRuntime,
    ) -> None:
        first = integration_runtime_nobody.execute(
            command="id -u && id -g",
            env={},
            stdin=None,
            timeout=60.0,
        )
        container_id = integration_runtime_nobody.container.id

        second = integration_runtime_nobody.execute(
            command="printenv CUSTOM_ENV",
            env={"CUSTOM_ENV": "persisted-env"},
            stdin=None,
            timeout=60.0,
        )

        assert integration_runtime_nobody.container.id == container_id
        assert "65534" in first.stdout
        assert "persisted-env" in second.stdout


@pytest.mark.skipif(
    not _docker_image_available(INTEGRATION_IMAGE),
    reason=f"Docker or {INTEGRATION_IMAGE} image not available",
)
def test_stream_waits_for_container_completion(tmp_path: Path) -> None:
    """Run a real container to ensure stream stays open until exit."""

    spec = DockerEnvironmentSpec(
        type="docker",
        name="test",
        docker=DockerConfig(
            image=INTEGRATION_IMAGE,
            workdir="/workspace",
            mount_workspace=False,
        ),
    )
    runtime = DockerRuntime.spawn(
        environment=spec,
        working_dir=tmp_path,
        disable_setup=True,
        image=INTEGRATION_IMAGE,
    )
    command = "/bin/sh -c 'for i in 1 2 3; do echo tick${i}; sleep 0.5; done'"

    try:
        events = list(
            runtime.stream(
                command=command,
                env={},
                stdin=None,
                timeout=10.0,
            )
        )
    finally:
        runtime.cleanup()

    stdout_chunks = [
        event.text.strip()
        for event in events
        if event.kind == "stdout" and event.text
    ]

    assert stdout_chunks == ["tick1", "tick2", "tick3"]
    assert events
    assert events[-1].kind == "finished"
    finished_event = events[-1]
    assert finished_event.result is not None
    assert finished_event.result.exit_code == 0
    assert finished_event.result.elapsed >= 1.0
