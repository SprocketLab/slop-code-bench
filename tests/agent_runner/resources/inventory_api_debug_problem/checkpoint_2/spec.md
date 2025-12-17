Extend the inventory API from checkpoint 1 with lightweight analytics and item
updates. The service must remain backwards compatible: all routes from
checkpoint 1 must continue to work exactly as before.

## New behaviour

### Item categories

* Every item now has an optional string field `category`.
* `POST /v1/items` accepts `"category"` in the request body (default `null`).
* All responses containing an item must include the `category` field.

### Update an item

`PUT /v1/items/<id>`

* Request body may include any subset of `name`, `quantity`, or `category`.
* Returns `200 OK` with the updated item.
* If the item does not exist → `404 Not Found` with `{"error":"ITEM_NOT_FOUND"}`.
* Invalid payloads should return `400 Bad Request` with
  `{"error":"INVALID_INPUT"}`.

### Filtered listing

`GET /v1/items?category=<value>` returns only items with the exact matching
category, still sorted by `id`. Without the query parameter it must return all
items (same as checkpoint 1).

### Inventory stats

`GET /v1/items/stats` returns summary information:

```json
{
  "total": <int>,                // total number of items
  "categories": {                // counts per distinct category
    "<category>": <int>,
    "...": ...
  }
}
```

## Notes

* Keep the same entrypoint (`%%%ENTRYPOINT:entry_file%%%`) and flag handling.
* Preserve response schemas from checkpoint 1 while adding `category`.
* Order of keys inside objects does not matter, but avoid extra metadata beyond
  what the contract specifies.
