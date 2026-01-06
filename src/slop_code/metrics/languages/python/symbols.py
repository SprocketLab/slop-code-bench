"""Tree-sitter based symbol extraction with complexity metrics."""

from __future__ import annotations

import hashlib
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


def _extract_signature(node: Node) -> tuple[dict[str, str | None], str | None]:
    """Extract function signature (parameters and return type).

    Args:
        node: The function_definition tree-sitter node.

    Returns:
        Tuple of (signature_dict, return_type) where signature_dict maps
        parameter names to their type annotations (or None if untyped).
    """
    signature: dict[str, str | None] = {}

    # Extract parameters
    params_node = node.child_by_field_name("parameters")
    if params_node:
        for child in params_node.named_children:
            param_name: str | None = None
            param_type: str | None = None

            if child.type == "identifier":
                # Simple parameter: def f(x)
                param_name = child.text.decode("utf-8")
            elif child.type == "typed_parameter":
                # Typed parameter: def f(x: int)
                name_node = child.child_by_field_name("name")
                if name_node is None:
                    # Fallback: first identifier child
                    for subchild in child.children:
                        if subchild.type == "identifier":
                            name_node = subchild
                            break
                if name_node:
                    param_name = name_node.text.decode("utf-8")
                type_node = child.child_by_field_name("type")
                if type_node:
                    param_type = type_node.text.decode("utf-8")
            elif child.type == "default_parameter":
                # Default parameter: def f(x=1)
                name_node = child.child_by_field_name("name")
                if name_node:
                    param_name = name_node.text.decode("utf-8")
            elif child.type == "typed_default_parameter":
                # Typed default parameter: def f(x: int = 1)
                name_node = child.child_by_field_name("name")
                if name_node:
                    param_name = name_node.text.decode("utf-8")
                type_node = child.child_by_field_name("type")
                if type_node:
                    param_type = type_node.text.decode("utf-8")
            elif child.type == "list_splat_pattern":
                # *args
                for subchild in child.children:
                    if subchild.type == "identifier":
                        param_name = "*" + subchild.text.decode("utf-8")
                        break
            elif child.type == "dictionary_splat_pattern":
                # **kwargs
                for subchild in child.children:
                    if subchild.type == "identifier":
                        param_name = "**" + subchild.text.decode("utf-8")
                        break

            if param_name:
                signature[param_name] = param_type

    # Extract return type
    return_type: str | None = None
    return_type_node = node.child_by_field_name("return_type")
    if return_type_node:
        return_type = return_type_node.text.decode("utf-8")

    return signature, return_type


def _extract_base_classes(node: Node) -> list[str]:
    """Extract base class names from a class definition.

    Args:
        node: The class_definition tree-sitter node.

    Returns:
        List of base class names as strings.
    """
    base_classes: list[str] = []

    # Look for argument_list which contains base classes
    for child in node.children:
        if child.type == "argument_list":
            for arg_child in child.named_children:
                if arg_child.type == "identifier":
                    # Simple base class: class Foo(Bar)
                    base_classes.append(arg_child.text.decode("utf-8"))
                elif arg_child.type == "attribute":
                    # Qualified base class: class Foo(module.Bar)
                    base_classes.append(arg_child.text.decode("utf-8"))
                elif arg_child.type == "subscript":
                    # Generic base class: class Foo(Generic[T])
                    base_classes.append(arg_child.text.decode("utf-8"))
                elif arg_child.type == "keyword_argument":
                    # metaclass=... or other keyword args - skip
                    pass
            break

    return base_classes


def _compute_body_hash(node: Node) -> str:
    """Compute hash of function body with normalized identifiers.

    Replaces all identifiers with positional placeholders (VAR_0, VAR_1, etc.)
    to detect code that is structurally identical but with renamed variables.

    Args:
        node: The function_definition tree-sitter node.

    Returns:
        SHA256 hash of the normalized body.
    """
    block = _get_block_child(node)
    if block is None:
        return hashlib.sha256(b"").hexdigest()

    # Build normalized representation
    identifier_map: dict[str, str] = {}
    counter = 0
    parts: list[str] = []

    stack: list[Node] = [block]
    while stack:
        current = stack.pop()
        if current.type == "identifier":
            name = current.text.decode("utf-8")
            if name not in identifier_map:
                identifier_map[name] = f"VAR_{counter}"
                counter += 1
            parts.append(identifier_map[name])
        elif current.type in {"string", "integer", "float"}:
            # Keep literals as-is for differentiation
            parts.append(current.text.decode("utf-8"))
        else:
            parts.append(current.type)

        # Add children in reverse to maintain order with stack
        stack.extend(reversed(current.children))

    normalized = " ".join(parts)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _compute_structure_hash(node: Node) -> str:
    """Compute hash of AST structure only (node types, no content).

    Ignores all identifiers, literals, and content - only considers
    the tree structure of node types.

    Args:
        node: The function_definition tree-sitter node.

    Returns:
        SHA256 hash of the structure.
    """
    block = _get_block_child(node)
    if block is None:
        return hashlib.sha256(b"").hexdigest()

    # Build structure representation using depth-first traversal
    parts: list[str] = []

    def traverse(n: Node, depth: int) -> None:
        parts.append(f"{depth}:{n.type}")
        for child in n.children:
            traverse(child, depth + 1)

    traverse(block, 0)

    structure = "|".join(parts)
    return hashlib.sha256(structure.encode("utf-8")).hexdigest()


def _compute_signature_hash(
    signature: dict[str, str | None], return_type: str | None
) -> str:
    """Compute hash of normalized function signature.

    Creates a canonical representation based on:
    - Number of parameters
    - Which parameters have type annotations
    - Whether there's a return type annotation

    Args:
        signature: Dict mapping parameter names to type annotations.
        return_type: Return type annotation or None.

    Returns:
        SHA256 hash of the normalized signature.
    """
    # Sort parameters by name for consistency
    sorted_params = sorted(signature.items())

    # Build canonical representation
    # Format: "arg_count:typed_positions:has_return"
    # typed_positions shows which args (by sorted index) have types
    typed_positions = [
        str(i) for i, (_, type_ann) in enumerate(sorted_params) if type_ann
    ]

    canonical = (
        f"{len(signature)}:"
        f"{','.join(typed_positions) if typed_positions else 'none'}:"
        f"{'1' if return_type else '0'}"
    )

    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _count_variables(node: Node) -> tuple[int, int]:
    """Count variable definitions and usages in a function body.

    Args:
        node: The function_definition tree-sitter node.

    Returns:
        Tuple of (variables_defined, variables_used).
    """
    block = _get_block_child(node)
    if block is None:
        return 0, 0

    defined: set[str] = set()
    used: set[str] = set()

    # Track assignment contexts to distinguish definitions from uses
    assignment_types = {
        "assignment",
        "augmented_assignment",
        "annotated_assignment",
    }

    stack: list[tuple[Node, bool]] = [(block, False)]
    while stack:
        current, in_assignment_target = stack.pop()

        if current.type in assignment_types:
            # Process left side as definition
            target = current.child_by_field_name("left")
            if target is None:
                target = current.child_by_field_name("target")
            if target:
                stack.append((target, True))
            # Process right side as usage
            value = current.child_by_field_name("right")
            if value is None:
                value = current.child_by_field_name("value")
            if value:
                stack.append((value, False))
            # Process type annotation if present
            type_node = current.child_by_field_name("type")
            if type_node:
                stack.append((type_node, False))
            continue

        if current.type == "identifier":
            name = current.text.decode("utf-8")
            if in_assignment_target:
                defined.add(name)
            else:
                used.add(name)
        else:
            for child in reversed(current.children):
                stack.append((child, in_assignment_target))

    return len(defined), len(used)


def _count_returns_and_raises(node: Node) -> tuple[int, int]:
    """Count return and raise statements in a function body.

    Args:
        node: The function_definition tree-sitter node.

    Returns:
        Tuple of (return_count, raise_count).
    """
    block = _get_block_child(node)
    if block is None:
        return 0, 0

    return_count = 0
    raise_count = 0

    stack: list[Node] = [block]
    while stack:
        current = stack.pop()
        if current.type == "return_statement":
            return_count += 1
        elif current.type == "raise_statement":
            raise_count += 1

        # Don't count returns/raises inside nested functions
        if current.type not in {"function_definition", "lambda"}:
            stack.extend(current.children)

    return return_count, raise_count


def _create_symbol(
    node: Node,
    name: str,
    symbol_type: str,
    include_base_complexity: bool = False,
    *,
    parent_class: str | None = None,
    base_classes: list[str] | None = None,
    signature: dict[str, str | None] | None = None,
    return_type: str | None = None,
    body_hash: str | None = None,
    structure_hash: str | None = None,
    signature_hash: str | None = None,
    variables_defined: int = 0,
    variables_used: int = 0,
    return_count: int = 0,
    raise_count: int = 0,
) -> SymbolMetrics:
    """Create a SymbolMetrics from a tree-sitter node.

    Args:
        node: The tree-sitter node to create metrics from.
        name: The name of the symbol.
        symbol_type: The type of symbol (function, method, class, variable,
            type_alias).
        include_base_complexity: If True, add 1 to complexity (for
            functions/methods).
        parent_class: Name of parent class if this is a method.
        base_classes: List of base class names for class definitions.
        signature: Dict mapping parameter names to type annotations.
        return_type: Return type annotation.
        body_hash: Hash of normalized function body.
        structure_hash: Hash of AST structure only.
        signature_hash: Hash of normalized signature.
        variables_defined: Number of variable definitions.
        variables_used: Number of variable usages.
        return_count: Number of return statements.
        raise_count: Number of raise statements.

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
        parent_class=parent_class,
        base_classes=base_classes,
        signature=signature,
        return_type=return_type,
        body_hash=body_hash,
        structure_hash=structure_hash,
        signature_hash=signature_hash,
        variables_defined=variables_defined,
        variables_used=variables_used,
        return_count=return_count,
        raise_count=raise_count,
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

    # Extract signature and hashes
    signature, return_type = _extract_signature(node)
    body_hash = _compute_body_hash(node)
    structure_hash = _compute_structure_hash(node)
    signature_hash = _compute_signature_hash(signature, return_type)

    # Extract flow metrics
    variables_defined, variables_used = _count_variables(node)
    return_count, raise_count = _count_returns_and_raises(node)

    symbols.append(
        _create_symbol(
            node,
            name,
            symbol_type,
            include_base_complexity=True,
            parent_class=parent_class,
            signature=signature,
            return_type=return_type,
            body_hash=body_hash,
            structure_hash=structure_hash,
            signature_hash=signature_hash,
            variables_defined=variables_defined,
            variables_used=variables_used,
            return_count=return_count,
            raise_count=raise_count,
        )
    )

    # Check for nested functions (not at module level)
    _extract_symbols_from_node(
        node, symbols, parent_class=None, at_module_level=False
    )


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
    base_classes = _extract_base_classes(node)

    symbol = _create_symbol(
        node,
        name,
        "class",
        include_base_complexity=False,
        base_classes=base_classes if base_classes else None,
    )
    symbol.method_count = method_count
    symbol.attribute_count = attribute_count
    symbols.append(symbol)

    # Extract methods from inside the class (not at module level)
    _extract_symbols_from_node(
        node, symbols, parent_class=name, at_module_level=False
    )


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

    # Set file_path on all symbols
    file_path_str = str(source)
    for sym in symbols:
        sym.file_path = file_path_str

    return symbols
