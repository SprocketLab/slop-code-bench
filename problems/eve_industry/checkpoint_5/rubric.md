# Checkpoint 5 Rubric: Build-All with Job Splitting

## Prior Checkpoints

### Checkpoint 1: Recipe Command
Built a CLI that parses BZ2-compressed SDE files and outputs recipe reports. Key capabilities established:
- SDE data loading and indexing (invTypes, invGroups, invCategories, invMarketGroups, invMetaTypes, industryActivity*, etc.)
- Blueprint ↔ Product resolution for Manufacturing (activity 1) and Reactions (activity 11)
- Group/Category hierarchy: `Category > Group`
- Market group path traversal (parent chain → root)
- Tech level detection from `invMetaTypes` (default to Tech I)
- Ship packaged volume from `ship_volumes.yaml`
- Materials table with buildable detection and case-insensitive sorting

### Checkpoint 2: Invention Command
Added `invention` subcommand for Tech II/III probability calculations:
- Activity ID 8 for Invention (T2), Activity ID 7 for Reverse Engineering (T3)
- Base blueprint identification for T2 (T1 blueprint used for invention)
- Datacore and skill extraction from SDE
- Base probability: SDE lookup for T2, relic quality table for T3
- Probability formula: `base * (1 + skills/30 + enc/40) * (1 + dec/100)`
- All 9 decryptor modifiers with probability, runs, ME, TE effects
- T3 output includes 27 rows (3 relics × 9 decryptors)
- Proper sorting: T2 by decryptor name, T3 by relic quality then decryptor

### Checkpoint 3: ME/TE Modifiers
Extended `recipe` command with efficiency modifiers:
- `--material-efficiency` / `-me`: [0,10], reduces material quantities
- `--time-efficiency` / `-te`: [0,20] even only, reduces time
- ME formula: `ceil(max(1, base * (1 - ME/100)))`
- ME only applies to Manufacturing, not Reactions
- TE formula: `time * (1 - TE/100)`, ceiling to minutes
- `--display-waste` flag adds Waste column showing savings vs ME=10

### Checkpoint 4: Plan Command
Added `plan` subcommand for build planning:
- Build string parsing (simple, ME/TE, invention, RE formats)
- Config YAML with `te_bonus` for additional time reduction
- Output `materials.csv`: materials to buy, volumes, sorted by name
- Output `jobs.csv`: jobs to run with runs, days, count, multi-key sorted
- Time calculation: `base * (1 - bp_te/100) * (1 - te_bonus/100)`
- Material aggregation across all jobs

---

## Overview

Add `--build-all` flag to the `plan` command that recursively builds all buildable intermediate materials instead of purchasing them. Also add job splitting for long-running jobs.

---

## New CLI Flag

```
--build-all    Build all buildable intermediate materials
```

---

## Extended Config YAML

```yaml
te_bonus: 20                    # [0, 30] - Additional TE reduction
split_days: 3.0                 # Max days per job before splitting
component_bpo_defaults:
  me: 10                        # Default ME for component blueprints
  te: 20                        # Default TE for component blueprints
```

---

## Dependency Tree Resolution

### Algorithm

1. **Start with target product**
2. **For each material in recipe:**
   - Check if material is buildable (has a recipe for activity 1 or 11)
   - If buildable AND `--build-all` is set → recurse into that material's recipe
   - If not buildable → add to purchase list
3. **Apply `component_bpo_defaults`** ME/TE to all component builds
4. **Calculate total quantities** working up from leaves to root
5. **Track intermediate products** that are produced internally

### Important Notes
- The final product uses the ME/TE from the build string
- Intermediate components use `component_bpo_defaults` ME/TE
- Reactions are never affected by ME (only TE)
- Materials that appear multiple places in the tree must be aggregated

---

## Job Splitting Algorithm

### When to Split
- If real job time > `min(30, config.split_days)` days
- Only split jobs with **more than 1 run**

### How to Split

```python
max_days = min(30, config.split_days)
time_per_run_days = run_time_seconds / 86400
max_runs_per_job = floor(max_days / time_per_run_days)

if total_runs <= max_runs_per_job:
    # No split needed
    return [(total_runs, 1)]  # 1 job with all runs

if total_runs == 1:
    # Cannot split single-run job
    return [(1, 1)]

# Need to split
num_jobs = ceil(total_runs / max_runs_per_job)
base_runs = total_runs // num_jobs
extra = total_runs % num_jobs

# Result: 'extra' jobs of (base_runs + 1), and (num_jobs - extra) jobs of base_runs
# All jobs within 1 run of each other
```

### Split Example
```
Total runs: 13
Max runs per job: 4 (due to split_days)

num_jobs = ceil(13 / 4) = 4
base_runs = 13 // 4 = 3
extra = 13 % 4 = 1

Result: 1 job of 4 runs, 3 jobs of 3 runs
NOT: 3 jobs of 4 runs, 1 job of 1 run
```

### Key Rule: Prefer Larger Jobs First
When splitting, the larger jobs (base_runs + 1) should be created before smaller jobs (base_runs). This matters for sorting.

---

## Materials.csv Changes

| Column | Without `--build-all` | With `--build-all` |
|--------|----------------------|-------------------|
| `to_buy` | Total to purchase | 0 for items you're building |
| `buy_volume` | `to_buy * volume` | 0 for items you're building |
| `start_amount` | 0 | 0 (starting inventory) |
| `end_amount` | 0 | Leftover from building (batch rounding) |

### End Amount Calculation
If a recipe produces 10,000 units per run, but you only need 9,500, the end_amount would be 500 (leftover).

---

## Jobs.csv Changes

- Now includes **all intermediate component jobs**
- Jobs may be split into multiple rows with same name but different runs/count
- Each unique (name, runs) combination gets its own row

---

## Grading Checklist

| Check | What to Verify | Pass/Fail |
|-------|----------------|-----------|
| Dependency traversal | Correctly identifies all buildable components | |
| Recursive resolution | Builds full tree to raw materials | |
| ME/TE defaults | Uses `component_bpo_defaults` for intermediates | |
| Final product ME/TE | Uses build string ME/TE, not defaults | |
| Reaction ME handling | Reactions not affected by ME | |
| Split threshold | Respects `min(30, split_days)` | |
| Split distribution | Jobs within 1 run of each other | |
| No single-run splits | Doesn't split 1-run jobs | |
| Larger jobs first | More runs in earlier splits | |
| End amount calculation | Correctly tracks leftover materials | |
| to_buy = 0 for built | Built items show 0 in to_buy | |
| Intermediate jobs | All component jobs appear in jobs.csv | |
| Material aggregation | Same material from different branches summed | |
| 30-day cap | Never exceeds 30 days per job | |

---

## Common Mistakes

- Splitting 1-run jobs (should never split these)
- Uneven splits (e.g., [4, 4, 4, 1] instead of [4, 3, 3, 3])
- Ignoring the 30-day cap when split_days > 30
- Applying ME to reactions
- Missing intermediate materials in recursion
- Double-counting materials that appear in multiple branches
- Using build string ME/TE for components instead of defaults
- Not applying component_bpo_defaults.te to reactions
- Wrong end_amount calculation (off-by-one in batch sizes)
- Forgetting to include intermediate jobs in jobs.csv

---

## Expected Output Examples

### Build: `Barrage L 10 None x10` with `--build-all`

**Config:**
```yaml
split_days: 30
component_bpo_defaults:
  me: 10
  te: 20
te_bonus: 20
```

**jobs.csv** (includes intermediate jobs):
```csv
name,runs,days,count
Barrage L Blueprint,10,1.28,10
Carbon Polymers Reaction Formula,20,2.0,1
Ceramic Powder Reaction Formula,15,1.5,1
Fernite Alloy Reaction Formula,15,1.5,1
Fernite Carbide Reaction Formula,30,3.0,1
Fulleride Reaction Formula,40,4.0,1
Helium Fuel Block Blueprint,3,0.02,1
Hydrogen Fuel Block Blueprint,8,0.05,1
Nitrogen Fuel Block Blueprint,8,0.05,1
Platinum Technite Reaction Formula,20,2.0,1
R.A.M.- Ammunition Tech Blueprint,1,0.02,1
```

**materials.csv** (raw materials only):
```csv
name,to_buy,buy_volume,start_amount,end_amount
Coolant,155,116.25,0,0
Enriched Uranium,69,51.75,0,0
...
Fernite Carbide,0,0.0,0,6000
Fullerides,0,0.0,0,2400
...
```

Note: `Fernite Carbide` and `Fullerides` have `to_buy=0` but `end_amount>0` because they're built internally with leftovers.

### Same Build with `split_days: 3`

**jobs.csv** (notice splits):
```csv
name,runs,days,count
...
Fernite Carbide Reaction Formula,15,1.5,2
Fulleride Reaction Formula,20,2.0,2
...
```

The 30-run and 40-run jobs are now split into 2 jobs each.

---

## Quick Reference

### Split Calculation Examples

| Total Runs | Max/Job | Num Jobs | Distribution |
|------------|---------|----------|--------------|
| 10 | 4 | 3 | 4, 3, 3 |
| 13 | 4 | 4 | 4, 3, 3, 3 |
| 30 | 15 | 2 | 15, 15 |
| 40 | 15 | 3 | 14, 13, 13 |
| 1 | any | 1 | 1 (no split) |

### Days Calculation
```
days = (base_seconds * (1 - bp_te/100) * (1 - te_bonus/100)) / 86400
```

### Activity Reminder
| Activity | ME from defaults? | TE from defaults? |
|----------|-------------------|-------------------|
| Manufacturing (1) | Yes | Yes |
| Reactions (11) | **No** | Yes |

### Material Tracking
| Scenario | to_buy | end_amount |
|----------|--------|------------|
| Raw material (buy) | >0 | 0 |
| Built intermediate | 0 | ≥0 (leftover) |
| Exact build | 0 | 0 |
