# Edge Case Patterns

Reference for common edge cases by problem type.

## Table of Contents

- CLI Tools
  - Input Edge Cases
  - File Input Edge Cases
  - Output Edge Cases
- API Servers
  - Request Edge Cases
  - Response Edge Cases
  - State Edge Cases
- Data Processing
  - Input Data Edge Cases
  - Numeric Edge Cases
  - String Edge Cases
- File Operations
  - Path Edge Cases
  - Operation Edge Cases
- Database / Storage
  - Query Edge Cases
  - Transaction Edge Cases
- Time / Date
  - Temporal Edge Cases
- Authentication / Authorization
  - Auth Edge Cases
- Checklist Template
- Problem-Specific Patterns
  - eve_jump_planner (Route Finding)
  - execution_server (Code Execution)

---

## CLI Tools

### Input Edge Cases
- Empty arguments: `tool` (no args)
- Missing required args: `tool --optional-only`
- Invalid flag: `tool --nonexistent`
- Conflicting flags: `tool --verbose --quiet`
- Duplicate flags: `tool --flag --flag`
- Empty string argument: `tool --input ""`
- Whitespace-only: `tool --input "   "`

### File Input Edge Cases
- Missing file: `tool nonexistent.txt`
- Empty file: `tool empty.txt`
- Directory instead of file: `tool ./some_dir/`
- Permission denied: `tool /root/secret.txt`
- Binary file when text expected
- Very large file
- File with no newline at end
- File with only newlines

### Output Edge Cases
- Stdout vs stderr separation
- Exit codes (0 success, non-zero failure)
- JSON output validity
- Newline handling in output

---

## API Servers

### Request Edge Cases
- Empty request body: `POST /endpoint` with `{}`
- Missing required fields
- Extra unexpected fields (should ignore or error?)
- Wrong content-type header
- Malformed JSON body
- Very large request body
- Unicode in request fields

### Response Edge Cases
- Correct status codes (201 created, 400 bad request, 404 not found)
- Response content-type header
- Error response format consistency
- Empty response body when appropriate

### State Edge Cases
- Duplicate creation (POST same item twice)
- Update non-existent resource
- Delete non-existent resource
- Delete already deleted resource
- Concurrent modifications

---

## Data Processing

### Input Data Edge Cases
- Empty dataset: `[]`
- Single item: `[{"one": "item"}]`
- Duplicate items
- Null values in data
- Missing optional fields
- Wrong types (string where number expected)

### Numeric Edge Cases
- Zero: `0`
- Negative: `-1`, `-999`
- Very large: `999999999999`
- Float precision: `0.1 + 0.2`
- Infinity, NaN (if applicable)
- Integer overflow (if applicable)

### String Edge Cases
- Empty string: `""`
- Whitespace only: `"   "`, `"\t\n"`
- Unicode: `"日本語"`, `"émoji 🎉"`
- Special characters: `"<>&\"'"`
- Very long string: `"a" * 10000`
- Null bytes: `"hello\x00world"`
- Newlines in string: `"line1\nline2"`

---

## File Operations

### Path Edge Cases
- Relative vs absolute paths
- Paths with spaces: `"my file.txt"`
- Paths with special chars: `"file[1].txt"`
- Very long paths
- Symlinks (follow or not?)
- Hidden files: `.hidden`

### Operation Edge Cases
- Write to read-only location
- Read from write-only
- Disk full scenario
- File locked by another process
- Partial write (interrupted)

---

## Database / Storage

### Query Edge Cases
- Empty result set
- Single result
- Very large result set
- NULL values in results
- Special characters in queries (SQL injection prevention)

### Transaction Edge Cases
- Concurrent writes
- Deadlock scenarios
- Rollback on error
- Partial failure in batch operations

---

## Time / Date

### Temporal Edge Cases
- Epoch: `1970-01-01`
- Far future: `2099-12-31`
- Leap year: `2024-02-29`
- Invalid date: `2023-02-29`
- Timezone handling
- Daylight saving transitions
- Midnight: `00:00:00` vs `24:00:00`

---

## Authentication / Authorization

### Auth Edge Cases
- Missing auth header
- Invalid/expired token
- Malformed token
- Wrong permissions (403 vs 401)
- Token with extra/missing claims

---

## Checklist Template

Copy this for each checkpoint analysis:

```markdown
### Checkpoint N Edge Case Review

**Spec requirements checked:**
- [ ] Requirement 1 - edge cases: ___
- [ ] Requirement 2 - edge cases: ___

**Input edge cases:**
- [ ] Empty input
- [ ] Missing required fields
- [ ] Invalid types
- [ ] Boundary values

**Error handling:**
- [ ] All error conditions from spec tested
- [ ] Error messages/codes verified
- [ ] Graceful failure (no crashes)

**Format edge cases:**
- [ ] Unicode input/output
- [ ] Special characters
- [ ] Large inputs

**State edge cases (if applicable):**
- [ ] Concurrent operations
- [ ] Duplicate handling
- [ ] Order independence
```

---

## Problem-Specific Patterns

### eve_jump_planner (Route Finding)
- Source = destination
- Invalid system names
- Disconnected systems
- Very long routes
- Route through dangerous systems

### execution_server (Code Execution)
- Empty command
- Command timeout
- Command with special shell chars
- Very long output
- Binary output
- Infinite loop command

### file_query_tool (Data Query)
- Empty CSV files
- Malformed CSV (wrong columns)
- Query on non-existent column
- Query returning no results
- Case sensitivity in queries

### log_query (Log Analysis)
- Empty log files
- Malformed log lines
- Timestamp parsing edge cases
- Regex special characters in queries
- Very large log files
