"""Shared test fixtures and utilities."""

from __future__ import annotations

import docker
import pytest


def is_docker_available() -> bool:
    """Check if Docker is available and running.

    Returns:
        True if Docker is available, False otherwise
    """
    try:
        client = docker.from_env()
        client.ping()
        client.close()
        return True
    except Exception:
        return False


@pytest.fixture(scope="session")
def docker_available() -> bool:
    """Session-scoped fixture that checks if Docker is available."""
    return is_docker_available()


@pytest.fixture(scope="session")
def skip_if_no_docker():
    """Skip test if Docker is not available."""
    if not is_docker_available():
        pytest.skip("Docker is not available")
