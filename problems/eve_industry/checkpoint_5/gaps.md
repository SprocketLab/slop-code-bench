# Checkpoint 5 Gap Analysis

## Summary
Extends the `plan` command with `--build-all` flag to recursively build all buildable components, and adds job splitting for long-duration jobs based on `split_days` config.

**Total behaviors tested:** 12
**True gaps found:** 3
**Not gaps (inferrable):** 8
**Over-specified (handled in over-spec rubric):** 1

---

## Test Behaviors Analysis

### Job Splitting Algorithm Details

**What tests expect:**
Jobs split so all resulting jobs are within 1 run of each other.
Example: 13 runs with 4-run limit → 1×4 runs + 3×3 runs (not 3×4 + 1×1).

**In spec examples?**
Yes - Lines 16-17 provide this specific example.

**In spec prose?**
Partial - Lines 14-18:
> "Split the job so that none breach the min(30,split_days) day threshold, and all are within 1 run of each other."

But:
1. Algorithm to achieve "within 1 run" not specified
2. How to handle remainders not explicit
3. Whether to prefer larger or smaller jobs not stated

**Can agent infer this?**

*Standard practice?* Partially - even distribution is common.

*Pattern in examples?* Yes - example shows the expected result.

*Clear from context?* No - "within 1 run of each other" describes the goal but not the algorithm.

*Could implementations reasonably differ?* Yes - multiple algorithms could satisfy "within 1 run":
- (13 runs, 4 limit) → 4,3,3,3 ✓
- (13 runs, 4 limit) → 3,3,3,4 ✓
- Different distribution orders

**Verdict:** TRUE GAP

**Fix:** CLARIFY

**Current text (lines 14-18):**
> "Split the job so that none breach the min(30,split_days) day threshold, and all are within 1 run of each other. For example: Say I have 13 runs you need to do in total. But 4 runs is 30 days. You should split them into 1 job of 4 runs and 3 jobs of 3 runs. INSTEAD of 3 runs of 4 jobs and a 1 run job."

**Ambiguity:**
The example shows ONE valid output but doesn't specify the algorithm. Questions:
1. How to determine number of jobs?
2. How to distribute runs across jobs?
3. What order should jobs appear in output?

**Replace with:**
> "Job splitting algorithm:
> 1. Calculate max_runs_per_job = floor(split_days_threshold × 86400 / time_per_run_seconds)
> 2. Calculate num_jobs = ceil(total_runs / max_runs_per_job)
> 3. Base runs per job = floor(total_runs / num_jobs)
> 4. Extra runs to distribute = total_runs mod num_jobs
> 5. Create `extra_runs` jobs with `base + 1` runs, and `num_jobs - extra_runs` jobs with `base` runs
> 6. Larger jobs (base+1 runs) come first in output
>
> Example: 13 total runs, max 4 per job:
> - num_jobs = ceil(13/4) = 4
> - base = floor(13/4) = 3
> - extra = 13 mod 4 = 1
> - Result: 1 job of 4 runs, 3 jobs of 3 runs"

**Why this is needed:**
"Within 1 run of each other" is a constraint, not an algorithm. Multiple valid outputs exist. The example implies a specific algorithm (maximize first, minimize rest) but this should be explicit.

---

### Build-All Recursion Depth and Material Tracking

**What tests expect:**
For `Barrage L 10 None x10` with `--build-all`:
- Builds Barrage L
- Builds its materials (Fernite Carbide, Fullerides, etc.)
- Builds materials of materials (fuel blocks, reaction components)
- Continues until only raw materials remain

Output shows all intermediate jobs and final raw materials to buy.

**In spec examples?**
Yes - Comprehensive example showing full build tree.

**In spec prose?**
Partial - Line 1: "assumes you are building ALL BUILDABLE items in the tree"

**Can agent infer this?**

*Standard practice?* Yes - recursive tree traversal is standard.

*Pattern in examples?* Yes - examples show the complete output.

*Clear from context?* Mostly - "buildable" from Checkpoint 1 defines what to recurse on.

*Could implementations reasonably differ?* Somewhat - stopping conditions, rounding, aggregation might vary.

**Verdict:** NOT A GAP (inferrable from example)

---

### Component BPO ME/TE Defaults

**What tests expect:**
Components use ME/TE from `component_bpo_defaults` in config.

**In spec examples?**
Yes - Config shows `me: 10, te: 20` defaults.

**In spec prose?**
Yes - Lines 7-11:
```yaml
component_bpo_defaults:
  me: <int in [0,10]>
  te: <int in [0,20]>
```

**Can agent infer this?**

*Standard practice?* N/A.

*Pattern in examples?* Yes.

*Clear from context?* Yes - config field name is clear.

*Could implementations reasonably differ?* No.

**Verdict:** NOT A GAP

---

### Reactions Also Subject to split_days

**What tests expect:**
Reaction jobs (like Fernite Carbide Reaction Formula) are split when exceeding split_days.
Example with split_days=3: Fernite Carbide Reaction Formula becomes 2 jobs of 15 runs instead of 1 job of 30 runs.

**In spec examples?**
Yes - Examples show reaction jobs being split.

**In spec prose?**
Not explicitly - spec doesn't mention if reactions follow same splitting rules.

**Can agent infer this?**

*Standard practice?* N/A.

*Pattern in examples?* Yes - examples show reaction splitting.

*Clear from context?* Yes - no reason to exempt reactions.

*Could implementations reasonably differ?* No - examples are clear.

**Verdict:** NOT A GAP (demonstrated in examples)

---

### Materials with end_amount > 0 (Leftover Products)

**What tests expect:**
When building components, leftover output goes to `end_amount`.
Example: Fernite Carbide shows `to_buy=0, end_amount=6000` - we produce more than needed and have leftovers.

**In spec examples?**
Yes - Example shows materials with non-zero end_amount.

**In spec prose?**
No - Column meanings not explained (same gap as Checkpoint 4).

**Can agent infer this?**

*Standard practice?* Yes - tracking inventory in/out is standard.

*Pattern in examples?* Yes - can see pattern in output.

*Clear from context?* Partially - "end_amount" suggests leftover inventory.

*Could implementations reasonably differ?* Yes - depends on column definitions.

**Verdict:** TRUE GAP (inherited from Checkpoint 4)

**Note:** This is the same gap as Checkpoint 4 materials.csv column definitions.

---

### Jobs with Single Run Can't Split

**What tests expect:**
Jobs with only 1 run cannot be split even if they exceed split_days.
Example: Revelation Blueprint shows 1 run at 18.52 days (exceeds split_days=3) but remains 1 job.

**In spec examples?**
Yes - Revelation example shows 1-run jobs not split.

**In spec prose?**
Yes - Line 18: "You can ONLY split jobs that have more than 1 run."

**Can agent infer this?**

*Standard practice?* Yes - can't split 1 into multiple.

*Pattern in examples?* Yes.

*Clear from context?* Yes - explicitly stated.

*Could implementations reasonably differ?* No.

**Verdict:** NOT A GAP

---

### split_days Capped at 30

**What tests expect:**
Even if config has split_days > 30, effective threshold is min(30, split_days).

**In spec examples?**
Yes - Config comment says `split_days: 30 # <float <= 30>`.

**In spec prose?**
Yes - Line 15: "min(30,split_days)" threshold.

**Can agent infer this?**

*Standard practice?* N/A.

*Pattern in examples?* Yes.

*Clear from context?* Yes - explicit formula.

*Could implementations reasonably differ?* No.

**Verdict:** NOT A GAP

---

### Quantity Calculations with ME for Components

**What tests expect:**
Component quantities calculated using ME formula, then recursively determine sub-component needs.

**In spec examples?**
Yes - Material quantities in example reflect ME=10.

**In spec prose?**
Implied - Uses `component_bpo_defaults` for ME.

**Can agent infer this?**

*Standard practice?* Yes - ME applies to all manufacturing.

*Pattern in examples?* Yes.

*Clear from context?* Yes - follows from Checkpoint 3.

*Could implementations reasonably differ?* No.

**Verdict:** NOT A GAP

---

### Job Count Aggregation

**What tests expect:**
Multiple jobs with same name/runs/days get aggregated into single row with higher `count`.
Example: `Auto-Integrity Preservation Seal Blueprint,222,2.96,4` - 4 identical jobs.

**In spec examples?**
Yes - Examples show aggregated counts.

**In spec prose?**
No - Not explicitly stated that identical jobs are combined.

**Can agent infer this?**

*Standard practice?* Yes - aggregation is common in reports.

*Pattern in examples?* Yes - can see the pattern.

*Clear from context?* Partially - sorting rule includes "count" suggesting jobs can have count > 1.

*Could implementations reasonably differ?* Yes - might output separate rows instead.

**Verdict:** TRUE GAP (minor)

**Fix:** CLARIFY

**Add to spec:**
> "Jobs with identical `name`, `runs`, and `days` should be aggregated into a single row with the combined `count`."

**Why this is needed:**
Without this, agents might output each job on separate rows, which would technically work but produce different output format.

---

### Materials Aggregation Across Build Tree

**What tests expect:**
All materials summed across the entire build tree, no duplicates.

**In spec examples?**
Yes - Materials show aggregated totals.

**In spec prose?**
Yes - Lines 42-48: "all external purchases summed" and "no duplicated names".

**Can agent infer this?**

*Standard practice?* Yes.

*Pattern in examples?* Yes.

*Clear from context?* Yes.

*Could implementations reasonably differ?* No.

**Verdict:** NOT A GAP

---

### Fuel Block Builds at Component Defaults

**What tests expect:**
Fuel blocks (buildable items) use component_bpo_defaults ME/TE.

**In spec examples?**
Yes - Fuel block jobs appear in output.

**In spec prose?**
Implied - all buildable items use defaults.

**Can agent infer this?**

*Standard practice?* Yes.

*Pattern in examples?* Yes.

*Clear from context?* Yes.

*Could implementations reasonably differ?* No.

**Verdict:** NOT A GAP

---

### Complex Build Tree Ordering

**What tests expect:**
Jobs sorted by name > runs > count > days, regardless of build tree depth.

**In spec examples?**
Yes - Large examples show sorted output.

**In spec prose?**
Inherited from Checkpoint 4 - same sorting rule.

**Can agent infer this?**

*Standard practice?* Yes.

*Pattern in examples?* Yes.

*Clear from context?* Yes.

*Could implementations reasonably differ?* No.

**Verdict:** NOT A GAP

---

## Summary of Gaps

**Critical gaps (test failures):**
1. Job splitting algorithm - "within 1 run of each other" describes constraint but not algorithm
2. Job count aggregation - not stated that identical jobs combine into single row
3. Materials end_amount semantics - inherited from Checkpoint 4

**Ambiguous specifications (need clarification):**
1. Split job ordering - should larger jobs come first?

**Not gaps (agent should infer):**
1. Build-all recursion - examples demonstrate clearly
2. Component BPO defaults - explicitly specified
3. Reactions subject to splitting - shown in examples
4. Single-run jobs can't split - explicitly specified
5. split_days capped at 30 - explicitly specified
6. ME applies to components - follows from Checkpoint 3
7. Materials aggregation - explicitly specified
8. Job sorting - inherited from Checkpoint 4

---

## Recommended Additions

**New examples needed:**
None - examples are comprehensive.

**Prose clarifications needed:**
1. Lines 14-18: Add explicit splitting algorithm (max runs calculation, distribution formula, job ordering)
2. Add after line 57 (from Checkpoint 4): "Jobs with identical name, runs, and days should be aggregated into a single row with combined count"
3. Inherit Checkpoint 4 fix: Materials.csv column definitions including end_amount semantics
