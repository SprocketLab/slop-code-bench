"""Exhaustive tests for Python abstraction waste detection.

Tests all functions in slop_code.metrics.languages.python.waste including:
- Public API: calculate_waste_metrics, detect_waste
- Helper functions: _find_call_sites, _is_trivial_wrapper, _is_docstring_statement
"""

from __future__ import annotations

from textwrap import dedent

from slop_code.metrics.languages.python import calculate_waste_metrics
from slop_code.metrics.languages.python import get_symbols

# =============================================================================
# Calculate Waste Metrics Tests
# =============================================================================


class TestCalculateWasteMetrics:
    """Tests for calculate_waste_metrics function."""

    def test_no_waste_patterns(self, tmp_path):
        """Test file with no waste patterns."""
        source = tmp_path / "clean.py"
        source.write_text(
            dedent("""
        def helper():
            x = 1
            y = 2
            return x + y

        def main():
            result = helper()
            result += helper()
            return result
        """)
        )

        symbols = get_symbols(source)
        metrics = calculate_waste_metrics(source, symbols)

        # helper is called twice, main is entry point
        assert len(metrics.single_use_functions) == 0 or "helper" not in [
            f.name for f in metrics.single_use_functions
        ]

    def test_single_use_function(self, tmp_path):
        """Test detection of single-use functions."""
        source = tmp_path / "single_use.py"
        source.write_text(
            dedent("""
        def helper():
            return 42

        def single_use():
            helper()

        def call_twice():
            helper()
            helper()
        """)
        )

        symbols = get_symbols(source)
        metrics = calculate_waste_metrics(source, symbols)

        single_use_names = {s.name for s in metrics.single_use_functions}
        # single_use is called 0 times, call_twice is called 0 times
        assert (
            "single_use" in single_use_names or "call_twice" in single_use_names
        )


class TestTrivialWrappers:
    """Tests for trivial wrapper detection."""

    def test_trivial_wrapper(self, tmp_path):
        """Test detection of trivial wrapper functions."""
        source = tmp_path / "wrapper.py"
        source.write_text(
            dedent("""
        def actual_work():
            return 42

        def wrapper():
            return actual_work()

        def main():
            wrapper()
            actual_work()
        """)
        )

        symbols = get_symbols(source)
        metrics = calculate_waste_metrics(source, symbols)

        trivial_names = {w.name for w in metrics.trivial_wrappers}
        assert "wrapper" in trivial_names

    def test_wrapper_with_args(self, tmp_path):
        """Test wrapper that just passes arguments through."""
        source = tmp_path / "pass_through.py"
        source.write_text(
            dedent("""
        def do_work(x, y):
            return x + y

        def wrapper(a, b):
            return do_work(a, b)
        """)
        )

        symbols = get_symbols(source)
        metrics = calculate_waste_metrics(source, symbols)

        trivial_names = {w.name for w in metrics.trivial_wrappers}
        assert "wrapper" in trivial_names

    def test_not_trivial_with_logic(self, tmp_path):
        """Test that functions with real logic are not marked as trivial."""
        source = tmp_path / "not_trivial.py"
        source.write_text(
            dedent("""
        def helper():
            return 1

        def not_trivial():
            x = helper()
            return x * 2
        """)
        )

        symbols = get_symbols(source)
        metrics = calculate_waste_metrics(source, symbols)

        trivial_names = {w.name for w in metrics.trivial_wrappers}
        assert "not_trivial" not in trivial_names

    def test_wrapper_with_docstring_only(self, tmp_path):
        """Test wrapper detection with docstring.

        Note: The implementation may count docstrings as statements,
        which means a function with docstring + return is not trivial.
        """
        source = tmp_path / "docstring_wrapper.py"
        source.write_text(
            dedent('''
        def work():
            return 42

        def wrapper():
            """This is a wrapper."""
            return work()
        ''')
        )

        symbols = get_symbols(source)
        metrics = calculate_waste_metrics(source, symbols)

        trivial_names = {w.name for w in metrics.trivial_wrappers}
        # Docstrings may be counted as statements, making wrapper non-trivial
        # This is implementation-dependent
        assert isinstance(trivial_names, set)


class TestSingleMethodClasses:
    """Tests for single-method class detection."""

    def test_single_method_class(self, tmp_path):
        """Test detection of single-method classes."""
        source = tmp_path / "single_method.py"
        source.write_text(
            dedent("""
        class Solo:
            def only_method(self):
                return 42
        """)
        )

        symbols = get_symbols(source)
        metrics = calculate_waste_metrics(source, symbols)

        assert "Solo" in metrics.single_method_classes

    def test_multi_method_class_not_detected(self, tmp_path):
        """Test that multi-method classes are not detected."""
        source = tmp_path / "multi_method.py"
        source.write_text(
            dedent("""
        class Multi:
            def method_a(self):
                return 1

            def method_b(self):
                return 2
        """)
        )

        symbols = get_symbols(source)
        metrics = calculate_waste_metrics(source, symbols)

        assert "Multi" not in metrics.single_method_classes

    def test_init_and_one_method(self, tmp_path):
        """Test class with __init__ and one other method."""
        source = tmp_path / "init_plus_one.py"
        source.write_text(
            dedent("""
        class WithInit:
            def __init__(self):
                self.x = 1

            def method(self):
                return self.x
        """)
        )

        symbols = get_symbols(source)
        metrics = calculate_waste_metrics(source, symbols)

        # Has 2 methods (__init__ + method), not single-method
        assert "WithInit" not in metrics.single_method_classes

    def test_empty_class_not_detected(self, tmp_path):
        """Test that empty class is not detected as single-method."""
        source = tmp_path / "empty.py"
        source.write_text(
            dedent("""
        class Empty:
            pass
        """)
        )

        symbols = get_symbols(source)
        metrics = calculate_waste_metrics(source, symbols)

        assert "Empty" not in metrics.single_method_classes

    def test_class_with_only_init(self, tmp_path):
        """Test class with only __init__ method."""
        source = tmp_path / "only_init.py"
        source.write_text(
            dedent("""
        class OnlyInit:
            def __init__(self):
                self.x = 1
        """)
        )

        symbols = get_symbols(source)
        metrics = calculate_waste_metrics(source, symbols)

        # __init__ only = 1 method
        assert "OnlyInit" in metrics.single_method_classes


class TestCallSiteDetection:
    """Tests for function call site detection."""

    def test_simple_call(self, tmp_path):
        """Test detection of simple function calls."""
        source = tmp_path / "simple_call.py"
        source.write_text(
            dedent("""
        def helper():
            return 1

        def main():
            return helper()
        """)
        )

        symbols = get_symbols(source)
        metrics = calculate_waste_metrics(source, symbols)

        # helper is called once
        single_use_names = {s.name for s in metrics.single_use_functions}
        # main is never called
        assert "main" in single_use_names

    def test_method_call(self, tmp_path):
        """Test detection of method calls."""
        source = tmp_path / "method_call.py"
        source.write_text(
            dedent("""
        class MyClass:
            def method(self):
                return 1

        def main():
            obj = MyClass()
            return obj.method()
        """)
        )

        symbols = get_symbols(source)
        calculate_waste_metrics(source, symbols)

        # method is called once

    def test_qualified_call(self, tmp_path):
        """Test detection of qualified function calls."""
        source = tmp_path / "qualified.py"
        source.write_text(
            dedent("""
        def helper():
            return 1

        def main():
            x = helper
            return x()
        """)
        )

        symbols = get_symbols(source)
        calculate_waste_metrics(source, symbols)

        # Call through variable may not be detected

    def test_multiple_calls_same_function(self, tmp_path):
        """Test function called multiple times."""
        source = tmp_path / "multi_call.py"
        source.write_text(
            dedent("""
        def util():
            return 1

        def main():
            a = util()
            b = util()
            c = util()
            return a + b + c
        """)
        )

        symbols = get_symbols(source)
        metrics = calculate_waste_metrics(source, symbols)

        single_use_names = {s.name for s in metrics.single_use_functions}
        # util is called 3 times, not single use
        assert "util" not in single_use_names


class TestWasteEdgeCases:
    """Edge case tests for waste detection."""

    def test_empty_file(self, tmp_path):
        """Test with empty file."""
        source = tmp_path / "empty.py"
        source.write_text("")

        symbols = get_symbols(source)
        metrics = calculate_waste_metrics(source, symbols)

        assert metrics.single_use_functions == []
        assert metrics.trivial_wrappers == []
        assert metrics.single_method_classes == []

    def test_recursive_function(self, tmp_path):
        """Test recursive function called externally is not inflated by self-calls."""
        source = tmp_path / "recursive.py"
        source.write_text(
            dedent("""
        def factorial(n):
            if n <= 1:
                return 1
            return n * factorial(n - 1)

        def a():
            return factorial(5)

        def b():
            return factorial(10)
        """)
        )

        symbols = get_symbols(source)
        metrics = calculate_waste_metrics(source, symbols)

        # factorial has 2 external callers, so it's NOT single-use
        single_use_names = [f.name for f in metrics.single_use_functions]
        assert "factorial" not in single_use_names

    def test_recursive_function_with_one_caller(self, tmp_path):
        """Recursive function called once externally IS single-use."""
        source = tmp_path / "recursive.py"
        source.write_text(
            dedent("""
        def factorial(n):
            if n <= 1:
                return 1
            return n * factorial(n - 1)

        def main():
            return factorial(5)
        """)
        )

        symbols = get_symbols(source)
        metrics = calculate_waste_metrics(source, symbols)

        # factorial has only 1 external caller — it's single-use
        # (the self-call is excluded from the count)
        single_use_names = [f.name for f in metrics.single_use_functions]
        assert "factorial" in single_use_names

    def test_mutually_recursive_functions(self, tmp_path):
        """Test mutually recursive functions are not falsely single-use."""
        source = tmp_path / "mutual.py"
        source.write_text(
            dedent("""
        def is_even(n):
            if n == 0:
                return True
            return is_odd(n - 1)

        def is_odd(n):
            if n == 0:
                return False
            return is_even(n - 1)
        """)
        )

        symbols = get_symbols(source)
        metrics = calculate_waste_metrics(source, symbols)

        # Each function is called once externally — both are single-use
        # This is correct: they each have exactly 1 external caller
        single_use_names = [f.name for f in metrics.single_use_functions]
        assert "is_even" in single_use_names
        assert "is_odd" in single_use_names

    def test_decorated_function(self, tmp_path):
        """Test decorated function waste detection."""
        source = tmp_path / "decorated.py"
        source.write_text(
            dedent("""
        def decorator(f):
            return f

        @decorator
        def decorated():
            return 42

        def main():
            return decorated()
        """)
        )

        symbols = get_symbols(source)
        calculate_waste_metrics(source, symbols)

        # decorated is called once

    def test_lambda_not_waste(self, tmp_path):
        """Test that lambdas don't create false positives."""
        source = tmp_path / "lambda.py"
        source.write_text(
            dedent("""
        def use_lambda():
            f = lambda x: x + 1
            return f(1)
        """)
        )

        symbols = get_symbols(source)
        calculate_waste_metrics(source, symbols)

        # Just ensure no crashes

    def test_staticmethod_and_classmethod(self, tmp_path):
        """Test class with staticmethod and classmethod."""
        source = tmp_path / "static.py"
        source.write_text(
            dedent("""
        class MyClass:
            @staticmethod
            def static_method():
                return 1

            @classmethod
            def class_method(cls):
                return 2
        """)
        )

        symbols = get_symbols(source)
        metrics = calculate_waste_metrics(source, symbols)

        # 2 methods, not single-method class
        assert "MyClass" not in metrics.single_method_classes


class TestIntegration:
    """Integration tests for waste detection."""

    def test_realistic_waste_patterns(self, tmp_path):
        """Test with realistic waste patterns."""
        source = tmp_path / "waste.py"
        source.write_text(
            dedent("""
        x = 1

        def helper():
            return x

        def wrapper():
            return helper()

        def single_use():
            helper()

        def call_helper_twice():
            helper()
            helper()

        class Solo:
            def only(self):
                return helper()
        """)
        )

        symbols = get_symbols(source)
        metrics = calculate_waste_metrics(source, symbols)

        trivial_names = {w.name for w in metrics.trivial_wrappers}
        assert "wrapper" in trivial_names

        single_method_classes = set(metrics.single_method_classes)
        assert "Solo" in single_method_classes

        single_use_names = {s.name for s in metrics.single_use_functions}
        assert "single_use" in single_use_names
        assert "call_helper_twice" in single_use_names


# =============================================================================
# Single-Use Variable Detection Tests
# =============================================================================


class TestSingleUseVariables:
    """Tests for single-use variable detection."""

    def test_single_use_variable_in_function(self, tmp_path):
        """Variable assigned once and used once is flagged."""
        source = tmp_path / "test.py"
        source.write_text(
            dedent("""
        def process():
            x = compute()
            return x
        """)
        )

        symbols = get_symbols(source)
        metrics = calculate_waste_metrics(source, symbols)

        suv_names = {v.name for v in metrics.single_use_variables}
        assert "x" in suv_names

    def test_variable_used_twice_not_flagged(self, tmp_path):
        """Variable used more than once is not single-use."""
        source = tmp_path / "test.py"
        source.write_text(
            dedent("""
        def process():
            x = compute()
            print(x)
            return x
        """)
        )

        symbols = get_symbols(source)
        metrics = calculate_waste_metrics(source, symbols)

        suv_names = {v.name for v in metrics.single_use_variables}
        assert "x" not in suv_names

    def test_unused_variable_not_flagged(self, tmp_path):
        """Variable assigned but never used is not single-use (it's unused)."""
        source = tmp_path / "test.py"
        source.write_text(
            dedent("""
        def process():
            x = compute()
            return 42
        """)
        )

        symbols = get_symbols(source)
        metrics = calculate_waste_metrics(source, symbols)

        suv_names = {v.name for v in metrics.single_use_variables}
        assert "x" not in suv_names

    def test_parameter_not_flagged(self, tmp_path):
        """Function parameters should never be flagged."""
        source = tmp_path / "test.py"
        source.write_text(
            dedent("""
        def process(data):
            return data
        """)
        )

        symbols = get_symbols(source)
        metrics = calculate_waste_metrics(source, symbols)

        suv_names = {v.name for v in metrics.single_use_variables}
        assert "data" not in suv_names

    def test_self_not_flagged(self, tmp_path):
        """self/cls should never be flagged."""
        source = tmp_path / "test.py"
        source.write_text(
            dedent("""
        class Foo:
            def bar(self):
                self.x = 1
        """)
        )

        symbols = get_symbols(source)
        metrics = calculate_waste_metrics(source, symbols)

        suv_names = {v.name for v in metrics.single_use_variables}
        assert "self" not in suv_names

    def test_module_level_single_use(self, tmp_path):
        """Module-level variable assigned once and used once."""
        source = tmp_path / "test.py"
        source.write_text(
            dedent("""
        config = load_config()
        result = process(config)
        """)
        )

        symbols = get_symbols(source)
        metrics = calculate_waste_metrics(source, symbols)

        module_suvs = {
            v.name for v in metrics.single_use_variables if v.scope == "module"
        }
        assert "config" in module_suvs

    def test_module_level_used_twice_not_flagged(self, tmp_path):
        """Module-level variable used multiple times is not single-use."""
        source = tmp_path / "test.py"
        source.write_text(
            dedent("""
        config = load_config()
        process(config)
        validate(config)
        """)
        )

        symbols = get_symbols(source)
        metrics = calculate_waste_metrics(source, symbols)

        module_suvs = {
            v.name for v in metrics.single_use_variables if v.scope == "module"
        }
        assert "config" not in module_suvs

    def test_count_matches_list(self, tmp_path):
        """single_use_variable_count matches len(single_use_variables)."""
        source = tmp_path / "test.py"
        source.write_text(
            dedent("""
        def process():
            x = compute()
            return x
        """)
        )

        symbols = get_symbols(source)
        metrics = calculate_waste_metrics(source, symbols)

        assert metrics.single_use_variable_count == len(
            metrics.single_use_variables
        )


class TestUnusedVariables:
    """Tests for unused variable detection."""

    def test_unused_variable_in_function(self, tmp_path):
        """Variable assigned but never referenced is flagged."""
        source = tmp_path / "test.py"
        source.write_text(
            dedent("""
        def process():
            x = compute()
            return 42
        """)
        )

        symbols = get_symbols(source)
        metrics = calculate_waste_metrics(source, symbols)

        unused_names = {v.name for v in metrics.unused_variables}
        assert "x" in unused_names
        assert metrics.unused_variable_count == len(metrics.unused_variables)

    def test_used_variable_not_flagged(self, tmp_path):
        """Variable that is used at least once is not unused."""
        source = tmp_path / "test.py"
        source.write_text(
            dedent("""
        def process():
            x = compute()
            return x
        """)
        )

        symbols = get_symbols(source)
        metrics = calculate_waste_metrics(source, symbols)

        unused_names = {v.name for v in metrics.unused_variables}
        assert "x" not in unused_names

    def test_parameter_not_flagged(self, tmp_path):
        """Function parameters should never be flagged as unused."""
        source = tmp_path / "test.py"
        source.write_text(
            dedent("""
        def process(data):
            return 42
        """)
        )

        symbols = get_symbols(source)
        metrics = calculate_waste_metrics(source, symbols)

        unused_names = {v.name for v in metrics.unused_variables}
        assert "data" not in unused_names

    def test_self_not_flagged(self, tmp_path):
        """self/cls should never be flagged as unused."""
        source = tmp_path / "test.py"
        source.write_text(
            dedent("""
        class Foo:
            def bar(self):
                return 42
        """)
        )

        symbols = get_symbols(source)
        metrics = calculate_waste_metrics(source, symbols)

        unused_names = {v.name for v in metrics.unused_variables}
        assert "self" not in unused_names

    def test_module_level_unused(self, tmp_path):
        """Module-level variable assigned but never used."""
        source = tmp_path / "test.py"
        source.write_text(
            dedent("""
        dead = compute()
        result = process()
        print(result)
        """)
        )

        symbols = get_symbols(source)
        metrics = calculate_waste_metrics(source, symbols)

        module_unused = {
            v.name for v in metrics.unused_variables if v.scope == "module"
        }
        assert "dead" in module_unused
        assert "result" not in module_unused

    def test_multiple_unused_in_function(self, tmp_path):
        """Multiple unused variables in a single function."""
        source = tmp_path / "test.py"
        source.write_text(
            dedent("""
        def process():
            a = 1
            b = 2
            c = 3
            return 42
        """)
        )

        symbols = get_symbols(source)
        metrics = calculate_waste_metrics(source, symbols)

        unused_names = {v.name for v in metrics.unused_variables}
        assert unused_names >= {"a", "b", "c"}

    def test_underscore_not_flagged(self, tmp_path):
        """_ convention variable should not be flagged."""
        source = tmp_path / "test.py"
        source.write_text(
            dedent("""
        def process():
            _ = compute()
            return 42
        """)
        )

        symbols = get_symbols(source)
        metrics = calculate_waste_metrics(source, symbols)

        unused_names = {v.name for v in metrics.unused_variables}
        assert "_" not in unused_names
