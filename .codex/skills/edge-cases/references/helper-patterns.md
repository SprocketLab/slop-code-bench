# Helper Patterns That Pay Off

Prefer a small toolkit of reusable helpers over repeating boilerplate. Keep
helpers tiny, pure, and easy to read. Avoid helpers that embed spec details;
pass expectations from the test.

Imports typically used: `csv`, `json`, `subprocess`, `pathlib.Path`, `pytest`.

## Common Helper Shapes

- `run_cli(entrypoint_argv, args, cwd, timeout)` wrapper around `subprocess.run`
- `write_text`/`write_json` helpers for input files under `tmp_path`
- `normalize_args(args, tmp_path)` for absolute paths in CLI invocations
- `request_json(base_url, method, path, payload)` for HTTP-style problems

## Case Table With a Single Runner

```python
EDGE_CASES = [
    {"id": "empty_input", "args": ["--input", ""], "err": "empty"},
    {"id": "negative_count", "args": ["--count", "-1"], "err": "negative"},
]


@pytest.mark.functionality
@pytest.mark.parametrize(
    "case",
    EDGE_CASES,
    ids=[case["id"] for case in EDGE_CASES],
)
def test_edge_cases(
    entrypoint_argv: list[str],
    tmp_path: Path,
    case: dict[str, str | list[str]],
) -> None:
    result = run_cli(entrypoint_argv, case["args"], cwd=tmp_path)
    assert_error(result, contains=case["err"])
```

## Structured Output Normalization

```python
def normalize_json_payload(payload: object) -> object:
    if isinstance(payload, dict):
        return {
            key: normalize_json_payload(payload[key])
            for key in sorted(payload)
        }
    if isinstance(payload, list):
        return [normalize_json_payload(item) for item in payload]
    return payload
```

## Plain-Text Normalization

```python
def assert_text_lines_equal(actual: str, expected: str) -> None:
    actual_lines = [line.rstrip() for line in actual.strip().splitlines()]
    expected_lines = [line.rstrip() for line in expected.strip().splitlines()]
    assert actual_lines == expected_lines
```

## Error Assertion Helper

```python
def assert_error(
    result: subprocess.CompletedProcess[str],
    *,
    contains: str | None = None,
) -> None:
    assert result.returncode != 0
    if contains:
        assert contains.lower() in result.stderr.lower()
```

## Stable Ordering Helper

```python
def sort_items(
    items: list[dict[str, object]],
    *,
    key: str,
) -> list[dict[str, object]]:
    return sorted(items, key=lambda item: str(item.get(key, "")))
```

## File Output Helpers (JSONL + CSV)

```python
def read_jsonl(path: Path) -> list[dict[str, object]]:
    lines = [line for line in path.read_text().splitlines() if line.strip()]
    return [json.loads(line) for line in lines]


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return [row for row in reader]
```

## Directory Snapshot Helper

```python
def list_tree(root: Path) -> list[str]:
    return sorted(
        str(path.relative_to(root))
        for path in root.rglob("*")
        if path.is_file()
    )
```

## Floating-Point Tolerance

```python
def assert_float_close(actual: float, expected: float) -> None:
    assert actual == pytest.approx(expected, rel=1e-6, abs=1e-9)
```

## HTTP Error Schema Helper

Only use when the spec defines these fields.

```python
def assert_http_error(
    status: int,
    body: dict[str, object] | None,
    *,
    allowed_statuses: set[int],
    code: str | None = None,
    message_contains: str | None = None,
) -> None:
    assert status in allowed_statuses
    assert body is not None
    if code is not None:
        assert body.get("code") == code
    if message_contains is not None:
        message = str(body.get("message", ""))
        assert message_contains.lower() in message.lower()
```
