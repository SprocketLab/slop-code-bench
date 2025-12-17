"""HTTP-based adapter that drives submissions exposed as API servers."""

from __future__ import annotations

import base64
import binascii
import functools
import io
import json
import queue
import socket
import tarfile
import tempfile
import threading
import time
import urllib.parse
import zipfile
from pathlib import Path
from typing import Any, Literal, Self

import httpx
from pydantic import ConfigDict
from pydantic import Field
from pydantic import model_validator

from slop_code.evaluation.adapters.base import ADAPTER_REGISTRY
from slop_code.evaluation.adapters.base import AdapterConfig
from slop_code.evaluation.adapters.base import AdapterError
from slop_code.evaluation.adapters.base import BaseAdapter
from slop_code.evaluation.adapters.models import BaseCase
from slop_code.evaluation.adapters.models import CaseResult
from slop_code.execution import DockerEnvironmentSpec
from slop_code.execution import Session
from slop_code.execution import SubmissionRuntime
from slop_code.execution.runtime import RuntimeEvent
from slop_code.logging import get_logger

logger = get_logger(__name__)

_ARCHIVE_MIME_KEYWORDS = (
    "application/zip",
    "application/x-zip-compressed",
    "application/x-tar",
    "application/tar",
    "application/gzip",
    "application/x-gzip",
    "application/x-tar+gzip",
    "application/x-compressed-tar",
)


def _is_archive_content_type(content_type: str | None) -> bool:
    """Return True when the provided content type represents an archive."""

    if not content_type:
        return False
    lowered = content_type.lower()
    return any(keyword in lowered for keyword in _ARCHIVE_MIME_KEYWORDS)


def _extract_archive(content: bytes, content_type: str) -> dict[str, str]:
    """Extract archive contents and return a dict of {path: content}.

    Supports zip, tar, tar.gz, and other tar variants. Extracts to a temporary
    directory, reads all files, and returns their contents as strings.

    Args:
        content: Raw bytes of the archive
        content_type: MIME type to determine extraction method

    Returns:
        Dictionary mapping file paths to their contents as strings

    Raises:
        AdapterError: If extraction fails or archive format is invalid
    """
    files: dict[str, str] = {}
    lowered = content_type.lower()

    # Determine if this is a zip or tar archive
    is_zip = any(
        kw in lowered
        for kw in ("application/zip", "application/x-zip-compressed")
    )
    is_tar = any(
        kw in lowered
        for kw in (
            "application/x-tar",
            "application/tar",
            "application/gzip",
            "application/x-gzip",
            "application/x-tar+gzip",
            "application/x-compressed-tar",
        )
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            if is_zip:
                # Extract zip archive
                with zipfile.ZipFile(io.BytesIO(content)) as zf:
                    zf.extractall(tmpdir)  # noqa: S202
            elif is_tar:
                # Extract tar archive (handles .tar, .tar.gz, .tar.bz2, etc.)
                with tarfile.open(fileobj=io.BytesIO(content)) as tf:
                    tf.extractall(tmpdir)  # noqa: S202
            else:
                raise AdapterError(
                    f"Unsupported archive content type: {content_type}"
                )

            # Walk the extracted directory and read all files
            tmppath = Path(tmpdir)
            for file_path in tmppath.rglob("*"):
                if file_path.is_file():
                    # Use relative path from extraction root
                    rel_path = file_path.relative_to(tmppath)
                    try:
                        # Try reading as text
                        files[str(rel_path)] = file_path.read_text(
                            encoding="utf-8"
                        )
                    except UnicodeDecodeError:
                        # If binary, base64 encode
                        files[str(rel_path)] = base64.b64encode(
                            file_path.read_bytes()
                        ).decode("ascii")

        except (zipfile.BadZipFile, tarfile.TarError) as exc:
            raise AdapterError(f"Failed to extract archive: {exc}") from exc

    return files


def _extract_filename_from_content_disposition(
    disposition: str | None,
) -> str | None:
    """Extract a filename from a Content-Disposition header, if present."""

    if not disposition:
        return None
    filename: str | None = None
    encoded_filename: str | None = None
    for part in disposition.split(";"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        key = key.strip().lower()
        cleaned = value.strip().strip('"')
        if key == "filename*":
            if cleaned.lower().startswith("utf-8''"):
                cleaned = cleaned[7:]
            encoded_filename = urllib.parse.unquote(cleaned)
        elif key == "filename":
            filename = urllib.parse.unquote(cleaned)
    return encoded_filename or filename


def get_random_available_port() -> int:
    """Return an unused TCP port by briefly binding to port 0."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(
            ("", 0)
        )  # Binds to all available interfaces and lets the OS pick a port
        return s.getsockname()[1]  # Returns the selected port number


class APIAdapterConfig(AdapterConfig):
    """Adapter configuration for submissions that expose an HTTP API."""

    model_config = ConfigDict(extra="forbid")
    type: Literal["api"] = "api"  # type: ignore
    address: str
    port: int | None = None
    health_path: str | None = None
    startup_timeout_s: int = 10
    max_startup_attempts: int = 5
    delay_startup_attempts: int = 5
    response_is_json: bool = False
    arguments: list[str] = Field(default_factory=list)


class APIResult(CaseResult):
    type: Literal["api"] = Field(default="api", frozen=True)  # type: ignore
    method: str = "GET"
    headers: dict[str, str] = Field(default_factory=dict)
    retries: int = 0
    binary_response_base64: str | None = None
    binary_response_filename: str | None = None
    binary_response_size: int | None = None


class APICase(BaseCase):
    """Concrete case model for the API adapter."""

    query: dict[str, int | str | float | bool | None] = Field(
        default_factory=dict
    )
    method: str = "GET"
    path: str = ""
    headers: dict[str, str] = Field(default_factory=dict)
    body: Any | None = None
    retries: int = 0

    @model_validator(mode="after")
    def validate_arguments(self) -> Self:
        if self.arguments and self.query:
            raise ValueError("arguments and query cannot both be set")
        return self

    def get_query_params(
        self,
    ) -> dict[str, int | str | float | bool | None] | None:
        if self.query:
            return self.query
        out = {}
        for arg in self.arguments:
            k, v = arg.split("=", 1)
            out[k] = v
        return out if out else None


@ADAPTER_REGISTRY.register("api")
class APIAdapter(BaseAdapter[APICase, APIResult, APIAdapterConfig]):
    """Adapter that starts a server once per group and sends HTTP requests.

    The adapter launches the provided entry file as a long-running server
    process. Each case is executed by constructing and sending an HTTP
    request to the server and validating the response.
    """

    case_class = APICase
    result_class = APIResult
    config_class = APIAdapterConfig

    def __init__(
        self,
        cfg: APIAdapterConfig,
        session: Session,
        env: dict[str, str],
        command: str,
        timeout: float | None = None,
        isolated: bool = False,
    ) -> None:
        """Initialize the adapter with configuration and execution context.

        Args:
            cfg: Adapter configuration containing address/port details.
            session: Execution session managing workspace and runtime lifecycle.
            env: Environment variables injected when launching the server.
            command: Command string used to boot the submission's server.
            timeout: Default request timeout applied when cases do not override.
            isolated: Whether to reset workspace after each case.
        """
        super().__init__(
            cfg=cfg,
            session=session,
            env=env,
            command=command,
            timeout=timeout,
            isolated=isolated,
        )
        # API-specific state
        self.port = cfg.port if cfg.port else get_random_available_port()
        self.address = cfg.address
        self._had_adapter_error = False
        self._runtime: SubmissionRuntime | None = None
        self._stream_thread: threading.Thread | None = None
        self._output_queue: queue.Queue[RuntimeEvent] = queue.Queue()
        self._stdout_chunks: list[str] = []
        self._stderr_chunks: list[str] = []

    @property
    def runtime(self) -> SubmissionRuntime:
        if self._runtime is None:
            raise AdapterError("Runtime not found")
        return self._runtime

    def _get_captured_output(self) -> tuple[str, str]:
        """Return captured stdout and stderr from the server process."""
        return "".join(self._stdout_chunks), "".join(self._stderr_chunks)

    def _coerce_archive_body(self, body: Any) -> bytes:
        """Return raw bytes for an archive request body.

        Supports bytes/bytearray inputs directly and decodes base64-encoded
        strings. Raises an adapter error when the body cannot be coerced.
        """

        if body is None:
            raise AdapterError("archive requests require a non-empty body")
        if isinstance(body, (bytes, bytearray, memoryview)):
            return bytes(body)
        if isinstance(body, str):
            try:
                return base64.b64decode(body)
            except binascii.Error as exc:
                raise AdapterError(
                    "Body for archive request must be base64-encoded"
                ) from exc
        raise AdapterError(
            f"Unsupported body type {type(body)!r} for archive request"
        )

    def _wait_for_ready(self) -> None:
        """Block until the server is reachable or raise if it exits early."""
        if self.runtime.poll() is not None:
            out, err = self._get_captured_output()

            logger.warning("Server failed to start", base_url=self.base_url)
            logger.debug("stdout", out=out)
            logger.debug("stderr", err=err)
            raise AdapterError(
                f"Server exited before ready. stdout={out!r} stderr={err!r}"
            )

        attempts = 0
        is_ready = False
        while attempts < self.cfg.max_startup_attempts:
            logger.debug(
                "Waiting for server to become ready", attempts=attempts
            )
            try:
                with httpx.Client(timeout=self.cfg.startup_timeout_s) as client:
                    path = self.cfg.health_path or "/"
                    resp = client.get(self.base_url + path)
                    if resp.status_code:
                        is_ready = True
                        break
            except (
                httpx.ConnectError,
                httpx.RemoteProtocolError,
                httpx.TimeoutException,
                httpx.ReadError,
            ) as e:
                # Treat transient connection issues as not-ready and keep waiting
                # until timeout or the server exits.
                logger.debug("Failed to connect to server", error=str(e))
            if self.runtime.poll() is not None:
                out, err = self._get_captured_output()
                self.runtime.kill()
                logger.error(
                    "Server exited before ready",
                    base_url=self.base_url,
                )
                logger.error("stdout", out=out)
                logger.error("stderr", err=err)
                raise AdapterError(
                    f"Server exited before ready. stdout={out!r}"
                    f" {self.cfg.startup_timeout_s}s"
                )
            attempts += 1
            time.sleep(self.cfg.delay_startup_attempts)
        if not is_ready:
            logger.warning(
                "Server did not become ready", base_url=self.base_url
            )
            out, err = self._get_captured_output()
            logger.debug("stdout", out=out)
            logger.debug("stderr", err=err)
            self.runtime.kill()
            raise AdapterError(
                f"Server did not become ready within {attempts:,} attempts"
                f" {self.cfg.startup_timeout_s}s"
            )
        logger.debug("Server became ready", base_url=self.base_url)

    def get_port_and_address(self) -> tuple[int, str]:
        """Return (container_port, container_bind_address) for server startup.

        - For Docker with bridge networking, bind to 0.0.0.0 on a fixed internal
          port (8000) and map it to the host port.
        - For Docker with host networking, bind directly to the configured
          host address/port so the host can connect without port mapping.
        - For local execution, return the configured host address/port.
        """
        if isinstance(self.session.spec, DockerEnvironmentSpec):
            network_mode = self.session.spec.effective_network_mode()
            bind_address = self.session.spec.get_effective_address(self.address)
            if network_mode == "host":
                # Host network: container sees the host namespace; use the
                # configured host port directly (no port publishing).
                return int(self.port), bind_address  # type: ignore[arg-type]
            # Bridge or other: use fixed internal port with publishing.
            return 8000, bind_address
        return self.port, self.address

    def _consume_stream(self, stream_iter):
        """Background thread to consume stream events and capture output."""
        try:
            for event in stream_iter:
                self._output_queue.put(event)
                if event.kind == "stdout" and event.text:
                    self._stdout_chunks.append(event.text)
                elif event.kind == "stderr" and event.text:
                    self._stderr_chunks.append(event.text)
                elif event.kind == "finished":
                    logger.info("Server process finished")
                    logger.debug(
                        "Result",
                        exit_code=event.result.exit_code
                        if event.result
                        else None,
                    )
                    if event.result:
                        logger.debug(
                            "stdout",
                            stdout=event.result.stdout
                            if event.result
                            else None,
                        )
                        logger.debug(
                            "stderr",
                            stderr=event.result.stderr
                            if event.result
                            else None,
                        )
                    break
        except Exception as e:
            logger.error("Error consuming stream", error=str(e))

    def _on_enter(self) -> None:
        """Start the server and wait for readiness.

        Raises:
            AdapterError: If the server exits prematurely or doesn't become
                ready within the configured timeout.
        """
        # Compute bind parameters for the process being launched without
        # mutating the host-facing base_url (self.address:self.port).
        container_port, container_bind_address = self.get_port_and_address()

        suffix_parts = []
        format_kwargs = {}
        if "{address}" in self.command:
            # Substitute the address value into the formatted command using the
            # bind address appropriate for the execution environment (e.g.,
            # 0.0.0.0 inside Docker bridge networking).
            format_kwargs["address"] = container_bind_address
        else:
            suffix_parts.extend(["--address", container_bind_address])
        if "{port}" in self.command:
            # Use the container bind port for the spawned process; the host
            # will connect via self.port which may differ when using Docker.
            format_kwargs["port"] = container_port
        else:
            suffix_parts.extend(["--port", str(container_port)])

        base_command = self.command.format(**format_kwargs)
        if suffix_parts:
            # Ensure arguments are separated when appended to the formatted command
            base_command = base_command + " " + " ".join(suffix_parts)

        if self.cfg.arguments:
            resolved_arguments = self.session.resolve_static_placeholders(
                {"arguments": self.cfg.arguments}
            )

            base_command = (
                base_command + " " + " ".join(resolved_arguments["arguments"])
            )

        # Compute port mapping for Docker bridge mode
        ports: dict[int, int] | None = None
        if isinstance(self.session.spec, DockerEnvironmentSpec):
            network_mode = self.session.spec.effective_network_mode()
            if network_mode != "host":
                # Bridge mode: map container port to host port
                ports = {container_port: self.port}

        # Spawn a runtime from the session with ports
        self._runtime = self.session.spawn(ports=ports)

        # Start the server process by calling stream()
        stream_iter = self._runtime.stream(
            command=base_command,
            env=self.session.spec.get_full_env(self.env),
            stdin=None,
            timeout=None,
        )

        # Start background thread to consume stream events
        self._stream_thread = threading.Thread(
            target=self._consume_stream,
            args=(stream_iter,),
            daemon=True,
        )
        self._stream_thread.start()

        # Give the process a moment to start
        time.sleep(0.1)

        try:
            self._wait_for_ready()
        except AdapterError as e:
            logger.error("Failed to wait for ready", error=str(e))
            self.runtime.kill()
            self._had_adapter_error = True

    def _on_exit(self, exc_type, exc, tb) -> None:
        """Terminate the server and clean up resources."""
        # Wait for stream thread to finish
        if self._stream_thread is not None and self._stream_thread.is_alive():
            self._stream_thread.join(timeout=5)

    @property
    def base_url(self) -> str:
        """Return the host-facing base URL for requests."""
        return f"http://{self.address}:{self.port}"

    def _execute_case(
        self, case: APICase, tracked_files: list[str]
    ) -> APIResult:
        """Send the HTTP request and convert the response into a result.

        Args:
            case: The resolved case with path, method, headers, body.
            tracked_files: File patterns to collect after execution.

        Returns:
            APIResult with status code, body, headers, and tracked files.
        """
        # Early return if server failed to start
        if self._had_adapter_error:
            return APIResult(
                status_code=-1,
                output=None,
                stderr="Adapter error",
                adapter_error=True,
                group_type=case.group_type,
                group=case.group,
                id=case.id,
            )

        t0 = time.time()
        url = f"{self.base_url}{case.path}"
        # Determine request timeout: case override > adapter default
        timeout_s = (
            float(case.timeout_s)
            if case.timeout_s is not None
            else self.timeout
        )

        attempt = 0
        last_err: str | None = None
        response: httpx.Response | None = None
        timed_out = False
        adapter_error = False
        while attempt <= max(0, int(case.retries)):
            timed_out = False
            try:
                with httpx.Client(timeout=timeout_s) as client:
                    method = case.method.upper()
                    request_headers = dict(case.headers or {})
                    header_lookup = {
                        key.lower(): value
                        for key, value in request_headers.items()
                    }
                    json_body: Any | None = None
                    content_body: str | bytes | None = None
                    if case.body is not None:
                        if _is_archive_content_type(
                            header_lookup.get("content-type")
                        ):
                            content_body = self._coerce_archive_body(case.body)
                        elif isinstance(case.body, (dict, list)):
                            json_body = case.body
                        elif isinstance(
                            case.body, (bytes, bytearray, memoryview)
                        ):
                            content_body = bytes(case.body)
                        else:
                            # Use raw content for non-JSON bodies
                            content_body = str(case.body)
                    params = case.get_query_params()
                    response = client.request(
                        method,
                        url,
                        params=params,
                        headers=request_headers or None,
                        content=content_body,
                        json=json_body,
                    )
                last_err = None
                timed_out = False
                break
            except AdapterError as e:
                last_err = str(e)
                adapter_error = True
                response = None
                break
            except httpx.ReadTimeout:
                last_err = "Request timed out"
                timed_out = True
                attempt += 1
            except (
                httpx.ConnectError,
                httpx.RemoteProtocolError,
            ) as e:
                last_err = str(e)
                attempt += 1

        elapsed = time.time() - t0
        files = dict(self._get_file_contents(tracked_files))

        # Extract archive responses and merge into files dict
        if response is not None:
            response_content_type = response.headers.get("content-type")
            if _is_archive_content_type(response_content_type):
                try:
                    extracted_files = _extract_archive(
                        response.content, response_content_type
                    )
                    files.update(extracted_files)
                except AdapterError as e:
                    logger.warning(
                        "Failed to extract archive response", error=str(e)
                    )

        result_factory = functools.partial(
            APIResult,
            resource_path=url,
            method=case.method,
            timed_out=timed_out,
            retries=attempt,
            adapter_error=adapter_error,
            elapsed=elapsed,
            files=files,
            group_type=case.group_type,
            group=case.group,
            id=case.id,
        )

        if response is None:
            # All attempts failed due to connection/timeout/etc.; normal failure
            result = result_factory(
                status_code=-1,
                output=None,
                stderr=last_err or "request failed",
            )
        else:
            response_headers = dict(response.headers)
            binary_base64: str | None = None
            binary_filename: str | None = None
            binary_size: int | None = None
            if _is_archive_content_type(response_headers.get("content-type")):
                binary_base64 = base64.b64encode(response.content).decode(
                    "ascii"
                )
                binary_size = len(response.content)
                binary_filename = _extract_filename_from_content_disposition(
                    response_headers.get("content-disposition")
                )
                output: Any = {
                    "content_b64": binary_base64,
                    "encoding": "base64",
                    "size": binary_size,
                    "content_type": response_headers.get("content-type"),
                    "is_archive": True,
                }
                if binary_filename:
                    output["filename"] = binary_filename
            else:
                if self.cfg.response_is_json:
                    try:
                        output = json.loads(response.text)
                    except json.JSONDecodeError:
                        output = response.text
                else:
                    output = response.text
            result = result_factory(
                status_code=response.status_code,
                output=output,
                headers=response_headers,
                binary_response_base64=binary_base64,
                binary_response_filename=binary_filename,
                binary_response_size=binary_size,
            )

        return result
