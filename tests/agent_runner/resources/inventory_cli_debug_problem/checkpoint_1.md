Build a minimal inventory command-line tool that stores items in a JSON file
and prints deterministic JSON responses. This problem is designed for quick
manual debugging and should be solvable in a single attempt.

## Deliverable

Create a CLI that manages an in-memory inventory persisted to a file in the
working directory.

* **Entrypoint:** `%%%ENTRYPOINT:entry_file%%%`
* **Usage:** `inventory_cli <command> [options]`
* **Persistence:** Store data in `inventory_state.json` (relative to CWD).
  Missing files should be treated as an empty inventory; the file must be
  updated after every successful mutation so that subsequent invocations see
  prior changes.
* **Output:** Print JSON to stdout only and terminate with exit code `0` on
  success. Validation failures should return a non-zero exit code and still
  print a JSON error payload.
* Each invocation starts with the persisted state; no background process is
  expected.

## Commands

### `create`

```
%%%ENTRYPOINT:entry_command%%% create --name <string> --quantity <int>
```

* Appends a new item to the inventory.
* Auto-assigns an integer `id` starting at `1` and incrementing by one per item.
* Returns `{"id": <int>, "name": <string>, "quantity": <int>}`.
* Rejects requests missing `name` or `quantity` with exit code `1` and
  `{"error":"INVALID_INPUT"}`.

### `get`

```
%%%ENTRYPOINT:entry_command%%% get <id>
```

* Returns the item matching the integer identifier.
* On success: exit `0` with the same shape as the create response.
* If not found: exit `1` with `{"error":"ITEM_NOT_FOUND"}`.

### `list`

```
%%%ENTRYPOINT:entry_command%%% list
```

* Returns exit `0` with a JSON array of all items in ascending `id` order.

## Implementation notes

* The CLI may use any argument-parsing library (e.g. `argparse`, `typer`).
* Persist all state in `inventory_state.json`; each invocation must read and
  write this file.
* Keep JSON output deterministic: no additional fields, and avoid trailing text.
