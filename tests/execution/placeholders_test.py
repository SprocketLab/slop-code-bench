"""Tests for static asset placeholder resolution."""

from pathlib import Path

import pytest

from slop_code.execution.assets import ResolvedStaticAsset
from slop_code.execution.placeholders import resolve_static_path
from slop_code.execution.placeholders import resolve_static_placeholders


class TestResolveStaticPath:
    """Tests for resolve_static_path function."""

    def test_local_returns_absolute_path(self):
        """For local execution, should return absolute host path."""
        asset = ResolvedStaticAsset(
            name="test_data",
            absolute_path=Path("/host/data/test.csv"),
            save_path=Path("data/test.csv"),
        )
        result = resolve_static_path(asset, is_docker=False)
        assert result == "/host/data/test.csv"

    def test_docker_returns_static_prefix_path(self):
        """For Docker execution, should return /static/{save_path}."""
        asset = ResolvedStaticAsset(
            name="test_data",
            absolute_path=Path("/host/data/test.csv"),
            save_path=Path("data/test.csv"),
        )
        result = resolve_static_path(asset, is_docker=True)
        assert result == "/static/data/test.csv"

    def test_docker_with_nested_save_path(self):
        """Docker path should handle nested save paths."""
        asset = ResolvedStaticAsset(
            name="config",
            absolute_path=Path("/host/configs/app/settings.json"),
            save_path=Path("configs/app/settings.json"),
        )
        result = resolve_static_path(asset, is_docker=True)
        assert result == "/static/configs/app/settings.json"


class TestResolveStaticPlaceholders:
    """Tests for resolve_static_placeholders function."""

    @pytest.fixture
    def static_assets(self):
        """Create test static assets."""
        return {
            "test_data": ResolvedStaticAsset(
                name="test_data",
                absolute_path=Path("/host/data/test.csv"),
                save_path=Path("data/test.csv"),
            ),
            "config": ResolvedStaticAsset(
                name="config",
                absolute_path=Path("/host/config.json"),
                save_path=Path("config.json"),
            ),
        }

    def test_resolve_string_local(self, static_assets):
        """Should resolve placeholders in strings for local execution."""
        data = "Load data from {{static:test_data}}"
        result = resolve_static_placeholders(
            data, static_assets, is_docker=False
        )
        assert result == "Load data from /host/data/test.csv"

    def test_resolve_string_docker(self, static_assets):
        """Should resolve placeholders in strings for Docker execution."""
        data = "Load data from {{static:test_data}}"
        result = resolve_static_placeholders(
            data, static_assets, is_docker=True
        )
        assert result == "Load data from /static/data/test.csv"

    def test_resolve_list_of_strings(self, static_assets):
        """Should resolve placeholders in lists."""
        data = [
            "--input",
            "{{static:test_data}}",
            "--config",
            "{{static:config}}",
        ]
        result = resolve_static_placeholders(
            data, static_assets, is_docker=True
        )
        assert result == [
            "--input",
            "/static/data/test.csv",
            "--config",
            "/static/config.json",
        ]

    def test_resolve_dict(self, static_assets):
        """Should resolve placeholders in dictionaries."""
        data = {
            "input_file": "{{static:test_data}}",
            "config_file": "{{static:config}}",
            "other": "no placeholder",
        }
        result = resolve_static_placeholders(
            data, static_assets, is_docker=False
        )
        assert result == {
            "input_file": "/host/data/test.csv",
            "config_file": "/host/config.json",
            "other": "no placeholder",
        }

    def test_resolve_nested_structure(self, static_assets):
        """Should resolve placeholders in nested structures."""
        data = {
            "arguments": ["--input", "{{static:test_data}}"],
            "config": {"path": "{{static:config}}"},
            "files": {
                "script.py": "import pandas as pd\ndf = pd.read_csv('{{static:test_data}}')"
            },
        }
        result = resolve_static_placeholders(
            data, static_assets, is_docker=True
        )
        assert result == {
            "arguments": ["--input", "/static/data/test.csv"],
            "config": {"path": "/static/config.json"},
            "files": {
                "script.py": "import pandas as pd\ndf = pd.read_csv('/static/data/test.csv')"
            },
        }

    def test_multiple_placeholders_in_string(self, static_assets):
        """Should resolve multiple placeholders in one string."""
        data = "cp {{static:test_data}} {{static:config}}"
        result = resolve_static_placeholders(
            data, static_assets, is_docker=False
        )
        assert result == "cp /host/data/test.csv /host/config.json"

    def test_unknown_placeholder_raises_error(self, static_assets):
        """Should raise ValueError for unknown placeholder."""
        data = "{{static:unknown}}"
        with pytest.raises(
            ValueError, match="Unknown static asset placeholder: unknown"
        ):
            resolve_static_placeholders(data, static_assets, is_docker=False)

    def test_no_placeholders_returns_unchanged(self, static_assets):
        """Data without placeholders should be returned unchanged."""
        data = {"key": "value", "list": [1, 2, 3]}
        result = resolve_static_placeholders(
            data, static_assets, is_docker=False
        )
        assert result == data

    def test_empty_dict(self, static_assets):
        """Should handle empty dictionaries."""
        result = resolve_static_placeholders({}, static_assets, is_docker=False)
        assert result == {}

    def test_tuple_preservation(self, static_assets):
        """Should preserve tuples and resolve placeholders within them."""
        data = ("--input", "{{static:test_data}}")
        result = resolve_static_placeholders(
            data, static_assets, is_docker=True
        )
        assert result == ("--input", "/static/data/test.csv")
        assert isinstance(result, tuple)

    def test_dict_keys_with_placeholders(self, static_assets):
        """Should resolve placeholders in dictionary keys."""
        data = {"{{static:test_data}}": "value"}
        result = resolve_static_placeholders(
            data, static_assets, is_docker=False
        )
        assert result == {"/host/data/test.csv": "value"}

    def test_non_string_values_unchanged(self, static_assets):
        """Non-string values should pass through unchanged."""
        data = {
            "int": 42,
            "float": 3.14,
            "bool": True,
            "none": None,
        }
        result = resolve_static_placeholders(
            data, static_assets, is_docker=False
        )
        assert result == data
