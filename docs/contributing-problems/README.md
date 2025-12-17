# Problem Design Philosophy

This guide helps you design problems that test whether agents can write flexible, maintainable code. **Read this before implementing your problem.**

## How to Use This Guide

1. **Read this page** to understand what makes a good problem
2. **See [Example: Calculator Problem](example_process.md)** for the design process in action
3. **Move to [Step-by-Step Tutorial](../problems/tutorial.md)** when ready to code
4. **Use the [Validation Checklist](checklist.md)** before submitting

---

## Core Philosophy

This benchmark tests whether SWE agents generate *flexible* and *maintainable* code. Code doesn't live in a single-iteration vacuum—designs change due to new information or optimization needs. Good code is written so that extending it or adding new functionality is painless and intuitive.

We test this through complex, multi-stage problems that have an inherent underlying structure. Good SWEs should design their code from the start to reflect this structure. Each problem has multiple **checkpoints** where new complexity is added.

**Target complexity:** Problems should take experienced software engineers about a week (~40 hours / ~3K LOC) to solve, assuming domain familiarity.

---

## Coming Up With Problems

At their core, problems contain inherent logical abstractions that *should* be separated:
- For a fraud detection pipeline: transactions, accounts, rules, and universe data (currencies, merchants)
- For a training loop: update steps, datasets, models, evaluation

**Best approach:** Take a tool/app/repo you know well and turn it into a problem. Add twists during checkpoints to prevent exact 1:1 implementations.

**Alternative:** Think about what you've asked Claude Code/Codex to build that it failed at.

**Constraints:** No frontend/visual problems for now.

**Example problems that work:**
- A rule-based battle simulator that runs many trials ([euiv.pdxsimulator.com](https://euiv.pdxsimulator.com))
- A pantry manager tracking food expiration, partial usage, and money wasted
- Agentic scaffolding that parses response messages and updates state using configured tools

---

## Checkpoints

There is a significant difference between first and subsequent checkpoints:

**First checkpoint:**
- Sets up the *entire* problem—gives the overall purpose
- Verbose about deliverables and error handling

**Subsequent checkpoints:**
- Describe a single focused behavior that extends prior checkpoints
- Less verbose—elements not mentioned are assumed unchanged

### Checkpoint Sizing

**Too small:**
```
Add support for triggering rules when an account is used at a merchant
it had never purchased from before.
```
- Too simple for a checkpoint
- If adding multiple things of the same type (rules, config types, file types), combine them
- It's easier to split a large checkpoint than combine many small ones

**Too broad:**
```
Extend the detection algorithm to flag transactions, return to them after
a period of time to determine if fraudulent. Use fraudulent transactions
to build a "suspicious" merchant score as a triggering weight.
```
- Way too unfocused
- Break it up: one checkpoint for flagging/returning, another for merchant weighting
- These parts are barely related to each other

**Good:**
```
Extend the detection algorithm to flag transactions and return to them
after a period of time to determine if fraudulent. Use config rules to
keep a running score with the `severity` key. A global `threshold` key
determines when suspicious becomes fraudulent. If not specified, any
flagged transaction is fraudulent.
```
- Focused on a *single* large core feature
- No unrelated functionality

### What Checkpoints CAN Do

The ideal checkpoint changes internal representations without changing output "shape":

- **Expand constraints:** "Now we provide account-to-person mapping. Update flagging for cross-account patterns."
- **Narrow constraints:** "Rules can now have a sliding window via `minutes` field. Rules without it don't use windows."
- **Modify input source:** "Change `--input` to handle both directories and STDIN"
- **Change modality:** "Convert the CLI app into a REST API"

### What Checkpoints Should NOT Do

- **Change the core problem:** "Calculate bank balances instead of flagging fraud"
- **Add unrelated problems:** "Add data breach detection to fraud flagging"

Checkpoints are natural extensions of prior specifications.

---

## Writing Specifications

### General Guidelines

**Be verbose and explicit.** It's easier to cut details than stitch them together.

| DON'T | DO |
|-------|-----|
| "Write results to a csv file at `--output`" | "Write results as CSV to `--output`, rows sorted by `Name` ascending" |

**Prefer examples over descriptions.** Examples convey tie-breaking, sorting, and formatting better than prose.

| DON'T | DO |
|-------|-----|
| "Format with 2 decimal places as a dollar amount" | "The result 2.957 prints as `$2.96`" |

**Include domain knowledge.** Don't test web search ability—provide equations and rules directly.

| DON'T | DO |
|-------|-----|
| "Soccer rules can be found on the web" | "Use the exact rules in this document {URL}" |

**Describe behavior, not structure.** The agent determines optimal design.

| DON'T | DO |
|-------|-----|
| "Create a Player base class for Forwards and Defenders" | "10 players and one goalie per team, each team defends a goal" |

**First checkpoint defines the core problem.** You can't change it later.

| DON'T | DO |
|-------|-----|
| CP1: transaction parser | CP1: Fraud detector for transactions |
| CP2: fraud detection | CP2: Track suspicious activity before flagging |
| CP3: fee profit calculator | CP3: Track suspicious merchants |

---

## Evaluation as Black Boxes

All problems are evaluated as **black boxes**:

- We don't prescribe internal structure or interfaces
- We only specify:
  - Entry file name (with language extension)
  - CLI: All flags/arguments
  - API: Flags/arguments + all endpoints
- We specify output format:
  - CLI: STDOUT/STDERR/output files
  - API: Response shapes for each endpoint

**Anything that could cause non-deterministic grading must be specified:**
- Tie-breaking and sorting
- Exit codes and error message formats

We don't penalize library use. Problems should require more than a single library call to solve.

### Specification Detail Level

**Too terse:**
```
An alert can only be triggered once per window.
```
- Missing: windows are in seconds
- Missing: lower bound is inclusive

**Too verbose (solution-giving):**
```
Daily windows (24h) are used only for amount_threshold.
All other rules use tumbling windows aligned to Unix epoch:
Window [W, W+Δ) where W = floor(ts / Δ) * Δ, Δ = window_minutes * 60s.
Deduplicate by (rule_id, account_id, window_start_iso)...
```
- Gives away the entire solution

**Good:**
```
Alerts with windows trigger once per window (seconds, lower bound inclusive).
Example: an alert for 5 events in 3 hours triggers on the 5th event.
A 6th event in the same window does not re-trigger.
```
- States units (seconds) and bounds (lower inclusive)
- Concrete example clarifies behavior
- Doesn't reveal implementation details

---

## Common Pitfalls

**Prescribing data structures**

| Bad | Good |
|-----|------|
| "Store transactions in a hash map keyed by account_id" | "Retrieve all transactions for an account in under 100ms" |

**Vague behavioral requirements**

| Bad | Good |
|-----|------|
| "Handle errors appropriately" | "On malformed input, print `Parse Error: Line {N} invalid format` to STDERR and continue" |

**Implicit ordering**

| Bad | Good |
|-----|------|
| "Output the top 10 results" | "Output top 10 by score (desc), ties by timestamp (earliest), then ID (lexicographic)" |

---

## Behavior vs Structure Reference

| Topic | Structure-Focused (avoid) | Behavior-Focused (preferred) |
|-------|---------------------------|------------------------------|
| Performance | Use a B-tree index | Lookups must complete in O(log n) time |
| Deduplication | Store seen IDs in a set | Duplicate IDs produce only one alert |
| Rule evaluation | Build an expression tree | Evaluate left-to-right with standard precedence |
| History | Maintain a linked list | Support undo/redo for the last N operations |

---

## Next Steps

1. **[See a worked example](example_process.md)** — Walk through designing a calculator problem
2. **[Implement your problem](../problems/tutorial.md)** — Step-by-step tutorial to create your first problem
3. **[Validate before submitting](checklist.md)** — Pre-submission checklist
