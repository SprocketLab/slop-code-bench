"""Pytest configuration for word_stats tests.

This conftest.py provides fixtures that are populated by the SCBench pytest runner:
- entrypoint: The command to run the submission (e.g., "python main.py")
- static_assets: Dict mapping asset names to their resolved paths
- checkpoint: The current checkpoint being evaluated
"""

import json
import pytest


def pytest_addoption(parser):
    """Add custom command-line options for SCBench integration."""
    parser.addoption(
        "--entrypoint",
        action="store",
        default="python main.py",
        help="Command to run the submission",
    )
    parser.addoption(
        "--checkpoint",
        action="store",
        default="checkpoint_1",
        help="Current checkpoint being evaluated",
    )
    parser.addoption(
        "--static-assets",
        action="store",
        default="{}",
        help="JSON dict of static asset name -> path",
    )


@pytest.fixture
def entrypoint(request) -> str:
    """Get the entrypoint command for running the submission."""
    return request.config.getoption("--entrypoint")


@pytest.fixture
def checkpoint(request) -> str:
    """Get the current checkpoint name."""
    return request.config.getoption("--checkpoint")


@pytest.fixture
def static_assets(request) -> dict[str, str]:
    """Get the static assets dict (name -> path)."""
    assets_json = request.config.getoption("--static-assets")
    return json.loads(assets_json)
