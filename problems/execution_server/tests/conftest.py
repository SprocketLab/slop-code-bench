"""Pytest configuration for execution_server evaluation."""

from __future__ import annotations

import shlex
import socket
import subprocess
import time

import httpx
import pytest

from .client import ExecutionServerClient


def pytest_addoption(parser):
    """Register CLI options for SCBench evaluation."""
    parser.addoption("--entrypoint", required=True, help="Command to start the server")
    parser.addoption("--checkpoint", required=True, help="Current checkpoint name")
    parser.addoption("--static-assets", default="{}", help="JSON dict of static assets")


@pytest.fixture(scope="session")
def entrypoint_argv(request):
    return shlex.split(request.config.getoption("--entrypoint"))


@pytest.fixture(scope="session")
def checkpoint_name(request):
    return request.config.getoption("--checkpoint")


@pytest.fixture(scope="session")
def server_port():
    """Find a free port."""
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def server_process(entrypoint_argv, server_port):
    """Start the execution server and wait for healthcheck."""
    cmd = entrypoint_argv + ["--port", str(server_port), "--address", "127.0.0.1"]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    base_url = f"http://127.0.0.1:{server_port}"
    for _ in range(100):
        try:
            resp = httpx.get(f"{base_url}/healthz", timeout=0.1)
            if resp.status_code == 200:
                break
        except httpx.RequestError:
            pass
        time.sleep(0.1)
    else:
        proc.kill()
        stdout, stderr = proc.communicate()
        raise RuntimeError(
            f"Server failed to start.\nstdout: {stdout.decode()}\nstderr: {stderr.decode()}"
        )

    yield proc

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


@pytest.fixture(scope="session")
def server_url(server_port, server_process):
    """Base URL for the running server."""
    return f"http://127.0.0.1:{server_port}"


@pytest.fixture(scope="session")
def client(server_url) -> ExecutionServerClient:
    """Session-scoped HTTP client for the execution server."""
    with ExecutionServerClient(server_url) as c:
        yield c
