# Checkpoint 5 Over-Specification Analysis

## Summary
Adds --build-all flag to plan command that builds all buildable items in the dependency tree, with job splitting for long-duration jobs based on configurable thresholds.

## Overall Assessment

**Difficulty Rating:** Too Easy

**Primary Issues:**
- Complete job splitting algorithm prescribed (major solution leak)
- Splitting logic detailed with step-by-step instructions
- Examples exhaustively demonstrate every splitting scenario
- Config fields and semantics fully prescribed

**Counts:** 2 solution leaks, 1 redundant over-spec, 0 bias phrases

---

## Design Freedom Analysis

**What design decisions must the agent make?**

- **Job splitting algorithm:** Prescribed - exact algorithm with steps (lines 14-18)
- **Split threshold calculation:** Prescribed - min(30, split_days) formula
- **Run distribution:** Prescribed - "all within 1 run of each other"
- **Build-all semantics:** Partially prescribed - "ALL BUILDABLE" but how to determine this requires inference
- **Component defaults:** Prescribed - config specifies ME/TE for components
- **Config parsing:** Prescribed - exact field names and types
- **CSV output:** Prescribed (from Checkpoint 4)

**Overall freedom:** Low - Job splitting algorithm is completely prescribed; only build tree traversal is left to agent

---

## Pattern-Matching Analysis

**Prose that maps directly to code:**

**Lines 14-18: Job Splitting Algorithm**
> "* If the real time (time less TE) for a job takes > **min(30,split_days) days**, then you will need to split the job up into multiple jobs
> * Split the job so that none breach the min(30,split_days) day threshold, and all are within 1 run of each other. For example:
> * Say I have 13 runs you need to do in total. But 4 runs is 30 days. You should split them into 1 job of 4 runs and 3 jobs of 3 runs. INSTEAD of 3 runs of 4 jobs and a 1 run job.
> * You can ONLY split jobs that have more than 1 run."

**Transcribes to:**
```python
def split_job(total_runs, time_per_run, split_threshold):
    max_runs_per_job = int(split_threshold / time_per_run)
    if max_runs_per_job >= total_runs or total_runs == 1:
        return [(total_runs, 1)]  # No split needed

    # Calculate split: all jobs within 1 run of each other
    num_jobs = math.ceil(total_runs / max_runs_per_job)
    runs_per_job = total_runs // num_jobs
    jobs_with_extra = total_runs % num_jobs

    jobs = []
    jobs.extend([(runs_per_job + 1, jobs_with_extra)])  # Jobs with extra run
    jobs.extend([(runs_per_job, num_jobs - jobs_with_extra)])  # Jobs with base runs
    return jobs
```

**Reasoning bypassed:**
Agent doesn't need to:
- Design a job splitting strategy
- Discover the "within 1 run" constraint
- Figure out how to distribute runs fairly
- Decide when to split vs. not split
- Understand the min(30, split_days) cap

Agent just transcribes the algorithm description to code.

---

**Lines 3-12: Config Field Specifications**
> ```yaml
> split_days: 3.0 # <float <= 30>
> component_bpo_defaults:
>   me: <int in [0,10]>
>   te: <int in [0,20]>
> ```

**Transcribes to:**
```python
config = yaml.safe_load(config_file)
split_days = min(30, config['split_days'])
component_me = config['component_bpo_defaults']['me']
component_te = config['component_bpo_defaults']['te']
```

**Reasoning bypassed:**
Config structure is prescribed. Agent just parses YAML and accesses fields.

---

## Example Inference Analysis

**Do examples force reasoning or just copying?**

**Example 1: Barrage L with split_days=30**
- **Inference requirement:** Low
- **Rationale:** Shows build-all functionality with no job splitting (all jobs under 30 days). Agent sees intermediate build jobs for components. With algorithm given, this is verification.
- **Missing edge cases:** Simple case without nested components

**Example 2: Barrage L with split_days=3**
- **Inference requirement:** Low
- **Rationale:** Shows job splitting in action. Fulleride Reaction Formula: 40 runs @ 4 days becomes 2 jobs of 20 runs @ 2 days each. Fernite Carbide: 30 runs @ 3 days becomes 2 jobs of 15 runs @ 1.5 days each. With algorithm given, agent just applies it.
- **Missing edge cases:** Edge cases mentioned in prose (1 job of 4 runs + 3 jobs of 3 runs)

**Example 3: Revelation x10 with split_days=3**
- **Inference requirement:** Low
- **Rationale:** Large complex build with many splits. Shows the "within 1 run" distribution pattern extensively. With algorithm given, this is pure verification at scale.
- **Missing edge cases:** Same examples could demonstrate discovery if algorithm wasn't given

**Overall:** Examples are comprehensive and demonstrate the splitting behavior extensively, but with the algorithm prescribed, they become verification exercises rather than pattern discovery opportunities.

---

## Issues (Sequential by Line Number)

### Lines 1-2: Appropriate Specification - Flag Introduction

**Note:** The --build-all flag introduction is appropriately specified. CLI flags need definition.

---

### Lines 3-12: Appropriate Specification - Config Fields

**Note:** Config file structure must be prescribed for YAML parsing. This is necessary specification, not over-specification. Type constraints (float <= 30, int in ranges) are appropriate.

---

### Lines 14-18: Solution Leak - Complete Job Splitting Algorithm

> "* If the real time (time less TE) for a job takes > min(30,split_days) days, then you will need to split the job up into multiple jobs
> * Split the job so that none breach the min(30,split_days) day threshold, and all are within 1 run of each other. For example:
> * Say I have 13 runs you need to do in total. But 4 runs is 30 days. You should split them into 1 job of 4 runs and 3 jobs of 3 runs. INSTEAD of 3 runs of 4 jobs and a 1 run job.
> * You can ONLY split jobs that have more than 1 run."

**Problem:**
Provides complete algorithm for job splitting with:
1. Threshold calculation (min(30, split_days))
2. Splitting criteria (real time > threshold)
3. Distribution strategy ("within 1 run of each other")
4. Explicit example showing correct distribution
5. Constraint (only split if > 1 run)

This is a major solution leak. The agent doesn't need to design any splitting strategy.

**Fix:** CONDENSE

**Current text (lines 14-18):**
> [Complete algorithm with distribution strategy and example]

**Replace with:**
> "Jobs with duration exceeding the configured split_days threshold should be divided into multiple jobs. The split_days threshold is capped at 30 days. Jobs are distributed to minimize imbalance. See examples showing split behavior."

**Why condense:**
The checkpoint should require agents to:
1. Discover splitting is needed from examples comparing split_days=30 vs split_days=3
2. Infer the threshold from example patterns
3. Discover the "within 1 run" distribution strategy by analyzing example outputs
4. Figure out edge cases (1-run jobs, threshold calculation)

Examples show:
- split_days=30: No splitting for Fulleride (4 days) or Fernite Carbide (3 days)
- split_days=3: Fulleride 40 runs becomes 2×20 runs, Fernite Carbide 30 runs becomes 2×15 runs

Agent should discover:
- Threshold = min(30, split_days) from behavior
- Distribution strategy from output patterns (20,20 not 25,15 for Fulleride)

This transforms it from "implement algorithm" to "discover algorithm from examples."

---

### Lines 22-101: Comprehensive Examples Appropriate for Complex Feature

**Note:** Unlike Checkpoint 3 where 6 examples were redundant, this checkpoint's 3 examples are justified:
1. Example 1 shows build-all without splitting (baseline)
2. Example 2 shows same build with splitting enabled (contrast)
3. Example 3 shows complex multi-level build with extensive splitting

These examples demonstrate the feature's complexity and are not redundant. They would be essential for pattern discovery if the algorithm were removed.

**Assessment:** Examples are appropriate, not over-specified.

---

### Lines 88-218: Verbose Output Table

**Problem:**
Example 3 (Revelation) has a 130-line job output table. This is comprehensive but potentially overwhelming.

**Assessment:** Not over-specification - this is realistic output demonstrating the feature at scale. Shows that splitting creates many jobs with the "within 1 run" pattern consistently applied.

**Verdict:** Appropriate for demonstrating complex build planning.

---

## Example Coverage Assessment

### Example 1: Barrage L with split_days=30

**What this demonstrates:**
- --build-all flag builds intermediate components
- Component ME/TE defaults from config
- No splitting when jobs are under threshold
- Complete build tree output

**Edge cases shown:**
None - standard successful case

**Edge cases missing:**
- Single job builds
- Jobs exactly at threshold
- Empty build trees

**Inference requirement:** Low with algorithm; High without algorithm

**Assessment:** Essential baseline example

---

### Example 2: Barrage L with split_days=3

**What this demonstrates:**
- Same build with different split_days
- Jobs split when exceeding threshold
- Split distribution pattern (2×20 for 40 total, 2×15 for 30 total)
- Comparison to Example 1 shows splitting effect

**Edge cases shown:**
None

**Edge cases missing:**
- Uneven splits (e.g., 13 runs → 4,3,3,3 from prose example)
- Single-run jobs (unsplittable)

**Inference requirement:** Low with algorithm; High without algorithm

Agent could discover splitting strategy by comparing to Example 1.

**Assessment:** Critical example for pattern discovery (if algorithm removed)

---

### Example 3: Revelation x10 with split_days=3

**What this demonstrates:**
- Large-scale complex build
- Many split jobs showing consistent distribution
- "Within 1 run" pattern extensively demonstrated (222/223, 28/29, etc.)
- Capital ship components build tree

**Edge cases shown:**
The "within 1 run" distribution pattern repeatedly:
- Auto-Integrity Preservation Seal: 4×222 runs + 2×223 runs (666 total)
- Carbon Fiber Reaction Formula: 3×28 runs + 35×29 runs (1099 total)

**Edge cases missing:**
None - this example is comprehensive

**Inference requirement:** Low with algorithm; High without algorithm

Agent could discover "within 1 run" distribution by analyzing the 222/223, 28/29 patterns.

**Assessment:** Excellent example for pattern discovery if algorithm removed

---

## Recommended Changes

**Prose to remove:**
None - config specifications are necessary

**Prose to condense:**
1. Lines 14-18: Job splitting algorithm (give outcome, remove algorithm details)

**Examples to enhance:**
1. Add the uneven split case mentioned in prose (13 runs → 1×4, 3×3) as Example 1.5
   - This would help agents discover the distribution algorithm

**Examples to simplify:**
None - 3 examples are appropriate for this complex feature

---

## Priority Fixes

**Must fix (biggest solution leaks):**
1. Lines 14-18: Complete job splitting algorithm - this is THE core algorithm of the checkpoint; prescribing it removes all challenge

**Should fix (significant over-specification):**
None beyond the algorithm

**Consider fixing (polish):**
1. Add prose example (13 runs case) as an actual test example for better pattern discovery

---

## Difficulty Assessment

**Current difficulty:** Too Easy

**Reasoning:**
- **Design freedom:** Low - Splitting algorithm completely prescribed
- **Pattern-matching:** Very High - Algorithm description maps directly to code
- **Example inference:** Low - Examples verify algorithm rather than enable discovery

**Key contributors to "too easy":**
1. Complete splitting algorithm with distribution strategy (lines 14-18) - removes algorithm design
2. Explicit "within 1 run" constraint - removes need to discover fair distribution
3. min(30, split_days) formula given - removes threshold discovery
4. Prose example (13 runs → 4,3,3,3) - shows exact distribution before agent sees any output

**What makes it too easy:**
An agent can implement this checkpoint by:
1. Reading the splitting algorithm description
2. Transcribing to code (simple division and modulo)
3. Applying the given threshold formula
4. Following the "within 1 run" distribution rule

No discovery, no inference, no problem-solving required beyond parsing instructions.

**Recommended difficulty improvements:**
1. **Remove splitting algorithm** - provide Examples 1, 2, 3; agent must discover:
   - When to split (threshold calculation)
   - How to split (distribution strategy)
   - Edge cases (1-run jobs unsplittable)

2. **Remove prose example (13 runs)** - let agent discover from actual output examples:
   - Example 3 shows 222/223 pattern (666 total runs distributed)
   - Agent must reverse-engineer the fair distribution algorithm

3. **Remove explicit constraints** - replace with outcome statement:
   - "Jobs exceeding the threshold are divided. See examples for splitting behavior."

4. **Add discovery-oriented examples:**
   - Show example with exact split (20 runs, 10 days threshold, 5 days/run → 2×10)
   - Show example with uneven split (visible in Example 3 but not highlighted)
   - Agent compares patterns to infer algorithm

With these changes, the checkpoint becomes:
- Analyze examples with different split_days values
- Discover threshold calculation from behavior changes
- Reverse-engineer fair distribution from output patterns (222/223, 28/29, etc.)
- Infer edge cases (1-run jobs) from constraints in examples
- Implement discovered algorithm

This transforms it from "transcribe algorithm" to "discover algorithm from examples" - a substantial challenge.

**Current state:** Algorithm given → transcription → trivial
**Improved state:** Examples only → algorithm discovery → appropriate difficulty

---

## Final Note on --build-all

**What's NOT over-specified (appropriately challenging):**

The --build-all flag semantics are only partially specified:
- "ALL BUILDABLE items in the tree" requires agent to:
  - Traverse the dependency tree
  - Identify which materials are buildable (using Checkpoint 1 logic)
  - Recursively plan builds for all buildable components
  - Apply component_bpo_defaults ME/TE to intermediate builds
  - Aggregate materials correctly

This aspect of the checkpoint retains appropriate difficulty. The over-specification issue is specifically the job splitting algorithm, not the build-all logic itself.
