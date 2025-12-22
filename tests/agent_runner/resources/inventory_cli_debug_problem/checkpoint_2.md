Extend the inventory CLI from checkpoint 1 with lightweight analytics and item
updates. The tool must remain backwards compatible: all commands from
checkpoint 1 should continue to work exactly as before.

## New behaviour

### Item categories

* Every item now has an optional string field `category`.
* `create` accepts `--category <value>` (default `null` when omitted).
* All responses containing an item must include the `category` field.

### Update an item

```
%%%ENTRYPOINT:entry_command%%% update <id> [--name <str>] [--quantity <int>] [--category <str>]
```

* Applies any provided fields to the item with the given identifier.
* Success: exit `0` with the updated item.
* Missing item: exit `1` with `{"error":"ITEM_NOT_FOUND"}`.
* Invalid payload (no fields, negative quantity, etc.): exit `1` with
  `{"error":"INVALID_INPUT"}`.

### Filtered listing

```
%%%ENTRYPOINT:entry_command%%% list [--category <value>]
```

* When `--category` is supplied, return only items whose category matches
  exactly, still sorted by `id`.
* Without the flag it must return all items (same as checkpoint 1, but now each
  item includes `category`).

### Inventory stats

```
%%%ENTRYPOINT:entry_command%%% stats
```

* Returns:

```json
{
  "total": <int>,                // number of items
  "categories": {                // counts per distinct category
    "<category>": <int>,
    "...": ...
  }
}
```

## Notes

* Keep using `inventory_state.json` for persistence between invocations.
* Preserve response schemas from checkpoint 1 while adding the `category`
  field.
* Order of keys inside objects does not matter, but avoid extra metadata beyond
  what the contract specifies.
