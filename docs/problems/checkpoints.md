---
version: 1.0
last_updated: 2025-11-06
---

# Checkpoint Design Guide

This guide explains when and how to split problems into multiple checkpoints, with patterns for designing effective milestone progression.

## Table of Contents

- [What is a Checkpoint?](#what-is-a-checkpoint)
- [When to Use Multiple Checkpoints](#when-to-use-multiple-checkpoints)
- [Checkpoint Design Patterns](#checkpoint-design-patterns)
- [Progression Strategies](#progression-strategies)
- [Agent Continuation](#agent-continuation)
- [Common Mistakes](#common-mistakes)
- [Examples from Real Problems](#examples-from-real-problems)

## What is a Checkpoint?

A **checkpoint** is a milestone in problem progression. Each checkpoint has:

- **Specification (`spec.md`)**: What to build at this stage
- **Test cases**: Validation for this milestone
- **Independent evaluation**: Pass/fail determined separately

**Key concept**: Checkpoints are **cumulative** by default—each builds on the previous one. Agent workspace state persists across checkpoints unless the problem is configured otherwise.

## When to Use Multiple Checkpoints

### ✅ Use Multiple Checkpoints When:

#### 1. Features Build on Each Other

**Example: File Backup System**

```
checkpoint_1: Parse schedule, determine due jobs
↓
checkpoint_2: Add actual backup execution
↓
checkpoint_3: Add verification mode
↓
checkpoint_4: Add incremental backups
```

Each checkpoint requires the previous checkpoint's code to work.

#### 2. Problem is Too Complex for One Spec

**Example: EVE Industry Planning**

```
checkpoint_1: Load item database (500 items)
↓
checkpoint_2: Calculate material requirements
↓
checkpoint_3: Add invention mechanics
↓
checkpoint_4: Parse build plans from YAML
↓
checkpoint_5: Optimize material purchasing
```

Five separate milestones, each with distinct requirements.

#### 3. You Want to Track Incremental Progress

**Benefit**: Know where agents get stuck

```
Results:
- checkpoint_1: 95% pass (easy)
- checkpoint_2: 75% pass (medium)
- checkpoint_3: 30% pass (hard)  ← Most agents fail here
- checkpoint_4: 10% pass (very hard)
```

#### 4. Different Skill Areas

**Example: Data Processing Pipeline**

```
checkpoint_1: Data parsing (file I/O)
checkpoint_2: Data transformation (algorithms)
checkpoint_3: Data validation (logic)
checkpoint_4: Data export (formatting)
```

Tests different competencies independently.

### ❌ Don't Use Multiple Checkpoints When:

#### 1. Problem is Simple

**Example: Temperature Converter**

Just one checkpoint:
```
checkpoint_1:
  - Convert Celsius to Fahrenheit
  - Convert Fahrenheit to Celsius
  - Handle invalid inputs
```

No need for progression here.

#### 2. Features Are Independent

**Example: Math Library**

```
# Bad (unnecessary checkpoints):
checkpoint_1: Addition and subtraction
checkpoint_2: Multiplication and division
checkpoint_3: Trigonometry

# Better (one checkpoint with groups):
checkpoint_1:
  core: Basic operations
  functionality: Trigonometry
  errors: Invalid inputs
```

Use groups instead of checkpoints for independent features.

#### 3. No Clear Progression

**Example: REST API**

```
# Bad (arbitrary split):
checkpoint_1: GET and POST
checkpoint_2: PUT and DELETE

# Better (logical split):
checkpoint_1: Basic CRUD
checkpoint_2: Filtering and pagination
checkpoint_3: Authentication
checkpoint_4: Rate limiting
```

Checkpoints should have clear purpose, not arbitrary divisions.

## Checkpoint Design Patterns

### Pattern 1: Linear Progression

Each checkpoint adds functionality to the previous one.

```
checkpoint_1: Core functionality
             ↓
checkpoint_2: + Persistence
             ↓
checkpoint_3: + Error handling
             ↓
checkpoint_4: + Performance optimization
```

**Example: Backup Scheduler**

```
checkpoint_1: Parse YAML, determine due jobs, emit events (simulation)
checkpoint_2: Actually backup files, multiple modes (full/pack/verify)
checkpoint_3: Verify existing backups, checksum validation
checkpoint_4: Incremental backups, track what changed
```

**Use when**:
- Features logically build on each other
- Later checkpoints need earlier code
- Natural progression from simple to complex

**Benefits**:
- Clear learning path for agents
- Easy to measure progress
- Natural complexity ramp

### Pattern 2: Parallel Features

Each checkpoint adds independent features.

```
checkpoint_1: Feature A
checkpoint_2: Feature B (independent of A)
checkpoint_3: Feature C (independent of A and B)
checkpoint_4: Combine A + B + C
```

**Example: Code Search Tool**

```
checkpoint_1: Search by function name (AST parsing)
checkpoint_2: Search by regex (text matching)
checkpoint_3: Search by imports (module analysis)
checkpoint_4: Combined queries (all features together)
```

**Use when**:
- Features are independent subsystems
- Final checkpoint integrates everything
- Testing each feature separately helps debugging

**Benefits**:
- Clear feature boundaries
- Parallel development possible
- Easy to identify which feature is broken

### Pattern 3: Expanding Scope

Each checkpoint handles more cases of the same problem.

```
checkpoint_1: Subset A (simple)
             ↓
checkpoint_2: Subset A + B (medium)
             ↓
checkpoint_3: Subset A + B + C (complex)
             ↓
checkpoint_4: Full problem (all cases)
```

**Example: Config Resolver**

```
checkpoint_1: Flat configs (no nesting, no includes)
checkpoint_2: + Nested configs (objects in objects)
checkpoint_3: + Includes (import other configs)
checkpoint_4: + Conflict resolution (deep merge, type checking)
```

**Use when**:
- Problem has natural subsets
- Complexity increases gradually
- Want to test partial solutions

**Benefits**:
- Incremental difficulty
- Early checkpoints are achievable
- Clear scope boundaries

### Pattern 4: Different Modes

Each checkpoint is a different mode of operation.

```
checkpoint_1: Mode 1 (read-only)
checkpoint_2: Mode 2 (read-write)
checkpoint_3: Mode 3 (batch processing)
checkpoint_4: Mode 4 (streaming)
```

**Example: Log Analyzer**

```
checkpoint_1: Parse logs (read)
checkpoint_2: Filter logs (read + query)
checkpoint_3: Transform logs (read + write)
checkpoint_4: Aggregate logs (read + compute + write)
```

**Use when**:
- Tool has distinct operational modes
- Each mode has unique requirements
- Modes share common infrastructure

**Benefits**:
- Tests different use cases
- Covers various workflows
- Realistic usage scenarios

### Pattern 5: Increasing Constraints

Each checkpoint adds constraints or requirements.

```
checkpoint_1: Correct output (any method)
             ↓
checkpoint_2: + Time constraints (< 5s)
             ↓
checkpoint_3: + Memory constraints (< 100MB)
             ↓
checkpoint_4: + Code quality (< 500 lines)
```

**Example: Optimization Problem**

```
checkpoint_1: Find a valid solution
checkpoint_2: Find a solution in < 10 seconds
checkpoint_3: Find an optimal solution
checkpoint_4: Find optimal solution with < 1GB memory
```

**Use when**:
- Testing optimization algorithms
- Performance matters
- Want to reward better solutions

**Benefits**:
- Rewards efficiency
- Tests algorithm quality
- Realistic production constraints

## Progression Strategies

### Strategy 1: Foundation → Extension

**Build a solid foundation, then extend it.**

```
checkpoint_1: Core data structures and basic operations
  - Define data models
  - Basic CRUD operations
  - Simple validation

checkpoint_2: Advanced operations on foundation
  - Complex queries
  - Bulk operations
  - Transactions

checkpoint_3: External integrations
  - API endpoints
  - File import/export
  - External services

checkpoint_4: Production features
  - Error handling
  - Logging
  - Performance
```

**Pros**: Strong foundation ensures later work is solid

**Cons**: Early checkpoints may be tedious

### Strategy 2: Happy Path → Edge Cases

**Start with ideal scenarios, add complexity.**

```
checkpoint_1: Happy path only
  - Valid inputs
  - No errors
  - Simple cases

checkpoint_2: + Input validation
  - Invalid types
  - Missing fields
  - Bad formats

checkpoint_3: + Error handling
  - Network failures
  - Timeouts
  - Partial failures

checkpoint_4: + Edge cases
  - Boundary values
  - Concurrent access
  - Race conditions
```

**Pros**: Quick wins early, builds confidence

**Cons**: May require refactoring for error handling

### Strategy 3: Vertical Slices

**Build complete features end-to-end.**

```
checkpoint_1: Feature A (complete)
  - Data model
  - API endpoints
  - Validation
  - Tests

checkpoint_2: Feature B (complete)
  - Data model
  - API endpoints
  - Validation
  - Tests

checkpoint_3: Feature C (complete)
  - Data model
  - API endpoints
  - Validation
  - Tests

checkpoint_4: Integration
  - Features A + B + C working together
```

**Pros**: Each checkpoint is a complete, usable feature

**Cons**: More complex early checkpoints

### Strategy 4: Breadth → Depth

**Cover basics first, then add sophistication.**

```
checkpoint_1: All features (basic)
  - User management (basic)
  - Data storage (basic)
  - API (basic)

checkpoint_2: All features (intermediate)
  - User management (with roles)
  - Data storage (with indexing)
  - API (with auth)

checkpoint_3: All features (advanced)
  - User management (with SSO)
  - Data storage (with replication)
  - API (with rate limiting)
```

**Pros**: Early checkpoint covers everything at basic level

**Cons**: More to implement per checkpoint

## Agent Continuation

### How Checkpoints Work with Agent State

**Default behavior (cumulative)**:

```
Agent State:
  checkpoint_1: Agent writes code
                └─ Code saved to workspace

  checkpoint_2: Agent continues in same workspace
                ├─ Previous code still there
                └─ Agent extends it

  checkpoint_3: Agent continues again
                ├─ All previous code still there
                └─ Agent adds more
```

This cumulative behavior is the standard approach for most problems. Agents build upon their previous work, extending functionality across checkpoints.

### Workspace Isolation Within Checkpoints

While checkpoints are cumulative (workspace persists), you can control **test case isolation** within each checkpoint using the `isolated` field on groups:

```yaml
groups:
  core:
    type: Core
    isolated: true   # Each test case starts with clean workspace state
```

When `isolated: true` (the default), each test case within a group starts with a fresh workspace. This prevents state pollution between tests while still allowing code to accumulate across checkpoints.

### Spec Design for Continuation

**Checkpoint 1 spec:**
```markdown
# Checkpoint 1: Basic Parsing

Build a CLI tool that parses YAML schedules.

## Deliverables

Create `backup_scheduler.py` with:
- YAML parsing
- Schedule validation
- Event emission
```

**Checkpoint 2 spec (continuation):**
```markdown
# Checkpoint 2: File Backup

Extend checkpoint_1 to actually backup files.

## Deliverables

Extend your existing `backup_scheduler.py` to:
- Read files from mount point
- Apply exclusion rules
- Write backup archives

**Note**: Your code from checkpoint 1 should still work.
```

**Key phrase**: "Extend your existing..." makes continuation explicit.

## Common Mistakes

### ❌ Mistake 1: Too Many Checkpoints

**Bad:**
```
checkpoint_1: Parse YAML
checkpoint_2: Validate schema
checkpoint_3: Determine due jobs
checkpoint_4: Apply exclusions
checkpoint_5: Emit events
checkpoint_6: Handle errors
```

**Why bad**: 6 checkpoints for one feature is excessive. Too granular.

**Fix:**
```
checkpoint_1: Parse, validate, and determine due jobs
  - All parsing logic together

checkpoint_2: Apply exclusions and emit events
  - All output logic together
```

**Rule of thumb**: 3-5 checkpoints is ideal, rarely more than 6.

### ❌ Mistake 2: Uneven Difficulty

**Bad:**
```
checkpoint_1: Hello World (1 hour)
checkpoint_2: Basic CRUD (2 hours)
checkpoint_3: Implement distributed consensus algorithm (40 hours)
checkpoint_4: Add logging (30 minutes)
```

**Why bad**: Checkpoint 3 is way harder than others.

**Fix**: Balance difficulty across checkpoints.

```
checkpoint_1: Basic CRUD (2 hours)
checkpoint_2: Add replication (3 hours)
checkpoint_3: Add consensus (leader election) (4 hours)
checkpoint_4: Add consensus (log agreement) (4 hours)
checkpoint_5: Add monitoring and recovery (3 hours)
```

### ❌ Mistake 3: Unclear Dependencies

**Bad:**
```
checkpoint_1 spec: "Build a parser"
checkpoint_2 spec: "Add execution"
  - Depends on checkpoint_1, but spec doesn't say so
```

**Why bad**: Agent might rewrite everything, breaking checkpoint_1 tests.

**Fix:**
```
checkpoint_2 spec: "Extend your parser from checkpoint_1 to add execution."
```

**Always explicitly state** when extending previous checkpoint.

### ❌ Mistake 4: Backwards Incompatibility

**Bad:**
```
checkpoint_1: CLI arguments: --input <file>
checkpoint_2: CLI arguments: --file <file> (breaks checkpoint_1!)
```

**Why bad**: Checkpoint_1 tests will fail after checkpoint_2.

**Fix**: Keep backwards compatibility, or add flags:
```
checkpoint_2: CLI arguments: --input <file> OR --file <file>
```

### ❌ Mistake 5: No Clear Theme

**Bad:**
```
checkpoint_1: User authentication
checkpoint_2: Data export to CSV
checkpoint_3: Email notifications
checkpoint_4: User permissions
```

**Why bad**: Seems random, no clear progression.

**Fix**: Group related features:
```
checkpoint_1: User authentication
checkpoint_2: User permissions (builds on auth)
checkpoint_3: Data management (CRUD)
checkpoint_4: Data export (builds on data management)
```

## Examples from Real Problems

### Example 1: `file_backup` (Linear Progression)

```
checkpoint_1: Parse YAML schedule, determine due jobs, emit JSONL events
  - 13 test cases
  - Focus: Parsing and scheduling logic
  - Time: ~2 hours

checkpoint_2: Actually backup files (full/pack/verify modes)
  - 3 test cases
  - Focus: File operations
  - Time: ~2 hours

checkpoint_3: Verify existing backups
  - 4 test cases
  - Focus: Checksum validation
  - Time: ~1 hour

checkpoint_4: Incremental backups
  - 4 test cases
  - Focus: State tracking
  - Time: ~2 hours
```

**Pattern**: Each checkpoint adds a major feature.

**Progression**: Simulation → Execution → Verification → Optimization

### Example 2: `eve_industry` (Expanding Scope)

```
checkpoint_1: Load item database, lookup recipes
  - 6 test cases
  - Focus: Data loading
  - Time: ~3 hours

checkpoint_2: Calculate material requirements recursively
  - 6 test cases
  - Focus: Tree traversal
  - Time: ~3 hours

checkpoint_3: Add invention mechanics
  - 6 test cases
  - Focus: Probability calculations
  - Time: ~4 hours

checkpoint_4: Parse build plans from YAML
  - 4 test cases
  - Focus: Complex input parsing
  - Time: ~3 hours

checkpoint_5: Optimize material purchasing
  - 3 test cases (+ hidden)
  - Focus: Optimization
  - Time: ~4 hours
```

**Pattern**: Each checkpoint adds complexity to the same domain.

**Progression**: Load → Calculate → Extend → Plan → Optimize

### Example 3: `dynamic_config_service_api` (Layered Complexity)

```
checkpoint_1: Basic CRUD, versioning, scoping
  - 42 test cases
  - Focus: Core API
  - Time: ~8 hours

checkpoint_2: Include resolution, deep merge
  - Additional cases
  - Focus: Config inheritance
  - Time: ~4 hours

checkpoint_3: Conflict detection, cycle prevention
  - Additional cases
  - Focus: Advanced validation
  - Time: ~4 hours

checkpoint_4: Performance, rate limiting, scaling
  - Additional cases
  - Focus: Production features
  - Time: ~4 hours
```

**Pattern**: Foundation → Extensions → Safety → Production

## Checkpoint Planning Worksheet

Use this to design your checkpoints:

```
Problem Name: _________________

Total Complexity: _____ hours (estimated)

Number of Checkpoints: _____ (aim for 3-5)

Checkpoint 1:
  - Theme: ___________________
  - Features: [list]
  - Dependencies: None
  - Time: _____ hours
  - Test cases: _____ cases

Checkpoint 2:
  - Theme: ___________________
  - Features: [list]
  - Dependencies: checkpoint_1 (or None)
  - Time: _____ hours
  - Test cases: _____ cases

[... repeat for each checkpoint ...]

Progression Pattern: [Linear | Parallel | Expanding | Modes | Constraints]

Continuation: [Cumulative | Reset]

Rationale: Why these divisions?
```

## Summary

**Key principles:**

1. **Use 3-5 checkpoints** for most problems
2. **Clear progression** with logical milestones
3. **Balanced difficulty** across checkpoints
4. **Explicit dependencies** in specs
5. **Backwards compatible** unless reset

**Common patterns:**

- Linear Progression (build on previous)
- Parallel Features (independent features)
- Expanding Scope (handle more cases)
- Different Modes (various workflows)
- Increasing Constraints (optimization)

**Avoid:**

- Too many checkpoints (over-granular)
- Uneven difficulty (one too hard)
- Unclear dependencies (implicit continuation)
- Breaking changes (backwards incompatibility)
- Random divisions (no clear theme)

**Planning checklist:**

- [ ] Checkpoints have clear themes
- [ ] Progression makes sense
- [ ] Difficulty is balanced
- [ ] Dependencies are explicit
- [ ] Each checkpoint is testable independently
- [ ] Total adds up to complete problem

## Next Steps

- **[Test Cases Guide](test-cases.md)** - Write tests for each checkpoint
- **[Groups Guide](groups.md)** - Organize tests within checkpoints
- **[Problem Structure](structure.md)** - See checkpoint structure
- **[Examples](examples/)** - Study real checkpoint progressions
