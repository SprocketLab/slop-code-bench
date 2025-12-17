# Spec Review Report: file_merger/checkpoint_2

## Checkpoint Summary

Checkpoint 2 extends checkpoint 1 by adding multi-format input support (CSV, TSV, JSONL, Parquet), auto-detection, compression handling (gzip), and schema resolution strategies across heterogeneous sources. It tests whether agents can extend their checkpoint 1 design to handle format abstraction, typed vs. untyped sources, and schema consensus mechanisms.

---

## Clarification Requests

1. **Schema strategy algorithms**: How exactly should `--schema-strategy=union` determine "simplest common type"? What does "majority of files support" mean for `--schema-strategy=consensus` when types conflict?

2. **Parquet testing gap**: Spec extensively describes Parquet support (lines 32, 40, 47-48) but there are NO test cases validating Parquet reading. Is Parquet a required feature or optional for checkpoint 2?

3. **Compression testing gap**: Spec describes gzip handling (lines 25, 37-39) but there are NO test cases validating `.gz` detection or decompression. Is this tested in a later checkpoint?

4. **Error code 5 overloading**: Spec uses error code 5 for both "compression mismatch" (line 39) and "TSV format violations" (line 45). Should these be distinct error codes?

5. **Exit code documentation**: Where should exit codes 5 and 6 be formally defined? Tests expect them but spec doesn't document them in a centralized exit code section.

---

## Example Coverage Notes

**Logic Demonstrated by Tests:**
- Multi-format merging (CSV + TSV + JSONL combinations)
- Auto format detection by extension
- Forced format detection via `--input-format`
- Schema strategies: `union` and `consensus` (but NOT `authoritative`)
- Type handling from typed sources (JSONL numbers)
- JSONL null preservation
- TSV parsing with tab delimiters
- Error conditions: unknown format (error 2), nested JSONL (error 6), TSV field violations (error 5), missing key (error 3)

**NOT Demonstrated by Tests (but in spec):**
- Parquet reading (entire major feature untested)
- Compression handling (gzip detection, `.gz` extension processing)
- Schema strategy: `authoritative` (the DEFAULT strategy!)
- Magic byte detection for format ambiguity
- Parquet nested structure rejection (error 6 only tested for JSONL)
- Parquet row group streaming
- Mixed typed sources (JSONL + Parquet)

**Critical Gap**: The spec extensively describes Parquet support but provides zero test coverage. Either tests are missing or Parquet is not actually required for checkpoint 2.

---

## Issues

## Lines 40, 87-88: Solution Leak

> Parquet reading must be streamed row group–wise; `--parquet-row-group-bytes` is advisory for batch sizing

> Implementation must work with `--memory-limit-mb` as low as 64 and terabyte-scale inputs
> Avoid format-specific issues (e.g., don't load entire Parquet files or JSON arrays)

**Recommended action:** REMOVE OR CONDENSE

**Rationale:** These lines explicitly reveal the implementation approach: streaming and row-group-based processing for Parquet. Line 40 prescribes "must be streamed row group–wise" which is an algorithm detail. Line 88 tells agents "don't load entire Parquet files" which is a solution hint. The spec should describe requirements (handle large files under memory constraints) not implementation (stream row groups).

**Suggested replacement:**
> Tool must handle inputs exceeding `--memory-limit-mb` constraint. Parquet files may be processed in batches controlled by `--parquet-row-group-bytes`.

---

## Lines 58-60: Ambiguity (Schema Strategy Definitions)

> - **Schema disagreement strategy** when inputs have conflicting types for same column:
>   - `--schema-strategy=authoritative` (default): prefer typed sources in precedence order
>   - `--schema-strategy=consensus`: choose type that majority of files support
>   - `--schema-strategy=union`: choose simplest common type that can hold all observed values

**Recommended action:** CLARIFY OR MOVE-TO-EXAMPLE

**Rationale:** These descriptions are vague and untestable:
- "Prefer typed sources in precedence order" - What is precedence order? Parquet > JSONL > CSV/TSV? File argument order?
- "Type that majority of files support" - If 3 files have 3 different types for a column, what is the majority? Does "support" mean parse successfully?
- "Simplest common type" - What is the type hierarchy? String > float > int? Or string is most general?

Tests validate `union` and `consensus` behaviors but the spec's prose doesn't match the tested behavior clearly.

**Suggested approach:** Either define precise rules (e.g., "authoritative precedence: Parquet > JSONL > CSV/TSV, then by file argument order") OR remove the vague descriptions and rely entirely on test cases to demonstrate behavior.

---

## Lines 33-36: Missing Information (Format Detection Algorithm)

> - `--input-format=auto` (default): detect per file by extension and magic bytes:
>   - `.csv` → csv, `.tsv` → tsv, `.jsonl`/`.ndjson` → jsonl, `.parquet` → parquet
>   - For gzip, allow `.gz` suffix after base extension (e.g., `data.csv.gz`, `events.jsonl.gz`)
>   - If extension is ambiguous and magic bytes indicate Parquet, treat as parquet; otherwise error 2

**Recommended action:** CLARIFY

**Rationale:** "Extension is ambiguous" is vague. When exactly is an extension ambiguous? Examples:
- Unknown extension like `.data` → error 2? (test confirms)
- No extension → error 2?
- `.gz` with no base extension → error 2?
- Extension is `.csv` but magic bytes indicate Parquet → use Parquet or error?

The algorithm flow is unclear. Tests show `.data` = error 2, but the spec says "if ambiguous AND magic bytes indicate Parquet" which implies magic bytes are only checked when ambiguous.

**Suggested replacement:**
```markdown
Format detection algorithm:
1. If `--input-format` is specified, use that format for all inputs
2. Otherwise (auto mode), for each file:
   a. Check extension (ignoring `.gz` suffix):
      - `.csv` → CSV
      - `.tsv` → TSV
      - `.jsonl` or `.ndjson` → JSONL
      - `.parquet` → Parquet
   b. If extension is unrecognized, check magic bytes:
      - Parquet magic bytes detected → Parquet
      - Otherwise → error 2
```

---

## Lines 37-39: Ambiguity (Compression Error Handling)

> - `--compression=auto` (default): detect `.gz` → gzip; otherwise none
> - `--compression=none` forces no decompression; `--compression=gzip` forces gzip
> - Mismatch is error 5

**Recommended action:** CLARIFY

**Rationale:** "Mismatch is error 5" - what constitutes a mismatch?
- File has `.gz` extension but content is not gzipped → error 5
- `--compression=gzip` specified but file is not gzipped → error 5
- `--compression=none` but file is gzipped → error 5
- All of the above?

The spec doesn't clarify. Additionally, error code 5 is reused for TSV format violations (line 45), creating ambiguity.

**Suggested clarification:**
> If `--compression` is set to `gzip` but file is not gzip-compressed, or set to `none` but file is gzip-compressed, exit with error 5.

---

## Line 45: Ambiguity (TSV Field Validation)

> - **TSV**: delimiter is tab (`\t`), no quoting, header row required, `\n` line endings; literal tabs inside field not allowed (error 5)

**Recommended action:** CLARIFY

**Rationale:** Test `tsv_embedded_tab.yaml` has content `1\tbad\trow\n` with header `id\tname\n` (2 columns). This is a field count mismatch, not a "literal tab inside field". The spec's phrasing suggests tabs within a single field value (e.g., `id="1\t2"`) are forbidden, but the test is actually validating column count alignment.

Either the test is wrong or the spec's wording is imprecise. TSV format violations could include:
- Wrong number of fields per row
- Literal tabs embedded in field content (though TSV has no escaping mechanism)

**Suggested replacement:**
> TSV rows must have the same number of tab-delimited fields as the header. Malformed rows trigger error 5.

---

## Lines 62-70: Over-Spec (Type Casting Details)

> **Casting**
>
> - CSV/TSV values are raw strings (after unescape for CSV)
> - JSONL values come typed (string/number/bool/null)
> - Parquet values come typed
> - Apply target output schema cast rules to every cell
> - For JSONL numbers, prefer `int` if integral and within range; otherwise `float`
> - If JSONL/Parquet value is `null` or CSV/TSV cell is empty, treat as missing → emit null literal
> - On cast failure, follow `--on-type-error` from checkpoint 1

**Recommended action:** CONDENSE OR MOVE-TO-EXAMPLE

**Rationale:** While type handling rules are necessary for deterministic evaluation, the level of detail here is tutorial-like. Lines 64-66 state the obvious (CSV is strings, JSONL is typed). Line 68 about JSONL int vs float preference could be demonstrated through examples instead of prose.

However, line 69's null handling rule is an observable behavior requirement and should be kept.

**Suggested condensation:**
```markdown
**Casting**

- CSV/TSV fields are parsed as strings; JSONL and Parquet provide typed values
- Empty cells and explicit `null` values map to the configured null literal
- Cast all values to the resolved schema type per `--on-type-error` rules
```

---

## Line 82: Bias Phrase (Atomic Write)

> - `--output -` writes to stdout; otherwise write atomically

**Recommended action:** REMOVE "atomically"

**Rationale:** Same issue as checkpoint 1 - "atomically" suggests temp file + rename implementation. Not tested, not necessary to specify.

**Suggested replacement:**
> - `--output -` writes to stdout; otherwise write to file path

---

## Lines 111-118: Over-Spec (Determinism Checklist)

> **Determinism Checklist**
>
> - Input format detection and gzip handling follow rules above
> - Schema resolution honors chosen `--schema-strategy`; column order is lexicographic when inferred
> - Flat-only enforcement for JSONL/Parquet; nested structures trigger error 6
> - All values cast per final schema; nulls/missing rendered as configured null literal
> - Sort correctness and stability across mixed sources
> - Exact exit codes and stderr message shape as specified

**Recommended action:** REMOVE

**Rationale:** This is meta-commentary for spec authors, not agent instructions. It summarizes requirements already stated above and adds no new information. Line 118 references "exact exit codes and stderr message shape as specified" but those are never formally specified in the spec.

---

## Lines 46-47: Missing Information (JSONL Nested Rejection)

> - **JSONL**: one UTF-8 JSON object per line; objects must be flat (no arrays/objects as values); `null` permitted; keys case-sensitive; blank/whitespace lines ignored

> - **Parquet**: flat schemas only (no nested/list/map types); nested fields trigger error 6

**Recommended action:** CLARIFY ERROR CODE

**Rationale:** Tests confirm error 6 for nested JSONL (test: `jsonl_nested.yaml`), but error code 6 is not documented in a centralized error code section. The spec mentions "error 6" inline but doesn't define it formally.

**Suggested addition:** Document error code 6 in a formal error code section (similar to recommendation for checkpoint 1).

---

## Missing from Spec: Exit Codes 5 and 6

**Test evidence:**
- `tsv_embedded_tab.yaml`: exit code 5 (TSV format violation)
- `jsonl_nested.yaml`: exit code 6 (nested structure)

**Recommended action:** ADD formal exit code documentation

**Rationale:** Checkpoint 2 introduces new error codes but doesn't document them in a centralized section. Inline mentions (line 39 error 5, line 47 error 6) are scattered.

**Suggested addition:**
```markdown
**Error Handling**

Exit codes (extending checkpoint 1):
- 5: Format parsing error or compression mismatch
- 6: Nested/complex structure in JSONL or Parquet
```

---

## Missing from Spec: Parquet Implementation Details

**Test evidence:** ZERO test cases for Parquet

**Recommended action:** CLARIFY or REMOVE Parquet from checkpoint 2

**Rationale:** The spec extensively describes Parquet support (lines 32, 34, 40, 47, 48, 66, 67, 88) but provides NO test coverage. This creates a massive gap:
- Is Parquet required for checkpoint 2?
- If yes, why no tests?
- If no, why is it in the spec?

**Options:**
1. Add Parquet test cases
2. Move Parquet to a later checkpoint
3. Document that Parquet is optional/extra credit

Without tests, agents cannot determine correct Parquet behavior.

---

## Missing from Spec: Compression (Gzip) Implementation

**Test evidence:** ZERO test cases for gzip/`.gz` handling

**Recommended action:** CLARIFY or REMOVE compression from checkpoint 2

**Rationale:** Similar to Parquet, the spec describes gzip compression handling (lines 25, 35, 37-39) but provides NO test coverage. Either add tests or clarify that compression is untested in checkpoint 2.

---

## Missing from Spec: Authoritative Schema Strategy

**Test evidence:** Tests cover `union` and `consensus` but NOT `authoritative` (the default!)

**Recommended action:** ADD test case for authoritative strategy OR remove it as default

**Rationale:** The spec says `authoritative` is the default (line 58) but provides no test demonstrating its behavior. The description "prefer typed sources in precedence order" is vague and untested. Either:
1. Add a test case showing authoritative strategy behavior
2. Change the default to `consensus` or `union` (which are tested)
3. Remove the default designation and require explicit specification

---

## Lines 42-48: Over-Spec (Source Dialect Assumptions)

> **Source Dialect Assumptions**
>
> - **CSV**: same as checkpoint 1 (RFC-4180, header row, `\n`, default quote `"`, escape by doubling)
> - **TSV**: delimiter is tab (`\t`), no quoting, header row required, `\n` line endings; literal tabs inside field not allowed (error 5)
> - **JSONL**: one UTF-8 JSON object per line; objects must be flat (no arrays/objects as values); `null` permitted; keys case-sensitive; blank/whitespace lines ignored
> - **Parquet**: flat schemas only (no nested/list/map types); nested fields trigger error 6

**Recommended action:** CONDENSE

**Rationale:** Some details are necessary for grading (header required, flat only), but others are over-specified:
- "one UTF-8 JSON object per line" - UTF-8 is implied
- "keys case-sensitive" - this is JSON standard behavior
- "blank/whitespace lines ignored" - reasonable edge case but could be tested instead of stated

**Suggested condensation:**
```markdown
**Source Format Requirements**

- **CSV**: RFC-4180, header row required (same as checkpoint 1)
- **TSV**: Tab-delimited, header row required, no quoting, `\n` line endings
- **JSONL**: Flat JSON objects only (no nested objects or arrays; error 6)
- **Parquet**: Flat schemas only (no nested/list/map types; error 6)
```

---

## Lines 90-99: Over-Spec (Command Examples)

> **Examples**
>
> - Mixed CSV + JSONL + Parquet, schema inferred by consensus, sort by composite key:
>
>   ```
>   %%%ENTRYPOINT:entry_command%%% --output merged.csv \
>            --key ts,id \
>            --schema-strategy consensus \
>            inputs/users.csv inputs/events.jsonl.gz inputs/metrics.parquet
>   ```
>
> - Authoritative provided schema, TSV source, gzip forced, descending sort:
>
>   ```
>   %%%ENTRYPOINT:entry_command%%% --output - \
>            --key created_at,id --desc \
>            --schema schema.json \
>            --input-format tsv --compression gzip \
>            data/*.tsv.gz
>   ```

**Recommended action:** KEEP but note irony

**Rationale:** These examples show valid CLI invocations and are helpful for interface understanding. However, there's an irony: the examples reference Parquet and gzip compression, but there are NO tests for either feature. This creates false expectations.

If Parquet and gzip are removed from the spec, update examples accordingly.

---

## Reviewer Checklist Results

- [ ] ❌ **No text describing algorithms or data structures** - FAILED: Lines 40, 87-88 prescribe streaming/row-group processing
- [ ] ❌ **Every rule inferable from examples or a single invariant line** - FAILED: Schema strategy algorithms vague; Parquet/gzip untested
- [ ] ❌ **Clear, deterministic grading criteria** - NEEDS WORK: Exit codes 5/6 not formally documented; schema strategies ambiguous
- [ ] ⚠️  **Examples cover normal, boundary, and failure modes** - PARTIAL: Tests cover multi-format basics but missing Parquet, gzip, authoritative strategy
- [x] ✅ **Later checkpoints build strictly on earlier outputs** - YES: Checkpoint 2 extends checkpoint 1's implementation
- [ ] ❌ **No redundant or tutorial language** - FAILED: Lines 111-118 (Determinism Checklist), lines 62-70 (detailed casting rules)
- [ ] ❌ **All remaining text focuses on outcomes and observables** - FAILED: Lines 40, 87-88 describe implementation approach

---

## Summary of Recommended Actions

| Priority | Action | Line Range | Type |
|----------|--------|------------|------|
| **CRITICAL** | Clarify Parquet testing: required or optional? Add tests or remove | 32, 40, 47, 66-67, 88 | Missing Information |
| **CRITICAL** | Clarify gzip/compression testing: add tests or remove | 25, 35, 37-39 | Missing Information |
| **CRITICAL** | Add test for authoritative schema strategy OR remove as default | 58 | Missing Information |
| **HIGH** | Remove/condense streaming and row-group implementation details | 40, 87-88 | Solution Leak |
| **HIGH** | Clarify schema strategy algorithms (authoritative precedence, consensus voting, union type selection) | 58-60 | Ambiguity |
| **HIGH** | Add formal exit code documentation for codes 5 and 6 | N/A (missing) | Missing Information |
| **MEDIUM** | Remove "Determinism Checklist" section | 111-118 | Over-Spec |
| **MEDIUM** | Clarify format detection algorithm (magic bytes, unknown extensions) | 33-36 | Ambiguity |
| **MEDIUM** | Clarify compression mismatch error conditions | 37-39 | Ambiguity |
| **MEDIUM** | Fix TSV field validation wording | 45 | Ambiguity |
| **MEDIUM** | Remove "atomically" from output spec | 82 | Bias Phrase |
| **MEDIUM** | Condense type casting details or move to examples | 62-70 | Over-Spec |
| **LOW** | Condense source dialect assumptions | 42-48 | Over-Spec |

---

## Delta from Checkpoint 1

Checkpoint 2 adds:
- Multi-format input support (CSV, TSV, JSONL, Parquet)
- Format auto-detection and compression handling
- Schema resolution strategies across heterogeneous typed/untyped sources
- New error codes 5 (format errors) and 6 (nested structures)

**Critical observation**: The spec describes extensive Parquet and compression features, but test coverage is ZERO for both. This is either a major testing gap or indicates these features should be moved to a later checkpoint.
