# Checkpoint 4 Gap Analysis

## Summary

This checkpoint extends the migration tool with file relocation capabilities including path-based renaming (`path_rename`), content-based renaming (`content_rename`), and bulk file moves (`relocate_files`).

**Total behaviors tested:** 20
**True gaps found:** 0 (previously 1, now fixed)
**Not gaps (inferrable):** 19
**Over-specified (handled in over-spec rubric):** 1

---

## Test Behaviors Analysis

### Inheritance Reference Update When Referencing File Moves

**What tests expect:**
When a file containing an `extends:` directive moves to a different directory, the inheritance reference path must be recalculated to maintain the correct relative path to the referenced file. In `multiphase_inheritance_move`: app.yaml (with `extends: base.yaml`) moves to `deploy/production.yaml`, and the extends must update to `extends: ../base.yaml`.

**In spec examples?**
Yes - Example 9 demonstrates this exact behavior with explicit note: "The inheritance reference is updated from `extends: base.yaml` to `extends: ../base.yaml` after the file moves to `deploy/` subdirectory."

**In spec prose?**
No - The Inheritance Reference Updates section only states: "When a file referenced in an inheritance directive is moved by a file relocation rule, all references to that file must be updated."

This describes when the REFERENCED file (e.g., base.yaml) moves, not when the REFERENCING file (e.g., app.yaml) moves.

**Can agent infer this?**

*Standard practice?* Somewhat - maintaining valid relative paths when moving files is a reasonable expectation, but the specific behavior isn't universal.

*Pattern in examples?* Yes - Example 9 clearly demonstrates this scenario.

*Clear from context?* Partially - An agent carefully reading Example 9 would understand, but an agent focusing on prose might miss this case since the prose describes a different scenario.

*Could implementations reasonably differ?* Yes - An agent reading only the prose could reasonably implement only the "referenced file moves" case without implementing the "referencing file moves" case.

**Verdict:** TRUE GAP

**Fix:** CLARIFY

**Current text (Inheritance Reference Updates section, line 97-104):**
> When a file referenced in an inheritance directive is moved by a file relocation rule, all references to that file must be updated.

**Ambiguity:**
The prose only describes one scenario (referenced file moves) but Example 9 demonstrates a different scenario (referencing file moves). Both require inheritance reference updates, but for different reasons.

**Replace with:**
> When file relocation affects inheritance references, paths must be updated to maintain correct relative relationships. This happens in two cases:
> 1. When a file referenced in an inheritance directive moves - all files referencing it must update their `extends:` path
> 2. When a file containing an inheritance directive moves - its `extends:` path must be recalculated relative to its new location

**Why this is needed:**
The current prose and Example 9 describe different scenarios. An agent focusing on prose might implement only case 1 (referenced file moves) and fail the `multiphase_inheritance_move` test which validates case 2 (referencing file moves).

---

### Files Relocated in Lexicographic Order by Source Path

**What tests expect:**
When a single rule matches multiple files, `file_relocated` events are emitted in lexicographic order by source path. Example: `environments/production/app.yaml` before `environments/staging/app.yaml`.

**In spec examples?**
Yes - Example 1 shows `services/api/config.yaml` before `services/worker/config.yaml`. Example 3 shows `environments/production/app.yaml`, `environments/production/db.yaml`, `environments/staging/app.yaml`, `environments/staging/db.yaml` in alphabetical order.

**In spec prose?**
No explicit statement about event ordering within a single rule.

**Can agent infer this?**

*Standard practice?* Alphabetical ordering is common but not universal.

*Pattern in examples?* Yes - All examples consistently show alphabetical ordering.

*Clear from context?* Yes - The pattern is obvious across multiple examples.

*Could implementations reasonably differ?* Without examples, yes. With examples, agents should match the pattern.

**Verdict:** NOT A GAP

**Reasoning:**
The examples clearly demonstrate alphabetical ordering. Additionally, the verifier sorts events before comparison (using `(file, event, rules_applied)` key), so event order doesn't actually affect test pass/fail as long as the correct events are emitted.

---

### Multi-Phase Execution Order

**What tests expect:**
Three distinct phases execute in order: (1) Inheritance resolution, (2) Content transformation, (3) File relocation. Events from each phase complete before the next phase begins.

**In spec examples?**
Yes - Examples 4 and 9 demonstrate the ordering explicitly.

**In spec prose?**
Yes - Line 85-94 explicitly states:
> 1. **Inheritance Resolution** (if `--inheritance` flag provided)
> 2. **Content Transformation Rules** (checkpoints 1-3 rules)
> 3. **File Relocation Rules** (checkpoint 4 rules with `scope: "file"`)
> Within each phase, rules apply in lexicographic order by rule name.

**Verdict:** NOT A GAP

---

### Pre-Relocation Path in file_updated Events

**What tests expect:**
The `file_updated` event from content transformation uses the file's path BEFORE any relocation occurs.

**In spec examples?**
Yes - Example 4 explicitly shows `{"event": "file_updated", "file": "temp/app.yaml", ...}` followed by relocation from `temp/app.yaml` to `configs/app.yaml`.

**In spec prose?**
Yes - Example 4 includes explicit note: "Note: The `file_updated` event uses the file's path **before** relocation."

**Verdict:** NOT A GAP (OVER-SPEC - both prose and example cover this)

---

### Atomic Collision Detection

**What tests expect:**
All destination paths are validated for collisions BEFORE any files are moved. If any collision is detected, no files are modified.

**In spec examples?**
Yes - Example 7 shows collision error occurring before any moves complete.

**In spec prose?**
Yes - Requirements section (line 580) explicitly states: "Check for all destination collisions before moving any files (atomic validation)"

**Verdict:** NOT A GAP

---

### Destination Collision Error Message Format

**What tests expect:**
Error message format: `Error: destination already exists: <path>`

**In spec examples?**
Yes - Example 7 shows: `Error: destination already exists: deployments/staging.yaml`

**In spec prose?**
Yes - Error Handling section shows: `Error: destination already exists: configs/api.yaml`

**Verdict:** NOT A GAP

---

### Invalid Pattern Error Message Format

**What tests expect:**
Error message format: `Error: invalid file pattern in rule '<rule_name>': <pattern>`

**In spec examples?**
No standalone example, but Error Handling section shows the format.

**In spec prose?**
Yes - Error Handling section shows: `Error: invalid file pattern in rule 'rename_services': *.{yaml`

**Verdict:** NOT A GAP

---

### Silent Skip for Missing Variables in content_rename

**What tests expect:**
When a file matches `file_pattern` but variable extraction fails (key doesn't exist in file content), the file is silently skipped with no event emitted and no error.

**In spec examples?**
No example shows this case.

**In spec prose?**
Yes - Line 57: "Skips file if any variable key is missing"

**Can agent infer this?**

*Standard practice?* Somewhat - "skip" typically implies silent non-processing.

*Clear from context?* Yes - "skips" is unambiguous.

**Verdict:** NOT A GAP

**Reasoning:**
The behavior is explicitly stated in prose. "Skips" clearly means silent non-processing rather than error.

---

### Directory Creation for Destinations

**What tests expect:**
Destination directories are automatically created as needed when files are relocated.

**In spec examples?**
Yes - Multiple examples show files moving to new directories that didn't exist.

**In spec prose?**
Yes - Each rule type behavior section states: "Creates destination directories as needed"

**Verdict:** NOT A GAP

---

### File Content Preservation During Move

**What tests expect:**
File contents and format are preserved exactly during relocation (no transformation applied during move phase).

**In spec examples?**
Yes - Examples show files with identical content at new locations.

**In spec prose?**
Yes - path_rename behavior states: "Preserves file format and content during move"

**Verdict:** NOT A GAP

---

### content_rename new_path Relative to Current Directory

**What tests expect:**
The `new_path` in `content_rename` is interpreted relative to the file's current directory, not the workspace root.

**In spec examples?**
Yes - Example 2 shows `services/api/config.yaml` with `new_path: "${svc}.yaml"` becoming `services/api/api-gateway.yaml`. Example 8 shows `services/app.yaml` becoming `services/us-west-2/api.yaml`.

**In spec prose?**
Yes - Line 58: "`new_path` is relative to the file's current directory"

**Verdict:** NOT A GAP

---

### Pattern Syntax Distinctions

**What tests expect:**
- `path_pattern` (path_rename): Uses `$variable` capture syntax from checkpoint 2
- `file_pattern` (content_rename): Uses glob patterns (`*`, `**`)
- `source_pattern` (relocate_files): Uses `$variable` capture syntax

**In spec examples?**
Yes - Each example demonstrates the appropriate syntax for its rule type.

**In spec prose?**
Yes - Requirements section (lines 583-584):
> - Glob patterns in `file_pattern` support `*` (single path component) and `**` (recursive)
> - Path patterns in `path_pattern` use checkpoint 2 syntax (`$variable`, `*`)

**Verdict:** NOT A GAP

---

### scope: "file" Required for File Relocation Rules

**What tests expect:**
Rules must have `"scope": "file"` to be treated as file relocation rules. Rules without this field are treated as content transformation rules.

**In spec examples?**
Yes - All file relocation examples include `"scope": "file"`.

**In spec prose?**
Yes - Line 7: "File relocation rules have a special `scope` field set to `"file"`"
Requirements section (lines 577-578):
> - File relocation rules must have `scope: "file"` field
> - Rules without `scope` field default to content transformation rules

**Verdict:** NOT A GAP

---

### Inheritance Reference Update Event Format

**What tests expect:**
Inheritance reference updates emit: `{"event": "file_updated", "file": "<path>", "rules_applied": [], "reason": "inheritance_reference_update"}`

**In spec examples?**
Yes - Examples 5 and 9 show this exact format.

**In spec prose?**
Yes - Output Format section (lines 120-124):
```jsonl
{"event": "file_updated", "file": "app.yaml", "rules_applied": [], "reason": "inheritance_reference_update"}
```

**Verdict:** NOT A GAP

---

### Multiple Variables in content_rename

**What tests expect:**
Multiple variables can be extracted from file content and combined in `new_path`.

**In spec examples?**
Yes - Examples 6 and 8 demonstrate multi-variable extraction and substitution.

**In spec prose?**
Yes - Example specifications show `"variables": {"svc": "...", "env": "..."}` and `new_path: "${svc}.${env}.yaml"`

**Verdict:** NOT A GAP

---

### Relative Path Calculation for Deep Directory Nesting

**What tests expect:**
Inheritance references correctly calculate relative paths across arbitrary directory depths (e.g., `../../shared/base.yaml`).

**In spec examples?**
Partially - Example 9 shows `../base.yaml` (one level up). The `inheritance_multi_reference_update` hidden test validates `../../shared/base.yaml` (two levels up).

**In spec prose?**
Yes - Line 103: "Paths remain relative to the config file's directory"

**Can agent infer this?**

*Standard practice?* Yes - relative path calculation is a standard file system operation.

*Pattern in examples?* Yes - Example 9 demonstrates the principle.

*Could implementations reasonably differ?* No - relative path calculation is deterministic.

**Verdict:** NOT A GAP

**Reasoning:**
While the spec only shows single-level (`../`), the principle of relative path calculation is clear and standard. Agents should generalize from the example.

---

### Exit Code 1 on Errors

**What tests expect:**
Tool exits with status code 1 on any error (collision, invalid pattern, etc.).

**In spec examples?**
No explicit exit code shown in examples.

**In spec prose?**
Not explicitly stated for checkpoint 4 errors.

**Can agent infer this?**

*Standard practice?* Yes - CLI convention is exit code 0 for success, non-zero (typically 1) for errors.

**Verdict:** NOT A GAP

**Reasoning:**
Frontier agents understand CLI conventions. Exit code 1 for errors is universal.

---

## Summary of Gaps

**Critical gaps (test failures):**
1. Inheritance reference update when referencing file moves - prose only describes "referenced file moves" case, but tests validate "referencing file moves" case (Example 9 demonstrates but prose doesn't describe)

**Ambiguous specifications (need clarification):**
1. Inheritance reference update conditions - prose and example describe different scenarios

**Not gaps (agent should infer):**
1. Event ordering within phases - clear pattern in examples, verifier sorts anyway
2. Exit code 1 on errors - standard CLI convention
3. Silent skip for missing variables - explicitly stated as "skips"
4. Atomic collision detection - explicitly stated
5. Pre-relocation path in events - explicitly shown and noted
6. Directory creation - explicitly stated for each rule type
7. Pattern syntax distinctions - explicitly documented
8. scope: "file" requirement - explicitly stated
9. Relative path calculation - standard operation, principle shown in example
10. Multi-variable extraction - demonstrated in examples

---

## Recommended Additions

**New examples needed:**
None required - existing examples are comprehensive.

**Prose clarifications needed:**
1. **Line 97-104 (Inheritance Reference Updates)**: Clarify that references must be updated in two cases: (1) when the referenced file moves, AND (2) when the file containing the reference moves. Currently only case 1 is described in prose, though Example 9 demonstrates case 2.
