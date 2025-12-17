# Checkpoint 1 Gap Analysis

## Summary
Establishes baseline EVE Online route planning: parsing station/system names, pathfinding through stargates, calculating travel time with complex warp physics, handling special Zarzakh mechanics, and formatting route output.

**Total behaviors tested:** 9
**True gaps found:** 1
**Not gaps (inferrable):** 8
**Over-specified (handled in over-spec rubric):** 0

---

## Test Behaviors Analysis

### Station-to-Station Route Planning

**What tests expect:**
Complete route planning from named station to named station with full output format including UNDOCK, multi-system path with security status, DOCK, and total time. Tests station name parsing, multi-jump pathfinding, time calculation, and output formatting.

**In spec examples?**
Yes - Example 1 (lines 110-122) demonstrates exactly this behavior with Jita station to Tama station.

**In spec prose?**
Yes - Rules at lines 20-25 specify station start = docked (needs undock) and station end = must dock. Output format described at lines 94-105.

**Can agent infer this?**

*Standard practice?* No - EVE-specific format, but clearly shown in example.

*Pattern in examples?* Yes - Example 1 shows complete pattern including conditionals.

*Clear from context?* Yes - example demonstrates all components.

*Could implementations reasonably differ?* No - example is specific and clear.

**Verdict:** NOT A GAP

---

### System-to-System Route Planning

**What tests expect:**
Route planning between two systems (not stations). No UNDOCK or DOCK operations, only START, GO, and DONE. Tests that agents understand start/end position rules correctly.

**In spec examples?**
No - no pure system-to-system example shown.

**In spec prose?**
Yes - Rules at lines 22-25 explicitly state:
- "If `start` is a **system** → pilot starts in space at the gate"
- "If `end` is a **system** → route completes upon entering that system"

**Can agent infer this?**

*Standard practice?* No - EVE-specific rules.

*Pattern in examples?* Partial - Example 2 shows system-to-station (no UNDOCK). Can infer the pattern.

*Clear from context?* Yes - rules explicitly state the conditionals, Example 2 demonstrates system start (no UNDOCK), and output format description at line 100 states "UNDOCK line (only if starting from a station)".

*Could implementations reasonably differ?* No - rules are explicit about when UNDOCK/DOCK appear.

**Verdict:** NOT A GAP

**Reasoning:**
The rules explicitly specify the conditionals, and Example 2 demonstrates a system start (no UNDOCK). An agent can deduce that system-to-system means neither UNDOCK nor DOCK.

---

### Station-to-System Long-Distance Route

**What tests expect:**
Long-distance route (11+ systems) from station to system. UNDOCK present, no DOCK. Tests extended pathfinding and correct application of start/end rules.

**In spec examples?**
No - no long-distance example shown.

**In spec prose?**
Yes - Rules at lines 20-25 specify station start = UNDOCK, system end = no DOCK.

**Can agent infer this?**

*Standard practice?* N/A - distance doesn't change rules.

*Pattern in examples?* Yes - can apply rules from Examples 1 and 2.

*Clear from context?* Yes - it's just application of stated rules.

*Could implementations reasonably differ?* No - rules are explicit.

**Verdict:** NOT A GAP

**Reasoning:**
This is simply applying the start/end position rules to a longer route. No new behavior is introduced.

---

### Zarzakh Gate Lock and Waiting Mechanics

**What tests expect:**
When routing through Zarzakh to a system different from origin, solution must:
1. Include 6-hour waiting period in travel time calculation
2. Add this 6h to the total DONE time
3. Choose this route only if faster than alternatives

Test case: Turnur → Zarzakh → Alsavoinon with parameters resulting in 8:03 total time (includes ~6h wait + ~2h travel).

**In spec examples?**
No - no Zarzakh example shown.

**In spec prose?**
Partially - Lines 27-30 state:
> "Entering Zarzakh via a gate locks you to that gate for 6h -> you can only leave Zarzakh back to the system you came from during that time."
> "Docking does not reset the lock."
> "Entering into Zarzakh from another gate resets the lock to that new gate."
> "Waiting is allowed if faster overall."

**Can agent infer this?**

*Standard practice?* No - EVE-specific game mechanic.

*Pattern in examples?* No - no Zarzakh example to demonstrate the behavior.

*Clear from context?* Ambiguous - the rules describe the lock mechanism but the operational implications for time calculation are unclear.

*Could implementations reasonably differ?* YES - agents could interpret this as:
1. "Locked for 6h" means cannot route through Zarzakh at all to non-origin destinations
2. Can route through Zarzakh but don't add waiting time to calculation
3. "Waiting is allowed if faster overall" means waiting is optional rather than required
4. Don't understand that the 6h wait should be included in the DONE time output
5. Unclear when exactly the wait applies (always when going forward? only to non-origin systems?)

**Ambiguity:**
The phrase "Waiting is allowed if faster overall" is ambiguous. It could mean:
- (A) "Waiting is permitted as a valid strategy; choose routes with waiting if they're faster than alternatives"
- (B) "Waiting automatically occurs if the route through Zarzakh is faster overall"

Interpretation (A) is correct - waiting is REQUIRED when going forward through Zarzakh (because you can't leave except back for 6h), and you should choose this route only if it's faster. But interpretation (B) is also reasonable.

Additionally, the spec doesn't explicitly state:
- That the 6h waiting period must be ADDED to the travel time calculation
- That this wait time should appear in the DONE time output
- The exact condition: waiting applies when routing to any system except the origin

**Verdict:** TRUE GAP

**Fix:** CLARIFY and ADD-EXAMPLE

**Specific specification:**

**Clarify prose (lines 27-30):**

**Replace:**
> "Entering Zarzakh via a gate locks you to that gate for 6h -> you can only leave Zarzakh back to the system you came from during that time."
> "Docking does not reset the lock."
> "Entering into Zarzakh from another gate resets the lock to that new gate."
> "Waiting is allowed if faster overall."

**With:**
> "Entering Zarzakh via a gate locks you to that gate for 6 hours. During this lock period, you can only leave Zarzakh back to the system you came from. To leave Zarzakh to any other system, you must wait until the 6-hour lock expires."
> "Docking does not reset the lock timer."
> "Entering Zarzakh from another gate resets the lock to that new gate (restarting the 6-hour timer)."
> "When calculating routes through Zarzakh, add 6 hours to the travel time for each forward transit (leaving to a system other than your origin). Choose routes with Zarzakh waiting only if the total time is still faster than alternative routes."

**Add Example 3: Routing Through Zarzakh**

**Setup:**
```sh
hauling Turnur Alsavoinon --align 60 --top-speed 100 --warp-speed 1.5 --dock-time 5 --gate-time 3600 --sde ./sde/
```

**Expected output:**
```
START: Turnur
GO: Turnur (0.4) -> Zarzakh (-1.0) -> Alsavoinon (0.3)
DONE: 08:03
```

**What this demonstrates:**
- Zarzakh appears in route with negative security status (-1.0)
- Total time (08:03 = 8 hours 3 minutes) includes the 6-hour Zarzakh gate lock waiting period
- With gate-time of 3600s (1 hour) and 2 gates, base travel is ~2 hours
- Additional ~6 hours shows the mandatory waiting period
- This route was chosen because it's faster than alternatives (even with the 6h wait)

**Why this is needed:**
The Zarzakh mechanic is complex and EVE-specific. Without an example, agents cannot see:
1. How the waiting time integrates into the route time calculation
2. That the 6h wait appears in the DONE time
3. That Zarzakh is a valid routing option when faster overall
4. The specific condition triggering the wait (forward transit, not back to origin)

Multiple reasonable implementations would differ on how to handle this mechanic. The prose describes the restriction but not the operational implementation for time calculation.

---

### Security Status Formatting

**What tests expect:**
Security status displayed with one decimal place in parentheses: (0.9), (1.0), (0.3), (-1.0)

**In spec examples?**
Yes - Examples 1 and 2 show (0.9), (1.0), (0.8), (0.3) format consistently.

**In spec prose?**
Partially - Line 96 mentions "security status in parentheses" but doesn't specify decimal precision.

**Can agent infer this?**

*Standard practice?* Yes - one decimal place is common for displaying security status.

*Pattern in examples?* Yes - all examples use one decimal place consistently.

*Clear from context?* Yes - pattern is obvious.

*Could implementations reasonably differ?* No - pattern is clear and consistent.

**Verdict:** NOT A GAP

---

### Time Formatting (HH:MM with Leading Zeros)

**What tests expect:**
Time formatted as HH:MM with leading zeros: 00:02, 00:01, 08:03

**In spec examples?**
Yes - Examples show 00:02 and 00:01.

**In spec prose?**
Yes - Line 105 explicitly states: "formatted with two digits for both hours and minutes (e.g., "00:45" for 45 minutes, "02:15" for 2 hours 15 minutes)"

**Can agent infer this?**

*Standard practice?* Yes - time formatting with leading zeros is common.

*Pattern in examples?* Yes - examples demonstrate the format.

*Clear from context?* Yes - both shown and stated.

*Could implementations reasonably differ?* No - explicitly specified.

**Verdict:** NOT A GAP

---

### Time Rounding Up to Nearest Minute

**What tests expect:**
Travel time rounded up to nearest minute before display.

**In spec examples?**
No - examples show 00:02 and 00:01 but you can't tell if these were rounded or exact.

**In spec prose?**
Yes - Line 105 explicitly states: "always rounded up to the nearest minute"

**Can agent infer this?**

*Standard practice?* Somewhat - rounding time is common, but could round down, up, or to nearest.

*Pattern in examples?* No - can't see rounding in examples.

*Clear from context?* Yes - explicitly stated in prose.

*Could implementations reasonably differ?* Yes without the prose - could round down or to nearest.

**Verdict:** NOT A GAP (prose specification is necessary)

---

### Shortest Path Calculation

**What tests expect:**
Route should follow the shortest path by number of jumps between systems.

**In spec examples?**
Implicit - examples show routes that appear to be shortest paths.

**In spec prose?**
No - doesn't explicitly state "find shortest path" or "minimize jumps".

**Can agent infer this?**

*Standard practice?* Yes - route planning typically finds optimal paths. In context of EVE with uniform gate connections, shortest path by jumps is standard.

*Pattern in examples?* Yes - examples show sensible shortest routes.

*Clear from context?* Yes - it's a route planning tool, and Zarzakh rule mentions "faster overall", indicating optimization.

*Could implementations reasonably differ?* No - route planning implies finding good routes.

**Verdict:** NOT A GAP

**Reasoning:**
Route optimization is fundamental to route planning. The Zarzakh rule's phrase "if faster overall" indicates that the tool should optimize for travel time, which correlates with shortest path when gate times are uniform.

---

### GO Line Omission for Same-System Travel

**What tests expect:**
When start and end are in the same system, GO line is omitted from output.

**In spec examples?**
Yes - Example 2 shows Jita (system) to Jita station with no GO line.

**In spec prose?**
Yes - Line 101 explicitly states: "(omitted if traveling within same system)"

**Can agent infer this?**

*Standard practice?* No specific standard.

*Pattern in examples?* Yes - Example 2 demonstrates this.

*Clear from context?* Yes - both shown and stated.

*Could implementations reasonably differ?* No - explicitly specified and demonstrated.

**Verdict:** NOT A GAP

---

## Summary of Gaps

**Critical gaps (test failures):**
1. Zarzakh waiting time calculation - tests expect 6h wait to be added to total time, but spec prose is ambiguous about operational implementation

**Ambiguous specifications (need clarification):**
1. "Waiting is allowed if faster overall" - unclear whether this means waiting is optional or describes when to choose the Zarzakh route
2. Operational calculation of Zarzakh wait - not explicit that 6h should be added to DONE time

**Not gaps (agent should infer):**
1. System-to-system routing (no UNDOCK/DOCK) - rules explicitly specify conditionals
2. Station-to-system routing (UNDOCK but no DOCK) - applying stated rules
3. Security status formatting - clear pattern in examples
4. Time formatting with leading zeros - explicitly stated and demonstrated
5. Time rounding up - explicitly stated in prose (necessary specification)
6. Shortest path calculation - standard practice for route planning
7. GO line omission - explicitly stated and demonstrated in Example 2

---

## Recommended Additions

**New examples needed:**
1. Zarzakh routing example showing negative security status, 6h wait included in time, and demonstrating when the wait applies

**Prose clarifications needed:**
1. Lines 27-30: Clarify Zarzakh mechanic to explicitly state that 6h wait must be added to travel time calculation for forward transits
2. Lines 27-30: Replace "Waiting is allowed if faster overall" with clearer language about when to choose Zarzakh routes and how to calculate the waiting period
