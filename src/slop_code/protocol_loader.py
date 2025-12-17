from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any

from slop_code.logging import get_logger

logger = get_logger(__name__)


class ProtocolLoadError(Exception):
    """Raised when a protocol implementation cannot be loaded or validated."""


def load_protocol_entrypoint(
    protocol: type[Any],
    module_path: Path,
    entrypoint_name: str,
) -> type[Any]:
    """Dynamically import a module and load an entrypoint that matches a
    protocol.

    Args:
        protocol: The protocol class that the entrypoint must implement
        module_path: Path to the Python module file
        entrypoint_name: Name of the entrypoint (class/function) to load from
                         the module

    Returns:
        Class/function that matches the specified protocol

    Raises:
        ProtocolLoadError: If the module cannot be imported, entrypoint doesn't
                          exist, or the entrypoint doesn't match the protocol

    Example:
        >>> from my_protocols import MyProtocol
        >>> impl = load_protocol_entrypoint(
        ...     MyProtocol, Path("my_module.py"), "MyClass"
        ... )
        >>> instance = impl()
    """
    if not module_path.exists():
        raise ProtocolLoadError(f"Module file {module_path} does not exist")

    logger.debug(
        "Loading protocol implementation",
        module_path=str(module_path.absolute()),
        entrypoint=entrypoint_name,
        protocol=protocol.__name__,
    )

    # Convert file path to module import path
    if module_path.suffix != ".py":
        raise ProtocolLoadError(
            f"Module file {module_path} is not a Python file"
        )

    module_name = module_path.stem
    parent_dir = module_path.parent.absolute()
    import_path = f"{parent_dir.name}.{module_name}"

    added = False
    try:
        parent_root = str(parent_dir.parent.absolute())
        if parent_root not in sys.path:
            sys.path.insert(0, parent_root)
            added = True

        module = importlib.import_module(import_path)
    except ImportError as e:
        raise ProtocolLoadError(
            f"Failed to import module '{import_path}' from {module_path}: {e}"
        ) from e
    finally:
        if added:
            sys.path.remove(parent_root)

    try:
        entrypoint = getattr(module, entrypoint_name)
    except AttributeError as e:
        raise ProtocolLoadError(
            f"Entrypoint '{entrypoint_name}' not found in module "
            f"'{import_path}': {e}"
        ) from e

    # Check if entrypoint matches the protocol
    if not isinstance(entrypoint, type):
        # For non-class entrypoints, check if they implement the protocol
        if not hasattr(entrypoint, "__annotations__"):
            raise ProtocolLoadError(
                f"Entrypoint '{entrypoint_name}' in module '{import_path}' "
                f"is not a class and has no type annotations"
            )

        # Basic protocol compliance check for functions
        # This is a simplified check - for full protocol validation,
        # you might need more sophisticated type checking
        if not hasattr(protocol, "__protocol__") and not hasattr(
            protocol, "_is_runtime_protocol"
        ):
            raise ProtocolLoadError(
                f"Protocol {protocol.__name__} is not a valid Protocol"
            )
    else:
        # For class entrypoints, check if they implement the protocol
        try:
            # Check if protocol is runtime checkable
            if (
                not hasattr(protocol, "_is_runtime_protocol")
                or not protocol._is_runtime_protocol
            ):
                # For non-runtime protocols, just check if required methods exist
                required_methods = getattr(
                    protocol, "__abstractmethods__", set()
                )
                for method_name in required_methods:
                    if not hasattr(entrypoint, method_name):
                        raise ProtocolLoadError(
                            f"Class '{entrypoint_name}' in module '{import_path}' "
                            f"does not implement required method '{method_name}' "
                            f"from protocol {protocol.__name__}"
                        )
            else:
                # For runtime checkable protocols, use issubclass
                if not issubclass(entrypoint, protocol):
                    raise ProtocolLoadError(
                        f"Class '{entrypoint_name}' in module '{import_path}' "
                        f"does not implement protocol {protocol.__name__}"
                    )
        except TypeError as e:
            raise ProtocolLoadError(
                f"Failed to check if '{entrypoint_name}' implements protocol "
                f"{protocol.__name__}: {e}"
            ) from e

    logger.debug(
        "Loaded protocol implementation",
        module=import_path,
        entrypoint=entrypoint_name,
        protocol=protocol.__name__,
    )

    return entrypoint  # type: ignore[return-value]


def get_source_files(
    module_path: Path,
    load_function: callable,
) -> dict[str, str]:
    """Return source code for a module and any local modules it imports.

    This ensures downstream consumers (e.g. reporting or artifact capture)
    can display the exact logic that executed for a checkpoint.

    Args:
        module_path: Filesystem path to the module file.
        load_function: Function to call to load the module (ensures it's in
                   sys.modules)

    Returns:
        Mapping of problem-relative file paths to their UTF-8 source contents.

    Raises:
        ProtocolLoadError: If the module cannot be imported.
    """
    if not module_path.exists():
        raise ProtocolLoadError(f"Module file {module_path} does not exist")

    # Ensure the module (and its dependencies) are imported so they appear in
    # sys.modules.
    try:
        load_function()
    except Exception:
        # Continue even if load function fails - we still want to return
        # whatever source files we can find
        pass

    problem_root = module_path.parent.resolve()
    sources: dict[str, str] = {}

    for module_name, module in list(sys.modules.items()):
        module_file = getattr(module, "__file__", None)
        if not module_file:
            continue

        try:
            module_file_path = Path(module_file).resolve(strict=False)
        except (OSError, ValueError):
            continue

        if module_file_path.suffix not in {".py", ".pyi"}:
            continue
        if "__pycache__" in module_file_path.parts:
            continue

        try:
            relative_path = module_file_path.relative_to(problem_root)
        except ValueError:
            # Module is outside the problem directory; skip it.
            continue

        if not module_file_path.exists():
            # Best effort: skip modules without source files (e.g. generated).
            continue

        sources[relative_path.as_posix()] = module_file_path.read_text(
            encoding="utf-8"
        )

    # Ensure the primary module file is always present.
    relative_module = module_path.resolve().relative_to(problem_root)
    if relative_module.as_posix() not in sources:
        sources[relative_module.as_posix()] = module_path.read_text(
            encoding="utf-8"
        )

    return sources
