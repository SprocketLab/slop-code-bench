"""Exhaustive tests for Python import extraction and tracing.

Tests all functions in slop_code.metrics.languages.python.imports including:
- Public API: extract_imports, trace_source_files
- Helper functions: _parse_import_statement, _parse_import_from_statement,
  _parse_relative_import, _resolve_import, _resolve_absolute_import,
  _resolve_relative_import, _try_resolve_module
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

from slop_code.metrics.languages.python import extract_imports
from slop_code.metrics.languages.python import trace_source_files

# =============================================================================
# Extract Imports Tests
# =============================================================================


class TestExtractImports:
    """Tests for extract_imports function."""

    def test_simple_import(self, tmp_path):
        """Test extracting simple import statements."""
        test_file = tmp_path / "test.py"
        test_file.write_text("import os\n")

        imports = extract_imports(test_file)

        assert len(imports) == 1
        assert imports[0].module_path == "os"
        assert imports[0].is_relative is False
        assert imports[0].relative_level == 0
        assert imports[0].imported_names == []
        assert imports[0].line == 1

    def test_dotted_import(self, tmp_path):
        """Test extracting dotted import statements."""
        test_file = tmp_path / "test.py"
        test_file.write_text("import os.path\n")

        imports = extract_imports(test_file)

        assert len(imports) == 1
        assert imports[0].module_path == "os.path"
        assert imports[0].is_relative is False

    def test_import_as(self, tmp_path):
        """Test extracting aliased import statements."""
        test_file = tmp_path / "test.py"
        test_file.write_text("import numpy as np\n")

        imports = extract_imports(test_file)

        assert len(imports) == 1
        assert imports[0].module_path == "numpy"

    def test_from_import(self, tmp_path):
        """Test extracting from...import statements."""
        test_file = tmp_path / "test.py"
        test_file.write_text("from pathlib import Path\n")

        imports = extract_imports(test_file)

        assert len(imports) == 1
        assert imports[0].module_path == "pathlib"
        assert imports[0].is_relative is False
        assert imports[0].imported_names == ["Path"]

    def test_from_import_multiple(self, tmp_path):
        """Test extracting from...import with multiple names."""
        test_file = tmp_path / "test.py"
        test_file.write_text("from typing import List, Dict, Optional\n")

        imports = extract_imports(test_file)

        assert len(imports) == 1
        assert imports[0].module_path == "typing"
        assert set(imports[0].imported_names) == {"List", "Dict", "Optional"}

    def test_relative_import_single_dot(self, tmp_path):
        """Test extracting single dot relative import."""
        test_file = tmp_path / "test.py"
        test_file.write_text("from . import utils\n")

        imports = extract_imports(test_file)

        assert len(imports) == 1
        assert imports[0].is_relative is True
        assert imports[0].relative_level == 1
        assert imports[0].module_path is None
        assert imports[0].imported_names == ["utils"]

    def test_relative_import_with_module(self, tmp_path):
        """Test extracting relative import with module path."""
        test_file = tmp_path / "test.py"
        test_file.write_text("from .utils import helper\n")

        imports = extract_imports(test_file)

        assert len(imports) == 1
        assert imports[0].is_relative is True
        assert imports[0].relative_level == 1
        assert imports[0].module_path == "utils"
        assert imports[0].imported_names == ["helper"]

    def test_relative_import_double_dot(self, tmp_path):
        """Test extracting double dot relative import."""
        test_file = tmp_path / "test.py"
        test_file.write_text("from ..parent import something\n")

        imports = extract_imports(test_file)

        assert len(imports) == 1
        assert imports[0].is_relative is True
        assert imports[0].relative_level == 2
        assert imports[0].module_path == "parent"
        assert imports[0].imported_names == ["something"]

    def test_relative_import_triple_dot(self, tmp_path):
        """Test extracting triple dot relative import."""
        test_file = tmp_path / "test.py"
        test_file.write_text("from ...grandparent import item\n")

        imports = extract_imports(test_file)

        assert len(imports) == 1
        assert imports[0].is_relative is True
        assert imports[0].relative_level == 3

    def test_wildcard_import(self, tmp_path):
        """Test extracting wildcard import."""
        test_file = tmp_path / "test.py"
        test_file.write_text("from module import *\n")

        imports = extract_imports(test_file)

        assert len(imports) == 1
        assert imports[0].module_path == "module"
        assert "*" in imports[0].imported_names

    def test_multiple_imports(self, tmp_path):
        """Test extracting multiple import statements."""
        test_file = tmp_path / "test.py"
        test_file.write_text(dedent("""
        import os
        import sys
        from pathlib import Path
        from . import utils
        """))

        imports = extract_imports(test_file)

        assert len(imports) == 4
        module_paths = [i.module_path for i in imports]
        assert "os" in module_paths
        assert "sys" in module_paths
        assert "pathlib" in module_paths

    def test_empty_file(self, tmp_path):
        """Test extracting from empty file."""
        test_file = tmp_path / "test.py"
        test_file.write_text("")

        imports = extract_imports(test_file)

        assert imports == []

    def test_file_with_no_imports(self, tmp_path):
        """Test extracting from file with no imports."""
        test_file = tmp_path / "test.py"
        test_file.write_text("x = 1\ndef func():\n    pass\n")

        imports = extract_imports(test_file)

        assert imports == []

    def test_import_in_function(self, tmp_path):
        """Test that imports inside functions are still extracted."""
        test_file = tmp_path / "test.py"
        test_file.write_text(dedent("""
        def func():
            import os
            return os.getcwd()
        """))

        imports = extract_imports(test_file)

        assert len(imports) == 1
        assert imports[0].module_path == "os"

    def test_import_line_numbers(self, tmp_path):
        """Test that import line numbers are correct."""
        test_file = tmp_path / "test.py"
        # Don't use dedent with leading newline to keep line numbers predictable
        test_file.write_text("# Comment\nimport os\n\nimport sys\n")

        imports = extract_imports(test_file)

        assert len(imports) == 2
        os_import = next(i for i in imports if i.module_path == "os")
        sys_import = next(i for i in imports if i.module_path == "sys")
        assert os_import.line == 2
        assert sys_import.line == 4

    def test_multiline_import(self, tmp_path):
        """Test multiline import with parentheses."""
        test_file = tmp_path / "test.py"
        test_file.write_text(dedent("""
        from typing import (
            List,
            Dict,
            Optional,
        )
        """))

        imports = extract_imports(test_file)

        assert len(imports) == 1
        assert set(imports[0].imported_names) == {"List", "Dict", "Optional"}


# =============================================================================
# Trace Source Files Tests
# =============================================================================


class TestTraceSourceFiles:
    """Tests for trace_source_files function."""

    def test_single_file_no_imports(self, tmp_path):
        """Test tracing a single file with no local imports."""
        (tmp_path / "main.py").write_text("x = 1\n")

        result = trace_source_files(tmp_path / "main.py", tmp_path)

        assert len(result) == 1
        assert Path("main.py") in result

    def test_simple_local_import(self, tmp_path):
        """Test tracing with a simple local import."""
        (tmp_path / "main.py").write_text("from utils import x\n")
        (tmp_path / "utils.py").write_text("x = 1\n")

        result = trace_source_files(tmp_path / "main.py", tmp_path)

        assert Path("main.py") in result
        assert Path("utils.py") in result

    def test_chained_imports(self, tmp_path):
        """Test tracing with chained imports."""
        (tmp_path / "main.py").write_text("from a import x\n")
        (tmp_path / "a.py").write_text("from b import y\nx = y\n")
        (tmp_path / "b.py").write_text("y = 1\n")

        result = trace_source_files(tmp_path / "main.py", tmp_path)

        assert Path("main.py") in result
        assert Path("a.py") in result
        assert Path("b.py") in result

    def test_package_import(self, tmp_path):
        """Test tracing package imports."""
        (tmp_path / "main.py").write_text("from pkg.module import func\n")
        pkg_dir = tmp_path / "pkg"
        pkg_dir.mkdir()
        (pkg_dir / "__init__.py").write_text("")
        (pkg_dir / "module.py").write_text("def func(): pass\n")

        result = trace_source_files(tmp_path / "main.py", tmp_path)

        assert Path("main.py") in result
        assert Path("pkg/module.py") in result

    def test_relative_import(self, tmp_path):
        """Test tracing relative imports."""
        pkg_dir = tmp_path / "pkg"
        pkg_dir.mkdir()
        (pkg_dir / "__init__.py").write_text("")
        (pkg_dir / "main.py").write_text("from .utils import helper\n")
        (pkg_dir / "utils.py").write_text("def helper(): pass\n")

        result = trace_source_files(pkg_dir / "main.py", tmp_path)

        assert Path("pkg/main.py") in result
        assert Path("pkg/utils.py") in result

    def test_circular_imports(self, tmp_path):
        """Test handling circular imports."""
        (tmp_path / "a.py").write_text("from b import x\ny = 1\n")
        (tmp_path / "b.py").write_text("from a import y\nx = 2\n")

        result = trace_source_files(tmp_path / "a.py", tmp_path)

        assert Path("a.py") in result
        assert Path("b.py") in result
        assert len(result) == 2

    def test_nonexistent_entrypoint(self, tmp_path):
        """Test with nonexistent entrypoint file."""
        result = trace_source_files(tmp_path / "nonexistent.py", tmp_path)

        assert result == set()

    def test_stdlib_imports_not_traced(self, tmp_path):
        """Test that stdlib imports are not traced."""
        (tmp_path / "main.py").write_text("import os\nimport sys\n")

        result = trace_source_files(tmp_path / "main.py", tmp_path)

        # Only main.py should be in results, not stdlib modules
        assert len(result) == 1
        assert Path("main.py") in result

    def test_mixed_local_and_stdlib(self, tmp_path):
        """Test with both local and stdlib imports."""
        (tmp_path / "main.py").write_text("import os\nfrom utils import x\n")
        (tmp_path / "utils.py").write_text("x = 1\n")

        result = trace_source_files(tmp_path / "main.py", tmp_path)

        assert Path("main.py") in result
        assert Path("utils.py") in result
        assert len(result) == 2

    def test_import_absolute_local_module(self, tmp_path):
        """Test importing local module with absolute import."""
        (tmp_path / "main.py").write_text("import local_module\n")
        (tmp_path / "local_module.py").write_text("x = 1\n")

        result = trace_source_files(tmp_path / "main.py", tmp_path)

        assert Path("main.py") in result
        assert Path("local_module.py") in result

    def test_deep_nested_packages(self, tmp_path):
        """Test tracing through deeply nested packages."""
        (tmp_path / "main.py").write_text("from pkg.sub.module import func\n")

        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")

        sub = pkg / "sub"
        sub.mkdir()
        (sub / "__init__.py").write_text("")
        (sub / "module.py").write_text("def func(): pass\n")

        result = trace_source_files(tmp_path / "main.py", tmp_path)

        assert Path("main.py") in result
        assert Path("pkg/sub/module.py") in result

    def test_package_init_import(self, tmp_path):
        """Test importing a package (uses __init__.py)."""
        (tmp_path / "main.py").write_text("import mypackage\n")

        pkg = tmp_path / "mypackage"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("x = 1\n")

        result = trace_source_files(tmp_path / "main.py", tmp_path)

        assert Path("main.py") in result
        # Should include __init__.py
        assert Path("mypackage/__init__.py") in result

    def test_missing_imported_module(self, tmp_path):
        """Test graceful handling of missing imported module."""
        (tmp_path / "main.py").write_text("from nonexistent import something\n")

        result = trace_source_files(tmp_path / "main.py", tmp_path)

        # Should still include main.py
        assert Path("main.py") in result
        assert len(result) == 1

    def test_parent_relative_import(self, tmp_path):
        """Test relative import going to parent package."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "utils.py").write_text("def helper(): pass\n")

        sub = pkg / "sub"
        sub.mkdir()
        (sub / "__init__.py").write_text("")
        (sub / "main.py").write_text("from ..utils import helper\n")

        result = trace_source_files(sub / "main.py", tmp_path)

        assert Path("pkg/sub/main.py") in result
        assert Path("pkg/utils.py") in result


# =============================================================================
# Edge Cases
# =============================================================================


class TestImportEdgeCases:
    """Edge case tests for import extraction and tracing."""

    def test_import_with_as_alias(self, tmp_path):
        """Test import with 'as' alias."""
        test_file = tmp_path / "test.py"
        test_file.write_text("from os.path import join as path_join\n")

        imports = extract_imports(test_file)

        assert len(imports) == 1
        assert imports[0].module_path == "os.path"

    def test_multiple_imports_same_module(self, tmp_path):
        """Test multiple imports from same module."""
        test_file = tmp_path / "test.py"
        test_file.write_text(dedent("""
        from typing import List
        from typing import Dict
        """))

        imports = extract_imports(test_file)

        assert len(imports) == 2

    def test_conditional_import(self, tmp_path):
        """Test import inside if block."""
        test_file = tmp_path / "test.py"
        test_file.write_text(dedent("""
        import sys
        if sys.version_info >= (3, 10):
            from typing import ParamSpec
        else:
            from typing_extensions import ParamSpec
        """))

        imports = extract_imports(test_file)

        # All imports should be extracted
        assert len(imports) == 3

    def test_try_except_import(self, tmp_path):
        """Test import inside try/except."""
        test_file = tmp_path / "test.py"
        test_file.write_text(dedent("""
        try:
            import ujson as json
        except ImportError:
            import json
        """))

        imports = extract_imports(test_file)

        assert len(imports) == 2

    def test_future_import(self, tmp_path):
        """Test __future__ import.

        Note: __future__ imports may be skipped by implementation as they
        don't represent actual module dependencies.
        """
        test_file = tmp_path / "test.py"
        test_file.write_text("from __future__ import annotations\n")

        imports = extract_imports(test_file)

        # __future__ imports may be skipped or extracted
        # Just verify no crash
        assert isinstance(imports, list)

    def test_syntax_error_file(self, tmp_path):
        """Test with file containing syntax error."""
        test_file = tmp_path / "test.py"
        test_file.write_text("import os\ndef broken(:\n    pass\n")

        # Should handle gracefully - may return partial results or empty
        imports = extract_imports(test_file)
        # Just ensure it doesn't crash
        assert isinstance(imports, list)
