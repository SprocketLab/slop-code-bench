# Checkpoint 4 Specification Review Report

## Checkpoint Summary
Extends pack strategy to support incremental backups by reading existing pack tar files from destination. System loads existing packs, compares file checksums, and emits new events for unchanged packs and files. Reverses checkpoint 3's explicit statement that pack doesn't use incremental backups.

## Critical Missing Information

### Complete Repacking Behavior
The most critical behavior is buried in line 140 (Key observations section) and not stated in deliverables or main specification.

**Recommended action:** CLARIFY

**Rationale:** Line 140 mentions "Packing algorithm reruns from scratch" but this is in the observations section, not requirements. Tests show the system:
- Completely discards old pack structure
- Repacks ALL files according to current max_pack_bytes
- Ignores which files were in which packs previously
- Creates entirely new pack assignments every run

This should be prominently stated in the deliverables or main spec: "The system repacks all files from scratch on each run. Existing pack structure is discarded; files are packed according to current size constraints."

### PACK_CREATED vs PACK_UPDATED vs PACK_UNCHANGED Decision Logic
The spec defines three events (lines 47-50) but never explains how to determine which to emit.

**Recommended action:** CLARIFY

**Rationale:** Tests show the decision is made by comparing new pack checksums to loaded pack checksums by pack NAME:
- Pack name exists in loaded packs AND checksums match → PACK_UNCHANGED
- Pack name exists in loaded packs AND checksums differ → PACK_UPDATED
- Pack name doesn't exist in loaded packs → PACK_CREATED

This comparison logic must be explicitly stated.

### PACK_LOADED Events Are Informational Only
The spec describes PACK_LOADED events (line 47) but doesn't clarify they don't affect packing decisions.

**Recommended action:** CLARIFY

**Rationale:** Tests show PACK_LOADED events are emitted but the loaded structure is NOT used to determine new pack assignments. Files are packed according to checkpoint 2's greedy algorithm, not according to previous pack membership. Add: "PACK_LOADED events are informational only. Pack assignments are determined by current file order and size constraints, not previous pack structure."

### Pack Completion Event Timing
The spec doesn't specify when PACK_CREATED/PACK_UPDATED/PACK_UNCHANGED events are emitted.

**Recommended action:** CLARIFY

**Rationale:** Tests show these events are emitted:
- After the last file for that pack is processed
- Before the next file (which goes into a different pack) is processed

Add explicit timing: "Pack completion events are emitted after processing the last file assigned to that pack, before selecting the next file."

### Empty Destination Behavior
The spec doesn't clarify what happens when destination is empty.

**Recommended action:** CLARIFY

**Rationale:** Tests show when destination is empty or doesn't exist, NO PACK_LOADED events are emitted. Behavior matches checkpoint 2 first run. Should explicitly state: "When destination has no existing packs, omit PACK_LOADED events and proceed as checkpoint 2 pack strategy."

### FILE_SELECTED Emission for Unchanged Files
The spec doesn't clarify whether FILE_SELECTED is emitted before PACK_SKIP_UNCHANGED.

**Recommended action:** CLARIFY

**Rationale:** Tests show FILE_SELECTED is ALWAYS emitted, even for unchanged files. Sequence is:
1. FILE_SELECTED
2. PACK_SKIP_UNCHANGED (if unchanged) OR FILE_PACKED (if changed)
3. Pack completion event when pack is done

Should state: "FILE_SELECTED is emitted for all files, including those that will be skipped as unchanged."

## Solution Leaks

### Line 140: Critical Information Buried
> Packing algorithm reruns from scratch - files are repacked based on current order and size constraints

**Recommended action:** MOVE to main specification

**Rationale:** This is the ONLY place mentioning complete repacking, and it's in the "Key observations" section at the end. This is critical behavioral information that determines the entire implementation approach. Must be moved to deliverables or main spec section.

## Bias Phrases

No significant bias phrases identified. The spec appropriately describes outcomes without prescribing implementation approaches.

## Over-Specification

### Lines 34-40: Over-Spec
> All JSON events must be emitted in compact format:
> - No spaces after colons or commas
> - No trailing commas
> - One event per line, newline-terminated
>
> Field ordering shown in examples is for readability only...

**Recommended action:** REMOVE

**Rationale:** This is copied from checkpoints 1-3. Either reference checkpoint 1 or remove entirely (examples demonstrate format).

### Lines 42-52: Over-Spec
> ### Event Schema Reference
>
> **New events in checkpoint 4**:
> ...

**Recommended action:** CONDENSE

**Rationale:** Replace table with: "New events: PACK_LOADED, PACK_SKIP_UNCHANGED, PACK_UNCHANGED, PACK_UPDATED. See examples for field requirements."

## Ambiguities

### Line 7: Ambiguity
> **Note:** The `strategy.options.max_pack_bytes` constraint still applies when updating packs.

**Recommended action:** CLARIFY

**Rationale:** "Still applies" is vague. Does this mean:
- New packs respect the limit?
- Old packs that violate new limits are repacked?
- Something else?

Tests show complete repacking occurs regardless. Should state: "All files are repacked according to the current max_pack_bytes limit, regardless of previous pack structure."

### Lines 109-111: Confusing Example Setup
> Assume A changed (now 1 byte, was 3 bytes in pack), C changed (now 2 bytes, was 4 bytes), but B, D, E unchanged.
>
> Destination state: pack-1.tar (A-old), pack-2.tar (C-old), pack-3.tar (D,E)

**Recommended action:** CLARIFY

**Rationale:** This description conflicts with the first run example:
- First run: pack-1 = A+B (3 bytes), pack-2 = C (2 bytes), pack-3 = D+E (4 bytes)
- This example claims: pack-1 = A-old alone, pack-2 = C-old alone

Either the example is wrong or the first run output is inconsistent. Should clarify the initial state matches first run output.

### Line 48: Field Name Inconsistency
> | `PACK_SKIP_UNCHANGED` | `event`, `job_id`, `pack_id`, `path`, `size`, `hash` |

**Recommended action:** CLARIFY

**Rationale:** Uses `hash` field but other events (FILE_BACKED_UP, FILE_VERIFIED, FILE_SKIPPED_UNCHANGED from checkpoint 3) use `checksum`. Should use consistent naming across all checkpoints.

### Lines 135-140: Key Observations Should Be Requirements
The "Key observations" section contains critical behavioral requirements, not observations.

**Recommended action:** MOVE to main specification

**Rationale:** These are requirements:
- PACK_LOADED emitted after STRATEGY_SELECTED
- Unchanged files emit PACK_SKIP_UNCHANGED instead of FILE_PACKED
- Packs with all unchanged files emit PACK_UNCHANGED
- Packs with changes emit PACK_UPDATED
- **Packing algorithm reruns from scratch**

Move these to main spec as explicit requirements, not observations.

## Example Coverage Analysis

### What Examples Demonstrate Well
- First run (empty destination) behavior
- All files unchanged scenario
- Some files changed with PACK_UPDATED

### Missing Example Coverage
1. **PACK_CREATED event** - Example never shows a pack being created (both examples have 3 packs in both runs)
2. **Mixed pack outcomes** - Show run with PACK_CREATED, PACK_UPDATED, and PACK_UNCHANGED in same job
3. **Changed max_pack_bytes** - Demonstrate repacking when size limit changes
4. **Empty destination** - Show no PACK_LOADED events explicitly
5. **Complete pack structure change** - Show old packs (A), (C), (D+E) becoming (A+B), (C), (D+E)

**Recommendation:** Add example showing:
- Destination with 2 existing packs
- Current run produces 4 packs due to max_pack_bytes decrease
- Shows PACK_UPDATED for first 2, PACK_CREATED for new packs 3-4
- Demonstrates complete repacking behavior explicitly

## Overall Assessment

This checkpoint spec has **critical under-specification** that will cause widespread implementation failures:

1. **Most critical gap**: Complete repacking behavior is mentioned only once in "Key observations" (line 140), not in main spec
2. **PACK_LOADED events are misleading** without clarifying they're informational only
3. **No decision logic** for PACK_CREATED vs PACK_UPDATED vs PACK_UNCHANGED
4. **No timing specification** for pack completion events
5. **"Key observations" section contains requirements**, not observations
6. **Confusing example** (line 109-111) contradicts first run output
7. **Field naming inconsistency** (hash vs checksum)
8. **Missing PACK_CREATED example** despite it being a core event

The spec would benefit from:
- Moving line 140 to deliverables: "System repacks all files from scratch on each run"
- Adding explicit decision logic for pack completion events
- Clarifying PACK_LOADED is informational only
- Moving "Key observations" into main requirements
- Example demonstrating PACK_CREATED event
- Example showing pack structure change with max_pack_bytes change
- Consistent field naming across all checkpoints
- Fixing confusing example setup (lines 109-111)

The biggest issue is that the ONE sentence explaining complete repacking (line 140) is easily missed, causing implementers to build the wrong mental model where they try to preserve and update existing pack structures rather than repacking from scratch.