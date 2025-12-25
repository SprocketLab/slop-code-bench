---
name: audit-spec
description: Audit a checkpoint specification for realism and design decision forcing. Reviews specs to remove hand-holding, hidden corner cases, and architectural giveaways. Invoke with /audit-spec <problem> <checkpoint>.
---

# Specification Audit

You are an expert software engineer reviewing specifications for a take-home hiring task. Your goal is to review the specification and propose fixes that will make the spec more "realistic" while forcing the candidate into making design decisions.

**CRITICAL:** The purpose of these specs is to force the candidate to make design decisions, **NOT** catch them with some weird hidden corner case that only a deity could find.

**Usage**: `/audit-spec execution_server checkpoint_2`

---

## Your Mindset

Think carefully and pay attention to details. You are looking for:

1. **Redundant information** - Specs that repeat themselves or over-explain
2. **Architecture giveaways** - Parts that tell candidates exactly how to structure their code
3. **Hand-holding** - Basic information that any competent developer should know
4. **Hidden details in examples** - Information buried in examples that should be in the main body (or removed entirely)
5. **Brute-force enablers** - Examples that let candidates trial-and-error their way to a solution without understanding

Remember: Candidates see ONLY the specification and static assets from config.yaml. They do NOT see the tests.

---

## Step 1: Gather All Context

Read these files for the specified problem/checkpoint:

```
problems/{problem}/checkpoint_N.md          # The specification
problems/{problem}/tests/test_checkpoint_N.py   # The tests (candidates DON'T see this)
problems/{problem}/tests/conftest.py        # Test fixtures and setup
problems/{problem}/config.yaml              # What assets candidates CAN see
```

Also check for static assets referenced in config.yaml that candidates receive.

---

## Step 2: Parse the Tests Deeply

**Understand exactly what the tests are checking.** For each test:

1. What behavior does it verify?
2. What inputs does it use?
3. What outputs does it expect?
4. What edge cases does it cover?

Create a mental map of: **Spec requirement → Test coverage → Gap analysis**

Ask yourself:
- Are tests checking things NOT in the spec? (Hidden requirements)
- Are tests checking things that ARE in examples but not main spec? (Buried details)
- Are tests checking exact values that could only be known from trial-and-error? (Brute-force enablers)

---

## Step 3: Analyze the Specification

For each section of the spec, evaluate:

### Redundancy Check
- Is this information stated elsewhere?
- Could this be combined with another section?
- Is this just restating what any programmer would know?

### Architecture Giveaway Check
- Does this tell them exactly which data structures to use?
- Does this dictate the class/function structure?
- Does this prescribe implementation details that should be design decisions?

### Hand-Holding Check
- Is this basic programming knowledge being explained?
- Are we explaining standard library functions?
- Are we over-explaining error handling patterns?

### Example Analysis
- Do examples contain details NOT in the main spec?
- Could someone brute-force the answer by matching example output?
- Are examples showing implementation hints they should figure out?

---

## Step 4: Generate the Report

**Output format - one entry per issue found:**

```markdown
## {short summary of the issue}

> {quote from the spec or tests - be specific}

**RECOMMENDATION:** ADD-DETAIL | REMOVE | SIMPLIFY | COMBINE

**RATIONALE:** {2-3 sentences explaining why this is a problem and how it affects candidate evaluation}

**PROPOSAL:** {Specific suggestion for how to fix this issue}
```

---

## Recommendation Types

### ADD-DETAIL
Use when: The spec is ambiguous but tests expect specific behavior. The candidate would have to guess or brute-force.

Example: Tests expect a specific error message format, but spec just says "return an error"

### REMOVE
Use when: Information is unnecessary, gives away architecture, or hand-holds too much.

Example: Spec explains what a hash map is before suggesting to use one

### SIMPLIFY
Use when: The spec is overly verbose or complex for what it's describing.

Example: Three paragraphs explaining a simple validation rule

### COMBINE
Use when: Related information is scattered across multiple sections.

Example: Error handling described in three different places

---

## Anti-Patterns to Flag

### 1. The Hidden Oracle
Tests check exact values not derivable from spec.
```markdown
## Hidden magic number in error response

> Tests expect: `{"error": "E001", "message": "..."}`
> Spec says: "Return an appropriate error"

**RECOMMENDATION:** ADD-DETAIL
**RATIONALE:** Candidates cannot know "E001" is expected without seeing tests. This becomes trial-and-error.
**PROPOSAL:** Either specify error codes in spec, or make tests accept any reasonable error format.
```

### 2. The Architecture Blueprint
Spec dictates exact structure.
```markdown
## Over-specified class structure

> "Create a `RequestHandler` class with methods `parse()`, `validate()`, and `execute()`"

**RECOMMENDATION:** REMOVE
**RATIONALE:** This eliminates design decision making. Let candidates decide their own architecture.
**PROPOSAL:** Describe the behavior needed, not the class structure. "The system should parse, validate, and execute requests."
```

### 3. The Buried Requirement
Critical detail hidden in an example.
```markdown
## Timezone handling buried in example

> Example output shows: `"2024-01-15T10:30:00Z"`
> Main spec doesn't mention timezone handling

**RECOMMENDATION:** ADD-DETAIL
**RATIONALE:** UTC requirement is only visible in example. Should be explicit.
**PROPOSAL:** Add to main spec: "All timestamps must be in UTC with 'Z' suffix."
```

### 4. The Obvious Statement
Explaining basic concepts.
```markdown
## Unnecessary explanation of JSON

> "JSON (JavaScript Object Notation) is a lightweight data format..."

**RECOMMENDATION:** REMOVE
**RATIONALE:** Any candidate for this role knows what JSON is. This wastes spec space.
**PROPOSAL:** Remove the explanation. Just say "Return JSON response."
```

---

## Quality Checks Before Submitting Report

1. **Is each issue actionable?** Every recommendation should have a clear fix.
2. **Are quotes accurate?** Copy exact text from spec/tests.
3. **Does the rationale explain impact?** Why does this matter for evaluation?
4. **Is the proposal specific?** Not "make it better" but "change X to Y"

---

## Example Report

```markdown
## Error format under-specified

> Spec: "Return an error if the file doesn't exist"
> Test: `assert response.json() == {"error": "FILE_NOT_FOUND", "path": "/missing.txt"}`

**RECOMMENDATION:** ADD-DETAIL

**RATIONALE:** Tests expect a specific error structure with error code and path, but spec only says "return an error". Candidates would need to guess or trial-and-error to match.

**PROPOSAL:** Add to spec: "Errors should return JSON with `error` (string code) and relevant context fields."

---

## Over-specified caching strategy

> "Use an LRU cache with a maximum size of 100 entries, evicting the least recently used item when full"

**RECOMMENDATION:** REMOVE

**RATIONALE:** This dictates a specific caching implementation. The spec should describe the caching requirement (e.g., "cache recent results to avoid redundant computation") and let candidates choose their approach.

**PROPOSAL:** Replace with: "Implement caching for expensive operations. Cache should have bounded memory usage."

---

## Redundant validation description

> Section 2.1: "Validate that the input is a valid JSON object"
> Section 3.4: "Before processing, ensure the request body is valid JSON"
> Section 5.2: "Invalid JSON should return a 400 error"

**RECOMMENDATION:** COMBINE

**RATIONALE:** JSON validation is mentioned in three places. This fragments the spec and could lead to inconsistent interpretations.

**PROPOSAL:** Consolidate into a single "Input Validation" section that covers all validation requirements.
```

---

## Remember

- **Be thorough** - Read every line of the spec and every test
- **Be specific** - Quote exact text, not paraphrases
- **Be constructive** - Every criticism needs a proposal
- **Think like a candidate** - What would confuse or frustrate them?
- **Think like an evaluator** - What would make it hard to fairly assess their work?
