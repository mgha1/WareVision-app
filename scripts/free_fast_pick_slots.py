from warehouse_api.config import Settings
from warehouse_api.database import SqlclDatabase
from warehouse_api.slotting import run_slotting_analysis


FAST_PICK_ZONE_SQL = """
    SELECT zone_id
    FROM warehouse_zones
    WHERE zone_type = 'STORAGE'
      AND LOWER(zone_name) LIKE '%fast%'
"""

RANDOM_OCCUPIED_SLOTS_SQL = """
    SELECT s.slot_id, i.sku_id, i.inv_id
    FROM slots s
    JOIN inventory i
      ON s.slot_id = i.slot_id
    WHERE s.zone_id = :fast_pick_zone_id
      AND s.is_occupied = 1
    ORDER BY DBMS_RANDOM.VALUE
    FETCH FIRST 7 ROWS ONLY
"""

DELETE_INVENTORY_SQL = """
    DELETE FROM inventory
    WHERE inv_id = :inv_id
"""

FREE_SLOT_SQL = """
    UPDATE slots
    SET is_occupied = 0
    WHERE slot_id = :slot_id
"""

VERIFY_OCCUPIED_SQL = """
    SELECT COUNT(*) AS occupied_count
    FROM slots
    WHERE zone_id = :fast_pick_zone_id
      AND is_occupied = 1
"""

DELETE_PENDING_RECOMMENDATIONS_SQL = """
    DELETE FROM slotting_recommendations
    WHERE status = 'PENDING'
"""


def main():
    db = SqlclDatabase(Settings())
    db.open()

    try:
        with db._acquire() as conn:
            try:
                with conn.cursor() as cur:
                    cur.execute(FAST_PICK_ZONE_SQL)
                    zone_rows = cur.fetchall()
                    if len(zone_rows) != 1:
                        raise RuntimeError(
                            "Expected exactly 1 fast-pick zone, found {0}".format(
                                len(zone_rows)
                            )
                        )

                    fast_pick_zone_id = zone_rows[0][0]

                    cur.execute(
                        RANDOM_OCCUPIED_SLOTS_SQL,
                        fast_pick_zone_id=fast_pick_zone_id,
                    )
                    rows = cur.fetchall()
                    if len(rows) != 7:
                        raise RuntimeError(
                            "Expected exactly 7 occupied fast-pick slots, found {0}".format(
                                len(rows)
                            )
                        )

                    for slot_id, _sku_id, inv_id in rows:
                        cur.execute(DELETE_INVENTORY_SQL, inv_id=inv_id)
                        cur.execute(FREE_SLOT_SQL, slot_id=slot_id)

                    conn.commit()

                    cur.execute(
                        VERIFY_OCCUPIED_SQL,
                        fast_pick_zone_id=fast_pick_zone_id,
                    )
                    occupied_count = int(cur.fetchone()[0])

                    print(
                        "Done. Freed 7 fast-pick slots. Now {0}/60 occupied.".format(
                            occupied_count
                        )
                    )

                    cur.execute(DELETE_PENDING_RECOMMENDATIONS_SQL)
                    conn.commit()

                refresh_summary = run_slotting_analysis(db=db)
                print(
                    "Refreshed slotting recommendations. Inserted {0} pending recommendations.".format(
                        refresh_summary["recommendations_inserted"]
                    )
                )
            except Exception:
                conn.rollback()
                raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
