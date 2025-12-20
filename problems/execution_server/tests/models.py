"""Typed request/response models for the execution server API."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ExecuteRequest:
    """POST /v1/execute request body."""

    command: str | list[dict[str, Any]]
    env: dict[str, str] = field(default_factory=dict)
    files: dict[str, Any] = field(default_factory=dict)
    stdin: str | list[str] = field(default_factory=list)
    timeout: float = 10.0
    track: list[str] | None = None
    continue_on_error: bool = False
    force: bool = False
    environment: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict, omitting None/default values."""
        d: dict[str, Any] = {"command": self.command}
        if self.env:
            d["env"] = self.env
        if self.files:
            d["files"] = self.files
        if self.stdin:
            d["stdin"] = self.stdin
        if self.timeout != 10.0:
            d["timeout"] = self.timeout
        if self.track is not None:
            d["track"] = self.track
        if self.continue_on_error:
            d["continue_on_error"] = True
        if self.force:
            d["force"] = True
        if self.environment is not None:
            d["environment"] = self.environment
        return d


@dataclass
class ExecuteResponse:
    """POST /v1/execute response."""

    status_code: int
    id: str
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    duration: float = 0.0
    timed_out: bool = False
    files: dict[str, str] = field(default_factory=dict)
    cached: bool | None = None
    commands: list[dict] | None = None
    environment: dict | None = None
    error: str | None = None
    code: str | None = None

    @classmethod
    def from_httpx(cls, resp) -> ExecuteResponse:
        data = resp.json()
        return cls(
            status_code=resp.status_code,
            id=data.get("id", ""),
            stdout=data.get("stdout", ""),
            stderr=data.get("stderr", ""),
            exit_code=data.get("exit_code", 0),
            duration=data.get("duration", 0.0),
            timed_out=data.get("timed_out", False),
            files=data.get("files", {}),
            cached=data.get("cached"),
            commands=data.get("commands"),
            environment=data.get("environment"),
            error=data.get("error"),
            code=data.get("code"),
        )


@dataclass
class StatsResponse:
    """GET /v1/stats/execution response."""

    status_code: int
    ran: int
    duration: dict[str, float | None]
    commands: dict | None = None
    cache: dict | None = None

    @classmethod
    def from_httpx(cls, resp) -> StatsResponse:
        data = resp.json()
        return cls(
            status_code=resp.status_code,
            ran=data.get("ran", 0),
            duration=data.get("duration", {}),
            commands=data.get("commands"),
            cache=data.get("cache"),
        )


@dataclass
class EnvironmentRequest:
    """POST /v1/environment request body (Checkpoint 6)."""

    name: str
    files: dict[str, Any] = field(default_factory=dict)
    concurrency_mode: str = "never"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "files": self.files,
            "concurrency_mode": self.concurrency_mode,
        }


@dataclass
class EnvironmentResponse:
    """POST /v1/environment response (Checkpoint 6)."""

    status_code: int
    name: str
    concurrency_mode: str
    files: dict[str, dict]
    error: str | None = None
    code: str | None = None

    @classmethod
    def from_httpx(cls, resp) -> EnvironmentResponse:
        data = resp.json()
        return cls(
            status_code=resp.status_code,
            name=data.get("name", ""),
            concurrency_mode=data.get("concurrency_mode", ""),
            files=data.get("files", {}),
            error=data.get("error"),
            code=data.get("code"),
        )
