# Known Issues

This document tracks current limitations and known issues in SlopCodeBench. We're actively working on improvements and welcome feedback.

> **Note**: This is an initial release. Some rough edges are expected as we iterate toward production-quality software.

---

## Documentation

### Dashboard Documentation Missing
- **Severity**: Medium
- **Issue**: Dashboard functionality is undocumented
- **Impact**: Users cannot use visualization features without reverse-engineering
- **Status**: Documentation in progress
- **Workaround**: See [GitHub Issues](https://github.com/SprocketLab/slop-code-bench/issues) or ask for help
- **Tracking**: [Issue #TBD]

---

## Configuration

### Agent/Model/Provider Configuration Complexity
- **Severity**: Medium
- **Issue**: Models, providers, and agents configuration is complex and not intuitive
- **Impact**: Steep learning curve for new users
- **Status**: Open to redesign suggestions
- **Feedback welcome**: We acknowledge this is hard to use and are open to changes

**Current workarounds:**
- See [Agent Guide](agents/README.md) for detailed setup
- Use provided config files in `configs/` as templates
- Check [FAQ](FAQ.md) for common configurations

---

## Solution Correctness

Due to specification evolution across checkpoints, some reference solutions may not pass all tests. However, **the test cases themselves are verified to be correct**. We prioritized test case accuracy over fixing all reference solutions.

### File Merger
- **Severity**: Medium
- **Checkpoints affected**: 2, 3
- **Issue**: Reference solution doesn't solve all cases
- **Impact**: Tests are correct; solution needs updating
- **Workaround**: Use tests as ground truth

**Details:**
- Checkpoint 2: Current solution incomplete but tests verified
- Checkpoint 3: Same as checkpoint 2

### EVE Market Tools
- **Severity**: Low
- **Checkpoints affected**: 1, 2, 3
- **Issue**: Reference solution fails some cases
- **Impact**: Expected answers verified against actual market data
- **Workaround**: Tests are authoritative

**Details:**
- Checkpoints 1/2: Solution wrong for a few cases, but expected outputs verified with market data
- Checkpoint 3: Exact yields off by 1-2 units in solution, but verifier correctly calculates reprocessing yields

### EVE Industry
- **Severity**: Low
- **Checkpoints affected**: 5
- **Issue**: Incorrect rounding for recursive jobs in reference solution
- **Impact**: Tests are correct
- **Status**: Will be fixed in future release
- **Workaround**: None needed; tests are accurate

### Dynamic Buffer
- **Severity**: Medium
- **Checkpoints affected**: 4
- **Issue**: Reference solution has incorrect code generation for C++/Rust
- **Impact**: Tests are identical across all languages and verified
- **Status**: Will be fixed
- **Workaround**: Use test cases as ground truth

### Execution Server
- **Severity**: Low
- **Checkpoints affected**: 6
- **Issue**: Solution fails some cases
- **Impact**: Cases verified to match specification exactly
- **Workaround**: Tests represent correct behavior per spec

---

## Planned Improvements

The following are planned for future releases:

- [ ] Fix all reference solutions to pass tests
- [ ] Document dashboard functionality
- [ ] Simplify agent/model/provider configuration
- [ ] Add parallel execution support
- [ ] Improve error messages and debugging

---

## Reporting Issues

Found a bug or limitation not listed here?

1. Check [GitHub Issues](https://github.com/SprocketLab/slop-code-bench/issues) to see if it's already reported
2. If not, [open a new issue](https://github.com/SprocketLab/slop-code-bench/issues/new) with:
   - Description of the issue
   - Steps to reproduce
   - Expected vs actual behavior
   - Your environment (OS, Python version, Docker version)
   - Relevant logs or error messages

We appreciate your patience and feedback as we improve SlopCodeBench!
