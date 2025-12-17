"""Tests for Python-specific quality metrics."""

from __future__ import annotations

import json
import subprocess
from unittest.mock import MagicMock

from slop_code.metrics.languages.python import calculate_line_metrics
from slop_code.metrics.languages.python import calculate_lint_metrics
from slop_code.metrics.languages.python import calculate_mi
from slop_code.metrics.languages.python import get_symbols


class TestCalculateMI:
    """Tests for calculate_mi function."""

    def test_calculate_mi(self, tmp_path, monkeypatch):
        """Test calculating maintainability index."""
        test_file = tmp_path / "test.py"
        test_file.write_text("def hello():\n    print('world')\n")

        # Mock radon.metrics.mi_visit to return a predictable value
        mock_mi_visit = MagicMock(return_value=75.5)
        monkeypatch.setattr(
            "slop_code.metrics.languages.python.line_metrics.radon.metrics.mi_visit",
            mock_mi_visit,
        )

        mi = calculate_mi(test_file)

        assert mi == 75.5
        # Verify it was called with the file contents and multi=False
        mock_mi_visit.assert_called_once_with("def hello():\n    print('world')\n", multi=False)

    def test_calculate_mi_caches_file_reads(self, tmp_path, monkeypatch):
        """Test that _get_code caching works."""
        test_file = tmp_path / "cached.py"
        test_file.write_text("print('cached')")

        mock_mi_visit = MagicMock(return_value=80.0)
        monkeypatch.setattr(
            "slop_code.metrics.languages.python.line_metrics.radon.metrics.mi_visit",
            mock_mi_visit,
        )

        # Call multiple times
        calculate_mi(test_file)
        calculate_mi(test_file)

        # Both calls should use the same cached content
        assert mock_mi_visit.call_count == 2


class TestCalculateLineMetrics:
    """Tests for calculate_line_metrics function."""

    def test_calculate_line_metrics(self, tmp_path, monkeypatch):
        """Test calculating line metrics from radon output."""
        test_file = tmp_path / "test.py"
        test_file.write_text("# comment\ndef func():\n    pass\n")

        # Mock radon.raw.analyze to return predictable metrics
        mock_raw_metrics = MagicMock()
        mock_raw_metrics.loc = 100  # Total lines
        mock_raw_metrics.sloc = 75  # Source lines of code
        mock_raw_metrics.comments = 20  # Total comments
        mock_raw_metrics.multi = 10  # Multi-line comments
        mock_raw_metrics.single_comments = 10  # Single-line comments

        mock_analyze = MagicMock(return_value=mock_raw_metrics)
        monkeypatch.setattr(
            "slop_code.metrics.languages.python.line_metrics.radon.raw.analyze",
            mock_analyze,
        )

        metrics = calculate_line_metrics(test_file)

        assert metrics.total_lines == 100
        assert metrics.loc == 75
        assert metrics.comments == 20
        assert metrics.multi_comment == 10
        assert metrics.single_comment == 10

    def test_calculate_line_metrics_empty_file(self, tmp_path, monkeypatch):
        """Test calculating metrics for an empty file."""
        test_file = tmp_path / "empty.py"
        test_file.write_text("")

        mock_raw_metrics = MagicMock()
        mock_raw_metrics.loc = 0
        mock_raw_metrics.sloc = 0
        mock_raw_metrics.comments = 0
        mock_raw_metrics.multi = 0
        mock_raw_metrics.single_comments = 0

        mock_analyze = MagicMock(return_value=mock_raw_metrics)
        monkeypatch.setattr(
            "slop_code.metrics.languages.python.line_metrics.radon.raw.analyze",
            mock_analyze,
        )

        metrics = calculate_line_metrics(test_file)

        assert metrics.total_lines == 0
        assert metrics.loc == 0
        assert metrics.comments == 0


class TestCalculateLintMetrics:
    """Tests for calculate_lint_metrics function."""

    def test_calculate_lint_metrics_with_errors(self, tmp_path, monkeypatch):
        """Test parsing ruff JSON output with lint errors."""
        test_file = tmp_path / "test.py"
        test_file.write_text("def func():\n    x=1\n")

        # Mock ruff output
        ruff_output = json.dumps([
            {"code": "E501", "count": 3, "fixable": True},
            {"code": "E302", "count": 2, "fixable": False},
            {"code": "W503", "count": 1, "fixable": True},
        ])

        mock_result = MagicMock()
        mock_result.stdout = ruff_output
        mock_result.returncode = 1

        mock_run = MagicMock(return_value=mock_result)
        monkeypatch.setattr("subprocess.run", mock_run)

        metrics = calculate_lint_metrics(test_file)

        assert metrics.errors == 6  # 3 + 2 + 1
        assert metrics.fixable == 4  # 3 + 1
        assert metrics.counts["E501"] == 3
        assert metrics.counts["E302"] == 2
        assert metrics.counts["W503"] == 1

        # Verify subprocess was called with correct args
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert call_args[0:3] == ["uv", "run", "ruff"]
        assert str(test_file.absolute()) in call_args

    def test_calculate_lint_metrics_no_errors(self, tmp_path, monkeypatch):
        """Test with clean code (no lint errors)."""
        test_file = tmp_path / "clean.py"
        test_file.write_text("def func():\n    pass\n")

        # Empty ruff output (no errors)
        mock_result = MagicMock()
        mock_result.stdout = "[]"
        mock_result.returncode = 0

        mock_run = MagicMock(return_value=mock_result)
        monkeypatch.setattr("subprocess.run", mock_run)

        metrics = calculate_lint_metrics(test_file)

        assert metrics.errors == 0
        assert metrics.fixable == 0
        assert metrics.counts == {}

    def test_calculate_lint_metrics_malformed_json(self, tmp_path, monkeypatch):
        """Test handling malformed JSON output with multiple lines."""
        test_file = tmp_path / "test.py"
        test_file.write_text("code")

        # Multi-line malformed output that will eventually be exhausted
        mock_result = MagicMock()
        mock_result.stdout = "invalid json line 1\ninvalid json line 2\n"
        mock_result.returncode = 1

        mock_run = MagicMock(return_value=mock_result)
        monkeypatch.setattr("subprocess.run", mock_run)

        metrics = calculate_lint_metrics(test_file)

        # Should return zero metrics on parse failure
        assert metrics.errors == 0
        assert metrics.fixable == 0
        assert metrics.counts == {}

    def test_calculate_lint_metrics_with_prefix(self, tmp_path, monkeypatch):
        """Test parsing JSON that has a prefix before the actual JSON."""
        test_file = tmp_path / "test.py"
        test_file.write_text("code")

        # Simulate output with a warning prefix
        ruff_output = 'Warning: something\n[{"code": "E501", "count": 1, "fixable": true}]'

        mock_result = MagicMock()
        mock_result.stdout = ruff_output
        mock_result.returncode = 1

        mock_run = MagicMock(return_value=mock_result)
        monkeypatch.setattr("subprocess.run", mock_run)

        metrics = calculate_lint_metrics(test_file)

        # Should skip the first line and parse the JSON
        assert metrics.errors == 1
        assert metrics.fixable == 1
        assert metrics.counts["E501"] == 1

    def test_calculate_lint_metrics_subprocess_error(self, tmp_path, monkeypatch):
        """Test handling subprocess errors gracefully."""
        test_file = tmp_path / "test.py"
        test_file.write_text("code")

        # Mock subprocess to raise CalledProcessError
        mock_run = MagicMock(side_effect=subprocess.CalledProcessError(1, "ruff"))
        monkeypatch.setattr("subprocess.run", mock_run)

        metrics = calculate_lint_metrics(test_file)

        # Should return zero metrics on error
        assert metrics.errors == 0
        assert metrics.fixable == 0
        assert metrics.counts == {}


class TestGetSymbols:
    """Tests for get_symbols function using tree-sitter.

    These tests compare get_symbols output against radon's cyclomatic
    complexity calculations to ensure accuracy.
    """

    def _get_radon_complexity(self, file_path) -> dict[str, int]:
        """Run radon cc on a file and return a dict of name -> complexity."""
        import re

        result = subprocess.run(
            ["uv", "run", "radon", "cc", "-s", str(file_path)],
            capture_output=True,
            text=True,
            check=True,
        )

        # Parse radon output: "    F 1:0 func_name - A (5)"
        pattern = re.compile(
            r"^\s+([FMC])\s+(\d+):(\d+)\s+(\S+(?:\.\S+)*)\s+-\s+([A-F])\s+\((\d+)\)",
            re.MULTILINE,
        )

        complexities = {}
        for match in pattern.finditer(result.stdout):
            kind, line, col, name, rating, cc = match.groups()
            complexities[name] = int(cc)

        return complexities

    def test_simple_function_matches_radon(self, tmp_path):
        """Test simple function complexity matches radon."""
        test_file = tmp_path / "test.py"
        test_file.write_text("""def hello():
    print("world")
""")
        symbols = get_symbols(test_file)
        radon_cc = self._get_radon_complexity(test_file)

        func = next(s for s in symbols if s.name == "hello")
        assert func.complexity == radon_cc["hello"]

    def test_if_elif_else_matches_radon(self, tmp_path):
        """Test if/elif/else complexity matches radon."""
        test_file = tmp_path / "test.py"
        test_file.write_text("""def classify(x):
    if x > 0:
        return "positive"
    elif x < 0:
        return "negative"
    else:
        return "zero"
""")
        symbols = get_symbols(test_file)
        radon_cc = self._get_radon_complexity(test_file)

        func = next(s for s in symbols if s.name == "classify")
        assert func.complexity == radon_cc["classify"]

    def test_nested_if_matches_radon(self, tmp_path):
        """Test nested if statements complexity matches radon."""
        test_file = tmp_path / "test.py"
        test_file.write_text("""def nested_check(a, b, c):
    if a:
        if b:
            if c:
                return "all true"
            return "a and b"
        return "only a"
    return "none"
""")
        symbols = get_symbols(test_file)
        radon_cc = self._get_radon_complexity(test_file)

        func = next(s for s in symbols if s.name == "nested_check")
        assert func.complexity == radon_cc["nested_check"]

    def test_for_loop_matches_radon(self, tmp_path):
        """Test for loop complexity matches radon."""
        test_file = tmp_path / "test.py"
        test_file.write_text("""def sum_list(items):
    total = 0
    for item in items:
        total += item
    return total
""")
        symbols = get_symbols(test_file)
        radon_cc = self._get_radon_complexity(test_file)

        func = next(s for s in symbols if s.name == "sum_list")
        assert func.complexity == radon_cc["sum_list"]

    def test_while_loop_matches_radon(self, tmp_path):
        """Test while loop complexity matches radon."""
        test_file = tmp_path / "test.py"
        test_file.write_text("""def countdown(n):
    while n > 0:
        print(n)
        n -= 1
    return "done"
""")
        symbols = get_symbols(test_file)
        radon_cc = self._get_radon_complexity(test_file)

        func = next(s for s in symbols if s.name == "countdown")
        assert func.complexity == radon_cc["countdown"]

    def test_nested_loops_matches_radon(self, tmp_path):
        """Test nested loops complexity matches radon."""
        test_file = tmp_path / "test.py"
        test_file.write_text("""def matrix_sum(matrix):
    total = 0
    for row in matrix:
        for cell in row:
            total += cell
    return total
""")
        symbols = get_symbols(test_file)
        radon_cc = self._get_radon_complexity(test_file)

        func = next(s for s in symbols if s.name == "matrix_sum")
        assert func.complexity == radon_cc["matrix_sum"]

    def test_boolean_and_matches_radon(self, tmp_path):
        """Test boolean 'and' operator complexity matches radon."""
        test_file = tmp_path / "test.py"
        test_file.write_text("""def check_both(a, b):
    if a and b:
        return True
    return False
""")
        symbols = get_symbols(test_file)
        radon_cc = self._get_radon_complexity(test_file)

        func = next(s for s in symbols if s.name == "check_both")
        assert func.complexity == radon_cc["check_both"]

    def test_boolean_or_matches_radon(self, tmp_path):
        """Test boolean 'or' operator complexity matches radon."""
        test_file = tmp_path / "test.py"
        test_file.write_text("""def check_either(a, b):
    if a or b:
        return True
    return False
""")
        symbols = get_symbols(test_file)
        radon_cc = self._get_radon_complexity(test_file)

        func = next(s for s in symbols if s.name == "check_either")
        assert func.complexity == radon_cc["check_either"]

    def test_complex_boolean_matches_radon(self, tmp_path):
        """Test complex boolean expression matches radon."""
        test_file = tmp_path / "test.py"
        test_file.write_text("""def complex_check(a, b, c, d):
    if (a and b) or (c and d):
        return True
    return False
""")
        symbols = get_symbols(test_file)
        radon_cc = self._get_radon_complexity(test_file)

        func = next(s for s in symbols if s.name == "complex_check")
        assert func.complexity == radon_cc["complex_check"]

    def test_try_except_matches_radon(self, tmp_path):
        """Test try/except complexity matches radon."""
        test_file = tmp_path / "test.py"
        test_file.write_text("""def safe_divide(a, b):
    try:
        return a / b
    except ZeroDivisionError:
        return 0
""")
        symbols = get_symbols(test_file)
        radon_cc = self._get_radon_complexity(test_file)

        func = next(s for s in symbols if s.name == "safe_divide")
        assert func.complexity == radon_cc["safe_divide"]

    def test_multiple_except_matches_radon(self, tmp_path):
        """Test multiple except clauses complexity matches radon."""
        test_file = tmp_path / "test.py"
        test_file.write_text("""def parse_value(value):
    try:
        return int(value)
    except ValueError:
        return 0
    except TypeError:
        return -1
    except Exception:
        return None
""")
        symbols = get_symbols(test_file)
        radon_cc = self._get_radon_complexity(test_file)

        func = next(s for s in symbols if s.name == "parse_value")
        assert func.complexity == radon_cc["parse_value"]

    def test_list_comprehension_matches_radon(self, tmp_path):
        """Test list comprehension complexity matches radon."""
        test_file = tmp_path / "test.py"
        test_file.write_text("""def get_squares(items):
    return [x**2 for x in items]
""")
        symbols = get_symbols(test_file)
        radon_cc = self._get_radon_complexity(test_file)

        func = next(s for s in symbols if s.name == "get_squares")
        assert func.complexity == radon_cc["get_squares"]

    def test_comprehension_with_condition_matches_radon(self, tmp_path):
        """Test comprehension with condition matches radon."""
        test_file = tmp_path / "test.py"
        test_file.write_text("""def get_evens(items):
    return [x for x in items if x % 2 == 0]
""")
        symbols = get_symbols(test_file)
        radon_cc = self._get_radon_complexity(test_file)

        func = next(s for s in symbols if s.name == "get_evens")
        assert func.complexity == radon_cc["get_evens"]

    def test_dict_comprehension_matches_radon(self, tmp_path):
        """Test dict comprehension complexity matches radon."""
        test_file = tmp_path / "test.py"
        test_file.write_text("""def make_dict(keys, values):
    return {k: v for k, v in zip(keys, values)}
""")
        symbols = get_symbols(test_file)
        radon_cc = self._get_radon_complexity(test_file)

        func = next(s for s in symbols if s.name == "make_dict")
        assert func.complexity == radon_cc["make_dict"]

    def test_generator_expression_matches_radon(self, tmp_path):
        """Test generator expression complexity matches radon."""
        test_file = tmp_path / "test.py"
        test_file.write_text("""def get_sum(items):
    return sum(x**2 for x in items)
""")
        symbols = get_symbols(test_file)
        radon_cc = self._get_radon_complexity(test_file)

        func = next(s for s in symbols if s.name == "get_sum")
        assert func.complexity == radon_cc["get_sum"]

    def test_ternary_expression_matches_radon(self, tmp_path):
        """Test ternary/conditional expression matches radon."""
        test_file = tmp_path / "test.py"
        test_file.write_text("""def get_sign(x):
    return "positive" if x > 0 else "non-positive"
""")
        symbols = get_symbols(test_file)
        radon_cc = self._get_radon_complexity(test_file)

        func = next(s for s in symbols if s.name == "get_sign")
        assert func.complexity == radon_cc["get_sign"]

    def test_assert_matches_radon(self, tmp_path):
        """Test assert statement complexity matches radon."""
        test_file = tmp_path / "test.py"
        test_file.write_text("""def validate(x):
    assert x > 0
    assert x < 100
    return x
""")
        symbols = get_symbols(test_file)
        radon_cc = self._get_radon_complexity(test_file)

        func = next(s for s in symbols if s.name == "validate")
        assert func.complexity == radon_cc["validate"]

    def test_with_statement_matches_radon(self, tmp_path):
        """Test with statement complexity matches radon."""
        test_file = tmp_path / "test.py"
        test_file.write_text("""def read_file(path):
    with open(path) as f:
        return f.read()
""")
        symbols = get_symbols(test_file)
        radon_cc = self._get_radon_complexity(test_file)

        func = next(s for s in symbols if s.name == "read_file")
        assert func.complexity == radon_cc["read_file"]

    def test_class_method_matches_radon(self, tmp_path):
        """Test class method complexity matches radon."""
        test_file = tmp_path / "test.py"
        test_file.write_text("""class Calculator:
    def add(self, a, b):
        if a < 0 or b < 0:
            return 0
        return a + b

    def multiply(self, a, b):
        result = 0
        for _ in range(b):
            result += a
        return result
""")
        symbols = get_symbols(test_file)
        radon_cc = self._get_radon_complexity(test_file)

        add_method = next(s for s in symbols if s.name == "add")
        multiply_method = next(s for s in symbols if s.name == "multiply")

        assert add_method.complexity == radon_cc["Calculator.add"]
        assert multiply_method.complexity == radon_cc["Calculator.multiply"]

    def test_complex_function_matches_radon(self, tmp_path):
        """Test complex function with multiple constructs matches radon."""
        test_file = tmp_path / "test.py"
        test_file.write_text("""def process_data(data, options):
    result = []
    for item in data:
        if item is None:
            continue
        if options.get("filter") and item < 0:
            continue
        try:
            processed = item * 2
            if processed > 100:
                processed = 100
            elif processed < -100:
                processed = -100
            result.append(processed)
        except TypeError:
            pass
    return result if result else None
""")
        symbols = get_symbols(test_file)
        radon_cc = self._get_radon_complexity(test_file)

        func = next(s for s in symbols if s.name == "process_data")
        assert func.complexity == radon_cc["process_data"]

    def test_very_complex_function_matches_radon(self, tmp_path):
        """Test very complex function matches radon."""
        test_file = tmp_path / "test.py"
        test_file.write_text("""def state_machine(state, events):
    for event in events:
        if state == "idle":
            if event == "start":
                state = "running"
            elif event == "error":
                state = "error"
        elif state == "running":
            if event == "pause":
                state = "paused"
            elif event == "stop":
                state = "idle"
            elif event == "error":
                state = "error"
        elif state == "paused":
            if event == "resume":
                state = "running"
            elif event == "stop":
                state = "idle"
        elif state == "error":
            if event == "reset":
                state = "idle"
    return state
""")
        symbols = get_symbols(test_file)
        radon_cc = self._get_radon_complexity(test_file)

        func = next(s for s in symbols if s.name == "state_machine")
        assert func.complexity == radon_cc["state_machine"]

    def test_multiple_functions_match_radon(self, tmp_path):
        """Test multiple functions all match radon."""
        test_file = tmp_path / "test.py"
        test_file.write_text("""def func_a(x):
    return x + 1

def func_b(x):
    if x > 0:
        return x
    return -x

def func_c(items):
    total = 0
    for item in items:
        if item > 0:
            total += item
    return total

def func_d(a, b, c):
    if a and b and c:
        return True
    if a or b or c:
        return None
    return False
""")
        symbols = get_symbols(test_file)
        radon_cc = self._get_radon_complexity(test_file)

        for func_name in ["func_a", "func_b", "func_c", "func_d"]:
            func = next(s for s in symbols if s.name == func_name)
            assert func.complexity == radon_cc[func_name], (
                f"{func_name}: tree-sitter={func.complexity}, radon={radon_cc[func_name]}"
            )

    def test_rating_matches_radon(self, tmp_path):
        """Test that computed rating matches radon's rating."""
        import re

        test_file = tmp_path / "test.py"
        test_file.write_text("""def simple():
    pass

def moderate(x):
    if x > 0:
        if x > 10:
            if x > 100:
                return "large"
            return "medium"
        return "small"
    return "negative"
""")
        symbols = get_symbols(test_file)

        # Get radon ratings
        result = subprocess.run(
            ["uv", "run", "radon", "cc", "-s", str(test_file)],
            capture_output=True,
            text=True,
            check=True,
        )

        pattern = re.compile(
            r"^\s+([FMC])\s+(\d+):(\d+)\s+(\S+)\s+-\s+([A-F])\s+\((\d+)\)",
            re.MULTILINE,
        )

        radon_ratings = {}
        for match in pattern.finditer(result.stdout):
            kind, line, col, name, rating, cc = match.groups()
            radon_ratings[name] = rating

        for func_name in ["simple", "moderate"]:
            func = next(s for s in symbols if s.name == func_name)
            assert func.rating == radon_ratings[func_name], (
                f"{func_name}: tree-sitter={func.rating}, radon={radon_ratings[func_name]}"
            )

    def test_empty_file(self, tmp_path):
        """Test with an empty file."""
        test_file = tmp_path / "empty.py"
        test_file.write_text("")

        symbols = get_symbols(test_file)
        assert symbols == []

    def test_extracts_variables(self, tmp_path):
        """Test extracting module-level variables."""
        test_file = tmp_path / "test.py"
        test_file.write_text("""x = 1
y = 2
CONSTANT = "value"
""")
        symbols = get_symbols(test_file)

        names = {s.name for s in symbols}
        assert names == {"x", "y", "CONSTANT"}
        for s in symbols:
            assert s.type == "variable"
            assert s.complexity == 0

    def test_extracts_type_alias(self, tmp_path):
        """Test extracting type aliases."""
        test_file = tmp_path / "test.py"
        test_file.write_text("""type IntList = list[int]
""")
        symbols = get_symbols(test_file)

        names = {s.name for s in symbols}
        assert "IntList" in names
        type_alias = next(s for s in symbols if s.name == "IntList")
        assert type_alias.type == "type_alias"

    def test_extracts_nested_functions(self, tmp_path):
        """Test extracting nested functions.

        Note: radon only reports the outer function, not nested functions.
        Our implementation extracts both for completeness.
        """
        test_file = tmp_path / "test.py"
        test_file.write_text("""def outer():
    def inner():
        pass
    return inner
""")
        symbols = get_symbols(test_file)
        radon_cc = self._get_radon_complexity(test_file)

        names = {s.name for s in symbols}
        assert "outer" in names
        assert "inner" in names

        # Verify outer complexity matches radon
        outer = next(s for s in symbols if s.name == "outer")
        assert outer.complexity == radon_cc["outer"]

        # Inner function is extracted but not reported by radon
        inner = next(s for s in symbols if s.name == "inner")
        assert inner.complexity == 1  # Base complexity for simple function

    def test_extracts_async_functions(self, tmp_path):
        """Test extracting async functions."""
        test_file = tmp_path / "test.py"
        test_file.write_text("""async def fetch(url):
    if url.startswith("https"):
        return await do_fetch(url)
    return None
""")
        symbols = get_symbols(test_file)
        radon_cc = self._get_radon_complexity(test_file)

        func = next(s for s in symbols if s.name == "fetch")
        assert func.complexity == radon_cc["fetch"]

    def test_position_accuracy(self, tmp_path):
        """Test that positions are accurate."""
        test_file = tmp_path / "test.py"
        test_file.write_text("""# Comment
x = 1

def func():
    pass

class Cls:
    pass
""")
        symbols = get_symbols(test_file)

        var = next(s for s in symbols if s.name == "x")
        assert var.start == 2
        assert var.start_col == 0

        func = next(s for s in symbols if s.name == "func")
        assert func.start == 4

        cls = next(s for s in symbols if s.name == "Cls")
        assert cls.start == 7


class TestExtractImports:
    """Tests for extract_imports function using tree-sitter."""

    def test_simple_import(self, tmp_path):
        """Test extracting simple import statements."""
        from slop_code.metrics.languages.python import extract_imports

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
        from slop_code.metrics.languages.python import extract_imports

        test_file = tmp_path / "test.py"
        test_file.write_text("import os.path\n")

        imports = extract_imports(test_file)

        assert len(imports) == 1
        assert imports[0].module_path == "os.path"
        assert imports[0].is_relative is False

    def test_import_as(self, tmp_path):
        """Test extracting aliased import statements."""
        from slop_code.metrics.languages.python import extract_imports

        test_file = tmp_path / "test.py"
        test_file.write_text("import numpy as np\n")

        imports = extract_imports(test_file)

        assert len(imports) == 1
        assert imports[0].module_path == "numpy"

    def test_from_import(self, tmp_path):
        """Test extracting from...import statements."""
        from slop_code.metrics.languages.python import extract_imports

        test_file = tmp_path / "test.py"
        test_file.write_text("from pathlib import Path\n")

        imports = extract_imports(test_file)

        assert len(imports) == 1
        assert imports[0].module_path == "pathlib"
        assert imports[0].is_relative is False
        assert imports[0].imported_names == ["Path"]

    def test_from_import_multiple(self, tmp_path):
        """Test extracting from...import with multiple names."""
        from slop_code.metrics.languages.python import extract_imports

        test_file = tmp_path / "test.py"
        test_file.write_text("from typing import List, Dict, Optional\n")

        imports = extract_imports(test_file)

        assert len(imports) == 1
        assert imports[0].module_path == "typing"
        assert set(imports[0].imported_names) == {"List", "Dict", "Optional"}

    def test_relative_import_single_dot(self, tmp_path):
        """Test extracting single dot relative import."""
        from slop_code.metrics.languages.python import extract_imports

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
        from slop_code.metrics.languages.python import extract_imports

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
        from slop_code.metrics.languages.python import extract_imports

        test_file = tmp_path / "test.py"
        test_file.write_text("from ..parent import something\n")

        imports = extract_imports(test_file)

        assert len(imports) == 1
        assert imports[0].is_relative is True
        assert imports[0].relative_level == 2
        assert imports[0].module_path == "parent"
        assert imports[0].imported_names == ["something"]

    def test_wildcard_import(self, tmp_path):
        """Test extracting wildcard import."""
        from slop_code.metrics.languages.python import extract_imports

        test_file = tmp_path / "test.py"
        test_file.write_text("from module import *\n")

        imports = extract_imports(test_file)

        assert len(imports) == 1
        assert imports[0].module_path == "module"
        assert "*" in imports[0].imported_names

    def test_multiple_imports(self, tmp_path):
        """Test extracting multiple import statements."""
        from slop_code.metrics.languages.python import extract_imports

        test_file = tmp_path / "test.py"
        test_file.write_text("""import os
import sys
from pathlib import Path
from . import utils
""")

        imports = extract_imports(test_file)

        assert len(imports) == 4
        module_paths = [i.module_path for i in imports]
        assert "os" in module_paths
        assert "sys" in module_paths
        assert "pathlib" in module_paths

    def test_empty_file(self, tmp_path):
        """Test extracting from empty file."""
        from slop_code.metrics.languages.python import extract_imports

        test_file = tmp_path / "test.py"
        test_file.write_text("")

        imports = extract_imports(test_file)

        assert imports == []

    def test_file_with_no_imports(self, tmp_path):
        """Test extracting from file with no imports."""
        from slop_code.metrics.languages.python import extract_imports

        test_file = tmp_path / "test.py"
        test_file.write_text("x = 1\ndef func():\n    pass\n")

        imports = extract_imports(test_file)

        assert imports == []


class TestTraceSourceFiles:
    """Tests for trace_source_files function."""

    def test_single_file_no_imports(self, tmp_path):
        """Test tracing a single file with no local imports."""
        from slop_code.metrics.languages.python import trace_source_files

        (tmp_path / "main.py").write_text("x = 1\n")

        result = trace_source_files(tmp_path / "main.py", tmp_path)

        assert len(result) == 1
        from pathlib import Path
        assert Path("main.py") in result

    def test_simple_local_import(self, tmp_path):
        """Test tracing with a simple local import."""
        from pathlib import Path

        from slop_code.metrics.languages.python import trace_source_files

        (tmp_path / "main.py").write_text("from utils import x\n")
        (tmp_path / "utils.py").write_text("x = 1\n")

        result = trace_source_files(tmp_path / "main.py", tmp_path)

        assert Path("main.py") in result
        assert Path("utils.py") in result

    def test_chained_imports(self, tmp_path):
        """Test tracing with chained imports."""
        from pathlib import Path

        from slop_code.metrics.languages.python import trace_source_files

        (tmp_path / "main.py").write_text("from a import x\n")
        (tmp_path / "a.py").write_text("from b import y\nx = y\n")
        (tmp_path / "b.py").write_text("y = 1\n")

        result = trace_source_files(tmp_path / "main.py", tmp_path)

        assert Path("main.py") in result
        assert Path("a.py") in result
        assert Path("b.py") in result

    def test_package_import(self, tmp_path):
        """Test tracing package imports."""
        from pathlib import Path

        from slop_code.metrics.languages.python import trace_source_files

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
        from pathlib import Path

        from slop_code.metrics.languages.python import trace_source_files

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
        from pathlib import Path

        from slop_code.metrics.languages.python import trace_source_files

        (tmp_path / "a.py").write_text("from b import x\ny = 1\n")
        (tmp_path / "b.py").write_text("from a import y\nx = 2\n")

        result = trace_source_files(tmp_path / "a.py", tmp_path)

        assert Path("a.py") in result
        assert Path("b.py") in result
        assert len(result) == 2

    def test_nonexistent_entrypoint(self, tmp_path):
        """Test with nonexistent entrypoint file."""
        from slop_code.metrics.languages.python import trace_source_files

        result = trace_source_files(tmp_path / "nonexistent.py", tmp_path)

        assert result == set()

    def test_stdlib_imports_not_traced(self, tmp_path):
        """Test that stdlib imports are not traced."""
        from pathlib import Path

        from slop_code.metrics.languages.python import trace_source_files

        (tmp_path / "main.py").write_text("import os\nimport sys\n")

        result = trace_source_files(tmp_path / "main.py", tmp_path)

        # Only main.py should be in results, not stdlib modules
        assert len(result) == 1
        assert Path("main.py") in result

    def test_mixed_local_and_stdlib(self, tmp_path):
        """Test with both local and stdlib imports."""
        from pathlib import Path

        from slop_code.metrics.languages.python import trace_source_files

        (tmp_path / "main.py").write_text("import os\nfrom utils import x\n")
        (tmp_path / "utils.py").write_text("x = 1\n")

        result = trace_source_files(tmp_path / "main.py", tmp_path)

        assert Path("main.py") in result
        assert Path("utils.py") in result
        assert len(result) == 2

    def test_import_absolute_local_module(self, tmp_path):
        """Test importing local module with absolute import."""
        from pathlib import Path

        from slop_code.metrics.languages.python import trace_source_files

        (tmp_path / "main.py").write_text("import local_module\n")
        (tmp_path / "local_module.py").write_text("x = 1\n")

        result = trace_source_files(tmp_path / "main.py", tmp_path)

        assert Path("main.py") in result
        assert Path("local_module.py") in result
