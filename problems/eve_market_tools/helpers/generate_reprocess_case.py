from __future__ import annotations

import argparse
import bz2
import gzip
import json
import math
from pathlib import Path

import pandas as pd

HUB_LOCATIONS = {
    "jita": 60003760,
    "amarr": 60008494,
    "dodixie": 60011866,
    "rens": 60004588,
    "hek": 60005686,
}

ASTEROID_CATEGORY = 25
ICE_GROUP = 465
GAS_GROUPS = {4168}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a reprocess profit case from local market data.",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Path to write the generated JSON case.",
    )
    parser.add_argument(
        "--hub",
        default="jita",
        help="Hub to source sell orders from.",
    )
    parser.add_argument(
        "--k",
        type=int,
        default=10,
        help="Maximum number of items to include.",
    )
    parser.add_argument(
        "--sort-by",
        choices=["roi", "profit"],
        default="roi",
        help="Sort key for items.",
    )
    parser.add_argument(
        "--sales-tax",
        type=float,
        default=0.04,
        help="Sales tax applied to buying and selling.",
    )
    parser.add_argument(
        "--scrap-efficiency",
        type=float,
        default=0.55,
        help="Scrap reprocessing efficiency.",
    )
    parser.add_argument(
        "--include-non-unit-portions",
        action="store_true",
        help="Include items with portionSize > 1 (default excludes them).",
    )
    parser.add_argument(
        "--order",
        type=int,
        default=1,
        help="Order index for the case payload.",
    )
    return parser.parse_args()


def load_orders(path: Path) -> pd.DataFrame:
    with gzip.open(path, "rt") as handle:
        return pd.read_csv(handle)


def load_types(path: Path) -> pd.DataFrame:
    with bz2.open(path, "rt") as handle:
        return pd.read_csv(handle)


def load_materials(path: Path) -> pd.DataFrame:
    with bz2.open(path, "rt") as handle:
        return pd.read_csv(handle)


def build_reprocess_items(
    orders_df: pd.DataFrame,
    materials_df: pd.DataFrame,
    types_df: pd.DataFrame,
    groups_df: pd.DataFrame,
    hub: str,
    sales_tax: float,
    scrap_efficiency: float,
    include_non_unit_portions: bool,
) -> list[dict[str, object]]:
    hub_location = HUB_LOCATIONS[hub.lower()]
    hub_orders = orders_df[orders_df["location_id"] == hub_location]
    hub_sells = hub_orders[hub_orders["is_buy_order"] == False]

    if hub_sells.empty:
        return []

    type_to_name = dict(zip(types_df["typeID"], types_df["typeName"]))
    type_to_portion = dict(zip(types_df["typeID"], types_df["portionSize"]))
    type_to_group = dict(zip(types_df["typeID"], types_df["groupID"]))
    group_to_category = dict(zip(groups_df["groupID"], groups_df["categoryID"]))

    hub_buys = hub_orders[hub_orders["is_buy_order"] == True]
    best_buy_by_type = hub_buys.groupby("type_id")["price"].max().to_dict()

    items: list[dict[str, object]] = []
    for type_id, sell_orders in hub_sells.groupby("type_id"):
        type_id_int = int(type_id)
        type_name = type_to_name.get(type_id_int)
        if not type_name:
            continue

        portion_size = int(type_to_portion.get(type_id_int, 1))
        if not include_non_unit_portions and portion_size != 1:
            continue

        mat_rows = materials_df[materials_df["typeID"] == type_id_int]
        if mat_rows.empty:
            continue

        group_id = type_to_group.get(type_id_int)
        category_id = group_to_category.get(group_id)
        if group_id == ICE_GROUP:
            continue
        if group_id in GAS_GROUPS:
            continue
        if category_id == ASTEROID_CATEGORY:
            continue

        per_unit_yields: dict[int, int] = {}
        for _, row in mat_rows.iterrows():
            mat_id = int(row["materialTypeID"])
            base_qty = int(row["quantity"])
            output_qty = math.floor(base_qty * scrap_efficiency)
            if output_qty > 0:
                per_unit_yields[mat_id] = output_qty

        if not per_unit_yields:
            continue

        value_per_unit = 0.0
        missing_price = False
        for mat_id, qty in per_unit_yields.items():
            price = best_buy_by_type.get(mat_id)
            if price is None:
                missing_price = True
                break
            value_per_unit += round(float(price), 2) * qty

        if missing_price or value_per_unit <= 0:
            continue

        value_per_unit_after_tax = value_per_unit * (1 - sales_tax)
        max_price = value_per_unit_after_tax / (1 + sales_tax)

        eligible = sell_orders[sell_orders["price"] <= max_price]
        if eligible.empty:
            continue

        quantity = int(eligible["volume_remain"].sum())
        if quantity <= 0:
            continue

        cost = float((eligible["price"] * eligible["volume_remain"]).sum())
        value = value_per_unit_after_tax * quantity
        profit = value - cost * (1 + sales_tax)
        if profit <= 0:
            continue

        roi = (profit / (cost * (1 + sales_tax))) * 100 if cost > 0 else 0.0

        items.append(
            {
                "item": type_name,
                "quantity": quantity,
                "cost": round(cost, 2),
                "value": round(value, 2),
                "profit": round(profit, 2),
                "roi": round(roi, 2),
                "max_price": round(max_price, 2),
            }
        )

    return items


def build_case_payload(
    items: list[dict[str, object]],
    hub: str,
    k: int,
    sort_by: str,
    sales_tax: float,
    scrap_efficiency: float,
    order_index: int,
) -> dict[str, object]:
    sort_key = "roi" if sort_by == "roi" else "profit"
    items = sorted(items, key=lambda item: (-item[sort_key], item["item"]))
    items = items[:k]

    total_cost = round(sum(item["cost"] for item in items), 2)
    total_value = round(sum(item["value"] for item in items), 2)
    total_profit = round(sum(item["profit"] for item in items), 2)

    request = {
        "k": k,
        "hub": hub,
        "sort_by": sort_by,
        "sales_tax": sales_tax,
        "scrap_efficiency": scrap_efficiency,
    }

    return {
        "order": order_index,
        "input": {
            "method": "POST",
            "path": "/v1/profit/reprocess",
            "body": request,
        },
        "expected": {
            "output": {
                "cost": total_cost,
                "revenue": total_value,
                "profit": total_profit,
                "items": items,
            },
            "status_code": 200,
        },
    }


def main() -> None:
    args = parse_args()
    base_dir = Path(__file__).resolve().parents[1]
    market_dir = base_dir / "tests" / "market_data"
    sde_dir = base_dir / "sde"

    orders_df = load_orders(market_dir / "orders.csv.gz")
    materials_df = load_materials(sde_dir / "invTypeMaterials.csv.bz2")
    types_df = load_types(sde_dir / "invTypes.csv.bz2")
    groups_df = load_types(sde_dir / "invGroups.csv.bz2")

    items = build_reprocess_items(
        orders_df=orders_df,
        materials_df=materials_df,
        types_df=types_df,
        groups_df=groups_df,
        hub=args.hub,
        sales_tax=args.sales_tax,
        scrap_efficiency=args.scrap_efficiency,
        include_non_unit_portions=args.include_non_unit_portions,
    )

    payload = build_case_payload(
        items=items,
        hub=args.hub,
        k=args.k,
        sort_by=args.sort_by,
        sales_tax=args.sales_tax,
        scrap_efficiency=args.scrap_efficiency,
        order_index=args.order,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")


if __name__ == "__main__":
    main()
