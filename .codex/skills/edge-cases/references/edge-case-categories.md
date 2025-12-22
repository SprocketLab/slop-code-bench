# Common Edge Case Categories

Use this list while scanning specs for missing coverage.

- Empty/null inputs
- Boundary values (0, -1, MAX_INT, empty string)
- Malformed data (invalid JSON, wrong types)
- Missing required fields or args
- Unexpected types or extra fields
- State edge cases (duplicates, idempotency, retries)
- Format edge cases (unicode, special chars, whitespace-only)
- Very large inputs or outputs
- Concurrency or ordering issues (if applicable)
