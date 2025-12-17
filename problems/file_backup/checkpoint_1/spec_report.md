# Checkpoint 1 Specification Review Report

## Checkpoint Summary
Establishes baseline backup scheduler functionality: YAML parsing, job scheduling (daily/weekly/once), file exclusion patterns, and JSON Lines event output.

## Critical Missing Information

### Error Handling Requirements
The specification lacks any mention of error handling, which is heavily tested:
- Exit codes for different error types
- Error message formats
- Schema validation requirements
- Which errors go to stderr vs stdout

**Recommended action:** CLARIFY

**Rationale:** Without error handling specifications, implementations cannot pass error tests. Add minimal requirements for deterministic grading.

### Weekly Job Multiple Triggers
The specification is ambiguous about whether weekly jobs trigger multiple times within the duration window.

**Recommended action:** CLARIFY

**Rationale:** Tests expect weekly jobs to trigger on every matching day within the duration window, but the spec could be interpreted as triggering only once.

### Non-UTC Timezone Format
The specification doesn't clarify that `now_local` should include numeric timezone offset for non-UTC timezones.

**Recommended action:** MOVE-TO-EXAMPLE

**Rationale:** Add an example with a non-UTC timezone showing the offset format (e.g., `-04:00`).

## Solution Leaks

## Lines 65-74: Solution Leak
> For each due job:
> 1. Emit a `JOB_STARTED` event.
> 2. For every file in the source directory tree:
>    - If excluded → emit a `FILE_EXCLUDED` event.
>    - Otherwise → emit a `FILE_SELECTED` event.
> 3. Emit a `JOB_COMPLETED` event with counts.

**Recommended action:** CONDENSE

**Rationale:** This prescribes the exact algorithm. Replace with outcome: "For each due job, emit events documenting which files are selected vs excluded based on patterns."

## Lines 93-96: Solution Leak
> - Sort due jobs by `id` ascending before execution.
> - For each job, process files in the source directory tree in lexicographic order by full relative path.
> - For `FILE_EXCLUDED`, the `pattern` is the **first** pattern (list order) that matches.

**Recommended action:** CONDENSE

**Rationale:** Over-prescriptive implementation details. Keep only: "Jobs execute in ascending ID order. Files are processed in lexicographic path order. First matching exclusion pattern wins."

## Bias Phrases

## Line 94: Bias Phrase
> process files in the source directory tree

**Recommended action:** REMOVE

**Rationale:** "directory tree" suggests tree traversal implementation. Replace with "process files in the source directory."

## Line 59: Bias Phrase
> Pattern syntax: glob with `*`, `?`, `**`, and character classes `[]`

**Recommended action:** CONDENSE

**Rationale:** Mentioning "glob" biases toward glob library usage. Just specify the pattern syntax without naming it.

## Over-Specification

## Lines 100-108: Over-Spec
> All JSON events must be emitted in compact format:
> - No spaces after colons or commas
> - No trailing commas
> - One event per line, newline-terminated
>
> Field ordering shown in examples is for readability only...

**Recommended action:** REMOVE

**Rationale:** Examples already demonstrate JSON Lines format. This prose adds no value.

## Lines 109-118: Over-Spec
> ### Event Schema Reference
>
> | Event | Required Fields | Notes |
> |-------|----------------|-------|
> | `SCHEDULE_PARSED` | `event`, `timezone`, `jobs_total` | Always first event |
> ...

**Recommended action:** REMOVE

**Rationale:** The table duplicates information clearly shown in examples. Let examples define the schema.

## Lines 45-51: Over-Spec
> Given `--now` and `--duration`, determine which jobs are _due_:
>
> - Jobs are evaluated using the schedule's `timezone`.
> - All timestamps are floored to the minute (seconds/microseconds ignored).
> - A job is **due** if its trigger time falls within the window...

**Recommended action:** CONDENSE

**Rationale:** Much of this repeats what examples show. Keep only essential rules not evident from examples.

## Ambiguities

## Line 27: Ambiguity
> when kind=once needs to be an ISO timestamp without timezone, interpreted in schedule's timezone

**Recommended action:** CLARIFY

**Rationale:** "ISO timestamp" is ambiguous. Specify exact format: "YYYY-MM-DDTHH:MM:SS with no timezone suffix."

## Line 49: Ambiguity
> `weekly`: triggers at the specified `at` time on the specified `days`

**Recommended action:** CLARIFY

**Rationale:** Unclear if this means "every occurrence" or "first occurrence" within duration window.

## Line 83: Ambiguity
> `now_local` is ISO 8601 with timezone: `Z` or `±HH:MM`

**Recommended action:** MOVE-TO-EXAMPLE

**Rationale:** All examples show only `Z`. Add example with numeric offset to demonstrate non-UTC behavior.

## Example Coverage Analysis

### What Examples Demonstrate Well
- Relative paths based on job source
- Exclusion pattern matching
- Job sorting by ID
- Basic daily job scheduling

### Missing Example Coverage
1. **Weekly job with multiple triggers** - Critical for understanding weekly behavior in duration windows
2. **Non-UTC timezone** - Shows numeric offset format for `now_local`
3. **Once job** - Demonstrates timestamp format without timezone
4. **Empty exclude array** - Valid edge case
5. **Complex glob patterns** - `?` and `[]` character class usage

**Recommendation:** Add a third example demonstrating weekly jobs with multiple days triggering across a 72-hour duration, using a non-UTC timezone. This would clarify the most ambiguous behaviors.

## Overall Assessment

This checkpoint spec is **moderately over-specified** with several solution leaks that reduce reasoning requirements:

1. **Algorithm prescription** (lines 65-74) removes design decisions
2. **Implementation details** (processing order, first pattern matching) should be outcomes, not methods
3. **Missing critical information** (error handling, timezone details) will cause implementation failures
4. **Redundant prose** explaining what examples already show

The spec would benefit from:
- Removing step-by-step algorithm descriptions
- Adding error handling requirements
- Including more diverse examples
- Condensing redundant prose explanations
- Clarifying ambiguous scheduling semantics

The goal should be a spec that clearly defines **what** must happen without prescribing **how** to implement it.