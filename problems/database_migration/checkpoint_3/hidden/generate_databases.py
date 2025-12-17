#!/usr/bin/env python3
"""
Helper script to generate all SQLite databases for checkpoint_3 hidden tests.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path


def create_migrations_table(cursor, version=1):
    """Create the _migrations tracking table."""
    cursor.execute("""
        CREATE TABLE "_migrations" (
            "version" INTEGER,
            "description" TEXT,
            "applied_at" TEXT
        )
    """)
    cursor.execute(
        f"INSERT INTO _migrations VALUES ({version}, 'Initial schema', '2024-01-01 00:00:00')"
    )


def create_test_db(test_name, schema_sql, data_rows=None, migrations_version=1):
    """Create a SQLite database for a test case.

    Args:
        test_name: Name of the test directory
        schema_sql: SQL to create tables
        data_rows: Dict of {table_name: [(col1, col2, ...), ...]}
        migrations_version: Version number for _migrations table
    """
    db_path = Path(__file__).parent / test_name / "app.db"

    # Remove existing database if it exists
    if db_path.exists():
        db_path.unlink()

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    # Enable foreign keys
    cursor.execute("PRAGMA foreign_keys = ON")

    # Create _migrations table
    create_migrations_table(cursor, version=migrations_version)

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

    # Test 1: drop_foreign_key
    create_test_db(
        "drop_foreign_key",
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL
        );
        CREATE TABLE posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            content TEXT,
            CONSTRAINT fk_posts_user_id FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        """,
        {
            "users": [
                (1, "alice@example.com", "Alice"),
                (2, "bob@example.com", "Bob"),
            ],
            "posts": [
                (1, 1, "First Post", "Hello world"),
                (2, 2, "Second Post", "Testing"),
            ],
        },
        migrations_version=1
    )

    # Test 2: composite_foreign_key
    create_test_db(
        "composite_foreign_key",
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL
        );
        CREATE TABLE address_types (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL
        );
        CREATE TABLE addresses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            address_type_id INTEGER NOT NULL,
            street TEXT NOT NULL,
            city TEXT NOT NULL
        );
        """,
        {
            "users": [
                (1, "alice@example.com"),
                (2, "bob@example.com"),
            ],
            "address_types": [
                (1, "home"),
                (2, "work"),
            ],
            "addresses": [
                (1, 1, 1, "123 Main St", "Boston"),
                (2, 1, 2, "456 Work Ave", "Boston"),
            ],
        },
        migrations_version=1
    )

    # Test 3: multiple_foreign_keys_same_table
    create_test_db(
        "multiple_foreign_keys_same_table",
        """
        CREATE TABLE departments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL
        );
        CREATE TABLE locations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            city TEXT NOT NULL
        );
        CREATE TABLE employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            department_id INTEGER NOT NULL,
            location_id INTEGER NOT NULL
        );
        """,
        {
            "departments": [
                (1, "Engineering"),
                (2, "Sales"),
            ],
            "locations": [
                (1, "San Francisco"),
                (2, "New York"),
            ],
            "employees": [
                (1, "Alice", 1, 1),
                (2, "Bob", 2, 2),
            ],
        },
        migrations_version=1
    )

    # Test 4: foreign_key_set_null
    create_test_db(
        "foreign_key_set_null",
        """
        CREATE TABLE categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL
        );
        CREATE TABLE products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category_id INTEGER
        );
        """,
        {
            "categories": [
                (1, "Electronics"),
                (2, "Books"),
            ],
            "products": [
                (1, "Laptop", 1),
                (2, "Phone", 1),
                (3, "Novel", 2),
            ],
        },
        migrations_version=1
    )

    # Test 5: foreign_key_set_default
    create_test_db(
        "foreign_key_set_default",
        """
        CREATE TABLE statuses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL
        );
        CREATE TABLE tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            status_id INTEGER NOT NULL DEFAULT 1
        );
        """,
        {
            "statuses": [
                (1, "Pending"),
                (2, "In Progress"),
                (3, "Done"),
            ],
            "tasks": [
                (1, "Task A", 2),
                (2, "Task B", 3),
            ],
        },
        migrations_version=1
    )

    # Test 6: self_referential_foreign_key
    create_test_db(
        "self_referential_foreign_key",
        """
        CREATE TABLE employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            manager_id INTEGER
        );
        """,
        {
            "employees": [
                (1, "CEO Alice", None),
                (2, "Manager Bob", 1),
                (3, "Employee Charlie", 2),
            ],
        },
        migrations_version=1
    )

    # Test 7: drop_index
    create_test_db(
        "drop_index",
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL,
            name TEXT NOT NULL
        );
        CREATE INDEX idx_users_email ON users(email);
        """,
        {
            "users": [
                (1, "alice@test.com", "Alice"),
                (2, "bob@test.com", "Bob"),
            ],
        },
        migrations_version=1
    )

    # Test 8: unique_index
    create_test_db(
        "unique_index",
        """
        CREATE TABLE products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sku TEXT NOT NULL,
            name TEXT NOT NULL,
            price REAL NOT NULL
        );
        """,
        {
            "products": [
                (1, "SKU001", "Product A", 19.99),
                (2, "SKU002", "Product B", 29.99),
            ],
        },
        migrations_version=1
    )

    # Test 9: unique_index_with_nulls
    create_test_db(
        "unique_index_with_nulls",
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL,
            social_security_number TEXT
        );
        """,
        {
            "users": [
                (1, "alice@test.com", "123-45-6789"),
                (2, "bob@test.com", None),
                (3, "charlie@test.com", None),
            ],
        },
        migrations_version=1
    )

    # Test 10: multi_column_unique_index
    create_test_db(
        "multi_column_unique_index",
        """
        CREATE TABLE enrollments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            course_id INTEGER NOT NULL,
            enrolled_at TEXT NOT NULL
        );
        """,
        {
            "enrollments": [
                (1, 101, 201, "2024-01-01"),
                (2, 101, 202, "2024-01-02"),
                (3, 102, 201, "2024-01-03"),
            ],
        },
        migrations_version=1
    )

    # Test 11: drop_check_constraint
    create_test_db(
        "drop_check_constraint",
        """
        CREATE TABLE products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            price REAL NOT NULL,
            CONSTRAINT chk_price_positive CHECK (price > 0)
        );
        """,
        {
            "products": [
                (1, "Product A", 19.99),
                (2, "Product B", 29.99),
            ],
        },
        migrations_version=1
    )

    # Test 12: multiple_check_constraints
    create_test_db(
        "multiple_check_constraints",
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL,
            age INTEGER
        );
        """,
        {
            "users": [
                (1, "alice@test.com", 25),
                (2, "bob@test.com", 30),
            ],
        },
        migrations_version=1
    )

    # Test 13: complex_check_expression
    create_test_db(
        "complex_check_expression",
        """
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            total REAL NOT NULL,
            discount REAL NOT NULL DEFAULT 0
        );
        """,
        {
            "orders": [
                (1, 100.0, 10.0),
                (2, 200.0, 50.0),
            ],
        },
        migrations_version=1
    )

    # Test 14: foreign_key_plus_index_combo
    create_test_db(
        "foreign_key_plus_index_combo",
        """
        CREATE TABLE customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL
        );
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL,
            total REAL NOT NULL
        );
        """,
        {
            "customers": [
                (1, "Alice"),
                (2, "Bob"),
            ],
            "orders": [
                (1, 1, 100.0),
                (2, 1, 150.0),
                (3, 2, 200.0),
            ],
        },
        migrations_version=1
    )

    # Test 15: all_constraint_types_together
    create_test_db(
        "all_constraint_types_together",
        """
        CREATE TABLE accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_number TEXT NOT NULL
        );
        CREATE TABLE transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL,
            transaction_id TEXT NOT NULL,
            amount REAL NOT NULL
        );
        """,
        {
            "accounts": [
                (1, "ACC001"),
                (2, "ACC002"),
            ],
            "transactions": [
                (1, 1, "TXN001", 100.0),
                (2, 1, "TXN002", 50.0),
                (3, 2, "TXN003", 200.0),
            ],
        },
        migrations_version=1
    )

    # Test 16: drop_fk_then_add_new_fk
    create_test_db(
        "drop_fk_then_add_new_fk",
        """
        CREATE TABLE old_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL
        );
        CREATE TABLE new_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL
        );
        CREATE TABLE posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            CONSTRAINT fk_posts_old_user FOREIGN KEY (user_id) REFERENCES old_users(id)
        );
        """,
        {
            "old_users": [
                (1, "Alice"),
            ],
            "new_users": [
                (1, "Alice Updated"),
            ],
            "posts": [
                (1, 1, "Post 1"),
            ],
        },
        migrations_version=1
    )

    # Test 17: table_recreation_preserves_data
    create_test_db(
        "table_recreation_preserves_data",
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL
        );
        CREATE TABLE products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            CONSTRAINT fk_products_user_id FOREIGN KEY (user_id) REFERENCES users(id)
        );
        """,
        {
            "users": [(i, f"user{i}@test.com") for i in range(1, 101)],
            "products": [(i, (i % 100) + 1, f"Product {i}") for i in range(1, 151)],
        },
        migrations_version=1
    )

    # Test 18: empty_table_with_constraints
    create_test_db(
        "empty_table_with_constraints",
        """
        CREATE TABLE customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL
        );
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL,
            total REAL NOT NULL
        );
        """,
        {
            "customers": [
                (1, "Alice"),
            ],
        },
        migrations_version=1
    )

    # Test 19: nullable_foreign_key_column
    create_test_db(
        "nullable_foreign_key_column",
        """
        CREATE TABLE comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            parent_comment_id INTEGER
        );
        """,
        {
            "comments": [
                (1, "Top level comment", None),
                (2, "Reply to 1", 1),
                (3, "Another top level", None),
            ],
        },
        migrations_version=1
    )

    # Test 20: index_on_expression
    create_test_db(
        "index_on_expression",
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            first_name TEXT NOT NULL,
            last_name TEXT NOT NULL,
            email TEXT NOT NULL
        );
        """,
        {
            "users": [
                (1, "Alice", "Smith", "ALICE@TEST.COM"),
                (2, "Bob", "Jones", "BOB@TEST.COM"),
            ],
        },
        migrations_version=1
    )

    # Test 21: checkpoint1_2_3_combined
    create_test_db(
        "checkpoint1_2_3_combined",
        """
        """,
        {},
        migrations_version=0
    )

    # Test 22: data_migration_then_constraints
    create_test_db(
        "data_migration_then_constraints",
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT,
            age_text TEXT
        );
        """,
        {
            "users": [
                (1, "ALICE@TEST.COM", "25"),
                (2, "BOB@TEST.COM", "30"),
            ],
        },
        migrations_version=1
    )

    # Test 23: create_drop_column_with_fk
    create_test_db(
        "create_drop_column_with_fk",
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL
        );
        CREATE TABLE authors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL
        );
        CREATE TABLE posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            CONSTRAINT fk_posts_user_id FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        """,
        {
            "users": [
                (1, "Alice"),
                (2, "Bob"),
            ],
            "authors": [
                (1, "Alice Author", "alice@authors.com"),
                (2, "Bob Author", "bob@authors.com"),
            ],
            "posts": [
                (1, 1, "Post 1"),
                (2, 2, "Post 2"),
            ],
        },
        migrations_version=1
    )

    print("\n✓ All databases generated successfully!")


if __name__ == "__main__":
    main()
