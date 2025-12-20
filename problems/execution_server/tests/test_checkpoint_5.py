"""Tests for checkpoint_5: Caching."""

import pytest

from .assertions import check, check_stats
from .models import ExecuteRequest


class TestCaching:
    """Core tests for caching functionality."""

    def test_cache_miss_then_hit(self, client):
        """First request is cache miss, second is cache hit."""
        # First request - cache miss
        resp1 = client.execute(
            ExecuteRequest(
                command="echo 'cache test unique'",
                timeout=5,
            )
        )
        check(resp1).success().cached(False).stdout("cache test unique")

        # Second identical request - cache hit
        resp2 = client.execute(
            ExecuteRequest(
                command="echo 'cache test unique'",
                timeout=5,
            )
        )
        check(resp2).success().cached(True).stdout("cache test unique")

        # IDs should be different
        assert resp1.id != resp2.id

    def test_different_command_cache_miss(self, client):
        """Different commands result in cache miss."""
        resp1 = client.execute(ExecuteRequest(command="echo 'first'"))
        check(resp1).success().cached(False)

        resp2 = client.execute(ExecuteRequest(command="echo 'second'"))
        check(resp2).success().cached(False)

    def test_different_files_cache_miss(self, client):
        """Different files result in cache miss."""
        resp1 = client.execute(
            ExecuteRequest(
                command="cat input.txt",
                files={"input.txt": "version 1"},
            )
        )
        check(resp1).success().cached(False).stdout("version 1")

        resp2 = client.execute(
            ExecuteRequest(
                command="cat input.txt",
                files={"input.txt": "version 2"},
            )
        )
        check(resp2).success().cached(False).stdout("version 2")

    def test_force_bypass_cache(self, client):
        """Force flag bypasses cache."""
        # Initial request
        resp1 = client.execute(ExecuteRequest(command="echo 'force test'"))
        check(resp1).success().cached(False)

        # Force re-run
        resp2 = client.execute(
            ExecuteRequest(command="echo 'force test'", force=True)
        )
        check(resp2).success().cached(False)

    def test_cache_includes_tracked_files(self, client):
        """Cached response includes tracked files."""
        resp1 = client.execute(
            ExecuteRequest(
                command="echo 'tracked' > out.txt",
                track=["*.txt"],
            )
        )
        check(resp1).success().cached(False).has_file("out.txt", "tracked\n")

        resp2 = client.execute(
            ExecuteRequest(
                command="echo 'tracked' > out.txt",
                track=["*.txt"],
            )
        )
        check(resp2).success().cached(True).has_file("out.txt", "tracked\n")

    def test_command_chain_caching(self, client):
        """Command chains are cached."""
        chain = [
            {"cmd": "echo 'step 1' > out.txt"},
            {"cmd": "echo 'step 2' >> out.txt"},
        ]

        resp1 = client.execute(
            ExecuteRequest(command=chain, track=["*.txt"])
        )
        check(resp1).success().cached(False).has_commands(2)

        resp2 = client.execute(
            ExecuteRequest(command=chain, track=["*.txt"])
        )
        check(resp2).success().cached(True).has_commands(2)

    def test_stats_include_cache_metrics(self, client):
        """Stats include cache hit/miss metrics."""
        stats = client.get_stats()
        check_stats(stats).status(200).has_cache_stats()
        assert stats.cache["hit_rate"] >= 0
        assert stats.cache["hit_rate"] <= 1


@pytest.mark.functionality
class TestCachingFunctionality:
    """Additional caching tests."""

    def test_different_timeout_cache_miss(self, client):
        """Different timeout results in cache miss."""
        resp1 = client.execute(
            ExecuteRequest(command="echo 'timeout test'", timeout=5)
        )
        check(resp1).success().cached(False)

        resp2 = client.execute(
            ExecuteRequest(command="echo 'timeout test'", timeout=10)
        )
        check(resp2).success().cached(False)

    def test_different_env_cache_miss(self, client):
        """Different env vars result in cache miss."""
        resp1 = client.execute(
            ExecuteRequest(
                command="echo $VAR",
                env={"VAR": "value1"},
            )
        )
        check(resp1).success().cached(False)

        resp2 = client.execute(
            ExecuteRequest(
                command="echo $VAR",
                env={"VAR": "value2"},
            )
        )
        check(resp2).success().cached(False)

    def test_cached_not_counted_in_stats(self, client):
        """Cached executions not counted in ran/duration stats."""
        # Get initial stats
        stats1 = client.get_stats()
        initial_ran = stats1.ran

        # Run a new command
        client.execute(ExecuteRequest(command="echo 'stats test unique cmd'"))

        # Run it again (cached)
        client.execute(ExecuteRequest(command="echo 'stats test unique cmd'"))

        stats2 = client.get_stats()
        # Should only count the first (non-cached) run
        assert stats2.ran == initial_ran + 1

    def test_force_updates_cache(self, client):
        """Force run updates the cache entry."""
        # Initial run
        resp1 = client.execute(
            ExecuteRequest(command="date +%s%N", timeout=5)
        )
        check(resp1).success().cached(False)
        first_output = resp1.stdout

        # Cached run - same output
        resp2 = client.execute(
            ExecuteRequest(command="date +%s%N", timeout=5)
        )
        check(resp2).success().cached(True)
        assert resp2.stdout == first_output

        # Force run - new output
        resp3 = client.execute(
            ExecuteRequest(command="date +%s%N", timeout=5, force=True)
        )
        check(resp3).success().cached(False)

        # Cached run should now have new output
        resp4 = client.execute(
            ExecuteRequest(command="date +%s%N", timeout=5)
        )
        check(resp4).success().cached(True)
        assert resp4.stdout == resp3.stdout


@pytest.mark.error
class TestCachingErrors:
    """Error handling for caching."""

    def test_invalid_force_type(self, client):
        """Non-boolean force should return 400."""
        resp = client.execute_raw(
            {"command": "echo test", "force": "yes"}
        )
        check(resp).status(400).error_code("INVALID_TYPE")
