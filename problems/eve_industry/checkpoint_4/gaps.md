# Checkpoint 4 Gap Analysis

## Summary
Introduces the `plan` command that creates a build plan from a build string, outputting jobs.csv and materials.csv files. Supports multiple build string formats including invention and manual ME/TE specifications.

**Total behaviors tested:** 14
**True gaps found:** 4
**Not gaps (inferrable):** 9
**Over-specified (handled in over-spec rubric):** 1

---

## Test Behaviors Analysis

### Materials CSV Column Definitions

**What tests expect:**
Output has columns: `name,to_buy,buy_volume,start_amount,end_amount` with specific values.

**In spec examples?**
Yes - Examples show output values.

**In spec prose?**
Partial - Lines 44-46 specify the header but not what each column means:
```
name,to_buy,buy_volume,start_amount,end_amount
```

**Can agent infer this?**

*Standard practice?* No - column semantics are application-specific.

*Pattern in examples?* Partially - can see values but meaning unclear.

*Clear from context?* No - what is `buy_volume`? What are `start_amount` and `end_amount` for?

*Could implementations reasonably differ?* Yes - without definitions, agents might calculate values differently.

**Verdict:** TRUE GAP

**Fix:** CLARIFY

**Current text (lines 44-46):**
> "name,to_buy,buy_volume,start_amount,end_amount"

**Ambiguity:**
Column semantics not defined. Questions:
- `to_buy`: Total quantity to purchase?
- `buy_volume`: Volume in m³? Or something else?
- `start_amount`: Starting inventory? Always 0 in examples.
- `end_amount`: Leftover after builds? Always 0 in examples.

**Replace with:**
> **Consolidated BOM to Buy (`materials.csv`)**
>
> One row per **type to purchase** (all external purchases summed). Header:
> ```
> name,to_buy,buy_volume,start_amount,end_amount
> ```
>
> Column definitions:
> - `name`: Material name
> - `to_buy`: Total quantity needed to purchase
> - `buy_volume`: Total volume in m³ (to_buy × item volume)
> - `start_amount`: Starting inventory (default 0)
> - `end_amount`: Remaining after all jobs complete (default 0)

**Why this is needed:**
Without definitions, agents must guess column meanings. The examples show all start/end as 0, which doesn't clarify if these are placeholders or calculated values.

---

### Spec Example Has Wrong Column Count

**What tests expect:**
5 columns matching header: `name,to_buy,buy_volume,start_amount,end_amount`

Test output:
```
Fernite Carbide,294000,2940.00,0,0
```

**In spec examples?**
INCORRECT - Spec lines 79-83 show 6 values per row:
```
Fernite Carbide,294000,16578660,2940.00,0,0
```

This is a spec error, not a gap. The spec example has an extra column value.

**Verdict:** SPEC ERROR (not a gap)

**Fix:** Correct the spec example to have 5 values matching the header.

---

### Jobs CSV "days" Column Calculation

**What tests expect:**
`days` column shows fractional days for job duration.
Example: Barrage L Blueprint shows 1.28 days for 10 runs.

**In spec examples?**
Yes - Examples show days values.

**In spec prose?**
Partial - Lines 66-67 mention `te_bonus` formula:
> "Full TE factor is `BP Time * (1- BP TE) * (1 - TE bonus)`"

But:
1. Formula units unclear (what is BP Time unit?)
2. How to get BP TE for invented blueprints?
3. Days calculation formula not explicit

**Can agent infer this?**

*Standard practice?* No - game-specific.

*Pattern in examples?* Partially - can work backwards from example values.

*Clear from context?* No - requires EVE game knowledge to understand.

*Could implementations reasonably differ?* Yes - formula has ambiguities.

**Verdict:** TRUE GAP

**Fix:** CLARIFY

**Current text (lines 66-67):**
> "Full TE factor is `BP Time * (1- BP TE) * (1 - TE bonus)`"

**Ambiguity:**
- BP Time unit not specified (seconds from SDE)
- BP TE source not specified (from invented BPC stats or blueprint original?)
- Final days calculation not explicit

**Replace with:**
> "Job time calculation:
> ```
> time_seconds = base_time_seconds * (1 - blueprint_TE/100) * (1 - te_bonus/100)
> days = (time_seconds * runs) / 86400
> ```
> Format days to 2 decimal places.
>
> For invention build strings (`{Item} {Runs} {Decryptor} x{Jobs}`), the blueprint_TE comes from the decryptor modifier (base TE=4, plus decryptor TE modifier from Checkpoint 2 table)."

**Why this is needed:**
The formula is incomplete. Agents need to know:
1. Base time is in seconds
2. How to find TE for invented blueprints
3. How to convert to days and format

---

### Job Name Format (Blueprint vs Product)

**What tests expect:**
Jobs show blueprint names, not product names.
Example: `Barrage L Blueprint,10,1.28,10` not `Barrage L,10,1.28,10`

**In spec examples?**
Yes - Examples show "Barrage L Blueprint".

**In spec prose?**
No - The spec notes say `{Item Name}` is "always the PRODUCT" (line 29), but the OUTPUT should use blueprint name. This is not stated.

**Can agent infer this?**

*Standard practice?* No - either could be reasonable.

*Pattern in examples?* Yes - examples consistently show blueprint names.

*Clear from context?* No - input is product name, but unclear what output should be.

*Could implementations reasonably differ?* Yes - agents might output product name since that's the input.

**Verdict:** TRUE GAP

**Fix:** CLARIFY

**Current text (line 51):**
> "One **row per job**. Header **required**: `name,runs,days,count`"

**Add clarification:**
> "The `name` column should contain the **blueprint name** (e.g., `Barrage L Blueprint`), not the product name. For items requiring invention, append ` Blueprint` to the product name."

**Why this is needed:**
The spec emphasizes that INPUT uses product names but doesn't specify OUTPUT format. Examples show blueprint names but this should be explicit.

---

### te_bonus Application

**What tests expect:**
Config `te_bonus: 20` reduces job time by additional 20%.

**In spec examples?**
Yes - Examples assume te_bonus=20.

**In spec prose?**
Yes - Lines 62-67 explain te_bonus config field and formula.

**Can agent infer this?**

*Standard practice?* N/A - game-specific.

*Pattern in examples?* Yes.

*Clear from context?* Yes.

*Could implementations reasonably differ?* No.

**Verdict:** NOT A GAP

---

### Build String Parsing - Multiple Formats

**What tests expect:**
Correctly parse different build string formats:
- Item format: `{Item name} {Runs Per Job} x{Number of Jobs}`
- Normal format: `{Item name} {Runs Per Job} {ME} {TE} x{Number of Jobs}`
- Invention format: `{Item name} {RunsPerJob} {DecryptorName|None} x{NumJobs}`
- Reverse Engineering: `{Item name} {RunsPerJob} {DecryptorName|None} {RelicName} x{NumJobs}`

**In spec examples?**
Yes - Multiple examples demonstrate formats.

**In spec prose?**
Yes - Lines 6-25 specify all formats.

**Can agent infer this?**

*Standard practice?* No - application-specific parsing.

*Pattern in examples?* Yes.

*Clear from context?* Yes.

*Could implementations reasonably differ?* No.

**Verdict:** NOT A GAP

---

### Invented BPC ME/TE Values

**What tests expect:**
When using invention format (e.g., `Barrage L 10 None x10`), use ME/TE from invention results (base ME=2, TE=4 + decryptor modifiers).

**In spec examples?**
Not explicitly stated - examples show end results.

**In spec prose?**
Implied - Invention format doesn't specify ME/TE, so must come from invention mechanics.

**Can agent infer this?**

*Standard practice?* N/A.

*Pattern in examples?* Yes - can verify by matching output values.

*Clear from context?* Partially - requires connecting to Checkpoint 2 invention mechanics.

*Could implementations reasonably differ?* Somewhat.

**Verdict:** NOT A GAP (cross-references Checkpoint 2)

**Note:** Consider adding explicit statement: "For invention build strings, use ME/TE values from the invented BPC (base ME=2, TE=4, modified by decryptor)."

---

### Jobs Sorting Rules

**What tests expect:**
Jobs sorted by: name > runs > count > days (ascending for all).

**In spec examples?**
Yes - Examples show sorted output.

**In spec prose?**
Yes - Line 57: "Sort the jobs by: `name > runs > count > days`"

**Can agent infer this?**

*Standard practice?* Yes - sorting is common.

*Pattern in examples?* Yes.

*Clear from context?* Yes.

*Could implementations reasonably differ?* No.

**Verdict:** NOT A GAP

---

### Materials Sorting Rules

**What tests expect:**
Materials sorted alphabetically by name.

**In spec examples?**
Yes - Examples show alphabetical order.

**In spec prose?**
Yes - Line 48: "Sort materials by `name`. There should not be any duplicated names."

**Can agent infer this?**

*Standard practice?* Yes.

*Pattern in examples?* Yes.

*Clear from context?* Yes.

*Could implementations reasonably differ?* No.

**Verdict:** NOT A GAP

---

### Invalid Build String Error

**What tests expect:**
Exit code 1 with `ERROR: '<Build String>' is invalid` for malformed input.

**In spec examples?**
No error examples.

**In spec prose?**
Yes - Lines 33-36 specify error handling.

**Can agent infer this?**

*Standard practice?* Yes.

*Pattern in examples?* N/A.

*Clear from context?* Yes.

*Could implementations reasonably differ?* No.

**Verdict:** NOT A GAP

---

### Default Values for Optional Parts

**What tests expect:**
When optional parts omitted:
- `x{Number of Jobs}` defaults to 1
- In Item format, `{Runs Per Job}` defaults to 1

**In spec examples?**
Not explicitly demonstrated.

**In spec prose?**
Yes - Lines 30-31 specify defaults.

**Can agent infer this?**

*Standard practice?* Yes - default values are common.

*Pattern in examples?* N/A.

*Clear from context?* Yes.

*Could implementations reasonably differ?* No.

**Verdict:** NOT A GAP

---

### Output Directory Creation

**What tests expect:**
Output files created in specified `--output` directory.

**In spec examples?**
Yes - Examples use `--output outputs`.

**In spec prose?**
Yes - Line 3 specifies `--output <Output directory>`.

**Can agent infer this?**

*Standard practice?* Yes - standard CLI behavior.

*Pattern in examples?* Yes.

*Clear from context?* Yes.

*Could implementations reasonably differ?* No.

**Verdict:** NOT A GAP

---

### Days Precision (2 Decimal Places)

**What tests expect:**
Days formatted to 2 decimal places: `1.28`, `0.02`, etc.

**In spec examples?**
Yes - Examples show 2 decimal places consistently.

**In spec prose?**
No - decimal precision not specified.

**Can agent infer this?**

*Standard practice?* No - varies.

*Pattern in examples?* Yes - consistent 2 decimals.

*Clear from context?* Yes - can infer from examples.

*Could implementations reasonably differ?* Somewhat - might use different precision.

**Verdict:** OVER-SPEC (examples demonstrate, prose should match)

**Note:** Add to spec: "Format `days` to 2 decimal places."

---

### Buy Volume Calculation

**What tests expect:**
`buy_volume = to_buy * item_volume`
Example: Fernite Carbide 294000 × 0.01 (volume) = 2940.00

**In spec examples?**
Yes - Can verify with examples.

**In spec prose?**
No - buy_volume calculation not explained.

**Can agent infer this?**

*Standard practice?* Yes - volume calculation is straightforward.

*Pattern in examples?* Yes - can verify math.

*Clear from context?* Partially - "volume" in column name suggests this.

*Could implementations reasonably differ?* No - once meaning is clear.

**Verdict:** NOT A GAP (inferrable)

---

## Summary of Gaps

**Critical gaps (test failures):**
1. Materials CSV column definitions - no explanation of what each column means
2. Job time/days calculation - formula incomplete, missing unit specifications and TE source for invented items
3. Job name format - should use blueprint name, not product name (not stated)
4. Spec example error - example has 6 values but header has 5 columns

**Ambiguous specifications (need clarification):**
1. Days decimal precision - not specified, inferred from examples

**Not gaps (agent should infer):**
1. te_bonus application - explicitly specified
2. Build string parsing - explicitly specified
3. Jobs/materials sorting - explicitly specified
4. Invalid build string error - explicitly specified
5. Default values for optional parts - explicitly specified
6. Output directory - standard CLI behavior
7. Buy volume calculation - inferrable from name and examples
8. Invented BPC ME/TE - follows from Checkpoint 2

---

## Recommended Additions

**New examples needed:**
None - existing examples sufficient once prose is clarified.

**Prose clarifications needed:**
1. Lines 44-46: Add column definitions for materials.csv (to_buy, buy_volume, start_amount, end_amount)
2. Lines 66-67: Complete days calculation formula with units and TE source for invented items
3. Line 51: Specify that job `name` should be blueprint name, not product name
4. After line 57: Specify days precision: "Format `days` to 2 decimal places"

**Spec errors to fix:**
1. Lines 79-83: Example has 6 values per row but header has 5 columns - remove extra column value
