# Checkpoint 2 Gap Analysis

## Summary
Extends checkpoint 1 with cargo hauling operations: ship configurations, manifest files, multi-trip planning, waypoint cargo pickup, and freighter routing restrictions.

**Total behaviors tested:** 11
**True gaps found:** 2
**Not gaps (inferrable):** 9
**Over-specified (handled in over-spec rubric):** 0

---

## Test Behaviors Analysis

### Ship Configuration and Manifest Parsing

**What tests expect:**
CLI accepts --config and --manifest arguments, parses YAML files, extracts ship stats (align, warp_speed, top_speed, cargo_size, type) and manifest data (start_cargo, waypoints).

**In spec examples?**
Yes - Examples 1 and 2 (lines 77-138) show config and manifest usage.

**In spec prose?**
Yes - Config format at lines 5-19, manifest format at lines 21-31.

**Can agent infer this?**

*Standard practice?* Yes - YAML config files are standard.

*Pattern in examples?* Yes - examples demonstrate usage.

*Clear from context?* Yes - format is explicitly specified.

*Could implementations reasonably differ?* No - format is explicit.

**Verdict:** NOT A GAP

---

### Single-Trip Cargo Hauling

**What tests expect:**
When total cargo fits in ship capacity, perform single trip: START → LOAD at start → UNDOCK → GO → DOCK → UNLOAD at end → DONE with MOVED summary.

**In spec examples?**
Yes - Example 1 (lines 77-97) demonstrates exactly this.

**In spec prose?**
Yes - Output format at lines 41-74 describes all operations.

**Can agent infer this?**

*Standard practice?* Yes - basic cargo transport logic.

*Pattern in examples?* Yes - Example 1 is clear.

*Clear from context?* Yes - fully demonstrated.

*Could implementations reasonably differ?* No - example is specific.

**Verdict:** NOT A GAP

---

### Multi-Trip Cargo Hauling with Capacity Constraints

**What tests expect:**
When cargo exceeds ship capacity, split into multiple trips with [--- TRIP N ---] separators. Each trip: load max capacity → deliver → return to source → repeat until all cargo moved.

**In spec examples?**
Yes - Example 2 (lines 99-138) demonstrates 3-trip scenario with 15,000 m3 in 5,000 m3 ship.

**In spec prose?**
Yes - Line 34 states "Multiple trips are allowed." Output format (lines 57-72) describes trip separators.

**Can agent infer this?**

*Standard practice?* Yes - multi-trip hauling when capacity is insufficient.

*Pattern in examples?* Yes - Example 2 clearly shows the pattern.

*Clear from context?* Yes - logistics are straightforward.

*Could implementations reasonably differ?* No - pattern is demonstrated.

**Verdict:** NOT A GAP

---

### Waypoint Cargo Pickup in First Trip

**What tests expect:**
When waypoints have cargo, optimize first trip to partially load from start (leaving room for waypoint cargo) and visit waypoint before final delivery. Example: 12,500 m3 at start + 2,500 m3 at waypoint with 5,000 m3 capacity → load 2,500 from start, pick up 2,500 at waypoint, deliver 5,000 total.

**In spec examples?**
Yes - Example 2 (lines 107-117) demonstrates this strategy:
- start_cargo: 12,500
- waypoint cargo: 2,500
- First trip loads: 2,500 (from start) + 2,500 (at waypoint) = 5,000

**In spec prose?**
Implicit - not explicitly stated as a rule, but shown in example.

**Can agent infer this?**

*Standard practice?* Yes - route optimization to minimize trips.

*Pattern in examples?* Yes - Example 2 clearly demonstrates the partial loading strategy.

*Clear from context?* Yes - the example shows the optimized approach.

*Could implementations reasonably differ?* Potentially - agents might try different strategies, but the example provides a clear pattern to follow.

**Verdict:** NOT A GAP

**Reasoning:**
While not explicitly stated in prose, the example clearly demonstrates the strategy. Agents analyzing the example should recognize the optimization pattern: partially load from start to accommodate waypoint cargo in the first trip.

---

### Freighter Cannot Enter Low-Sec Systems

**What tests expect:**
Freighter-class ships must avoid systems with security < 0.5 when alternative routes exist. Tests show:
- `rairomon_sivala_charon`: Freighter takes longer route through 0.5+ systems, avoiding 0.4 systems
- `jita_tama_charon`: Freighter route includes 0.3 system (destination) - allowed by exception
- `hs_to_island_charon`: Freighter traverses 0.4 and 0.3 systems when it's the only route

**In spec examples?**
No - no example shows freighter routing behavior or demonstrates the security threshold.

**In spec prose?**
Partially - Lines 36-38 state:
> "**Freighter class ships** (ships with type "Freighter" in config):
> * CANNOT enter non-high sec systems
> * Exception: Can traverse low-sec if it's the ONLY possible route to destination"

**Can agent infer this?**

*Standard practice?* No - this is EVE Online-specific game knowledge.

*Pattern in examples?* No - no example demonstrates freighter behavior.

*Clear from context?* No - the security threshold is not defined.

*Could implementations reasonably differ?* YES - agents could interpret "non-high sec" as:
1. Security < 1.0 (only 1.0 is high-sec)
2. Security < 0.5 (correct: 0.5-1.0 is high-sec, < 0.5 is low-sec)
3. Security < 0.0 (any positive security is high-sec)
4. Any system not explicitly marked as "high-sec" in data

**Ambiguity:**
The term "non-high sec" assumes knowledge of EVE Online's security system:
- **High-sec:** 0.5 to 1.0
- **Low-sec:** 0.1 to 0.4
- **Null-sec:** 0.0 and below

Without this context, agents cannot determine which security values constitute "non-high sec". The test `rairomon_sivala_charon` validates that freighters avoid 0.4 systems when alternatives exist, but this behavior isn't documented in the spec.

**Verdict:** TRUE GAP

**Fix:** CLARIFY and ADD-EXAMPLE

**Specific specification:**

**Clarify prose (lines 36-38):**

**Replace:**
> "**Freighter class ships** (ships with type "Freighter" in config):
> * CANNOT enter non-high sec systems
> * Exception: Can traverse low-sec if it's the ONLY possible route to destination"

**With:**
> "**Freighter class ships** (ships with type "Freighter" in config):
> * CANNOT enter systems with security status < 0.5 (low-sec and null-sec)
> * Exception: Can traverse low-sec systems (0.1 to 0.4) if it's the ONLY possible route to destination
> * Can always use high-sec systems (security >= 0.5)"

**Add Example 3: Freighter Routing with Security Restrictions**

**Setup:**
```yaml
# config.yaml
ships:
  Charon:
    type: Freighter
    align: 60
    top_speed: 100
    warp_speed: 1.5
    cargo_size: 1000000
times:
  dock: 5
  gate: 1
  move_cargo: 10
```

```sh
hauling Rairomon Sivala --config config.yaml --ship Charon --sde ./sde/
```

**Expected output:**
```
START: Rairomon
GO: Rairomon (0.6) -> Huttaken (0.6) -> Halaima (0.7) -> Kamio (0.7) -> Ikao (0.6) -> Uedama (0.5) -> Sivala (0.6)
DONE: 00:15
```

**What this demonstrates:**
- Freighter takes a longer 7-jump route through systems with security >= 0.5
- Avoids the shorter 4-jump route: Rairomon (0.6) -> Enderailen (0.4) -> Kubinen (0.4) -> Sivala (0.6)
- Shows that security 0.4 systems are restricted (low-sec)
- Security 0.5 and above are allowed (high-sec)

**Contrast with Blockade Runner (from checkpoint 1):**
For the same route, a Prowler (Blockade Runner) would take the shorter route through 0.4 systems because it has no security restrictions.

**Why this is needed:**
The security threshold (0.5) is EVE-specific domain knowledge. Without defining "high-sec" vs "low-sec", agents cannot implement the restriction correctly. The term "non-high sec" is ambiguous and could be interpreted multiple ways. An example showing the freighter avoiding 0.4 systems while using 0.5 systems makes the threshold explicit.

---

### Trip Ordering Tie-Breaking Rule

**What tests expect:**
When multiple trip orderings result in the same outcome, tie-break using the rule: "Waypoints Finished > Minimum warps in space with cargo in hold > Alphabetical"

**In spec examples?**
No - no example demonstrates a scenario where tie-breaking is needed.

**In spec prose?**
Yes - Line 35 states the tie-breaking rule:
> "If the ordering of two trips does not effect the outcome. Tie break with `Waypoints Finished > Minimum warps in space with cargo in hold > Alphabetical`"

**Can agent infer this?**

*Standard practice?* No - this is a complex, problem-specific rule.

*Pattern in examples?* No - Examples 1 and 2 don't require tie-breaking (unambiguous optimal orders).

*Clear from context?* Partially - the rule is stated but complex.

*Could implementations reasonably differ?* YES - agents could:
1. Not implement tie-breaking at all (arbitrary order)
2. Misinterpret the priority order (e.g., alphabetical first)
3. Misunderstand "Waypoints Finished" (does this mean number of waypoints visited?)
4. Misunderstand "Minimum warps in space with cargo" (minimize total warps with cargo? minimize max warps per trip?)
5. Implement alphabetical sorting incorrectly (by what field? start location? end location? waypoint name?)

**Verdict:** TRUE GAP

**Fix:** ADD-EXAMPLE

**Specific specification:**

**Add Example 4: Trip Ordering Tie-Breaking**

**Setup:**
```yaml
# manifest.yaml
start_cargo: null
waypoints:
  - name: Amarr VIII (Oris) - Emperor Family Academy
    cargo: 3000
  - name: Jita IV - Moon 4 - Caldari Navy Assembly Plant
    cargo: 3000
```

```yaml
# config.yaml
ships:
  Hauler:
    type: Blockade Runner
    align: 2.1
    top_speed: 250
    warp_speed: 10.0
    cargo_size: 5000
times:
  dock: 5
  gate: 1
  move_cargo: 10
```

```sh
hauling "Rens VI - Moon 8 - Brutor Tribe Treasury" "Rens VI - Moon 8 - Brutor Tribe Treasury" --manifest manifest.yaml --config config.yaml --ship Hauler --sde ./sde/
```

**Expected output:**
```
START: Rens VI - Moon 8 - Brutor Tribe Treasury
UNDOCK
GO: Rens -> [route to Amarr]
DOCK: Amarr VIII (Oris) - Emperor Family Academy
LOAD: 3,000.00 m3
UNDOCK
GO: Amarr -> [route to Rens]
DOCK: Rens VI - Moon 8 - Brutor Tribe Treasury
UNLOAD: 3,000.00 m3
[--- TRIP 2 ---]
UNDOCK
GO: Rens -> [route to Jita]
DOCK: Jita IV - Moon 4 - Caldari Navy Assembly Plant
LOAD: 3,000.00 m3
UNDOCK
GO: Jita -> [route to Rens]
DOCK: Rens VI - Moon 8 - Brutor Tribe Treasury
UNLOAD: 3,000.00 m3
DONE: [time]
MOVED: 6,000.00 m3
```

**What this demonstrates:**
- Same start/end location (round trip to Rens)
- Two waypoints with equal cargo amounts (3,000 m3 each)
- Both orderings (Amarr first vs Jita first) deliver the same total cargo
- Tie-breaking rule applies: "Waypoints Finished > Minimum warps with cargo > Alphabetical"
  - Both complete same number of waypoints (1 per trip) - TIE
  - Both have same number of warps with cargo (return trip with 3k m3) - TIE
  - Alphabetical: "Amarr" comes before "Jita" → Amarr waypoint is visited first

**Why this is needed:**
The tie-breaking rule is complex with three levels of priority. Without seeing it in action, agents might:
- Not implement tie-breaking (leading to inconsistent/arbitrary results)
- Implement the priorities in wrong order
- Misinterpret what each criterion means

An example makes the rule concrete and testable.

---

### Freighter Exception: Can Traverse Low-Sec if Only Route

**What tests expect:**
Freighter can enter systems with security < 0.5 when it's the only possible route to destination. Test `hs_to_island_charon` validates freighter going through 0.4 and 0.3 systems when necessary.

**In spec examples?**
No - no example demonstrates the exception.

**In spec prose?**
Yes - Line 38 states: "Exception: Can traverse low-sec if it's the ONLY possible route to destination"

**Can agent infer this?**

*Standard practice?* No - but the exception is explicitly stated.

*Pattern in examples?* No examples show this.

*Clear from context?* Yes - the exception is clearly stated.

*Could implementations reasonably differ?* Potentially - agents might:
- Not detect that a route is "the only route" (pathfinding complexity)
- Be conservative and refuse to route through low-sec even with exception

However, the prose is explicit. With the security threshold clarification from the previous gap fix, this becomes clear.

**Verdict:** NOT A GAP (with security threshold defined)

**Reasoning:**
The exception is explicitly stated. Once the security threshold (< 0.5) is defined, agents can implement this correctly. The pathfinding logic to detect "only route" is a standard algorithm problem (check if any high-sec path exists).

---

### Cargo Formatting with Comma Separators and Decimals

**What tests expect:**
Cargo amounts formatted as: comma-separated thousands, two decimal places, "m3" suffix.
Examples: 5,000.00 m3, 15,000.00 m3, 1,000,000.00 m3, 3,001,000.00 m3

**In spec examples?**
Yes - Examples 1 and 2 consistently show this format.

**In spec prose?**
Yes - Line 69 states: "(with amount in m3, comma-separated thousands)"
Line 70 mentions two decimal places implicitly through examples.

**Can agent infer this?**

*Standard practice?* Yes - comma-separated thousands is common formatting.

*Pattern in examples?* Yes - consistent across all examples.

*Clear from context?* Yes - both stated and demonstrated.

*Could implementations reasonably differ?* No - format is clear.

**Verdict:** NOT A GAP

---

### null Cargo Handling

**What tests expect:**
- `start_cargo: null` treated as 0 (no cargo from start)
- Waypoint with `cargo: null` means no cargo operation at that waypoint

**In spec examples?**
Partially - Example 1 has `start_cargo: 5000` (not null), Example 2 has `start_cargo: 12500` (not null). Tests validate null but examples don't show it.

**In spec prose?**
Yes - Lines 24 and 27 explicitly state:
- Line 24: "`start_cargo: <float m3 or null>  # Initial cargo to load at start (null = 0)`"
- Line 27: "`cargo: <float m3 or null>  # Cargo to pickup at this waypoint (null = no cargo operation)`"

**Can agent infer this?**

*Standard practice?* Yes - null typically means absence/zero.

*Pattern in examples?* Not shown, but explicitly documented.

*Clear from context?* Yes - prose is explicit.

*Could implementations reasonably differ?* No - explicitly defined.

**Verdict:** NOT A GAP

---

### MOVED Line Only Appears with Cargo

**What tests expect:**
MOVED line showing total m3 transported appears only when cargo is actually moved (manifest with cargo > 0).

**In spec examples?**
Yes - Examples 1 and 2 both show MOVED line.

**In spec prose?**
Yes - Line 65 explicitly states: "* `MOVED` only shows up if there is cargo."

**Can agent infer this?**

*Standard practice?* Yes - only report movement when something moved.

*Pattern in examples?* Yes (though both examples have cargo).

*Clear from context?* Yes - explicitly stated.

*Could implementations reasonably differ?* No - clearly specified.

**Verdict:** NOT A GAP

---

### Trip Separator Format

**What tests expect:**
Multiple trips separated by `[--- TRIP N ---]` markers, where N is the trip number (2, 3, 4, etc.). First trip has no marker.

**In spec examples?**
Yes - Example 2 shows `[--- TRIP 2 ---]` and `[--- TRIP 3 ---]`.

**In spec prose?**
Yes - Line 57 describes: "`[--- TRIP 2 ---]  # If multiple trips needed`"

**Can agent infer this?**

*Standard practice?* Yes - separating sections with markers is common.

*Pattern in examples?* Yes - Example 2 demonstrates the format.

*Clear from context?* Yes - both shown and stated.

*Could implementations reasonably differ?* No - format is explicit.

**Verdict:** NOT A GAP

---

### Return Routes for Subsequent Trips

**What tests expect:**
After delivering cargo on a trip, if more trips are needed, show return route from destination back to source to pick up more cargo.

**In spec examples?**
Yes - Example 2 (lines 118-135) shows return routes:
```
[--- TRIP 2 ---]
UNDOCK
GO: Tama (0.3) -> Nourvukaiken (0.8) -> Tunttaras (0.9) -> Niyabainen (1.0) -> Jita (0.9)
DOCK: Jita IV - Moon 4 - Caldari Navy Assembly Plant
LOAD: 5,000.00 m3
...
```

**In spec prose?**
Yes - Line 59 mentions: "GO: <route back to pickup>"

**Can agent infer this?**

*Standard practice?* Yes - obvious logistics requirement.

*Pattern in examples?* Yes - Example 2 clearly shows return trips.

*Clear from context?* Yes - fully demonstrated.

*Could implementations reasonably differ?* No - logic is straightforward.

**Verdict:** NOT A GAP

---

### Time Calculation Includes move_cargo

**What tests expect:**
Loading and unloading cargo operations each cost `move_cargo` seconds (default: 10s). Total time includes these operations.

**In spec examples?**
Implicit - Example 1 shows DONE: 00:03, which includes cargo time, but not explicitly broken down.

**In spec prose?**
Yes - Line 18 defines: "`move_cargo: <float seconds, >0> # Time to load and unload cargo.`"

**Can agent infer this?**

*Standard practice?* Yes - cargo operations take time.

*Pattern in examples?* Implicit in time calculations.

*Clear from context?* Yes - config defines the parameter.

*Could implementations reasonably differ?* No - parameter is explicitly defined.

**Verdict:** NOT A GAP

---

### Backward Compatibility: No Manifest Means No Cargo

**What tests expect:**
When no --manifest argument provided, route planning works as in checkpoint 1 (no cargo operations). Test `jita_tama` validates this.

**In spec examples?**
No - examples all use manifests.

**In spec prose?**
Yes - Line 32 explicitly states: "* No manifest means no cargo."

**Can agent infer this?**

*Standard practice?* Yes - optional parameters should have sensible defaults.

*Pattern in examples?* No, but explicitly documented.

*Clear from context?* Yes - explicitly stated.

*Could implementations reasonably differ?* No - clearly specified.

**Verdict:** NOT A GAP

---

## Summary of Gaps

**Critical gaps (test failures):**
1. High-sec vs low-sec security threshold - tests expect freighters to avoid systems with security < 0.5, but spec doesn't define "non-high sec"
2. Trip ordering tie-breaking rule - complex rule stated but not demonstrated, agents likely to implement incorrectly

**Ambiguous specifications (need clarification):**
1. "non-high sec systems" - needs explicit definition of security threshold (< 0.5)
2. Tie-breaking criteria interpretation - "Waypoints Finished", "Minimum warps in space with cargo", and "Alphabetical" need concrete example

**Not gaps (agent should infer):**
1. Multi-trip cargo hauling - clearly demonstrated in Example 2
2. Waypoint cargo pickup optimization - shown in Example 2's partial loading strategy
3. Cargo formatting - shown consistently in examples
4. null cargo handling - explicitly documented
5. MOVED line conditional - explicitly stated
6. Trip separators - shown in examples
7. Return routes - demonstrated in Example 2
8. move_cargo time inclusion - parameter is defined
9. No manifest backward compatibility - explicitly stated

---

## Recommended Additions

**New examples needed:**
1. Freighter routing example showing avoidance of 0.4 systems and use of 0.5+ systems (makes security threshold explicit)
2. Trip ordering tie-breaking example with equal-cargo waypoints showing alphabetical ordering

**Prose clarifications needed:**
1. Lines 36-38: Define security thresholds explicitly (high-sec >= 0.5, low-sec 0.1-0.4, null-sec <= 0.0)
2. Line 35: Consider expanding tie-breaking rule explanation with concrete definitions of each criterion
