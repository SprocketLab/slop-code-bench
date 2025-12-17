"""Shared utilities for the test suite."""

from __future__ import annotations

import os
import shutil
import subprocess
from functools import cache

DOCKER_TEST_IMAGE = os.environ.get(
    "SLOP_CODE_TEST_DOCKER_IMAGE",
    "python:3.12-slim",
)


def _docker_binary() -> str | None:
    """Return the path to the docker binary if it exists."""
    return shutil.which("docker")


@cache
def docker_tests_available(image: str = DOCKER_TEST_IMAGE) -> bool:
    """Check that Docker is usable and the provided image is present."""
    docker_bin = _docker_binary()
    if not docker_bin:
        return False

    result = subprocess.run(
        [docker_bin, "image", "inspect", image],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


__all__ = ["DOCKER_TEST_IMAGE", "docker_tests_available"]
