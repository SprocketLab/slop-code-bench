"""Tests for Docker environment spec user resolution."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from slop_code.execution.docker_runtime.models import DockerConfig
from slop_code.execution.docker_runtime.models import DockerEnvironmentSpec
from slop_code.execution.docker_runtime.models import resolve_host_user
from slop_code.execution.models import CommandConfig

if TYPE_CHECKING:
    import pytest


class TestResolveHostUser:
    """Tests for resolve_host_user."""

    def test_uses_process_ids_by_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("HUID", raising=False)
        monkeypatch.delenv("HGID", raising=False)
        assert resolve_host_user() == f"{os.getuid()}:{os.getgid()}"

    def test_env_overrides_process_ids(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HUID", "4242")
        monkeypatch.setenv("HGID", "4343")
        assert resolve_host_user() == "4242:4343"


class TestGetContainerUser:
    """Tests for DockerEnvironmentSpec.get_container_user."""

    def test_defaults_to_host_user(
        self,
        docker_spec: DockerEnvironmentSpec,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("HUID", raising=False)
        monkeypatch.delenv("HGID", raising=False)
        assert docker_spec.get_container_user() == (
            f"{os.getuid()}:{os.getgid()}"
        )

    def test_explicit_spec_user_wins(self) -> None:
        spec = DockerEnvironmentSpec(
            type="docker",
            name="test-docker-user",
            commands=CommandConfig(command="python"),
            docker=DockerConfig(
                image="python:3.12-slim",
                workdir="/workspace",
                user="7:8",
            ),
        )
        assert spec.get_container_user() == "7:8"
