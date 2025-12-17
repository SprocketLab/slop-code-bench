# Checkpoint 2 Hidden Tests

This directory contains 20 comprehensive hidden tests for checkpoint_2 of the database_migration problem.

## Test Overview

### Category 1: NULL Handling (5 tests)
1. **null_source_column_migration** - Tests migrate_column_data with NULL values in source column (no default)
2. **null_migration_with_default** - Tests migrate_column_data with default_value for NULLs
3. **transform_null_concatenation** - Tests NULL propagation in concatenation expressions
4. **coalesce_null_handling** - Tests COALESCE to handle NULLs in transform expressions
5. **backfill_only_nulls** - Tests backfill with WHERE clause targeting only NULL rows

### Category 2: Complex SQL Expressions (5 tests)
6. **mathematical_transformations** - Tests mathematical expressions with REAL numbers
7. **case_statement_transformation** - Tests CASE statement for categorization
8. **string_functions_transform** - Tests SQLite string functions (UPPER, LOWER, SUBSTR, INSTR)
9. **nested_expressions** - Tests complex nested expressions combining multiple functions
10. **integer_division_and_modulo** - Tests integer math operations (division, modulo)

### Category 3: Multi-Operation Workflows (4 tests)
11. **add_transform_backfill_sequence** - Tests chaining multiple transform_data operations
12. **add_migrate_transform_sequence** - Tests migrate data then transform it
13. **multiple_tables_single_migration** - Tests operations on multiple tables in one migration
14. **all_three_new_operations_chained** - Tests all three new operations in sequence

### Category 4: Edge Cases (4 tests)
15. **empty_table_operations** - Tests operations on empty tables
16. **where_clause_no_matches** - Tests backfill with WHERE clause matching no rows
17. **large_dataset_migration** - Tests performance with 150 rows
18. **various_data_types** - Tests transformations with INTEGER, REAL, TEXT, BLOB types

### Category 5: Regression Tests (2 tests)
19. **checkpoint1_and_checkpoint2_mixed** - Tests mix of checkpoint 1 and 2 operations
20. **create_table_then_populate** - Tests create_table (checkpoint 1) then backfill (checkpoint 2)

## Test Structure

Each test directory contains:
- **app.db** - SQLite database with pre-populated schema and data
- **case.yaml** - Test configuration with inline migration JSON, input files, and expected status
- **expected.jsonl** - Expected JSONL output events
- **expected_db_content.yaml** - Expected database state after migration for verification

## Verifier Enhancements

The verifier has been enhanced to:
- Verify actual database content after migrations (not just JSONL output)
- Compare row data with expected values from `expected_db_content.yaml`
- Handle NULL values correctly
- Use float comparison tolerance for REAL types
- Provide detailed diff messages when verification fails

## Regenerating Tests

To regenerate all databases:
```bash
python3 generate_databases.py
```

To regenerate all test configuration files:
```bash
python3 generate_test_files.py
```

## Coverage

These tests provide comprehensive coverage of:
- ✓ NULL handling in all three new operations
- ✓ Complex SQL expressions (math, CASE, string functions, nested)
- ✓ Multi-operation workflows and chaining
- ✓ Edge cases (empty tables, no matches, large datasets, various types)
- ✓ Backward compatibility with checkpoint 1 operations

All tests are **success scenarios** (not error tests) with full data verification.
