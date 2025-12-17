#!/usr/bin/env python3
"""
Helper script to generate case.yaml, expected.jsonl, and expected_db_content.yaml files
for all checkpoint_2 hidden tests.
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml


def write_yaml(file_path, data):
    """Write YAML file."""
    with open(file_path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def write_jsonl(file_path, lines):
    """Write JSONL file."""
    with open(file_path, "w") as f:
        for line in lines:
            f.write(json.dumps(line) + "\n")


def create_test_files(test_name, migration_json, expected_events, expected_db_content):
    """Create all test files for a test case.

    Args:
        test_name: Name of the test directory
        migration_json: Migration JSON content (as dict)
        expected_events: List of expected JSONL events (as dicts)
        expected_db_content: Expected database content (as dict) or None
    """
    test_dir = Path(__file__).parent / test_name

    # Create case.yaml
    case_yaml = {
        "arguments": "migrate migration.json app.db",
        "input_files": [
            {"path": "app.db", "file_type": "sqlite"},
            {
                "content": json.dumps(migration_json, indent=2),
                "file_type": "json",
                "path": "migration.json",
            },
        ],
        "tracked_files": ["app.db"],
        "expected_status": 0,
    }
    write_yaml(test_dir / "case.yaml", case_yaml)

    # Create expected.jsonl
    write_jsonl(test_dir / "expected.jsonl", expected_events)

    # Create expected_db_content.yaml if provided
    if expected_db_content:
        write_yaml(test_dir / "expected_db_content.yaml", expected_db_content)

    print(f"✓ Created files for {test_name}")


def main():
    """Generate all test configuration files."""
    print("Generating test configuration files...\n")

    # Test 1: null_source_column_migration
    create_test_files(
        "null_source_column_migration",
        {
            "version": 2,
            "description": "Migrate temp_email to email preserving NULLs",
            "operations": [
                {
                    "type": "add_column",
                    "table": "users",
                    "column": {"name": "email", "type": "TEXT", "not_null": False},
                },
                {
                    "type": "migrate_column_data",
                    "table": "users",
                    "from_column": "temp_email",
                    "to_column": "email",
                },
            ],
        },
        [
            {
                "event": "operation_applied",
                "type": "add_column",
                "table": "users",
                "column": "email",
                "version": 2,
            },
            {
                "event": "operation_applied",
                "type": "migrate_column_data",
                "table": "users",
                "from_column": "temp_email",
                "to_column": "email",
                "version": 2,
            },
            {"event": "migration_complete", "version": 2, "operations_count": 2},
        ],
        {
            "tables": {
                "users": {
                    "columns": ["id", "temp_email", "name", "email"],
                    "rows": [
                        {"id": 1, "temp_email": "alice@test.com", "name": "Alice", "email": "alice@test.com"},
                        {"id": 2, "temp_email": None, "name": "Bob", "email": None},
                        {"id": 3, "temp_email": "charlie@test.com", "name": "Charlie", "email": "charlie@test.com"},
                        {"id": 4, "temp_email": None, "name": "Diana", "email": None},
                    ],
                }
            }
        },
    )

    # Test 2: null_migration_with_default
    create_test_files(
        "null_migration_with_default",
        {
            "version": 2,
            "description": "Migrate email with default for NULLs",
            "operations": [
                {
                    "type": "add_column",
                    "table": "users",
                    "column": {"name": "email", "type": "TEXT"},
                },
                {
                    "type": "migrate_column_data",
                    "table": "users",
                    "from_column": "old_email",
                    "to_column": "email",
                    "default_value": "'unknown@example.com'",
                },
            ],
        },
        [
            {
                "event": "operation_applied",
                "type": "add_column",
                "table": "users",
                "column": "email",
                "version": 2,
            },
            {
                "event": "operation_applied",
                "type": "migrate_column_data",
                "table": "users",
                "from_column": "old_email",
                "to_column": "email",
                "version": 2,
            },
            {"event": "migration_complete", "version": 2, "operations_count": 2},
        ],
        {
            "tables": {
                "users": {
                    "columns": ["id", "old_email", "name", "email"],
                    "rows": [
                        {"id": 1, "old_email": "alice@old.com", "name": "Alice", "email": "alice@old.com"},
                        {"id": 2, "old_email": None, "name": "Bob", "email": "unknown@example.com"},
                        {"id": 3, "old_email": None, "name": "Charlie", "email": "unknown@example.com"},
                        {"id": 4, "old_email": "diana@old.com", "name": "Diana", "email": "diana@old.com"},
                    ],
                }
            }
        },
    )

    # Test 3: transform_null_concatenation
    create_test_files(
        "transform_null_concatenation",
        {
            "version": 2,
            "description": "Concatenate names with NULLs",
            "operations": [
                {
                    "type": "add_column",
                    "table": "users",
                    "column": {"name": "full_name", "type": "TEXT"},
                },
                {
                    "type": "transform_data",
                    "table": "users",
                    "transformations": [
                        {
                            "column": "full_name",
                            "expression": "first_name || ' ' || middle_name || ' ' || last_name",
                        }
                    ],
                },
            ],
        },
        [
            {
                "event": "operation_applied",
                "type": "add_column",
                "table": "users",
                "column": "full_name",
                "version": 2,
            },
            {
                "event": "operation_applied",
                "type": "transform_data",
                "table": "users",
                "version": 2,
            },
            {"event": "migration_complete", "version": 2, "operations_count": 2},
        ],
        {
            "tables": {
                "users": {
                    "columns": ["id", "first_name", "middle_name", "last_name", "full_name"],
                    "rows": [
                        {"id": 1, "first_name": "Alice", "middle_name": "Ann", "last_name": "Anderson", "full_name": "Alice Ann Anderson"},
                        {"id": 2, "first_name": "Bob", "middle_name": None, "last_name": "Brown", "full_name": None},
                        {"id": 3, "first_name": "Charlie", "middle_name": "C", "last_name": "Clark", "full_name": "Charlie C Clark"},
                        {"id": 4, "first_name": "Diana", "middle_name": None, "last_name": "Davis", "full_name": None},
                    ],
                }
            }
        },
    )

    # Test 4: coalesce_null_handling
    create_test_files(
        "coalesce_null_handling",
        {
            "version": 2,
            "description": "Concatenate names with COALESCE",
            "operations": [
                {
                    "type": "add_column",
                    "table": "users",
                    "column": {"name": "full_name", "type": "TEXT"},
                },
                {
                    "type": "transform_data",
                    "table": "users",
                    "transformations": [
                        {
                            "column": "full_name",
                            "expression": "first_name || ' ' || COALESCE(middle_name || ' ', '') || last_name",
                        }
                    ],
                },
            ],
        },
        [
            {
                "event": "operation_applied",
                "type": "add_column",
                "table": "users",
                "column": "full_name",
                "version": 2,
            },
            {
                "event": "operation_applied",
                "type": "transform_data",
                "table": "users",
                "version": 2,
            },
            {"event": "migration_complete", "version": 2, "operations_count": 2},
        ],
        {
            "tables": {
                "users": {
                    "columns": ["id", "first_name", "middle_name", "last_name", "full_name"],
                    "rows": [
                        {"id": 1, "first_name": "Alice", "middle_name": "Ann", "last_name": "Anderson", "full_name": "Alice Ann Anderson"},
                        {"id": 2, "first_name": "Bob", "middle_name": None, "last_name": "Brown", "full_name": "Bob Brown"},
                        {"id": 3, "first_name": "Charlie", "middle_name": None, "last_name": "Clark", "full_name": "Charlie Clark"},
                    ],
                }
            }
        },
    )

    # Test 5: backfill_only_nulls
    create_test_files(
        "backfill_only_nulls",
        {
            "version": 2,
            "description": "Backfill NULL status values only",
            "operations": [
                {
                    "type": "backfill_data",
                    "table": "products",
                    "column": "status",
                    "value": "'pending'",
                    "where": "status IS NULL",
                },
            ],
        },
        [
            {
                "event": "operation_applied",
                "type": "backfill_data",
                "table": "products",
                "column": "status",
                "version": 2,
            },
            {"event": "migration_complete", "version": 2, "operations_count": 1},
        ],
        {
            "tables": {
                "products": {
                    "columns": ["id", "name", "status", "stock"],
                    "rows": [
                        {"id": 1, "name": "Widget", "status": "pending", "stock": 100},
                        {"id": 2, "name": "Gadget", "status": "active", "stock": 50},
                        {"id": 3, "name": "Doohickey", "status": "pending", "stock": 75},
                        {"id": 4, "name": "Thingamajig", "status": "inactive", "stock": 0},
                    ],
                }
            }
        },
    )

    # Test 6: mathematical_transformations
    create_test_files(
        "mathematical_transformations",
        {
            "version": 2,
            "description": "Calculate final price with tax",
            "operations": [
                {
                    "type": "add_column",
                    "table": "products",
                    "column": {"name": "final_price", "type": "REAL"},
                },
                {
                    "type": "transform_data",
                    "table": "products",
                    "transformations": [
                        {"column": "final_price", "expression": "price * (1 + tax_rate)"}
                    ],
                },
            ],
        },
        [
            {
                "event": "operation_applied",
                "type": "add_column",
                "table": "products",
                "column": "final_price",
                "version": 2,
            },
            {
                "event": "operation_applied",
                "type": "transform_data",
                "table": "products",
                "version": 2,
            },
            {"event": "migration_complete", "version": 2, "operations_count": 2},
        ],
        {
            "tables": {
                "products": {
                    "columns": ["id", "price", "tax_rate", "final_price"],
                    "rows": [
                        {"id": 1, "price": 100.0, "tax_rate": 0.08, "final_price": 108.0},
                        {"id": 2, "price": 50.5, "tax_rate": 0.08, "final_price": 54.54},
                        {"id": 3, "price": 200.0, "tax_rate": 0.1, "final_price": 220.0},
                        {"id": 4, "price": 75.25, "tax_rate": 0.08, "final_price": 81.27},
                    ],
                }
            }
        },
    )

    # Test 7: case_statement_transformation
    create_test_files(
        "case_statement_transformation",
        {
            "version": 2,
            "description": "Add order size category",
            "operations": [
                {
                    "type": "add_column",
                    "table": "orders",
                    "column": {"name": "size_category", "type": "TEXT"},
                },
                {
                    "type": "transform_data",
                    "table": "orders",
                    "transformations": [
                        {
                            "column": "size_category",
                            "expression": "CASE WHEN total < 50 THEN 'small' WHEN total < 200 THEN 'medium' ELSE 'large' END",
                        }
                    ],
                },
            ],
        },
        [
            {
                "event": "operation_applied",
                "type": "add_column",
                "table": "orders",
                "column": "size_category",
                "version": 2,
            },
            {
                "event": "operation_applied",
                "type": "transform_data",
                "table": "orders",
                "version": 2,
            },
            {"event": "migration_complete", "version": 2, "operations_count": 2},
        ],
        {
            "tables": {
                "orders": {
                    "columns": ["id", "total", "created_at", "size_category"],
                    "rows": [
                        {"id": 1, "total": 25.0, "created_at": "2024-01-01", "size_category": "small"},
                        {"id": 2, "total": 150.0, "created_at": "2024-01-02", "size_category": "medium"},
                        {"id": 3, "total": 75.0, "created_at": "2024-01-03", "size_category": "medium"},
                        {"id": 4, "total": 500.0, "created_at": "2024-01-04", "size_category": "large"},
                        {"id": 5, "total": 10.0, "created_at": "2024-01-05", "size_category": "small"},
                    ],
                }
            }
        },
    )

    # Test 8: string_functions_transform
    create_test_files(
        "string_functions_transform",
        {
            "version": 2,
            "description": "Normalize email and extract domain",
            "operations": [
                {
                    "type": "add_column",
                    "table": "users",
                    "column": {"name": "email_normalized", "type": "TEXT"},
                },
                {
                    "type": "add_column",
                    "table": "users",
                    "column": {"name": "email_domain", "type": "TEXT"},
                },
                {
                    "type": "transform_data",
                    "table": "users",
                    "transformations": [
                        {"column": "email_normalized", "expression": "LOWER(email)"},
                        {
                            "column": "email_domain",
                            "expression": "SUBSTR(LOWER(email), INSTR(LOWER(email), '@') + 1)",
                        },
                    ],
                },
            ],
        },
        [
            {
                "event": "operation_applied",
                "type": "add_column",
                "table": "users",
                "column": "email_normalized",
                "version": 2,
            },
            {
                "event": "operation_applied",
                "type": "add_column",
                "table": "users",
                "column": "email_domain",
                "version": 2,
            },
            {
                "event": "operation_applied",
                "type": "transform_data",
                "table": "users",
                "version": 2,
            },
            {"event": "migration_complete", "version": 2, "operations_count": 3},
        ],
        {
            "tables": {
                "users": {
                    "columns": ["id", "email", "username", "email_normalized", "email_domain"],
                    "rows": [
                        {"id": 1, "email": "Alice@Example.COM", "username": "alice123", "email_normalized": "alice@example.com", "email_domain": "example.com"},
                        {"id": 2, "email": "BOB@example.com", "username": "bob456", "email_normalized": "bob@example.com", "email_domain": "example.com"},
                        {"id": 3, "email": "Charlie@TEST.org", "username": "charlie789", "email_normalized": "charlie@test.org", "email_domain": "test.org"},
                    ],
                }
            }
        },
    )

    # Test 9: nested_expressions
    create_test_files(
        "nested_expressions",
        {
            "version": 2,
            "description": "Create display name and price tier",
            "operations": [
                {
                    "type": "add_column",
                    "table": "products",
                    "column": {"name": "display_name", "type": "TEXT"},
                },
                {
                    "type": "transform_data",
                    "table": "products",
                    "transformations": [
                        {
                            "column": "display_name",
                            "expression": "UPPER(SUBSTR(name, 1, 1)) || SUBSTR(name, 2) || ' - $' || CAST(ROUND(price, 2) AS TEXT)",
                        }
                    ],
                },
            ],
        },
        [
            {
                "event": "operation_applied",
                "type": "add_column",
                "table": "products",
                "column": "display_name",
                "version": 2,
            },
            {
                "event": "operation_applied",
                "type": "transform_data",
                "table": "products",
                "version": 2,
            },
            {"event": "migration_complete", "version": 2, "operations_count": 2},
        ],
        {
            "tables": {
                "products": {
                    "columns": ["id", "name", "price", "display_name"],
                    "rows": [
                        {"id": 1, "name": "super widget", "price": 99.99, "display_name": "Super widget - $99.99"},
                        {"id": 2, "name": "mega gadget", "price": 149.50, "display_name": "Mega gadget - $149.5"},
                        {"id": 3, "name": "ultra doohickey", "price": 75.00, "display_name": "Ultra doohickey - $75.0"},
                    ],
                }
            }
        },
    )

    # Test 10: integer_division_and_modulo
    create_test_files(
        "integer_division_and_modulo",
        {
            "version": 2,
            "description": "Split cents into dollars and cents",
            "operations": [
                {
                    "type": "add_column",
                    "table": "transactions",
                    "column": {"name": "dollars", "type": "INTEGER"},
                },
                {
                    "type": "add_column",
                    "table": "transactions",
                    "column": {"name": "cents", "type": "INTEGER"},
                },
                {
                    "type": "transform_data",
                    "table": "transactions",
                    "transformations": [
                        {"column": "dollars", "expression": "amount_cents / 100"},
                        {"column": "cents", "expression": "amount_cents % 100"},
                    ],
                },
            ],
        },
        [
            {
                "event": "operation_applied",
                "type": "add_column",
                "table": "transactions",
                "column": "dollars",
                "version": 2,
            },
            {
                "event": "operation_applied",
                "type": "add_column",
                "table": "transactions",
                "column": "cents",
                "version": 2,
            },
            {
                "event": "operation_applied",
                "type": "transform_data",
                "table": "transactions",
                "version": 2,
            },
            {"event": "migration_complete", "version": 2, "operations_count": 3},
        ],
        {
            "tables": {
                "transactions": {
                    "columns": ["id", "amount_cents", "dollars", "cents"],
                    "rows": [
                        {"id": 1, "amount_cents": 12345, "dollars": 123, "cents": 45},
                        {"id": 2, "amount_cents": 50000, "dollars": 500, "cents": 0},
                        {"id": 3, "amount_cents": 9999, "dollars": 99, "cents": 99},
                        {"id": 4, "amount_cents": 100, "dollars": 1, "cents": 0},
                    ],
                }
            }
        },
    )

    # Test 11: add_transform_backfill_sequence
    create_test_files(
        "add_transform_backfill_sequence",
        {
            "version": 2,
            "description": "Add full_name and grade, then transform both",
            "operations": [
                {
                    "type": "add_column",
                    "table": "users",
                    "column": {"name": "full_name", "type": "TEXT"},
                },
                {
                    "type": "add_column",
                    "table": "users",
                    "column": {"name": "grade", "type": "TEXT"},
                },
                {
                    "type": "transform_data",
                    "table": "users",
                    "transformations": [
                        {"column": "full_name", "expression": "first_name || ' ' || last_name"}
                    ],
                },
                {
                    "type": "transform_data",
                    "table": "users",
                    "transformations": [
                        {
                            "column": "grade",
                            "expression": "CASE WHEN score >= 90 THEN 'A' WHEN score >= 80 THEN 'B' ELSE 'C' END",
                        }
                    ],
                },
            ],
        },
        [
            {
                "event": "operation_applied",
                "type": "add_column",
                "table": "users",
                "column": "full_name",
                "version": 2,
            },
            {
                "event": "operation_applied",
                "type": "add_column",
                "table": "users",
                "column": "grade",
                "version": 2,
            },
            {
                "event": "operation_applied",
                "type": "transform_data",
                "table": "users",
                "version": 2,
            },
            {
                "event": "operation_applied",
                "type": "transform_data",
                "table": "users",
                "version": 2,
            },
            {"event": "migration_complete", "version": 2, "operations_count": 4},
        ],
        {
            "tables": {
                "users": {
                    "columns": ["id", "first_name", "last_name", "score", "full_name", "grade"],
                    "rows": [
                        {"id": 1, "first_name": "Alice", "last_name": "Anderson", "score": 85, "full_name": "Alice Anderson", "grade": "B"},
                        {"id": 2, "first_name": "Bob", "last_name": "Brown", "score": 92, "full_name": "Bob Brown", "grade": "A"},
                        {"id": 3, "first_name": "Charlie", "last_name": "Clark", "score": 78, "full_name": "Charlie Clark", "grade": "C"},
                    ],
                }
            }
        },
    )

    # Test 12: add_migrate_transform_sequence
    create_test_files(
        "add_migrate_transform_sequence",
        {
            "version": 2,
            "description": "Migrate to new price with 10% increase",
            "operations": [
                {
                    "type": "add_column",
                    "table": "products",
                    "column": {"name": "price", "type": "REAL"},
                },
                {
                    "type": "migrate_column_data",
                    "table": "products",
                    "from_column": "old_price",
                    "to_column": "price",
                },
                {
                    "type": "transform_data",
                    "table": "products",
                    "transformations": [{"column": "price", "expression": "price * 1.10"}],
                },
            ],
        },
        [
            {
                "event": "operation_applied",
                "type": "add_column",
                "table": "products",
                "column": "price",
                "version": 2,
            },
            {
                "event": "operation_applied",
                "type": "migrate_column_data",
                "table": "products",
                "from_column": "old_price",
                "to_column": "price",
                "version": 2,
            },
            {
                "event": "operation_applied",
                "type": "transform_data",
                "table": "products",
                "version": 2,
            },
            {"event": "migration_complete", "version": 2, "operations_count": 3},
        ],
        {
            "tables": {
                "products": {
                    "columns": ["id", "name", "old_price", "price"],
                    "rows": [
                        {"id": 1, "name": "Widget", "old_price": 100.0, "price": 110.0},
                        {"id": 2, "name": "Gadget", "old_price": 50.0, "price": 55.0},
                        {"id": 3, "name": "Doohickey", "old_price": 75.0, "price": 82.5},
                    ],
                }
            }
        },
    )

    # Test 13: multiple_tables_single_migration
    create_test_files(
        "multiple_tables_single_migration",
        {
            "version": 2,
            "description": "Add status to both users and orders",
            "operations": [
                {
                    "type": "add_column",
                    "table": "users",
                    "column": {"name": "status", "type": "TEXT"},
                },
                {
                    "type": "backfill_data",
                    "table": "users",
                    "column": "status",
                    "value": "'active'",
                },
                {
                    "type": "add_column",
                    "table": "orders",
                    "column": {"name": "status", "type": "TEXT"},
                },
                {
                    "type": "backfill_data",
                    "table": "orders",
                    "column": "status",
                    "value": "'pending'",
                },
            ],
        },
        [
            {
                "event": "operation_applied",
                "type": "add_column",
                "table": "users",
                "column": "status",
                "version": 2,
            },
            {
                "event": "operation_applied",
                "type": "backfill_data",
                "table": "users",
                "column": "status",
                "version": 2,
            },
            {
                "event": "operation_applied",
                "type": "add_column",
                "table": "orders",
                "column": "status",
                "version": 2,
            },
            {
                "event": "operation_applied",
                "type": "backfill_data",
                "table": "orders",
                "column": "status",
                "version": 2,
            },
            {"event": "migration_complete", "version": 2, "operations_count": 4},
        ],
        {
            "tables": {
                "users": {
                    "columns": ["id", "name", "status"],
                    "rows": [
                        {"id": 1, "name": "Alice", "status": "active"},
                        {"id": 2, "name": "Bob", "status": "active"},
                    ],
                },
                "orders": {
                    "columns": ["id", "user_id", "total", "status"],
                    "rows": [
                        {"id": 1, "user_id": 1, "total": 100.0, "status": "pending"},
                        {"id": 2, "user_id": 1, "total": 50.0, "status": "pending"},
                        {"id": 3, "user_id": 2, "total": 75.0, "status": "pending"},
                    ],
                },
            }
        },
    )

    # Test 14: all_three_new_operations_chained
    create_test_files(
        "all_three_new_operations_chained",
        {
            "version": 2,
            "description": "Complex employee data migration",
            "operations": [
                {
                    "type": "add_column",
                    "table": "employees",
                    "column": {"name": "email", "type": "TEXT"},
                },
                {
                    "type": "add_column",
                    "table": "employees",
                    "column": {"name": "full_name", "type": "TEXT"},
                },
                {
                    "type": "add_column",
                    "table": "employees",
                    "column": {"name": "bonus", "type": "INTEGER"},
                },
                {
                    "type": "migrate_column_data",
                    "table": "employees",
                    "from_column": "temp_email",
                    "to_column": "email",
                    "default_value": "'noemail@company.com'",
                },
                {
                    "type": "transform_data",
                    "table": "employees",
                    "transformations": [
                        {"column": "full_name", "expression": "first_name || ' ' || last_name"},
                        {"column": "bonus", "expression": "salary / 10"},
                    ],
                },
                {
                    "type": "backfill_data",
                    "table": "employees",
                    "column": "email",
                    "value": "LOWER(email)",
                },
            ],
        },
        [
            {
                "event": "operation_applied",
                "type": "add_column",
                "table": "employees",
                "column": "email",
                "version": 2,
            },
            {
                "event": "operation_applied",
                "type": "add_column",
                "table": "employees",
                "column": "full_name",
                "version": 2,
            },
            {
                "event": "operation_applied",
                "type": "add_column",
                "table": "employees",
                "column": "bonus",
                "version": 2,
            },
            {
                "event": "operation_applied",
                "type": "migrate_column_data",
                "table": "employees",
                "from_column": "temp_email",
                "to_column": "email",
                "version": 2,
            },
            {
                "event": "operation_applied",
                "type": "transform_data",
                "table": "employees",
                "version": 2,
            },
            {
                "event": "operation_applied",
                "type": "backfill_data",
                "table": "employees",
                "column": "email",
                "version": 2,
            },
            {"event": "migration_complete", "version": 2, "operations_count": 6},
        ],
        {
            "tables": {
                "employees": {
                    "columns": ["id", "temp_email", "salary", "first_name", "last_name", "email", "full_name", "bonus"],
                    "rows": [
                        {"id": 1, "temp_email": "alice@old.com", "salary": 50000, "first_name": "Alice", "last_name": "Anderson", "email": "alice@old.com", "full_name": "Alice Anderson", "bonus": 5000},
                        {"id": 2, "temp_email": None, "salary": 60000, "first_name": "Bob", "last_name": "Brown", "email": "noemail@company.com", "full_name": "Bob Brown", "bonus": 6000},
                        {"id": 3, "temp_email": "charlie@old.com", "salary": 55000, "first_name": "Charlie", "last_name": "Clark", "email": "charlie@old.com", "full_name": "Charlie Clark", "bonus": 5500},
                    ],
                }
            }
        },
    )

    # Test 15: empty_table_operations
    create_test_files(
        "empty_table_operations",
        {
            "version": 2,
            "description": "Operations on empty table",
            "operations": [
                {
                    "type": "add_column",
                    "table": "users",
                    "column": {"name": "email", "type": "TEXT"},
                },
                {
                    "type": "add_column",
                    "table": "users",
                    "column": {"name": "status", "type": "TEXT"},
                },
                {
                    "type": "backfill_data",
                    "table": "users",
                    "column": "status",
                    "value": "'active'",
                },
            ],
        },
        [
            {
                "event": "operation_applied",
                "type": "add_column",
                "table": "users",
                "column": "email",
                "version": 2,
            },
            {
                "event": "operation_applied",
                "type": "add_column",
                "table": "users",
                "column": "status",
                "version": 2,
            },
            {
                "event": "operation_applied",
                "type": "backfill_data",
                "table": "users",
                "column": "status",
                "version": 2,
            },
            {"event": "migration_complete", "version": 2, "operations_count": 3},
        ],
        {
            "tables": {
                "users": {
                    "row_count": 0,
                }
            }
        },
    )

    # Test 16: where_clause_no_matches
    create_test_files(
        "where_clause_no_matches",
        {
            "version": 2,
            "description": "Backfill non-existent inactive products",
            "operations": [
                {
                    "type": "backfill_data",
                    "table": "products",
                    "column": "status",
                    "value": "'archived'",
                    "where": "status = 'inactive'",
                },
            ],
        },
        [
            {
                "event": "operation_applied",
                "type": "backfill_data",
                "table": "products",
                "column": "status",
                "version": 2,
            },
            {"event": "migration_complete", "version": 2, "operations_count": 1},
        ],
        {
            "tables": {
                "products": {
                    "columns": ["id", "name", "status"],
                    "rows": [
                        {"id": 1, "name": "Widget", "status": "active"},
                        {"id": 2, "name": "Gadget", "status": "active"},
                        {"id": 3, "name": "Doohickey", "status": "active"},
                    ],
                }
            }
        },
    )

    # Test 17: large_dataset_migration
    create_test_files(
        "large_dataset_migration",
        {
            "version": 2,
            "description": "Transform large dataset",
            "operations": [
                {
                    "type": "add_column",
                    "table": "events",
                    "column": {"name": "category", "type": "TEXT"},
                },
                {
                    "type": "transform_data",
                    "table": "events",
                    "transformations": [
                        {
                            "column": "category",
                            "expression": "CASE WHEN value < 100 THEN 'low' WHEN value < 500 THEN 'medium' ELSE 'high' END",
                        }
                    ],
                },
            ],
        },
        [
            {
                "event": "operation_applied",
                "type": "add_column",
                "table": "events",
                "column": "category",
                "version": 2,
            },
            {
                "event": "operation_applied",
                "type": "transform_data",
                "table": "events",
                "version": 2,
            },
            {"event": "migration_complete", "version": 2, "operations_count": 2},
        ],
        {
            "tables": {
                "events": {
                    "row_count": 150,
                }
            }
        },
    )

    # Test 18: various_data_types
    create_test_files(
        "various_data_types",
        {
            "version": 2,
            "description": "Transform various types",
            "operations": [
                {
                    "type": "add_column",
                    "table": "mixed_data",
                    "column": {"name": "computed", "type": "REAL"},
                },
                {
                    "type": "add_column",
                    "table": "mixed_data",
                    "column": {"name": "text_upper", "type": "TEXT"},
                },
                {
                    "type": "transform_data",
                    "table": "mixed_data",
                    "transformations": [
                        {"column": "computed", "expression": "int_val * real_val"},
                        {"column": "text_upper", "expression": "UPPER(text_val)"},
                    ],
                },
            ],
        },
        [
            {
                "event": "operation_applied",
                "type": "add_column",
                "table": "mixed_data",
                "column": "computed",
                "version": 2,
            },
            {
                "event": "operation_applied",
                "type": "add_column",
                "table": "mixed_data",
                "column": "text_upper",
                "version": 2,
            },
            {
                "event": "operation_applied",
                "type": "transform_data",
                "table": "mixed_data",
                "version": 2,
            },
            {"event": "migration_complete", "version": 2, "operations_count": 3},
        ],
        {
            "tables": {
                "mixed_data": {
                    "columns": ["id", "int_val", "real_val", "text_val", "computed", "text_upper"],
                    "rows": [
                        {"id": 1, "int_val": 42, "real_val": 3.14, "text_val": "hello", "computed": 131.88, "text_upper": "HELLO"},
                        {"id": 2, "int_val": 100, "real_val": 2.71, "text_val": "world", "computed": 271.0, "text_upper": "WORLD"},
                    ],
                }
            }
        },
    )

    # Test 19: checkpoint1_and_checkpoint2_mixed
    create_test_files(
        "checkpoint1_and_checkpoint2_mixed",
        {
            "version": 2,
            "description": "Mixed checkpoint 1 and 2 operations",
            "operations": [
                {
                    "type": "add_column",
                    "table": "users",
                    "column": {"name": "name", "type": "TEXT"},
                },
                {
                    "type": "migrate_column_data",
                    "table": "users",
                    "from_column": "old_name",
                    "to_column": "name",
                },
                {"type": "drop_column", "table": "users", "column": "old_name"},
                {
                    "type": "add_column",
                    "table": "users",
                    "column": {"name": "age_group", "type": "TEXT"},
                },
                {
                    "type": "transform_data",
                    "table": "users",
                    "transformations": [
                        {
                            "column": "age_group",
                            "expression": "CASE WHEN age < 30 THEN 'young' ELSE 'adult' END",
                        }
                    ],
                },
            ],
        },
        [
            {
                "event": "operation_applied",
                "type": "add_column",
                "table": "users",
                "column": "name",
                "version": 2,
            },
            {
                "event": "operation_applied",
                "type": "migrate_column_data",
                "table": "users",
                "from_column": "old_name",
                "to_column": "name",
                "version": 2,
            },
            {
                "event": "operation_applied",
                "type": "drop_column",
                "table": "users",
                "column": "old_name",
                "version": 2,
            },
            {
                "event": "operation_applied",
                "type": "add_column",
                "table": "users",
                "column": "age_group",
                "version": 2,
            },
            {
                "event": "operation_applied",
                "type": "transform_data",
                "table": "users",
                "version": 2,
            },
            {"event": "migration_complete", "version": 2, "operations_count": 5},
        ],
        {
            "tables": {
                "users": {
                    "columns": ["id", "age", "name", "age_group"],
                    "rows": [
                        {"id": 1, "age": 30, "name": "Alice", "age_group": "adult"},
                        {"id": 2, "age": 25, "name": "Bob", "age_group": "young"},
                    ],
                }
            }
        },
    )

    # Test 20: create_table_then_populate
    create_test_files(
        "create_table_then_populate",
        {
            "version": 2,
            "description": "Create and populate new table",
            "operations": [
                {
                    "type": "create_table",
                    "table": "settings",
                    "columns": [
                        {"name": "id", "type": "INTEGER", "primary_key": True},
                        {"name": "key", "type": "TEXT", "not_null": True},
                        {"name": "value", "type": "TEXT"},
                    ],
                },
                {
                    "type": "add_column",
                    "table": "settings",
                    "column": {"name": "created_at", "type": "TEXT"},
                },
            ],
        },
        [
            {
                "event": "operation_applied",
                "type": "create_table",
                "table": "settings",
                "version": 2,
            },
            {
                "event": "operation_applied",
                "type": "add_column",
                "table": "settings",
                "column": "created_at",
                "version": 2,
            },
            {"event": "migration_complete", "version": 2, "operations_count": 2},
        ],
        {
            "tables": {
                "settings": {
                    "row_count": 0,
                }
            }
        },
    )

    print("\n✓ All test configuration files generated successfully!")


if __name__ == "__main__":
    main()
