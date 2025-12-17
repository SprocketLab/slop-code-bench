Build a tiny settings command-line tool that reads default assets, persists
state between runs, and emits deterministic JSON responses. This problem should
be quick to solve and useful for debugging agent behaviour end-to-end.

## Deliverable

Create a CLI that manages a key/value settings map persisted to the working
directory.

* **Entrypoint:** `%%%ENTRYPOINT:entry_file%%%`
* **Usage:** `tiny_settings_cli <command> [arguments]`
* **Defaults:** Ship the provided `assets/default_settings.json` along with the
  accompanying `assets/meta_notes.txt`. The CLI must copy the defaults into a
  runtime state file named `settings_state.json` when it is missing.
* **Static metadata:** Every response must include the text from
  `assets/meta_notes.txt` under the key `"meta": {"notes": "<contents>"}`.
* **Persistence:** Read and write `settings_state.json` for all stateful
  commands. If the file is missing, recreate it from the defaults before
  executing the command. All file paths are relative to the current working
  directory.
* **Output:** Print JSON only, with no extra logging. Successful commands exit
  with status code `0`. Validation failures should exit non-zero and still
  print a JSON payload.

## Commands

### `show`

```
tiny_settings_cli show
```

* Loads the current state (or defaults if no state file exists).
* Returns exit `0` with:

```json
{
  "settings": {
    "...": "..."
  },
  "meta": {
    "notes": "<contents of assets/meta_notes.txt>"
  }
}
```

### `set`

```
tiny_settings_cli set <key> <value>
```

* Updates a single string-valued entry.
* Persists the updated map to `settings_state.json`.
* Returns exit `0` with `{"key": "<key>", "value": "<value>"}` and the same
  `meta` block as above.
* Missing arguments should exit `1` and return `{"error": "INVALID_INPUT"}`.

### `reset`

```
tiny_settings_cli reset
```

* Deletes `settings_state.json` if it exists and recreates it using the bundled
  defaults.
* Returns exit `0` with the same JSON payload shape as the `show` command.

## Implementation Notes

* Use any argument-parsing approach (e.g. `argparse`).
* Keep the defaults small and deterministic; no randomisation.
* Do not emit extraneous stderr/stdout content.
