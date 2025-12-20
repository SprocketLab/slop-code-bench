# Loader Patterns Reference

This document catalogs the different loader patterns found in SCBench problems and how to migrate each to pytest.

## Pattern Categories

### 1. CLI with Case Directories (file_backup, dag_execution)

**Characteristics:**
- Each case is a directory: `checkpoint_N/{group}/case_name/`
- Contains `case.yaml` and `expected.jsonl`
- May have additional input files in subdirectories
- May have `backup/` or `existing/` directories with pre-populated files

**Old loader pattern:**
```python
class Loader(BaseLoader):
    def __call__(self, group, store):
        group_dir = helpers.get_group_path(group, self.problem, self.checkpoint)
        for case_dir in group_dir.iterdir():
            if not case_dir.is_dir():
                continue
            yield self.load_case(case_dir, group)

    def load_case(self, case_dir, group):
        case_yaml = yaml.load((case_dir / "case.yaml").open())
        expected = json.loads((case_dir / "expected.jsonl").read_text())
        # ... build CLICase and CLIResult
```

**New pytest pattern:**
```python
# Embed case data directly in test file
CASE_DAILY_DUE = {
    "name": "daily_due",
    "args": ["--now", "2025-09-10T03:30:00Z", "--schedule", "schedule.yaml"],
    "schedule_content": {
        "version": 1,
        "timezone": "UTC",
        "jobs": [{"id": "daily-home", "when": {"kind": "daily", "at": "03:30"}}]
    },
    "expected_events": [
        {"event": "SCHEDULE_PARSED", "timezone": "UTC", "jobs_total": 1},
        {"event": "JOB_ELIGIBLE", "job_id": "daily-home"},
    ],
}

@pytest.fixture
def schedule_file(tmp_path, request):
    """Create schedule.yaml for test."""
    schedule = tmp_path / "schedule.yaml"
    schedule.write_text(yaml.dump(request.param))
    return schedule

@pytest.mark.parametrize(
    "case,schedule_file",
    [(CASE_DAILY_DUE, CASE_DAILY_DUE["schedule_content"])],
    ids=["daily_due"],
    indirect=["schedule_file"],
)
def test_daily_due(entrypoint_argv, case, schedule_file):
    result = run_cli(entrypoint_argv, *case["args"])
    events = parse_jsonl(result.stdout)
    assert events == case["expected_events"]
```

---

### 2. CLI with Group JSON Files (etl_pipeline)

**Characteristics:**
- All cases in one JSON file: `checkpoint_N/{group}.json`
- Cases have `stdin` input (JSON piped to process)
- Arguments may come from group defaults

**Old loader pattern:**
```python
class Loader(BaseLoader):
    def __call__(self, group, store):
        group_file = chkpt_path / f"{group.get_real_name()}.json"
        with group_file.open() as f:
            cases = json.load(f)
        for case_name, case_dict in cases.items():
            stdin = json.dumps(case_dict["stdin"])
            expected = case_dict["expected"]
            # ... build CLICase with stdin
```

**New pytest pattern:**
```python
# Load cases from JSON at module level or embed directly
PIPELINE_CASES = {
    "basic_transform": {
        "stdin": {"data": [1, 2, 3]},
        "expected": {"normalized": {"values": [1, 2, 3]}},
    },
    "with_filter": {
        "stdin": {"data": [1, 2, 3, 4, 5]},
        "arguments": ["--execute"],
        "expected": {"normalized": {"values": [2, 4]}},
    },
}

@pytest.mark.parametrize(
    "case_name,case",
    list(PIPELINE_CASES.items()),
    ids=list(PIPELINE_CASES.keys()),
)
def test_pipeline(entrypoint_argv, case_name, case):
    args = case.get("arguments", [])
    stdin_data = json.dumps(case["stdin"])

    result = subprocess.run(
        entrypoint_argv + args,
        input=stdin_data,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert output == case["expected"]
```

---

### 3. API with Ordered Cases (dynamic_config_service_api)

**Characteristics:**
- Per-case JSON files: `checkpoint_N/{group}/case_name.json`
- `case_order` in config determines execution order
- Cases have `{"case": {...}, "expected": {...}}` structure
- May use Jinja2 templates in case files

**Old loader pattern:**
```python
class Loader(BaseLoader):
    def __call__(self, group, store):
        group_dir = helpers.get_group_path(group, self.problem, self.checkpoint)
        for case_name in group.case_order:
            case_file = group_dir / f"{case_name}.json"
            yield self.load_case(case_file, group)

    def load_case(self, case_file, group):
        contents = Template(case_file.read_text()).render()
        case_data = json.loads(contents)
        case = APICase(**case_data["case"])
        expected = APIResult(**case_data["expected"])
        return case, expected
```

**New pytest pattern:**
```python
import pytest
import requests

# Define cases in execution order (important for stateful APIs)
CREATE_CONFIG = {
    "method": "POST",
    "path": "/v1/configs/base",
    "body": {"config": {"db": {"host": "prod"}}, "scope": {"env": "prod"}},
    "expected_status": 201,
    "expected_body": {"name": "base", "version": 1},
}

GET_CONFIG = {
    "method": "GET",
    "path": "/v1/configs/base",
    "expected_status": 200,
    "expected_body": {"name": "base", "version": 1, "config": {"db": {"host": "prod"}}},
}


def test_create_config(api_server):
    """Core: Create base config."""
    response = requests.request(
        method=CREATE_CONFIG["method"],
        url=f"{api_server}{CREATE_CONFIG['path']}",
        json=CREATE_CONFIG.get("body"),
    )
    assert response.status_code == CREATE_CONFIG["expected_status"]
    # Use subset check if response has extra fields (like timestamps)
    for key, value in CREATE_CONFIG["expected_body"].items():
        assert response.json()[key] == value


def test_get_config(api_server):
    """Core: Get config after creation."""
    response = requests.request(
        method=GET_CONFIG["method"],
        url=f"{api_server}{GET_CONFIG['path']}",
    )
    assert response.status_code == GET_CONFIG["expected_status"]
```

---

### 4. API with Stateful Store (execution_server)

**Characteristics:**
- Custom `CaseStore` subclass tracks state across cases
- Jinja2 templates reference store values (e.g., `{{ran}}`, `{{cache_hits}}`)
- Cases depend on results of previous cases
- Stats endpoints validated against accumulated state

**Old loader pattern:**
```python
class ExecutionServerStore(CaseStore):
    def __init__(self, checkpoint_name):
        self.execution_ids = {}
        self.cache_hits = 0
        self.num_ran = 0

    def update(self, case, result, expected):
        if case.path == "/v1/execute":
            self.num_ran += 1
            self.execution_ids[case.id] = result.output["id"]

    def render_template(self, template):
        return Template(template).render(**self.get_stats_dict())

class Loader(BaseLoader):
    def initialize_store(self):
        return ExecutionServerStore(self.checkpoint.name)

    def load_case(self, case_name, case_dict, group, store):
        case_dict_str = store.render_template(json.dumps(case_dict))
        case_dict = json.loads(case_dict_str)
        # ...
```

**New pytest pattern:**
```python
import pytest

@pytest.fixture(scope="module")
def execution_state():
    """Track state across execution tests (replaces CaseStore)."""
    return {
        "execution_ids": {},
        "num_ran": 0,
        "cache_hits": 0,
        "durations": [],
    }


def test_first_execute(api_server, execution_state):
    """Execute a command for the first time."""
    response = requests.post(
        f"{api_server}/v1/execute",
        json={"command": "echo hello", "timeout": 10},
    )
    assert response.status_code == 201
    data = response.json()

    # Update state
    execution_state["execution_ids"]["echo"] = data["id"]
    execution_state["num_ran"] += 1
    execution_state["durations"].append(data["duration"])


def test_cached_execute(api_server, execution_state):
    """Same command should hit cache."""
    response = requests.post(
        f"{api_server}/v1/execute",
        json={"command": "echo hello", "timeout": 10},
    )
    assert response.status_code == 200
    assert response.json().get("cached") is True
    execution_state["cache_hits"] += 1


def test_stats_endpoint(api_server, execution_state):
    """Stats should reflect accumulated state."""
    response = requests.get(f"{api_server}/v1/stats/execution")
    assert response.status_code == 200
    data = response.json()

    assert data["ran"] == execution_state["num_ran"]
    # Allow for floating point comparison
    if execution_state["durations"]:
        import statistics
        expected_avg = statistics.mean(execution_state["durations"])
        assert abs(data["duration"]["average"] - expected_avg) < 0.01
```

---

### 5. CLI with Tracked Files (dag_execution)

**Characteristics:**
- Commands produce output files in addition to stdout
- `tracked_files` in CLICase specifies directories to capture
- Expected files stored in case directory (e.g., `output/`, `working/`)
- Verification compares file contents

**Old loader pattern:**
```python
class Loader(BaseLoader):
    def load_case(self, case_dir, group):
        # ... load input files
        case = CLICase(
            tracked_files=["output", "working"],
            # ...
        )

        expected_files = {}
        for ff in (case_dir / "output").rglob("*"):
            expected_files[ff.relative_to(case_dir).as_posix()] = ff.read_text()

        result = CLIResult(
            files=expected_files,
            # ...
        )
```

**New pytest pattern:**
```python
import json
from pathlib import Path

def test_pipeline_with_output_files(entrypoint_argv, tmp_path):
    """Test that produces output files."""
    # Setup input files
    pipeline = tmp_path / "pipeline.pipe"
    pipeline.write_text("LOAD data.csv\nTRANSFORM normalize\nSAVE output/result.json")

    working = tmp_path / "working"
    working.mkdir()
    (working / "data.csv").write_text("a,b\n1,2\n3,4")

    output_dir = tmp_path / "output"
    output_dir.mkdir()

    # Run command
    result = subprocess.run(
        entrypoint_argv + [
            str(pipeline),
            "--workspace", str(working),
            "--output", str(output_dir),
        ],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )

    assert result.returncode == 0

    # Verify stdout events
    events = parse_jsonl(result.stdout)
    assert any(e["event"] == "TASK_COMPLETED" for e in events)

    # Verify output files
    result_file = output_dir / "result.json"
    assert result_file.exists()
    result_data = json.loads(result_file.read_text())
    assert result_data == {"normalized": [[1, 2], [3, 4]]}

    # Verify jobs.jsonl
    jobs_file = output_dir / "jobs.jsonl"
    jobs = [json.loads(line) for line in jobs_file.read_text().strip().split("\n")]
    assert len(jobs) == 3  # LOAD, TRANSFORM, SAVE
```

---

### 6. CLI with Static Asset Placeholders

**Characteristics:**
- Arguments contain `{{static:asset_name}}` placeholders
- Replaced with actual paths at runtime
- Assets defined in `config.yaml` under `static_assets`

**Old case.yaml:**
```yaml
arguments: --config config.yaml --data-dir {{static:data_files}}
```

**New pytest pattern:**
```python
# In conftest.py
@pytest.fixture(scope="session")
def data_files():
    """Get data_files static asset directory."""
    return Path(__file__).parent / "assets" / "data_files"

# In test file
def test_with_static_asset(entrypoint_argv, data_files, tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text(yaml.dump({"setting": "value"}))

    result = subprocess.run(
        entrypoint_argv + [
            "--config", str(config),
            "--data-dir", str(data_files),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
```

---

## Loader Helper Functions

The old system used `slop_code.evaluation.loaders.helpers`:

| Old Helper | New Equivalent |
|------------|----------------|
| `get_group_path(group, problem, checkpoint)` | Embed data in test file |
| `get_chkpt_path(group, problem, checkpoint)` | Embed data in test file |

---

## CaseStore Migration

| Old CaseStore Pattern | New Pytest Pattern |
|-----------------------|-------------------|
| `class MyStore(CaseStore)` | `@pytest.fixture(scope="module")` |
| `store.update(case, result, expected)` | Update fixture dict after each test |
| `store.render_template(template)` | Use Python f-strings or format() |
| `loader.initialize_store()` | Fixture initialization |

---

## Input File Handling

| Old Pattern | New Pattern |
|-------------|-------------|
| `InputFile(path=..., content=...)` | Write to `tmp_path` fixture |
| `InputFile.from_path(...)` | Use `shutil.copy()` or `Path.write_text()` |
| Binary content in InputFile | Use `Path.write_bytes()` |
| `FileType.YAML` | `yaml.dump()` + `Path.write_text()` |
| `FileType.JSON` | `json.dumps()` + `Path.write_text()` |
| `FileType.BINARY` | `Path.write_bytes()` |

Example:
```python
def test_with_input_files(entrypoint_argv, tmp_path):
    # Create YAML config
    config = tmp_path / "config.yaml"
    config.write_text(yaml.dump({"key": "value"}))

    # Create JSON data
    data = tmp_path / "data.json"
    data.write_text(json.dumps({"items": [1, 2, 3]}))

    # Create binary file
    binary = tmp_path / "data.bin"
    binary.write_bytes(b"\x00\x01\x02\x03")

    # Run with all files
    result = subprocess.run(
        entrypoint_argv + [
            "--config", str(config),
            "--data", str(data),
            "--binary", str(binary),
        ],
        capture_output=True,
        text=True,
    )
```

---

## Complex Case Loading

If a problem has many cases, consider loading from JSON at module level:

```python
import json
from pathlib import Path

# Load cases from embedded JSON (converted from old case directories)
CASES_JSON = """
{
    "case_1": {"args": [...], "expected": [...]},
    "case_2": {"args": [...], "expected": [...]}
}
"""
CASES = json.loads(CASES_JSON)

@pytest.mark.parametrize("case_name,case", list(CASES.items()), ids=list(CASES.keys()))
def test_all_cases(entrypoint_argv, case_name, case):
    # ...
```

Or if you prefer external files, create `tests/data/` directory:
```python
@pytest.fixture(scope="module")
def test_cases():
    cases_file = Path(__file__).parent / "data" / "checkpoint_1_cases.json"
    return json.loads(cases_file.read_text())
```
