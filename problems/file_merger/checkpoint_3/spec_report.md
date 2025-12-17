# Spec Review Report: file_merger/checkpoint_3

## Checkpoint Summary

Checkpoint 3 adds partitioned output capabilities: Hive-style field partitioning with directory hierarchies, row-based and byte-based file sharding, and the ability to combine both. It tests whether agents can extend their checkpoint 2 implementation to handle output organization, multi-file writes, and maintain sorting guarantees across partitioned datasets.

---

## Clarification Requests

1. **Multi-column partition directory nesting order**: When `--partition-by a,b` is specified, is the directory structure `a=X/b=Y/` or determined by some other rule (alphabetical, schema order)? Tests show flag order determines nesting, but spec doesn't state this.

2. **Byte calculation method**: "On-disk byte size" (line 57) doesn't define whether to count CRLF vs LF, quote characters, CSV escaping. How should agents calculate file size for `--max-bytes-per-file`?

3. **Character encoding safety set**: Spec says `[A-Za-z0-9._-]` are safe (line 47), implying everything else gets percent-encoded. Tests show `+` is encoded. Should spec list common unsafe characters explicitly or is the safe set exhaustive?

4. **Error code for missing partition column**: Tests expect error code 3 and specific message format when partition column isn't in schema, but spec doesn't document this error condition.

---

## Example Coverage Notes

**Logic Demonstrated by Tests (11 test cases):**
- Single-column field partitioning (Hive-style directories)
- Multi-column hierarchical partitioning
- Partition value percent-encoding (space, slash, UTF-8 multi-byte, plus sign)
- Null partition values (`_null` literal)
- Row-based sharding (`--max-rows-per-file`)
- Byte-based sharding (`--max-bytes-per-file`)
- Combined row + byte limits
- Combined field partitioning + sharding
- Descending sort within partitions
- Error: stdout with partitioning
- Error: missing partition column

**NOT Demonstrated by Tests:**
- Single row exceeding `--max-bytes-per-file` limit (exception mentioned in spec line 58)
- Byte limit hit before row limit (all tests hit row limit first)
- Multiple partitions each containing multiple sharded files (only single partition with sharding tested)
- Atomic write failure and cleanup (spec mentions temp directory cleanup on line 39 but not tested)
- Comprehensive character encoding (only space, slash, UTF-8, plus tested)
- File header validation across all output files

---

## Issues

## Lines 38-39: Solution Leak

> - Perform atomic write by creating sibling temp directory and renaming on success
> - On failure, remove temp directory and partial files

**Recommended action:** REMOVE OR CONDENSE

**Rationale:** This prescribes the exact implementation: create temp directory, write files, rename on success. This is an algorithm-level detail. The spec should describe the **requirement** (atomic writes, cleanup on failure) but not the **implementation** (temp directory + rename pattern).

**Suggested replacement:**
> Directory writes must be atomic: either all files appear or none. Clean up partial writes on failure.

---

## Lines 44-48: Over-Spec (Percent-Encoding Details)

> - Emit directory tree inside `--output` using Hive-style segments:
>   `<col1>=<val1>/<col2>=<val2>/.../`
>   - Values derived after casting to resolved schema types
>   - Apply percent-encoding of UTF-8 bytes for characters outside `[A-Za-z0-9._-]`; space → `%20`; `/` encoded as `%2F`
>   - Null (missing) partition values use literal `_null`

**Recommended action:** KEEP but CLARIFY character set

**Rationale:** While detailed, these rules are necessary for deterministic output validation. However, the safe character set `[A-Za-z0-9._-]` is ambiguous:
- Tests show `+` is encoded, confirming it's outside the safe set
- But spec doesn't explicitly list all unsafe characters
- "Characters outside" is technically correct but could benefit from examples

**Suggested addition:**
> Examples of encoded characters: space → `%20`, `/` → `%2F`, `+` → `%2B`. UTF-8 multi-byte characters are encoded byte-by-byte (e.g., `ü` → `%C3%BC`).

---

## Lines 44-45: Missing Information (Directory Nesting Order)

> - Emit directory tree inside `--output` using Hive-style segments:
>   `<col1>=<val1>/<col2>=<val2>/.../`

**Recommended action:** CLARIFY

**Rationale:** When `--partition-by state,city` is specified, is the directory structure `state=CA/city=LA/` or `city=LA/state=CA/`? Tests show the order follows the `--partition-by` flag order, but spec uses generic `<col1>/<col2>` notation without stating what determines column ordering.

**Suggested replacement:**
> Partition columns create nested directories in the order specified in `--partition-by`: `<col1>=<val1>/<col2>=<val2>/.../`

---

## Lines 49-52: Over-Spec (File Naming Details)

> - Within each partition directory, write CSV files named sequentially:
>   `part-00000.csv`, `part-00001.csv`, … (zero-padded width 5)
>   - Each file contains header row (resolved schema header)
>   - Must respect size/row-based cutting rules if set (see below); otherwise one file per partition

**Recommended action:** KEEP (necessary for deterministic output)

**Rationale:** File naming is an observable output requirement. Zero-padding width and sequence numbering are testable behaviors. This is appropriate detail for a deterministic spec.

---

## Lines 56-59: Ambiguity (Byte Limit Calculation)

> - `--max-bytes-per-file <INT>`: cut so on-disk byte size of each file (including header and line endings) is ≤ INT
>   - Exception: if single row alone exceeds INT, place that row in file by itself (allowed to exceed limit)
> - When both `--max-rows-per-file` and `--max-bytes-per-file` provided, cut at earliest boundary that would violate either constraint

**Recommended action:** CLARIFY OR MOVE-TO-EXAMPLE

**Rationale:**
1. "On-disk byte size including header and line endings" doesn't specify:
   - Whether to count `\n` (LF) as 1 byte or `\r\n` (CRLF) as 2 bytes
   - How CSV quoting/escaping affects byte count (quoted vs unquoted)
   - Whether to count bytes as written to disk or logical byte count
2. The exception for single row exceeding limit is mentioned but not tested
3. No guidance on how to predict file size before writing (streaming scenario)

Tests use small byte limits (12 bytes) but don't show calculation method.

**Suggested approach:** Either provide precise byte counting rules or add a test case demonstrating the calculation with explicit byte counts.

---

## Lines 59: Missing Information (Dual Constraint Interaction)

> - When both `--max-rows-per-file` and `--max-bytes-per-file` provided, cut at earliest boundary that would violate either constraint

**Recommended action:** ADD TEST COVERAGE

**Rationale:** Spec clearly states the rule ("earliest boundary"), but test `both_limits.yaml` only validates the case where row limit is hit first. No test shows byte limit being hit before row limit. This leaves a testing gap for the interaction.

**Suggested addition:** Add test case with large rows and high row limit where byte limit is the earlier constraint.

---

## Lines 76-77: Solution Leak (Memory Limit Reference)

> **Memory & External Merge**
>
> - Continue to honor small `--memory-limit-mb` values
> - Tool must work on arbitrarily large inputs

**Recommended action:** REMOVE OR CONDENSE

**Rationale:** "External Merge" in the section title is a solution hint (implies disk-based sorting). Same issue as checkpoints 1 and 2. The requirement is clear (handle large inputs under memory constraints) but the implementation (external merge sort) is revealed.

**Suggested replacement:**
> **Performance Requirements**
>
> Tool must handle inputs exceeding `--memory-limit-mb` constraint.

---

## Lines 110-115: Over-Spec (Determinism Checklist)

> **Determinism Checklist**
>
> - Directory layout and file names follow exact rules (Hive-style segments, `_null` for missing, percent-encoding)
> - Size/row-based cutting produces deterministically named `part-xxxxx.csv` files with headers
> - Atomic directory creation/move semantics; temp artifacts cleaned on failure
> - Exact exit codes and stderr message shapes as specified

**Recommended action:** REMOVE

**Rationale:** This is meta-commentary for spec authors, not agent instructions. It summarizes requirements already stated above. Line 115 references "exact exit codes and stderr message shapes as specified" but these are not formally documented in the spec (same issue as previous checkpoints).

---

## Missing from Spec: Partition Column Validation

**Test evidence:** `missing_partition_col.yaml` expects error code 3 and stderr `ERR 3 key column "city" not present in resolved schema`

**Recommended action:** ADD error handling specification

**Rationale:** Spec line 46 says partition values are "derived after casting to resolved schema types" which implies columns must exist, but doesn't explicitly state what happens when they don't. Tests define the behavior (error code 3) but spec doesn't document this error condition.

**Suggested addition:**
```markdown
**Error Handling**

- If a partition column is not present in the resolved schema, exit with error code 3.
```

---

## Missing from Spec: Output CSV Column Ordering

**Test evidence:** Tests show output CSVs have columns in alphabetical order (resolved schema order)

**Recommended action:** CLARIFY (or rely on checkpoint 1/2 spec)

**Rationale:** Checkpoint 1 spec states "Column order: ascending lexicographic order of column names" for inferred schemas. Checkpoint 3 doesn't restate this. Tests confirm behavior but it's inherited context, not explicit in checkpoint 3 spec.

**Suggested approach:** Either add a cross-reference to checkpoint 1's column ordering rule or restate it briefly.

---

## Missing from Spec: File Header Requirements

**Test evidence:** Spec says "Each file contains header row" (line 51) but doesn't test multi-file scenarios comprehensively

**Recommended action:** ADD TEST COVERAGE

**Rationale:** Line 72 states "Every output CSV includes header row" which is clear, but tests don't validate that ALL files in a multi-partition, multi-shard scenario have correct headers. Test `partitions.yaml` has 2 files in one partition, but no test has multiple partitions each with multiple files.

**Suggested addition:** Add test with 2+ partitions, each containing 2+ sharded files, validating all files have correct headers.

---

## Lines 33-40: Missing Information (Directory vs File Mode Detection)

> **Output Location & Mode**
>
> - When no partitioning flags provided: write single CSV to `--output` (file path or `-` for stdout)
> - When any partitioning flag provided: `--output` must be directory path (not `-`)

**Recommended action:** CLARIFY "any partitioning flag"

**Rationale:** "Any partitioning flag" is slightly ambiguous. Does this mean:
- Any of `--partition-by`, `--max-rows-per-file`, `--max-bytes-per-file`?
- Only `--partition-by`?
- Any combination?

Tests show `--partition-by` triggers directory mode, and `--max-rows-per-file` alone also triggers directory mode (`shard_rows/basic.yaml`). This confirms "any partitioning flag" includes sharding flags, but spec could be more explicit.

**Suggested replacement:**
> When any partitioning or sharding flag (`--partition-by`, `--max-rows-per-file`, or `--max-bytes-per-file`) is provided: `--output` must be directory path (not `-`)

---

## Lines 80-108: Over-Spec (Command Examples)

> **Examples**
>
> - Field-partitioned by `country,dt` with per-partition sharding to ≤ 50 MB parts:
> - Globally sorted stream sharded into files of ≤ 1,000,000 rows (no field partitions):
> - Field-partition only (one file per partition), descending order:

**Recommended action:** KEEP (reasonable CLI examples)

**Rationale:** These show valid invocation patterns demonstrating different combinations of partitioning and sharding. They don't reveal algorithm details. The examples are helpful for understanding flag interactions.

---

## Lines 63-67: Missing Information (Sorting Guarantee Precision)

> **Sorting Guarantees**
>
> - With no field partitioning: rows must be globally sorted by `--key` (and `--desc` if set)
> - With field partitioning: rows in each partition directory must be sorted by `--key` within that partition

**Recommended action:** CLARIFY cross-partition ordering

**Rationale:** With field partitioning, rows are sorted within partitions, but spec doesn't state whether there's any ordering relationship BETWEEN partitions. For example, if partitioning by `country`:
- Are all rows in `country=US` guaranteed to come before/after `country=CA` in some global sense?
- Or is inter-partition ordering undefined?

Tests don't validate cross-partition ordering. This is likely undefined, but spec could clarify.

**Suggested addition:**
> Ordering between partitions is not guaranteed; sorting applies only within each partition directory.

---

## Reviewer Checklist Results

- [ ] ❌ **No text describing algorithms or data structures** - FAILED: Lines 38-39 prescribe temp directory + rename; line 76 section title says "External Merge"
- [x] ✅ **Every rule inferable from examples or a single invariant line** - MOSTLY: Partition nesting order not explicit; byte calculation undefined
- [ ] ❌ **Clear, deterministic grading criteria** - NEEDS WORK: Byte counting method unclear; partition column error not documented
- [ ] ⚠️  **Examples cover normal, boundary, and failure modes** - PARTIAL: Good coverage but missing single-row-exceeds-bytes, multi-partition-multi-shard, byte-before-row
- [x] ✅ **Later checkpoints build strictly on earlier outputs** - YES: Extends checkpoint 2's multi-format merger
- [ ] ❌ **No redundant or tutorial language** - FAILED: Lines 110-115 (Determinism Checklist)
- [ ] ❌ **All remaining text focuses on outcomes and observables** - FAILED: Lines 38-39 describe implementation approach

---

## Summary of Recommended Actions

| Priority | Action | Line Range | Type |
|----------|--------|------------|------|
| **HIGH** | Remove temp directory implementation details | 38-39 | Solution Leak |
| **HIGH** | Clarify partition directory nesting order | 44-45 | Missing Information |
| **HIGH** | Add partition column error handling spec | N/A (missing) | Missing Information |
| **HIGH** | Clarify byte calculation method for max-bytes-per-file | 56-59 | Ambiguity |
| **MEDIUM** | Remove "Determinism Checklist" section | 110-115 | Over-Spec |
| **MEDIUM** | Remove "External Merge" from section title | 76 | Solution Leak |
| **MEDIUM** | Clarify "any partitioning flag" to include sharding | 33-36 | Ambiguity |
| **MEDIUM** | Add cross-partition ordering clarification | 63-67 | Missing Information |
| **MEDIUM** | Add examples of unsafe characters for encoding | 47-48 | Ambiguity |
| **LOW** | Add test coverage for byte-limit-first scenario | N/A | Missing Information |
| **LOW** | Add test coverage for single-row-exceeds-bytes exception | N/A | Missing Information |
| **LOW** | Add test coverage for multi-partition-multi-shard scenario | N/A | Missing Information |
| **LOW** | Clarify or cross-reference column ordering rule | N/A | Missing Information |

---

## Delta from Checkpoint 2

Checkpoint 3 adds:
- Hive-style field partitioning with directory hierarchies
- Partition value encoding (percent-encoding, UTF-8, `_null` handling)
- Row-based file sharding (`--max-rows-per-file`)
- Byte-based file sharding (`--max-bytes-per-file`)
- Combined partitioning + sharding
- Per-partition vs global sorting guarantees
- Multi-file output with sequential naming
- Atomic directory writes
- New error condition: missing partition column (error 3)

**Test Coverage:** 11 test cases provide good coverage of core features but have gaps in edge cases (single row exceeding bytes, byte-limit-first interaction, multi-partition-multi-shard validation).

**Critical Observation:** Spec provides implementation details (temp directory pattern) that should be removed. Byte calculation method needs clarification for deterministic grading. Directory nesting order needs explicit specification.
