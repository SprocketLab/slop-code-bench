### Problem Understanding

* **Core requirement**: Parse a YAML backup schedule, determine which jobs are due within a time window, simulate file selection with exclusion rules in a mounted directory, and emit a deterministic JSON Lines event stream.
* **Input/Output**: CLI inputs (`--schedule`, `--now`, `--duration`, `--mount`) → JSON Lines to `stdout`, errors to `stderr`. Reads a YAML schedule file on disk; walks files under `--mount`.
* **Key constraints**: Strict schema validation with specific exit codes (`E_PARSE`, `E_SCHEMA`). Timezone-aware “due” checks at minute precision. Deterministic ordering (sorted jobs, sorted files). Use `Job` and `File` dataclasses. **Only walk each job’s source once**.

---

### Implementation Steps

1. **Scaffold CLI + Event Writer**

   * Build: `main()` with `argparse` for the four flags and defaults; helper `emit(event: dict)` that serializes **keys in exact order**: `level,event,job_id` then event-specific fields. Use `json.dumps(..., separators=(',',':'))` and `sys.stdout.write(line+'\n')`.
   * Result: Running script prints a single dummy `SCHEDULE_PARSED` skeleton line (no YAML yet).

2. **YAML Load + Schema Validation**

   * Build:

     * `load_yaml(path) -> dict` using `yaml.safe_load`. Catch parser exceptions → `stderr: "ERROR:E_PARSE:<msg>"` and `sys.exit(3)`.
     * `validate_schedule(doc, mount_root) -> (timezone, List[Job])`. Enforce:

       * `version == 1`
       * `timezone` is valid IANA (via `zoneinfo.ZoneInfo`), default `"UTC"`; invalid → `E_SCHEMA`.
       * `jobs` non-empty; each has unique `id` (≤128, non-empty).
       * `when.kind ∈ {daily, weekly, once}` with required/forbidden fields.
       * `when.at`: for `daily|weekly` -> `"HH:MM"` (24h); for `once` -> ISO string **without tz**, parse in schedule tz.
       * `source`: `"mount://..."` path that resolves under `--mount` and exists as directory.
       * `destination`: optional `"mount://..."` or `"ignored://sink"`. If `mount://...`, just validate path syntax (existence not required by spec) and normalization under `--mount`.
       * `exclude`: list[str] or default `[]`.
     * Create `Job` dataclass: `id, enabled, kind, at, days, source_abs, source_rel, exclude_patterns, destination, tags`.
   * Result: With a valid file, script emits a real `SCHEDULE_PARSED` (`timezone`,`jobs_total`). Invalid files produce exactly one error line and proper exit code `4`.

3. **Scheduling Window Computation (minute precision)**

   * Build:

     * Parse `--now` as UTC (RFC3339). If omitted, use current UTC.
     * Convert to schedule tz (`ZoneInfo`), compute closed interval `[now_local_minute, end_local_minute]` where `end = now + duration hours` **inclusive bound** at minute level.
     * `is_due(job, window_start_local, window_end_local, tz) -> bool`:

       * `daily`: Construct candidate datetimes at `HH:MM` for all calendar days intersecting window; due if any candidate minute within inclusive window.
       * `weekly`: As above, additionally require weekday ∈ `days` (Mon..Sun).
       * `once`: Interpret `when.at` as a timezone-naive local timestamp, localize to schedule tz; due if its minute is within inclusive window.
     * Emit for each job exactly one of: `JOB_ELIGIBLE` or `JOB_SKIPPED_NOT_DUE` with `kind` and `now_local` (formatted local minute `YYYY-MM-DDTHH:MM`).
   * Result: You can run with different `--now/--duration` and see correct eligibility events.

4. **Single-Pass Source Walk + Glob Matching**

   * Build:

     * `File` dataclass: `rel_path: str` (POSIX-style), maybe `abs_path: Path`.
     * `iter_files(source_abs) -> List[File]`: **walk exactly once** using `os.walk`, build `rel_path` via `os.path.relpath(..., source_abs)` and convert to POSIX with `PurePosixPath`. Collect into a list, then **sort lexicographically by `rel_path`** to ensure determinism.
     * `first_matching_pattern(rel_path, patterns) -> Optional[str]` using `PurePosixPath(rel_path).match(p)` to get proper `**` semantics across `/` (case-sensitive). Return the **first** pattern that matches, else `None`.
   * Result: For a job, you can print which files would be excluded/selected deterministically without rewalking.

5. **Execution Loop + Event Emission**

   * Build:

     * Sort **due** jobs by `id` ascending.
     * For each due job:

       * Emit `JOB_STARTED` with `exclude_count`.
       * Iterate sorted `File`s once:

         * If `match := first_matching_pattern(...)` → emit `FILE_EXCLUDED` with `path` and `pattern`, increment `excluded`.
         * Else → emit `FILE_SELECTED` with `path`, increment `selected`.
       * Emit `JOB_COMPLETED` with counts.
   * Result: End-to-end behavior matches the sample outputs (order, fields, counts), with deterministic JSON Lines.

---

### Code Structure

```
backup_scheduler.py
├── main()
├── emit(record: dict) -> None
├── load_yaml(path: str) -> dict
├── validate_schedule(doc: dict, mount_root: Path) -> tuple[ZoneInfo, list[Job]]
├── is_due(job: Job, win_start_local: datetime, win_end_local: datetime, tz: ZoneInfo) -> bool
├── iter_files(source_abs: Path) -> list[File]
├── first_matching_pattern(rel_path: str, patterns: list[str]) -> str|None
├── data classes
│   ├── Job(id: str, enabled: bool, kind: str, at: Union[time, datetime], days: set[int]|None,
│   │        source_abs: Path, source_rel: str, exclude_patterns: list[str],
│   │        destination: str|None, tags: list[str]|None)
│   └── File(rel_path: str, abs_path: Path)
└── helpers
    ├── parse_local_time_hhmm(s: str) -> time
    ├── parse_once_local_datetime(s: str, tz: ZoneInfo) -> datetime
    ├── fmt_local_minute(dt: datetime) -> str  # "YYYY-MM-DDTHH:MM"
requirements.txt
└── pyyaml
```

* **Standard library**: `argparse`, `json`, `sys`, `os`, `pathlib`, `datetime`, `zoneinfo`, `itertools`, `typing`, `dataclasses`.
* **Third-party**: `PyYAML` only (listed exactly as `pyyaml`).

---

### Test Cases to Verify

* [ ] **Basic (matches sample)**
  Schedule and `files` tree from the prompt, `--mount` pointing to the provided structure, run with `--now 2025-09-10T03:30:00Z --duration 24 --schedule schedule.yaml`.
  Expected: Events exactly as shown in Example 1 (counts, ordering, first matching pattern, minute formatting).

* [ ] **Source subdir (sample variant)**
  Same schedule but `source: mount://A/B`, expected events exactly as Example 2 (relative paths rooted at `A/B`, counts/ordering).

* [ ] **Weekly with day filter + inclusive end**
  `when.kind=weekly`, `days: ["Tue"]`, `at: "03:30"`, `--now` set to Monday `2025-09-08T04:00Z`, `--duration 23`. Not due.
  Then `--duration 24` to cross into local Tuesday 03:30 — due, and `JOB_ELIGIBLE` emitted. Confirms inclusive end minute.

* [ ] **Once with timezone interpretation**
  `timezone: "America/Chicago"`, `kind: once`, `at: "2025-09-10T03:30"` (no tz). With `--now 2025-09-10T08:30:20Z --duration 0`, should be **due** (03:30 CT == 08:30Z), minute precision (seconds ignored).

* [ ] **Exclusion precedence (first match)**
  Patterns `["**/*.bin","A/*"]`, file `A/J.bin` must report `"pattern": "**/*.bin"` (first match), even though later patterns also match.

* [ ] **Schema errors → `E_SCHEMA`**

  * Invalid timezone string.
  * Duplicate job IDs.
  * Weekly without `days`.
  * `source` not under `--mount` or does not exist.
    Each prints **one** `stderr` line and exits with code `4`.

* [ ] **Parse errors → `E_PARSE`**
  Broken YAML (e.g., bad indentation). Prints **one** error line and exits `3`.

* [ ] **Determinism**
  Re-run same inputs → byte-identical JSON lines (no trailing spaces, no extra newline at end of file, fixed key order).

---

#### Notes on tricky bits (addressed in steps)

* **Minute precision**: Truncate seconds from both window bounds and candidate times; treat end bound as inclusive.
* **Glob semantics**: Use `PurePosixPath.match` for `**` spanning directories; keep paths POSIX-style irrespective of OS.
* **Only walk once**: For each job, `os.walk` exactly once → collect all file paths, sort once, process once. No re-walks for exclusions.
* **JSON key order**: Build dicts in insertion order with `("level","event","job_id",...)` to guarantee serialization order.

If you want, I can now generate the initial `backup_scheduler.py` and `requirements.txt` following this plan.
