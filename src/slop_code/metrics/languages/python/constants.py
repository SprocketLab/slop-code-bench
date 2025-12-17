"""Constants for Python code quality metrics."""

from __future__ import annotations

EXTENSIONS = {".py"}

# Slop scale: 1 = cosmetic, 3 = noisy/low-quality, 5 = extremely sloppy
RUFF_CODES: dict[str, int] = {
    "AIR": 3,
    "ERA": 4,  # commented-out or dead code is loud slop
    "FAST": 2,
    "ANN401": 2,
    "ASYNC": 3,
    "S": 3,
    "BLE": 4,
    "FBT": 2,
    "B": 4,
    "A001": 3,
    "A002": 3,
    "A003": 3,
    "A004": 3,
    "A005": 3,
    "A006": 3,
    "COM819": 1,
    "C4": 2,
    "DTZ": 3,
    "T10": 4,  # debugger/breakpoint left behind
    "DJ": 2,
    "EXE": 1,
    "FIX": 2,
    "FA": 1,
    "INT": 2,
    "ISC": 2,
    "ICN": 1,
    "LOG": 2,
    "INP": 2,
    "PIE": 2,
    "PYI": 2,
    "PT": 2,
    "Q001": 1,
    "Q002": 1,
    "Q003": 1,
    "Q004": 1,
    "RSE": 3,
    "RET": 2,
    "SLF": 2,
    "SIM": 2,
    "SLOT": 1,
    "TID251": 2,
    "TID253": 2,
    "TD": 1,
    "TC": 2,
    "ARG": 2,
    "PTH": 2,
    "FLY": 1,
    "C90": 4,
    "NPY": 2,
    "PD": 2,
    "N": 3,
    "PERF": 3,
    "E711": 3,
    "E712": 3,
    "E713": 3,
    "E714": 3,
    "E721": 3,
    "E722": 4,
    "E741": 2,
    "E742": 2,
    "E743": 2,
    "DOC": 1,
    "F": 4,
    "PLC": 2,
    "PLE": 4,
    "PLR": 2,
    "PLW": 3,
    "UP": 2,
    "FURB": 2,
    "RUF": 2,
    "TRY": 3,
    "F841": 2,
    "PGH": 4,  # blanket ignore/noqa is very sloppy
    "G": 2,
    "YTT": 1,
    "EM": 2,
}

RUFF_SELECT_FLAGS = [flag for code in RUFF_CODES for flag in ("--select", code)]

# Tree-sitter node types that contribute to cyclomatic complexity
COMPLEXITY_NODE_TYPES = frozenset(
    {
        "if_statement",
        "elif_clause",
        "for_statement",
        "while_statement",
        "except_clause",
        "assert_statement",
        "list_comprehension",
        "set_comprehension",
        "dictionary_comprehension",
        "generator_expression",
        "boolean_operator",
        "conditional_expression",  # ternary operator
        "if_clause",  # `if` inside comprehensions
    }
)

# Tree-sitter node types that are statements
STATEMENT_NODE_TYPES = frozenset(
    {
        "expression_statement",
        "return_statement",
        "pass_statement",
        "break_statement",
        "continue_statement",
        "raise_statement",
        "import_statement",
        "import_from_statement",
        "global_statement",
        "nonlocal_statement",
        "delete_statement",
        "if_statement",
        "for_statement",
        "while_statement",
        "try_statement",
        "with_statement",
        "assert_statement",
        "match_statement",
    }
)

CONTROL_BLOCK_TYPES = frozenset(
    {
        "if_statement",
        "for_statement",
        "while_statement",
        "with_statement",
        "try_statement",
        "match_statement",
    }
)

CONTROL_FLOW_NODE_TYPES = frozenset(
    {
        "if_statement",
        "elif_clause",
        "match_statement",
        "case_clause",
    }
)

EXCEPTION_SCAFFOLD_NODE_TYPES = frozenset(
    {
        "try_statement",
        "except_clause",
        "finally_clause",
    }
)

EXPRESSION_NODE_TYPES = frozenset(
    {
        "call",
        "binary_operator",
        "unary_operator",
        "comparison_operator",
        "boolean_operator",
        "subscript",
        "attribute",
        "conditional_expression",
        "lambda",
        "list_comprehension",
        "dict_comprehension",
        "set_comprehension",
        "generator_expression",
    }
)

CLONE_NODE_TYPES = frozenset(
    {
        "function_definition",
        "if_statement",
        "for_statement",
        "while_statement",
        "with_statement",
        "try_statement",
        "match_statement",
    }
)
