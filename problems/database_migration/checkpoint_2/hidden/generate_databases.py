#!/usr/bin/env python3
"""
Helper script to generate all SQLite databases for checkpoint_2 hidden tests.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path


def create_migrations_table(cursor):
    """Create the _migrations tracking table."""
    cursor.execute("""
        CREATE TABLE "_migrations" (
            "version" INTEGER,
            "description" TEXT,
            "applied_at" TEXT
        )
    """)
    cursor.execute(
        "INSERT INTO _migrations VALUES (1, 'Initial schema', '2024-01-01 00:00:00')"
    )


def create_test_db(test_name, schema_sql, data_rows=None):
    """Create a SQLite database for a test case.

    Args:
        test_name: Name of the test directory
        schema_sql: SQL to create tables
        data_rows: Dict of {table_name: [(col1, col2, ...), ...]}
    """
    db_path = Path(__file__).parent / test_name / "app.db"

    # Remove existing database if it exists
    if db_path.exists():
        db_path.unlink()

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    # Create _migrations table
    create_migrations_table(cursor)

    # Create test schema
    cursor.executescript(schema_sql)

    # Insert test data
    if data_rows:
        for table, rows in data_rows.items():
            for row in rows:
                placeholders = ", ".join(["?"] * len(row))
                cursor.execute(f"INSERT INTO {table} VALUES ({placeholders})", row)

    conn.commit()
    conn.close()
    print(f"✓ Created {test_name}/app.db")


def main():
    """Generate all test databases."""
    print("Generating test databases...\n")

    # Category 1: NULL Handling Tests

    # Test 1: null_source_column_migration
    create_test_db(
        "null_source_column_migration",
        """
        CREATE TABLE users (
            id INTEGER,
            temp_email TEXT,
            name TEXT
        );
        """,
        {
            "users": [
                (1, "alice@test.com", "Alice"),
                (2, None, "Bob"),
                (3, "charlie@test.com", "Charlie"),
                (4, None, "Diana"),
            ]
        },
    )

    # Test 2: null_migration_with_default
    create_test_db(
        "null_migration_with_default",
        """
        CREATE TABLE users (
            id INTEGER,
            old_email TEXT,
            name TEXT
        );
        """,
        {
            "users": [
                (1, "alice@old.com", "Alice"),
                (2, None, "Bob"),
                (3, None, "Charlie"),
                (4, "diana@old.com", "Diana"),
            ]
        },
    )

    # Test 3: transform_null_concatenation
    create_test_db(
        "transform_null_concatenation",
        """
        CREATE TABLE users (
            id INTEGER,
            first_name TEXT,
            middle_name TEXT,
            last_name TEXT
        );
        """,
        {
            "users": [
                (1, "Alice", "Ann", "Anderson"),
                (2, "Bob", None, "Brown"),
                (3, "Charlie", "C", "Clark"),
                (4, "Diana", None, "Davis"),
            ]
        },
    )

    # Test 4: coalesce_null_handling
    create_test_db(
        "coalesce_null_handling",
        """
        CREATE TABLE users (
            id INTEGER,
            first_name TEXT,
            middle_name TEXT,
            last_name TEXT
        );
        """,
        {
            "users": [
                (1, "Alice", "Ann", "Anderson"),
                (2, "Bob", None, "Brown"),
                (3, "Charlie", None, "Clark"),
            ]
        },
    )

    # Test 5: backfill_only_nulls
    create_test_db(
        "backfill_only_nulls",
        """
        CREATE TABLE products (
            id INTEGER,
            name TEXT,
            status TEXT,
            stock INTEGER
        );
        """,
        {
            "products": [
                (1, "Widget", None, 100),
                (2, "Gadget", "active", 50),
                (3, "Doohickey", None, 75),
                (4, "Thingamajig", "inactive", 0),
            ]
        },
    )

    # Category 2: Complex SQL Expression Tests

    # Test 6: mathematical_transformations
    create_test_db(
        "mathematical_transformations",
        """
        CREATE TABLE products (
            id INTEGER,
            price REAL,
            tax_rate REAL
        );
        """,
        {
            "products": [
                (1, 100.0, 0.08),
                (2, 50.5, 0.08),
                (3, 200.0, 0.1),
                (4, 75.25, 0.08),
            ]
        },
    )

    # Test 7: case_statement_transformation
    create_test_db(
        "case_statement_transformation",
        """
        CREATE TABLE orders (
            id INTEGER,
            total REAL,
            created_at TEXT
        );
        """,
        {
            "orders": [
                (1, 25.0, "2024-01-01"),
                (2, 150.0, "2024-01-02"),
                (3, 75.0, "2024-01-03"),
                (4, 500.0, "2024-01-04"),
                (5, 10.0, "2024-01-05"),
            ]
        },
    )

    # Test 8: string_functions_transform
    create_test_db(
        "string_functions_transform",
        """
        CREATE TABLE users (
            id INTEGER,
            email TEXT,
            username TEXT
        );
        """,
        {
            "users": [
                (1, "Alice@Example.COM", "alice123"),
                (2, "BOB@example.com", "bob456"),
                (3, "Charlie@TEST.org", "charlie789"),
            ]
        },
    )

    # Test 9: nested_expressions
    create_test_db(
        "nested_expressions",
        """
        CREATE TABLE products (
            id INTEGER,
            name TEXT,
            price REAL
        );
        """,
        {
            "products": [
                (1, "super widget", 99.99),
                (2, "mega gadget", 149.50),
                (3, "ultra doohickey", 75.00),
            ]
        },
    )

    # Test 10: integer_division_and_modulo
    create_test_db(
        "integer_division_and_modulo",
        """
        CREATE TABLE transactions (
            id INTEGER,
            amount_cents INTEGER
        );
        """,
        {
            "transactions": [
                (1, 12345),
                (2, 50000),
                (3, 9999),
                (4, 100),
            ]
        },
    )

    # Category 3: Multi-Operation Workflow Tests

    # Test 11: add_transform_backfill_sequence
    create_test_db(
        "add_transform_backfill_sequence",
        """
        CREATE TABLE users (
            id INTEGER,
            first_name TEXT,
            last_name TEXT,
            score INTEGER
        );
        """,
        {
            "users": [
                (1, "Alice", "Anderson", 85),
                (2, "Bob", "Brown", 92),
                (3, "Charlie", "Clark", 78),
            ]
        },
    )

    # Test 12: add_migrate_transform_sequence
    create_test_db(
        "add_migrate_transform_sequence",
        """
        CREATE TABLE products (
            id INTEGER,
            name TEXT,
            old_price REAL
        );
        """,
        {
            "products": [
                (1, "Widget", 100.0),
                (2, "Gadget", 50.0),
                (3, "Doohickey", 75.0),
            ]
        },
    )

    # Test 13: multiple_tables_single_migration
    create_test_db(
        "multiple_tables_single_migration",
        """
        CREATE TABLE users (
            id INTEGER,
            name TEXT
        );
        CREATE TABLE orders (
            id INTEGER,
            user_id INTEGER,
            total REAL
        );
        """,
        {
            "users": [
                (1, "Alice"),
                (2, "Bob"),
            ],
            "orders": [
                (1, 1, 100.0),
                (2, 1, 50.0),
                (3, 2, 75.0),
            ],
        },
    )

    # Test 14: all_three_new_operations_chained
    create_test_db(
        "all_three_new_operations_chained",
        """
        CREATE TABLE employees (
            id INTEGER,
            temp_email TEXT,
            salary INTEGER,
            first_name TEXT,
            last_name TEXT
        );
        """,
        {
            "employees": [
                (1, "alice@old.com", 50000, "Alice", "Anderson"),
                (2, None, 60000, "Bob", "Brown"),
                (3, "charlie@old.com", 55000, "Charlie", "Clark"),
            ]
        },
    )

    # Category 4: Edge Case Tests

    # Test 15: empty_table_operations
    create_test_db(
        "empty_table_operations",
        """
        CREATE TABLE users (
            id INTEGER,
            name TEXT
        );
        """,
        {"users": []},  # Empty table
    )

    # Test 16: where_clause_no_matches
    create_test_db(
        "where_clause_no_matches",
        """
        CREATE TABLE products (
            id INTEGER,
            name TEXT,
            status TEXT
        );
        """,
        {
            "products": [
                (1, "Widget", "active"),
                (2, "Gadget", "active"),
                (3, "Doohickey", "active"),
            ]
        },
    )

    # Test 17: large_dataset_migration
    create_test_db(
        "large_dataset_migration",
        """
        CREATE TABLE events (
            id INTEGER,
            event_type TEXT,
            value INTEGER
        );
        """,
        {
            "events": [
                (i, f"type_{i % 10}", (i * 17) % 1000)
                for i in range(1, 151)
            ]
        },
    )

    # Test 18: various_data_types
    create_test_db(
        "various_data_types",
        """
        CREATE TABLE mixed_data (
            id INTEGER,
            int_val INTEGER,
            real_val REAL,
            text_val TEXT,
            blob_val BLOB
        );
        """,
        {
            "mixed_data": [
                (1, 42, 3.14, "hello", b"\xDE\xAD\xBE\xEF"),
                (2, 100, 2.71, "world", b"\xCA\xFE\xBA\xBE"),
            ]
        },
    )

    # Category 5: Regression Tests

    # Test 19: checkpoint1_and_checkpoint2_mixed
    create_test_db(
        "checkpoint1_and_checkpoint2_mixed",
        """
        CREATE TABLE users (
            id INTEGER,
            old_name TEXT,
            age INTEGER
        );
        """,
        {
            "users": [
                (1, "Alice", 30),
                (2, "Bob", 25),
            ]
        },
    )

    # Test 20: create_table_then_populate
    create_test_db(
        "create_table_then_populate",
        "",  # Only _migrations table
        None,
    )

    print("\n✓ All databases generated successfully!")


if __name__ == "__main__":
    main()
