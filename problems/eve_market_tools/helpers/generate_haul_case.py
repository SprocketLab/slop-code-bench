from __future__ import annotations

import argparse
import bz2
import gzip
import json
import math
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from datetime import timedelta
from pathlib import Path
from typing import Iterable

import pandas as pd

HUB_LOCATIONS = {
    "jita": 60003760,
    "amarr": 60008494,
    "dodixie": 60011866,
    "rens": 60004588,
    "hek": 60005686,
}


@dataclass(frozen=True)
class CandidateOrder:
    metric: float
    item_name: str
    type_id: int
    location_id: int
    system_id: int
    price: float
    volume_remain: int
    volume_per_unit: float
    sell_price: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a hauling case from local market data.",
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
        choices=sorted(HUB_LOCATIONS.keys()),
        help="Destination hub for hauling.",
    )
    parser.add_argument(
        "--capacity",
        type=float,
        default=60000,
        help="Maximum capacity in m3.",
    )
    parser.add_argument(
        "--shipping",
        type=float,
        default=350,
        help="Shipping cost per m3.",
    )
    parser.add_argument(
        "--max-jumps",
        type=int,
        default=5,
        help="Maximum jumps from the hub.",
    )
    parser.add_argument(
        "--margin",
        type=float,
        default=20,
        help="Minimum margin percent required.",
    )
    parser.add_argument(
        "--include-hubs",
        action="store_true",
        help="Include other hubs as purchase sources.",
    )
    parser.add_argument(
        "--daily-value",
        type=float,
        default=1_000_000_000,
        help="Minimum average daily value to include an item.",
    )
    parser.add_argument(
        "--optimize",
        choices=["m3", "roi", "profit"],
        default="m3",
        help="Optimization metric for selecting orders.",
    )
    parser.add_argument(
        "--sales-tax",
        type=float,
        default=0.04,
        help="Sales tax applied to buying and selling.",
    )
    parser.add_argument(
        "--order",
        type=int,
        default=1,
        help="Order index for the case payload.",
    )
    return parser.parse_args()


def round_to_4_sig_digits(price: float, direction: str) -> float:
    if price <= 0:
        return price

    magnitude = math.floor(math.log10(abs(price)))
    step = 10 ** max(0, magnitude - 3)

    if direction == "undercut":
        rounded = math.floor(price / step) * step
        return rounded - step if rounded == price else rounded

    rounded = math.ceil(price / step) * step
    return rounded + step if rounded == price else rounded


def load_orders(path: Path) -> pd.DataFrame:
    with gzip.open(path, "rt") as handle:
        return pd.read_csv(handle)


def load_history(path: Path) -> pd.DataFrame:
    with gzip.open(path, "rt") as handle:
        return pd.read_csv(handle)


def load_stations(path: Path) -> pd.DataFrame:
    with gzip.open(path, "rt") as handle:
        return pd.read_csv(handle)


def load_types(path: Path) -> pd.DataFrame:
    with bz2.open(path, "rt") as handle:
        return pd.read_csv(handle)


def load_system_regions(path: Path) -> dict[int, int]:
    if not path.exists():
        return {}

    with bz2.open(path, "rt") as handle:
        systems_df = pd.read_csv(handle)

    return dict(
        zip(
            systems_df["solarSystemID"].astype(int),
            systems_df["regionID"].astype(int),
        )
    )


def load_jump_graph(path: Path) -> dict[int, set[int]]:
    if not path.exists():
        return {}

    with bz2.open(path, "rt") as handle:
        jumps_df = pd.read_csv(handle)

    graph: dict[int, set[int]] = {}
    for _, row in jumps_df.iterrows():
        from_system = int(row["fromSolarSystemID"])
        to_system = int(row["toSolarSystemID"])
        graph.setdefault(from_system, set()).add(to_system)
        graph.setdefault(to_system, set()).add(from_system)
    return graph


def compute_jump_distances(
    graph: dict[int, set[int]],
    start: int,
    max_jumps: int,
) -> dict[int, int]:
    if not graph:
        return {start: 0}

    distances = {start: 0}
    queue: deque[tuple[int, int]] = deque([(start, 0)])

    while queue:
        node, distance = queue.popleft()
        if distance >= max_jumps:
            continue
        for neighbor in graph.get(node, set()):
            if neighbor in distances:
                continue
            distances[neighbor] = distance + 1
            queue.append((neighbor, distance + 1))

    return distances


def get_effective_timestamp(orders_df: pd.DataFrame) -> datetime:
    issued = pd.to_datetime(orders_df["issued"], utc=False, errors="coerce")
    return issued.max().to_pydatetime()


def compute_competition_metrics(
    orders_df: pd.DataFrame,
    location_id: int,
    type_id: int,
    effective_ts: datetime,
) -> dict[str, int]:
    filtered = orders_df[
        (orders_df["location_id"] == location_id)
        & (orders_df["type_id"] == type_id)
        & (orders_df["is_buy_order"] == False)
    ]

    if filtered.empty:
        return {"5_minutes": 0, "1_hour": 0, "1_day": 0}

    issued = pd.to_datetime(filtered["issued"], utc=False, errors="coerce")
    return {
        "5_minutes": int((issued >= effective_ts - timedelta(minutes=5)).sum()),
        "1_hour": int((issued >= effective_ts - timedelta(minutes=60)).sum()),
        "1_day": int((issued >= effective_ts - timedelta(minutes=1440)).sum()),
    }


def compute_daily_values(
    history_df: pd.DataFrame,
    region_id: int | None,
) -> dict[int, float]:
    if history_df.empty:
        return {}

    if region_id is not None:
        history_df = history_df[history_df["region_id"] == region_id]

    totals = (history_df["average"] * history_df["volume"]).groupby(
        history_df["type_id"]
    )
    return (totals.sum() / 30).to_dict()


def iter_sell_orders(
    orders_df: pd.DataFrame,
    hub_location: int,
    include_hubs: bool,
) -> Iterable[pd.Series]:
    hub_ids = set(HUB_LOCATIONS.values())
    for _, order in orders_df.iterrows():
        if order["is_buy_order"]:
            continue
        location_id = int(order["location_id"])
        if location_id == hub_location:
            continue
        if not include_hubs and location_id in hub_ids:
            continue
        yield order


def build_candidates(
    orders_df: pd.DataFrame,
    history_df: pd.DataFrame,
    types_df: pd.DataFrame,
    system_regions: dict[int, int],
    jump_graph: dict[int, set[int]],
    hub: str,
    include_hubs: bool,
    shipping: float,
    margin: float,
    daily_value: float,
    max_jumps: int,
    optimize: str,
    sales_tax: float,
) -> tuple[list[CandidateOrder], int]:
    hub_location = HUB_LOCATIONS[hub]
    hub_orders = orders_df[orders_df["location_id"] == hub_location]
    if hub_orders.empty:
        raise ValueError(f"No orders found for hub {hub}.")

    hub_system = int(hub_orders["system_id"].iloc[0])
    hub_region = system_regions.get(hub_system)

    daily_values = compute_daily_values(history_df, hub_region)

    hub_sells = hub_orders[hub_orders["is_buy_order"] == False]
    sell_price_map = hub_sells.groupby("type_id")["price"].min().to_dict()

    type_to_name = dict(
        zip(types_df["typeID"].astype(int), types_df["typeName"])
    )
    type_to_volume = dict(
        zip(types_df["typeID"].astype(int), types_df["volume"])
    )

    jumps = compute_jump_distances(jump_graph, hub_system, max_jumps)

    candidates: list[CandidateOrder] = []
    for order in iter_sell_orders(orders_df, hub_location, include_hubs):
        type_id = int(order["type_id"])
        if type_id not in sell_price_map:
            continue
        if daily_values.get(type_id, 0.0) < daily_value:
            continue
        system_id = int(order["system_id"])
        if system_id not in jumps:
            continue

        item_name = type_to_name.get(type_id)
        if not item_name:
            continue

        sell_price = round_to_4_sig_digits(
            float(sell_price_map[type_id]),
            "undercut",
        )

        buy_price = float(order["price"])
        unit_volume = float(type_to_volume.get(type_id, 1.0))
        if unit_volume <= 0:
            continue

        shipping_unit = shipping * unit_volume
        margin_pct = (sell_price - buy_price - shipping_unit) / buy_price * 100
        if margin_pct < margin:
            continue

        profit_unit = (
            sell_price * (1 - sales_tax)
            - buy_price * (1 + sales_tax)
            - shipping_unit
        )
        if profit_unit <= 0:
            continue

        if optimize == "profit":
            metric = profit_unit * int(order["volume_remain"])
        elif optimize == "roi":
            denom = buy_price * (1 + sales_tax) + shipping_unit
            metric = (profit_unit / denom) * 100 if denom > 0 else 0.0
        else:
            metric = profit_unit / unit_volume

        candidates.append(
            CandidateOrder(
                metric=metric,
                item_name=item_name,
                type_id=type_id,
                location_id=int(order["location_id"]),
                system_id=system_id,
                price=buy_price,
                volume_remain=int(order["volume_remain"]),
                volume_per_unit=unit_volume,
                sell_price=sell_price,
            )
        )

    candidates.sort(key=lambda item: (-item.metric, item.item_name))
    return candidates, hub_location


def build_case_payload(
    candidates: list[CandidateOrder],
    stations_df: pd.DataFrame,
    orders_df: pd.DataFrame,
    hub_location: int,
    capacity: float,
    shipping: float,
    sales_tax: float,
    request: dict[str, object],
    order_index: int,
) -> dict[str, object]:
    station_names = dict(
        zip(
            stations_df["location_id"].astype(int),
            stations_df["name"].astype(str),
        )
    )

    effective_ts = get_effective_timestamp(orders_df)
    remaining_capacity = capacity
    purchases: dict[str, list[dict[str, object]]] = {}
    sales: dict[str, dict[str, object]] = {}
    total_cost = 0.0

    for candidate in candidates:
        if remaining_capacity <= 0:
            break
        unit_volume = candidate.volume_per_unit
        if unit_volume <= 0:
            continue
        max_units = (
            math.floor(remaining_capacity / unit_volume)
            if capacity > 0
            else candidate.volume_remain
        )
        quantity = min(candidate.volume_remain, max_units)
        if quantity <= 0:
            continue

        remaining_capacity -= quantity * unit_volume
        total = round(candidate.price * quantity, 2)
        total_cost += total

        station_name = station_names.get(
            candidate.location_id,
            str(candidate.location_id),
        )
        purchases.setdefault(station_name, []).append(
            {
                "item": candidate.item_name,
                "quantity": int(quantity),
                "total": total,
            }
        )

        if candidate.item_name not in sales:
            sales[candidate.item_name] = {
                "sell_price": candidate.sell_price,
                "total": 0,
                "volume": 0.0,
                "revenue": 0.0,
                "competition": compute_competition_metrics(
                    orders_df,
                    hub_location,
                    candidate.type_id,
                    effective_ts,
                ),
            }

        sales_entry = sales[candidate.item_name]
        sales_entry["total"] = int(sales_entry["total"]) + int(quantity)
        sales_entry["volume"] = round(
            float(sales_entry["volume"]) + quantity * unit_volume,
            2,
        )
        sales_entry["revenue"] = round(
            int(sales_entry["total"])
            * candidate.sell_price
            * (1 - sales_tax),
            2,
        )

    revenue = round(sum(item["revenue"] for item in sales.values()), 2)
    total_volume = sum(item["volume"] for item in sales.values())
    shipping_cost = total_volume * shipping
    profit = round(revenue - total_cost * (1 + sales_tax) - shipping_cost, 2)

    payload = {
        "order": order_index,
        "input": {
            "method": "GET",
            "path": "/v1/profit/haul",
            "query": request,
        },
        "expected": {
            "output": {
                "cost": round(total_cost, 2),
                "revenue": revenue,
                "profit": profit,
                "purchases": purchases,
                "sales": sales,
            },
            "status_code": 200,
        },
    }
    return payload


def main() -> None:
    args = parse_args()
    base_dir = Path(__file__).resolve().parents[1]

    market_dir = base_dir / "tests" / "market_data"
    sde_dir = base_dir / "sde"

    orders_df = load_orders(market_dir / "orders.csv.gz")
    history_df = load_history(market_dir / "history.csv.gz")
    stations_df = load_stations(market_dir / "stations.csv.gz")
    types_df = load_types(sde_dir / "invTypes.csv.bz2")
    system_regions = load_system_regions(sde_dir / "mapSolarSystems.csv.bz2")
    jump_graph = load_jump_graph(sde_dir / "mapSolarSystemJumps.csv.bz2")

    candidates, hub_location = build_candidates(
        orders_df=orders_df,
        history_df=history_df,
        types_df=types_df,
        system_regions=system_regions,
        jump_graph=jump_graph,
        hub=args.hub,
        include_hubs=args.include_hubs,
        shipping=args.shipping,
        margin=args.margin,
        daily_value=args.daily_value,
        max_jumps=args.max_jumps,
        optimize=args.optimize,
        sales_tax=args.sales_tax,
    )

    request = {
        "optimize": args.optimize,
        "hub": args.hub,
        "capacity": args.capacity,
        "shipping": args.shipping,
        "margin": args.margin,
        "include_hubs": args.include_hubs,
        "daily_value": args.daily_value,
        "sales_tax": args.sales_tax,
        "max_jumps": args.max_jumps,
    }

    payload = build_case_payload(
        candidates=candidates,
        stations_df=stations_df,
        orders_df=orders_df,
        hub_location=hub_location,
        capacity=args.capacity,
        shipping=args.shipping,
        sales_tax=args.sales_tax,
        request=request,
        order_index=args.order,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")


if __name__ == "__main__":
    main()
