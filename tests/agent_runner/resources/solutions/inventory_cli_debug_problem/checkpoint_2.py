#!/usr/bin/env python3
import argparse
import json
import os
import sys
from typing import Any

STATE_FILE = "inventory_state.json"


def _print_json(obj: Any) -> None:
    sys.stdout.write(json.dumps(obj, separators=(",", ":")))
    sys.stdout.write("\n")


def _error(payload: dict[str, Any], code: int = 1) -> None:
    _print_json(payload)
    sys.exit(code)


def load_state() -> list[dict[str, Any]]:
    if not os.path.exists(STATE_FILE):
        return []
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                cleaned = []
                for it in data:
                    if (
                        isinstance(it, dict)
                        and {"id", "name", "quantity"} <= it.keys()
                    ):
                        cleaned.append(
                            {
                                "id": int(it.get("id")),
                                "name": str(it.get("name")),
                                "quantity": int(it.get("quantity")),
                                # Back-compat: legacy items might lack category
                                "category": (
                                    it.get("category")
                                    if it.get("category") is not None
                                    else None
                                ),
                            }
                        )
                return cleaned
            return []
    except Exception:
        # Treat unreadable/invalid JSON as empty inventory
        return []


def save_state(items: list[dict[str, Any]]) -> None:
    items_sorted = sorted(items, key=lambda x: int(x["id"]))
    # Ensure each item has category key (possibly None) for persistence
    normalized = []
    for it in items_sorted:
        normalized.append(
            {
                "id": int(it["id"]),
                "name": str(it["name"]),
                "quantity": int(it["quantity"]),
                "category": (
                    it["category"] if it.get("category") is not None else None
                ),
            }
        )
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(normalized, f, separators=(",", ":"))


class JsonArgParser(argparse.ArgumentParser):
    def error(self, message):
        _error({"error": "INVALID_INPUT"}, code=1)

    def exit(self, status=0, message=None):
        if status:
            _error({"error": "INVALID_INPUT"}, code=1)
        else:
            sys.exit(0)


def next_id(items: list[dict[str, Any]]) -> int:
    if not items:
        return 1
    return max(int(it["id"]) for it in items) + 1


def validate_quantity(q: int | None) -> bool:
    if q is None:
        return True
    try:
        return int(q) >= 0
    except Exception:
        return False


def as_item_output(it: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": int(it["id"]),
        "name": str(it["name"]),
        "quantity": int(it["quantity"]),
        "category": (
            it["category"] if it.get("category") is not None else None
        ),
    }


def cmd_create(args) -> None:
    name = args.name
    quantity = args.quantity
    category = (
        args.category
        if args.category is not None and args.category != ""
        else None
    )

    if (
        name is None
        or name == ""
        or quantity is None
        or not validate_quantity(quantity)
    ):
        _error({"error": "INVALID_INPUT"}, code=1)

    items = load_state()
    nid = next_id(items)
    item = {
        "id": nid,
        "name": str(name),
        "quantity": int(quantity),
        "category": category,
    }
    items.append(item)
    save_state(items)
    _print_json(as_item_output(item))
    sys.exit(0)


def cmd_get(args) -> None:
    try:
        iid = int(args.id)
    except Exception:
        _error({"error": "INVALID_INPUT"}, code=1)

    items = load_state()
    for it in items:
        if int(it["id"]) == iid:
            _print_json(as_item_output(it))
            sys.exit(0)

    _error({"error": "ITEM_NOT_FOUND"}, code=1)


def cmd_list(args) -> None:
    items = load_state()
    items_sorted = sorted(items, key=lambda x: int(x["id"]))
    if args.category is not None:
        cat = args.category
        items_sorted = [it for it in items_sorted if it.get("category") == cat]
    out = [as_item_output(it) for it in items_sorted]
    _print_json(out)
    sys.exit(0)


def cmd_update(args) -> None:
    # Must provide at least one field
    no_fields = (
        args.name is None and args.quantity is None and args.category is None
    )
    if no_fields:
        _error({"error": "INVALID_INPUT"}, code=1)

    # Validate id
    try:
        iid = int(args.id)
    except Exception:
        _error({"error": "INVALID_INPUT"}, code=1)

    # Validate fields
    if args.quantity is not None and not validate_quantity(args.quantity):
        _error({"error": "INVALID_INPUT"}, code=1)
    if args.name is not None and args.name == "":
        _error({"error": "INVALID_INPUT"}, code=1)

    items = load_state()
    for it in items:
        if int(it["id"]) == iid:
            if args.name is not None:
                it["name"] = str(args.name)
            if args.quantity is not None:
                it["quantity"] = int(args.quantity)
            if args.category is not None:
                it["category"] = args.category if args.category != "" else None
            save_state(items)
            _print_json(as_item_output(it))
            sys.exit(0)

    _error({"error": "ITEM_NOT_FOUND"}, code=1)


def cmd_stats(_args) -> None:
    items = load_state()
    total = len(items)
    categories: dict[str, int] = {}
    for it in items:
        cat = it.get("category")
        if cat is None:
            continue  # exclude null from keyed counts (keys must be strings)
        categories[cat] = categories.get(cat, 0) + 1
    _print_json({"total": int(total), "categories": categories})
    sys.exit(0)


def build_parser() -> argparse.ArgumentParser:
    parser = JsonArgParser(prog="inventory_cli", add_help=False)
    subparsers = parser.add_subparsers(dest="command")

    # create
    p_create = subparsers.add_parser("create", add_help=False)
    p_create.add_argument("--name", required=False)
    p_create.add_argument("--quantity", type=int, required=False)
    p_create.add_argument("--category", required=False)
    p_create.set_defaults(func=cmd_create)

    # get
    p_get = subparsers.add_parser("get", add_help=False)
    p_get.add_argument("id", nargs="?", type=int)
    p_get.set_defaults(func=cmd_get)

    # list
    p_list = subparsers.add_parser("list", add_help=False)
    p_list.add_argument("--category", required=False)
    p_list.set_defaults(func=cmd_list)

    # update
    p_update = subparsers.add_parser("update", add_help=False)
    p_update.add_argument("id", nargs="?", type=int)
    p_update.add_argument("--name", required=False)
    p_update.add_argument("--quantity", type=int, required=False)
    p_update.add_argument("--category", required=False)
    p_update.set_defaults(func=cmd_update)

    # stats
    p_stats = subparsers.add_parser("stats", add_help=False)
    p_stats.set_defaults(func=cmd_stats)

    return parser


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]

    parser = build_parser()

    if not argv:
        _error({"error": "INVALID_INPUT"}, code=1)

    args = parser.parse_args(argv)

    if not hasattr(args, "func"):
        _error({"error": "INVALID_INPUT"}, code=1)

    args.func(args)


if __name__ == "__main__":
    main()
