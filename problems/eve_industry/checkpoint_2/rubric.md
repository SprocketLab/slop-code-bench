# Checkpoint 2 Rubric: Invention Command

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

---

## Overview

Add an `invention` subcommand that calculates success probabilities for Tech II (invention) and Tech III (reverse engineering) blueprints. The command computes probability for all decryptor combinations and outputs a formatted table.

---

## Activity IDs

| ID | Name | Tech Level |
|----|------|------------|
| 8 | Invention | Tech II |
| 7 | Reverse Engineering | Tech III |

---

## Implementation Steps

### 1. Resolve Input to T2/T3 Product
- Same resolution as Checkpoint 1, but target must be Tech II or Tech III
- Determine which activity applies based on tech level

### 2. Find Base Blueprint (Tech II only)
- For T2 invention, find the T1 blueprint used as input
- Look in `industryActivityProducts` where `activityID=8` and `productTypeID` = T2 blueprint
- The `typeID` in that row is the T1 blueprint
- Output as: `Base: <T1 Blueprint Name> (<T1 Blueprint typeID>)`
- **Omit this line entirely for Tech III**

### 3. Get Datacores
- From `industryActivityMaterials` for the invention/RE activity
- Filter to datacore items
- All datacores for a single activity use the **same quantity per run**
- Sort alphabetically (case-insensitive), join with `, ` (comma-space)

### 4. Get Required Skills
- From `industryActivitySkills` for the invention/RE activity
- Resolve skill typeIDs to names via `invTypes`
- Sort alphabetically (case-insensitive), join with `, ` (comma-space)

### 5. Get Base Probability

**Tech II:**
- From `industryActivityProbabilities` table
- Lookup by blueprint typeID and activityID=8
- Value is 0-1 probability

**Tech III:**
- Use hardcoded relic quality table:

| Relic Quality | Base Chance |
|---------------|-------------|
| Intact | 0.26 |
| Malfunctioning | 0.21 |
| Wrecked | 0.14 |

### 6. Get Base Runs for Invented BPC

**Tech II:**
- From `industryActivityProducts.quantity` for invention activity

**Tech III:**
- From relic table:

| Relic Quality | Base Runs |
|---------------|-----------|
| Intact | 20 |
| Malfunctioning | 10 |
| Wrecked | 3 |

### 7. Probability Calculation

```
success = base_prob
          × (1 + (num_science_skills × skill_level) / 30 + skill_level / 40)
          × (1 + decryptor_modifier / 100)
```

- `skill_level` = `--skill` argument (default 5)
- `num_science_skills` = count of science skills required (from industryActivitySkills)
- **Clamp result to [0, 1]**
- Output as percentage without `%`, 2 decimal places (e.g., `49.58`)

### 8. Decryptor Modifiers Table (Hardcoded)

| Decryptor | Prob Mod | Runs | ME | TE |
|-----------|----------|------|----|----|
| None | 0 | 0 | 0 | 0 |
| Accelerant Decryptor | +20 | +1 | +2 | +10 |
| Attainment Decryptor | +80 | +4 | -1 | +4 |
| Augmentation Decryptor | -40 | +9 | -2 | +2 |
| Optimized Attainment Decryptor | +90 | +2 | +1 | -2 |
| Optimized Augmentation Decryptor | -10 | +7 | +2 | 0 |
| Parity Decryptor | +50 | +3 | +1 | -2 |
| Process Decryptor | +10 | 0 | +3 | +6 |
| Symmetry Decryptor | 0 | +2 | +1 | +8 |

### 9. ME/TE for Resulting BPC
- Base: ME=2, TE=4 (same for T2 and T3)
- Add decryptor modifiers
- ME/TE **can go to 0 or negative** (e.g., Augmentation gives ME=0)

### 10. Generate Probability Table

**Tech II:** 9 rows (one per decryptor)
- Sort by Decryptor name (ascending, case-insensitive)

**Tech III:** 27 rows (3 relics × 9 decryptors)
- Primary sort: relic quality (Intact → Malfunctioning → Wrecked)
- Secondary sort: Decryptor name (ascending, case-insensitive)

---

## Grading Checklist

| Check | What to Verify | Pass/Fail |
|-------|----------------|-----------|
| Activity ID | Uses 8 for invention, 7 for RE | |
| Base blueprint (T2) | Correctly identifies T1 blueprint | |
| Base line omitted (T3) | No "Base:" line for Tech III | |
| Datacore list | Correct items, sorted, comma-space separated | |
| Required Per Run | Correct quantity for datacores | |
| Skill list | Correct skills, sorted, comma-space separated | |
| Base probability source | SDE for T2, relic table for T3 | |
| Probability formula | `base * (1 + skills/30 + enc/40) * (1 + dec/100)` | |
| Skill level parameter | Respects `--skill` flag, default 5 | |
| Probability clamping | Clamped to [0,1] | |
| Probability format | Percentage, 2 decimals, no % sign | |
| Decryptor modifiers | All 9 decryptors correct | |
| ME/TE calculation | Base 2/4 + modifiers | |
| T2 row sorting | By decryptor name | |
| T3 row sorting | By relic quality, then decryptor name | |
| Time | Minutes, ceiling rounded | |

---

## Common Mistakes

- Using activity ID 1 instead of 8 for invention
- Wrong probability formula (missing the +1 terms inside parentheses)
- Not clamping probability to [0,1]
- Wrong base ME/TE (not 2/4)
- Including "Base" line for Tech III
- Wrong sorting for T3 (should be by relic quality first)
- Using wrong number of science skills in formula
- Forgetting to count encryption skill separately

---

## Expected Output Format

**Tech II:**
```
ITEM: <item name> (<type ID>)
Group: <Category Name> > <Group Name>
Market Group: <hierarchy joined by ' > '>
Tech Level: Tech II

Invention:
Base: <Base Blueprint Name> (<Base blueprint TypeID>)
Datacores: <Comma separated list of datacores, sorted alphabetically>
Required Per Run: <Number of datacores required per run>
Skills: <Comma separated list of skills, sorted alphabetically>
Time: <Time in minutes, rounded up>
Probabilities:
| Decryptor                       | Probability | Runs | ME | TE |
|---------------------------------|-------------|------|----|----|
| {Decryptor or None}             | {##.##}     | {R}  | {M}| {T}|
```

**Tech III:**
```
ITEM: <item name> (<type ID>)
Group: <Category Name> > <Group Name>
Market Group: <hierarchy joined by ' > '>
Tech Level: Tech III

Invention:
Datacores: <Comma separated list of datacores, sorted alphabetically>
Required Per Run: <Number of datacores required per run>
Skills: <Comma separated list of skills, sorted alphabetically>
Time: <Time in minutes, rounded up>
Probabilities:
| Invented From                | Decryptor                       | Probability | Runs | ME | TE |
|------------------------------|---------------------------------|-------------|------|----|----|
| {Relic}                      | {Decryptor or None}             | {##.##}     | {R}  | {M}| {T}|
```

---

## Quick Reference

### Relic Quality Order (T3)
1. Intact (base 0.26, 20 runs)
2. Malfunctioning (base 0.21, 10 runs)
3. Wrecked (base 0.14, 3 runs)

### Probability Example (Barrage L, skill 5)
```
Base probability: 0.26 (from SDE)
Science skills: 2 (Mechanical Engineering, Nuclear Physics)
Encryption: 1 (Minmatar Encryption Methods)

No decryptor:
= 0.26 * (1 + (2*5)/30 + 5/40) * (1 + 0/100)
= 0.26 * (1 + 0.333 + 0.125) * 1
= 0.26 * 1.458
= 0.379...
→ but actual is 0.4958, so base must be higher (0.34)

Check SDE for actual base probability!
```
