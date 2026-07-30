"""Abstraction waste pattern detection."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from slop_code.metrics.languages.python.parser import get_python_parser
from slop_code.metrics.languages.python.symbols import _get_block_child
from slop_code.metrics.languages.python.symbols import _get_name_from_node
from slop_code.metrics.languages.python.symbols import _node_text
from slop_code.metrics.languages.python.utils import read_python_code
from slop_code.metrics.models import SingleUseFunction
from slop_code.metrics.models import SingleUseVariable
from slop_code.metrics.models import SymbolMetrics
from slop_code.metrics.models import TrivialWrapper
from slop_code.metrics.models import UnusedVariable
from slop_code.metrics.models import WasteMetrics

if TYPE_CHECKING:
    from tree_sitter import Node


def _find_call_sites(root: Node) -> dict[str, list[int]]:
    """Find all function call sites in the file."""
    call_sites: dict[str, list[int]] = {}
    stack = [root]
    while stack:
        current = stack.pop()
        if current.type == "call":
            func = current.child_by_field_name("function")
            if func is None and current.named_children:
                func = current.named_children[0]
            name: str | None = None
            if func and func.type == "identifier":
                name = _node_text(func)
            elif func and func.type == "attribute":
                attr_child = func.child_by_field_name("attribute")
                if attr_child and attr_child.type == "identifier":
                    name = _node_text(attr_child)
            if name:
                call_sites.setdefault(name, []).append(
                    current.start_point[0] + 1
                )
        stack.extend(current.children)
    return call_sites


def _is_docstring_statement(node: Node) -> bool:
    """Return True if node represents a docstring expression statement."""
    if node.type != "expression_statement":
        return False
    if not node.named_children:
        return False
    child = node.named_children[0]
    return child.type == "string"


def _find_single_call(expr: Node) -> Node | None:
    """Return the call node if expr contains exactly one call node, else None."""
    # unwrap common wrappers that don't add new calls
    while expr and expr.type in {"parenthesized_expression"}:
        # tree-sitter-python uses "expression" for parenthesized_expression
        inner = expr.child_by_field_name("expression")
        if inner is None and expr.named_children:
            inner = expr.named_children[0]
        if inner is None:
            break
        expr = inner

    calls: list[Node] = []
    stack = [expr]
    while stack:
        n = stack.pop()
        if n.type == "call":
            calls.append(n)
            # keep walking to detect nested calls like f(g(x))
        for ch in n.named_children:
            stack.append(ch)

    return calls[0] if len(calls) == 1 else None


def _callee_name(call: Node) -> str | None:
    func = call.child_by_field_name("function")
    if func is None and call.named_children:
        func = call.named_children[0]

    if not func:
        return None
    if func.type == "identifier":
        return _node_text(func)
    if func.type == "attribute":
        # your current behavior: last attribute only (foo.bar -> "bar")
        attr = func.child_by_field_name("attribute")
        if attr and attr.type == "identifier":
            return _node_text(attr)
    return None


def _is_trivial_wrapper(func_node: Node) -> tuple[bool, str | None]:
    block = _get_block_child(func_node)
    if block is None:
        return False, None

    statements = [
        ch for ch in block.named_children if ch.type != "pass_statement"
    ]
    non_doc = [s for s in statements if not _is_docstring_statement(s)]
    if len(non_doc) != 1:
        return False, None

    stmt = non_doc[0]

    expr = None
    if stmt.type == "return_statement":
        expr = stmt.child_by_field_name("argument")
        if expr is None and stmt.named_children:
            expr = stmt.named_children[0]
    elif stmt.type == "expression_statement":
        expr = stmt.child_by_field_name("expression")
        if expr is None and stmt.named_children:
            expr = stmt.named_children[0]
    else:
        return False, None

    if expr is None:
        return False, None

    call = _find_single_call(expr)
    if call is None:
        return False, None

    wrapped = _callee_name(call)
    return (True, wrapped) if wrapped else (False, None)


_IGNORED_VARIABLE_NAMES = frozenset({"self", "cls", "_"})

_ASSIGNMENT_TYPES = frozenset(
    {
        "assignment",
        "augmented_assignment",
        "annotated_assignment",
    }
)


def _extract_parameter_names(func_node: Node) -> set[str]:
    """Extract parameter names from a function_definition node."""
    names: set[str] = set()
    params_node = func_node.child_by_field_name("parameters")
    if not params_node:
        return names
    for child in params_node.named_children:
        if child.type == "identifier":
            names.add(_node_text(child))
        elif child.type in {
            "typed_parameter",
            "default_parameter",
            "typed_default_parameter",
        }:
            name_node = child.child_by_field_name("name")
            if name_node is None:
                for subchild in child.children:
                    if subchild.type == "identifier":
                        name_node = subchild
                        break
            if name_node:
                names.add(_node_text(name_node))
        elif child.type in {"list_splat_pattern", "dictionary_splat_pattern"}:
            for subchild in child.children:
                if subchild.type == "identifier":
                    names.add(_node_text(subchild))
                    break
    return names


def _count_variable_occurrences(
    block: Node,
) -> dict[str, tuple[int, int, int]]:
    """Count per-variable definitions and usages in a block.

    Returns:
        Dict mapping variable name to (def_count, use_count, first_def_line).
    """
    # {name: [def_count, use_count, first_def_line]}
    counts: dict[str, list[int]] = {}

    stack: list[tuple[Node, bool]] = [(block, False)]
    while stack:
        current, in_target = stack.pop()

        if current.type in _ASSIGNMENT_TYPES:
            target = current.child_by_field_name("left")
            if target is None:
                target = current.child_by_field_name("target")
            if target:
                stack.append((target, True))
            value = current.child_by_field_name("right")
            if value is None:
                value = current.child_by_field_name("value")
            if value:
                stack.append((value, False))
            type_node = current.child_by_field_name("type")
            if type_node:
                stack.append((type_node, False))
            continue

        if current.type == "identifier":
            name = _node_text(current)
            if name not in counts:
                counts[name] = [0, 0, current.start_point[0] + 1]
            if in_target:
                counts[name][0] += 1
                counts[name][2] = current.start_point[0] + 1
            else:
                counts[name][1] += 1
        else:
            for child in reversed(current.children):
                stack.append((child, in_target))

    return {n: (c[0], c[1], c[2]) for n, c in counts.items()}


def _find_single_use_variables(
    root: Node, symbols: list[SymbolMetrics]
) -> list[SingleUseVariable]:
    """Find variables assigned exactly once and used exactly once."""
    results: list[SingleUseVariable] = []

    # Build a set of function/class line ranges to exclude from module-level scan
    symbol_ranges: list[tuple[int, int, str]] = []
    for sym in symbols:
        if sym.type in ("function", "method", "class"):
            symbol_ranges.append((sym.start, sym.end, sym.name))

    # --- Per-function detection ---
    func_nodes: list[tuple[str, Node]] = []
    stack = [root]
    while stack:
        current = stack.pop()
        if current.type == "function_definition":
            name = _get_name_from_node(current)
            if name:
                func_nodes.append((name, current))
        stack.extend(current.children)

    for func_name, func_node in func_nodes:
        block = _get_block_child(func_node)
        if block is None:
            continue
        param_names = _extract_parameter_names(func_node)
        counts = _count_variable_occurrences(block)
        for var_name, (defs, uses, def_line) in counts.items():
            if var_name in param_names or var_name in _IGNORED_VARIABLE_NAMES:
                continue
            if defs == 1 and uses == 1:
                results.append(
                    SingleUseVariable(
                        name=var_name, line=def_line, scope=func_name
                    )
                )

    # --- Module-level detection ---
    module_counts: dict[
        str, list[int]
    ] = {}  # {name: [def_count, use_count, def_line]}

    for child in root.children:
        # Only look at top-level statements, skip function/class definitions
        if child.type in {
            "function_definition",
            "class_definition",
            "decorated_definition",
        }:
            continue

        sub_stack: list[tuple[Node, bool]] = [(child, False)]
        while sub_stack:
            current, in_target = sub_stack.pop()

            if current.type in _ASSIGNMENT_TYPES:
                target = current.child_by_field_name("left")
                if target is None:
                    target = current.child_by_field_name("target")
                if target:
                    sub_stack.append((target, True))
                value = current.child_by_field_name("right")
                if value is None:
                    value = current.child_by_field_name("value")
                if value:
                    sub_stack.append((value, False))
                type_node = current.child_by_field_name("type")
                if type_node:
                    sub_stack.append((type_node, False))
                continue

            if current.type == "identifier":
                name = _node_text(current)
                if name not in module_counts:
                    module_counts[name] = [0, 0, current.start_point[0] + 1]
                if in_target:
                    module_counts[name][0] += 1
                    module_counts[name][2] = current.start_point[0] + 1
                else:
                    module_counts[name][1] += 1
            else:
                for ch in reversed(current.children):
                    sub_stack.append((ch, in_target))

    for var_name, (defs, uses, def_line) in module_counts.items():
        if var_name in _IGNORED_VARIABLE_NAMES:
            continue
        if defs == 1 and uses == 1:
            results.append(
                SingleUseVariable(name=var_name, line=def_line, scope="module")
            )

    return results


def _find_unused_variables(
    root: Node, symbols: list[SymbolMetrics]
) -> list[UnusedVariable]:
    """Find variables assigned but never referenced."""
    results: list[UnusedVariable] = []

    # --- Per-function detection ---
    func_nodes: list[tuple[str, Node]] = []
    stack = [root]
    while stack:
        current = stack.pop()
        if current.type == "function_definition":
            name = _get_name_from_node(current)
            if name:
                func_nodes.append((name, current))
        stack.extend(current.children)

    for func_name, func_node in func_nodes:
        block = _get_block_child(func_node)
        if block is None:
            continue
        param_names = _extract_parameter_names(func_node)
        counts = _count_variable_occurrences(block)
        for var_name, (defs, uses, def_line) in counts.items():
            if var_name in param_names or var_name in _IGNORED_VARIABLE_NAMES:
                continue
            if defs >= 1 and uses == 0:
                results.append(
                    UnusedVariable(
                        name=var_name, line=def_line, scope=func_name
                    )
                )

    # --- Module-level detection ---
    module_counts: dict[str, list[int]] = {}

    for child in root.children:
        if child.type in {
            "function_definition",
            "class_definition",
            "decorated_definition",
        }:
            continue

        sub_stack: list[tuple[Node, bool]] = [(child, False)]
        while sub_stack:
            current, in_target = sub_stack.pop()

            if current.type in _ASSIGNMENT_TYPES:
                target = current.child_by_field_name("left")
                if target is None:
                    target = current.child_by_field_name("target")
                if target:
                    sub_stack.append((target, True))
                value = current.child_by_field_name("right")
                if value is None:
                    value = current.child_by_field_name("value")
                if value:
                    sub_stack.append((value, False))
                type_node = current.child_by_field_name("type")
                if type_node:
                    sub_stack.append((type_node, False))
                continue

            if current.type == "identifier":
                name = _node_text(current)
                if name not in module_counts:
                    module_counts[name] = [0, 0, current.start_point[0] + 1]
                if in_target:
                    module_counts[name][0] += 1
                    module_counts[name][2] = current.start_point[0] + 1
                else:
                    module_counts[name][1] += 1
            else:
                for ch in reversed(current.children):
                    sub_stack.append((ch, in_target))

    for var_name, (defs, uses, def_line) in module_counts.items():
        if var_name in _IGNORED_VARIABLE_NAMES:
            continue
        if defs >= 1 and uses == 0:
            results.append(
                UnusedVariable(name=var_name, line=def_line, scope="module")
            )

    return results


def detect_waste(source: Path, symbols: list[SymbolMetrics]) -> WasteMetrics:
    """Detect abstraction waste patterns."""
    code = read_python_code(source)
    if not code.strip():
        return WasteMetrics(
            single_use_functions=[],
            trivial_wrappers=[],
            single_method_classes=[],
            single_use_count=0,
            trivial_wrapper_count=0,
            single_method_class_count=0,
        )

    parser = get_python_parser()
    tree = parser.parse(code.encode("utf-8"))

    call_sites = _find_call_sites(tree.root_node)

    single_use_functions: list[SingleUseFunction] = []
    for symbol in symbols:
        if symbol.type != "function":
            continue
        calls = call_sites.get(symbol.name, [])
        # Exclude self-calls (recursion) — calls within the function's own body
        external_calls = [
            ln for ln in calls if not (symbol.start <= ln <= symbol.end)
        ]
        if len(external_calls) <= 1:
            single_use_functions.append(
                SingleUseFunction(
                    name=symbol.name,
                    line=symbol.start,
                    called_from_line=external_calls[0]
                    if external_calls
                    else None,
                )
            )

    func_nodes: dict[str, Node] = {}
    stack = [tree.root_node]
    while stack:
        current = stack.pop()
        if current.type == "function_definition":
            name = _get_name_from_node(current)
            if name and current.parent and current.parent.type == "module":
                func_nodes[name] = current
        stack.extend(current.children)

    trivial_wrappers: list[TrivialWrapper] = []
    for name, node in func_nodes.items():
        is_wrapper, wrapped = _is_trivial_wrapper(node)
        if is_wrapper and wrapped:
            trivial_wrappers.append(
                TrivialWrapper(
                    name=name,
                    line=node.start_point[0] + 1,
                    wraps=wrapped,
                )
            )

    single_method_classes = [
        symbol.name
        for symbol in symbols
        if symbol.type == "class" and symbol.method_count == 1
    ]

    single_use_variables = _find_single_use_variables(tree.root_node, symbols)
    unused_variables = _find_unused_variables(tree.root_node, symbols)

    return WasteMetrics(
        single_use_functions=single_use_functions,
        trivial_wrappers=trivial_wrappers,
        single_method_classes=single_method_classes,
        single_use_count=len(single_use_functions),
        trivial_wrapper_count=len(trivial_wrappers),
        single_method_class_count=len(single_method_classes),
        single_use_variables=single_use_variables,
        single_use_variable_count=len(single_use_variables),
        unused_variables=unused_variables,
        unused_variable_count=len(unused_variables),
    )


def calculate_waste_metrics(
    source: Path, symbols: list[SymbolMetrics]
) -> WasteMetrics:
    """Calculate waste metrics for a Python file."""
    return detect_waste(source, symbols)
