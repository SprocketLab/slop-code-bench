"""Import extraction and source file tracing."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from slop_code.logging import get_logger
from slop_code.metrics.languages.python.parser import get_python_parser
from slop_code.metrics.languages.python.utils import read_python_code
from slop_code.metrics.models import ImportInfo

if TYPE_CHECKING:
    from tree_sitter import Node

logger = get_logger(__name__)


def _parse_import_statement(node: Node) -> ImportInfo | None:
    """Parse 'import X' or 'import X.Y' or 'import X as Y' statements.

    Args:
        node: The import_statement tree-sitter node.

    Returns:
        ImportInfo or None if parsing fails.
    """
    for child in node.children:
        if child.type == "dotted_name":
            return ImportInfo(
                module_path=child.text.decode("utf-8"),
                is_relative=False,
                relative_level=0,
                imported_names=[],
                line=node.start_point[0] + 1,
            )
        if child.type == "aliased_import":
            for subchild in child.children:
                if subchild.type == "dotted_name":
                    return ImportInfo(
                        module_path=subchild.text.decode("utf-8"),
                        is_relative=False,
                        relative_level=0,
                        imported_names=[],
                        line=node.start_point[0] + 1,
                    )
    return None


def _parse_relative_import(node: Node) -> tuple[int, str | None]:
    """Parse a relative_import node.

    Args:
        node: The relative_import tree-sitter node.

    Returns:
        Tuple of (level, module_path) where level is the number of dots.
    """
    level = 0
    module_path = None

    for child in node.children:
        if child.type == "import_prefix":
            # Count the dots in the prefix
            level = len([c for c in child.children if c.type == "."])
        elif child.type == "dotted_name":
            module_path = child.text.decode("utf-8")

    return level, module_path


def _parse_import_from_statement(node: Node) -> ImportInfo | None:
    """Parse 'from X import Y' style statements including relative imports.

    Args:
        node: The import_from_statement tree-sitter node.

    Returns:
        ImportInfo or None if parsing fails.
    """
    module_path: str | None = None
    relative_level = 0
    imported_names: list[str] = []
    is_relative = False
    found_import_keyword = False

    for child in node.children:
        if child.type == "from":
            continue
        if child.type == "import":
            found_import_keyword = True
        elif child.type == "relative_import":
            is_relative = True
            relative_level, module_path = _parse_relative_import(child)
        elif child.type == "dotted_name":
            if not found_import_keyword:
                module_path = child.text.decode("utf-8")
            else:
                imported_names.append(child.text.decode("utf-8"))
        elif child.type == "aliased_import":
            for subchild in child.children:
                if subchild.type == "dotted_name":
                    imported_names.append(subchild.text.decode("utf-8"))
                    break
        elif child.type == "wildcard_import":
            imported_names.append("*")

    return ImportInfo(
        module_path=module_path,
        is_relative=is_relative,
        relative_level=relative_level,
        imported_names=imported_names,
        line=node.start_point[0] + 1,
    )


def _extract_imports_from_node(node: Node, imports: list[ImportInfo]) -> None:
    """Recursively walk AST and extract import information.

    Args:
        node: The tree-sitter node to process.
        imports: List to append extracted imports to.
    """
    for child in node.children:
        if child.type == "import_statement":
            result = _parse_import_statement(child)
            if result:
                imports.append(result)
        elif child.type == "import_from_statement":
            result = _parse_import_from_statement(child)
            if result:
                imports.append(result)
        else:
            _extract_imports_from_node(child, imports)


def extract_imports(source: Path) -> list[ImportInfo]:
    """Extract all import statements from a Python source file using tree-sitter.

    Handles:
    - import X
    - import X.Y
    - import X as Y
    - from X import Y
    - from X import Y, Z
    - from . import X
    - from .X import Y
    - from ..X import Y

    Args:
        source: Path to the Python source file.

    Returns:
        List of ImportInfo for all imports found in the file.
    """
    code = read_python_code(source)
    if not code.strip():
        return []

    parser = get_python_parser()
    tree = parser.parse(code.encode("utf-8"))

    imports: list[ImportInfo] = []
    _extract_imports_from_node(tree.root_node, imports)

    return imports


# =============================================================================
# Import Tracing
# =============================================================================


def _try_resolve_module(
    base_dir: Path,
    module_path: str,
    snapshot_dir: Path,
) -> Path | None:
    """Try to resolve a dotted module path to a file.

    Args:
        base_dir: Directory to start resolution from.
        module_path: Dotted module path (e.g., "scheduler.parser").
        snapshot_dir: Root directory of the snapshot.

    Returns:
        Resolved file path, or None if not found.
    """
    parts = module_path.split(".")
    target_dir = base_dir

    for part in parts[:-1]:
        target_dir = target_dir / part
        if not target_dir.exists():
            return None

    last_part = parts[-1]

    # Try as file
    file_path = target_dir / f"{last_part}.py"
    if file_path.exists() and file_path.is_relative_to(snapshot_dir):
        return file_path

    # Try as package
    package_path = target_dir / last_part / "__init__.py"
    if package_path.exists() and package_path.is_relative_to(snapshot_dir):
        return package_path

    return None


def _resolve_relative_import(
    import_info: ImportInfo,
    importing_file: Path,
    snapshot_dir: Path,
) -> list[Path]:
    """Resolve a relative import (e.g., from .utils import X).

    Args:
        import_info: The import information.
        importing_file: Path to the file containing the import.
        snapshot_dir: Root directory of the snapshot.

    Returns:
        List of resolved file paths.
    """
    results: list[Path] = []
    base_dir = importing_file.parent

    # Go up directories based on relative level (level 1 = current package)
    for _ in range(import_info.relative_level - 1):
        base_dir = base_dir.parent

    if import_info.module_path:
        # "from .module import X" - resolve the module
        resolved = _try_resolve_module(
            base_dir, import_info.module_path, snapshot_dir
        )
        if resolved:
            results.append(resolved)

    # Also check if imported names are submodules
    for name in import_info.imported_names:
        if name == "*":
            continue
        target_dir = base_dir
        if import_info.module_path:
            for part in import_info.module_path.split("."):
                target_dir = target_dir / part

        resolved = _try_resolve_module(target_dir, name, snapshot_dir)
        if resolved:
            results.append(resolved)

    return results


def _resolve_absolute_import(
    import_info: ImportInfo,
    snapshot_dir: Path,
) -> list[Path]:
    """Resolve an absolute import (e.g., import scheduler.parser).

    Args:
        import_info: The import information.
        snapshot_dir: Root directory of the snapshot.

    Returns:
        List of resolved file paths.
    """
    results: list[Path] = []

    if import_info.module_path:
        resolved = _try_resolve_module(
            snapshot_dir, import_info.module_path, snapshot_dir
        )
        if resolved:
            results.append(resolved)

    # Check if imported names are submodules
    if import_info.module_path and import_info.imported_names:
        module_dir = snapshot_dir
        for part in import_info.module_path.split("."):
            module_dir = module_dir / part

        for name in import_info.imported_names:
            if name == "*":
                continue
            resolved = _try_resolve_module(module_dir, name, snapshot_dir)
            if resolved:
                results.append(resolved)

    return results


def _resolve_import(
    import_info: ImportInfo,
    importing_file: Path,
    snapshot_dir: Path,
) -> list[Path]:
    """Resolve an import to file path(s) within the snapshot.

    Args:
        import_info: The import information.
        importing_file: Path to the file containing the import.
        snapshot_dir: Root directory of the snapshot.

    Returns:
        List of resolved file paths.
    """
    if import_info.is_relative:
        return _resolve_relative_import(
            import_info, importing_file, snapshot_dir
        )
    return _resolve_absolute_import(import_info, snapshot_dir)


def trace_source_files(
    entrypoint: Path,
    snapshot_dir: Path,
) -> set[Path]:
    """Trace all source files reachable from an entrypoint via imports.

    Starting from the entrypoint file, recursively follows imports to build
    a complete set of source files that are part of the import graph.

    Non-local imports (stdlib, third-party packages) are silently skipped.
    Missing files are logged as debug messages but don't stop tracing.
    Circular imports are handled by tracking visited files.

    Args:
        entrypoint: Path to the entrypoint Python file.
        snapshot_dir: Root directory of the snapshot.

    Returns:
        Set of Path objects (relative to snapshot_dir) for all traced files.
    """
    # Normalize entrypoint path
    if entrypoint.is_absolute():
        entrypoint_abs = entrypoint
    else:
        entrypoint_abs = (snapshot_dir / entrypoint).resolve()

    if not entrypoint_abs.exists():
        logger.warning(
            "Entrypoint file does not exist",
            entrypoint=str(entrypoint),
        )
        return set()

    visited: set[Path] = set()
    to_visit: list[Path] = [entrypoint_abs]

    while to_visit:
        current = to_visit.pop()

        if current in visited:
            continue
        visited.add(current)

        if (
            not current.exists()
            or not current.is_file()
            or current.suffix != ".py"
        ):
            continue

        try:
            imports = extract_imports(current)
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "Failed to extract imports",
                file=str(current),
                error=str(e),
            )
            continue

        for imp in imports:
            resolved = _resolve_import(imp, current, snapshot_dir)
            for path in resolved:
                if path not in visited:
                    to_visit.append(path)

    return {
        p.relative_to(snapshot_dir)
        for p in visited
        if p.is_relative_to(snapshot_dir)
    }
