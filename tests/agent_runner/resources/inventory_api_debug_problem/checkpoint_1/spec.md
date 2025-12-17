Build a minimal inventory HTTP API service that can store in-memory items and
expose deterministic JSON responses. This problem is designed for quick manual
debugging and should be solvable in a single attempt.

## Deliverable

Create a service that starts an HTTP server and responds to the routes
described below.

* **Entrypoint:** `%%%ENTRYPOINT:entry_file%%%`
* **Flags (required):**
  * `--address` (default `0.0.0.0`)
  * `--port` (default `8080`)
* **Healthcheck:** `GET /healthz` returns `200 OK` with `{"ok": true}`
* The server may use any Python web framework (Flask, FastAPI, etc.) but must
  install its dependencies at runtime (e.g. by writing a `requirements.txt`
  and invoking `pip install -r requirements.txt` inside the entrypoint script).
* Persist all data in memory only; each run starts from an empty inventory.
* Always respond with `application/json; charset=utf-8`.

## API contract

### `POST /v1/items`

Request body:

```json
{ "name": "<string>", "quantity": <int> }
```

Behaviour:

* Creates a new item.
* Auto-assigns an integer `id` starting at `1` and incrementing by one per item.
* Returns `201 Created` with the created item.
* Rejects requests missing `name` or `quantity` with `400 Bad Request` and
  `{"error":"INVALID_INPUT"}`.

Response:

```json
{ "id": <int>, "name": "<string>", "quantity": <int> }
```

### `GET /v1/items/<id>`

* Returns the item matching the integer identifier.
* On success: `200 OK` with the same shape as the create response.
* If not found: `404 Not Found` with `{"error":"ITEM_NOT_FOUND"}`.

### `GET /v1/items`

* Returns `200 OK` with a JSON array of all items in ascending `id` order.

## Implementation notes

* The entrypoint script should launch the server and block until termination.
* Accept the flag values either via CLI parsing (`argparse`, `click`, etc.) or
  environment variables; the tests will invoke the script with `--address` and
  `--port`.
* Use deterministic JSON output (no additional fields, stable key ordering is
  fine).
* The service must start within 10 seconds so that the health check succeeds.
