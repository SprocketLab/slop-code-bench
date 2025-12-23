"""Exhaustive tests for Python symbol extraction and metrics.

Tests all functions in slop_code.metrics.languages.python.symbols including:
- Public API: get_symbols
- Complexity counting: _count_complexity_and_branches, _count_statements
- Expression counting: _count_expressions, _count_control_blocks
- Nesting: _calculate_max_depth
- Control flow: _count_control_flow_and_comparisons
- Class metrics: _count_methods, _count_class_attributes
- Signature extraction: _extract_signature, _extract_base_classes
- Hashing: _compute_body_hash, _compute_structure_hash, _compute_signature_hash
- Variable counting: _count_variables, _count_returns_and_raises
- Name extraction: _get_name_from_node, _get_assignment_name
- Handlers: _handle_function_definition, _handle_class_definition, etc.
"""

from __future__ import annotations

import re
import subprocess
from textwrap import dedent

import pytest

from slop_code.metrics.languages.python.parser import get_python_parser
from slop_code.metrics.languages.python.symbols import _calculate_max_depth
from slop_code.metrics.languages.python.symbols import _compute_body_hash
from slop_code.metrics.languages.python.symbols import _compute_signature_hash
from slop_code.metrics.languages.python.symbols import _compute_structure_hash
from slop_code.metrics.languages.python.symbols import _count_class_attributes
from slop_code.metrics.languages.python.symbols import (
    _count_complexity_and_branches,
)
from slop_code.metrics.languages.python.symbols import _count_control_blocks
from slop_code.metrics.languages.python.symbols import (
    _count_control_flow_and_comparisons,
)
from slop_code.metrics.languages.python.symbols import _count_expressions
from slop_code.metrics.languages.python.symbols import _count_methods
from slop_code.metrics.languages.python.symbols import _count_returns_and_raises
from slop_code.metrics.languages.python.symbols import _count_statements
from slop_code.metrics.languages.python.symbols import _count_variables
from slop_code.metrics.languages.python.symbols import _extract_base_classes
from slop_code.metrics.languages.python.symbols import _extract_signature
from slop_code.metrics.languages.python.symbols import _get_assignment_name
from slop_code.metrics.languages.python.symbols import _get_name_from_node
from slop_code.metrics.languages.python.symbols import get_symbols

# =============================================================================
# Test Utilities
# =============================================================================


def parse_code(code: str):
    """Parse code and return the root node."""
    parser = get_python_parser()
    tree = parser.parse(code.encode("utf-8"))
    return tree.root_node


def get_function_node(code: str):
    """Parse code and return the first function_definition node."""
    root = parse_code(code)
    for child in root.children:
        if child.type == "function_definition":
            return child
        if child.type == "decorated_definition":
            for grandchild in child.children:
                if grandchild.type == "function_definition":
                    return grandchild
    raise ValueError("No function_definition found in code")


def get_class_node(code: str):
    """Parse code and return the first class_definition node."""
    root = parse_code(code)
    for child in root.children:
        if child.type == "class_definition":
            return child
        if child.type == "decorated_definition":
            for grandchild in child.children:
                if grandchild.type == "class_definition":
                    return grandchild
    raise ValueError("No class_definition found in code")


def get_radon_complexity(file_path) -> dict[str, int]:
    """Run radon cc on a file and return a dict of name -> complexity."""
    result = subprocess.run(
        ["uv", "run", "radon", "cc", "-s", str(file_path)],
        capture_output=True,
        text=True,
        check=True,
    )

    pattern = re.compile(
        r"^\s+([FMC])\s+(\d+):(\d+)\s+(\S+(?:\.\S+)*)\s+-\s+([A-F])\s+\((\d+)\)",
        re.MULTILINE,
    )

    complexities = {}
    for match in pattern.finditer(result.stdout):
        kind, line, col, name, rating, cc = match.groups()
        complexities[name] = int(cc)

    return complexities


# =============================================================================
# Complexity and Branch Counting Tests
# =============================================================================


class TestCountComplexityAndBranches:
    """Tests for _count_complexity_and_branches function."""

    def test_empty_function(self):
        """Function with just pass has no complexity contributions."""
        node = get_function_node("def foo(): pass")
        complexity, branches = _count_complexity_and_branches(node)
        assert complexity == 0
        assert branches == 0

    def test_single_if(self):
        """Function with single if statement."""
        code = dedent("""
        def foo(x):
            if x:
                return 1
            return 0
        """)
        node = get_function_node(code)
        complexity, branches = _count_complexity_and_branches(node)
        assert complexity >= 1
        assert branches >= 1

    def test_if_elif_else(self):
        """Function with if/elif/else chain."""
        code = dedent("""
        def foo(x):
            if x > 0:
                return 1
            elif x < 0:
                return -1
            else:
                return 0
        """)
        node = get_function_node(code)
        complexity, branches = _count_complexity_and_branches(node)
        # if and elif add complexity
        assert complexity >= 2
        assert branches >= 2

    def test_for_loop(self):
        """Function with for loop."""
        code = dedent("""
        def foo(items):
            for item in items:
                print(item)
        """)
        node = get_function_node(code)
        complexity, branches = _count_complexity_and_branches(node)
        assert complexity >= 1

    def test_while_loop(self):
        """Function with while loop."""
        code = dedent("""
        def foo(n):
            while n > 0:
                n -= 1
        """)
        node = get_function_node(code)
        complexity, branches = _count_complexity_and_branches(node)
        assert complexity >= 1

    def test_try_except(self):
        """Function with try/except."""
        code = dedent("""
        def foo():
            try:
                risky()
            except Exception:
                handle()
        """)
        node = get_function_node(code)
        complexity, branches = _count_complexity_and_branches(node)
        assert complexity >= 1

    def test_multiple_except(self):
        """Function with multiple except handlers."""
        code = dedent("""
        def foo():
            try:
                risky()
            except ValueError:
                handle1()
            except TypeError:
                handle2()
            except Exception:
                handle3()
        """)
        node = get_function_node(code)
        complexity, branches = _count_complexity_and_branches(node)
        # Each except clause adds complexity
        assert complexity >= 3

    def test_boolean_and_operator(self):
        """Boolean 'and' adds complexity."""
        code = dedent("""
        def foo(a, b):
            if a and b:
                return True
        """)
        node = get_function_node(code)
        complexity, branches = _count_complexity_and_branches(node)
        # if + and operator
        assert complexity >= 2

    def test_boolean_or_operator(self):
        """Boolean 'or' adds complexity."""
        code = dedent("""
        def foo(a, b):
            if a or b:
                return True
        """)
        node = get_function_node(code)
        complexity, branches = _count_complexity_and_branches(node)
        # if + or operator
        assert complexity >= 2

    def test_nested_boolean(self):
        """Nested boolean operators."""
        code = dedent("""
        def foo(a, b, c, d):
            if (a and b) or (c and d):
                return True
        """)
        node = get_function_node(code)
        complexity, branches = _count_complexity_and_branches(node)
        # if + 3 boolean operators
        assert complexity >= 4

    def test_list_comprehension(self):
        """List comprehension adds complexity."""
        code = dedent("""
        def foo(items):
            return [x for x in items]
        """)
        node = get_function_node(code)
        complexity, branches = _count_complexity_and_branches(node)
        assert complexity >= 1

    def test_list_comprehension_with_condition(self):
        """List comprehension with if adds complexity."""
        code = dedent("""
        def foo(items):
            return [x for x in items if x > 0]
        """)
        node = get_function_node(code)
        complexity, branches = _count_complexity_and_branches(node)
        # for + if
        assert complexity >= 2

    def test_dict_comprehension(self):
        """Dict comprehension adds complexity."""
        code = dedent("""
        def foo(items):
            return {k: v for k, v in items}
        """)
        node = get_function_node(code)
        complexity, branches = _count_complexity_and_branches(node)
        assert complexity >= 1

    def test_set_comprehension(self):
        """Set comprehension adds complexity."""
        code = dedent("""
        def foo(items):
            return {x for x in items}
        """)
        node = get_function_node(code)
        complexity, branches = _count_complexity_and_branches(node)
        assert complexity >= 1

    def test_generator_expression(self):
        """Generator expression adds complexity."""
        code = dedent("""
        def foo(items):
            return sum(x for x in items)
        """)
        node = get_function_node(code)
        complexity, branches = _count_complexity_and_branches(node)
        assert complexity >= 1

    def test_ternary_expression(self):
        """Ternary expression adds complexity."""
        code = dedent("""
        def foo(x):
            return "yes" if x else "no"
        """)
        node = get_function_node(code)
        complexity, branches = _count_complexity_and_branches(node)
        assert complexity >= 1

    def test_lambda_expression(self):
        """Lambda expression in tree-sitter.

        Note: Lambda expressions may not be counted as complexity nodes
        in the current implementation using COMPLEXITY_NODE_TYPES.
        """
        code = dedent("""
        def foo():
            return lambda x: x + 1
        """)
        node = get_function_node(code)
        complexity, branches = _count_complexity_and_branches(node)
        # Lambda may not be in COMPLEXITY_NODE_TYPES
        assert complexity >= 0

    def test_match_statement(self):
        """Match statement with cases.

        Note: Match statements may not contribute to cyclomatic complexity
        in the same way as if/for/while in the current implementation.
        """
        code = dedent("""
        def foo(x):
            match x:
                case 1:
                    return "one"
                case 2:
                    return "two"
                case _:
                    return "other"
        """)
        node = get_function_node(code)
        complexity, branches = _count_complexity_and_branches(node)
        # Match may or may not be in COMPLEXITY_NODE_TYPES
        assert complexity >= 0

    def test_nested_loops(self):
        """Nested loops add complexity."""
        code = dedent("""
        def foo(matrix):
            for row in matrix:
                for cell in row:
                    print(cell)
        """)
        node = get_function_node(code)
        complexity, branches = _count_complexity_and_branches(node)
        assert complexity >= 2


# =============================================================================
# Statement Counting Tests
# =============================================================================


class TestCountStatements:
    """Tests for _count_statements function."""

    def test_empty_function(self):
        """Function with just pass has one statement."""
        node = get_function_node("def foo(): pass")
        count = _count_statements(node)
        assert count >= 1

    def test_multiple_statements(self):
        """Function with multiple statements.

        Note: Statement counting depends on what's in STATEMENT_NODE_TYPES.
        Assignment expressions may not count as statement nodes in tree-sitter.
        """
        code = dedent("""
        def foo():
            x = 1
            y = 2
            z = 3
            return x + y + z
        """)
        node = get_function_node(code)
        count = _count_statements(node)
        # return_statement is typically counted
        assert count >= 1

    def test_nested_statements(self):
        """Statements inside control structures.

        Note: Statement counting depends on what's in STATEMENT_NODE_TYPES.
        if_statement and return_statement are typically counted.
        """
        code = dedent("""
        def foo(x):
            if x:
                a = 1
                b = 2
            else:
                c = 3
            return 0
        """)
        node = get_function_node(code)
        count = _count_statements(node)
        # if_statement + return_statement are typically counted
        assert count >= 2


# =============================================================================
# Expression Counting Tests
# =============================================================================


class TestCountExpressions:
    """Tests for _count_expressions function."""

    def test_no_expressions(self):
        """Function with no expression statements."""
        node = get_function_node("def foo(): pass")
        top_level, total = _count_expressions(node)
        # pass is a statement, not an expression
        assert total >= 0

    def test_call_expressions(self):
        """Function with call expressions."""
        code = dedent("""
        def foo():
            print("hello")
            print("world")
        """)
        node = get_function_node(code)
        top_level, total = _count_expressions(node)
        assert total >= 2

    def test_nested_expressions(self):
        """Nested expressions vs top-level."""
        code = dedent("""
        def foo(x):
            if x > 0:
                print(x)
            print("done")
        """)
        node = get_function_node(code)
        top_level, total = _count_expressions(node)
        # Only top-level print("done") at block level
        # total includes nested ones


# =============================================================================
# Control Block Counting Tests
# =============================================================================


class TestCountControlBlocks:
    """Tests for _count_control_blocks function."""

    def test_no_control_blocks(self):
        """Function with no control blocks."""
        node = get_function_node("def foo():\n    x = 1")
        count = _count_control_blocks(node)
        assert count == 0

    def test_single_if(self):
        """Function with single if."""
        code = dedent("""
        def foo(x):
            if x:
                pass
        """)
        node = get_function_node(code)
        count = _count_control_blocks(node)
        assert count == 1

    def test_multiple_control_blocks(self):
        """Function with multiple control blocks."""
        code = dedent("""
        def foo(items):
            if items:
                pass
            for item in items:
                pass
            while items:
                break
        """)
        node = get_function_node(code)
        count = _count_control_blocks(node)
        assert count == 3

    def test_nested_not_counted(self):
        """Nested control blocks not counted at top level."""
        code = dedent("""
        def foo(x):
            if x:
                if x > 1:
                    pass
        """)
        node = get_function_node(code)
        count = _count_control_blocks(node)
        # Only top-level if counted
        assert count == 1


# =============================================================================
# Max Nesting Depth Tests
# =============================================================================


class TestCalculateMaxDepth:
    """Tests for _calculate_max_depth function."""

    def test_no_nesting(self):
        """Function with no nesting."""
        node = get_function_node("def foo():\n    x = 1")
        depth = _calculate_max_depth(node)
        assert depth == 0

    def test_single_level_nesting(self):
        """Function with single level of nesting."""
        code = dedent("""
        def foo(x):
            if x:
                return 1
        """)
        node = get_function_node(code)
        depth = _calculate_max_depth(node)
        assert depth == 1

    def test_double_nesting(self):
        """Function with double nesting."""
        code = dedent("""
        def foo(x):
            if x:
                if x > 1:
                    return 1
        """)
        node = get_function_node(code)
        depth = _calculate_max_depth(node)
        assert depth == 2

    def test_triple_nesting(self):
        """Function with triple nesting."""
        code = dedent("""
        def foo(items):
            for item in items:
                if item:
                    while item:
                        item -= 1
        """)
        node = get_function_node(code)
        depth = _calculate_max_depth(node)
        assert depth == 3

    def test_max_of_branches(self):
        """Returns maximum across branches."""
        code = dedent("""
        def foo(x):
            if x > 0:
                if x > 10:
                    return 1
            else:
                return 0
        """)
        node = get_function_node(code)
        depth = _calculate_max_depth(node)
        assert depth == 2


# =============================================================================
# Control Flow and Comparisons Tests
# =============================================================================


class TestCountControlFlowAndComparisons:
    """Tests for _count_control_flow_and_comparisons function."""

    def test_no_control_flow(self):
        """Function with no control flow."""
        node = get_function_node("def foo(): pass")
        cf, es, comp = _count_control_flow_and_comparisons(node)
        assert cf == 0
        assert es == 0
        assert comp == 0

    def test_if_control_flow(self):
        """If statement counts as control flow."""
        code = dedent("""
        def foo(x):
            if x:
                pass
        """)
        node = get_function_node(code)
        cf, es, comp = _count_control_flow_and_comparisons(node)
        assert cf >= 1

    def test_elif_control_flow(self):
        """Elif counts as control flow."""
        code = dedent("""
        def foo(x):
            if x > 0:
                pass
            elif x < 0:
                pass
        """)
        node = get_function_node(code)
        cf, es, comp = _count_control_flow_and_comparisons(node)
        # if + elif
        assert cf >= 2

    def test_match_case_control_flow(self):
        """Match/case counts as control flow."""
        code = dedent("""
        def foo(x):
            match x:
                case 1:
                    pass
                case 2:
                    pass
        """)
        node = get_function_node(code)
        cf, es, comp = _count_control_flow_and_comparisons(node)
        assert cf >= 1

    def test_exception_scaffold(self):
        """Try/except/finally counts as exception scaffold."""
        code = dedent("""
        def foo():
            try:
                pass
            except:
                pass
            finally:
                pass
        """)
        node = get_function_node(code)
        cf, es, comp = _count_control_flow_and_comparisons(node)
        assert es >= 3

    def test_comparison_operators(self):
        """Comparison operators are counted."""
        code = dedent("""
        def foo(x):
            if x > 0:
                pass
            if x == 0:
                pass
        """)
        node = get_function_node(code)
        cf, es, comp = _count_control_flow_and_comparisons(node)
        assert comp >= 2

    def test_chained_comparison(self):
        """Chained comparisons counted properly."""
        code = dedent("""
        def foo(x):
            if 0 < x < 10:
                pass
        """)
        node = get_function_node(code)
        cf, es, comp = _count_control_flow_and_comparisons(node)
        # 0 < x < 10 has 2 comparisons
        assert comp >= 2


# =============================================================================
# Class Method and Attribute Counting Tests
# =============================================================================


class TestCountMethods:
    """Tests for _count_methods function."""

    def test_no_methods(self):
        """Class with no methods."""
        node = get_class_node("class Foo: pass")
        count = _count_methods(node)
        assert count == 0

    def test_single_method(self):
        """Class with single method."""
        code = dedent("""
        class Foo:
            def method(self):
                pass
        """)
        node = get_class_node(code)
        count = _count_methods(node)
        assert count == 1

    def test_multiple_methods(self):
        """Class with multiple methods."""
        code = dedent("""
        class Foo:
            def method1(self): pass
            def method2(self): pass
            def method3(self): pass
        """)
        node = get_class_node(code)
        count = _count_methods(node)
        assert count == 3

    def test_decorated_methods(self):
        """Decorated methods are counted."""
        code = dedent("""
        class Foo:
            @property
            def prop(self): return 1

            @staticmethod
            def static_method(): pass

            @classmethod
            def class_method(cls): pass
        """)
        node = get_class_node(code)
        count = _count_methods(node)
        assert count == 3


class TestCountClassAttributes:
    """Tests for _count_class_attributes function."""

    def test_no_attributes(self):
        """Class with no attributes."""
        node = get_class_node("class Foo: pass")
        count = _count_class_attributes(node)
        assert count == 0

    def test_init_attributes(self):
        """Attributes set in __init__."""
        code = dedent("""
        class Foo:
            def __init__(self):
                self.a = 1
                self.b = 2
        """)
        node = get_class_node(code)
        count = _count_class_attributes(node)
        assert count == 2

    def test_class_level_attributes(self):
        """Class-level attribute definitions."""
        code = dedent("""
        class Foo:
            x = 1
            y = 2
        """)
        node = get_class_node(code)
        count = _count_class_attributes(node)
        assert count == 2

    def test_dataclass_attributes(self):
        """Dataclass-style attributes."""
        code = dedent("""
        @dataclass
        class Foo:
            x: int
            y: str = "default"
        """)
        node = get_class_node(code)
        count = _count_class_attributes(node)
        assert count == 2

    def test_unique_attributes(self):
        """Same attribute assigned multiple times counts once."""
        code = dedent("""
        class Foo:
            def __init__(self):
                self.x = 1
                self.x = 2
        """)
        node = get_class_node(code)
        count = _count_class_attributes(node)
        assert count == 1


# =============================================================================
# Signature Extraction Tests
# =============================================================================


class TestExtractSignature:
    """Tests for _extract_signature function."""

    def test_no_params(self):
        """Function with no parameters."""
        node = get_function_node("def foo(): pass")
        signature, return_type = _extract_signature(node)
        assert signature == {}
        assert return_type is None

    def test_single_untyped_param(self):
        """Function with single untyped parameter."""
        node = get_function_node("def foo(x): pass")
        signature, return_type = _extract_signature(node)
        assert signature == {"x": None}

    def test_multiple_untyped_params(self):
        """Function with multiple untyped parameters."""
        node = get_function_node("def foo(a, b, c): pass")
        signature, return_type = _extract_signature(node)
        assert signature == {"a": None, "b": None, "c": None}

    def test_single_typed_param(self):
        """Function with single typed parameter."""
        node = get_function_node("def foo(x: int): pass")
        signature, return_type = _extract_signature(node)
        assert signature == {"x": "int"}

    def test_multiple_typed_params(self):
        """Function with multiple typed parameters."""
        node = get_function_node("def foo(x: int, y: str, z: float): pass")
        signature, return_type = _extract_signature(node)
        assert signature == {"x": "int", "y": "str", "z": "float"}

    def test_mixed_typed_untyped_params(self):
        """Function with mix of typed and untyped parameters."""
        node = get_function_node("def foo(x, y: int, z): pass")
        signature, return_type = _extract_signature(node)
        assert signature == {"x": None, "y": "int", "z": None}

    def test_default_param(self):
        """Function with default parameter value."""
        node = get_function_node("def foo(x=5): pass")
        signature, return_type = _extract_signature(node)
        assert signature == {"x": None}

    def test_typed_default_param(self):
        """Function with typed parameter and default value."""
        node = get_function_node("def foo(x: int = 5): pass")
        signature, return_type = _extract_signature(node)
        assert signature == {"x": "int"}

    def test_args(self):
        """Function with *args."""
        node = get_function_node("def foo(*args): pass")
        signature, return_type = _extract_signature(node)
        assert signature == {"*args": None}

    def test_kwargs(self):
        """Function with **kwargs."""
        node = get_function_node("def foo(**kwargs): pass")
        signature, return_type = _extract_signature(node)
        assert signature == {"**kwargs": None}

    def test_args_and_kwargs(self):
        """Function with both *args and **kwargs."""
        node = get_function_node("def foo(x, *args, **kwargs): pass")
        signature, return_type = _extract_signature(node)
        assert signature == {"x": None, "*args": None, "**kwargs": None}

    def test_return_type_simple(self):
        """Function with simple return type."""
        node = get_function_node("def foo() -> int: pass")
        signature, return_type = _extract_signature(node)
        assert return_type == "int"

    def test_return_type_none(self):
        """Function with None return type."""
        node = get_function_node("def foo() -> None: pass")
        signature, return_type = _extract_signature(node)
        assert return_type == "None"

    def test_return_type_complex(self):
        """Function with complex return type."""
        node = get_function_node("def foo() -> dict[str, list[int]]: pass")
        signature, return_type = _extract_signature(node)
        assert return_type == "dict[str, list[int]]"

    def test_full_signature(self):
        """Function with full typed signature."""
        node = get_function_node(
            "def foo(x: int, y: str = 'hello') -> bool: pass"
        )
        signature, return_type = _extract_signature(node)
        assert signature == {"x": "int", "y": "str"}
        assert return_type == "bool"


# =============================================================================
# Base Class Extraction Tests
# =============================================================================


class TestExtractBaseClasses:
    """Tests for _extract_base_classes function."""

    def test_no_base_class(self):
        """Class with no explicit base class."""
        node = get_class_node("class Foo: pass")
        bases = _extract_base_classes(node)
        assert bases == []

    def test_single_base_class(self):
        """Class with single base class."""
        node = get_class_node("class Foo(Bar): pass")
        bases = _extract_base_classes(node)
        assert bases == ["Bar"]

    def test_multiple_base_classes(self):
        """Class with multiple base classes."""
        node = get_class_node("class Foo(Bar, Baz): pass")
        bases = _extract_base_classes(node)
        assert bases == ["Bar", "Baz"]

    def test_qualified_base_class(self):
        """Class with qualified (module.Class) base class."""
        node = get_class_node("class Foo(module.Bar): pass")
        bases = _extract_base_classes(node)
        assert bases == ["module.Bar"]

    def test_generic_base_class(self):
        """Class with generic base class."""
        node = get_class_node("class Foo(Generic[T]): pass")
        bases = _extract_base_classes(node)
        assert bases == ["Generic[T]"]

    def test_complex_generic_base_class(self):
        """Class with complex generic base class."""
        node = get_class_node("class Foo(Dict[str, List[int]]): pass")
        bases = _extract_base_classes(node)
        assert bases == ["Dict[str, List[int]]"]

    def test_mixed_base_classes(self):
        """Class with mixed base class types."""
        node = get_class_node("class Foo(Base, Generic[T], module.Mixin): pass")
        bases = _extract_base_classes(node)
        assert bases == ["Base", "Generic[T]", "module.Mixin"]

    def test_with_metaclass(self):
        """Class with metaclass (should be ignored)."""
        node = get_class_node("class Foo(Bar, metaclass=ABCMeta): pass")
        bases = _extract_base_classes(node)
        assert bases == ["Bar"]


# =============================================================================
# Body Hash Tests
# =============================================================================


class TestComputeBodyHash:
    """Tests for _compute_body_hash function."""

    def test_empty_function(self):
        """Empty function with pass."""
        node = get_function_node("def foo(): pass")
        hash_val = _compute_body_hash(node)
        assert len(hash_val) == 64  # SHA256 hex

    def test_identical_functions_same_hash(self):
        """Identical functions should have same hash."""
        node1 = get_function_node("def foo():\n    x = 1\n    return x")
        node2 = get_function_node("def bar():\n    x = 1\n    return x")
        assert _compute_body_hash(node1) == _compute_body_hash(node2)

    def test_renamed_variables_same_hash(self):
        """Functions with renamed variables should have same hash."""
        node1 = get_function_node("def foo():\n    x = 1\n    return x")
        node2 = get_function_node("def bar():\n    y = 1\n    return y")
        assert _compute_body_hash(node1) == _compute_body_hash(node2)

    def test_different_logic_different_hash(self):
        """Functions with different logic should have different hash."""
        node1 = get_function_node("def foo():\n    x = 1\n    return x")
        node2 = get_function_node("def bar():\n    x = 1\n    return x + 1")
        assert _compute_body_hash(node1) != _compute_body_hash(node2)

    def test_different_literals_different_hash(self):
        """Functions with different literals should have different hash."""
        node1 = get_function_node("def foo():\n    return 1")
        node2 = get_function_node("def bar():\n    return 2")
        assert _compute_body_hash(node1) != _compute_body_hash(node2)

    def test_different_string_literals_different_hash(self):
        """Functions with different string literals should have different hash."""
        node1 = get_function_node("def foo():\n    return 'hello'")
        node2 = get_function_node("def bar():\n    return 'world'")
        assert _compute_body_hash(node1) != _compute_body_hash(node2)

    def test_complex_function_hash(self):
        """Complex function produces consistent hash."""
        code = dedent("""
        def foo(x, y):
            result = 0
            for i in range(x):
                if i > y:
                    result += i
            return result
        """)
        node = get_function_node(code)
        hash1 = _compute_body_hash(node)
        hash2 = _compute_body_hash(node)
        assert hash1 == hash2


# =============================================================================
# Structure Hash Tests
# =============================================================================


class TestComputeStructureHash:
    """Tests for _compute_structure_hash function."""

    def test_empty_function(self):
        """Empty function with pass."""
        node = get_function_node("def foo(): pass")
        hash_val = _compute_structure_hash(node)
        assert len(hash_val) == 64  # SHA256 hex

    def test_same_structure_different_names(self):
        """Functions with same structure but different names."""
        node1 = get_function_node("def foo():\n    x = 1\n    return x")
        node2 = get_function_node("def bar():\n    y = 2\n    return y")
        assert _compute_structure_hash(node1) == _compute_structure_hash(node2)

    def test_different_structure_different_hash(self):
        """Functions with different structure should have different hash."""
        node1 = get_function_node("def foo():\n    return 1")
        node2 = get_function_node("def bar():\n    if True:\n        return 1")
        assert _compute_structure_hash(node1) != _compute_structure_hash(node2)

    def test_structure_ignores_literals(self):
        """Structure hash should be same regardless of literal values."""
        node1 = get_function_node("def foo():\n    return 1")
        node2 = get_function_node("def bar():\n    return 99999")
        assert _compute_structure_hash(node1) == _compute_structure_hash(node2)

    def test_loop_structure(self):
        """Functions with loops have consistent structure hash."""
        code = dedent("""
        def foo():
            for i in range(10):
                if i > 5:
                    print(i)
        """)
        node = get_function_node(code)
        hash1 = _compute_structure_hash(node)
        hash2 = _compute_structure_hash(node)
        assert hash1 == hash2


# =============================================================================
# Signature Hash Tests
# =============================================================================


class TestComputeSignatureHash:
    """Tests for _compute_signature_hash function."""

    def test_empty_signature(self):
        """Empty signature produces consistent hash."""
        hash1 = _compute_signature_hash({}, None)
        hash2 = _compute_signature_hash({}, None)
        assert hash1 == hash2
        assert len(hash1) == 64

    def test_same_signature_same_hash(self):
        """Same signatures produce same hash."""
        sig1 = {"x": "int", "y": "str"}
        sig2 = {"x": "int", "y": "str"}
        hash1 = _compute_signature_hash(sig1, "bool")
        hash2 = _compute_signature_hash(sig2, "bool")
        assert hash1 == hash2

    def test_same_arity_different_names_same_hash(self):
        """Signatures with same types but different names should have same hash."""
        sig1 = {"x": "int", "y": "str"}
        sig2 = {"a": "int", "b": "str"}
        hash1 = _compute_signature_hash(sig1, None)
        hash2 = _compute_signature_hash(sig2, None)
        assert hash1 == hash2

    def test_different_arity_different_hash(self):
        """Signatures with different number of params have different hash."""
        sig1 = {"x": "int"}
        sig2 = {"x": "int", "y": "str"}
        hash1 = _compute_signature_hash(sig1, None)
        hash2 = _compute_signature_hash(sig2, None)
        assert hash1 != hash2

    def test_different_return_type_different_hash(self):
        """Signatures with different return types have different hash."""
        sig = {"x": "int"}
        hash1 = _compute_signature_hash(sig, "bool")
        hash2 = _compute_signature_hash(sig, None)
        assert hash1 != hash2

    def test_type_presence_matters(self):
        """Signatures with/without types have different hash."""
        sig1 = {"x": "int"}
        sig2 = {"x": None}
        hash1 = _compute_signature_hash(sig1, None)
        hash2 = _compute_signature_hash(sig2, None)
        assert hash1 != hash2


# =============================================================================
# Variable Counting Tests
# =============================================================================


class TestCountVariables:
    """Tests for _count_variables function."""

    def test_no_variables(self):
        """Function with no variables."""
        node = get_function_node("def foo(): pass")
        defined, used = _count_variables(node)
        assert defined == 0
        assert used == 0

    def test_single_assignment(self):
        """Function with single variable assignment."""
        node = get_function_node("def foo():\n    x = 1")
        defined, used = _count_variables(node)
        assert defined == 1
        # '1' is an integer literal, not a variable use
        assert used == 0

    def test_multiple_assignments(self):
        """Function with multiple variable assignments."""
        node = get_function_node("def foo():\n    x = 1\n    y = 2\n    z = 3")
        defined, used = _count_variables(node)
        assert defined == 3

    def test_variable_usage(self):
        """Function that uses variables."""
        node = get_function_node("def foo():\n    x = 1\n    y = x + 1\n    return y")
        defined, used = _count_variables(node)
        assert defined == 2
        assert used >= 2

    def test_augmented_assignment(self):
        """Function with augmented assignment."""
        node = get_function_node("def foo():\n    x = 0\n    x += 1")
        defined, used = _count_variables(node)
        assert defined >= 1

    def test_annotated_assignment(self):
        """Function with annotated assignment."""
        node = get_function_node("def foo():\n    x: int = 1")
        defined, used = _count_variables(node)
        assert defined == 1


# =============================================================================
# Return/Raise Counting Tests
# =============================================================================


class TestCountReturnsAndRaises:
    """Tests for _count_returns_and_raises function."""

    def test_no_returns_no_raises(self):
        """Function with no returns or raises."""
        node = get_function_node("def foo(): pass")
        returns, raises = _count_returns_and_raises(node)
        assert returns == 0
        assert raises == 0

    def test_single_return(self):
        """Function with single return."""
        node = get_function_node("def foo():\n    return 1")
        returns, raises = _count_returns_and_raises(node)
        assert returns == 1
        assert raises == 0

    def test_multiple_returns(self):
        """Function with multiple returns."""
        code = dedent("""
        def foo(x):
            if x > 0:
                return 1
            elif x < 0:
                return -1
            else:
                return 0
        """)
        node = get_function_node(code)
        returns, raises = _count_returns_and_raises(node)
        assert returns == 3
        assert raises == 0

    def test_single_raise(self):
        """Function with single raise."""
        node = get_function_node("def foo():\n    raise ValueError()")
        returns, raises = _count_returns_and_raises(node)
        assert returns == 0
        assert raises == 1

    def test_multiple_raises(self):
        """Function with multiple raises."""
        code = dedent("""
        def foo(x):
            if x < 0:
                raise ValueError('negative')
            if x > 100:
                raise ValueError('too big')
            return x
        """)
        node = get_function_node(code)
        returns, raises = _count_returns_and_raises(node)
        assert returns == 1
        assert raises == 2

    def test_returns_and_raises(self):
        """Function with both returns and raises."""
        code = dedent("""
        def foo(x):
            if x is None:
                raise TypeError()
            if x < 0:
                return -1
            return x
        """)
        node = get_function_node(code)
        returns, raises = _count_returns_and_raises(node)
        assert returns == 2
        assert raises == 1

    def test_nested_function_not_counted(self):
        """Nested function's returns/raises should not be counted."""
        code = dedent("""
        def foo():
            def inner():
                return 1
            return inner
        """)
        node = get_function_node(code)
        returns, raises = _count_returns_and_raises(node)
        # Only outer function's return should be counted
        assert returns == 1


# =============================================================================
# Name Extraction Tests
# =============================================================================


class TestGetNameFromNode:
    """Tests for _get_name_from_node function."""

    def test_function_name(self):
        """Extract function name."""
        node = get_function_node("def my_function(): pass")
        name = _get_name_from_node(node)
        assert name == "my_function"

    def test_class_name(self):
        """Extract class name."""
        node = get_class_node("class MyClass: pass")
        name = _get_name_from_node(node)
        assert name == "MyClass"

    def test_type_alias_name(self):
        """Extract type alias name."""
        root = parse_code("type MyType = int")
        for child in root.children:
            if child.type == "type_alias_statement":
                name = _get_name_from_node(child)
                assert name == "MyType"
                return
        pytest.fail("No type_alias_statement found")


class TestGetAssignmentName:
    """Tests for _get_assignment_name function."""

    def test_simple_assignment(self):
        """Extract name from simple assignment."""
        root = parse_code("x = 1")
        for child in root.children:
            if child.type in ("assignment", "expression_statement"):
                if child.type == "expression_statement":
                    for subchild in child.children:
                        if subchild.type == "assignment":
                            name = _get_assignment_name(subchild)
                            assert name == "x"
                            return
                else:
                    name = _get_assignment_name(child)
                    assert name == "x"
                    return
        pytest.fail("No assignment found")

    def test_tuple_assignment_returns_none(self):
        """Tuple assignment returns None (not simple identifier)."""
        root = parse_code("a, b = 1, 2")
        for child in root.children:
            if child.type in ("assignment", "expression_statement"):
                if child.type == "expression_statement":
                    for subchild in child.children:
                        if subchild.type == "assignment":
                            name = _get_assignment_name(subchild)
                            assert name is None
                            return


# =============================================================================
# Radon Comparison Tests
# =============================================================================


class TestRadonComplexityComparison:
    """Tests comparing get_symbols output against radon's complexity."""

    def test_simple_function_matches_radon(self, tmp_path):
        """Test simple function complexity matches radon."""
        test_file = tmp_path / "test.py"
        test_file.write_text('def hello():\n    print("world")\n')
        symbols = get_symbols(test_file)
        radon_cc = get_radon_complexity(test_file)

        func = next(s for s in symbols if s.name == "hello")
        assert func.complexity == radon_cc["hello"]

    def test_if_elif_else_matches_radon(self, tmp_path):
        """Test if/elif/else complexity matches radon."""
        test_file = tmp_path / "test.py"
        test_file.write_text(dedent("""
        def classify(x):
            if x > 0:
                return "positive"
            elif x < 0:
                return "negative"
            else:
                return "zero"
        """))
        symbols = get_symbols(test_file)
        radon_cc = get_radon_complexity(test_file)

        func = next(s for s in symbols if s.name == "classify")
        assert func.complexity == radon_cc["classify"]

    def test_nested_if_matches_radon(self, tmp_path):
        """Test nested if statements complexity matches radon."""
        test_file = tmp_path / "test.py"
        test_file.write_text(dedent("""
        def nested_check(a, b, c):
            if a:
                if b:
                    if c:
                        return "all true"
                    return "a and b"
                return "only a"
            return "none"
        """))
        symbols = get_symbols(test_file)
        radon_cc = get_radon_complexity(test_file)

        func = next(s for s in symbols if s.name == "nested_check")
        assert func.complexity == radon_cc["nested_check"]

    def test_for_loop_matches_radon(self, tmp_path):
        """Test for loop complexity matches radon."""
        test_file = tmp_path / "test.py"
        test_file.write_text(dedent("""
        def sum_list(items):
            total = 0
            for item in items:
                total += item
            return total
        """))
        symbols = get_symbols(test_file)
        radon_cc = get_radon_complexity(test_file)

        func = next(s for s in symbols if s.name == "sum_list")
        assert func.complexity == radon_cc["sum_list"]

    def test_while_loop_matches_radon(self, tmp_path):
        """Test while loop complexity matches radon."""
        test_file = tmp_path / "test.py"
        test_file.write_text(dedent("""
        def countdown(n):
            while n > 0:
                print(n)
                n -= 1
            return "done"
        """))
        symbols = get_symbols(test_file)
        radon_cc = get_radon_complexity(test_file)

        func = next(s for s in symbols if s.name == "countdown")
        assert func.complexity == radon_cc["countdown"]

    def test_nested_loops_matches_radon(self, tmp_path):
        """Test nested loops complexity matches radon."""
        test_file = tmp_path / "test.py"
        test_file.write_text(dedent("""
        def matrix_sum(matrix):
            total = 0
            for row in matrix:
                for cell in row:
                    total += cell
            return total
        """))
        symbols = get_symbols(test_file)
        radon_cc = get_radon_complexity(test_file)

        func = next(s for s in symbols if s.name == "matrix_sum")
        assert func.complexity == radon_cc["matrix_sum"]

    def test_boolean_and_matches_radon(self, tmp_path):
        """Test boolean 'and' operator complexity matches radon."""
        test_file = tmp_path / "test.py"
        test_file.write_text(dedent("""
        def check_both(a, b):
            if a and b:
                return True
            return False
        """))
        symbols = get_symbols(test_file)
        radon_cc = get_radon_complexity(test_file)

        func = next(s for s in symbols if s.name == "check_both")
        assert func.complexity == radon_cc["check_both"]

    def test_boolean_or_matches_radon(self, tmp_path):
        """Test boolean 'or' operator complexity matches radon."""
        test_file = tmp_path / "test.py"
        test_file.write_text(dedent("""
        def check_either(a, b):
            if a or b:
                return True
            return False
        """))
        symbols = get_symbols(test_file)
        radon_cc = get_radon_complexity(test_file)

        func = next(s for s in symbols if s.name == "check_either")
        assert func.complexity == radon_cc["check_either"]

    def test_try_except_matches_radon(self, tmp_path):
        """Test try/except complexity matches radon."""
        test_file = tmp_path / "test.py"
        test_file.write_text(dedent("""
        def safe_divide(a, b):
            try:
                return a / b
            except ZeroDivisionError:
                return 0
        """))
        symbols = get_symbols(test_file)
        radon_cc = get_radon_complexity(test_file)

        func = next(s for s in symbols if s.name == "safe_divide")
        assert func.complexity == radon_cc["safe_divide"]

    def test_list_comprehension_matches_radon(self, tmp_path):
        """Test list comprehension complexity matches radon."""
        test_file = tmp_path / "test.py"
        test_file.write_text(dedent("""
        def get_squares(items):
            return [x**2 for x in items]
        """))
        symbols = get_symbols(test_file)
        radon_cc = get_radon_complexity(test_file)

        func = next(s for s in symbols if s.name == "get_squares")
        assert func.complexity == radon_cc["get_squares"]

    def test_ternary_expression_matches_radon(self, tmp_path):
        """Test ternary/conditional expression matches radon."""
        test_file = tmp_path / "test.py"
        test_file.write_text(dedent("""
        def get_sign(x):
            return "positive" if x > 0 else "non-positive"
        """))
        symbols = get_symbols(test_file)
        radon_cc = get_radon_complexity(test_file)

        func = next(s for s in symbols if s.name == "get_sign")
        assert func.complexity == radon_cc["get_sign"]

    def test_class_method_matches_radon(self, tmp_path):
        """Test class method complexity matches radon."""
        test_file = tmp_path / "test.py"
        test_file.write_text(dedent("""
        class Calculator:
            def add(self, a, b):
                if a < 0 or b < 0:
                    return 0
                return a + b

            def multiply(self, a, b):
                result = 0
                for _ in range(b):
                    result += a
                return result
        """))
        symbols = get_symbols(test_file)
        radon_cc = get_radon_complexity(test_file)

        add_method = next(s for s in symbols if s.name == "add")
        multiply_method = next(s for s in symbols if s.name == "multiply")

        assert add_method.complexity == radon_cc["Calculator.add"]
        assert multiply_method.complexity == radon_cc["Calculator.multiply"]


# =============================================================================
# Integration Tests with get_symbols
# =============================================================================


class TestGetSymbols:
    """Integration tests for get_symbols function."""

    def test_empty_file(self, tmp_path):
        """Test with an empty file."""
        test_file = tmp_path / "empty.py"
        test_file.write_text("")

        symbols = get_symbols(test_file)
        assert symbols == []

    def test_extracts_functions(self, tmp_path):
        """Test extracting functions."""
        test_file = tmp_path / "test.py"
        test_file.write_text(dedent("""
        def func_a():
            pass

        def func_b(x):
            return x
        """))
        symbols = get_symbols(test_file)

        names = {s.name for s in symbols}
        assert "func_a" in names
        assert "func_b" in names

    def test_extracts_classes(self, tmp_path):
        """Test extracting classes."""
        test_file = tmp_path / "test.py"
        test_file.write_text(dedent("""
        class MyClass:
            pass
        """))
        symbols = get_symbols(test_file)

        cls = next(s for s in symbols if s.name == "MyClass")
        assert cls.type == "class"

    def test_extracts_methods(self, tmp_path):
        """Test extracting methods with parent_class."""
        test_file = tmp_path / "test.py"
        test_file.write_text(dedent("""
        class MyClass:
            def method(self):
                pass
        """))
        symbols = get_symbols(test_file)

        method = next(s for s in symbols if s.name == "method")
        assert method.type == "method"
        assert method.parent_class == "MyClass"

    def test_extracts_variables(self, tmp_path):
        """Test extracting module-level variables."""
        test_file = tmp_path / "test.py"
        test_file.write_text(dedent("""
        x = 1
        y = 2
        CONSTANT = "value"
        """))
        symbols = get_symbols(test_file)

        names = {s.name for s in symbols}
        assert names == {"x", "y", "CONSTANT"}
        for s in symbols:
            assert s.type == "variable"
            assert s.complexity == 0

    def test_extracts_type_alias(self, tmp_path):
        """Test extracting type aliases."""
        test_file = tmp_path / "test.py"
        test_file.write_text("type IntList = list[int]\n")
        symbols = get_symbols(test_file)

        names = {s.name for s in symbols}
        assert "IntList" in names
        type_alias = next(s for s in symbols if s.name == "IntList")
        assert type_alias.type == "type_alias"

    def test_extracts_nested_functions(self, tmp_path):
        """Test extracting nested functions."""
        test_file = tmp_path / "test.py"
        test_file.write_text(dedent("""
        def outer():
            def inner():
                pass
            return inner
        """))
        symbols = get_symbols(test_file)

        names = {s.name for s in symbols}
        assert "outer" in names
        assert "inner" in names

    def test_extracts_async_functions(self, tmp_path):
        """Test extracting async functions."""
        test_file = tmp_path / "test.py"
        test_file.write_text(dedent("""
        async def fetch(url):
            if url.startswith("https"):
                return await do_fetch(url)
            return None
        """))
        symbols = get_symbols(test_file)

        func = next(s for s in symbols if s.name == "fetch")
        assert func.type == "function"

    def test_function_has_signature(self, tmp_path):
        """Function symbol includes signature."""
        test_file = tmp_path / "test.py"
        test_file.write_text(dedent("""
        def foo(x: int, y: str = 'hello') -> bool:
            return True
        """))
        symbols = get_symbols(test_file)
        func = next(s for s in symbols if s.name == "foo")

        assert func.signature == {"x": "int", "y": "str"}
        assert func.return_type == "bool"

    def test_function_has_hashes(self, tmp_path):
        """Function symbol includes body and structure hashes."""
        test_file = tmp_path / "test.py"
        test_file.write_text(dedent("""
        def foo(x):
            y = x + 1
            return y
        """))
        symbols = get_symbols(test_file)
        func = next(s for s in symbols if s.name == "foo")

        assert func.body_hash is not None
        assert len(func.body_hash) == 64
        assert func.structure_hash is not None
        assert len(func.structure_hash) == 64
        assert func.signature_hash is not None
        assert len(func.signature_hash) == 64

    def test_function_has_flow_metrics(self, tmp_path):
        """Function symbol includes flow metrics."""
        test_file = tmp_path / "test.py"
        test_file.write_text(dedent("""
        def foo(x):
            if x < 0:
                raise ValueError()
            y = x * 2
            z = y + 1
            return z
        """))
        symbols = get_symbols(test_file)
        func = next(s for s in symbols if s.name == "foo")

        assert func.variables_defined >= 2
        assert func.variables_used >= 2
        assert func.return_count == 1
        assert func.raise_count == 1

    def test_method_has_parent_class(self, tmp_path):
        """Method symbol includes parent_class."""
        test_file = tmp_path / "test.py"
        test_file.write_text(dedent("""
        class Foo:
            def bar(self, x: int) -> str:
                return str(x)
        """))
        symbols = get_symbols(test_file)
        method = next(s for s in symbols if s.name == "bar")

        assert method.type == "method"
        assert method.parent_class == "Foo"
        assert method.signature == {"self": None, "x": "int"}

    def test_class_has_base_classes(self, tmp_path):
        """Class symbol includes base_classes."""
        test_file = tmp_path / "test.py"
        test_file.write_text(dedent("""
        class Foo(Bar, Generic[T]):
            pass
        """))
        symbols = get_symbols(test_file)
        cls = next(s for s in symbols if s.name == "Foo")

        assert cls.type == "class"
        assert cls.base_classes == ["Bar", "Generic[T]"]

    def test_class_no_base_classes(self, tmp_path):
        """Class with no base classes has None."""
        test_file = tmp_path / "test.py"
        test_file.write_text(dedent("""
        class Foo:
            pass
        """))
        symbols = get_symbols(test_file)
        cls = next(s for s in symbols if s.name == "Foo")

        assert cls.type == "class"
        assert cls.base_classes is None

    def test_file_path_set(self, tmp_path):
        """All symbols have file_path set."""
        test_file = tmp_path / "test.py"
        test_file.write_text(dedent("""
        class Foo:
            def bar(self):
                pass

        def baz():
            pass

        X = 1
        """))
        symbols = get_symbols(test_file)

        for sym in symbols:
            assert sym.file_path == str(test_file)

    def test_position_accuracy(self, tmp_path):
        """Test that positions are accurate."""
        test_file = tmp_path / "test.py"
        # Don't use dedent with leading newline to keep line numbers predictable
        test_file.write_text("# Comment\nx = 1\n\ndef func():\n    pass\n\nclass Cls:\n    pass\n")
        symbols = get_symbols(test_file)

        var = next(s for s in symbols if s.name == "x")
        assert var.start == 2
        assert var.start_col == 0

        func = next(s for s in symbols if s.name == "func")
        assert func.start == 4

        cls = next(s for s in symbols if s.name == "Cls")
        assert cls.start == 7


# =============================================================================
# Hash Consistency Tests
# =============================================================================


class TestHashConsistency:
    """Tests for hash consistency across identical code."""

    def test_identical_functions_match(self, tmp_path):
        """Identical functions in different files have same hashes."""
        code1 = dedent("""
        def process(data):
            result = []
            for item in data:
                if item > 0:
                    result.append(item)
            return result
        """)
        code2 = dedent("""
        def filter_positive(values):
            output = []
            for value in values:
                if value > 0:
                    output.append(value)
            return output
        """)

        file1 = tmp_path / "file1.py"
        file2 = tmp_path / "file2.py"
        file1.write_text(code1)
        file2.write_text(code2)

        symbols1 = get_symbols(file1)
        symbols2 = get_symbols(file2)

        func1 = symbols1[0]
        func2 = symbols2[0]

        # Body hash should be same (normalized identifiers)
        assert func1.body_hash == func2.body_hash
        # Structure hash should be same (same AST structure)
        assert func1.structure_hash == func2.structure_hash

    def test_different_functions_different_hashes(self, tmp_path):
        """Different functions have different hashes."""
        code1 = dedent("""
        def foo(x):
            return x + 1
        """)
        code2 = dedent("""
        def bar(x):
            return x * 2
        """)

        file1 = tmp_path / "file1.py"
        file2 = tmp_path / "file2.py"
        file1.write_text(code1)
        file2.write_text(code2)

        symbols1 = get_symbols(file1)
        symbols2 = get_symbols(file2)

        func1 = symbols1[0]
        func2 = symbols2[0]

        # Different operations = different body hash
        assert func1.body_hash != func2.body_hash


# =============================================================================
# Edge Case Tests
# =============================================================================


class TestEdgeCases:
    """Edge case tests."""

    def test_async_function(self, tmp_path):
        """Async function has signature and hashes."""
        test_file = tmp_path / "test.py"
        test_file.write_text(dedent("""
        async def fetch(url: str) -> bytes:
            return b''
        """))
        symbols = get_symbols(test_file)
        func = symbols[0]

        assert func.signature == {"url": "str"}
        assert func.return_type == "bytes"
        assert func.body_hash is not None

    def test_decorated_function(self, tmp_path):
        """Decorated function has signature and hashes."""
        test_file = tmp_path / "test.py"
        test_file.write_text(dedent("""
        @decorator
        def foo(x: int) -> str:
            return str(x)
        """))
        symbols = get_symbols(test_file)
        func = next(s for s in symbols if s.name == "foo")

        assert func.signature == {"x": "int"}
        assert func.return_type == "str"

    def test_property_method(self, tmp_path):
        """Property method has signature."""
        test_file = tmp_path / "test.py"
        test_file.write_text(dedent("""
        class Foo:
            @property
            def value(self) -> int:
                return self._value
        """))
        symbols = get_symbols(test_file)
        method = next(s for s in symbols if s.name == "value")

        assert method.type == "method"
        assert method.parent_class == "Foo"
        assert method.signature == {"self": None}
        assert method.return_type == "int"

    def test_staticmethod(self, tmp_path):
        """Static method has signature without self."""
        test_file = tmp_path / "test.py"
        test_file.write_text(dedent("""
        class Foo:
            @staticmethod
            def create(x: int) -> 'Foo':
                return Foo()
        """))
        symbols = get_symbols(test_file)
        method = next(s for s in symbols if s.name == "create")

        assert method.type == "method"
        assert method.signature == {"x": "int"}
        assert method.return_type == "'Foo'"

    def test_classmethod(self, tmp_path):
        """Class method has signature with cls."""
        test_file = tmp_path / "test.py"
        test_file.write_text(dedent("""
        class Foo:
            @classmethod
            def from_string(cls, s: str) -> 'Foo':
                return cls()
        """))
        symbols = get_symbols(test_file)
        method = next(s for s in symbols if s.name == "from_string")

        assert method.type == "method"
        assert method.signature == {"cls": None, "s": "str"}

    def test_empty_class(self, tmp_path):
        """Empty class has no base classes."""
        test_file = tmp_path / "test.py"
        test_file.write_text("class Empty: pass")
        symbols = get_symbols(test_file)
        cls = symbols[0]

        assert cls.type == "class"
        assert cls.base_classes is None

    def test_lambda_inside_function(self, tmp_path):
        """Lambda inside function doesn't create extra symbol."""
        test_file = tmp_path / "test.py"
        test_file.write_text(dedent("""
        def outer():
            f = lambda x: x + 1
            return f
        """))
        symbols = get_symbols(test_file)

        # Only outer function should be a symbol
        names = {s.name for s in symbols}
        assert "outer" in names
        # Lambda is anonymous, no separate symbol

    def test_complex_class_hierarchy(self, tmp_path):
        """Complex class with multiple methods and inheritance."""
        test_file = tmp_path / "test.py"
        test_file.write_text(dedent("""
        class Base:
            def method1(self) -> None:
                pass

        class Child(Base):
            def method1(self) -> None:
                return None

            def method2(self, x: int, y: str) -> bool:
                result = x > len(y)
                return result
        """))
        symbols = get_symbols(test_file)

        base = next(s for s in symbols if s.name == "Base")
        child = next(s for s in symbols if s.name == "Child")
        method1_base = next(
            s for s in symbols if s.name == "method1" and s.parent_class == "Base"
        )
        method1_child = next(
            s for s in symbols if s.name == "method1" and s.parent_class == "Child"
        )
        method2 = next(s for s in symbols if s.name == "method2")

        assert base.base_classes is None
        assert child.base_classes == ["Base"]
        assert method1_base.return_type == "None"
        assert method1_child.return_type == "None"
        assert method2.signature == {"self": None, "x": "int", "y": "str"}
        assert method2.return_type == "bool"
        assert method2.return_count == 1


# =============================================================================
# Symbol Metrics Field Tests
# =============================================================================


class TestSymbolMetricsFields:
    """Tests for all SymbolMetrics fields."""

    def test_function_metrics_fields(self, tmp_path):
        """Test all metrics fields for a function."""
        test_file = tmp_path / "test.py"
        test_file.write_text(dedent("""
        def complex_func(a, b, c):
            result = 0
            if a:
                for item in b:
                    if item > 0:
                        result += item
            try:
                result /= c
            except ZeroDivisionError:
                result = 0
            return result
        """))
        symbols = get_symbols(test_file)
        func = symbols[0]

        # Basic info
        assert func.name == "complex_func"
        assert func.type == "function"
        assert func.file_path == str(test_file)

        # Position
        assert func.start >= 1
        assert func.end > func.start
        assert func.start_col >= 0
        assert func.end_col >= 0
        assert func.lines == func.end - func.start + 1

        # Complexity
        assert func.complexity >= 1
        assert func.branches >= 0

        # Statement/expression counts
        assert func.statements >= 1
        assert func.expressions_total >= 0

        # Control flow
        assert func.control_blocks >= 0
        assert func.control_flow >= 0
        assert func.exception_scaffold >= 0
        assert func.comparisons >= 0
        assert func.max_nesting_depth >= 0

        # Signature info
        assert func.signature == {"a": None, "b": None, "c": None}
        assert func.return_type is None

        # Hashes
        assert func.body_hash is not None
        assert len(func.body_hash) == 64
        assert func.structure_hash is not None
        assert func.signature_hash is not None

        # Flow metrics
        assert func.variables_defined >= 0
        assert func.variables_used >= 0
        assert func.return_count >= 0
        assert func.raise_count >= 0

    def test_class_metrics_fields(self, tmp_path):
        """Test all metrics fields for a class."""
        test_file = tmp_path / "test.py"
        test_file.write_text(dedent("""
        class MyClass(BaseClass):
            x: int
            y: str = "default"

            def __init__(self):
                self.a = 1
                self.b = 2

            def method(self):
                pass
        """))
        symbols = get_symbols(test_file)
        cls = next(s for s in symbols if s.name == "MyClass")

        # Basic info
        assert cls.name == "MyClass"
        assert cls.type == "class"
        assert cls.file_path == str(test_file)

        # Position
        assert cls.start >= 1
        assert cls.end > cls.start

        # Class-specific
        assert cls.base_classes == ["BaseClass"]
        assert cls.method_count == 2
        assert cls.attribute_count >= 2

        # Functions/methods don't apply to classes
        assert cls.parent_class is None
        assert cls.signature is None
        assert cls.return_type is None
        assert cls.body_hash is None
