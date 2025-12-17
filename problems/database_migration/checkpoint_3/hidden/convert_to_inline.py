#!/usr/bin/env python3
"""
Convert all checkpoint 3 hidden tests to use inline migrations instead of
pre-built app.db files.
"""

import json
from pathlib import Path


def create_case_yaml(test_name, setup_migrations, test_migration, expected_events):
    """
    Generate case.yaml content with inline migrations.

    Args:
        test_name: Name of the test directory
        setup_migrations: List of (version, description, operations) tuples for setup
        test_migration: (version, description, operations) tuple for the actual test
        expected_events: List of event dicts for expected.jsonl
    """
    input_files = []

    # Add setup migrations (v1, v2, etc.)
    for i, (version, description, operations) in enumerate(setup_migrations, 1):
        migration = {
            "version": version,
            "description": description,
            "operations": operations
        }
        input_files.append({
            "content": json.dumps(migration, indent=2),
            "file_type": "json",
            "path": f"migration_v{version}.json"
        })

    # Add test migration (final version)
    version, description, operations = test_migration
    migration = {
        "version": version,
        "description": description,
        "operations": operations
    }
    input_files.append({
        "content": json.dumps(migration, indent=2),
        "file_type": "json",
        "path": "migration.json"
    })

    case_yaml = """arguments: migrate migration.json app.db
input_files:
"""

    for input_file in input_files:
        # Properly indent each line of the JSON content
        json_lines = input_file['content'].split('\n')
        indented_json = '\n'.join('    ' + line for line in json_lines)

        case_yaml += f"""- content: |
{indented_json}
  file_type: {input_file['file_type']}
  path: {input_file['path']}
"""

    case_yaml += """tracked_files:
- app.db
expected_status: 0
"""

    return case_yaml


# Test 1: drop_foreign_key
def generate_drop_foreign_key():
    setup = [(1, "Initial schema with FK", [
        {"type": "create_table", "table": "users", "columns": [
            {"name": "id", "type": "INTEGER", "primary_key": True, "auto_increment": True},
            {"name": "email", "type": "TEXT", "not_null": True, "unique": True},
            {"name": "name", "type": "TEXT", "not_null": True}
        ]},
        {"type": "create_table", "table": "posts", "columns": [
            {"name": "id", "type": "INTEGER", "primary_key": True, "auto_increment": True},
            {"name": "user_id", "type": "INTEGER", "not_null": True},
            {"name": "title", "type": "TEXT", "not_null": True},
            {"name": "content", "type": "TEXT"}
        ]},
        {"type": "add_foreign_key", "table": "posts", "name": "fk_posts_user_id",
         "columns": ["user_id"], "references": {"table": "users", "columns": ["id"]},
         "on_delete": "CASCADE"}
    ])]

    test = (2, "Drop foreign key from posts table", [
        {"type": "drop_foreign_key", "table": "posts", "name": "fk_posts_user_id"}
    ])

    return create_case_yaml("drop_foreign_key", setup, test, None)


# Test 2: composite_foreign_key
def generate_composite_foreign_key():
    setup = [(1, "Create base tables", [
        {"type": "create_table", "table": "users", "columns": [
            {"name": "id", "type": "INTEGER", "primary_key": True, "auto_increment": True},
            {"name": "email", "type": "TEXT", "not_null": True, "unique": True}
        ]},
        {"type": "create_table", "table": "address_types", "columns": [
            {"name": "id", "type": "INTEGER", "primary_key": True, "auto_increment": True},
            {"name": "name", "type": "TEXT", "not_null": True, "unique": True}
        ]},
        {"type": "create_table", "table": "addresses", "columns": [
            {"name": "id", "type": "INTEGER", "primary_key": True, "auto_increment": True},
            {"name": "user_id", "type": "INTEGER", "not_null": True},
            {"name": "address_type_id", "type": "INTEGER", "not_null": True},
            {"name": "street", "type": "TEXT", "not_null": True},
            {"name": "city", "type": "TEXT", "not_null": True}
        ]}
    ])]

    test = (2, "Add composite foreign key to addresses table", [
        {"type": "add_foreign_key", "table": "addresses", "name": "fk_addresses_user_type",
         "columns": ["user_id", "address_type_id"],
         "references": {"table": "users", "columns": ["id", "id"]},
         "on_delete": "CASCADE"}
    ])

    return create_case_yaml("composite_foreign_key", setup, test, None)


# Test 3: multiple_foreign_keys_same_table
def generate_multiple_foreign_keys_same_table():
    setup = [(1, "Create base tables", [
        {"type": "create_table", "table": "departments", "columns": [
            {"name": "id", "type": "INTEGER", "primary_key": True, "auto_increment": True},
            {"name": "name", "type": "TEXT", "not_null": True, "unique": True}
        ]},
        {"type": "create_table", "table": "locations", "columns": [
            {"name": "id", "type": "INTEGER", "primary_key": True, "auto_increment": True},
            {"name": "city", "type": "TEXT", "not_null": True},
            {"name": "country", "type": "TEXT", "not_null": True}
        ]},
        {"type": "create_table", "table": "employees", "columns": [
            {"name": "id", "type": "INTEGER", "primary_key": True, "auto_increment": True},
            {"name": "name", "type": "TEXT", "not_null": True},
            {"name": "department_id", "type": "INTEGER", "not_null": True},
            {"name": "location_id", "type": "INTEGER", "not_null": True}
        ]}
    ])]

    test = (2, "Add multiple foreign keys to employees table", [
        {"type": "add_foreign_key", "table": "employees", "name": "fk_employees_department",
         "columns": ["department_id"], "references": {"table": "departments", "columns": ["id"]},
         "on_delete": "RESTRICT"},
        {"type": "add_foreign_key", "table": "employees", "name": "fk_employees_location",
         "columns": ["location_id"], "references": {"table": "locations", "columns": ["id"]},
         "on_delete": "RESTRICT"}
    ])

    return create_case_yaml("multiple_foreign_keys_same_table", setup, test, None)


# Test 4: foreign_key_set_null
def generate_foreign_key_set_null():
    setup = [(1, "Create base tables", [
        {"type": "create_table", "table": "categories", "columns": [
            {"name": "id", "type": "INTEGER", "primary_key": True, "auto_increment": True},
            {"name": "name", "type": "TEXT", "not_null": True, "unique": True}
        ]},
        {"type": "create_table", "table": "products", "columns": [
            {"name": "id", "type": "INTEGER", "primary_key": True, "auto_increment": True},
            {"name": "name", "type": "TEXT", "not_null": True},
            {"name": "category_id", "type": "INTEGER"}
        ]}
    ])]

    test = (2, "Add foreign key with SET NULL on_delete", [
        {"type": "add_foreign_key", "table": "products", "name": "fk_products_category",
         "columns": ["category_id"], "references": {"table": "categories", "columns": ["id"]},
         "on_delete": "SET NULL"}
    ])

    return create_case_yaml("foreign_key_set_null", setup, test, None)


# Test 5: foreign_key_set_default
def generate_foreign_key_set_default():
    setup = [(1, "Create base tables", [
        {"type": "create_table", "table": "statuses", "columns": [
            {"name": "id", "type": "INTEGER", "primary_key": True},
            {"name": "name", "type": "TEXT", "not_null": True, "unique": True}
        ]},
        {"type": "create_table", "table": "tasks", "columns": [
            {"name": "id", "type": "INTEGER", "primary_key": True, "auto_increment": True},
            {"name": "title", "type": "TEXT", "not_null": True},
            {"name": "status_id", "type": "INTEGER", "default": "1", "not_null": True}
        ]}
    ])]

    test = (2, "Add foreign key with SET DEFAULT on_delete", [
        {"type": "add_foreign_key", "table": "tasks", "name": "fk_tasks_status",
         "columns": ["status_id"], "references": {"table": "statuses", "columns": ["id"]},
         "on_delete": "SET DEFAULT"}
    ])

    return create_case_yaml("foreign_key_set_default", setup, test, None)


# Test 6: self_referential_foreign_key
def generate_self_referential_foreign_key():
    setup = [(1, "Create employees table", [
        {"type": "create_table", "table": "employees", "columns": [
            {"name": "id", "type": "INTEGER", "primary_key": True, "auto_increment": True},
            {"name": "name", "type": "TEXT", "not_null": True},
            {"name": "manager_id", "type": "INTEGER"}
        ]}
    ])]

    test = (2, "Add self-referential foreign key for employees hierarchy", [
        {"type": "add_foreign_key", "table": "employees", "name": "fk_employees_manager",
         "columns": ["manager_id"], "references": {"table": "employees", "columns": ["id"]},
         "on_delete": "SET NULL"}
    ])

    return create_case_yaml("self_referential_foreign_key", setup, test, None)


# Test 7: drop_index
def generate_drop_index():
    setup = [(1, "Create table with index", [
        {"type": "create_table", "table": "users", "columns": [
            {"name": "id", "type": "INTEGER", "primary_key": True, "auto_increment": True},
            {"name": "email", "type": "TEXT", "not_null": True, "unique": True},
            {"name": "name", "type": "TEXT", "not_null": True}
        ]},
        {"type": "create_index", "name": "idx_users_name", "table": "users",
         "columns": ["name"], "unique": False}
    ])]

    test = (2, "Drop index from users table", [
        {"type": "drop_index", "name": "idx_users_name"}
    ])

    return create_case_yaml("drop_index", setup, test, None)


# Test 8: unique_index
def generate_unique_index():
    setup = [(1, "Create products table", [
        {"type": "create_table", "table": "products", "columns": [
            {"name": "id", "type": "INTEGER", "primary_key": True, "auto_increment": True},
            {"name": "name", "type": "TEXT", "not_null": True},
            {"name": "sku", "type": "TEXT", "not_null": True}
        ]}
    ])]

    test = (2, "Create unique index on SKU column", [
        {"type": "create_index", "name": "idx_products_sku", "table": "products",
         "columns": ["sku"], "unique": True}
    ])

    return create_case_yaml("unique_index", setup, test, None)


# Test 9: unique_index_with_nulls
def generate_unique_index_with_nulls():
    setup = [(1, "Create users table", [
        {"type": "create_table", "table": "users", "columns": [
            {"name": "id", "type": "INTEGER", "primary_key": True, "auto_increment": True},
            {"name": "email", "type": "TEXT", "not_null": True, "unique": True},
            {"name": "social_security_number", "type": "TEXT"}
        ]}
    ])]

    test = (2, "Create unique index on SSN allowing multiple NULLs", [
        {"type": "create_index", "name": "idx_users_ssn", "table": "users",
         "columns": ["social_security_number"], "unique": True}
    ])

    return create_case_yaml("unique_index_with_nulls", setup, test, None)


# Test 10: multi_column_unique_index
def generate_multi_column_unique_index():
    setup = [(1, "Create enrollment tables", [
        {"type": "create_table", "table": "students", "columns": [
            {"name": "id", "type": "INTEGER", "primary_key": True, "auto_increment": True},
            {"name": "name", "type": "TEXT", "not_null": True}
        ]},
        {"type": "create_table", "table": "courses", "columns": [
            {"name": "id", "type": "INTEGER", "primary_key": True, "auto_increment": True},
            {"name": "name", "type": "TEXT", "not_null": True}
        ]},
        {"type": "create_table", "table": "enrollments", "columns": [
            {"name": "id", "type": "INTEGER", "primary_key": True, "auto_increment": True},
            {"name": "student_id", "type": "INTEGER", "not_null": True},
            {"name": "course_id", "type": "INTEGER", "not_null": True}
        ]}
    ])]

    test = (2, "Create composite unique index on student-course pair", [
        {"type": "create_index", "name": "idx_enrollments_student_course", "table": "enrollments",
         "columns": ["student_id", "course_id"], "unique": True}
    ])

    return create_case_yaml("multi_column_unique_index", setup, test, None)


# Test 11: drop_check_constraint
def generate_drop_check_constraint():
    setup = [(1, "Create table with check constraint", [
        {"type": "create_table", "table": "products", "columns": [
            {"name": "id", "type": "INTEGER", "primary_key": True, "auto_increment": True},
            {"name": "name", "type": "TEXT", "not_null": True},
            {"name": "price", "type": "REAL", "not_null": True}
        ]},
        {"type": "add_check_constraint", "table": "products", "name": "chk_price_positive",
         "expression": "price > 0"}
    ])]

    test = (2, "Drop check constraint from products table", [
        {"type": "drop_check_constraint", "table": "products", "name": "chk_price_positive"}
    ])

    return create_case_yaml("drop_check_constraint", setup, test, None)


# Test 12: multiple_check_constraints
def generate_multiple_check_constraints():
    setup = [(1, "Create users table", [
        {"type": "create_table", "table": "users", "columns": [
            {"name": "id", "type": "INTEGER", "primary_key": True, "auto_increment": True},
            {"name": "email", "type": "TEXT", "not_null": True},
            {"name": "age", "type": "INTEGER", "not_null": True}
        ]}
    ])]

    test = (2, "Add multiple check constraints to users table", [
        {"type": "add_check_constraint", "table": "users", "name": "chk_users_age",
         "expression": "age >= 0 AND age <= 150"},
        {"type": "add_check_constraint", "table": "users", "name": "chk_users_email",
         "expression": "email LIKE '%@%'"}
    ])

    return create_case_yaml("multiple_check_constraints", setup, test, None)


# Test 13: complex_check_expression
def generate_complex_check_expression():
    setup = [(1, "Create orders table", [
        {"type": "create_table", "table": "orders", "columns": [
            {"name": "id", "type": "INTEGER", "primary_key": True, "auto_increment": True},
            {"name": "total", "type": "REAL", "not_null": True},
            {"name": "discount", "type": "REAL", "not_null": True, "default": "0"}
        ]}
    ])]

    test = (2, "Add check constraint with complex expression", [
        {"type": "add_check_constraint", "table": "orders", "name": "chk_orders_discount",
         "expression": "discount <= total * 0.5"}
    ])

    return create_case_yaml("complex_check_expression", setup, test, None)


# Test 14: foreign_key_plus_index_combo
def generate_foreign_key_plus_index_combo():
    setup = [(1, "Create base tables", [
        {"type": "create_table", "table": "customers", "columns": [
            {"name": "id", "type": "INTEGER", "primary_key": True, "auto_increment": True},
            {"name": "name", "type": "TEXT", "not_null": True}
        ]},
        {"type": "create_table", "table": "orders", "columns": [
            {"name": "id", "type": "INTEGER", "primary_key": True, "auto_increment": True},
            {"name": "customer_id", "type": "INTEGER", "not_null": True},
            {"name": "total", "type": "REAL", "not_null": True}
        ]}
    ])]

    test = (2, "Add foreign key and index on customer_id", [
        {"type": "add_foreign_key", "table": "orders", "name": "fk_orders_customer",
         "columns": ["customer_id"], "references": {"table": "customers", "columns": ["id"]},
         "on_delete": "CASCADE"},
        {"type": "create_index", "name": "idx_orders_customer", "table": "orders",
         "columns": ["customer_id"], "unique": False}
    ])

    return create_case_yaml("foreign_key_plus_index_combo", setup, test, None)


# Test 15: all_constraint_types_together
def generate_all_constraint_types_together():
    setup = [(1, "Create base tables", [
        {"type": "create_table", "table": "accounts", "columns": [
            {"name": "id", "type": "INTEGER", "primary_key": True, "auto_increment": True},
            {"name": "account_number", "type": "TEXT", "not_null": True, "unique": True}
        ]},
        {"type": "create_table", "table": "transactions", "columns": [
            {"name": "id", "type": "INTEGER", "primary_key": True, "auto_increment": True},
            {"name": "account_id", "type": "INTEGER", "not_null": True},
            {"name": "transaction_id", "type": "TEXT", "not_null": True},
            {"name": "amount", "type": "REAL", "not_null": True}
        ]}
    ])]

    test = (2, "Add FK, unique index, and check constraint", [
        {"type": "add_foreign_key", "table": "transactions", "name": "fk_transactions_account",
         "columns": ["account_id"], "references": {"table": "accounts", "columns": ["id"]},
         "on_delete": "CASCADE"},
        {"type": "create_index", "name": "idx_transactions_txn_id", "table": "transactions",
         "columns": ["transaction_id"], "unique": True},
        {"type": "add_check_constraint", "table": "transactions", "name": "chk_transactions_amount",
         "expression": "amount > 0"}
    ])

    return create_case_yaml("all_constraint_types_together", setup, test, None)


# Test 16: drop_fk_then_add_new_fk
def generate_drop_fk_then_add_new_fk():
    setup = [(1, "Create base tables with FK", [
        {"type": "create_table", "table": "old_users", "columns": [
            {"name": "id", "type": "INTEGER", "primary_key": True, "auto_increment": True},
            {"name": "name", "type": "TEXT", "not_null": True}
        ]},
        {"type": "create_table", "table": "new_users", "columns": [
            {"name": "id", "type": "INTEGER", "primary_key": True, "auto_increment": True},
            {"name": "name", "type": "TEXT", "not_null": True},
            {"name": "email", "type": "TEXT", "not_null": True}
        ]},
        {"type": "create_table", "table": "posts", "columns": [
            {"name": "id", "type": "INTEGER", "primary_key": True, "auto_increment": True},
            {"name": "user_id", "type": "INTEGER", "not_null": True},
            {"name": "title", "type": "TEXT", "not_null": True}
        ]},
        {"type": "add_foreign_key", "table": "posts", "name": "fk_posts_user_id",
         "columns": ["user_id"], "references": {"table": "old_users", "columns": ["id"]}}
    ])]

    test = (2, "Replace FK from old_users to new_users", [
        {"type": "drop_foreign_key", "table": "posts", "name": "fk_posts_user_id"},
        {"type": "add_foreign_key", "table": "posts", "name": "fk_posts_new_user_id",
         "columns": ["user_id"], "references": {"table": "new_users", "columns": ["id"]},
         "on_delete": "CASCADE"}
    ])

    return create_case_yaml("drop_fk_then_add_new_fk", setup, test, None)


# Test 17: table_recreation_preserves_data
def generate_table_recreation_preserves_data():
    setup = [(1, "Create tables with FK and data", [
        {"type": "create_table", "table": "categories", "columns": [
            {"name": "id", "type": "INTEGER", "primary_key": True, "auto_increment": True},
            {"name": "name", "type": "TEXT", "not_null": True}
        ]},
        {"type": "create_table", "table": "products", "columns": [
            {"name": "id", "type": "INTEGER", "primary_key": True, "auto_increment": True},
            {"name": "name", "type": "TEXT", "not_null": True},
            {"name": "price", "type": "REAL", "not_null": True},
            {"name": "category_id", "type": "INTEGER", "not_null": True},
            {"name": "description", "type": "TEXT"}
        ]},
        {"type": "add_foreign_key", "table": "products", "name": "fk_products_category_id",
         "columns": ["category_id"], "references": {"table": "categories", "columns": ["id"]}}
    ])]

    test = (2, "Drop FK to verify data preservation during table recreation", [
        {"type": "drop_foreign_key", "table": "products", "name": "fk_products_category_id"}
    ])

    return create_case_yaml("table_recreation_preserves_data", setup, test, None)


# Test 18: empty_table_with_constraints
def generate_empty_table_with_constraints():
    setup = [(1, "Create empty tables", [
        {"type": "create_table", "table": "customers", "columns": [
            {"name": "id", "type": "INTEGER", "primary_key": True, "auto_increment": True},
            {"name": "name", "type": "TEXT", "not_null": True}
        ]},
        {"type": "create_table", "table": "orders", "columns": [
            {"name": "id", "type": "INTEGER", "primary_key": True, "auto_increment": True},
            {"name": "customer_id", "type": "INTEGER", "not_null": True},
            {"name": "total", "type": "REAL", "not_null": True},
            {"name": "status", "type": "TEXT", "not_null": True}
        ]}
    ])]

    test = (2, "Add constraints to empty orders table", [
        {"type": "add_foreign_key", "table": "orders", "name": "fk_orders_customer",
         "columns": ["customer_id"], "references": {"table": "customers", "columns": ["id"]},
         "on_delete": "CASCADE"},
        {"type": "create_index", "name": "idx_orders_customer", "table": "orders",
         "columns": ["customer_id"], "unique": False},
        {"type": "add_check_constraint", "table": "orders", "name": "chk_orders_total",
         "expression": "total > 0"}
    ])

    return create_case_yaml("empty_table_with_constraints", setup, test, None)


# Test 19: nullable_foreign_key_column
def generate_nullable_foreign_key_column():
    setup = [(1, "Create comments table", [
        {"type": "create_table", "table": "comments", "columns": [
            {"name": "id", "type": "INTEGER", "primary_key": True, "auto_increment": True},
            {"name": "content", "type": "TEXT", "not_null": True},
            {"name": "parent_comment_id", "type": "INTEGER"}
        ]}
    ])]

    test = (2, "Add self-referential FK on nullable parent_comment_id", [
        {"type": "add_foreign_key", "table": "comments", "name": "fk_comments_parent",
         "columns": ["parent_comment_id"], "references": {"table": "comments", "columns": ["id"]},
         "on_delete": "CASCADE"}
    ])

    return create_case_yaml("nullable_foreign_key_column", setup, test, None)


# Test 20: index_on_expression
def generate_index_on_expression():
    setup = [(1, "Create users table", [
        {"type": "create_table", "table": "users", "columns": [
            {"name": "id", "type": "INTEGER", "primary_key": True, "auto_increment": True},
            {"name": "first_name", "type": "TEXT", "not_null": True},
            {"name": "last_name", "type": "TEXT", "not_null": True},
            {"name": "email", "type": "TEXT", "not_null": True}
        ]}
    ])]

    test = (2, "Create index on email for case-insensitive lookups", [
        {"type": "create_index", "name": "idx_users_email_lower", "table": "users",
         "columns": ["email"], "unique": False}
    ])

    return create_case_yaml("index_on_expression", setup, test, None)


# Test 21: checkpoint1_2_3_combined
def generate_checkpoint1_2_3_combined():
    setup = []

    test = (1, "Complete migration across all three checkpoints", [
        {"type": "create_table", "table": "users", "columns": [
            {"name": "id", "type": "INTEGER", "primary_key": True, "auto_increment": True},
            {"name": "name", "type": "TEXT", "not_null": True},
            {"name": "age_text", "type": "TEXT"}
        ]},
        {"type": "add_column", "table": "users", "column": {"name": "age", "type": "INTEGER"}},
        {"type": "transform_column_data", "table": "users", "column": "age",
         "expression": "CAST(age_text AS INTEGER)"},
        {"type": "drop_column", "table": "users", "column": "age_text"},
        {"type": "create_table", "table": "posts", "columns": [
            {"name": "id", "type": "INTEGER", "primary_key": True, "auto_increment": True},
            {"name": "user_id", "type": "INTEGER", "not_null": True},
            {"name": "title", "type": "TEXT", "not_null": True}
        ]},
        {"type": "add_foreign_key", "table": "posts", "name": "fk_posts_user",
         "columns": ["user_id"], "references": {"table": "users", "columns": ["id"]},
         "on_delete": "CASCADE"},
        {"type": "create_index", "name": "idx_posts_user", "table": "posts",
         "columns": ["user_id"], "unique": False},
        {"type": "add_check_constraint", "table": "users", "name": "chk_users_age",
         "expression": "age >= 0 AND age <= 150"}
    ])

    return create_case_yaml("checkpoint1_2_3_combined", setup, test, None)


# Test 22: data_migration_then_constraints
def generate_data_migration_then_constraints():
    setup = [(1, "Create users table with messy data", [
        {"type": "create_table", "table": "users", "columns": [
            {"name": "id", "type": "INTEGER", "primary_key": True, "auto_increment": True},
            {"name": "email", "type": "TEXT"},
            {"name": "age_text", "type": "TEXT"}
        ]}
    ])]

    test = (2, "Transform data then add constraints", [
        {"type": "add_column", "table": "users", "column": {"name": "age", "type": "INTEGER"}},
        {"type": "transform_column_data", "table": "users", "column": "age",
         "expression": "CAST(age_text AS INTEGER)"},
        {"type": "transform_column_data", "table": "users", "column": "email",
         "expression": "LOWER(email)"},
        {"type": "drop_column", "table": "users", "column": "age_text"},
        {"type": "add_check_constraint", "table": "users", "name": "chk_users_age",
         "expression": "age >= 18 AND age <= 100"},
        {"type": "add_check_constraint", "table": "users", "name": "chk_users_email",
         "expression": "email LIKE '%@%'"}
    ])

    return create_case_yaml("data_migration_then_constraints", setup, test, None)


# Test 23: create_drop_column_with_fk
def generate_create_drop_column_with_fk():
    setup = [(1, "Create tables with FK", [
        {"type": "create_table", "table": "users", "columns": [
            {"name": "id", "type": "INTEGER", "primary_key": True, "auto_increment": True},
            {"name": "name", "type": "TEXT", "not_null": True}
        ]},
        {"type": "create_table", "table": "authors", "columns": [
            {"name": "id", "type": "INTEGER", "primary_key": True, "auto_increment": True},
            {"name": "name", "type": "TEXT", "not_null": True},
            {"name": "email", "type": "TEXT", "not_null": True}
        ]},
        {"type": "create_table", "table": "posts", "columns": [
            {"name": "id", "type": "INTEGER", "primary_key": True, "auto_increment": True},
            {"name": "user_id", "type": "INTEGER", "not_null": True},
            {"name": "title", "type": "TEXT", "not_null": True}
        ]},
        {"type": "add_foreign_key", "table": "posts", "name": "fk_posts_user_id",
         "columns": ["user_id"], "references": {"table": "users", "columns": ["id"]}}
    ])]

    test = (2, "Complex schema evolution: drop FK, drop column, add new column with new FK", [
        {"type": "drop_foreign_key", "table": "posts", "name": "fk_posts_user_id"},
        {"type": "drop_column", "table": "posts", "column": "user_id"},
        {"type": "add_column", "table": "posts", "column":
         {"name": "author_id", "type": "INTEGER", "not_null": True, "default": "1"}},
        {"type": "migrate_column_data", "table": "posts", "from_column": "id", "to_column": "author_id"},
        {"type": "add_foreign_key", "table": "posts", "name": "fk_posts_author",
         "columns": ["author_id"], "references": {"table": "authors", "columns": ["id"]},
         "on_delete": "CASCADE"}
    ])

    return create_case_yaml("create_drop_column_with_fk", setup, test, None)


def main():
    """Generate all case.yaml files."""
    base_path = Path(__file__).parent

    generators = [
        ("drop_foreign_key", generate_drop_foreign_key),
        ("composite_foreign_key", generate_composite_foreign_key),
        ("multiple_foreign_keys_same_table", generate_multiple_foreign_keys_same_table),
        ("foreign_key_set_null", generate_foreign_key_set_null),
        ("foreign_key_set_default", generate_foreign_key_set_default),
        ("self_referential_foreign_key", generate_self_referential_foreign_key),
        ("drop_index", generate_drop_index),
        ("unique_index", generate_unique_index),
        ("unique_index_with_nulls", generate_unique_index_with_nulls),
        ("multi_column_unique_index", generate_multi_column_unique_index),
        ("drop_check_constraint", generate_drop_check_constraint),
        ("multiple_check_constraints", generate_multiple_check_constraints),
        ("complex_check_expression", generate_complex_check_expression),
        ("foreign_key_plus_index_combo", generate_foreign_key_plus_index_combo),
        ("all_constraint_types_together", generate_all_constraint_types_together),
        ("drop_fk_then_add_new_fk", generate_drop_fk_then_add_new_fk),
        ("table_recreation_preserves_data", generate_table_recreation_preserves_data),
        ("empty_table_with_constraints", generate_empty_table_with_constraints),
        ("nullable_foreign_key_column", generate_nullable_foreign_key_column),
        ("index_on_expression", generate_index_on_expression),
        ("checkpoint1_2_3_combined", generate_checkpoint1_2_3_combined),
        ("data_migration_then_constraints", generate_data_migration_then_constraints),
        ("create_drop_column_with_fk", generate_create_drop_column_with_fk),
    ]

    for test_name, generator in generators:
        case_yaml = generator()
        case_path = base_path / test_name / "case.yaml"
        case_path.write_text(case_yaml)
        print(f"✓ Updated {test_name}/case.yaml")

    print("\n✓ All 23 case.yaml files updated to use inline migrations!")
    print("Note: app.db files are no longer needed and can be deleted.")


if __name__ == "__main__":
    main()
