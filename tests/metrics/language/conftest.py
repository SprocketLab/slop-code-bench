"""Shared fixtures for Python language metrics tests."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from slop_code.metrics.languages.python.parser import get_python_parser


@pytest.fixture
def parser():
    """Get the Python tree-sitter parser."""
    return get_python_parser()


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


def write_file(tmp_path: Path, name: str, content: str) -> Path:
    """Write content to a file and return its path."""
    path = tmp_path / name
    path.write_text(dedent(content))
    return path
