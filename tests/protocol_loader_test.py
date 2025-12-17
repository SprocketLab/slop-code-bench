from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Protocol, runtime_checkable

import pytest

from slop_code.protocol_loader import ProtocolLoadError
from slop_code.protocol_loader import get_source_files
from slop_code.protocol_loader import load_protocol_entrypoint


@runtime_checkable
class TestProtocol(Protocol):
    """A simple test protocol for testing purposes."""

    def test_method(self) -> str: ...


class HelperTestClass:
    """A test class that implements TestProtocol."""

    def test_method(self) -> str:
        return "test_result"


class HelperTestFunction:
    """A test function-like class for testing function entrypoints."""

    def __call__(self) -> str:
        return "function_result"


def helper_test_function() -> str:
    """A test function for testing function entrypoints."""
    return "function_result"


class TestLoadProtocolEntrypoint:
    """Test cases for load_protocol_entrypoint function."""

    def test_load_class_success(self):
        """Test successful loading of a class that implements the protocol."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            module_file = temp_path / "test_module.py"

            # Write a test module with a class that implements the protocol
            module_file.write_text("""
class TestClass:
    def test_method(self) -> str:
        return "test_result"
""")

            result = load_protocol_entrypoint(
                protocol=TestProtocol,
                module_path=module_file,
                entrypoint_name="TestClass",
            )

            assert result.__name__ == "TestClass"
            instance = result()
            assert instance.test_method() == "test_result"

    def test_load_class_not_implementing_protocol(self):
        """Test loading a class that doesn't implement the protocol."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            module_file = temp_path / "test_module.py"

            # Write a test module with a class that doesn't implement the protocol
            module_file.write_text("""
class WrongClass:
    def wrong_method(self) -> str:
        return "wrong_result"
""")

            with pytest.raises(ProtocolLoadError, match="does not implement protocol"):
                load_protocol_entrypoint(
                    protocol=TestProtocol,
                    module_path=module_file,
                    entrypoint_name="WrongClass",
                )

    def test_load_function_success(self):
        """Test successful loading of a function entrypoint."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            module_file = temp_path / "test_module.py"

            # Write a test module with a function
            module_file.write_text("""
def test_function() -> str:
    return "function_result"
""")

            # For functions, we'll use a more permissive protocol check
            result = load_protocol_entrypoint(
                protocol=TestProtocol,
                module_path=module_file,
                entrypoint_name="test_function",
            )

            assert callable(result)
            assert result() == "function_result"

    def test_load_nonexistent_file(self):
        """Test loading from a nonexistent file."""
        with pytest.raises(ProtocolLoadError, match="Module file .* does not exist"):
            load_protocol_entrypoint(
                protocol=TestProtocol,
                module_path=Path("nonexistent.py"),
                entrypoint_name="TestClass",
            )

    def test_load_non_python_file(self):
        """Test loading from a non-Python file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            module_file = temp_path / "test_module.txt"
            module_file.write_text("not python")

            with pytest.raises(ProtocolLoadError, match="is not a Python file"):
                load_protocol_entrypoint(
                    protocol=TestProtocol,
                    module_path=module_file,
                    entrypoint_name="TestClass",
                )

    def test_load_nonexistent_entrypoint(self):
        """Test loading a nonexistent entrypoint."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            module_file = temp_path / "test_module.py"
            module_file.write_text("class TestClass: pass")

            with pytest.raises(ProtocolLoadError, match="not found in module"):
                load_protocol_entrypoint(
                    protocol=TestProtocol,
                    module_path=module_file,
                    entrypoint_name="NonExistentClass",
                )

    def test_load_entrypoint_not_class(self):
        """Test loading an entrypoint that's not a class and has no annotations."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            module_file = temp_path / "test_module.py"
            module_file.write_text("test_variable = 42")

            with pytest.raises(ProtocolLoadError, match="not a class and has no type annotations"):
                load_protocol_entrypoint(
                    protocol=TestProtocol,
                    module_path=module_file,
                    entrypoint_name="test_variable",
                )

    def test_load_with_import_error(self):
        """Test loading a module with import errors."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            module_file = temp_path / "test_module.py"
            module_file.write_text("import nonexistent_module")

            with pytest.raises(ProtocolLoadError, match="Failed to import module"):
                load_protocol_entrypoint(
                    protocol=TestProtocol,
                    module_path=module_file,
                    entrypoint_name="TestClass",
                )

    def test_load_nested_directory(self):
        """Test loading from a nested directory structure."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            nested_dir = temp_path / "nested"
            nested_dir.mkdir()
            module_file = nested_dir / "test_module.py"

            module_file.write_text("""
class TestClass:
    def test_method(self) -> str:
        return "nested_result"
""")

            result = load_protocol_entrypoint(
                protocol=TestProtocol,
                module_path=module_file,
                entrypoint_name="TestClass",
            )

            assert result.__name__ == "TestClass"
            instance = result()
            assert instance.test_method() == "nested_result"


class TestGetSourceFiles:
    """Test cases for get_source_files function."""

    def test_get_source_files_success(self):
        """Test successful extraction of source files."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            module_file = temp_path / "test_module.py"

            # Write a test module
            module_content = '''
class TestClass:
    def test_method(self) -> str:
        return "test_result"
'''
            module_file.write_text(module_content)

            # Mock load function that does nothing
            def mock_load():
                pass

            sources = get_source_files(
                module_path=module_file,
                load_function=mock_load,
            )

            assert "test_module.py" in sources
            assert sources["test_module.py"] == module_content

    def test_get_source_files_nonexistent_file(self):
        """Test getting source files from a nonexistent file."""
        with pytest.raises(ProtocolLoadError, match="Module file .* does not exist"):
            get_source_files(
                module_path=Path("nonexistent.py"),
                load_function=lambda: None,
            )

    def test_get_source_files_with_dependencies(self):
        """Test getting source files including dependencies."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Create a main module that imports a local module
            main_module = temp_path / "main.py"
            main_module.write_text("""
from local_module import helper_function

class TestClass:
    def test_method(self) -> str:
        return helper_function()
""")

            # Create the local dependency
            local_module = temp_path / "local_module.py"
            local_module.write_text("""
def helper_function() -> str:
    return "helper_result"
""")

# Load function that imports the main module
            def load_main():
                import importlib.util
                import sys

                # Add temp directory to sys.path so local_module can be found
                if str(temp_path) not in sys.path:
                    sys.path.insert(0, str(temp_path))

                spec = importlib.util.spec_from_file_location("main", main_module)
                module = importlib.util.module_from_spec(spec)
                sys.modules["main"] = module
                spec.loader.exec_module(module)

            sources = get_source_files(
                module_path=main_module,
                load_function=load_main,
            )

            assert "main.py" in sources
            assert "local_module.py" in sources
            assert "def helper_function()" in sources["local_module.py"]

    def test_get_source_files_excludes_pycache(self):
        """Test that __pycache__ directories are excluded."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            module_file = temp_path / "test_module.py"
            module_file.write_text("class TestClass: pass")

            # Create a __pycache__ directory
            pycache_dir = temp_path / "__pycache__"
            pycache_dir.mkdir()
            pycache_file = pycache_dir / "test_module.cpython-312.pyc"
            pycache_file.write_bytes(b"compiled bytecode")

            def mock_load():
                pass

            sources = get_source_files(
                module_path=module_file,
                load_function=mock_load,
            )

            # Should only contain the Python file, not the cached file
            assert "test_module.py" in sources
            assert "__pycache__" not in sources
            assert len(sources) == 1

    def test_get_source_files_load_function_error(self):
        """Test error handling when load function raises an exception."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            module_file = temp_path / "test_module.py"
            module_file.write_text("class TestClass: pass")

            def failing_load():
                raise ValueError("Load failed")

            # Should still return sources even if load function fails
            sources = get_source_files(
                module_path=module_file,
                load_function=failing_load,
            )

            assert "test_module.py" in sources
