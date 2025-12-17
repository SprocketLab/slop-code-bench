# Checkpoint 2 Specification Review Report

## Checkpoint Summary
Adds backup strategy support (full, pack, verify) to the baseline scheduler from checkpoint 1. Introduces tar archive creation with size limits for pack strategy.

## Critical Missing Information

### Job and File Processing Order
The specification does not restate requirements from checkpoint 1 about job and file ordering, assuming readers will reference the previous checkpoint.

**Recommended action:** CLARIFY

**Rationale:** Checkpoint specs should be self-contained. Add brief reminder that jobs execute in alphabetical ID order and files process in lexicographic order, or explicitly reference checkpoint 1 requirements that remain unchanged.

### When to Include JOB_COMPLETED Fields
Line 57 states fields "may include" `packs` and `total_size` but doesn't specify when each should be present.

**Recommended action:** CLARIFY

**Rationale:** Tests show specific patterns:
- `full`: includes `total_size`
- `pack`: includes both `packs` and `total_size`
- `verify`: includes neither
- No strategy: includes neither

This should be explicitly stated or clearly shown in examples.

### Final Pack Finalization
The spec describes when to finalize packs during processing but doesn't explicitly state that any remaining pack must be finalized before JOB_COMPLETED.

**Recommended action:** CLARIFY

**Rationale:** Add explicit requirement: "Any pack with files must be finalized before JOB_COMPLETED, even if not full."

### Strategy Field Omission Behavior
Line 25 states "behavior matches checkpoint 1 (no backup operations, no STRATEGY_SELECTED event)" but doesn't clarify all implications.

**Recommended action:** MOVE-TO-EXAMPLE

**Rationale:** Add an example showing a job without strategy field to demonstrate backward compatibility.

## Solution Leaks

### Lines 36-37: Solution Leak
> Each file is always packed (even if alone it exceeds limit); when adding would overflow, finalize current pack first.

**Recommended action:** CONDENSE

**Rationale:** This prescribes the exact packing algorithm. Replace with outcome: "Files are packed into archives subject to size limit. When a pack reaches capacity, it is finalized and a new pack begins."

### Lines 38-41: Necessary Specification
> **Tar archive requirements (for deterministic checksums):**
>   - Format: GNU tar format (`tarfile.GNU_FORMAT`)
>   - Entry metadata: `mtime=0`, `mode=0o644`, `uid=0`, `gid=0`, `uname=""`, `gname=""`

**Recommended action:** KEEP with modification

**Rationale:** While specific, these details are necessary for deterministic checksums. However, remove `tarfile.GNU_FORMAT` reference (see bias phrases). State format requirements as outcomes: "Archives must use GNU tar format with normalized metadata for deterministic checksums."

## Bias Phrases

### Line 39: Bias Phrase
> Format: GNU tar format (`tarfile.GNU_FORMAT`)

**Recommended action:** REMOVE

**Rationale:** `tarfile.GNU_FORMAT` is Python-specific implementation detail. State as "GNU tar format" without language-specific constants.

### Line 35: Acceptable Specificity
> Creates sequential `.tar` archives

**Recommended action:** KEEP

**Rationale:** Tar format is industry standard and required for interoperability. This is specification, not bias.

## Over-Specification

### Lines 62-68: Over-Spec
> All JSON events must be emitted in compact format:
> - No spaces after colons or commas
> - No trailing commas
> - One event per line, newline-terminated
>
> Field ordering shown in examples is for readability only...

**Recommended action:** REMOVE

**Rationale:** This is copied verbatim from checkpoint 1. Either reference checkpoint 1 or remove entirely (examples demonstrate format).

### Lines 70-90: Over-Spec
> ### Event Schema Reference
>
> **Events from checkpoint 1** (unchanged):
> ...
> **New events in checkpoint 2**:
> ...

**Recommended action:** CONDENSE

**Rationale:** Replace entire table with: "New events: STRATEGY_SELECTED, FILE_BACKED_UP, FILE_VERIFIED, FILE_PACKED, PACK_CREATED. See examples for field requirements."

## Ambiguities

### Lines 99-101: Ambiguity
> Both `full` and `verify` strategies process files individually. The only difference is the event emitted after each selected file

**Recommended action:** CLARIFY

**Rationale:** Imprecise. There are multiple differences:
- Event name (FILE_BACKED_UP vs FILE_VERIFIED)
- STRATEGY_SELECTED event shows different kind
- JOB_COMPLETED includes total_size for full but not verify

Replace with: "Both strategies process files individually and emit similar events, with differences in event names and summary fields."

### Line 133-135: Incorrect Example Statement
> For `verify` strategy, output is identical except:
> - `STRATEGY_SELECTED` has `"kind":"verify"`
> - `FILE_BACKED_UP` events become `FILE_VERIFIED` events (same fields)

**Recommended action:** CLARIFY

**Rationale:** This misses that JOB_COMPLETED doesn't include `total_size` for verify. Either show full verify example or list all differences.

### Line 89: Incomplete Field Description
> | `PACK_CREATED` | `event`, `job_id`, `name`, `size`, `timestamp`, `checksum`, `tar_size` | When pack archive finalized |

**Recommended action:** CLARIFY

**Rationale:** Doesn't explain what `size` vs `tar_size` means. From example context: `size` is content bytes, `tar_size` is archive bytes with tar overhead.

## Example Coverage Analysis

### What Examples Demonstrate Well
- Pack strategy with multiple files and pack transitions
- Full strategy basic usage
- Strategy selection and event flow
- Pack creation with size limit logic

### Missing Example Coverage
1. **No strategy field** - Job without strategy field showing backward compatibility
2. **Verify strategy complete output** - Example 1 describes verify but doesn't show actual output
3. **Empty pack job** - Pack strategy with all files excluded
4. **Single oversized file** - File larger than max_pack_bytes packed alone
5. **Exact fit pack** - Files that exactly equal max_pack_bytes

### Test Data Issue
The test case `checkpoint_2/core/verify/expected.jsonl` appears to have incorrect data:
- case.yaml specifies `strategy.kind: verify`
- expected.jsonl shows `kind: "full"` and `FILE_BACKED_UP` events

Hidden verify tests show correct behavior. This appears to be a test bug, not a spec issue.

## Overall Assessment

This checkpoint spec is **moderately over-specified** with several issues:

1. **Missing critical information** about when to include optional fields and final pack finalization
2. **Solution leaks** in packing algorithm description (lines 36-37)
3. **Unnecessary table** duplicating event schemas that examples demonstrate
4. **Incomplete example coverage** - verify strategy mentioned but not shown
5. **Python-specific bias** in tar format specification
6. **Ambiguous statements** about strategy differences

The spec would benefit from:
- Self-contained ordering requirements (not assuming checkpoint 1 knowledge)
- Explicit rules for optional JOB_COMPLETED fields
- Removing prescriptive packing algorithm details
- Complete verify strategy example
- Example showing no-strategy backward compatibility
- Removing language-specific implementation details
- Clarifying field meanings (size vs tar_size)

The goal should be clearly defining **what** each strategy produces without prescribing **how** to implement the packing algorithm.