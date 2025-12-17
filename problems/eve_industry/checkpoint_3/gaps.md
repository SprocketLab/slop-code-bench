# Checkpoint 3 Gap Analysis

## Summary
Extends the `recipe` command with Material Efficiency (ME) and Time Efficiency (TE) flags, including waste display functionality. Manufacturing jobs apply ME/TE while Reactions only apply TE.

**Total behaviors tested:** 10
**True gaps found:** 2
**Not gaps (inferrable):** 7
**Over-specified (handled in over-spec rubric):** 1

---

## Test Behaviors Analysis

### Time Efficiency (TE) Formula

**What tests expect:**
With TE=20, Naga run time changes from 250 minutes to 200 minutes.
With TE=10, Fernite Carbide run time changes from 180 minutes to 162 minutes.

**In spec examples?**
Yes - Examples show the expected output values (200 minutes with TE=20).

**In spec prose?**
Partial - Line 14: "Time Efficiency is similar to but at the _seconds_ level." and lines 15-16 require even integer in [0,20].

This is ambiguous:
1. "Similar to" ME suggests the formula pattern, but doesn't state it explicitly
2. "At the seconds level" is confusing - the SDE time is in seconds, but output is in minutes
3. No explicit formula like ME has

**Can agent infer this?**

*Standard practice?* No - game-specific mechanics.

*Pattern in examples?* Yes - 250 * (1 - 20/100) = 200, 180 * (1 - 10/100) = 162.

*Clear from context?* Partially - "similar to" ME suggests: `time * (1 - TE/100)`.

*Could implementations reasonably differ?* Yes - ambiguity about seconds vs minutes and exact formula.

**Verdict:** TRUE GAP

**Fix:** CLARIFY

**Current text (lines 14-16):**
> "Time Efficiency is similar to but at the _seconds_ level.
> It must be an _even_ integer in the range of `[0,20]`."

**Ambiguity:**
- No explicit formula for TE calculation
- "At the seconds level" is confusing since output is in minutes
- "Similar to" ME is vague

**Replace with:**
> "Time Efficiency (TE): Reduces job duration by the percentage. Formula:
> ```
> Time (seconds) = base_time_seconds * (1 - TE/100)
> ```
> Convert to minutes and round up (ceiling) for display. TE must be an even integer in `[0,20]`."

**Why this is needed:**
Unlike ME which has an explicit formula, TE relies on agents inferring the calculation. The "seconds level" phrasing adds confusion. While examples demonstrate the math, an explicit formula ensures consistency.

---

### Waste Column Calculation

**What tests expect:**
Waste = (quantity at ME=0) - (quantity at current ME).
Example: ME=5 Isogen shows Quantity=24700, Waste=1300. Base Isogen is 26000. 26000-24700=1300.

**In spec examples?**
Yes - Example on lines 64-77 shows waste values.

**In spec prose?**
No - The spec shows the `--display-waste` flag and example output but never defines what "Waste" means or how to calculate it.

**Can agent infer this?**

*Standard practice?* No - "waste" could mean several things.

*Pattern in examples?* Yes - can reverse-engineer from example: 26000 (base) - 24700 (ME=5) = 1300.

*Clear from context?* Partially - name suggests "waste" is what you're not using.

*Could implementations reasonably differ?* Yes - "waste" could be interpreted as:
1. Base - Current (what spec expects)
2. Current - Maximum (difference from ME=10)
3. Percentage wasted

**Verdict:** TRUE GAP

**Fix:** CLARIFY

**Current text (lines 64-77):**
Shows example output with Waste column but no definition.

**Add after line 63:**
> "The Waste column shows how much extra material would be required compared to ME=0:
> ```
> Waste = quantity_at_ME0 - quantity_at_current_ME
> ```
> This represents the materials saved by having non-zero ME (or equivalently, the penalty for not having ME=10)."

**Why this is needed:**
"Waste" is ambiguous. The example demonstrates the expected values, but without defining the calculation, agents might implement it differently. The definition should clarify that waste is calculated against ME=0 baseline, not ME=10.

---

### ME Formula Implementation

**What tests expect:**
Materials reduced according to formula: `ceil(max(1, quantity * (1 - ME/100) * num_runs))`

**In spec examples?**
Yes - Multiple examples with ME=5 and ME=10.

**In spec prose?**
Yes - Lines 10-12 provide explicit formula:
```
Amount needed = ceil(max(1,quantity required per run * (1 - ME/100) * num_runs))
```

**Can agent infer this?**

*Standard practice?* N/A - game-specific.

*Pattern in examples?* Yes.

*Clear from context?* Yes - formula is explicit.

*Could implementations reasonably differ?* No.

**Verdict:** NOT A GAP

---

### ME Only Applies to Manufacturing

**What tests expect:**
Reactions ignore ME flag; Manufacturing applies it.

**In spec examples?**
Yes - Manufacturing examples show ME impact, spec says reactions error out.

**In spec prose?**
Yes - Lines 6-7: "Only Manufacturing jobs are impacted by this. Not Reactions."
Lines 109-112: Error message for reactions with ME.

**Can agent infer this?**

*Standard practice?* N/A - game-specific.

*Pattern in examples?* Yes.

*Clear from context?* Yes - explicit.

*Could implementations reasonably differ?* No.

**Verdict:** NOT A GAP

---

### Reactions Error with ME

**What tests expect:**
Exit code 1 with `ERROR: <item name> cannot be used with ME` when ME flag used with reaction.

**In spec examples?**
Yes - Lines 109-112 show error format.

**In spec prose?**
Yes - Lines 109-112 clearly specify.

**Can agent infer this?**

*Standard practice?* Yes - error handling is standard.

*Pattern in examples?* Yes.

*Clear from context?* Yes.

*Could implementations reasonably differ?* No.

**Verdict:** NOT A GAP

---

### TE Applies to Both Manufacturing and Reactions

**What tests expect:**
Fernite Carbide (reaction) with TE=10 shows reduced time (180 → 162 minutes).

**In spec examples?**
Not explicitly shown in spec - hidden test demonstrates this.

**In spec prose?**
Implied - TE section doesn't mention Manufacturing-only restriction like ME does.

**Can agent infer this?**

*Standard practice?* N/A.

*Pattern in examples?* No explicit reaction + TE example in spec.

*Clear from context?* Yes - by omission. ME section says "Only Manufacturing", TE section doesn't have this restriction.

*Could implementations reasonably differ?* Somewhat - agents might assume TE follows ME pattern.

**Verdict:** NOT A GAP (inferrable by omission)

**Note:** Consider adding explicit clarification: "TE applies to both Manufacturing and Reactions."

---

### Flag Argument Formats

**What tests expect:**
Both long (--material-efficiency) and short (-me) forms accepted.

**In spec examples?**
Examples use descriptive form (ME=10, TE=20), not actual CLI flags.

**In spec prose?**
Yes - Lines 2-4 specify:
- `--material-efficiency`/`-me`
- `--time-efficiency`/`-te`
- `--display-waste`/`-waste`

**Can agent infer this?**

*Standard practice?* Yes - CLI convention for long/short flags.

*Pattern in examples?* N/A.

*Clear from context?* Yes.

*Could implementations reasonably differ?* No.

**Verdict:** NOT A GAP

---

### ME/TE Value Validation

**What tests expect:**
ME in [0,10] integer, TE in [0,20] even integer.

**In spec examples?**
Demonstrated by example values (ME=5, ME=10, TE=20).

**In spec prose?**
Yes - Lines 7-8 for ME, Line 15 for TE.

**Can agent infer this?**

*Standard practice?* Yes - input validation is standard.

*Pattern in examples?* Yes.

*Clear from context?* Yes.

*Could implementations reasonably differ?* No.

**Verdict:** NOT A GAP

---

### Waste Column Header Positioning

**What tests expect:**
Table header: `| Item | Quantity |Waste | Buildable |` (Waste column between Quantity and Buildable).

**In spec examples?**
Yes - Lines 68-77 show the table format.

**In spec prose?**
No explicit column ordering specified, but example demonstrates.

**Can agent infer this?**

*Standard practice?* N/A.

*Pattern in examples?* Yes - clear from example.

*Clear from context?* Yes.

*Could implementations reasonably differ?* No - example is clear.

**Verdict:** NOT A GAP

---

### Waste Shows 0 for Items at Ceiling

**What tests expect:**
Hidden test (proteus_me5_waste) shows some items with Waste=0 when ceiling already reached.
Example: `Electromechanical Interface Nexus | 8 | 0 | Yes` (base is 8, ME=5 still gives 8).

**In spec examples?**
Not explicitly - main spec example doesn't show 0 waste.

**In spec prose?**
No - waste handling for minimum values not discussed.

**Can agent infer this?**

*Standard practice?* Yes - if formula gives same result, waste is 0.

*Pattern in examples?* Not in spec examples, but mathematical consequence.

*Clear from context?* Yes - follows from formula.

*Could implementations reasonably differ?* No.

**Verdict:** NOT A GAP (mathematical consequence)

---

## Summary of Gaps

**Critical gaps (test failures):**
1. TE formula - not explicitly stated, relies on "similar to" and example inference
2. Waste calculation definition - shows example but never defines what waste means

**Ambiguous specifications (need clarification):**
1. TE applies to reactions - implied by omission but not explicit

**Not gaps (agent should infer):**
1. ME formula - explicitly specified
2. ME only for Manufacturing - explicitly specified
3. Reactions error with ME - explicitly specified
4. TE applies to reactions - inferrable by omission from ME restriction
5. Flag formats (-me, --material-efficiency) - explicitly specified
6. Value validation ranges - explicitly specified
7. Waste column positioning - shown in example
8. Zero waste values - mathematical consequence

---

## Recommended Additions

**New examples needed:**
1. Reaction with TE applied (to make explicit that TE works for reactions)

**Prose clarifications needed:**
1. Lines 14-16: Add explicit TE formula: `time_seconds * (1 - TE/100)`, convert to minutes with ceiling
2. After line 63: Add waste definition: `Waste = quantity_at_ME0 - quantity_at_current_ME`
3. After line 16: Add clarification: "TE applies to both Manufacturing and Reactions, unlike ME which is Manufacturing-only."
