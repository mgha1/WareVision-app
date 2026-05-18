#!/usr/bin/env python3

"""Seed warehouse demo data into Oracle via SQLcl."""

import datetime
import random

from warehouse_api.config import Settings
from warehouse_api.database import SqlclDatabase, sql_literal


GRID_WIDTH = 800
GRID_HEIGHT = 600
TOTAL_AISLES = 10
TOTAL_BAYS = 20
TOTAL_SKUS = 150
TOTAL_PICKS = 2000
BATCH_SIZE = 200
RANDOM_SEED = 42

FAST_ZONE_ID = "Z_FAST"
BULK_ZONE_ID = "Z_BULK"
DISPATCH_ZONE_ID = "Z_DISP"


def sql_number(value, precision=2):
    fmt = "{0:." + str(precision) + "f}"
    return fmt.format(float(value))


def chunked(items, size):
    for index in range(0, len(items), size):
        yield items[index : index + size]


def zone_lookup(db):
    rows = db.fetch_all(
        """
        SELECT
            zone_id,
            zone_name,
            zone_type,
            x1,
            y1,
            x2,
            y2
        FROM warehouse_zones
        ORDER BY zone_id
        """
    )
    return {row["zone_id"]: row for row in rows}


def build_slot_records(zones):
    records = []
    fast_zone = zones[FAST_ZONE_ID]
    bulk_zone = zones[BULK_ZONE_ID]

    fast_aisles = 3
    bulk_aisles = TOTAL_AISLES - fast_aisles

    fast_width = float(fast_zone["x2"]) - float(fast_zone["x1"])
    fast_height = float(fast_zone["y2"]) - float(fast_zone["y1"])
    bulk_width = float(bulk_zone["x2"]) - float(bulk_zone["x1"])
    bulk_height = float(bulk_zone["y2"]) - float(bulk_zone["y1"])

    fast_slot_width = max(12.0, (fast_width / fast_aisles) * 0.58)
    fast_slot_height = max(8.0, (fast_height / TOTAL_BAYS) * 0.50)
    bulk_slot_width = max(16.0, (bulk_width / bulk_aisles) * 0.54)
    bulk_slot_height = max(8.0, (bulk_height / TOTAL_BAYS) * 0.48)

    for aisle_index in range(TOTAL_AISLES):
        zone_id = FAST_ZONE_ID if aisle_index < fast_aisles else BULK_ZONE_ID
        if zone_id == FAST_ZONE_ID:
            local_aisle = aisle_index
            step_x = fast_width / fast_aisles
            step_y = fast_height / TOTAL_BAYS
            x = float(fast_zone["x1"]) + (local_aisle * step_x) + ((step_x - fast_slot_width) / 2.0)
            slot_width = fast_slot_width
            slot_height = fast_slot_height
            zone_top = float(fast_zone["y1"])
        else:
            local_aisle = aisle_index - fast_aisles
            step_x = bulk_width / bulk_aisles
            step_y = bulk_height / TOTAL_BAYS
            x = float(bulk_zone["x1"]) + (local_aisle * step_x) + ((step_x - bulk_slot_width) / 2.0)
            slot_width = bulk_slot_width
            slot_height = bulk_slot_height
            zone_top = float(bulk_zone["y1"])

        aisle_label = "A{0:02d}".format(aisle_index + 1)
        for bay_index in range(TOTAL_BAYS):
            y = zone_top + (bay_index * step_y) + ((step_y - slot_height) / 2.0)
            level = 1 if bay_index < 10 else 2
            slot_id = "SL-{0}-{1:02d}".format(aisle_label, bay_index + 1)
            records.append(
                {
                    "slot_id": slot_id,
                    "zone_id": zone_id,
                    "aisle": aisle_label,
                    "bay": bay_index + 1,
                    "level": level,
                    "x": round(x, 2),
                    "y": round(y, 2),
                    "width": round(slot_width, 2),
                    "height": round(slot_height, 2),
                    "capacity_kg": 400 if zone_id == FAST_ZONE_ID else 1200,
                    "is_occupied": 0,
                }
            )
    return records


def build_inventory_records(slot_records, rng):
    fast_slots = [slot for slot in slot_records if slot["zone_id"] == FAST_ZONE_ID]
    bulk_slots = [slot for slot in slot_records if slot["zone_id"] == BULK_ZONE_ID]

    # Deliberately place more active SKUs in bulk to create visible misplacement.
    assigned_slots = bulk_slots[:100] + fast_slots[:50]
    records = []
    for sku_index in range(TOTAL_SKUS):
        slot = assigned_slots[sku_index]
        quantity = rng.randint(8, 160) if slot["zone_id"] == BULK_ZONE_ID else rng.randint(3, 48)
        sku_id = "SKU-{0:03d}".format(sku_index + 1)
        records.append(
            {
                "seed_index": sku_index + 1,
                "sku_id": sku_id,
                "sku_name": "Demo SKU {0:03d}".format(sku_index + 1),
                "slot_id": slot["slot_id"],
                "quantity": quantity,
                "weight_kg": round(rng.uniform(2.5, 35.0), 2),
                "category": "BULK" if slot["zone_id"] == BULK_ZONE_ID else "FAST",
                "zone_id": slot["zone_id"],
            }
        )
        slot["is_occupied"] = 1
    return records


def build_pick_history_records(inventory_records, zones, rng):
    dispatch_zone = zones[DISPATCH_ZONE_ID]
    dispatch_x = (float(dispatch_zone["x1"]) + float(dispatch_zone["x2"])) / 2.0
    dispatch_y = (float(dispatch_zone["y1"]) + float(dispatch_zone["y2"])) / 2.0

    weighted_inventory = []
    for record in inventory_records:
        weight = 5 if record["zone_id"] == BULK_ZONE_ID else 1
        weighted_inventory.extend([record] * weight)

    now = datetime.datetime.utcnow()
    records = []
    for pick_id in range(1, TOTAL_PICKS + 1):
        item = rng.choice(weighted_inventory)
        picked_at = now - datetime.timedelta(
            days=rng.uniform(0, 30),
            hours=rng.uniform(0, 24),
            minutes=rng.uniform(0, 60),
        )
        aisle_number = int(item["slot_id"].split("-")[1][1:])
        bay_number = int(item["slot_id"].split("-")[2])
        distance_bias = abs(dispatch_x - aisle_number * 12.5) + abs(dispatch_y - bay_number * 12.0)
        records.append(
            {
                "seed_pick_id": pick_id,
                "sku_id": item["sku_id"],
                "slot_id": item["slot_id"],
                "picked_at": picked_at,
                "picker_id": "PKR-{0:02d}".format(rng.randint(1, 12)),
                "distance_m": round(max(6.0, distance_bias / 10.0 + rng.uniform(0.5, 8.0)), 2),
            }
        )
    return records


def build_asset_positions():
    return [
        {"asset_id": "FLT-01", "asset_type": "FORKLIFT", "x": 120, "y": 82, "status": "IDLE"},
        {"asset_id": "FLT-02", "asset_type": "FORKLIFT", "x": 328, "y": 468, "status": "MOVING"},
        {"asset_id": "FLT-03", "asset_type": "FORKLIFT", "x": 610, "y": 236, "status": "PICKING"},
    ]


def reset_statements():
    return [
        "DELETE FROM slotting_recommendations",
        "DELETE FROM pick_history",
        "DELETE FROM inventory",
        "DELETE FROM asset_positions",
        "DELETE FROM slots",
        "COMMIT",
    ]


def slot_insert_sql(slot):
    return """
    INSERT INTO slots (
        slot_id,
        aisle,
        bay,
        "LEVEL",
        zone_id,
        x,
        y,
        width,
        height,
        capacity_kg,
        is_occupied
    ) VALUES (
        {slot_id},
        {aisle},
        {bay},
        {level},
        {zone_id},
        {x},
        {y},
        {width},
        {height},
        {capacity_kg},
        {is_occupied}
    )
    """.format(
        slot_id=sql_literal(slot["slot_id"]),
        aisle=sql_literal(slot["aisle"]),
        bay=int(slot["bay"]),
        level=int(slot["level"]),
        zone_id=sql_literal(slot["zone_id"]),
        x=sql_number(slot["x"]),
        y=sql_number(slot["y"]),
        width=sql_number(slot["width"]),
        height=sql_number(slot["height"]),
        capacity_kg=sql_number(slot["capacity_kg"]),
        is_occupied=int(slot["is_occupied"]),
    )


def inventory_insert_sql(record):
    return """
    INSERT INTO inventory (
        sku_id,
        sku_name,
        slot_id,
        quantity,
        weight_kg,
        placed_at,
        category
    ) VALUES (
        {sku_id},
        {sku_name},
        {slot_id},
        {quantity},
        {weight_kg},
        SYSTIMESTAMP - NUMTODSINTERVAL({age_hours}, 'HOUR'),
        {category}
    )
    """.format(
        sku_id=sql_literal(record["sku_id"]),
        sku_name=sql_literal(record["sku_name"]),
        slot_id=sql_literal(record["slot_id"]),
        quantity=int(record["quantity"]),
        weight_kg=sql_number(record["weight_kg"]),
        age_hours=sql_number((record["seed_index"] % 72) + 1),
        category=sql_literal(record["category"]),
    )


def pick_history_insert_sql(record):
    timestamp = record["picked_at"].strftime("%Y-%m-%d %H:%M:%S")
    return """
    INSERT INTO pick_history (
        sku_id,
        slot_id,
        picked_at,
        picker_id,
        distance_m
    ) VALUES (
        {sku_id},
        {slot_id},
        TO_TIMESTAMP({picked_at}, 'YYYY-MM-DD HH24:MI:SS'),
        {picker_id},
        {distance_m}
    )
    """.format(
        sku_id=sql_literal(record["sku_id"]),
        slot_id=sql_literal(record["slot_id"]),
        picked_at=sql_literal(timestamp),
        picker_id=sql_literal(record["picker_id"]),
        distance_m=sql_number(record["distance_m"]),
    )


def asset_insert_sql(asset):
    return """
    INSERT INTO asset_positions (
        asset_id,
        asset_type,
        x,
        y,
        status,
        updated_at
    ) VALUES (
        {asset_id},
        {asset_type},
        {x},
        {y},
        {status},
        SYSTIMESTAMP
    )
    """.format(
        asset_id=sql_literal(asset["asset_id"]),
        asset_type=sql_literal(asset["asset_type"]),
        x=sql_number(asset["x"]),
        y=sql_number(asset["y"]),
        status=sql_literal(asset["status"]),
    )


def execute_batched(db, statements):
    for batch in chunked(statements, BATCH_SIZE):
        db.execute_script(batch + ["COMMIT"])


def main():
    rng = random.Random(RANDOM_SEED)
    settings = Settings()
    db = SqlclDatabase(settings)

    zones = zone_lookup(db)
    missing = [zone_id for zone_id in (FAST_ZONE_ID, BULK_ZONE_ID, DISPATCH_ZONE_ID) if zone_id not in zones]
    if missing:
        raise RuntimeError("Required warehouse zones are missing: {0}".format(", ".join(missing)))

    slot_records = build_slot_records(zones)
    inventory_records = build_inventory_records(slot_records, rng)
    pick_history_records = build_pick_history_records(inventory_records, zones, rng)
    assets = build_asset_positions()

    db.execute_script(reset_statements())
    execute_batched(db, [slot_insert_sql(slot) for slot in slot_records])
    execute_batched(db, [inventory_insert_sql(record) for record in inventory_records])
    execute_batched(db, [pick_history_insert_sql(record) for record in pick_history_records])
    execute_batched(db, [asset_insert_sql(asset) for asset in assets])

    print("Seed complete")
    print("Slots inserted: {0}".format(len(slot_records)))
    print("Inventory rows inserted: {0}".format(len(inventory_records)))
    print("Pick history rows inserted: {0}".format(len(pick_history_records)))
    print("Asset positions inserted: {0}".format(len(assets)))


if __name__ == "__main__":
    main()
