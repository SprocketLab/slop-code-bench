# Checkpoint 1 Rubric: Recipe Command

## Prior Checkpoints
*None — this is the first checkpoint.*

---

## Overview

Build a CLI that parses the EVE Online Static Data Export (SDE) and outputs a formatted recipe report for any item or blueprint. The CLI must handle BZ2-compressed CSV files, resolve item/blueprint names, and output a canonical block with exact formatting.

---

## Required SDE Tables & Key Columns

| Table | Key Columns | Purpose |
|-------|-------------|---------|
| `invTypes.csv.bz2` | `typeID`, `typeName`, `groupID`, `volume`, `marketGroupID`, `published` | Item lookup, volume, market group |
| `invGroups.csv.bz2` | `groupID`, `categoryID`, `groupName` | Group hierarchy |
| `invCategories.csv.bz2` | `categoryID`, `categoryName` | Category names |
| `invMarketGroups.csv.bz2` | `marketGroupID`, `parentGroupID`, `marketGroupName` | Market group path |
| `invMetaTypes.csv.bz2` | `typeID`, `metaGroupID` | Tech level lookup |
| `invMetaGroups.csv.bz2` | `metaGroupID`, `metaGroupName` | Meta group names (Tech I=1, Tech II=2, Tech III=14) |
| `industryActivity.csv.bz2` | `typeID`, `activityID`, `time` | Blueprint → time in seconds |
| `industryActivityProducts.csv.bz2` | `typeID`, `activityID`, `productTypeID`, `quantity` | Blueprint → product mapping |
| `industryActivityMaterials.csv.bz2` | `typeID`, `activityID`, `materialTypeID`, `quantity` | Required materials |
| `ship_volumes.yaml` | `groupName: volume` | Packaged ship volumes |
| `ramActivities.csv.bz2` | `activityID`, `activityName` | Activity ID → name (1=Manufacturing, 11=Reactions) |

---

## Implementation Steps

### 1. Load and Index SDE Data
- Parse all BZ2 CSV files (UTF-8, comma-separated, headers)
- Filter: only `published == 1` items are valid
- Build lookup dicts: `typeID → TypeInfo`, `groupID → GroupInfo`, etc.

### 2. Resolve Input to Product
- Input can be product name ("Naga") or blueprint name ("Barrage L Blueprint")
- If input is a product: find its blueprint via `industryActivityProducts` (where `productTypeID` matches)
- If input is a blueprint: find its product via `industryActivityProducts`
- Activity must be Manufacturing (1) or Reactions (11)

### 3. Build Group/Category Path
- Format: `<Category Name> > <Group Name>`
- Lookup chain: `typeID → groupID → categoryID`

### 4. Build Market Group Path
- Walk `parentGroupID` chain from leaf to root
- Join with ` > ` (space-arrow-space)
- If no `marketGroupID` → output `None`

### 5. Determine Tech Level
- Lookup `typeID` in `invMetaTypes` → get `metaGroupID`
- Map: 1 → "Tech I", 2 → "Tech II", 14 → "Tech III"
- **Default to "Tech I"** if not found in `invMetaTypes`

### 6. Determine Volume
- Check if item's group name exists in `ship_volumes.yaml`
- If yes → use packaged volume from YAML
- If no → use `volume` from `invTypes`
- Format: always show 2 decimal places (e.g., `15000.00`)

### 7. Get Recipe Details
- Activity: "Manufacturing" (activityID=1) or "Reactions" (activityID=11)
- Output Quantity: from `industryActivityProducts.quantity`
- Run Time: `industryActivity.time` in seconds → convert to minutes, **ceiling** (round up)

### 8. Build Materials Table
- Get materials from `industryActivityMaterials` for the blueprint + activity
- For each material:
  - Get name from `invTypes`
  - Quantity: integer, no thousands separators
  - Buildable: "Yes" if material has its own recipe (exists in `industryActivityProducts` as a product for activity 1 or 11), "No" otherwise
- **Sort alphabetically by item name (case-insensitive)**

---

## Grading Checklist

| Check | What to Verify | Pass/Fail |
|-------|----------------|-----------|
| BZ2 parsing | Correctly decompresses and parses CSV | |
| Published filter | Only `published == 1` items are valid | |
| Blueprint ↔ Product resolution | Works both directions | |
| Ship volume | Uses `ship_volumes.yaml` for ships, not `invTypes.volume` | |
| Tech level default | Defaults to "Tech I" when not in `invMetaTypes` | |
| Market group path | Full path from root to leaf, or "None" | |
| Time rounding | Uses ceiling (rounds up) | |
| Material sorting | Case-insensitive alphabetical | |
| Buildable detection | Correctly identifies if material has a recipe | |
| Output format | Exact labels, capitalization, spacing | |

---

## Common Mistakes

- Using unpackaged ship volume instead of packaged
- Not handling "None" for market group
- Sorting case-sensitively
- Not defaulting tech level to Tech I
- Rounding time down instead of up
- Using thousands separators in quantities

---

## Expected Output Format

```
ITEM: <item name> (<type ID>)
Group: <Category Name> > <Group Name>
Market Group: <Market group hierarchy from root to leaf, joined by ' > '>
Tech Level: <Tech I | Tech II | Tech III>
Volume: <volume in m3>

Recipe:
Activity: <Manufacturing | Reactions>
Output Quantity: <Output quantity for 1 run>
Run Time: <Ceiling Time in minutes for a single run>
| Item | Quantity | Buildable |
|:-:|:---:|---:|
| {Item Name} | {Num Required} | {'Yes' if the item is buildable else 'No'} |
```

---

## Quick Reference

### Activity IDs
| ID | Name |
|----|------|
| 1 | Manufacturing |
| 11 | Reactions |

### Tech Levels
| metaGroupID | Display |
|-------------|---------|
| 1 | Tech I |
| 2 | Tech II |
| 14 | Tech III |
| (not found) | Tech I (default) |
