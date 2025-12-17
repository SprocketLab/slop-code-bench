import base64
import io
import os
import shutil
import socket
import subprocess
import tarfile
import zipfile
from pathlib import Path

import pytest

from slop_code.evaluation.adapters import api
from slop_code.evaluation.adapters.base import Adapter
from slop_code.evaluation.adapters.models import GroupType
from slop_code.execution import LocalEnvironmentSpec
from slop_code.execution import Session
from slop_code.execution import Snapshot
from slop_code.execution import Workspace
from slop_code.execution.models import CommandConfig
from slop_code.execution.models import EnvironmentConfig
from slop_code.execution.models import SetupConfig


def _find_free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    _, port = s.getsockname()
    s.close()
    return int(port)


def _docker_image_available(image: str) -> bool:
    """Check if Docker is available and the specified image exists."""
    docker_bin = shutil.which("docker")
    if not docker_bin:
        return False
    result = subprocess.run(
        [docker_bin, "image", "inspect", image],
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def _create_zip_archive(files: dict[str, str]) -> bytes:
    """Create a ZIP archive containing the given files."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for filename, content in files.items():
            zf.writestr(filename, content)
    return buffer.getvalue()


def _create_tar_archive(files: dict[str, str], compression: str = "") -> bytes:
    """Create a TAR archive containing the given files.

    Args:
        files: Dictionary mapping filenames to contents
        compression: Compression mode ("gz" for tar.gz, "" for uncompressed)
    """
    buffer = io.BytesIO()
    mode = f"w:{compression}" if compression else "w"
    with tarfile.open(fileobj=buffer, mode=mode) as tf:
        for filename, content in files.items():
            content_bytes = content.encode("utf-8")
            tarinfo = tarfile.TarInfo(name=filename)
            tarinfo.size = len(content_bytes)
            tf.addfile(tarinfo, io.BytesIO(content_bytes))
    return buffer.getvalue()


@pytest.fixture
def server_script() -> str:  # type: ignore
    """Return a small HTTP server script for exercising API adapter behavior."""
    return """import argparse
import base64
import io
import os
import tarfile
import time
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs



class Handler(BaseHTTPRequestHandler):
    # Use HTTP/1.0 to avoid chunked encoding requirements
    protocol_version = "HTTP/1.0"
    def _write(self, code=200, body="", content_type="text/plain"):
        print(" _write", code, body, content_type)
        self.send_response(code)
        if isinstance(body, str):
            body = body.encode()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    # Silence default logging to avoid filling stderr pipe
    def log_message(self, format, *args):  # noqa: A003
        return

    def do_GET(self):  # noqa: N802
        print("do_GET", self.path)
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._write(200, "ok")
            return
        if parsed.path == "/query":
            q = parse_qs(parsed.query)
            self._write(200, q.get("q", [""])[0])
            return
        if parsed.path == "/wait":
            q = parse_qs(parsed.query)
            try:
                delay = float(q.get("delay", ["1"][0]))
            except Exception:
                delay = 1.0
            time.sleep(delay)
            self._write(200, "done")
            return
        if parsed.path == "/write":
            q = parse_qs(parsed.query)
            path = q.get("path", ["out.txt"])[0]
            content = q.get("content", [""])[0]
            try:
                with open(path, "w") as f:
                    f.write(content)
                self._write(200, "ok")
            except Exception as e:
                self._write(500, f"error: {e}")
            return
        if parsed.path == "/archive/zip":
            # Return a ZIP archive with test files
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("file1.txt", "content1")
                zf.writestr("subdir/file2.txt", "content2")
            self._write(200, buffer.getvalue(), "application/zip")
            return
        if parsed.path == "/archive/tar":
            # Return a TAR archive with test files
            buffer = io.BytesIO()
            with tarfile.open(fileobj=buffer, mode="w") as tf:
                for filename, content in [("file1.txt", "content1"), ("subdir/file2.txt", "content2")]:
                    content_bytes = content.encode("utf-8")
                    tarinfo = tarfile.TarInfo(name=filename)
                    tarinfo.size = len(content_bytes)
                    tf.addfile(tarinfo, io.BytesIO(content_bytes))
            self._write(200, buffer.getvalue(), "application/x-tar")
            return
        if parsed.path == "/archive/targz":
            # Return a TAR.GZ archive with test files
            buffer = io.BytesIO()
            with tarfile.open(fileobj=buffer, mode="w:gz") as tf:
                for filename, content in [("file1.txt", "content1"), ("subdir/file2.txt", "content2")]:
                    content_bytes = content.encode("utf-8")
                    tarinfo = tarfile.TarInfo(name=filename)
                    tarinfo.size = len(content_bytes)
                    tf.addfile(tarinfo, io.BytesIO(content_bytes))
            self._write(200, buffer.getvalue(), "application/x-tar+gzip")
            return
        self._write(200, "root")

    def do_POST(self):  # noqa: N802
        print("do_POST", self.path)
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else b""
        if parsed.path == "/echo":
            self._write(200, body)
            return
        if parsed.path == "/archive/upload":
            # Echo back information about the uploaded archive
            content_type = self.headers.get("Content-Type", "")
            response = f"Received {len(body)} bytes with type {content_type}"
            self._write(200, response)
            return
        self._write(404, "not found")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--address", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    ADDRESS = args.address
    PORT = args.port
    server = ThreadingHTTPServer((ADDRESS, PORT), Handler)
    print("Server created", ADDRESS, PORT)
    server.daemon_threads = True
    print("Server started", ADDRESS, PORT)
    try:
        print("Server serving", ADDRESS, PORT)
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    print("???")
    main()
        """


@pytest.fixture
def submission(tmpdir, server_script) -> tuple[Path, str, dict[str, bytes]]:
    """Create a submission directory containing the HTTP server entry file."""
    sub_dir = Path(tmpdir) / "sub"
    sub_dir.mkdir()
    entry_file = "server.py"
    files = {entry_file: server_script.encode()}
    for file, content in files.items():
        (sub_dir / file).write_bytes(content)
    return sub_dir, entry_file, files


@pytest.fixture
def api_adapter(submission):
    """Provide a configured `APIAdapter` backed by a local session."""
    sub_dir, entry_file, _ = submission
    port = _find_free_port()
    spec = LocalEnvironmentSpec(
        type="local",
        name="local-api-adapter",
        setup=SetupConfig(commands=[]),
        commands=CommandConfig(
            command=f"uv run --project={Path(__file__).parents[3].absolute()}",
            agent_command="python",
        ),
        environment=EnvironmentConfig(include_os_env=True),
    )

    def snapshot_fn(cwd: Path) -> Snapshot:
        return Snapshot.from_directory(cwd, env=os.environ.copy())

    initial_snapshot = snapshot_fn(sub_dir)
    workspace = Workspace(
        initial_snapshot=initial_snapshot,
        snapshot_fn=snapshot_fn,
        is_agent_infer=False,
    )
    session = Session(spec, workspace)
    command = spec.get_command(entry_file)
    return api.APIAdapter(
        cfg=api.APIAdapterConfig(
            address="127.0.0.1",
            port=port,
            health_path="/health",
            startup_timeout_s=5,
        ),
        env={},
        session=session,
        command=command,
        timeout=2,
    )


def test_api_adapter_is_instance(api_adapter: Adapter):
    """Sanity check that fixture produces a subclass of `Adapter`."""
    assert isinstance(api_adapter, Adapter)


def test_api_requests_happy_path(api_adapter: api.APIAdapter):
    """Health endpoint should respond with 200 and body 'ok'."""
    with api_adapter:
        # health
        res = api_adapter.run_case(
            api.APICase(
                id="h",
                path="/health",
                group_type=GroupType.CORE,
                group="core",
                checkpoint="checkpoint_1",
            )
        )
        assert res.status_code == 200
        assert "ok" in str(res.output)
        assert res.stderr is None


def test_api_requests_query(api_adapter: api.APIAdapter):
    """GET with query parameters should echo the provided query value."""
    with api_adapter:
        # query
        res = api_adapter.run_case(
            api.APICase(
                id="q",
                path="/query",
                query={"q": "hello"},
                group_type=GroupType.CORE,
                group="core",
                checkpoint="checkpoint_1",
            )
        )
        assert res.status_code == 200
        assert str(res.output).strip() == "hello"


def test_api_requests_echo(api_adapter: api.APIAdapter):
    """POST /echo should return the request body verbatim."""
    with api_adapter:
        # post echo
        res = api_adapter.run_case(
            api.APICase(
                id="p",
                method="POST",
                path="/echo",
                body="ping",
                group_type=GroupType.CORE,
                group="core",
                checkpoint="checkpoint_1",
            )
        )
        assert res.status_code == 200
        assert str(res.output) == "ping"


def test_api_requests_write(submission, local_environment_spec):
    """Server writes a file; adapter should collect it via tracked files."""
    sub_dir, entry_file, _ = submission
    port = _find_free_port()
    spec = local_environment_spec

    def snapshot_fn(cwd: Path) -> Snapshot:
        return Snapshot.from_directory(cwd, env=os.environ.copy())

    initial_snapshot = snapshot_fn(sub_dir)
    workspace = Workspace(
        initial_snapshot=initial_snapshot,
        snapshot_fn=snapshot_fn,
        is_agent_infer=False,
    )
    session = Session(spec, workspace)
    adapter = api.APIAdapter(
        cfg=api.APIAdapterConfig(
            address="127.0.0.1",
            port=port,
            health_path="/health",
            startup_timeout_s=5,
            tracked_files=["note.txt"],
        ),
        env={},
        session=session,
        command=f"python {entry_file}",
        timeout=2,
    )
    with adapter:
        # write file and collect
        res = adapter.run_case(
            api.APICase(
                id="w",
                path="/write",
                query={"path": "note.txt", "content": "hi"},
                group_type=GroupType.CORE,
                group="core",
                checkpoint="checkpoint_1",
            )
        )
        assert res.status_code == 200
        assert res.files.get("note.txt") == "hi"


def test_api_timeout_and_retries(api_adapter: api.APIAdapter):
    """Timeout should trigger retries and ultimately set status_code to -1."""
    with api_adapter:
        # Endpoint sleeps beyond timeout; ensure retries occur and
        # final status_code=-1
        res = api_adapter.run_case(
            api.APICase(
                id="t",
                path="/wait",
                query={"delay": "1.0"},
                retries=1,
                timeout_s=0.1,
                group_type=GroupType.CORE,
                group="core",
                checkpoint="checkpoint_1",
            )
        )
        assert res.status_code == -1
        assert res.stderr != ""


@pytest.fixture
def docker_api_adapter(submission, docker_environment_spec):
    """Provide an `APIAdapter` configured to run inside Docker when available."""
    sub_dir, entry_file, _ = submission
    port = _find_free_port()
    address = "127.0.0.1"  # Host address for connections
    spec = docker_environment_spec

    def snapshot_fn(cwd: Path) -> Snapshot:
        return Snapshot.from_directory(cwd, env=os.environ.copy())

    initial_snapshot = snapshot_fn(sub_dir)
    workspace = Workspace(
        initial_snapshot=initial_snapshot,
        snapshot_fn=snapshot_fn,
        is_agent_infer=False,
    )
    session = Session(spec, workspace)
    return api.APIAdapter(
        cfg=api.APIAdapterConfig(
            address=address,
            port=port,
            health_path="/health",
            startup_timeout_s=10,
        ),
        env={},
        session=session,
        command=f"python {entry_file}",
        timeout=2,
    )


DOCKER_IMAGE = "ghcr.io/astral-sh/uv:python3.12-trixie-slim"


@pytest.mark.skipif(
    not _docker_image_available(DOCKER_IMAGE),
    reason=f"Docker or {DOCKER_IMAGE} image not available",
)
def test_docker_api_adapter_is_instance(docker_api_adapter: Adapter):
    """Sanity check for Docker-backed adapter instance creation."""
    assert isinstance(docker_api_adapter, Adapter)


@pytest.mark.skipif(
    not _docker_image_available(DOCKER_IMAGE),
    reason=f"Docker or {DOCKER_IMAGE} image not available",
)
def test_docker_api_requests_happy_path(docker_api_adapter: api.APIAdapter):
    """Health endpoint within Docker should respond with 200 and body 'ok'."""
    with docker_api_adapter:
        # health
        res = docker_api_adapter.run_case(
            api.APICase(
                id="h",
                path="/health",
                group_type=GroupType.CORE,
                group="core",
                checkpoint="checkpoint_1",
            )
        )
        assert res.status_code == 200
        assert "ok" in str(res.output)
        assert res.stderr is None


@pytest.mark.skipif(
    not _docker_image_available(DOCKER_IMAGE),
    reason=f"Docker or {DOCKER_IMAGE} image not available",
)
def test_docker_api_requests_query(docker_api_adapter: api.APIAdapter):
    """GET within Docker should echo the provided query parameter value."""
    with docker_api_adapter:
        # query
        res = docker_api_adapter.run_case(
            api.APICase(
                id="q",
                path="/query",
                query={"q": "docker-hello"},
                group_type=GroupType.CORE,
                group="core",
                checkpoint="checkpoint_1",
            )
        )
        assert res.status_code == 200
        assert str(res.output).strip() == "docker-hello"


@pytest.mark.skipif(
    not _docker_image_available(DOCKER_IMAGE),
    reason=f"Docker or {DOCKER_IMAGE} image not available",
)
def test_docker_api_requests_echo(docker_api_adapter: api.APIAdapter):
    """POST within Docker should echo the request body."""
    with docker_api_adapter:
        # post echo
        res = docker_api_adapter.run_case(
            api.APICase(
                id="p",
                method="POST",
                path="/echo",
                body="docker-ping",
                group_type=GroupType.CORE,
                group="core",
                checkpoint="checkpoint_1",
            )
        )
        assert res.status_code == 200
        assert str(res.output) == "docker-ping"


@pytest.mark.skipif(
    not _docker_image_available(DOCKER_IMAGE),
    reason=f"Docker or {DOCKER_IMAGE} image not available",
)
def test_docker_api_requests_write(submission, docker_environment_spec):
    """Within Docker, server writes a file; adapter collects tracked file."""
    sub_dir, entry_file, _ = submission
    port = _find_free_port()
    address = "127.0.0.1"
    spec = docker_environment_spec

    def snapshot_fn(cwd: Path) -> Snapshot:
        return Snapshot.from_directory(cwd, env=os.environ.copy())

    initial_snapshot = snapshot_fn(sub_dir)
    workspace = Workspace(
        initial_snapshot=initial_snapshot,
        snapshot_fn=snapshot_fn,
        is_agent_infer=False,
    )
    session = Session(spec, workspace)
    adapter = api.APIAdapter(
        cfg=api.APIAdapterConfig(
            address=address,
            port=port,
            health_path="/health",
            startup_timeout_s=10,
            tracked_files=["docker_note.txt"],
        ),
        env={},
        session=session,
        command=f"python {entry_file}",
        timeout=2,
    )
    with adapter:
        # write file and collect
        res = adapter.run_case(
            api.APICase(
                id="w",
                path="/write",
                query={"path": "docker_note.txt", "content": "docker-content"},
                group_type=GroupType.CORE,
                group="core",
                checkpoint="checkpoint_1",
            )
        )
        assert res.status_code == 200
        assert res.files.get("docker_note.txt") == "docker-content"


# Archive extraction tests


def test_api_zip_response_extraction(api_adapter: api.APIAdapter):
    """ZIP archive responses should be extracted into result.files."""
    with api_adapter:
        res = api_adapter.run_case(
            api.APICase(
                id="zip",
                path="/archive/zip",
                group_type=GroupType.CORE,
                group="core",
                checkpoint="checkpoint_1",
            )
        )
        assert res.status_code == 200
        # Check that extracted files appear in the files dict
        assert "file1.txt" in res.files
        assert res.files["file1.txt"] == "content1"
        assert "subdir/file2.txt" in res.files
        assert res.files["subdir/file2.txt"] == "content2"
        # Binary response should still be preserved
        assert res.binary_response_base64 is not None
        assert res.binary_response_size is not None


def test_api_tar_response_extraction(api_adapter: api.APIAdapter):
    """TAR archive responses should be extracted into result.files."""
    with api_adapter:
        res = api_adapter.run_case(
            api.APICase(
                id="tar",
                path="/archive/tar",
                group_type=GroupType.CORE,
                group="core",
                checkpoint="checkpoint_1",
            )
        )
        assert res.status_code == 200
        # Check that extracted files appear in the files dict
        assert "file1.txt" in res.files
        assert res.files["file1.txt"] == "content1"
        assert "subdir/file2.txt" in res.files
        assert res.files["subdir/file2.txt"] == "content2"
        # Binary response should still be preserved
        assert res.binary_response_base64 is not None
        assert res.binary_response_size is not None


def test_api_targz_response_extraction(api_adapter: api.APIAdapter):
    """TAR.GZ archive responses should be extracted into result.files."""
    with api_adapter:
        res = api_adapter.run_case(
            api.APICase(
                id="targz",
                path="/archive/targz",
                group_type=GroupType.CORE,
                group="core",
                checkpoint="checkpoint_1",
            )
        )
        assert res.status_code == 200
        # Check that extracted files appear in the files dict
        assert "file1.txt" in res.files
        assert res.files["file1.txt"] == "content1"
        assert "subdir/file2.txt" in res.files
        assert res.files["subdir/file2.txt"] == "content2"
        # Binary response should still be preserved
        assert res.binary_response_base64 is not None
        assert res.binary_response_size is not None


def test_api_archive_upload_base64(api_adapter: api.APIAdapter):
    """Archive uploads with base64-encoded bodies should work."""
    with api_adapter:
        # Create a small ZIP archive
        test_files = {"test.txt": "hello world"}
        zip_bytes = _create_zip_archive(test_files)
        zip_b64 = base64.b64encode(zip_bytes).decode("ascii")

        res = api_adapter.run_case(
            api.APICase(
                id="upload",
                method="POST",
                path="/archive/upload",
                headers={"Content-Type": "application/zip"},
                body=zip_b64,
                group_type=GroupType.CORE,
                group="core",
                checkpoint="checkpoint_1",
            )
        )
        assert res.status_code == 200
        # Server should confirm receipt
        assert "application/zip" in str(res.output)
        assert str(len(zip_bytes)) in str(res.output)


def test_api_archive_upload_bytes(api_adapter: api.APIAdapter):
    """Archive uploads with raw bytes bodies should work."""
    with api_adapter:
        # Create a small TAR archive
        test_files = {"test.txt": "hello world"}
        tar_bytes = _create_tar_archive(test_files)

        res = api_adapter.run_case(
            api.APICase(
                id="upload",
                method="POST",
                path="/archive/upload",
                headers={"Content-Type": "application/x-tar"},
                body=tar_bytes,
                group_type=GroupType.CORE,
                group="core",
                checkpoint="checkpoint_1",
            )
        )
        assert res.status_code == 200
        # Server should confirm receipt
        assert "application/x-tar" in str(res.output)
        assert str(len(tar_bytes)) in str(res.output)


def test_extract_archive_helper_zip():
    """Test the _extract_archive helper function with ZIP files."""
    test_files = {"file1.txt": "content1", "dir/file2.txt": "content2"}
    zip_bytes = _create_zip_archive(test_files)

    extracted = api._extract_archive(zip_bytes, "application/zip")

    assert len(extracted) == 2
    assert extracted["file1.txt"] == "content1"
    assert extracted["dir/file2.txt"] == "content2"


def test_extract_archive_helper_tar():
    """Test the _extract_archive helper function with TAR files."""
    test_files = {"file1.txt": "content1", "dir/file2.txt": "content2"}
    tar_bytes = _create_tar_archive(test_files)

    extracted = api._extract_archive(tar_bytes, "application/x-tar")

    assert len(extracted) == 2
    assert extracted["file1.txt"] == "content1"
    assert extracted["dir/file2.txt"] == "content2"


def test_extract_archive_helper_targz():
    """Test the _extract_archive helper function with TAR.GZ files."""
    test_files = {"file1.txt": "content1", "dir/file2.txt": "content2"}
    targz_bytes = _create_tar_archive(test_files, compression="gz")

    extracted = api._extract_archive(targz_bytes, "application/x-tar+gzip")

    assert len(extracted) == 2
    assert extracted["file1.txt"] == "content1"
    assert extracted["dir/file2.txt"] == "content2"


def test_extract_archive_invalid_format():
    """Test that invalid archive data raises AdapterError."""
    from slop_code.evaluation.adapters.base import AdapterError

    invalid_data = b"this is not a valid archive"

    with pytest.raises(AdapterError, match="Failed to extract archive"):
        api._extract_archive(invalid_data, "application/zip")


def test_coerce_archive_body_base64():
    """Test _coerce_archive_body with base64-encoded string."""
    adapter = api.APIAdapter(
        cfg=api.APIAdapterConfig(address="127.0.0.1"),
        env={},
        session=None,  # type: ignore
        command="test",
    )

    test_data = b"test archive data"
    b64_str = base64.b64encode(test_data).decode("ascii")

    result = adapter._coerce_archive_body(b64_str)
    assert result == test_data


def test_coerce_archive_body_bytes():
    """Test _coerce_archive_body with raw bytes."""
    adapter = api.APIAdapter(
        cfg=api.APIAdapterConfig(address="127.0.0.1"),
        env={},
        session=None,  # type: ignore
        command="test",
    )

    test_data = b"test archive data"
    result = adapter._coerce_archive_body(test_data)
    assert result == test_data


def test_coerce_archive_body_invalid():
    """Test _coerce_archive_body with invalid input."""
    from slop_code.evaluation.adapters.base import AdapterError

    adapter = api.APIAdapter(
        cfg=api.APIAdapterConfig(address="127.0.0.1"),
        env={},
        session=None,  # type: ignore
        command="test",
    )

    # None should raise error
    with pytest.raises(AdapterError, match="archive requests require"):
        adapter._coerce_archive_body(None)

    # Invalid type should raise error
    with pytest.raises(AdapterError, match="Unsupported body type"):
        adapter._coerce_archive_body(123)  # type: ignore

    # Invalid base64 should raise error
    with pytest.raises(AdapterError, match="must be base64-encoded"):
        adapter._coerce_archive_body("not valid base64!!!")
