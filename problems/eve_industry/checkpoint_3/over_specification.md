# Checkpoint 3 Over-Specification Analysis

## Summary
Extends the recipe command to support Material Efficiency (ME) and Time Efficiency (TE) flags, showing how blueprint improvements reduce material costs and build time.

## Overall Assessment

**Difficulty Rating:** Too Easy

**Primary Issues:**
- Complete ME formula provided (major solution leak)
- TE impact described explicitly
- Waste calculation spelled out
- Examples exhaustively demonstrate every combination

**Counts:** 3 solution leaks, 4 redundant over-specs, 0 bias phrases

---

## Design Freedom Analysis

**What design decisions must the agent make?**

- **ME calculation:** Prescribed - exact formula given in line 11
- **TE calculation:** Prescribed - implicit from "at the seconds level"
- **Waste calculation:** Prescribed - difference between base and ME-adjusted
- **Reactions exclusion:** Prescribed - explicit error message and exit code
- **Output format:** Prescribed - exact column structure for --display-waste
- **Parameter validation:** Prescribed - exact ranges and error handling

**Overall freedom:** Very Low - formulas and behavior completely prescribed

---

## Pattern-Matching Analysis

**Prose that maps directly to code:**

**Lines 9-12: ME Formula**
> "To calculate the amount needed you can use:
> ```
> Amount needed = ceil(max(1,quantity required per run * (1 - ME/100) * num_runs))
> ```"

**Transcribes to:**
```python
def calculate_materials(base_quantity, me, num_runs=1):
    return math.ceil(max(1, base_quantity * (1 - me/100) * num_runs))
```

**Reasoning bypassed:**
Agent doesn't need to:
- Discover the formula from examples
- Understand how ME percentage affects quantities
- Figure out the ceiling and max(1) edge case handling
- Reverse-engineer the calculation from example outputs

Agent just transcribes the mathematical formula to code.

---

**Lines 64-77: Waste Calculation**
> Shows examples with Waste column containing difference between ME=0 and ME=5 quantities

**Transcribes to:**
```python
waste = quantity_without_me - quantity_with_me
```

**Reasoning bypassed:**
Simple subtraction. No discovery required.

---

**Lines 109-112: Reactions Error Handling**
> "However if we were to try to do this with a reaction you exit with code=1 and print to stderr:
> ```
> ERROR: <item name> cannot be used with ME
> ```"

**Transcribes to:**
```python
if activity_type == "Reactions" and me > 0:
    sys.stderr.write(f"ERROR: {item_name} cannot be used with ME\n")
    sys.exit(1)
```

**Reasoning bypassed:**
Exact error message and exit code given. No design decision required.

---

## Example Inference Analysis

**Do examples force reasoning or just copying?**

**Examples 1-3: Naga with ME variations (0, 10, 5)**
- **Inference requirement:** Low
- **Rationale:** Shows three ME levels with formula already given. Agent can verify formula works. No pattern discovery needed.
- **Missing edge cases:** ME boundaries (ME=1, ME=9), fractional edge cases

**Example 4: Naga with ME=5 and --display-waste**
- **Inference requirement:** Very Low
- **Rationale:** Waste is obviously the difference between base and ME-adjusted quantities. Examples make this trivial.
- **Missing edge cases:** Waste display with ME=0 (should be all zeros?)

**Example 5: Naga with TE=20 only**
- **Inference requirement:** Low
- **Rationale:** Shows time reduction. Straightforward application of TE.
- **Missing edge cases:** Various TE values (TE=2, TE=10, etc.)

**Example 6: Naga with ME=10 and TE=20**
- **Inference requirement:** Very Low
- **Rationale:** Combines both modifiers. Both formulas already given.
- **Missing edge cases:** None

**Overall:** Examples are arithmetic verification exercises. With formulas provided, there's no inference or discovery required. Agent applies formula to each example and checks output matches.

---

## Issues (Sequential by Line Number)

### Lines 1-4: Appropriate Specification - Flag Introduction

**Note:** The flag definitions (--material-efficiency, --time-efficiency, --display-waste) are appropriately specified. CLI flags need explicit parameter definitions for auto-grading.

---

### Lines 6-8: Redundant Over-Spec - ME Scope and Range

> "**Material Efficiency(ME)** represents the percent less of base materials, per run, to use
> * Only **Manufacturing** jobs are impacted by this. Not Reactions.
> * It must be an integer in `[0,10]`"

**Problem:**
While the range is necessary, the "percent less" description is redundant with the formula. The formula (line 11) already defines what ME means mathematically.

**Fix:** CONDENSE

**Replace:**
> "**Material Efficiency(ME)** represents the percent less of base materials, per run, to use
> * Only **Manufacturing** jobs are impacted by this. Not Reactions.
> * It must be an integer in `[0,10]`"

**With:**
> "**Material Efficiency (ME):** Integer in [0,10]. Only applies to Manufacturing jobs (see error handling). See examples for calculation."

**Why condense:**
The formula and examples show how ME works. "Percent less" is redundant. Focus on constraints (range, manufacturing-only) and let examples demonstrate the calculation.

---

### Lines 9-12: Solution Leak - Complete ME Formula

> "To calculate the amount needed you can use:
> ```
> Amount needed = ceil(max(1,quantity required per run * (1 - ME/100) * num_runs))
> ```"

**Problem:**
Provides the complete formula for material calculation. This is the core algorithm of the checkpoint. By providing it explicitly, the task becomes arithmetic transcription rather than formula discovery.

**Fix:** CONDENSE

**Current text (lines 9-12):**
> [Complete formula with ceiling and max(1)]

**Replace with:**
> "ME reduces material quantities as a percentage. See examples showing ME=0, ME=5, and ME=10 to understand the calculation. Note that quantities are always at least 1."

**Why condense:**
The checkpoint should require agents to:
1. Compare examples with different ME values
2. Discover the percentage reduction formula
3. Infer the ceiling operation from integer outputs
4. Discover the max(1) edge case from examples (if provided)

Without the formula, agents must reverse-engineer from examples:
- Naga ME=0: Isogen 26000
- Naga ME=10: Isogen 23400
- Reduction: 23400/26000 = 0.90 = (1 - 10/100)

This transforms it from "transcribe formula" to "discover formula from examples."

---

### Lines 14-16: Solution Leak - TE Formula Hint

> "**Time Efficiency** is similar to but at the _seconds_ level.
> * It must be an _even_ integer in the range of `[0,20]`."

**Problem:**
"Similar to" reveals that TE uses the same percentage reduction formula as ME. This removes the need to discover the TE formula independently.

**Fix:** CONDENSE

**Replace:**
> "**Time Efficiency** is similar to but at the _seconds_ level.
> * It must be an _even_ integer in the range of `[0,20]`."

**With:**
> "**Time Efficiency (TE):** Even integer in [0,20]. Reduces build time. See examples."

**Why condense:**
Don't reveal the formula structure. Let agent discover from examples (250 minutes → 200 minutes with TE=20).

---

### Lines 64-77: Redundant Over-Spec - Waste Column Examples

> Shows example with Waste column:
> "| Item      | Quantity  |Waste   | Buildable |
> |:---------:|:---------:|:-----:|----------:|
> | Isogen    | 24700     | 1300  | No        |"

**Problem:**
The waste calculation (difference between base and ME-adjusted) is obvious from the column values. The examples show quantity=24700 and waste=1300, making it clear that waste = 26000 - 24700. This is redundant with what anyone can calculate from the numbers.

**Fix:** Keep examples but remove any prose explanation of waste calculation (there isn't explicit prose, which is good).

**Assessment:** Not over-specified - examples demonstrate without explicit formula, which is appropriate.

---

### Lines 109-112: Solution Leak - Reactions Error Message

> "However if we were to try to do this with a reaction you exit with code=1 and print to stderr:
> ```
> ERROR: <item name> cannot be used with ME
> ```"

**Problem:**
Prescribes exact error message and behavior. While necessary for auto-grading, this removes the need for agents to understand WHY reactions don't use ME.

**Fix:** Appropriate as-is for auto-grading requirements.

**Note:** CLI error messages need to be exact for testing. This is justified prescription.

---

### Lines 19-107: Redundant Over-Spec - Exhaustive Examples

**Problem:**
The spec provides 6 examples showing every combination:
1. ME=0 (baseline)
2. ME=10 (max)
3. ME=5 (middle)
4. ME=5 with --display-waste
5. TE=20 only
6. ME=10 + TE=20 (combined)

This is redundant. Examples 1, 2, and 5 would be sufficient to demonstrate the patterns. Examples 3, 4, and 6 are verification cases that don't add new information.

**Fix:** SIMPLIFY EXAMPLES

**Keep:**
- Example 1: ME=0 (baseline)
- Example 2: ME=10 (shows maximum ME)
- Example 5: TE=20 only (shows TE effect)

**Remove or consolidate:**
- Example 3: ME=5 (redundant - agent can infer from ME=0 and ME=10)
- Example 4: ME=5 with --display-waste (show waste with one example, not two)
- Example 6: ME=10 + TE=20 (agent should be able to combine independently)

**Why simplify:**
With formula given, all 6 examples are verification exercises. If formula is removed (as recommended), 3 strategic examples are sufficient for pattern discovery:
- ME=0 baseline
- ME=10 maximum
- TE=20 time reduction

Agent must interpolate ME=5 and discover waste calculation from these patterns.

---

## Example Coverage Assessment

### Examples 1-3: ME Variations

**What these demonstrate:**
- ME=0 baseline
- ME=10 maximum reduction
- ME=5 middle value
- Material quantity changes

**Edge cases shown:**
None - all successful cases

**Edge cases missing:**
- ME=1 (minimum non-zero)
- ME with quantity that rounds to 0 (max(1) case)
- Reactions error case

**Inference requirement:** Low with formula; Medium without formula

**Assessment:** Redundant with formula provided; adequate for pattern discovery if formula removed

---

### Example 4: Waste Display

**What this demonstrates:**
- --display-waste flag
- Waste column format
- Waste calculation (difference)

**Edge cases shown:**
None

**Edge cases missing:**
- Waste with ME=0 (all zeros?)
- Waste with ME=10

**Inference requirement:** Very Low

Waste is obviously the difference. No challenge.

**Assessment:** Redundant - waste calculation is trivial

---

### Example 5-6: TE Examples

**What these demonstrate:**
- TE reduces time
- ME and TE can be combined
- Materials unchanged by TE

**Edge cases shown:**
None

**Edge cases missing:**
- Various TE values (TE=2, TE=10)
- TE with reactions (should work)

**Inference requirement:** Low

**Assessment:** Adequate for showing TE, but formula makes it trivial

---

## Recommended Changes

**Prose to remove:**
None - most prose is parameter definitions

**Prose to condense:**
1. Lines 9-12: ME formula (give examples, not formula)
2. Lines 6-8: ME description (remove "percent less", just give constraints)
3. Lines 14-16: TE description (remove "similar to" hint)

**Examples to enhance:**
1. Add reactions error case
2. Add ME edge case where max(1) matters

**Examples to simplify:**
1. Remove example 3 (ME=5) - agent can interpolate
2. Remove example 6 (ME+TE combined) - agent should combine independently
3. Consolidate waste display to one example

---

## Priority Fixes

**Must fix (biggest solution leaks):**
1. Lines 9-12: ME formula - this is THE core algorithm; prescribing it removes all challenge
2. Lines 14-16: TE "similar to" hint - reveals formula structure

**Should fix (significant over-specification):**
1. Lines 19-107: Too many examples - reduce to 3 strategic cases
2. Lines 6-8: Redundant ME description

**Consider fixing (polish):**
None beyond the above

---

## Difficulty Assessment

**Current difficulty:** Too Easy

**Reasoning:**
- **Design freedom:** Very Low - formulas completely prescribed
- **Pattern-matching:** Very High - formulas map directly to arithmetic code
- **Example inference:** Low - examples verify formula rather than enabling discovery

**Key contributors to "too easy":**
1. Complete ME formula with ceiling and max(1) (lines 9-12) - removes algorithm design
2. TE "similar to" hint (line 14) - reveals formula structure
3. Exhaustive examples (6 examples) - every combination shown, no interpolation needed
4. Waste calculation obvious from column values - no discovery required

**What makes it too easy:**
An agent can implement this checkpoint by:
1. Reading the ME formula
2. Transcribing to code (simple arithmetic)
3. Copying error message from spec
4. Adding waste column (simple subtraction)

No discovery, minimal inference, no problem-solving required.

**Recommended difficulty improvements:**
1. **Remove ME formula** - provide examples at ME=0, ME=10; agent must discover formula and edge cases
2. **Remove "similar to" TE hint** - let agent discover TE formula from time examples
3. **Reduce examples to 3** - ME=0, ME=10, TE=20 only; agent must interpolate ME=5 and combine ME+TE
4. **Add edge case example** - show material with quantity=1 at ME=0 to illustrate max(1) behavior
5. **Remove waste formula prose** - waste is obviously difference; let agent discover from column

With these changes, the checkpoint becomes:
- Analyze ME=0 vs ME=10 examples to discover percentage formula
- Discover ceiling operation from integer outputs
- Discover max(1) from edge case example
- Discover TE formula from time reduction example
- Interpolate intermediate values (ME=5)
- Combine ME+TE independently

This transforms it from "transcribe formula" to "discover formula from examples" - a more substantial challenge.

**Current state:** Formula given → arithmetic transcription → trivial
**Improved state:** Examples only → formula discovery → appropriate difficulty
