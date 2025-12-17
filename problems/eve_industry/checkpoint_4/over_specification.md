# Checkpoint 4 Over-Specification Analysis

## Summary
Introduces the plan command that creates build plans from a build string, generating CSV files for materials to buy and jobs to run.

## Overall Assessment

**Difficulty Rating:** Appropriate

**Primary Issues:**
- Build string format heavily prescribed (necessary for CLI)
- TE formula given explicitly (solution leak)
- CSV output format prescribed (necessary for auto-grading)
- Minimal examples for complex functionality

**Counts:** 1 solution leak, 2 redundant over-specs, 0 bias phrases

---

## Design Freedom Analysis

**What design decisions must the agent make?**

- **Build string parsing:** Prescribed - exact formats for 4 different cases
- **Material aggregation:** Agent chooses - how to sum buildable vs. non-buildable materials
- **Job planning:** Agent chooses - how to compute jobs from build requirements
- **Dependency resolution:** Agent chooses - spec doesn't prescribe how to recurse through build tree
- **TE calculation:** Prescribed - exact formula given in line 66
- **CSV output format:** Prescribed - exact headers and sorting required for auto-grading
- **Volume calculation:** Agent chooses - how to compute buy_volume

**Overall freedom:** Medium - Input/output formats are prescribed (necessary for CLI/auto-grading), but core build planning algorithm is left to agent. This is appropriate for a planning tool.

---

## Pattern-Matching Analysis

**Prose that maps directly to code:**

**Lines 6-25: Build String Parsing**
> ```
> {Item name} {Runs Per Job} x{Number of Jobs}
> {Item name} {Runs Per Job} {Material Efficiency} {Time Efficiency} x{Number of Jobs}
> {Item name} {RunsPerJob} {DecryptorName|None} x{NumJobs}
> {Item name} {RunsPerJob} {DecryptorName|None} {RelicName} x{NumJobs}
> ```

**Transcribes to:**
```python
def parse_build_string(build_str):
    parts = build_str.split()
    if 'x' in build_str:
        count = int(parts[-1].replace('x', ''))
        # ... parse other parts based on count
```

**Reasoning bypassed:**
Agent doesn't need to design input format. Just parse prescribed structure.

**Note:** This level of prescription is appropriate for CLI argument parsing. Input formats must be exact for user interface consistency.

---

**Line 66: TE Formula**
> "Full TE factor is `BP Time * (1- BP TE) * (1 - TE bonus)`"

**Transcribes to:**
```python
actual_time = bp_time * (1 - bp_te/100) * (1 - te_bonus/100)
```

**Reasoning bypassed:**
Formula given explicitly. Agent transcribes to code.

**Note:** This is carried over from Checkpoint 3, but now includes te_bonus from config.

---

**Lines 43-58: CSV Format and Sorting**
> ```
> name,to_buy,buy_volume,start_amount,end_amount
> name,runs,days,count
> ```
> "Sort materials by name"
> "Sort the jobs by: name > runs > count > days"

**Transcribes to:**
```python
materials_df.sort_values('name').to_csv('materials.csv', index=False)
jobs_df.sort_values(['name', 'runs', 'count', 'days']).to_csv('jobs.csv', index=False)
```

**Reasoning bypassed:**
Output format is prescribed. Agent just formats data to spec.

**Note:** CSV output formats must be prescribed for auto-grading. This is justified.

---

## Example Inference Analysis

**Do examples force reasoning or just copying?**

**Example 1: Barrage L Invention (10 runs × 10 jobs)**
- **Inference requirement:** Medium
- **Rationale:** Shows invention job planning. Agent must understand that invention creates blueprints, which are then used for manufacturing. Must compute total materials needed across all jobs.
- **Missing edge cases:** Simple case with only buying materials, no intermediate builds

**Example 2: Barrage L Manual ME/TE (10 runs × 10 jobs)**
- **Inference requirement:** Medium
- **Rationale:** Shows how ME/TE from build string affect materials and time. Agent must apply ME formula to reduce materials and TE formula to reduce time.
- **Missing edge cases:** Complex build tree with multiple levels, buildable components

**Overall:** Examples show two contrasting cases (invention vs. manual ME/TE), but don't demonstrate the full build tree complexity. Agent must infer:
- How to aggregate materials across multiple jobs
- How to compute buy_volume (not explained)
- What start_amount and end_amount mean (both 0 in examples)

With only 2 simple examples, agents need to make reasonable inferences about build planning behavior.

---

## Issues (Sequential by Line Number)

### Lines 6-25: Appropriate Specification - Build String Formats

**Note:** The build string formats are appropriately prescribed. CLI argument parsing requires exact format specification for user interface consistency. This is not over-specification.

---

### Lines 28-32: Ambiguity - Build String Parsing Rules

> "* {Item Name} is always the PRODUCT not the recipe.
> * If x{Number of Jobs} is not present, assume it is 1.
> * In the Item format, if {Runs Per Job} is not present, assume it is 1."

**Note:** These are necessary clarifications for input parsing. Not over-specification.

---

### Lines 38-48: Appropriate Specification - CSV Headers

> "```
> name,to_buy,buy_volume,start_amount,end_amount
> name,runs,days,count
> ```"

**Note:** CSV headers must be prescribed for auto-grading. Not over-specification.

---

### Line 49: Redundant Over-Spec - Material Sorting

> "Sort materials by name. There should not be any duplicated names."

**Problem:**
Examples already show materials in alphabetical order. The sorting rule is visible from the examples.

**Fix:** CONDENSE

**Replace:**
> "Sort materials by name. There should not be any duplicated names."

**With:**
> "Materials are sorted and deduplicated by name (see examples)."

**Why condense:**
Examples demonstrate the sorting. "Deduplicated" is necessary to clarify that multiple occurrences are summed, but "sort by name" is redundant with examples.

---

### Line 56: Redundant Over-Spec - Job Sorting

> "Sort the jobs by: name > runs > count > days"

**Problem:**
Examples show jobs sorted this way. The pattern is visible from example output.

**Fix:** CONDENSE

**Replace:**
> "Sort the jobs by: name > runs > count > days"

**With:**
> "Jobs are sorted (see examples for order)."

**Why condense:**
Examples demonstrate the multi-level sorting. Let agent infer the sort key order from examples.

---

### Line 66: Solution Leak - TE Formula

> "Full TE factor is BP Time * (1- BP TE) * (1 - TE bonus)"

**Problem:**
Provides complete formula for time calculation. This is a solution leak from Checkpoint 3, now with config te_bonus added.

**Fix:** CONDENSE

**Replace:**
> "Full TE factor is BP Time * (1- BP TE) * (1 - TE bonus)"

**With:**
> "Blueprint TE and config te_bonus both affect job time. See examples."

**Why condense:**
Examples show the result of TE application. Agent should discover the formula from comparing examples with different TE values. However, since this formula was already given in Checkpoint 3, agents may already know it. Consider this a lower priority fix.

---

### Lines 73-112: Minimal Examples for Complex Functionality

**Problem:**
The checkpoint introduces complex build planning (materials aggregation, job creation, buildable item handling) but provides only 2 examples:
1. Invention case (Barrage L)
2. Manual ME/TE case (Barrage L)

Neither example shows:
- Build tree with multiple levels (building components from raw materials)
- start_amount or end_amount being non-zero
- buy_volume calculation approach
- Complex material aggregation

**Fix:** ADD EXAMPLES

**Add example showing:**
1. Item with buildable components (e.g., a Tech I ship that requires materials that are themselves buildable)
2. Multi-level build tree to demonstrate recursive material planning
3. Non-zero start_amount/end_amount to clarify what these fields mean

**Why needed:**
Current examples only show single-level builds (buy materials → produce item). Agent must infer how to handle multi-level dependency trees without any examples demonstrating this behavior.

---

## Example Coverage Assessment

### Example 1: Barrage L Invention

**What this demonstrates:**
- Invention build string format
- Materials CSV with to_buy quantities
- Jobs CSV with single job type
- buy_volume calculation
- days calculation with te_bonus

**Edge cases shown:**
None - standard successful case

**Edge cases missing:**
- Multi-level build tree
- Buildable components (all materials in this example must be bought)
- Multiple job types in output
- start_amount/end_amount usage
- Invalid build string

**Inference requirement:** Medium

Agent must understand invention produces blueprints which are used for manufacturing.

**Assessment:** Adequate for invention case, but doesn't demonstrate build tree complexity

---

### Example 2: Barrage L Manual ME/TE

**What this demonstrates:**
- Manual ME/TE build string format
- ME reducing to_buy quantities
- TE reducing job days
- Same item with different parameters

**Edge cases shown:**
None

**Edge cases missing:**
- Same as Example 1
- Different items
- Jobs with different runs/count values

**Inference requirement:** Medium

Agent must apply ME/TE formulas from previous checkpoints.

**Assessment:** Demonstrates parameter effects but not build complexity

---

## Recommended Changes

**Prose to remove:**
None - most prose is necessary CLI specification

**Prose to condense:**
1. Line 49: Material sorting (redundant with examples)
2. Line 56: Job sorting (redundant with examples)
3. Line 66: TE formula (reduce to outcome statement)

**Examples to enhance:**
1. **Add Example 3:** Multi-level build showing buildable components
   - Example: "Naga 1 10 20 x1" where some materials are buildable
   - Shows jobs.csv with multiple job types (component builds)
   - Shows materials.csv with both to_buy and buildable items
   - Demonstrates start_amount/end_amount usage

2. **Add Example 4:** Complex build tree
   - Example with 3+ levels of dependency
   - Shows recursive material planning

**Examples to simplify:**
None - only 2 examples is already minimal

---

## Priority Fixes

**Must fix (missing examples):**
1. Add multi-level build example - current examples don't demonstrate core build tree planning

**Should fix (significant over-specification):**
1. Line 66: TE formula - repeated from Checkpoint 3
2. Lines 49, 56: Sorting rules - redundant with examples

**Consider fixing (polish):**
None beyond the above

---

## Difficulty Assessment

**Current difficulty:** Appropriate (but could be improved with better examples)

**Reasoning:**
- **Design freedom:** Medium - Input/output prescribed (justified), but build planning algorithm is agent's choice
- **Pattern-matching:** Medium - Some formulas given, but core planning logic is not prescribed
- **Example inference:** Medium/High - Examples show simple cases; agent must infer complex build tree handling

**Key factors:**
1. Build planning algorithm not prescribed - agent must design dependency resolution
2. Material aggregation logic not prescribed - agent must sum across build tree
3. Output format prescribed - justified for CLI and auto-grading
4. TE formula prescribed - carried over from Checkpoint 3

**Not "too easy" because:**
- Agent must design build tree traversal algorithm
- Material aggregation across multiple jobs requires planning
- Dependency resolution not specified
- start_amount/end_amount semantics not explained
- buy_volume calculation approach not prescribed

**Not "too hard" because:**
- Examples demonstrate expected behavior
- Input/output formats are clear
- Previous checkpoints establish ME/TE handling

**Recommended difficulty improvements:**
1. **Add multi-level build example** - clarify expected behavior for complex builds
2. **Remove TE formula** - let agent carry forward from Checkpoint 3 or rediscover
3. **Remove sorting prescriptions** - let agent infer from examples
4. **Add edge case example** - show start_amount/end_amount usage

**Assessment:** Difficulty is appropriate for a build planning checkpoint. The main issue is insufficient examples demonstrating complex build trees, which creates ambiguity rather than over-specification. The spec trusts agents to infer reasonable build planning behavior from minimal examples.
