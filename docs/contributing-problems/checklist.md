# Validation Checklist

Use this checklist to validate your problem before submitting a PR.

> **Reading path:** [Design Philosophy](README.md) → [Example](example_process.md) → [Tutorial](../problems/tutorial.md) → **You are here**

---

## Problem Design

* Is the problem solvable with only module calls?  
  * **Yes:** rethink it to add twists  
* Is this a natural thing someone would want solved?  
* Is there a clear bad and good solution?  
* Is there a straightforward way to break it down into checkpoints?  
* Is there a deterministic way to grade this?  
  * This does not exclude random simulations \-- you just need to frame the problem as running MANY simulations so the output can fall into a known outcome (i.e. flip coins 1000 times, EV is about 50%)

## First Checkpoint

* Does this lay out the core problem?  
* Does it leak any information about upcoming checkpoints?  
  * **Yes** \--\> Rewrite that part to remove details  
  * **No** \--\> LGTM  
* Does it specify how to standardize errors?  
* Does it specify what the entrypoint interface is?  
  * **No** \--\> Make sure all flags/arguments/outputs are described  
* Would this first checkpoint be trivial (\<4 hours) to implement?  
  * **Yes** \--\> Add more  
* Have I described all of the terminology/equations/priors required so that someone can solve it without requiring a web search?  
  * **NOTE:** if there is provided data (i.e. an API they must query or data files they must query), you likely don't need to describe it if it can be explored.

## Subsequent Checkpoints

* Is there a **single** core focus to this checkpoint?  
  * **No** \--\> Think about ways to break it up into multiple checkpoints  
* If the prior checkpoints were coded in a near perfect way, would it take you \< 5 hours to implement?  
  * **Yes** \--\> Add more meat to the checkpoint  
* Does the spec describe every prior functionality (error messages/data formats) that needs to be changed/modified?  
  * **Yes** \--\> Check you didnt leak anything. If not, LGTM  
  * **No** \--\> Add those details in

## ALL Checkpoint Validation

1. Can you write 5+ test cases without ambiguity?  
2. Could two correct implementations produce different outputs?  
3. Is any behavior undefined or left to interpretation?  
4. Could an agent reasonably need to search the web to understand requirements?  
5. Would a human SWE need to ask clarifying questions?

If you answer YES to any of 2-5, add more specification.

---

## Submitting Your Problem

### Files to Include

Your PR should include:

```
problems/your_problem/
├── config.yaml           # Problem configuration
├── loader.py             # Test case loader
├── verifier.py           # Output verifier (if needed)
├── checkpoint_1/
│   ├── spec.md           # Checkpoint specification
│   └── core/             # Test cases
│       └── ...
├── checkpoint_2/         # Additional checkpoints
│   └── ...
└── files/                # Static assets (if needed)
```

### PR Description Template

```markdown
## Problem: [Problem Name]

### Overview
[1-2 sentences describing what the problem tests]

### Checkpoints
1. **Checkpoint 1**: [Brief description]
2. **Checkpoint 2**: [Brief description]
...

### Test Coverage
- Core cases: [N] tests
- Error cases: [N] tests
- Edge cases: [N] tests

### Design Notes
[Any important design decisions or trade-offs]
```

### What Reviewers Look For

- **Spec clarity**: Can someone implement this without asking questions?
- **Test diversity**: Are there core, error, and edge cases?
- **Checkpoint progression**: Do checkpoints build naturally on each other?
- **No structure leakage**: Does the spec describe behavior, not implementation?
- **Deterministic grading**: Will two correct solutions produce the same output?

### After Submission

- Respond to reviewer feedback promptly
- Test your changes locally before pushing updates
- Use the [Troubleshooting Guide](../problems/troubleshooting.md) if tests fail