# Spec Review Report: file_merger/checkpoint_4

## Checkpoint Summary

Checkpoint 4 adds nested type support (struct, array, map), type aliasing system, field path notation for keys/partitions, and canonical JSON serialization for CSV output. It tests whether agents can extend their checkpoint 3 implementation to handle complex schema definitions, recursive type casting, and path-based navigation while maintaining sorting and partitioning guarantees.

---

## Clarification Requests

1. **Partition-by with nested paths**: Spec mentions `--partition-by <fieldPath>` can use dot notation (line 12) but there are ZERO tests validating this. Is partitioning by nested paths required or future work?

2. **Map bracket syntax requirements**: Tests show `attrs["country"]` works but `attrs[country]` (no quotes) fails. Spec shows correct syntax but doesn't explicitly state unquoted keys are invalid. Should this be clarified?

3. **Sparse struct fields from input**: When JSONL input has a struct with subset of schema fields (e.g., schema defines `user.name` and `user.age` but input only has `user.name`), what happens? Tests suggest missing fields become `null` but spec doesn't state this explicitly.

4. **Invalid path syntax enumeration**: Spec describes valid syntax but doesn't list all invalid forms. Tests reject `items.[x].qty`, `items.-1.qty`, `attrs[country]`. Should spec enumerate invalid syntax patterns?

---

## Example Coverage Notes

**Logic Demonstrated by Tests (24 test cases):**
- Built-in type aliases (integer→int, text→string, list→array, json→struct, etc.)
- Custom type alias files with transitive resolution
- Alias cycle detection
- Unknown type detection
- Struct, array, map type definitions
- Field path keying: dot notation (`user.id`), array indices (`items.0.qty`), map lookups (`attrs["country"]`)
- Nested struct paths (`user.meta.last_login`)
- Array out-of-range handling (null key fragment)
- Map missing key handling (null value)
- JSON type accepting arbitrary values
- Recursive casting with on-type-error modes
- Canonical JSON output with struct field ordering and map key sorting
- UTC normalization in nested timestamps
- Invalid JSON in CSV cells
- Non-primitive key path rejection
- Nested structures without schema rejection
- Path syntax validation errors

**NOT Demonstrated by Tests:**
- **Partition-by with nested paths** (completely untested despite spec mention)
- Deep nesting (3+ levels) - only 2 levels tested
- JSON type nested inside arrays or structs (`array<json>`, struct with json field)
- Empty struct `{}` and empty map `{}` (empty array `[]` is tested)
- Timestamp as map value (nested temporal normalization)
- Mixed-case type aliases (spec says case-insensitive but tests use consistent casing)
- Map keys with special characters beyond non-ASCII

---

## Issues

## Line 168: Solution Leak

> External sort/merge, partitioning, stability, and exit codes/messages continue from prior checkpoints

**Recommended action:** REMOVE "External sort/merge"

**Rationale:** "External sort/merge" reveals the algorithm approach. This continues the solution leak from previous checkpoints. The spec should reference "performance requirements" or "memory constraints" not implementation techniques.

**Suggested replacement:**
> Sorting, partitioning, stability, memory limits, and exit codes/messages continue from prior checkpoints.

---

## Lines 104-114: Over-Spec (Canonical JSON Normalization Details)

> **Normalization & Output Encoding**
>
> - If entire column value is null → emit CSV null literal
> - Otherwise, serialize nested value as canonical JSON:
>   - Minified (no spaces), UTF-8, RFC 8259 JSON escaping
>   - Struct fields in schema-declared order
>   - Map keys sorted lexicographically
>   - Arrays preserve original element order after casting
>   - Timestamps inside nested values normalized to UTC `Z`; `date` stays `YYYY-MM-DD`
>   - All struct fields included (even when null) with explicit `null` values
> - This JSON is the CSV cell content for nested columns

**Recommended action:** CONDENSE OR MOVE-TO-EXAMPLE

**Rationale:** While canonical JSON rules are necessary for deterministic output validation, this level of detail reads like an implementation spec. Some rules could be demonstrated through test examples rather than enumerated in prose:
- "Minified (no spaces)" is an observable output requirement (OK to keep)
- "Struct fields in schema-declared order" is testable (OK to keep)
- "Map keys sorted lexicographically" is testable (OK to keep)
- "All struct fields included (even when null)" is an important invariant (OK to keep)

However, the list is very prescriptive. Consider condensing or grouping rules.

**Suggested condensation:**
> Nested values serialize as canonical JSON (minified, UTF-8, RFC 8259): struct fields in schema order, map keys sorted lexicographically, arrays in original order. Timestamps normalized to UTC Z; dates stay YYYY-MM-DD. Null fields explicitly included.

---

## Lines 118-126: Missing Information (Field Path Syntax Rules)

> **Keys & Partitioning with Nested**
>
> * Field paths traverse structs, use numeric indices into arrays, and map lookups with bracketed string keys
> * Examples: `user.id`, `items.0.qty`, `attrs["country"]`
> * Array indices must be non-negative integers
>   * If out of range or element is null/missing → key fragment is null for that row
> * Map lookups with `["key"]` read value by exact key
>   * If absent → null for that fragment

**Recommended action:** CLARIFY invalid syntax patterns

**Rationale:** Spec shows valid examples but doesn't enumerate invalid syntax. Tests reject:
- `items.[x].qty` (non-numeric index)
- `items.-1.qty` (negative index)
- `attrs[country]` (unquoted map key)

Line 120 states "Array indices must be non-negative integers" which covers negatives, but doesn't address:
- Whether map bracket syntax REQUIRES quotes
- Whether non-numeric indices like `[x]` are detected as syntax errors

**Suggested addition:**
> Map bracket syntax requires double-quoted string keys: `["key"]` not `[key]`. Array indices must be non-negative integer literals. Invalid syntax triggers error 2.

---

## Lines 19-22: Missing Information (Partition-by Testing Gap)

> * `--key` and `--partition-by` now accept **field paths** using dot notation (e.g., `user.id`, `items.0.sku`)
> * Paths must resolve to primitive types (`string`, `int`, `float`, `bool`, `date`, `timestamp`)
> * Referencing non-primitive (struct/array/map) in keys/partitions is error 3
> * Without `--schema`, nested inputs not allowed (error 6)

**Recommended action:** ADD TEST COVERAGE or CLARIFY scope

**Rationale:** Spec explicitly states `--partition-by` accepts field paths (line 12, line 19) and shows example at line 143 (`--partition-by attrs["country"]`). However, ZERO tests validate this functionality. Tests only cover `--key` with nested paths, not `--partition-by`.

This is a critical gap: either tests are missing or partition-by with nested paths isn't actually implemented for checkpoint 4.

**Options:**
1. Add test cases for `--partition-by user.id`, `--partition-by attrs["country"]`, etc.
2. Document that partition-by with nested paths is mentioned but deferred to testing
3. Remove partition-by examples if not tested

---

## Lines 80-82: Ambiguity (Alias Resolution Edge Cases)

> * Aliases apply after lowercasing names
> * May refer to built-ins or other aliases (resolve transitively; detect cycles → error 2)
> * Special alias `json`: when field declared as `"type":"json"`, accept any JSON value (object/array/primitive) and emit as JSON text

**Recommended action:** CLARIFY case-insensitive resolution

**Rationale:** Spec says "Aliases apply after lowercasing names" which means:
- Schema can have `"type": "INTEGER"` and it resolves to built-in `integer→int`
- Alias file can define `{"MyInt": "int"}` which becomes `myint→int`

Tests don't validate mixed-case aliases (all tests use lowercase or uppercase consistently). The behavior is clear from the rule but not demonstrated.

**Suggested approach:** Either add a test with mixed-case alias names or add an example in spec showing `"type": "INTEGER"` resolving to int.

---

## Lines 86-93: Missing Information (Sparse Struct Field Handling)

> **Input Handling for Nested**
>
> * **JSONL**: Accept nested objects/arrays only when schema declares column as nested or `json`
>   * If schema declares flat type but input has object/array, handle per `--on-type-error`
> * **Parquet**: Accept nested structs/lists/maps only when schema declares compatible nested types
>   * Without schema, nested triggers error 6
> * **CSV/TSV**: Cell must contain single JSON literal when target type is nested or `json`
>   * Empty cell → null
>   * Invalid JSON → handled per `--on-type-error`/error 5

**Recommended action:** CLARIFY incomplete struct behavior

**Rationale:** When JSONL input has a struct object missing fields compared to schema (e.g., schema defines `user:{name:string, age:int}` but input has `{"name":"Alice"}`), what happens?

Tests show the behavior: missing field becomes `null` in output JSON (`{"name":"Alice","age":null}`). However, spec doesn't explicitly state this. Line 113 says "All struct fields included (even when null)" which implies this, but it's about OUTPUT not INPUT handling.

**Suggested addition:**
> When input struct has subset of schema fields, missing fields are treated as null and explicitly included in output JSON.

---

## Lines 96-103: Over-Spec (Recursive Casting Details)

> **Casting & Validation**
>
> * Nested values cast recursively to declared types
> * On cast failure within nested structures:
>   * `coerce-null`: set field/element to JSON `null`
>   * `keep-string`: set to original unparsed JSON string or stringified form
>   * `fail`: emit `ERR 4 cannot cast "<val>" to <type> in field "<path>" (file=... line=...)`
> * For `json` type: accept any JSON value without casting; normalize only
> * Primitive casting rules, temporal normalization, null handling apply recursively inside nested values

**Recommended action:** KEEP but note detail level

**Rationale:** This section is detailed but necessary for deterministic grading. The error message format (line 100) is critical for test validation. However, line 99 "set to original unparsed JSON string or stringified form" is slightly vague - does "stringified form" mean something different from "original unparsed"?

Tests clarify: `keep-string` preserves the invalid JSON text as-is in the output. This is testable and OK to specify.

**Verdict:** Keep as-is. Detail is justified for error handling specification.

---

## Lines 160-168: Over-Spec (Determinism Checklist)

> **Determinism Checklist**
>
> * Alias resolution is case-insensitive, transitive, cycle-checked; unknown types error deterministically
> * Nested casting/normalization yields canonical JSON per ordering rules
> * CSV null literal applies only when entire cell is null
> * Dotted/bracketed field paths resolve to primitives or error 3
> * Without `--schema`, nested inputs rejected (error 6)
> * With `--schema`, Parquet/JSONL nesting must structurally match and cast recursively
> * External sort/merge, partitioning, stability, and exit codes/messages continue from prior checkpoints

**Recommended action:** REMOVE

**Rationale:** This is meta-commentary for spec authors, not agent instructions. It summarizes requirements already stated above. Line 168 contains a solution leak ("External sort/merge"). This section adds no new testable requirements.

---

## Lines 52-56: Missing Information (Type Definition Completeness)

> Supported nested kinds:
> * **struct**: ordered list of named fields (names unique within struct)
> * **array\<T>**: homogeneous element type T (can be nested)
> * **map\<string,T>**: string keys only; value type T can be nested or primitive

**Recommended action:** CLARIFY nesting depth limits and recursion

**Rationale:** Spec says types "can be nested" but doesn't specify:
- Maximum nesting depth (if any)
- Can you have `array<array<int>>`? (implied yes)
- Can you have `map<string,map<string,int>>`? (implied yes)
- Can you have `struct` with field of type `struct`? (tests show yes, depth 2)

Tests demonstrate 2-level nesting but not deeper. Spec could clarify there's no arbitrary limit or state a limit if one exists.

**Suggested addition:**
> Nested types can be arbitrarily composed: `array<struct<...>>`, `struct` containing `map<string,array<...>>`, etc.

---

## Lines 60-65: Over-Spec (Built-in Alias Enumeration)

> * Built-in aliases (always present):
>   * `integer`→`int`, `long`→`int`, `double`→`float`, `number`→`float`, `boolean`→`bool`
>   * `datetime`→`timestamp`, `timestamptz`→`timestamp`, `text`→`string`, `varchar`→`string`
>   * `list<T>`→`array<T>`
>   * `json`→`struct` (accept any JSON, see below)

**Recommended action:** KEEP (necessary for grading)

**Rationale:** While detailed, this list is essential for deterministic type resolution. Agents must know which aliases are built-in vs. requiring custom definition. This is observable behavior (tests validate these work), so it's appropriate to document.

**Verdict:** Keep as-is. This is a necessary interface specification.

---

## Missing from Spec: Empty Nested Structure Handling

**Test evidence:** Tests include empty array `[]` but not empty struct `{}` or empty map `{}`

**Recommended action:** CLARIFY OR ADD TEST COVERAGE

**Rationale:** What's the output for:
- Empty array: `[]` (tested - outputs as `[]`)
- Empty struct: `{}` (untested - outputs as `{}`?)
- Empty map: `{}` (untested - outputs as `{}`?)
- Null vs empty distinction

Spec doesn't address whether empty collections are allowed or how they're serialized.

**Suggested addition:**
> Empty arrays, structs, and maps are serialized as `[]`, `{}`, `{}` respectively. Null is distinct from empty.

---

## Missing from Spec: Non-ASCII Character Handling in JSON

**Test evidence:** Test case validates UTF-8 map key `\xE9` but spec only mentions "RFC 8259 JSON escaping"

**Recommended action:** ADD EXAMPLES

**Rationale:** "RFC 8259 JSON escaping" is correct but vague. Tests show non-ASCII characters work but spec doesn't provide examples. Agents might be uncertain whether to:
- Escape non-ASCII as `\uXXXX`
- Keep as UTF-8 bytes
- Use some other encoding

Tests clarify: UTF-8 bytes are used directly (not escaped to `\uXXXX`). Spec could show an example.

**Suggested addition:**
> Non-ASCII characters in JSON strings use UTF-8 encoding directly (not `\uXXXX` escape sequences). Map key sort order follows byte-wise lexicographic comparison.

---

## Missing from Spec: Path Not Found Error Message

**Test evidence:** `key_path_not_found.yaml` expects `ERR 3 key column "user.age" not present in resolved schema`

**Recommended action:** CLARIFY error message format

**Rationale:** Line 125 states "Otherwise: `ERR 3 key column "<path>" does not resolve to a primitive`" for non-primitive paths, but doesn't show error message for paths that don't exist at all (field not in schema).

Tests show both errors use code 3 but different messages:
- Non-primitive: "does not resolve to a primitive"
- Not found: "not present in resolved schema"

Spec should distinguish these or use consistent wording.

**Suggested clarification:**
> Field paths that don't exist in schema: `ERR 3 key column "<path>" not present in resolved schema`

---

## Lines 136-147: Command Examples

> **Examples**
>
> * Nested schema; key on nested leaf; partition by map value:
> * Accept arbitrary JSON in column while sorting by primitive field:

**Recommended action:** KEEP but note partition-by is untested

**Rationale:** Examples are helpful and don't reveal algorithm details. However, first example shows `--partition-by attrs["country"]` which is NOT tested. This creates false expectations if feature isn't implemented.

If partition-by with nested paths is removed from scope, update this example.

---

## Reviewer Checklist Results

- [ ] ❌ **No text describing algorithms or data structures** - FAILED: Line 168 mentions "External sort/merge"
- [x] ✅ **Every rule inferable from examples or a single invariant line** - MOSTLY: Map bracket quote requirement implicit; sparse struct behavior implicit
- [ ] ⚠️  **Clear, deterministic grading criteria** - NEEDS WORK: Invalid path syntax patterns not enumerated; sparse struct behavior not explicit
- [ ] ⚠️  **Examples cover normal, boundary, and failure modes** - PARTIAL: Good coverage but missing partition-by nested paths, deep nesting (3+), empty struct/map
- [x] ✅ **Later checkpoints build strictly on earlier outputs** - YES: Extends checkpoint 3's partitioned merger
- [ ] ❌ **No redundant or tutorial language** - FAILED: Lines 160-168 (Determinism Checklist)
- [ ] ❌ **All remaining text focuses on outcomes and observables** - FAILED: Line 168 describes implementation approach

---

## Summary of Recommended Actions

| Priority | Action | Line Range | Type |
|----------|--------|------------|------|
| **CRITICAL** | Add test coverage for partition-by with nested paths OR remove from spec | 12, 19, 143 | Missing Information |
| **HIGH** | Remove "External sort/merge" reference | 168 | Solution Leak |
| **HIGH** | Remove "Determinism Checklist" section | 160-168 | Over-Spec |
| **HIGH** | Clarify map bracket syntax requires quotes | 118-123 | Missing Information |
| **HIGH** | Clarify sparse struct field handling (missing fields → null) | 86-93 | Missing Information |
| **MEDIUM** | Add invalid path syntax enumeration | 118-126 | Missing Information |
| **MEDIUM** | Clarify path-not-found vs non-primitive error messages | 125 | Ambiguity |
| **MEDIUM** | Add examples of non-ASCII JSON handling | 108 | Missing Information |
| **MEDIUM** | Clarify nesting depth limits or lack thereof | 52-56 | Missing Information |
| **MEDIUM** | Condense canonical JSON normalization rules | 104-114 | Over-Spec |
| **LOW** | Add test coverage for deep nesting (3+ levels) | N/A | Missing Information |
| **LOW** | Add test coverage for empty struct `{}` and map `{}` | N/A | Missing Information |
| **LOW** | Add test coverage for mixed-case aliases | N/A | Missing Information |
| **LOW** | Clarify empty vs null for collections | N/A | Missing Information |

---

## Delta from Checkpoint 3

Checkpoint 4 adds:
- Nested type system (struct, array, map)
- Type aliasing with built-in and custom aliases
- Field path notation for keys/partitions (dot, array index, map bracket)
- Canonical JSON serialization for nested CSV cells
- Recursive type casting with path-aware error messages
- JSON type for flexible content acceptance
- Case-insensitive alias resolution with cycle detection
- Enhanced error messages with field paths

**Test Coverage:** 24 test cases provide strong coverage of nested types, aliases, and field paths. CRITICAL GAP: partition-by with nested paths mentioned in spec but completely untested.

**Critical Observation:** Spec continues "External sort/merge" solution leak. Partition-by feature described but not validated by tests. Canonical JSON rules are detailed and necessary but very prescriptive. Map bracket quote requirement and sparse struct handling are implicit, not explicit.