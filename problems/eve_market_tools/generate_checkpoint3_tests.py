#!/usr/bin/env python3
"""Generate test cases for checkpoint 3 of eve_market_tools.

This script uses the optimizer.py module to generate accurate expected
outputs for various test case configurations.
"""
from __future__ import annotations

import json
import shutil
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from optimizer import HUB_LOCATIONS
from optimizer import HUB_STATION_NAMES
from optimizer import NumpyEncoder
from optimizer import build_candidates
from optimizer import build_ore_variant_map
from optimizer import filter_to_hubs
from optimizer import get_output_material_prices
from optimizer import load_market_data
from optimizer import load_sde_file
from optimizer import load_stations_data
from optimizer import optimize_purchases
from optimizer import parse_materials

BASE_DIR = Path(__file__).parent
SDE_PATH = BASE_DIR / "sde"
MARKET_DATA = BASE_DIR / "orders.csv.gz"
CHECKPOINT_DIR = BASE_DIR / "checkpoint_3"


@dataclass
class TestConfig:
    """Configuration for a single test case."""
    name: str
    materials: dict[str, int]
    hubs: list[str]
    order: int
    cost_weight: float = 1.0
    overage_weight: float = 0.1
    cost_per_m3: float = 350.0
    collateral_tax: float = 0.0
    efficiencies: dict[str, float] | None = None
    ore_variants: dict[str, bool] | None = None
    include_scrap: bool = True
    drill_down: bool = True
    regions: list[str] | None = None
    sales_tax: float = 0.02


def get_default_efficiencies() -> dict[str, float]:
    return {"ore": 0.9063, "gas": 0.95, "scrap": 0.55}


def get_default_ore_variants() -> dict[str, bool]:
    return {"base": True, "plus5": True, "plus10": True, "plus15": True}


def generate_test_case(
    config: TestConfig,
    orders_df: pd.DataFrame,
    types_df: pd.DataFrame,
    groups_df: pd.DataFrame,
    materials_df: pd.DataFrame,
    ore_variant_map: dict[int, str],
    station_names: dict[int, str],
) -> dict:
    """Generate a single test case from configuration."""
    efficiencies = config.efficiencies or get_default_efficiencies()
    ore_variants = config.ore_variants or get_default_ore_variants()
    regions = config.regions or []

    # Filter orders to hubs
    filtered_orders = filter_to_hubs(orders_df, config.hubs)

    # Parse targets
    targets = parse_materials(config.materials, types_df)

    if not targets:
        raise ValueError(f"No valid targets for test {config.name}")

    # Build allowed ore variants
    allowed_ore_variants = {k for k, v in ore_variants.items() if v}

    # Build candidates
    candidates = build_candidates(
        set(targets.keys()),
        filtered_orders,
        types_df,
        groups_df,
        materials_df,
        ore_variant_map=ore_variant_map,
        allowed_ore_variants=allowed_ore_variants,
        include_scrap=config.include_scrap,
        drill_down=config.drill_down,
    )

    if not candidates:
        raise ValueError(f"No candidates found for test {config.name}")

    # Run optimization
    result = optimize_purchases(
        targets=targets,
        candidates=candidates,
        efficiencies=efficiencies,
        cost_weight=config.cost_weight,
        overage_weight=config.overage_weight,
        shipping_rate=config.cost_per_m3,
        types_df=types_df,
    )

    if result.status != "Optimal":
        raise ValueError(f"Optimization failed for {config.name}: {result.status}")

    # Build buy_list output
    buy_list: dict[str, dict] = {}
    items_cost = 0.0
    input_volume = 0.0

    for purchase in result.purchases:
        name = purchase["name"]
        cost = purchase["total_price"]
        volume = purchase["volume"]
        items_cost += cost
        input_volume += volume

        # Aggregate purchases by station
        station_totals: dict[str, dict] = defaultdict(lambda: {"quantity": 0, "total": 0.0})
        for tier in purchase.get("price_breakdown", []):
            hub_key = tier.get("hub", "unknown")
            station_id = HUB_LOCATIONS.get(hub_key)
            location = station_names.get(station_id, hub_key) if station_id else hub_key
            station_totals[location]["quantity"] += tier["quantity"]
            station_totals[location]["total"] += tier["subtotal"]

        purchases: dict[str, dict] = {}
        for station, data in station_totals.items():
            purchases[station] = {
                "quantity": data["quantity"],
                "total": round(data["total"], 2),
                "avg_price": round(data["total"] / data["quantity"], 2) if data["quantity"] > 0 else 0,
            }

        buy_list[name] = {
            "quantity": purchase["quantity"],
            "cost": cost,
            "volume": volume,
            "category": purchase["category"],
            "purchases": purchases,
        }

    # Calculate financial fields
    shipping_amount = round(input_volume * config.cost_per_m3, 2)
    collateral_tax_amount = round(items_cost * config.collateral_tax, 2)
    total = round(items_cost + shipping_amount + collateral_tax_amount, 2)

    # Calculate yields with prices
    yields_dict: dict[str, dict] = {}
    raw_total = 0.0
    output_volume = 0.0

    for mat_name, yield_data in result.yields.items():
        type_id = yield_data["type_id"]
        actual = yield_data["actual"]

        buy_value, sell_value = get_output_material_prices(type_id, actual, filtered_orders)

        type_row = types_df[types_df["typeID"] == type_id]
        mat_volume = float(type_row.iloc[0].get("volume", 0)) if not type_row.empty else 0
        output_volume += mat_volume * actual

        if sell_value is not None:
            raw_total += sell_value

        yields_dict[mat_name] = {
            "target": yield_data["target"],
            "actual": actual,
            "buy": buy_value,
            "sell": sell_value,
        }

    raw_ship = round(
        (output_volume * config.cost_per_m3) + (raw_total * config.collateral_tax),
        2
    )
    raw_total = round(raw_total, 2)
    profit = round((raw_total + raw_ship) - total, 2)
    roi = round((profit / total) * 100, 2) if total > 0 else 0.0

    # Build output
    output = {
        "buy_list": buy_list,
        "total": total,
        "shipping": shipping_amount,
        "collateral_tax": collateral_tax_amount,
        "items": round(items_cost, 2),
        "raw_ship": raw_ship,
        "raw_total": raw_total,
        "profit": profit,
        "roi": roi,
        "yields": yields_dict,
        "parameters": {
            "hubs": config.hubs,
            "regions": regions,
            "shipping_rate": config.cost_per_m3,
            "cost_weight": config.cost_weight,
            "overage_weight": config.overage_weight,
            "efficiencies": efficiencies,
            "ore_variants": ore_variants,
            "include_scrap": config.include_scrap,
            "drill_down": config.drill_down,
        },
    }

    # Build input
    input_body = {
        "materials": config.materials,
        "hubs": config.hubs,
        "regions": regions,
        "cost_weight": config.cost_weight,
        "overage_weight": config.overage_weight,
        "sales_tax": config.sales_tax,
        "cost_per_m3": config.cost_per_m3,
        "collateral_tax": config.collateral_tax,
        "efficiencies": efficiencies,
        "drill_down": config.drill_down,
        "ore_variants": ore_variants,
        "include_scrap": config.include_scrap,
    }

    return {
        "expected": {
            "output": output,
            "status_code": 200,
        },
        "input": {
            "body": input_body,
            "method": "POST",
            "path": "/v1/compress",
        },
        "order": config.order,
    }


def get_core_test_configs() -> list[TestConfig]:
    """Define core test configurations."""
    return [
        # Test 1: Single hub (Jita only) with Tritanium target
        TestConfig(
            name="jita_only",
            materials={"Tritanium": 500000},
            hubs=["jita"],
            order=4,
        ),
        # Test 2: Multiple material targets
        TestConfig(
            name="multi_material",
            materials={"Pyerite": 100000, "Mexallon": 50000},
            hubs=["jita", "amarr"],
            order=5,
        ),
        # Test 3: Limited ore variants (base only)
        TestConfig(
            name="ore_variants_limited",
            materials={"Tritanium": 1000000},
            hubs=["jita", "amarr"],
            ore_variants={"base": True, "plus5": False, "plus10": False, "plus15": False},
            order=6,
        ),
        # Test 4: Exclude scrap items
        TestConfig(
            name="no_scrap",
            materials={"Pyerite": 500000},
            hubs=["jita", "amarr", "dodixie"],
            include_scrap=False,
            order=7,
        ),
        # Test 5: Higher overage weight
        TestConfig(
            name="high_overage_weight",
            materials={"Mexallon": 200000},
            hubs=["jita", "amarr"],
            cost_weight=0.5,
            overage_weight=1.0,
            order=8,
        ),
        # Test 6: Drill down with ore targets (already default)
        TestConfig(
            name="drill_down_ore",
            materials={"Isogen": 100000},
            hubs=["jita"],
            drill_down=True,
            order=9,
        ),
        # Test 7: Custom efficiencies
        TestConfig(
            name="custom_efficiencies",
            materials={"Nocxium": 10000},
            hubs=["jita", "amarr"],
            efficiencies={"ore": 0.85, "gas": 0.90, "scrap": 0.50},
            order=10,
        ),
    ]


def get_hidden_test_configs() -> list[TestConfig]:
    """Define hidden test configurations."""
    return [
        # Test 2: Less common hubs (Dodixie + Rens)
        TestConfig(
            name="dodixie_rens",
            materials={"Pyerite": 250000},
            hubs=["dodixie", "rens"],
            order=2,
        ),
        # Test 3: Basic mineral target with all hubs
        TestConfig(
            name="all_hubs_pyerite",
            materials={"Pyerite": 1000000},
            hubs=["jita", "amarr", "dodixie", "rens", "hek"],
            order=3,
        ),
        # Test 4: Gas target (Hydrocarbons via gas)
        TestConfig(
            name="gas_target",
            materials={"Nitrogen Isotopes": 50000},
            hubs=["jita", "amarr"],
            order=4,
        ),
        # Test 5: Single variant (plus15 only)
        TestConfig(
            name="plus15_only",
            materials={"Tritanium": 500000},
            hubs=["jita"],
            ore_variants={"base": False, "plus5": False, "plus10": False, "plus15": True},
            order=5,
        ),
        # Test 6: Large quantity
        TestConfig(
            name="large_quantity",
            materials={"Tritanium": 10000000},
            hubs=["jita", "amarr"],
            order=6,
        ),
        # Test 7: Low cost weight (prioritize overage)
        TestConfig(
            name="low_cost_weight",
            materials={"Mexallon": 100000},
            hubs=["jita"],
            cost_weight=0.1,
            overage_weight=1.0,
            order=7,
        ),
        # Test 8: Mixed category (ore + scrap materials)
        TestConfig(
            name="mixed_category",
            materials={"Pyerite": 100000, "Zydrine": 5000},
            hubs=["jita", "amarr"],
            order=8,
        ),
        # Test 9: With collateral tax
        TestConfig(
            name="collateral_tax",
            materials={"Mexallon": 150000},
            hubs=["jita", "amarr"],
            collateral_tax=0.02,
            order=9,
        ),
        # Test 10: Higher shipping rate
        TestConfig(
            name="high_shipping",
            materials={"Tritanium": 500000},
            hubs=["jita"],
            cost_per_m3=1000.0,
            order=10,
        ),
        # Test 11: Only plus5 variants
        TestConfig(
            name="plus5_only",
            materials={"Tritanium": 500000},
            hubs=["jita"],
            ore_variants={"base": False, "plus5": True, "plus10": False, "plus15": False},
            order=11,
        ),
        # Test 12: Only plus10 variants
        TestConfig(
            name="plus10_only",
            materials={"Pyerite": 300000},
            hubs=["amarr"],
            ore_variants={"base": False, "plus5": False, "plus10": True, "plus15": False},
            order=12,
        ),
        # Test 13: Rens single hub
        TestConfig(
            name="rens_single",
            materials={"Tritanium": 200000},
            hubs=["rens"],
            order=13,
        ),
        # Test 14: Hek single hub
        TestConfig(
            name="hek_single",
            materials={"Pyerite": 150000},
            hubs=["hek"],
            order=14,
        ),
        # Test 15: Hub case sensitivity (mixed case)
        TestConfig(
            name="hub_case_mixed",
            materials={"Tritanium": 100000},
            hubs=["JiTa", "AMARR"],
            order=15,
        ),
        # Test 16: Zero shipping cost
        TestConfig(
            name="zero_shipping",
            materials={"Mexallon": 100000},
            hubs=["jita"],
            cost_per_m3=0.0,
            order=16,
        ),
        # Test 17: Small quantity (near portion boundary)
        TestConfig(
            name="small_quantity",
            materials={"Tritanium": 1000},
            hubs=["jita"],
            order=17,
        ),
    ]


def main():
    print("Loading SDE data...")
    types_df = load_sde_file(SDE_PATH / "invTypes.csv.bz2")
    groups_df = load_sde_file(SDE_PATH / "invGroups.csv.bz2")
    materials_df = load_sde_file(SDE_PATH / "invTypeMaterials.csv.bz2")
    stations_df = load_stations_data(SDE_PATH)

    print("Loading market data...")
    orders_df = load_market_data(MARKET_DATA)

    print("Building ore variant map...")
    ore_variant_map = build_ore_variant_map(types_df, groups_df, materials_df)

    # Build station names lookup
    station_names: dict[int, str] = {}
    for hub_name, station_id in HUB_LOCATIONS.items():
        station_names[station_id] = HUB_STATION_NAMES.get(hub_name, f"Station {station_id}")
    if not stations_df.empty:
        sde_stations = stations_df.set_index('stationID')['stationName'].to_dict()
        for sid, sname in sde_stations.items():
            station_names.setdefault(int(sid), str(sname))

    # Generate core tests
    print("\nGenerating core tests...")
    core_dir = CHECKPOINT_DIR / "core"
    core_configs = get_core_test_configs()

    for config in core_configs:
        print(f"  Generating {config.name}...")
        try:
            test_case = generate_test_case(
                config, orders_df, types_df, groups_df, materials_df,
                ore_variant_map, station_names,
            )
            output_path = core_dir / f"{config.name}.json"
            with open(output_path, "w") as f:
                json.dump(test_case, f, indent=2, cls=NumpyEncoder)
            print(f"    Written to {output_path}")
        except Exception as e:
            print(f"    ERROR: {e}")

    # Generate hidden tests
    print("\nGenerating hidden tests...")
    hidden_dir = CHECKPOINT_DIR / "hidden"
    hidden_configs = get_hidden_test_configs()

    # Copy upload_prices.json first
    print("  Copying upload_prices.json...")
    src_upload = core_dir / "upload_prices.json"
    dst_upload = hidden_dir / "upload_prices.json"
    if src_upload.exists():
        shutil.copy(src_upload, dst_upload)
        print(f"    Copied to {dst_upload}")

    for config in hidden_configs:
        print(f"  Generating {config.name}...")
        try:
            test_case = generate_test_case(
                config, orders_df, types_df, groups_df, materials_df,
                ore_variant_map, station_names,
            )
            output_path = hidden_dir / f"{config.name}.json"
            with open(output_path, "w") as f:
                json.dump(test_case, f, indent=2, cls=NumpyEncoder)
            print(f"    Written to {output_path}")
        except Exception as e:
            print(f"    ERROR: {e}")

    print("\nDone!")


if __name__ == "__main__":
    main()
