# Code Search Tool Specification

Build a command-line code searcher that finds patterns in source files using exact string matching, regular expressions, and structure-aware pattern matching with metavariables.

## Command Syntax

```bash
code_search <root_dir> --rules <rules_file> [--encoding <name>]
```

- `<root_dir>`: Directory to search recursively
- `--rules <rules_file>`: JSON file containing search rules
- `--encoding <name>`: File encoding (default: utf-8); skip files that fail to decode

## Supported Languages and Extensions

- **Python**: `.py`
- **JavaScript**: `.js`, `.mjs`, `.cjs`
- **C++**: `.cc`, `.cpp`, `.cxx`, `.hh`, `.hpp`, `.hxx`

## Rule Types

### 1. Exact Match
```json
{"id": "rule1", "kind": "exact", "pattern": "TODO:", "languages": ["python"]}
```

### 2. Regular Expression
```json
{"id": "rule2", "kind": "regex", "pattern": "print\\(.*\\)", "flags": "i"}
```

### 3. Pattern with Metavariables
```json
{"id": "rule3", "kind": "pattern", "pattern": "print($MSG)", "languages": ["python"]}
```

## Output Format

JSON Lines format (one match per line) to STDOUT:

```json
{"rule_id":"<id>","file":"<path>","language":"<lang>","start":{"line":<n>,"col":<n>},"end":{"line":<n>,"col":<n>},"match":"<text>","captures":{}}
```

The `captures` field is only present for pattern rules and contains metavariable bindings.

## Example 1

**Input file:** `example.py`
```python
# Line 1 starts here
print("hello")  # TODO: fix this
x = 10 + 20
```

**Rules:**
```json
[
  {"id": "r1", "kind": "exact", "pattern": "TODO:"},
  {"id": "r2", "kind": "regex", "pattern": "\\d+", "flags": ""}
]
```

**Output:**
```json
{"rule_id":"r1","file":"example.py","language":"python","start":{"line":2,"col":19},"end":{"line":2,"col":24},"match":"TODO:"}
{"rule_id":"r2","file":"example.py","language":"python","start":{"line":3,"col":5},"end":{"line":3,"col":7},"match":"10"}
{"rule_id":"r2","file":"example.py","language":"python","start":{"line":3,"col":10},"end":{"line":3,"col":12},"match":"20"}
```

**Column offset explanation:**
- Lines and columns are **1-based**
- Column 1 is the first character of a line
- The `end` position is **one position after** the last matched character
- For "TODO:" starting at column 19: start=19, end=24 (positions 19,20,21,22,23 are the 5 characters)
- Columns count Unicode characters correctly (emojis count as 1 position)

## Example 2: Multi-Language Support

**Files:**
- `main.py`: `print("Starting app")`
- `app.js`: `console.log("Hello");`
- `src/utils.cpp`: `std::cout << "Debug" << std::endl;`

**Rules:**
```json
[
  {"id": "py_only", "kind": "exact", "pattern": "print", "languages": ["python"]},
  {"id": "js_only", "kind": "regex", "pattern": "console\\.", "languages": ["javascript"]},
  {"id": "all_langs", "kind": "exact", "pattern": "\""}
]
```

**Output:**
```json
{"rule_id":"js_only","file":"app.js","language":"javascript","start":{"line":1,"col":1},"end":{"line":1,"col":9},"match":"console."}
{"rule_id":"all_langs","file":"app.js","language":"javascript","start":{"line":1,"col":13},"end":{"line":1,"col":14},"match":"\""}
{"rule_id":"all_langs","file":"app.js","language":"javascript","start":{"line":1,"col":19},"end":{"line":1,"col":20},"match":"\""}
{"rule_id":"py_only","file":"main.py","language":"python","start":{"line":1,"col":1},"end":{"line":1,"col":6},"match":"print"}
{"rule_id":"all_langs","file":"main.py","language":"python","start":{"line":1,"col":7},"end":{"line":1,"col":8},"match":"\""}
{"rule_id":"all_langs","file":"main.py","language":"python","start":{"line":1,"col":20},"end":{"line":1,"col":21},"match":"\""}
{"rule_id":"all_langs","file":"src/utils.cpp","language":"cpp","start":{"line":1,"col":14},"end":{"line":1,"col":15},"match":"\""}
{"rule_id":"all_langs","file":"src/utils.cpp","language":"cpp","start":{"line":1,"col":20},"end":{"line":1,"col":21},"match":"\""}
{"rule_id":"all_langs","file":"src/utils.cpp","language":"cpp","start":{"line":1,"col":22},"end":{"line":1,"col":23},"match":"\""}
{"rule_id":"all_langs","file":"src/utils.cpp","language":"cpp","start":{"line":1,"col":26},"end":{"line":1,"col":27},"match":"\""}
```

Note: When `languages` is omitted, the rule applies to all supported languages.

## Example 3: Pattern Matching with Metavariables

**Input file:** `code.py`
```python
print("Hello")
print(name)
result = add(x, y)
```

**Rules:**
```json
[
  {"id": "p1", "kind": "pattern", "pattern": "print($ARG)"},
  {"id": "p2", "kind": "pattern", "pattern": "$VAR = add($A, $B)"}
]
```

**Output:**
```json
{"rule_id":"p1","file":"code.py","language":"python","start":{"line":1,"col":1},"end":{"line":1,"col":15},"match":"print(\"Hello\")","captures":{"$ARG":{"text":"\"Hello\"","ranges":[{"start":{"line":1,"col":7},"end":{"line":1,"col":14}}]}}}
{"rule_id":"p1","file":"code.py","language":"python","start":{"line":2,"col":1},"end":{"line":2,"col":12},"match":"print(name)","captures":{"$ARG":{"text":"name","ranges":[{"start":{"line":2,"col":7},"end":{"line":2,"col":11}}]}}}
{"rule_id":"p2","file":"code.py","language":"python","start":{"line":3,"col":1},"end":{"line":3,"col":19},"match":"result = add(x, y)","captures":{"$A":{"text":"x","ranges":[{"start":{"line":3,"col":14},"end":{"line":3,"col":15}}]},"$B":{"text":"y","ranges":[{"start":{"line":3,"col":17},"end":{"line":3,"col":18}}]},"$VAR":{"text":"result","ranges":[{"start":{"line":3,"col":1},"end":{"line":3,"col":7}}]}}}
```

## Additional Functionality

### Regex Flags
- `i`: Case-insensitive matching
- `m`: Multiline mode (^ and $ match line boundaries)
- `s`: Dotall mode (. matches newlines)
- Flags can be combined: `"flags": "ims"`

### Metavariable Rules
- **Syntax**: `$IDENTIFIER` where IDENTIFIER matches `[A-Z_][A-Z0-9_]*`
- **Optional metavariables**: `$VAR?` matches zero or one occurrence
- **Repeated metavariables**: If `$X` appears multiple times in a pattern, all occurrences must match identical text
- **Escaped dollar**: `$$` in pattern matches literal `$` in source code
- **Matching scope**: A metavariable matches a complete syntactic element (identifier, expression, literal) appropriate for its position

### Pattern Matching Behavior
- Patterns must be syntactically valid code in the target language (with metavariables as placeholders)
- Matches are structure-aware, respecting language syntax
- Patterns can span multiple lines
- When multiple metavariables appear, each captures its matched text independently
- The `ranges` array in captures lists all positions where that metavariable appears within the match

### Output Ordering
Results are sorted by:
1. File path (lexicographic order, forward slashes)
2. Start line number
3. Start column number
4. End line number (for same start position)
5. End column number (for same start position)
6. Rule ID (lexicographic)

### File Processing
- Recursively search all files in root_dir
- Only process files with supported extensions
- Skip binary files and files that fail to decode
- File paths in output are relative to root_dir with forward slashes
- Exit with code 0 on success (even with zero matches)
- Exit with non-zero code on errors (invalid rules, missing files, etc.)

### Edge Cases
- Empty matches are valid (e.g., regex `^` matches start of lines)
- Matches inside comments and strings are included
- Overlapping matches from different rules are all reported
- For patterns, metavariables in the `captures` object are sorted lexicographically by name
- Pattern rules include captures field even when empty; exact/regex rules never include it