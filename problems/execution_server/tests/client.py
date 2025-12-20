"""Typed HTTP client for the execution server API."""

from __future__ import annotations

import httpx

from .models import (
    EnvironmentRequest,
    EnvironmentResponse,
    ExecuteRequest,
    ExecuteResponse,
    StatsResponse,
)


class ExecutionServerClient:
    """Typed HTTP client for the execution server API."""

    def __init__(self, base_url: str, timeout: float = 30.0):
        self._base_url = base_url.rstrip("/")
        self._client = httpx.Client(base_url=self._base_url, timeout=timeout)

    def close(self):
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def execute(self, request: ExecuteRequest) -> ExecuteResponse:
        """POST /v1/execute - run a command."""
        resp = self._client.post("/v1/execute", json=request.to_dict())
        return ExecuteResponse.from_httpx(resp)

    def execute_raw(self, body: dict) -> ExecuteResponse:
        """POST /v1/execute with raw dict (for error testing)."""
        resp = self._client.post("/v1/execute", json=body)
        return ExecuteResponse.from_httpx(resp)

    def get_stats(self) -> StatsResponse:
        """GET /v1/stats/execution."""
        resp = self._client.get("/v1/stats/execution")
        return StatsResponse.from_httpx(resp)

    def create_environment(self, request: EnvironmentRequest) -> EnvironmentResponse:
        """POST /v1/environment - create persistent environment."""
        resp = self._client.post("/v1/environment", json=request.to_dict())
        return EnvironmentResponse.from_httpx(resp)

    def healthcheck(self) -> bool:
        """GET /healthz - check server is running."""
        try:
            resp = self._client.get("/healthz", timeout=1.0)
            return resp.status_code == 200
        except httpx.RequestError:
            return False


class AsyncExecutionServerClient:
    """Async version for concurrency tests."""

    def __init__(self, base_url: str, timeout: float = 30.0):
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(base_url=self._base_url, timeout=timeout)

    async def close(self):
        await self._client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()

    async def execute(self, request: ExecuteRequest) -> ExecuteResponse:
        resp = await self._client.post("/v1/execute", json=request.to_dict())
        return ExecuteResponse.from_httpx(resp)

    async def create_environment(
        self, request: EnvironmentRequest
    ) -> EnvironmentResponse:
        resp = await self._client.post("/v1/environment", json=request.to_dict())
        return EnvironmentResponse.from_httpx(resp)
