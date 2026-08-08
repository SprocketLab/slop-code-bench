from __future__ import annotations

import os
from unittest.mock import patch

from slop_code.execution.docker_runtime.models import DockerConfig
from slop_code.execution.docker_runtime.models import DockerEnvironmentSpec
from slop_code.execution.models import CommandConfig


def _docker_spec(*, user: str | None = None) -> DockerEnvironmentSpec:
    return DockerEnvironmentSpec(
        type="docker",
        name="test-docker",
        commands=CommandConfig(command="python"),
        docker=DockerConfig(
            image="python:3.12-slim",
            user=user,
        ),
    )


def test_actual_user_prefers_docker_config(monkeypatch) -> None:
    monkeypatch.setenv("HUID", "2000")
    monkeypatch.setenv("HGID", "2001")

    assert _docker_spec(user="3000:3001").get_actual_user() == "3000:3001"


def test_actual_user_uses_host_environment(monkeypatch) -> None:
    monkeypatch.setenv("HUID", "2000")
    monkeypatch.setenv("HGID", "2001")

    assert _docker_spec().get_actual_user() == "2000:2001"


def test_actual_user_defaults_to_process_user(monkeypatch) -> None:
    monkeypatch.delenv("HUID", raising=False)
    monkeypatch.delenv("HGID", raising=False)

    with (
        patch.object(os, "getuid", return_value=1234),
        patch.object(os, "getgid", return_value=5678),
    ):
        assert _docker_spec().get_actual_user() == "1234:5678"


def test_actual_user_has_non_posix_fallback(monkeypatch) -> None:
    monkeypatch.delenv("HUID", raising=False)
    monkeypatch.delenv("HGID", raising=False)

    with (
        patch.object(os, "getuid", None),
        patch.object(os, "getgid", None),
    ):
        assert _docker_spec().get_actual_user() == "1000:1000"
