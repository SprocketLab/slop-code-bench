# Example Patterns

Use minimal helpers that fit the problem shape.

Imports typically used: `json`, `urllib.request`, `urllib.error`, `subprocess`,
`pathlib.Path`, `pytest`.

## CLI-Style

```python
def run_cli(
    entrypoint_argv: list[str],
    args: list[str],
    *,
    cwd: Path,
    timeout: int = 10,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        entrypoint_argv + args,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(cwd),
    )


@pytest.mark.functionality
def test_missing_required_flag(
    entrypoint_argv: list[str],
    tmp_path: Path,
) -> None:
    """Edge case: Missing required flag should return an error."""
    result = run_cli(entrypoint_argv, [], cwd=tmp_path)
    assert result.returncode != 0
    assert "required" in result.stderr.lower()
```

## HTTP-Style (stdlib `json` and `urllib`)

```python
def request_json(
    base_url: str,
    method: str,
    path: str,
    payload: dict[str, object] | None,
) -> tuple[int, dict[str, str], dict[str, object] | None]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"content-type": "application/json"} if data else {}
    request = urllib_request.Request(
        f"{base_url}{path}",
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with urllib_request.urlopen(request, timeout=10) as response:
            body = response.read().decode("utf-8")
            return (
                response.status,
                dict(response.headers.items()),
                json.loads(body) if body else None,
            )
    except urllib_error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        return exc.code, dict(exc.headers.items()), json.loads(body) if body else None


@pytest.mark.functionality
def test_missing_required_field(server_url: str) -> None:
    """Edge case: Missing required field should return a validation error."""
    status, _headers, body = request_json(server_url, "POST", "/v1/items", {})
    assert status in {400, 422}
    assert body is not None
```
