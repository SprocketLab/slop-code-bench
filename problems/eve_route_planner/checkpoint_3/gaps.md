# Checkpoint 3 Gap Analysis

## Summary
Introduces contract hauling with profit optimization: selecting best ship, filtering contracts by profitability and risk constraints, planning multi-contract routes with return trip optimization.

**Total behaviors tested:** 10
**True gaps found:** 3
**Not gaps (inferrable):** 7
**Over-specified (handled in over-spec rubric):** 0

---

## Test Behaviors Analysis

### Basic Contract Execution with Round Trip

**What tests expect:**
Execute single contract: travel to pickup location, load contract, deliver to destination, return to base. Output includes ship selection, route with LOAD/UNLOAD operations showing issuer and contract ID, and final statistics (NUM CONTRACTS, PROFIT, ISK/M3, ISK/Jump including return, ISK/Hour).

**In spec examples?**
No - no examples provided in spec.

**In spec prose?**
Yes - Lines 1-53 describe contracts command, output format, and statistics.

**Can agent infer this?**

*Standard practice?* No - complex domain-specific format, but fully specified.

*Pattern in examples?* No examples provided.

*Clear from context?* Yes - output format is explicitly described.

*Could implementations reasonably differ?* No - format is detailed.

**Verdict:** NOT A GAP

**Reasoning:**
While no examples are shown, the spec provides detailed format specifications. The lack of examples makes implementation harder but isn't a gap per the rubric - the information is present.

---

### max_isk_per_ehp Constraint Filtering

**What tests expect:**
Reject contracts where (actual_value / ship_ehp) > max_isk_per_ehp. Blockade Runners are exempt. Test validates: 10B actual value / 600K EHP = 16,667 ISK/EHP exceeds 350 limit → reject contract.

**In spec examples?**
No examples.

**In spec prose?**
Partially - Line 25 states: "`max_isk_per_ehp` which is a float... the _maximum_ value you would allow to be carried (does NOT apply to blockade runners)."

**Can agent infer this?**

*Standard practice?* No - domain-specific risk metric.

*Pattern in examples?* No examples.

*Clear from context?* Ambiguous - "maximum value you would allow to be carried" could mean:
1. Maximum total value in the ship (actual_value <= max_isk_per_ehp)
2. Maximum value per unit of EHP (actual_value / ehp <= max_isk_per_ehp) [CORRECT]

*Could implementations reasonably differ?* YES - agents could interpret as:
- A cap on total cargo value
- A ratio calculation (correct interpretation)
- A different formula entirely

**Ambiguity:**
The phrase "maximum value you would allow to be carried" describes the constraint's purpose (risk management) but not the formula. The calculation (actual_value / ship_ehp <= max_isk_per_ehp) is not stated explicitly.

**Verdict:** TRUE GAP

**Fix:** CLARIFY

**Specific specification:**

**Clarify prose (line 25):**

**Current text:**
> "The latter is the _maximum_ value you would allow to be carried (does NOT apply to blockade runners)."

**Replace with:**
> "`max_isk_per_ehp`: Maximum risk tolerance ratio. For each contract, calculate `actual_value / ship_ehp`. Reject contracts where this ratio exceeds `max_isk_per_ehp`. This constraint does NOT apply to Blockade Runners (they are exempt due to speed/agility)."

**Add Example:**
```
Example:
- Contract actual_value: 210,000,000 ISK
- Ship EHP: 600,000
- Ratio: 210M / 600K = 350 ISK/EHP
- max_isk_per_ehp: 350
- Result: 350 <= 350 → Contract ACCEPTED

- Contract actual_value: 10,000,000,000 ISK
- Ship EHP: 600,000
- Ratio: 10B / 600K = 16,667 ISK/EHP
- max_isk_per_ehp: 350
- Result: 16,667 > 350 → Contract REJECTED
```

**Why this is needed:**
"Maximum value you would allow" is ambiguous - it describes the constraint's purpose but not the calculation method. Agents need the explicit formula. Multiple reasonable interpretations exist without the formula.

---

### min_isk_per_jump Constraint Filtering

**What tests expect:**
Reject contracts where (reward / total_jumps_including_return) < min_isk_per_jump. Test validates: 2.9M reward / 4 total jumps = 725K ISK/jump < 1M minimum → reject contract.

**In spec examples?**
No examples.

**In spec prose?**
Partially - Lines 25-26 state: "The former represents the minimum isk per jump that you would consider worth it. A contract's isk/jump is based on the total number of jumps it would require in addition to your current route."

**Can agent infer this?**

*Standard practice?* No - domain-specific profitability metric.

*Pattern in examples?* No examples.

*Clear from context?* Ambiguous - "in addition to your current route" could mean:
1. Incremental jumps added to existing route
2. Total jumps for the contract (pickup + delivery + return to base) [CORRECT]

*Could implementations reasonably differ?* YES - agents could interpret as:
- Only the jumps to deliver the contract (not including return)
- Jumps added to an existing route (incremental)
- Total round-trip jumps from base to pickup to delivery back to base (correct)

**Ambiguity:**
The phrase "in addition to your current route" suggests incremental jumps added to an existing route. However, tests show the calculation includes the FULL round trip: jumps from base to pickup, pickup to delivery, and delivery back to base.

Test case: Hek → Lanngisi (2 jumps) → Hek (2 jumps) = 4 total jumps. With 2.9M reward: 2.9M / 4 = 725K ISK/jump.

**Verdict:** TRUE GAP

**Fix:** CLARIFY

**Specific specification:**

**Clarify prose (lines 25-26):**

**Current text:**
> "The former represents the minimum isk per jump that you would consider worth it. A contract's isk/jump is based on the total number of jumps it would require in addition to your current route."

**Replace with:**
> "`min_isk_per_jump`: Minimum profitability threshold. For each contract, calculate the full round-trip jumps: (jumps from base to pickup location) + (jumps from pickup to delivery location) + (jumps from delivery back to base). Divide the reward by this total. Reject contracts where `reward / total_round_trip_jumps < min_isk_per_jump`."

**Add Example:**
```
Example:
- Base: Hek
- Contract: Pickup at Lanngisi, Deliver to Hek
- Route: Hek → Lanngisi (2 jumps), Lanngisi → Hek (2 jumps)
- Total jumps: 4
- Reward: 2,900,000 ISK
- ISK/Jump: 2.9M / 4 = 725,000 ISK/jump
- min_isk_per_jump: 1,000,000
- Result: 725K < 1M → Contract REJECTED

- Contract: Pickup at Hek, Deliver to Nakugard
- Route: Hek → Nakugard (1 jump), Nakugard → Hek (1 jump)
- Total jumps: 2
- Reward: 5,000,000 ISK
- ISK/Jump: 5M / 2 = 2,500,000 ISK/jump
- min_isk_per_jump: 1,000,000
- Result: 2.5M > 1M → Contract ACCEPTED
```

**Why this is needed:**
"In addition to your current route" is ambiguous and suggests incremental calculation. The actual calculation includes the complete round trip from base. Without an example, agents cannot determine whether to include return jumps or how to count jumps for contracts that start or end at the base location.

---

### "Most Profitable" Optimization Objective

**What tests expect:**
When `--max-time` is set, select the combination of contracts that maximizes total profit within the time limit. Test `max_time` shows: Two contracts available (4.9M and 5.0M), choose the 5.0M contract that fits in 15 minutes.

**In spec examples?**
No examples.

**In spec prose?**
Partially - Lines 15-17 state:
> "Our goal is to find the most profitable hauling plan we can come up with. `--max-time` sets the maximum amount of time we want to be hauling for. If returning to our base puts us over it, that is fine. If omitted, then 'most profitable' means ALL contracts that fit our constraints."

**Can agent infer this?**

*Standard practice?* Somewhat - "most profitable" intuitively means maximum money, but could be measured different ways.

*Pattern in examples?* No examples.

*Clear from context?* Ambiguous - "most profitable" could mean:
1. Maximum total profit (sum of all reward values) [CORRECT when max-time set]
2. Maximum ISK per hour
3. Maximum ISK per jump
4. Maximum ISK per m3
5. Some weighted combination

*Could implementations reasonably differ?* YES - agents could optimize for:
- Total profit (correct for max-time scenarios)
- ISK/hour (time efficiency)
- ISK/jump (routing efficiency)
- Number of contracts completed
- Different objectives for max-time vs no-max-time scenarios

**Ambiguity:**
When `--max-time` is set, what does "most profitable" mean? The spec doesn't define the optimization objective. Test `max_time` shows selecting the higher-value contract (5.0M vs 4.9M) that fits in the time limit, suggesting maximizing total profit.

However, what if you could do the 4.9M contract twice in the same time window, earning 9.8M? Should you prefer that over a single 5.0M contract?

The spec doesn't clarify:
- Maximize total profit within time limit
- Maximize ISK/hour
- Maximize number of contracts
- Some other objective

**Verdict:** TRUE GAP

**Fix:** CLARIFY and ADD-EXAMPLE

**Specific specification:**

**Clarify prose (lines 15-17):**

**Current text:**
> "Our goal is to find the most profitable hauling plan we can come up with. `--max-time` sets the maximum amount of time we want to be hauling for. If returning to our base puts us over it, that is fine. If omitted, then 'most profitable' means ALL contracts that fit our constraints."

**Replace with:**
> "Our goal is to maximize total profit from hauling contracts.
>
> **When `--max-time` is set:** Select the combination of contracts that maximizes total profit (sum of rewards) while keeping total route time ≤ max-time. You may exceed max-time when returning to base.
>
> **When `--max-time` is omitted:** Execute ALL contracts that meet the constraints (min_isk_per_jump, max_isk_per_ehp, cargo capacity). If multiple contracts require multiple trips, execute them all sequentially.
>
> **Optimization objective:** Maximize `sum(contract_rewards)` subject to time and constraint limits."

**Add Example: Contract Selection with max-time**

**Setup:**
```jsonl
{"start": "Hek VIII", "end": "Lanngisi III", "reward": 4900000, "m3": 100000, "actual_value": 210000000, "issuer": "Alice", "collateral": 0}
{"start": "Hek VIII", "end": "Nakugard V", "reward": 5000000, "m3": 100000, "actual_value": 210000000, "issuer": "Bob", "collateral": 0}
```

```sh
hauling contracts "Hek VIII - Moon 12 - Boundless Creation Factory" contracts.jsonl --config config.yaml --max-time 15 --sde ./sde/
```

**Available contracts:**
- Contract 1: Hek → Lanngisi (2 jumps each way = 4 total), 4.9M ISK, ~15 minutes total
- Contract 2: Hek → Nakugard (1 jump each way = 2 total), 5.0M ISK, ~10 minutes total

**Expected behavior:**
- Select Contract 2 (5.0M ISK in 10 minutes)
- Contract 1 would take ~15 minutes, equal to limit, but lower profit
- Objective: Maximize total profit → Choose 5.0M over 4.9M

**Output:**
```
SHIP: Rhea
START: Hek VIII - Moon 12 - Boundless Creation Factory
LOAD Bob (id=2): 5.00M ISK | 100,000.00 m3
UNDOCK
GO: Hek (0.8) -> Nakugard (0.5)
DOCK: Nakugard V - Moon 1 - Republic Justice Department Tribunal
UNLOAD Bob (id=2): 2 Jumps | 100,000.00 m3
[Return route]
DONE: 00:10
MOVED: 100,000.00 m3
NUM CONTRACTS: 1
PROFIT: 5.00M
ISK/Jump: 2.50M
ISK/Hour: 30.33M
```

**What this demonstrates:**
- When max-time is set, choose contracts that maximize total profit within time limit
- Higher total profit preferred over higher ISK/hour when both fit the constraint
- Clear optimization objective: maximize sum(rewards)

**Why this is needed:**
"Most profitable" is ambiguous - could mean total profit, ISK/hour, ISK/jump, or other metrics. Different reasonable interpretations would lead to different contract selections. Without explicit objective function and example, agents may optimize for the wrong metric.

---

### Ship Selection with Time Minimization

**What tests expect:**
Select fastest ship that can carry the cargo. Tiebreaker: EHP (higher better), then Name (alphabetical). Test `blockade_runner` validates: Prowler selected over Charon for 5K m3 cargo (both can carry it, Prowler is faster).

**In spec examples?**
No examples.

**In spec prose?**
Yes - Line 10 states: "You must select the best ship to minimize travel time. If two ships are equivalent then the tiebreaker is EHP then Name."

**Can agent infer this?**

*Standard practice?* Yes - selecting optimal resources is standard optimization.

*Pattern in examples?* No examples, but rule is explicit.

*Clear from context?* Yes - explicitly stated.

*Could implementations reasonably differ?* No - rule is clear.

**Verdict:** NOT A GAP

---

### Multiple Trips for Multiple Contracts

**What tests expect:**
When multiple contracts can't fit simultaneously (due to cargo capacity or routing), execute them in separate trips with `[--- TRIP N ---]` separators. Accumulate statistics across all trips.

**In spec examples?**
No examples.

**In spec prose?**
Partially - Line 20 states: "You CAN pick up as many contracts as possible." Line 17 implies multiple trips: "If omitted, then 'most profitable' means ALL contracts that fit our constraints."

**Can agent infer this?**

*Standard practice?* Yes - multiple trips for multiple tasks when capacity constrained.

*Pattern in examples?* No examples, but behavior follows checkpoint 2 patterns.

*Clear from context?* Yes - implied by constraints and goals.

*Could implementations reasonably differ?* No - logical extension of multi-trip hauling from checkpoint 2.

**Verdict:** NOT A GAP

**Reasoning:**
This extends the multi-trip behavior from checkpoint 2. While no example is shown, the logic is straightforward given the constraints and checkpoint 2 patterns.

---

### Return Trip Optimization

**What tests expect:**
When returning to base, check for contracts that end at base and pick them up on the return trip (instead of empty return). Test `return_trip` validates: Loading contract 6 (Lanngisi → Hek) during return from delivering contract 1.

**In spec examples?**
No examples.

**In spec prose?**
Yes - Line 22 states: "You are allowed to pickup contracts that end at the original start location."

**Can agent infer this?**

*Standard practice?* Yes - return load optimization is common in logistics.

*Pattern in examples?* No examples.

*Clear from context?* Yes - explicitly allowed, and "most profitable" implies optimization.

*Could implementations reasonably differ?* Potentially - agents might not realize this is an optimization opportunity, but the spec allows it and the goal is "most profitable."

**Verdict:** NOT A GAP

**Reasoning:**
The spec explicitly allows this behavior, and the goal of maximizing profit implies using it. While an example would help, agents pursuing "most profitable" should discover this optimization.

---

### Multiple Simultaneous Contracts

**What tests expect:**
Carry multiple contracts simultaneously when they fit in cargo capacity and routing is compatible. Test `inline_stop` validates: Carrying 2 contracts (20K m3 each) in Occator (60K capacity) with stops at multiple stations.

**In spec examples?**
No examples.

**In spec prose?**
Yes - Line 21 states: "You CAN pick up as many contracts as possible."

**Can agent infer this?**

*Standard practice?* Yes - maximizing cargo utilization is standard logistics.

*Pattern in examples?* No examples.

*Clear from context?* Yes - "as many contracts as possible" implies simultaneous carrying when possible.

*Could implementations reasonably differ?* No - constraint is clear (cargo capacity), behavior is implied.

**Verdict:** NOT A GAP

**Reasoning:**
"Pick up as many contracts as possible" combined with cargo capacity constraints clearly implies simultaneous carrying when cargo fits.

---

### Blockade Runner EHP Exemption

**What tests expect:**
Blockade Runners ignore max_isk_per_ehp constraint. Test validates: Prowler carries 1B ISK cargo (1B / 10K EHP = 100K ISK/EHP) that would fail 350 limit on other ships.

**In spec examples?**
No examples.

**In spec prose?**
Yes - Lines 25 and 28 state: "does NOT apply to blockade runners" and "Blockade runners do not care about EHP because they suppppaaaa fast."

**Can agent infer this?**

*Standard practice?* No - domain-specific rule.

*Pattern in examples?* No examples.

*Clear from context?* Yes - explicitly stated (with emphasis: "suppppaaaa fast").

*Could implementations reasonably differ?* No - rule is explicit.

**Verdict:** NOT A GAP

---

### In-System Station Changes

**What tests expect:**
DOCK operations between stations in the same system without GO line. Test `inline_stop` validates: DOCK at Jita Moon 6 after loading at Jita Moon 4 (same system, no GO).

**In spec examples?**
No examples in checkpoint 3 spec.

**In spec prose?**
No - this behavior is from checkpoint 1.

**Can agent infer this?**

*Standard practice?* N/A - covered by checkpoint 1.

*Pattern in examples?* Checkpoint 1 Example 2 demonstrates this.

*Clear from context?* Yes - checkpoint 1 spec explicitly states (line 101): "omitted if traveling within same system"

*Could implementations reasonably differ?* No - already specified in checkpoint 1.

**Verdict:** NOT A GAP (covered by checkpoint 1)

---

### No Good Contracts Message

**What tests expect:**
When all contracts fail constraints, output "No Good Contracts". Test `basic_ehp_cap` validates this.

**In spec examples?**
No examples.

**In spec prose?**
Yes - Line 29 states: "If no contracts fulfill the constraints then print 'No Good Contracts'"

**Can agent infer this?**

*Standard practice?* Yes - reporting when no valid options exist is standard.

*Pattern in examples?* No examples.

*Clear from context?* Yes - explicitly stated with exact message.

*Could implementations reasonably differ?* No - message is specified exactly.

**Verdict:** NOT A GAP

---

## Summary of Gaps

**Critical gaps (test failures):**
1. max_isk_per_ehp formula not stated - agents don't know to divide actual_value by ship_ehp
2. min_isk_per_jump calculation ambiguous - "in addition to your current route" unclear about including return trip
3. "Most profitable" objective undefined - could mean total profit, ISK/hour, ISK/jump, etc.

**Ambiguous specifications (need clarification):**
1. max_isk_per_ehp: "maximum value you would allow" doesn't specify the ratio calculation
2. min_isk_per_jump: "in addition to your current route" suggests incremental jumps, but tests show total round-trip jumps
3. "Most profitable": No explicit optimization objective (maximize total reward sum, ISK/hour, etc.)

**Not gaps (agent should infer):**
1. Ship selection tiebreaker - explicitly stated
2. Multiple trips for multiple contracts - follows checkpoint 2 patterns
3. Return trip optimization - explicitly allowed and implied by "most profitable" goal
4. Multiple simultaneous contracts - "as many as possible" implies simultaneous when cargo allows
5. Blockade Runner EHP exemption - explicitly stated
6. In-system station changes - covered by checkpoint 1 spec
7. No good contracts message - explicitly stated with exact wording

---

## Recommended Additions

**New examples needed:**
1. Basic contract execution showing full workflow (ship selection, route with LOAD/UNLOAD, statistics)
2. max-time contract selection showing optimization for total profit
3. Constraint filtering examples (min_isk_per_jump and max_isk_per_ehp with calculations)

**Prose clarifications needed:**
1. Line 25: Add explicit formula for max_isk_per_ehp calculation (actual_value / ship_ehp <= max)
2. Lines 25-26: Clarify min_isk_per_jump calculation includes full round trip from base to pickup to delivery back to base
3. Lines 15-17: Define optimization objective explicitly (maximize sum of rewards when max-time set, execute all contracts when not set)
