"""Abstraction waste pattern detection."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from slop_code.metrics.languages.python.parser import get_python_parser
from slop_code.metrics.languages.python.symbols import _get_block_child
from slop_code.metrics.languages.python.symbols import _get_name_from_node
from slop_code.metrics.languages.python.utils import read_python_code
from slop_code.metrics.models import SingleUseFunction
from slop_code.metrics.models import SymbolMetrics
from slop_code.metrics.models import TrivialWrapper
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
                name = func.text.decode("utf-8")
            elif func and func.type == "attribute":
                attr_child = func.child_by_field_name("attribute")
                if attr_child and attr_child.type == "identifier":
                    name = attr_child.text.decode("utf-8")
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
        return func.text.decode("utf-8")
    if func.type == "attribute":
        # your current behavior: last attribute only (foo.bar -> "bar")
        attr = func.child_by_field_name("attribute")
        if attr and attr.type == "identifier":
            return attr.text.decode("utf-8")
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
        if len(calls) <= 1:
            single_use_functions.append(
                SingleUseFunction(
                    name=symbol.name,
                    line=symbol.start,
                    called_from_line=calls[0] if calls else None,
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

    return WasteMetrics(
        single_use_functions=single_use_functions,
        trivial_wrappers=trivial_wrappers,
        single_method_classes=single_method_classes,
        single_use_count=len(single_use_functions),
        trivial_wrapper_count=len(trivial_wrappers),
        single_method_class_count=len(single_method_classes),
    )


def calculate_waste_metrics(
    source: Path, symbols: list[SymbolMetrics]
) -> WasteMetrics:
    """Calculate waste metrics for a Python file."""
    return detect_waste(source, symbols)
