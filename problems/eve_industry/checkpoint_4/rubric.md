# Checkpoint 4 Rubric: Plan Command

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

---

## Overview

Add a `plan` subcommand that creates a build plan for a given item, outputting CSV files for materials to purchase and jobs to run.

---

## CLI Syntax

```
industry plan <Build string> --config <YAML> --sde <SDE dir> --output <Output dir>
```

---

## Build String Formats

| Format | Example | Parsed Fields |
|--------|---------|---------------|
| Simple (minimal) | `Naga` | name only (runs=1, jobs=1) |
| Simple (with runs) | `Naga 5` | name, runs (jobs=1) |
| Simple (with jobs) | `Naga 1 x5` | name, runs, jobs |
| ME/TE | `Barrage L 10 10 20 x10` | name, runs, ME, TE, jobs |
| Invention | `Barrage L 10 None x10` | name, runs, decryptor, jobs |
| Reverse Eng | `Proteus 20 Accelerant Intact x5` | name, runs, decryptor, relic, jobs |

### Parsing Rules
- `{Item Name}` is always the **PRODUCT**, not the blueprint
- If `x{Number of Jobs}` is not present, assume 1
- If `{Runs Per Job}` is not present, assume 1
- Decryptor can be "None" or a decryptor name
- Relic can be "Intact", "Malfunctioning", or "Wrecked"

---

## Config YAML

```yaml
te_bonus: 20  # [0, 30] - Additional TE reduction beyond blueprint
```

---

## Time Calculation

```
job_time_seconds = base_time * (1 - blueprint_TE/100) * (1 - config.te_bonus/100)
job_time_days = job_time_seconds / 86400
```

For invention builds, the blueprint TE comes from:
- Base TE = 4
- Plus decryptor modifier (if applicable)

---

## Output Files

### `materials.csv`

```csv
name,to_buy,buy_volume,start_amount,end_amount
```

| Column | Description |
|--------|-------------|
| `name` | Material name |
| `to_buy` | Total quantity to purchase |
| `buy_volume` | `to_buy * item_volume` |
| `start_amount` | Starting inventory (0 for this checkpoint) |
| `end_amount` | Ending inventory (0 for this checkpoint) |

**Sorting:** Alphabetically by `name`. No duplicate names.

### `jobs.csv`

```csv
name,runs,days,count
```

| Column | Description |
|--------|-------------|
| `name` | Blueprint/formula name |
| `runs` | Runs per job |
| `days` | Duration in days (with TE applied), 2 decimal places |
| `count` | Number of identical jobs |

**Sorting:** Multi-key sort: `name` → `runs` → `count` → `days`

---

## Material Aggregation

1. Calculate materials for one run (with ME applied for manufacturing)
2. Multiply by runs per job
3. Multiply by number of jobs
4. Sum all materials across all jobs
5. Aggregate by material name (no duplicates)

---

## Invention/RE Build Handling

When build string uses invention format:
1. Determine ME/TE from decryptor (base ME=2, TE=4 + decryptor mods)
2. Determine runs from:
   - T2: SDE base runs + decryptor runs modifier
   - T3: Relic base runs + decryptor runs modifier
3. Apply these to the manufacturing job

---

## Grading Checklist

| Check | What to Verify | Pass/Fail |
|-------|----------------|-----------|
| Build string parsing | All formats correctly parsed | |
| Default values | runs=1, jobs=1 when omitted | |
| Config loading | YAML parsed correctly | |
| TE bonus application | `(1 - bp_te/100) * (1 - te_bonus/100)` | |
| Material aggregation | Correctly summed across all jobs | |
| Volume calculation | `quantity * item_volume` | |
| CSV headers | Correct headers present | |
| CSV column order | Matches specification | |
| materials.csv sorting | Alphabetically by name | |
| jobs.csv sorting | Multi-key: name → runs → count → days | |
| Decimal formatting | Consistent (2 decimal places for days/volume) | |
| No duplicate materials | Materials aggregated by name | |
| Invention ME/TE | Uses decryptor modifiers correctly | |
| Output directory | Creates files in specified directory | |

---

## Common Mistakes

- Parsing build string incorrectly (especially with spaces in item names)
- Applying TE bonus additively instead of multiplicatively
- Wrong sort order for jobs.csv (should be multi-key)
- Missing headers in CSV
- Integer vs float formatting inconsistency
- Not aggregating materials (duplicate rows)
- Wrong ME/TE for invention builds (forgetting base 2/4)
- Days calculation off by factor (seconds vs minutes vs hours)

---

## Expected Output Examples

### Invention Build: `Barrage L 10 None x10`

**Config:**
```yaml
te_bonus: 20
```

**Calculation:**
- Decryptor: None → ME=2, TE=4, runs from SDE (10)
- Time: base_time * 0.96 * 0.80
- Materials: base * (1 - 2/100) = base * 0.98

**materials.csv:**
```csv
name,to_buy,buy_volume,start_amount,end_amount
Fernite Carbide,294000,2940.00,0,0
Fullerides,117600,17640.00,0,0
Morphite,1470,14.70,0,0
R.A.M.- Ammunition Tech,100,4.00,0,0
```

**jobs.csv:**
```csv
name,runs,days,count
Barrage L Blueprint,10,1.28,10
```

### Manual ME/TE Build: `Barrage L 10 10 20 x10`

**materials.csv:**
```csv
name,to_buy,buy_volume,start_amount,end_amount
Fernite Carbide,270000,2700.0,0,0
Fullerides,108000,16200.0,0,0
Morphite,1350,13.5,0,0
R.A.M.- Ammunition Tech,100,4.0,0,0
```

**jobs.csv:**
```csv
name,runs,days,count
Barrage L Blueprint,10,1.07,10
```

---

## Quick Reference

### Decryptor Effects on Invented BPC

| Decryptor | ME | TE | Runs Mod |
|-----------|----|----|----------|
| None | 2 | 4 | +0 |
| Accelerant Decryptor | 4 | 14 | +1 |
| Attainment Decryptor | 1 | 8 | +4 |
| Augmentation Decryptor | 0 | 6 | +9 |
| Optimized Attainment Decryptor | 3 | 2 | +2 |
| Optimized Augmentation Decryptor | 4 | 4 | +7 |
| Parity Decryptor | 3 | 2 | +3 |
| Process Decryptor | 5 | 10 | +0 |
| Symmetry Decryptor | 3 | 12 | +2 |

### T3 Relic Base Runs

| Relic | Base Runs |
|-------|-----------|
| Intact | 20 |
| Malfunctioning | 10 |
| Wrecked | 3 |

### Time Conversion
```
seconds → days = seconds / 86400
```
