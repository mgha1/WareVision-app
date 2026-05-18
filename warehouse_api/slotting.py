import logging
import math

from apscheduler.schedulers.background import BackgroundScheduler

from warehouse_api.config import Settings
from warehouse_api.database import SqlclDatabase, sql_literal

LOGGER = logging.getLogger(__name__)


def sql_number(value):
    return "{0:.6f}".format(float(value))


def slot_center(slot):
    x = float(slot.get("x") or 0)
    y = float(slot.get("y") or 0)
    width = float(slot.get("width") or 0)
    height = float(slot.get("height") or 0)
    return (x + (width / 2.0), y + (height / 2.0))


def euclidean_distance(point_a, point_b):
    return math.sqrt(
        ((point_a[0] - point_b[0]) ** 2) + ((point_a[1] - point_b[1]) ** 2)
    )


def fetch_dispatch_dock(db):
    zone = db.fetch_one(
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
        WHERE UPPER(zone_type) = 'DISPATCH'
           OR UPPER(zone_name) = 'DISPATCH'
        ORDER BY zone_id
        FETCH FIRST 1 ROWS ONLY
        """
    )
    if zone is None:
        raise RuntimeError("Dispatch zone not found")
    return (
        (float(zone["x1"] or 0) + float(zone["x2"] or 0)) / 2.0,
        (float(zone["y1"] or 0) + float(zone["y2"] or 0)) / 2.0,
    )


def fetch_pick_frequencies(db):
    rows = db.fetch_all(
        """
        SELECT
            sku_id,
            COUNT(*) AS pick_frequency
        FROM pick_history
        WHERE picked_at >= SYSTIMESTAMP - INTERVAL '30' DAY
        GROUP BY sku_id
        """
    )
    return {
        row["sku_id"]: int(row["pick_frequency"] or 0)
        for row in rows
        if row.get("sku_id")
    }


def fetch_current_inventory_positions(db):
    return db.fetch_all(
        """
        SELECT
            sku_id,
            sku_name,
            slot_id AS from_slot,
            x,
            y,
            width,
            height,
            quantity
        FROM (
            SELECT
                i.sku_id,
                i.sku_name,
                i.slot_id,
                s.x,
                s.y,
                s.width,
                s.height,
                i.quantity,
                ROW_NUMBER() OVER (
                    PARTITION BY i.sku_id
                    ORDER BY i.quantity DESC NULLS LAST,
                             i.placed_at DESC NULLS LAST,
                             i.inv_id DESC
                ) AS row_num
            FROM inventory i
            JOIN slots s
                ON s.slot_id = i.slot_id
        )
        WHERE row_num = 1
        """
    )


def fetch_empty_fast_pick_slots(db):
    return db.fetch_all(
        """
        SELECT
            s.slot_id,
            s.x,
            s.y,
            s.width,
            s.height
        FROM slots s
        JOIN warehouse_zones z
            ON z.zone_id = s.zone_id
        LEFT JOIN inventory i
            ON i.slot_id = s.slot_id
        WHERE UPPER(z.zone_name) = 'FAST-PICK'
          AND NVL(s.is_occupied, 0) = 0
          AND i.slot_id IS NULL
        ORDER BY s.slot_id
        """
    )


def build_reason(item, slot, saving):
    return (
        "Move SKU {sku_id} from {from_slot} to {to_slot}. "
        "Pick frequency {pick_frequency}/30d, waste score {waste_score:.2f}, "
        "estimated daily saving {saving:.2f}m."
    ).format(
        sku_id=item["sku_id"],
        from_slot=item["from_slot"],
        to_slot=slot["slot_id"],
        pick_frequency=item["pick_frequency"],
        waste_score=item["waste_score"],
        saving=saving,
    )


def clear_existing_pending(db, recommendations):
    if not recommendations:
        return None

    clauses = []
    for item in recommendations:
        clauses.append(
            "(sku_id = {sku_id} AND from_slot = {from_slot})".format(
                sku_id=sql_literal(item["sku_id"]),
                from_slot=sql_literal(item["from_slot"]),
            )
        )

    return """
        DELETE FROM slotting_recommendations
        WHERE status = 'PENDING'
          AND (
              {clauses}
          )
        """.format(clauses="\n              OR ".join(clauses))


def insert_recommendations(db, recommendations):
    if not recommendations:
        return 0

    statements = []
    delete_statement = clear_existing_pending(db, recommendations)
    if delete_statement:
        statements.append(delete_statement)

    for offset, item in enumerate(recommendations, start=1):
        statements.append(
            """
            INSERT INTO slotting_recommendations (
                sku_id,
                from_slot,
                to_slot,
                saving_m,
                ai_reason,
                status,
                created_at
            )
            VALUES (
                {sku_id},
                {from_slot},
                {to_slot},
                {saving_m},
                {ai_reason},
                'PENDING',
                SYSTIMESTAMP
            )
            """.format(
                sku_id=sql_literal(item["sku_id"]),
                from_slot=sql_literal(item["from_slot"]),
                to_slot=sql_literal(item["to_slot"]),
                saving_m=sql_number(item["daily_saving_meters"]),
                ai_reason=sql_literal(item["ai_reason"]),
            )
        )

    statements.append("COMMIT")
    db.execute_script(statements)
    return len(recommendations)


def run_slotting_analysis(db=None):
    owns_db = db is None
    if owns_db:
        db = SqlclDatabase(Settings())
        db.open()

    try:
        dispatch_dock = fetch_dispatch_dock(db)
        pick_frequencies = fetch_pick_frequencies(db)
        inventory_positions = fetch_current_inventory_positions(db)
        empty_fast_pick_slots = fetch_empty_fast_pick_slots(db)

        scored_items = []
        for item in inventory_positions:
            sku_id = item.get("sku_id")
            pick_frequency = pick_frequencies.get(sku_id, 0)
            if pick_frequency <= 0:
                continue

            current_distance = euclidean_distance(
                slot_center(item),
                dispatch_dock,
            )
            scored_items.append(
                {
                    "sku_id": sku_id,
                    "sku_name": item.get("sku_name"),
                    "from_slot": item.get("from_slot"),
                    "pick_frequency": pick_frequency,
                    "current_distance": current_distance,
                    "waste_score": pick_frequency * current_distance,
                }
            )

        top_items = sorted(
            scored_items,
            key=lambda item: item["waste_score"],
            reverse=True,
        )[:10]

        assigned_slots = set()
        recommendations = []
        for item in top_items:
            nearest_slot = None
            nearest_distance = None
            for slot in empty_fast_pick_slots:
                slot_id = slot.get("slot_id")
                if slot_id in assigned_slots:
                    continue
                distance = euclidean_distance(slot_center(slot), dispatch_dock)
                if nearest_distance is None or distance < nearest_distance:
                    nearest_slot = slot
                    nearest_distance = distance

            if nearest_slot is None:
                continue

            saving = (
                item["current_distance"] - nearest_distance
            ) * item["pick_frequency"]
            if saving <= 0:
                continue

            assigned_slots.add(nearest_slot["slot_id"])
            recommendations.append(
                {
                    "sku_id": item["sku_id"],
                    "from_slot": item["from_slot"],
                    "to_slot": nearest_slot["slot_id"],
                    "daily_saving_meters": saving,
                    "waste_score": item["waste_score"],
                    "pick_frequency": item["pick_frequency"],
                    "ai_reason": build_reason(item, nearest_slot, saving),
                }
            )

        inserted = insert_recommendations(db, recommendations)
        summary = {
            "analyzed_skus": len(scored_items),
            "top_candidates": len(top_items),
            "recommendations_inserted": inserted,
        }
        LOGGER.info("Slotting analysis completed: %s", summary)
        return summary
    except Exception:
        try:
            db.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        if owns_db:
            db.close()


def create_slotting_scheduler(db, interval_seconds):
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        run_slotting_analysis,
        "interval",
        seconds=interval_seconds,
        kwargs={"db": db},
        id="slotting_analysis",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    return scheduler
