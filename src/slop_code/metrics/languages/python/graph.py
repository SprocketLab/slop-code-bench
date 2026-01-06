"""Program dependency graph construction and metrics."""

from __future__ import annotations

from pathlib import Path

import networkx as nx
from tree_sitter import Node

from slop_code.logging import get_logger
from slop_code.metrics.languages.python.imports import trace_source_files
from slop_code.metrics.languages.python.parser import get_python_parser
from slop_code.metrics.models import GraphMetrics

logger = get_logger(__name__)


def _extract_functions_from_file(file_path: Path) -> list[tuple[str, Node]]:
    """Extract all function and method definitions from a Python file.

    Args:
        file_path: Path to Python file.

    Returns:
        List of (qualified_name, node) tuples for each function/method.
        qualified_name format: "ClassName.method_name" or "function_name"
    """
    parser = get_python_parser()

    try:
        source_code = file_path.read_bytes()
        tree = parser.parse(source_code)
    except Exception as e:  # noqa: BLE001
        logger.debug(
            "Failed to parse file for function extraction",
            file=str(file_path),
            error=str(e),
        )
        return []

    functions = []

    def visit_node(node: Node, class_name: str | None = None):
        """Recursively visit nodes to extract functions."""
        if node.type == "function_definition":
            # Get function name
            name_node = node.child_by_field_name("name")
            if name_node:
                func_name = source_code[
                    name_node.start_byte : name_node.end_byte
                ].decode("utf-8")
                if class_name:
                    qualified_name = f"{class_name}.{func_name}"
                else:
                    qualified_name = func_name
                functions.append((qualified_name, node))

        elif node.type == "class_definition":
            # Get class name and recurse into class body
            name_node = node.child_by_field_name("name")
            body_node = node.child_by_field_name("body")
            if name_node and body_node:
                class_name_str = source_code[
                    name_node.start_byte : name_node.end_byte
                ].decode("utf-8")
                # Visit all children in the class body
                for child in body_node.children:
                    visit_node(child, class_name_str)
        else:
            # Recurse into children
            for child in node.children:
                visit_node(child, class_name)

    visit_node(tree.root_node)
    return functions


def _extract_class_hierarchy(file_path: Path) -> dict[str, list[str]]:
    """Extract class inheritance relationships from a Python file.

    Args:
        file_path: Path to Python file.

    Returns:
        Dict mapping class names to lists of parent class names.
        E.g., {'Child': ['Base'], 'Multi': ['A', 'B']}
    """
    parser = get_python_parser()

    try:
        source_code = file_path.read_bytes()
        tree = parser.parse(source_code)
    except Exception as e:  # noqa: BLE001
        logger.debug(
            "Failed to parse file for class hierarchy extraction",
            file=str(file_path),
            error=str(e),
        )
        return {}

    hierarchy: dict[str, list[str]] = {}

    def visit_node(node: Node):
        """Recursively find class definitions."""
        if node.type == "class_definition":
            name_node = node.child_by_field_name("name")
            if name_node:
                class_name = source_code[
                    name_node.start_byte : name_node.end_byte
                ].decode("utf-8")
                parents: list[str] = []

                # Find argument_list which contains parent classes
                for child in node.children:
                    if child.type == "argument_list":
                        # Extract parent class names from argument list
                        for arg in child.children:
                            if arg.type == "identifier":
                                parent_name = source_code[
                                    arg.start_byte : arg.end_byte
                                ].decode("utf-8")
                                parents.append(parent_name)

                hierarchy[class_name] = parents

        # Recurse into children
        for child in node.children:
            visit_node(child)

    visit_node(tree.root_node)
    return hierarchy


def _extract_imports(
    file_path: Path,
    file_rel_path: Path | None = None,
) -> dict[str, str]:
    """Extract import mappings from a Python file.

    Args:
        file_path: Absolute path to Python file.
        file_rel_path: Relative path from snapshot root (for resolving relative
            imports). If None, relative imports cannot be resolved.

    Returns:
        Dict mapping imported names to module names.
        For 'from module import func', maps 'func' -> 'module'
        For 'import module', maps 'module' -> 'module'
        For 'import module as alias', maps 'alias' -> 'module'
        For relative imports, resolves to the target module path stem.
    """
    parser = get_python_parser()

    try:
        source_code = file_path.read_bytes()
        tree = parser.parse(source_code)
    except Exception as e:  # noqa: BLE001
        logger.debug(
            "Failed to parse file for import extraction",
            file=str(file_path),
            error=str(e),
        )
        return {}

    imports = {}

    def _resolve_relative_import(
        level: int, module_name: str | None
    ) -> str | None:
        """Resolve a relative import to a module path stem.

        Args:
            level: Number of dots (1 for '.', 2 for '..', etc.)
            module_name: Optional module name after dots (e.g., 'utils' in '.utils')

        Returns:
            Resolved module path stem, or None if cannot resolve.
        """
        if file_rel_path is None:
            return None

        # Start from the file's parent directory
        current = file_rel_path.parent

        # Go up directories for each level beyond 1
        for _ in range(level - 1):
            current = current.parent
            if current == Path():
                # Can't go above root
                return None

        if module_name:
            # Construct path like 'mypackage/utils' -> stem 'utils'
            # But we need to match against full relative path
            parts = module_name.split(".")
            resolved = current / "/".join(parts)
            # Return the path without .py extension for matching
            return resolved.as_posix()
        # 'from . import x' - x is a sibling module
        # Return the current directory path for prefix matching
        return current.as_posix()

    def visit_node(node: Node):
        """Recursively visit nodes to extract imports."""
        if node.type == "import_statement":
            # Handle: import module [as alias]
            for child in node.children:
                if child.type == "dotted_name":
                    module_name = source_code[
                        child.start_byte : child.end_byte
                    ].decode("utf-8")
                    imports[module_name] = module_name
                elif child.type == "aliased_import":
                    # import module as alias
                    name_node = child.child_by_field_name("name")
                    alias_node = child.child_by_field_name("alias")
                    if name_node and alias_node:
                        module_name = source_code[
                            name_node.start_byte : name_node.end_byte
                        ].decode("utf-8")
                        alias = source_code[
                            alias_node.start_byte : alias_node.end_byte
                        ].decode("utf-8")
                        imports[alias] = module_name

        elif node.type == "import_from_statement":
            # Handle: from module import name [as alias]
            module_node = node.child_by_field_name("module_name")
            if module_node:
                raw_module = source_code[
                    module_node.start_byte : module_node.end_byte
                ].decode("utf-8")

                # Check if this is a relative import
                is_relative = module_node.type == "relative_import"
                if is_relative:
                    # Count dots for level
                    level = 0
                    inner_module = None
                    for child in module_node.children:
                        if child.type == "import_prefix":
                            level = child.end_byte - child.start_byte
                        elif child.type == "dotted_name":
                            inner_module = source_code[
                                child.start_byte : child.end_byte
                            ].decode("utf-8")

                    resolved_base = _resolve_relative_import(
                        level, inner_module
                    )
                    if resolved_base is None:
                        # Can't resolve, skip this import
                        return

                    # For 'from . import utils', the imported module is 'utils'
                    # and it maps to 'mypackage/utils' (sibling)
                    if inner_module is None:
                        # 'from . import x' pattern
                        # The dotted_name children are the imported modules
                        for child in node.children:
                            if child.type == "dotted_name":
                                imported_name = source_code[
                                    child.start_byte : child.end_byte
                                ].decode("utf-8")
                                # Map 'utils' -> 'mypackage/utils'
                                imports[imported_name] = (
                                    f"{resolved_base}/{imported_name}"
                                )
                            elif child.type == "aliased_import":
                                name_node = child.child_by_field_name("name")
                                alias_node = child.child_by_field_name("alias")
                                if name_node and alias_node:
                                    imported_name = source_code[
                                        name_node.start_byte : name_node.end_byte
                                    ].decode("utf-8")
                                    alias = source_code[
                                        alias_node.start_byte : alias_node.end_byte
                                    ].decode("utf-8")
                                    imports[alias] = (
                                        f"{resolved_base}/{imported_name}"
                                    )
                    else:
                        # 'from .utils import x' pattern
                        module_name = resolved_base
                        for child in node.children:
                            if (
                                child.type == "dotted_name"
                                and child != module_node
                            ):
                                func_name = source_code[
                                    child.start_byte : child.end_byte
                                ].decode("utf-8")
                                imports[func_name] = module_name
                            elif child.type == "aliased_import":
                                name_node = child.child_by_field_name("name")
                                alias_node = child.child_by_field_name("alias")
                                if name_node and alias_node:
                                    func_name = source_code[
                                        name_node.start_byte : name_node.end_byte
                                    ].decode("utf-8")
                                    alias = source_code[
                                        alias_node.start_byte : alias_node.end_byte
                                    ].decode("utf-8")
                                    imports[alias] = module_name
                else:
                    # Absolute import
                    module_name = raw_module
                    for child in node.children:
                        if child.type == "dotted_name" and child != module_node:
                            func_name = source_code[
                                child.start_byte : child.end_byte
                            ].decode("utf-8")
                            imports[func_name] = module_name
                        elif child.type == "aliased_import":
                            name_node = child.child_by_field_name("name")
                            alias_node = child.child_by_field_name("alias")
                            if name_node and alias_node:
                                func_name = source_code[
                                    name_node.start_byte : name_node.end_byte
                                ].decode("utf-8")
                                alias = source_code[
                                    alias_node.start_byte : alias_node.end_byte
                                ].decode("utf-8")
                                imports[alias] = module_name

        # Recurse into children
        for child in node.children:
            visit_node(child)

    visit_node(tree.root_node)
    return imports


def _extract_function_calls(
    func_node: Node, source_code: bytes
) -> list[tuple[str, str | None]]:
    """Extract all function/method calls from a function body.

    Args:
        func_node: Tree-sitter node for function definition.
        source_code: Source code bytes.

    Returns:
        List of (called_name, qualifier) tuples.
        - For simple calls 'func()', returns ('func', None)
        - For qualified calls 'module.func()', returns ('func', 'module')
        - For method calls 'obj.method()', returns ('method', 'obj')
    """
    calls = []

    def visit_node(node: Node):
        """Recursively find call nodes."""
        if node.type == "call":
            # Get the function being called
            func_node = node.child_by_field_name("function")
            if func_node:
                # Handle simple calls: func()
                if func_node.type == "identifier":
                    name = source_code[
                        func_node.start_byte : func_node.end_byte
                    ].decode("utf-8")
                    calls.append((name, None))
                # Handle qualified calls: module.func() or obj.method()
                elif func_node.type == "attribute":
                    # Get the object/module part
                    object_node = func_node.child_by_field_name("object")
                    attr_node = func_node.child_by_field_name("attribute")
                    if object_node and attr_node:
                        # Extract qualifier (could be nested like a.b.c)
                        qualifier = source_code[
                            object_node.start_byte : object_node.end_byte
                        ].decode("utf-8")
                        method_name = source_code[
                            attr_node.start_byte : attr_node.end_byte
                        ].decode("utf-8")
                        calls.append((method_name, qualifier))

        # Recurse into children
        for child in node.children:
            visit_node(child)

    # Get function body
    body_node = func_node.child_by_field_name("body")
    if body_node:
        visit_node(body_node)

    return calls


def _extract_local_types(
    func_node: Node,
    source_code: bytes,
) -> dict[str, str]:
    """Extract local variable type hints from constructor calls.

    Analyzes assignments like 'c = Client()' to infer that 'c' has type 'Client'.

    Args:
        func_node: Tree-sitter node for function definition.
        source_code: Source code bytes.

    Returns:
        Dict mapping variable names to class names.
    """
    local_types: dict[str, str] = {}

    def visit_node(node: Node):
        """Recursively find assignment nodes."""
        if node.type == "assignment":
            # Look for pattern: identifier = call(identifier)
            # e.g., c = Client()
            children = list(node.children)

            # Find the target (left side) and value (right side)
            target = None
            value = None
            for i, child in enumerate(children):
                if child.type == "identifier" and target is None:
                    target = child
                elif child.type == "=" and target is not None:
                    # Everything after = is the value
                    for j in range(i + 1, len(children)):
                        if children[j].type == "call":
                            value = children[j]
                            break

            if target and value:
                var_name = source_code[
                    target.start_byte : target.end_byte
                ].decode("utf-8")

                # Check if the call is to a simple identifier (class name)
                func_node_inner = value.child_by_field_name("function")
                if func_node_inner and func_node_inner.type == "identifier":
                    class_name = source_code[
                        func_node_inner.start_byte : func_node_inner.end_byte
                    ].decode("utf-8")
                    # Only track if it looks like a class (starts with uppercase)
                    if class_name and class_name[0].isupper():
                        local_types[var_name] = class_name

        # Recurse into children
        for child in node.children:
            visit_node(child)

    # Get function body
    body_node = func_node.child_by_field_name("body")
    if body_node:
        visit_node(body_node)

    return local_types


def _resolve_call(
    called_name: str,
    qualifier: str | None,
    caller_file: Path,
    imports: dict[str, str],
    function_index: dict[str, list[tuple[Path, str]]],
    local_types: dict[str, str] | None = None,
    class_hierarchy: dict[str, list[str]] | None = None,
    caller_qual_name: str | None = None,
) -> str | None:
    """Resolve a function call to a specific node ID.

    Resolution priority:
    1. If qualified (e.g., 'module.func'), resolve via imports or local types
    2. If unqualified, check same-file functions first
    3. Then check imported modules
    4. Finally, fallback to unique name matching

    Args:
        called_name: Name of the called function.
        qualifier: Module/object qualifier (e.g., 'utils' in 'utils.helper()').
        caller_file: Path of the file making the call.
        imports: Import map for the caller file.
        function_index: Index mapping function names to (file, qual_name) tuples.
        local_types: Optional mapping of local variable names to class names.
        class_hierarchy: Optional mapping of class names to parent class names.
        caller_qual_name: Optional qualified name of the caller function
            (e.g., 'Child.process' for methods).

    Returns:
        Node ID if resolved, None otherwise.
    """
    candidates = function_index.get(called_name, [])

    if not candidates:
        return None

    if local_types is None:
        local_types = {}

    if class_hierarchy is None:
        class_hierarchy = {}

    # Case 1: Qualified call (e.g., module.func() or obj.method())
    if qualifier:
        # Special case: 'self' - method call within the same file
        if qualifier == "self":
            # Look for method in same file
            for file_path, qual_name in candidates:
                if file_path == caller_file:
                    return f"{file_path.as_posix()}::{qual_name}"

        # Special case: 'super()' - call to parent class method
        if qualifier == "super()":
            # Need to know which class we're in to find parent
            if caller_qual_name and "." in caller_qual_name:
                current_class = caller_qual_name.split(".")[0]
                parent_classes = class_hierarchy.get(current_class, [])
                if parent_classes:
                    # Look for method in first parent class (MRO)
                    parent_class = parent_classes[0]
                    for file_path, qual_name in candidates:
                        if qual_name == f"{parent_class}.{called_name}":
                            return f"{file_path.as_posix()}::{qual_name}"

        # Check if qualifier is an imported module
        if qualifier in imports:
            module_name = imports[qualifier]
            # Find functions in that module
            for file_path, qual_name in candidates:
                # Match by module name - can be stem (absolute imports) or
                # path without extension (relative imports like 'mypackage/utils')
                file_path_no_ext = file_path.with_suffix("").as_posix()
                if (
                    file_path.stem == module_name
                    or file_path_no_ext == module_name
                ):
                    return f"{file_path.as_posix()}::{qual_name}"

        # Check if qualifier is a local variable with known type
        if qualifier in local_types:
            class_name = local_types[qualifier]
            # Look for method in class (qual_name should be ClassName.method_name)
            for file_path, qual_name in candidates:
                if qual_name == f"{class_name}.{called_name}":
                    return f"{file_path.as_posix()}::{qual_name}"

        # Unknown qualifier (could be variable, etc.)
        return None

    # Case 2: Unqualified call - check same file first (highest priority)
    for file_path, qual_name in candidates:
        if file_path == caller_file:
            return f"{file_path.as_posix()}::{qual_name}"

    # Case 3: Check if the function name was imported
    if called_name in imports:
        module_name = imports[called_name]
        # Find functions in that module
        for file_path, qual_name in candidates:
            file_path_no_ext = file_path.with_suffix("").as_posix()
            matches_module = (
                file_path.stem == module_name or file_path_no_ext == module_name
            )
            if matches_module and (
                qual_name.endswith(f".{called_name}")
                or qual_name == called_name
            ):
                return f"{file_path.as_posix()}::{qual_name}"

    # Case 4: Fallback to unique name matching (if only one candidate exists)
    if len(candidates) == 1:
        file_path, qual_name = candidates[0]
        return f"{file_path.as_posix()}::{qual_name}"

    # Multiple candidates and no clear resolution - don't create edge
    return None


def build_dependency_graph(
    snapshot_dir: Path,
    entrypoint: Path,
) -> nx.DiGraph:
    """Build a directed call graph from function/method call relationships.

    Constructs a graph where:
    - Nodes: Functions and methods (qualified names)
    - Edges: Call relationships (caller -> callee)
    - Edge weights: Number of calls from caller to callee

    Args:
        snapshot_dir: Root directory of the code snapshot.
        entrypoint: Path to the entrypoint file (absolute or relative to
            snapshot_dir).

    Returns:
        NetworkX directed graph with weighted edges representing call dependencies.
    """
    # Normalize paths
    snapshot_dir = snapshot_dir.resolve()

    if entrypoint.is_absolute():
        entrypoint_abs = entrypoint
    else:
        entrypoint_abs = (snapshot_dir / entrypoint).resolve()

    if not entrypoint_abs.exists():
        logger.warning(
            "Entrypoint does not exist for graph construction",
            entrypoint=str(entrypoint),
        )
        return nx.DiGraph()

    # Trace all source files reachable from entrypoint
    try:
        source_files = trace_source_files(entrypoint_abs, snapshot_dir)
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "Failed to trace source files for graph construction",
            entrypoint=str(entrypoint),
            error=str(e),
        )
        return nx.DiGraph()

    # Build graph
    graph = nx.DiGraph()

    # First pass: Extract all functions from all files and add as nodes
    file_to_functions: dict[Path, list[tuple[str, Node]]] = {}
    file_to_imports: dict[Path, dict[str, str]] = {}
    file_to_class_hierarchy: dict[Path, dict[str, list[str]]] = {}
    # Build index: function_name -> list of (file_path, qualified_name)
    function_index: dict[str, list[tuple[Path, str]]] = {}

    for file_path in source_files:
        file_abs = snapshot_dir / file_path
        functions = _extract_functions_from_file(file_abs)
        file_to_functions[file_path] = functions

        # Extract imports for this file (pass relative path for resolving relative imports)
        file_to_imports[file_path] = _extract_imports(file_abs, file_path)

        # Extract class hierarchy for super() resolution
        file_to_class_hierarchy[file_path] = _extract_class_hierarchy(file_abs)

        # Add qualified function names with file prefix for uniqueness
        for qual_name, _ in functions:
            node_id = f"{file_path.as_posix()}::{qual_name}"
            graph.add_node(node_id)

            # Index by simple function name (last component)
            simple_name = qual_name.split(".")[-1]
            if simple_name not in function_index:
                function_index[simple_name] = []
            function_index[simple_name].append((file_path, qual_name))

    # Second pass: Extract calls and add edges
    from collections import Counter

    for file_path, functions in file_to_functions.items():
        for qual_name, func_node in functions:
            caller_id = f"{file_path.as_posix()}::{qual_name}"

            # Extract all calls from this function
            source_code = (snapshot_dir / file_path).read_bytes()
            calls = _extract_function_calls(func_node, source_code)

            # Extract local variable type hints for this function
            local_types = _extract_local_types(func_node, source_code)

            # Count calls to each target (need to track both name and qualifier)
            call_counts: Counter[tuple[str, str | None]] = Counter(calls)

            # Add edges for calls to known functions
            for (called_name, qualifier), count in call_counts.items():
                # Resolve the call to a specific function
                callee_id = _resolve_call(
                    called_name,
                    qualifier,
                    file_path,
                    file_to_imports.get(file_path, {}),
                    function_index,
                    local_types,
                    file_to_class_hierarchy.get(file_path, {}),
                    qual_name,
                )

                if callee_id:
                    graph.add_edge(caller_id, callee_id, weight=count)

    logger.debug(
        "Built call graph",
        nodes=graph.number_of_nodes(),
        edges=graph.number_of_edges(),
    )

    return graph


def _compute_cyclic_dependency_mass(graph: nx.DiGraph) -> float:
    """Compute cyclic dependency mass (CY).

    CY is the ratio of edge weight in strongly connected components (SCCs)
    of size >= 2 to total edge weight. Captures structural rot from cycles.

    Args:
        graph: NetworkX directed graph with weighted edges.

    Returns:
        Cyclic dependency mass in range [0, 1].
    """
    if graph.number_of_edges() == 0:
        return 0.0

    # Compute total edge weight
    total_weight = sum(
        graph.get_edge_data(u, v).get("weight", 1) for u, v in graph.edges()
    )

    if total_weight == 0:
        return 0.0

    # Find all SCCs of size >= 2
    sccs = [
        scc for scc in nx.strongly_connected_components(graph) if len(scc) >= 2
    ]

    # Sum weights of edges where both endpoints are in the same SCC
    scc_weight = 0
    for scc in sccs:
        scc_nodes = set(scc)
        for u, v in graph.edges():
            if u in scc_nodes and v in scc_nodes:
                scc_weight += graph.get_edge_data(u, v).get("weight", 1)

    return scc_weight / total_weight


def _compute_propagation_cost(graph: nx.DiGraph) -> float:
    """Compute propagation cost (PC).

    PC measures average reachability: if I change one unit, how much of the
    system is reachable downstream (directly or transitively)?

    PC = (sum of reachable pairs) / (total possible pairs)

    Args:
        graph: NetworkX directed graph.

    Returns:
        Propagation cost in range [0, 1]. 0 = modular, 1 = everything touches everything.
    """
    node_count = graph.number_of_nodes()

    if node_count <= 1:
        return 0.0

    # Compute reachable pairs using transitive closure
    reachable_count = 0
    for u in graph.nodes():
        # Find all nodes reachable from u (excluding u itself)
        reachable = set(nx.descendants(graph, u))
        reachable_count += len(reachable)

    # Total possible pairs (excluding u=v)
    total_pairs = node_count * (node_count - 1)

    return reachable_count / total_pairs


def _compute_dependency_entropy(graph: nx.DiGraph) -> float:
    """Compute dependency entropy (ENT).

    ENT measures how scattered dependencies are. For each node, computes
    normalized Shannon entropy of its outgoing dependency distribution.
    High entropy = dependencies spread across many targets (erosion).

    Args:
        graph: NetworkX directed graph with weighted edges.

    Returns:
        Average normalized entropy across all nodes in range [0, 1].
    """
    import math

    node_count = graph.number_of_nodes()

    if node_count == 0:
        return 0.0

    normalized_entropies = []

    for u in graph.nodes():
        out_edges = list(graph.out_edges(u, data=True))

        # Skip nodes with out-degree <= 1 (H_n = 0 by definition)
        if len(out_edges) <= 1:
            normalized_entropies.append(0.0)
            continue

        # Compute probability distribution over outgoing edges
        total_weight = sum(
            edge_data.get("weight", 1) for _, _, edge_data in out_edges
        )

        if total_weight == 0:
            normalized_entropies.append(0.0)
            continue

        probabilities = [
            edge_data.get("weight", 1) / total_weight
            for _, _, edge_data in out_edges
        ]

        # Compute Shannon entropy: H(u) = -sum(p * log(p))
        entropy = -sum(p * math.log(p) for p in probabilities if p > 0)

        # Normalize by max entropy for this outdegree
        k = len(out_edges)
        max_entropy = math.log(k)
        normalized_entropy = entropy / max_entropy if max_entropy > 0 else 0.0

        normalized_entropies.append(normalized_entropy)

    # Return average normalized entropy
    return sum(normalized_entropies) / node_count


def compute_graph_metrics(graph: nx.DiGraph) -> GraphMetrics:
    """Compute comprehensive metrics from a dependency graph.

    Args:
        graph: NetworkX directed graph representing code dependencies.

    Returns:
        GraphMetrics with computed values.
    """
    node_count = graph.number_of_nodes()
    edge_count = graph.number_of_edges()

    if node_count == 0:
        return GraphMetrics(
            node_count=0,
            edge_count=0,
            cyclic_dependency_mass=0.0,
            propagation_cost=0.0,
            dependency_entropy=0.0,
        )

    # Calculate advanced structural metrics
    cyclic_dependency_mass = _compute_cyclic_dependency_mass(graph)
    propagation_cost = _compute_propagation_cost(graph)
    dependency_entropy = _compute_dependency_entropy(graph)

    return GraphMetrics(
        node_count=node_count,
        edge_count=edge_count,
        cyclic_dependency_mass=cyclic_dependency_mass,
        propagation_cost=propagation_cost,
        dependency_entropy=dependency_entropy,
    )
