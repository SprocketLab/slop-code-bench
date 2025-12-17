"""Tree-sitter based symbol extraction with complexity metrics."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from slop_code.metrics.languages.python.constants import COMPLEXITY_NODE_TYPES
from slop_code.metrics.languages.python.constants import CONTROL_BLOCK_TYPES
from slop_code.metrics.languages.python.constants import CONTROL_FLOW_NODE_TYPES
from slop_code.metrics.languages.python.constants import (
    EXCEPTION_SCAFFOLD_NODE_TYPES,
)
from slop_code.metrics.languages.python.constants import EXPRESSION_NODE_TYPES
from slop_code.metrics.languages.python.constants import STATEMENT_NODE_TYPES
from slop_code.metrics.languages.python.parser import get_python_parser
from slop_code.metrics.languages.python.utils import read_python_code
from slop_code.metrics.models import SymbolMetrics

if TYPE_CHECKING:
    from tree_sitter import Node


def _count_complexity_and_branches(node: Node) -> tuple[int, int]:
    """Count complexity-contributing nodes and branches within a node.

    Args:
        node: The tree-sitter node to analyze.

    Returns:
        Tuple of (complexity_count, branch_count).
    """
    complexity = 0
    branches = 0
    stack = [node]

    while stack:
        current = stack.pop()
        if current.type in COMPLEXITY_NODE_TYPES:
            complexity += 1
            # Branches are decision points (not including boolean operators)
            if current.type not in {
                "boolean_operator",
                "conditional_expression",
            }:
                branches += 1

        for child in current.children:
            stack.append(child)

    return complexity, branches


def _count_statements(node: Node) -> int:
    """Count statement nodes within a node.

    Args:
        node: The tree-sitter node to analyze.

    Returns:
        Number of statements found.
    """
    count = 0
    stack = [node]

    while stack:
        current = stack.pop()
        if current.type in STATEMENT_NODE_TYPES:
            count += 1

        for child in current.children:
            stack.append(child)

    return count


def _get_block_child(node: Node) -> Node | None:
    """Return the block child of a node if present."""
    for child in node.children:
        if child.type == "block":
            return child
    return None


def _count_expressions(node: Node) -> tuple[int, int]:
    """Count expressions within a node.

    Returns:
        Tuple of (top_level_count, total_count).
    """
    total = 0
    stack = [node]
    while stack:
        current = stack.pop()
        if current.type in EXPRESSION_NODE_TYPES:
            total += 1
        stack.extend(current.children)

    top_level = 0
    block = _get_block_child(node)
    if block:
        for child in block.named_children:
            if child.type in EXPRESSION_NODE_TYPES:
                top_level += 1
    return top_level, total


def _count_control_blocks(node: Node) -> int:
    """Count top-level control blocks in a function body."""
    block = _get_block_child(node)
    if block is None:
        return 0

    count = 0
    for child in block.named_children:
        if child.type in CONTROL_BLOCK_TYPES:
            count += 1
    return count


def _calculate_max_depth(node: Node) -> int:
    """Calculate maximum nesting depth of control structures."""
    max_depth = 0
    stack: list[tuple[Node, int]] = [(node, 0)]

    while stack:
        current, depth = stack.pop()
        new_depth = depth
        if current.type in CONTROL_BLOCK_TYPES:
            new_depth = depth + 1
            max_depth = max(max_depth, new_depth)

        for child in current.children:
            stack.append((child, new_depth))

    return max_depth


def _count_control_flow_and_comparisons(
    node: Node,
) -> tuple[int, int, int]:
    """Count control flow, exception scaffolds, and comparisons."""
    control_flow = 0
    exception_scaffold = 0
    comparisons = 0

    stack = [node]
    while stack:
        current = stack.pop()
        if current.type in CONTROL_FLOW_NODE_TYPES:
            control_flow += 1
        if current.type in EXCEPTION_SCAFFOLD_NODE_TYPES:
            exception_scaffold += 1
        if current.type == "comparison_operator":
            operand_count = sum(
                1 for child in current.children if child.is_named
            )
            if operand_count:
                comparisons += operand_count - 1
        stack.extend(current.children)

    return control_flow, exception_scaffold, comparisons


def _count_methods(class_node: Node) -> int:
    """Count methods directly defined on a class."""
    block = _get_block_child(class_node)
    if block is None:
        return 0

    count = 0
    for child in block.named_children:
        if child.type == "function_definition":
            count += 1
        elif child.type == "decorated_definition":
            if any(
                grandchild.type == "function_definition"
                for grandchild in child.children
            ):
                count += 1
    return count


def _get_self_attribute_name(node: Node) -> str | None:
    """Return attribute name if node represents `self.<attr>`."""
    obj = node.child_by_field_name("object")
    attr = node.child_by_field_name("attribute")
    if (
        obj
        and obj.type == "identifier"
        and obj.text.decode("utf-8") == "self"
        and attr
        and attr.type == "identifier"
    ):
        return attr.text.decode("utf-8")
    return None


def _extract_assignment_targets(assign_node: Node) -> list[Node]:
    """Return nodes representing assignment targets."""
    targets: list[Node] = []
    for field_name in ("left", "target"):
        target = assign_node.child_by_field_name(field_name)
        if target:
            targets.append(target)
    if not targets and assign_node.named_children:
        targets.append(assign_node.named_children[0])
    return targets


def _collect_self_attributes_from_target(
    target: Node, attributes: set[str]
) -> None:
    """Collect self attribute names from an assignment target node."""
    if target.type == "attribute":
        name = _get_self_attribute_name(target)
        if name:
            attributes.add(name)
    for child in target.named_children:
        _collect_self_attributes_from_target(child, attributes)


def _get_identifier_from_target(target: Node) -> str | None:
    """Return identifier name from an assignment target if present."""
    if target.type in {"identifier", "name"}:
        return target.text.decode("utf-8")
    return None


def _count_class_attributes(class_node: Node) -> int:
    """Count unique self.x attribute assignments in a class."""
    attributes: set[str] = set()
    stack: list[tuple[Node, bool]] = [(class_node, False)]
    while stack:
        current, in_function = stack.pop()
        in_function = in_function or current.type in {
            "function_definition",
            "decorated_definition",
        }
        if current.type in {
            "assignment",
            "augmented_assignment",
            "annotated_assignment",
        }:
            for target in _extract_assignment_targets(current):
                if not in_function:
                    identifier = _get_identifier_from_target(target)
                    if identifier:
                        attributes.add(identifier)
                _collect_self_attributes_from_target(target, attributes)
        for child in current.named_children:
            stack.append((child, in_function))
    return len(attributes)


def _get_name_from_node(node: Node) -> str | None:
    """Extract the name from a definition node.

    Args:
        node: The tree-sitter node (function_definition, class_definition,
            etc.)

    Returns:
        The name string or None if not found.
    """
    for child in node.children:
        if child.type == "identifier":
            return child.text.decode("utf-8")
        if child.type == "name":
            return child.text.decode("utf-8")
        # For type_alias_statement, the name is in a "type" node
        if child.type == "type" and node.type == "type_alias_statement":
            for subchild in child.children:
                if subchild.type == "identifier":
                    return subchild.text.decode("utf-8")
    return None


def _get_assignment_name(node: Node) -> str | None:
    """Extract the name from an assignment node.

    Args:
        node: The tree-sitter assignment, augmented_assignment, or
            annotated_assignment node.

    Returns:
        The name string or None if not a simple identifier assignment.
    """
    target = node.child_by_field_name("left")
    if target is None:
        return None
    if target.type in {"identifier", "name"}:
        return target.text.decode("utf-8")
    return None


def _create_symbol(
    node: Node,
    name: str,
    symbol_type: str,
    include_base_complexity: bool = False,
) -> SymbolMetrics:
    """Create a SymbolMetrics from a tree-sitter node.

    Args:
        node: The tree-sitter node to create metrics from.
        name: The name of the symbol.
        symbol_type: The type of symbol (function, method, class, variable,
            type_alias).
        include_base_complexity: If True, add 1 to complexity (for
            functions/methods).

    Returns:
        A SymbolMetrics instance with computed metrics.
    """
    complexity, branches = _count_complexity_and_branches(node)
    statements = _count_statements(node)
    expr_top, expr_total = _count_expressions(node)
    control_blocks = _count_control_blocks(node)
    max_depth = _calculate_max_depth(node)
    control_flow, exception_scaffold, comparisons = (
        _count_control_flow_and_comparisons(node)
    )
    lines = node.end_point[0] - node.start_point[0] + 1

    return SymbolMetrics(
        name=name,
        type=symbol_type,
        start=node.start_point[0] + 1,
        start_col=node.start_point[1],
        end=node.end_point[0] + 1,
        end_col=node.end_point[1],
        complexity=(1 + complexity) if include_base_complexity else complexity,
        branches=branches,
        statements=statements,
        expressions_top_level=expr_top,
        expressions_total=expr_total,
        control_blocks=control_blocks,
        control_flow=control_flow,
        exception_scaffold=exception_scaffold,
        comparisons=comparisons,
        max_nesting_depth=max_depth,
        lines=lines,
    )


def _handle_function_definition(
    node: Node,
    symbols: list[SymbolMetrics],
    parent_class: str | None,
) -> None:
    """Handle function_definition nodes.

    Args:
        node: The function_definition tree-sitter node.
        symbols: List to append extracted symbols to.
        parent_class: Name of parent class if this is a method.
    """
    name = _get_name_from_node(node)
    if not name:
        return

    symbol_type = "method" if parent_class else "function"
    symbols.append(
        _create_symbol(node, name, symbol_type, include_base_complexity=True)
    )

    # Check for nested functions (not at module level)
    _extract_symbols_from_node(node, symbols, parent_class=None, at_module_level=False)


def _handle_class_definition(
    node: Node,
    symbols: list[SymbolMetrics],
) -> None:
    """Handle class_definition nodes.

    Args:
        node: The class_definition tree-sitter node.
        symbols: List to append extracted symbols to.
    """
    name = _get_name_from_node(node)
    if not name:
        return

    method_count = _count_methods(node)
    attribute_count = _count_class_attributes(node)

    symbol = _create_symbol(node, name, "class", include_base_complexity=False)
    symbol.method_count = method_count
    symbol.attribute_count = attribute_count
    symbols.append(symbol)

    # Extract methods from inside the class (not at module level)
    _extract_symbols_from_node(node, symbols, parent_class=name, at_module_level=False)


def _handle_assignment(node: Node, symbols: list[SymbolMetrics]) -> None:
    """Handle module-level assignment nodes.

    Args:
        node: The assignment or expression_statement tree-sitter node.
        symbols: List to append extracted symbols to.
    """
    assign_node = node
    if node.type == "expression_statement":
        for subchild in node.children:
            if subchild.type == "assignment":
                assign_node = subchild
                break
        else:
            return

    name = _get_assignment_name(assign_node)
    if name:
        symbols.append(
            SymbolMetrics(
                name=name,
                type="variable",
                start=node.start_point[0] + 1,
                start_col=node.start_point[1],
                end=node.end_point[0] + 1,
                end_col=node.end_point[1],
                complexity=0,
                branches=0,
                statements=1,
            )
        )


def _handle_type_alias(node: Node, symbols: list[SymbolMetrics]) -> None:
    """Handle type_alias_statement nodes.

    Args:
        node: The type_alias_statement tree-sitter node.
        symbols: List to append extracted symbols to.
    """
    name = _get_name_from_node(node)
    if name:
        symbols.append(
            _create_symbol(
                node, name, "type_alias", include_base_complexity=False
            )
        )


def _extract_symbols_from_node(
    node: Node,
    symbols: list[SymbolMetrics],
    parent_class: str | None = None,
    at_module_level: bool = False,
) -> None:
    """Recursively extract symbols from a tree-sitter node.

    Args:
        node: The tree-sitter node to process.
        symbols: List to append extracted symbols to.
        parent_class: Name of parent class if inside a class definition.
        at_module_level: True only when processing actual module-level nodes.
    """
    for child in node.children:
        if child.type == "function_definition":
            _handle_function_definition(child, symbols, parent_class)

        elif child.type == "class_definition":
            _handle_class_definition(child, symbols)

        elif child.type == "decorated_definition":
            _extract_symbols_from_node(
                child, symbols, parent_class, at_module_level
            )

        elif child.type in ("assignment", "expression_statement"):
            if at_module_level:
                _handle_assignment(child, symbols)

        elif child.type == "type_alias_statement":
            if at_module_level:
                _handle_type_alias(child, symbols)

        elif child.type == "block":
            _extract_symbols_from_node(child, symbols, parent_class, False)


def get_symbols(source: Path) -> list[SymbolMetrics]:
    """Extract all symbols from a Python source file using tree-sitter.

    Extracts functions, classes, methods, module-level variables, and type
    aliases. For each symbol, calculates cyclomatic complexity, branch count,
    and statement count.

    Args:
        source: Path to the Python source file.

    Returns:
        List of SymbolMetrics for all symbols found in the file.
    """
    code = read_python_code(source)
    if not code.strip():
        return []
    parser = get_python_parser()
    tree = parser.parse(code.encode("utf-8"))

    symbols: list[SymbolMetrics] = []
    _extract_symbols_from_node(tree.root_node, symbols, at_module_level=True)

    return symbols
