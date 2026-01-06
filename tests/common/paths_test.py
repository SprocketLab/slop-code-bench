"""Tests for slop_code.common.paths module."""

from __future__ import annotations

from pathlib import Path

from slop_code.common.paths import serialize_path_dict
from slop_code.common.paths import to_relative_path
from slop_code.utils import ROOT as PROJECT_ROOT


class TestToRelativePath:
    """Tests for to_relative_path function."""

    def test_none_returns_none(self) -> None:
        assert to_relative_path(None) is None

    def test_already_relative_path_unchanged(self) -> None:
        result = to_relative_path(Path("configs/agents/test.yaml"))
        assert result == "configs/agents/test.yaml"

    def test_already_relative_string_unchanged(self) -> None:
        result = to_relative_path("configs/agents/test.yaml")
        assert result == "configs/agents/test.yaml"

    def test_absolute_path_within_project(self) -> None:
        abs_path = PROJECT_ROOT / "configs" / "agents" / "test.yaml"
        result = to_relative_path(abs_path)
        assert result == "configs/agents/test.yaml"

    def test_absolute_string_within_project(self) -> None:
        abs_path = str(PROJECT_ROOT / "configs" / "agents" / "test.yaml")
        result = to_relative_path(abs_path)
        assert result == "configs/agents/test.yaml"

    def test_absolute_path_outside_project_returns_string(self) -> None:
        outside_path = Path("/some/other/location/file.txt")
        result = to_relative_path(outside_path)
        assert result == "/some/other/location/file.txt"

    def test_custom_base_directory(self) -> None:
        base = Path("/custom/base")
        abs_path = Path("/custom/base/subdir/file.txt")
        result = to_relative_path(abs_path, base=base)
        assert result == "subdir/file.txt"

    def test_custom_base_path_outside_returns_string(self) -> None:
        base = Path("/custom/base")
        outside_path = Path("/other/location/file.txt")
        result = to_relative_path(outside_path, base=base)
        assert result == "/other/location/file.txt"


class TestSerializePathDict:
    """Tests for serialize_path_dict function."""

    def test_empty_dict(self) -> None:
        assert serialize_path_dict({}) == {}

    def test_no_path_values(self) -> None:
        data = {"name": "test", "value": 42, "enabled": True}
        result = serialize_path_dict(data)
        assert result == data

    def test_path_value_converted(self) -> None:
        data = {"config": PROJECT_ROOT / "configs" / "test.yaml"}
        result = serialize_path_dict(data)
        assert result == {"config": "configs/test.yaml"}

    def test_nested_dict_with_path(self) -> None:
        data = {"outer": {"inner": PROJECT_ROOT / "configs" / "nested.yaml"}}
        result = serialize_path_dict(data)
        assert result == {"outer": {"inner": "configs/nested.yaml"}}

    def test_list_with_dicts_containing_paths(self) -> None:
        data = {
            "items": [
                {"path": PROJECT_ROOT / "file1.txt"},
                {"path": PROJECT_ROOT / "file2.txt"},
            ]
        }
        result = serialize_path_dict(data)
        assert result == {
            "items": [
                {"path": "file1.txt"},
                {"path": "file2.txt"},
            ]
        }

    def test_list_with_non_dict_items_unchanged(self) -> None:
        data = {"values": [1, 2, "three", None]}
        result = serialize_path_dict(data)
        assert result == data

    def test_mixed_values(self) -> None:
        data = {
            "name": "test",
            "count": 5,
            "config_path": PROJECT_ROOT / "config.yaml",
            "nested": {
                "enabled": True,
                "file": PROJECT_ROOT / "nested" / "file.txt",
            },
            "items": [
                {"id": 1, "path": PROJECT_ROOT / "item1.txt"},
                {"id": 2, "path": PROJECT_ROOT / "item2.txt"},
            ],
        }
        result = serialize_path_dict(data)
        assert result == {
            "name": "test",
            "count": 5,
            "config_path": "config.yaml",
            "nested": {
                "enabled": True,
                "file": "nested/file.txt",
            },
            "items": [
                {"id": 1, "path": "item1.txt"},
                {"id": 2, "path": "item2.txt"},
            ],
        }

    def test_custom_base_directory(self) -> None:
        base = Path("/custom/base")
        data = {"file": Path("/custom/base/subdir/test.txt")}
        result = serialize_path_dict(data, base=base)
        assert result == {"file": "subdir/test.txt"}

    def test_original_dict_not_modified(self) -> None:
        original_path = PROJECT_ROOT / "test.yaml"
        data = {"config": original_path}
        serialize_path_dict(data)
        # Original dict should still have Path object
        assert data["config"] == original_path
        assert isinstance(data["config"], Path)
