# Checkpoint 3 Rubric: ME/TE Modifiers

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

---

## Overview

Extend the `recipe` command with material efficiency (ME) and time efficiency (TE) modifiers. Add an optional waste display column.

---

## New CLI Flags

| Flag | Aliases | Type | Range | Default |
|------|---------|------|-------|---------|
| `--material-efficiency` | `-me` | int | [0, 10] | 0 |
| `--time-efficiency` | `-te` | int | [0, 20], **even only** | 0 |
| `--display-waste` | `-waste` | bool flag | - | false |

---

## Material Efficiency Formula

```
adjusted_quantity = ceil(max(1, base_quantity * (1 - ME/100)))
```

### Critical Rules
- **Only applies to Manufacturing** (activityID=1)
- **Does NOT apply to Reactions** (activityID=11)
- `max(1, ...)` ensures at least 1 material required
- `ceil()` rounds up to next integer

### Example Calculations (Naga, base Tritanium = 3,640,000)

| ME | Calculation | Result |
|----|-------------|--------|
| 0 | `ceil(max(1, 3640000 * 1.00))` | 3,640,000 |
| 5 | `ceil(max(1, 3640000 * 0.95))` | 3,458,000 |
| 10 | `ceil(max(1, 3640000 * 0.90))` | 3,276,000 |

---

## Time Efficiency Formula

```
adjusted_time_seconds = base_time_seconds * (1 - TE/100)
adjusted_time_minutes = ceil(adjusted_time_seconds / 60)
```

### Example Calculations (Naga, base time = 15000 seconds = 250 minutes)

| TE | Calculation | Result (minutes) |
|----|-------------|------------------|
| 0 | `ceil(15000 * 1.00 / 60)` | 250 |
| 10 | `ceil(15000 * 0.90 / 60)` | 225 |
| 20 | `ceil(15000 * 0.80 / 60)` | 200 |

---

## Waste Column

When `--display-waste` is enabled:
- Insert a `Waste` column between `Quantity` and `Buildable`
- Waste represents materials saved if ME were at maximum (10)

```
waste = adjusted_quantity_at_current_ME - adjusted_quantity_at_ME_10
```

Or equivalently:
```
waste = ceil(base * (1 - current_ME/100)) - ceil(base * 0.90)
```

### Table Format with Waste

```
| Item      | Quantity  | Waste  | Buildable |
|:---------:|:---------:|:------:|----------:|
```

---

## Validation Requirements

| Parameter | Validation |
|-----------|------------|
| ME | Must be integer in [0, 10] |
| TE | Must be **even** integer in [0, 20] |

Invalid values should result in an error (not silent clamping).

---

## Grading Checklist

| Check | What to Verify | Pass/Fail |
|-------|----------------|-----------|
| ME validation | Only accepts [0, 10] | |
| TE validation | Only accepts even values [0, 20] | |
| ME formula | `ceil(max(1, qty * (1 - ME/100)))` | |
| Manufacturing only | ME does not affect Reactions | |
| TE formula | Reduces time by percentage | |
| Time ceiling | Always rounds up to next minute | |
| Waste calculation | Correct difference from current to max efficiency | |
| Waste column position | Between Quantity and Buildable | |
| Waste only when flag set | No waste column without `--display-waste` | |
| Combined ME+TE | Both apply correctly together | |
| Default values | ME=0, TE=0 when flags not provided | |

---

## Common Mistakes

- Applying ME to Reactions (should only affect Manufacturing)
- Not enforcing even-only for TE
- Accepting odd TE values silently
- Forgetting `max(1, ...)` floor (at least 1 material required)
- Rounding down instead of ceiling
- Calculating waste incorrectly (comparing to wrong baseline)
- Wrong column order when waste is displayed
- Applying TE as additive instead of multiplicative

---

## Expected Output Examples

### ME=10, no TE, no waste (Naga)
```
...
Run Time: 250
| Item      | Quantity  | Buildable |
|:---------:|:---------:|----------:|
| Isogen    | 23400     | No        |
| Megacyte  | 468       | No        |
| Mexallon  | 210600    | No        |
| Nocxium   | 9360      | No        |
| Pyerite   | 1170000   | No        |
| Tritanium | 3276000   | No        |
| Zydrine   | 2340      | No        |
```

### ME=5, with waste display (Naga)
```
...
Run Time: 250
| Item      | Quantity  | Waste  | Buildable |
|:---------:|:---------:|:------:|----------:|
| Isogen    | 24700     | 1300   | No        |
| Megacyte  | 494       | 26     | No        |
| Mexallon  | 222300    | 11700  | No        |
| Nocxium   | 9880      | 520    | No        |
| Pyerite   | 1235000   | 65000  | No        |
| Tritanium | 3458000   | 182000 | No        |
| Zydrine   | 2470      | 130    | No        |
```

### TE=20 only (Naga)
```
...
Run Time: 200
| Item      | Quantity  | Buildable |
|:---------:|:---------:|----------:|
| Isogen    | 26000     | No        |
...
```

### ME=10 + TE=20 (Naga)
```
...
Run Time: 200
| Item      | Quantity  | Buildable |
|:---------:|:---------:|----------:|
| Isogen    | 23400     | No        |
...
```

---

## Quick Reference

### ME Effect on Quantities
| ME | Multiplier | Example (base 1000) |
|----|------------|---------------------|
| 0 | 1.00 | 1000 |
| 1 | 0.99 | 990 |
| 2 | 0.98 | 980 |
| 5 | 0.95 | 950 |
| 10 | 0.90 | 900 |

### TE Effect on Time
| TE | Multiplier |
|----|------------|
| 0 | 1.00 |
| 2 | 0.98 |
| 4 | 0.96 |
| 10 | 0.90 |
| 20 | 0.80 |

### Activity Reminder
| Activity | ME Applies? | TE Applies? |
|----------|-------------|-------------|
| Manufacturing (1) | Yes | Yes |
| Reactions (11) | **No** | Yes |
