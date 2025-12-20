"""Tests for checkpoint_6: Persistent environments with concurrency modes."""

import asyncio

import pytest

from .assertions import check
from .client import AsyncExecutionServerClient
from .models import EnvironmentRequest, ExecuteRequest


class TestEnvironmentCreation:
    """Core tests for environment creation."""

    def test_create_environment_never_mode(self, client):
        """Create environment with never concurrency mode."""
        resp = client.create_environment(
            EnvironmentRequest(
                name="test-never-env",
                concurrency_mode="never",
                files={"config.txt": "value"},
            )
        )
        assert resp.status_code == 201
        assert resp.name == "test-never-env"
        assert resp.concurrency_mode == "never"
        assert "config.txt" in resp.files
        assert resp.files["config.txt"]["written_bytes"] > 0

    def test_create_environment_fork_mode(self, client):
        """Create environment with fork concurrency mode."""
        resp = client.create_environment(
            EnvironmentRequest(
                name="test-fork-env",
                concurrency_mode="fork",
                files={"counter.txt": "0"},
            )
        )
        assert resp.status_code == 201
        assert resp.concurrency_mode == "fork"

    def test_create_environment_base_mode(self, client):
        """Create environment with base concurrency mode."""
        resp = client.create_environment(
            EnvironmentRequest(
                name="test-base-env",
                concurrency_mode="base",
                files={"setup.sh": "#!/bin/bash\necho 'init'\n"},
            )
        )
        assert resp.status_code == 201
        assert resp.concurrency_mode == "base"


class TestEnvironmentExecution:
    """Core tests for execution with environments."""

    def test_execute_with_environment(self, client):
        """Execute command in environment."""
        # Create environment
        client.create_environment(
            EnvironmentRequest(
                name="exec-test-env",
                files={"data.txt": "environment data"},
            )
        )

        # Execute in environment
        resp = client.execute(
            ExecuteRequest(
                command="cat data.txt",
                environment="exec-test-env",
            )
        )
        check(resp).success().stdout("environment data").environment_name("exec-test-env")

    def test_execute_overlay_files(self, client):
        """Overlay files on top of environment."""
        client.create_environment(
            EnvironmentRequest(
                name="overlay-test-env",
                files={"base.txt": "base content"},
            )
        )

        resp = client.execute(
            ExecuteRequest(
                command="cat base.txt && cat overlay.txt",
                environment="overlay-test-env",
                files={"overlay.txt": "overlay content"},
            )
        )
        check(resp).success()
        assert "base content" in resp.stdout
        assert "overlay content" in resp.stdout

    def test_environment_persists_changes_never_mode(self, client):
        """Changes persist in never mode."""
        client.create_environment(
            EnvironmentRequest(
                name="persist-never-env",
                concurrency_mode="never",
            )
        )

        # First execution creates file
        client.execute(
            ExecuteRequest(
                command="echo 'created' > state.txt",
                environment="persist-never-env",
            )
        )

        # Second execution sees file
        resp = client.execute(
            ExecuteRequest(
                command="cat state.txt",
                environment="persist-never-env",
            )
        )
        check(resp).success().stdout("created")

    def test_base_mode_isolated_executions(self, client):
        """Base mode starts fresh each time."""
        client.create_environment(
            EnvironmentRequest(
                name="isolated-base-env",
                concurrency_mode="base",
                files={"original.txt": "original"},
            )
        )

        # First execution creates new file
        client.execute(
            ExecuteRequest(
                command="echo 'modified' > new.txt",
                environment="isolated-base-env",
            )
        )

        # Second execution should not see new file
        resp = client.execute(
            ExecuteRequest(
                command="ls",
                environment="isolated-base-env",
            )
        )
        check(resp).success()
        assert "original.txt" in resp.stdout
        assert "new.txt" not in resp.stdout


@pytest.mark.functionality
@pytest.mark.asyncio
class TestConcurrency:
    """Async concurrency tests."""

    async def test_never_mode_blocks_concurrent(self, server_url):
        """Never mode should return 423 for concurrent requests."""
        async with AsyncExecutionServerClient(server_url) as client:
            # Create exclusive environment
            await client.create_environment(
                EnvironmentRequest(
                    name="exclusive-concurrent-test",
                    concurrency_mode="never",
                )
            )

            # Start long-running request
            task1 = asyncio.create_task(
                client.execute(
                    ExecuteRequest(
                        command="sleep 2",
                        environment="exclusive-concurrent-test",
                    )
                )
            )

            # Wait for T1 to acquire lock
            await asyncio.sleep(0.3)

            # Try concurrent request - should fail
            resp2 = await client.execute(
                ExecuteRequest(
                    command="echo test",
                    environment="exclusive-concurrent-test",
                )
            )

            check(resp2).status(423).error_code("ENVIRONMENT_LOCKED")

            # T1 should succeed
            resp1 = await task1
            check(resp1).success()

    async def test_fork_mode_allows_concurrent(self, server_url):
        """Fork mode should allow concurrent requests."""
        async with AsyncExecutionServerClient(server_url) as client:
            await client.create_environment(
                EnvironmentRequest(
                    name="fork-concurrent-test",
                    concurrency_mode="fork",
                    files={"counter.txt": "0"},
                )
            )

            # Both requests should succeed concurrently
            results = await asyncio.gather(
                client.execute(
                    ExecuteRequest(
                        command="cat counter.txt",
                        environment="fork-concurrent-test",
                    )
                ),
                client.execute(
                    ExecuteRequest(
                        command="cat counter.txt",
                        environment="fork-concurrent-test",
                    )
                ),
            )

            for resp in results:
                check(resp).success()

    async def test_base_mode_allows_concurrent(self, server_url):
        """Base mode should allow concurrent requests from base."""
        async with AsyncExecutionServerClient(server_url) as client:
            await client.create_environment(
                EnvironmentRequest(
                    name="base-concurrent-test",
                    concurrency_mode="base",
                    files={"setup.txt": "initial"},
                )
            )

            # Both start from same base
            results = await asyncio.gather(
                client.execute(
                    ExecuteRequest(
                        command="cat setup.txt && echo 'run1' > out.txt",
                        environment="base-concurrent-test",
                    )
                ),
                client.execute(
                    ExecuteRequest(
                        command="cat setup.txt && echo 'run2' > out.txt",
                        environment="base-concurrent-test",
                    )
                ),
            )

            for resp in results:
                check(resp).success()
                assert "initial" in resp.stdout


@pytest.mark.error
class TestEnvironmentErrors:
    """Error handling for environments."""

    def test_missing_environment_field(self, client):
        """Missing environment field should return 400."""
        resp = client.execute_raw({"command": "echo hello"})
        check(resp).status(400).error_code("MISSING_ENVIRONMENT")

    def test_unknown_environment(self, client):
        """Unknown environment should return 404."""
        resp = client.execute(
            ExecuteRequest(
                command="echo test",
                environment="does-not-exist",
            )
        )
        check(resp).status(404).error_code("ENVIRONMENT_NOT_FOUND")

    def test_duplicate_environment_name(self, client):
        """Creating duplicate environment name should fail."""
        # Create first
        resp1 = client.create_environment(
            EnvironmentRequest(name="duplicate-env-test")
        )
        assert resp1.status_code == 201

        # Try to create duplicate
        resp2 = client.create_environment(
            EnvironmentRequest(name="duplicate-env-test")
        )
        assert resp2.status_code in (400, 409)
        assert resp2.code == "ENVIRONMENT_EXISTS"

    def test_invalid_concurrency_mode(self, client):
        """Invalid concurrency mode should return 400."""
        resp = client._client.post(
            "/v1/environment",
            json={
                "name": "invalid-mode-env",
                "concurrency_mode": "invalid",
            },
        )
        assert resp.status_code == 400

    def test_empty_environment_name(self, client):
        """Empty environment name should return 400."""
        resp = client._client.post(
            "/v1/environment",
            json={"name": "", "concurrency_mode": "never"},
        )
        assert resp.status_code == 400
