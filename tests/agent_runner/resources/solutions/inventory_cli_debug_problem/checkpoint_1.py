#!/usr/bin/env python3
import argparse
import json
import os
import sys
from typing import Any

STATE_FILE = "inventory_state.json"


def _print_json(obj: Any) -> None:
    # Deterministic/minimal JSON (no spaces, no extra fields)
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
                # Ensure items are dicts with expected keys
                cleaned = []
                for it in data:
                    if (
                        isinstance(it, dict)
                        and {"id", "name", "quantity"} <= it.keys()
                    ):
                        cleaned.append(
                            {
                                "id": int(it["id"]),
                                "name": str(it["name"]),
                                "quantity": int(it["quantity"]),
                            }
                        )
                return cleaned
            return []
    except Exception:
        # Treat unreadable/invalid JSON as empty inventory per “missing files” spirit
        return []


def save_state(items: list[dict[str, Any]]) -> None:
    # Persist list of items; keep sorted by id for deterministic state
    items_sorted = sorted(items, key=lambda x: int(x["id"]))
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(items_sorted, f, separators=(",", ":"))


class JsonArgParser(argparse.ArgumentParser):
    def error(self, message):
        # Print deterministic JSON error on stdout and exit code 1
        _error({"error": "INVALID_INPUT"}, code=1)

    def exit(self, status=0, message=None):
        # Route all exits through our JSON error on non-zero
        if status:
            _error({"error": "INVALID_INPUT"}, code=1)
        else:
            sys.exit(0)


def next_id(items: list[dict[str, Any]]) -> int:
    if not items:
        return 1
    # IDs increment by one per item; choose max(existing)+1
    return max(int(it["id"]) for it in items) + 1


def cmd_create(args) -> None:
    # Validate presence (argparse guarantees flags exist if provided, but we also enforce non-empty name)
    name = args.name
    quantity = args.quantity

    if name is None or name == "" or quantity is None:
        _error({"error": "INVALID_INPUT"}, code=1)

    items = load_state()
    nid = next_id(items)
    item = {"id": nid, "name": str(name), "quantity": int(quantity)}
    items.append(item)
    save_state(items)
    _print_json(item)
    sys.exit(0)


def cmd_get(args) -> None:
    try:
        iid = int(args.id)
    except Exception:
        _error({"error": "INVALID_INPUT"}, code=1)

    items = load_state()
    for it in items:
        if int(it["id"]) == iid:
            # Return item in required shape/order
            out = {
                "id": int(it["id"]),
                "name": str(it["name"]),
                "quantity": int(it["quantity"]),
            }
            _print_json(out)
            sys.exit(0)

    _error({"error": "ITEM_NOT_FOUND"}, code=1)


def cmd_list(_args) -> None:
    items = load_state()
    items_sorted = sorted(items, key=lambda x: int(x["id"]))
    out = [
        {
            "id": int(it["id"]),
            "name": str(it["name"]),
            "quantity": int(it["quantity"]),
        }
        for it in items_sorted
    ]
    _print_json(out)
    sys.exit(0)


def build_parser() -> argparse.ArgumentParser:
    parser = JsonArgParser(prog="inventory_cli", add_help=False)
    subparsers = parser.add_subparsers(dest="command")

    # create
    p_create = subparsers.add_parser("create", add_help=False)
    p_create.add_argument("--name", required=False)
    p_create.add_argument("--quantity", type=int, required=False)
    p_create.set_defaults(func=cmd_create)

    # get
    p_get = subparsers.add_parser("get", add_help=False)
    p_get.add_argument("id", nargs="?", type=int)
    p_get.set_defaults(func=cmd_get)

    # list
    p_list = subparsers.add_parser("list", add_help=False)
    p_list.set_defaults(func=cmd_list)

    return parser


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]

    parser = build_parser()

    # If no arguments at all, treat as INVALID_INPUT
    if not argv:
        _error({"error": "INVALID_INPUT"}, code=1)

    args = parser.parse_args(argv)

    # If no subcommand matched, invalid input
    if not hasattr(args, "func"):
        _error({"error": "INVALID_INPUT"}, code=1)

    # Dispatch
    args.func(args)


if __name__ == "__main__":
    main()
