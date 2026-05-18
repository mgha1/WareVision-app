import secrets
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.sessions import SessionMiddleware

from warehouse_api.config import Settings
from warehouse_api.database import SqlclDatabase, sql_literal
from warehouse_api.forecast_engine import (
    ForecastEngine,
    ensure_forecast_history_support,
)
from warehouse_api.slotting import create_slotting_scheduler


settings = Settings()
app = FastAPI(title="Warehouse Backend")
STATIC_DIR = Path(__file__).resolve().parent / "static"
reordered_skus = set()
CACHE_TTLS = {
    "floor": 5.0,
    "recommendations": 5.0,
    "heatmap": 5.0,
    "assets": 2.0,
    "inbound_log": 5.0,
    "analytics": 10.0,
    "login_metrics": 10.0,
}

app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    session_cookie="warehouse_session",
    same_site="lax",
    https_only=False,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


class MoveInventoryRequest(BaseModel):
    sku_id: str
    from_slot: str
    to_slot: str


class AcceptRecommendationRequest(BaseModel):
    rec_id: int


class LoginRequest(BaseModel):
    username: str
    password: str


class InventoryRecommendationRequest(BaseModel):
    sku_id: str
    quantity: int
    category: str = ""
    exclude_slots: list[str] = Field(default_factory=list)


class InventoryAssignRequest(BaseModel):
    sku_id: str
    slot_id: str
    quantity: int
    sku_name: str = ""
    category: str = ""
    unit_weight: Optional[float] = None
    supplier: str = ""
    notes: str = ""


@app.on_event("startup")
def startup():
    app.state.db = SqlclDatabase(settings)
    app.state.db.open()
    app.state.inventory_upload_schema_error = None
    app.state.forecast_schema_error = None
    try:
        _ensure_inventory_upload_support(app.state.db)
    except Exception as exc:
        app.state.inventory_upload_schema_error = str(exc)
    try:
        ensure_forecast_history_support(app.state.db)
        app.state.forecast_engine = ForecastEngine(app.state.db)
    except Exception as exc:
        app.state.forecast_schema_error = str(exc)
        app.state.forecast_engine = None
    app.state.response_cache = {}
    app.state.active_sessions = set()
    app.state.slotting_scheduler = None
    if settings.enable_slotting_scheduler:
        app.state.slotting_scheduler = create_slotting_scheduler(
            app.state.db,
            settings.slotting_interval_seconds,
        )


@app.on_event("shutdown")
def shutdown():
    scheduler = getattr(app.state, "slotting_scheduler", None)
    if scheduler is not None:
        scheduler.shutdown(wait=False)
    if hasattr(app.state, "db"):
        app.state.db.close()


def get_db():
    return app.state.db


def require_auth(request):
    session_id = request.session.get("session_id")
    active_sessions = getattr(app.state, "active_sessions", set())
    if request.session.get("authenticated") and session_id in active_sessions:
        return
    raise HTTPException(status_code=401, detail="Authentication required")


def _get_cached_payload(key, loader):
    cache = app.state.response_cache
    now = time.time()
    entry = cache.get(key)
    ttl = CACHE_TTLS[key]
    if entry is not None and (now - entry["timestamp"]) < ttl:
        return entry["payload"]

    payload = loader()
    cache[key] = {"timestamp": now, "payload": payload}
    return payload


def _invalidate_cache(*keys):
    cache = app.state.response_cache
    for key in keys:
        cache.pop(key, None)


def _recent_reordered_skus(db):
    rows = db.fetch_all(
        """
        SELECT sku_id
        FROM movement_log
        WHERE movement_type = 'REORDER_INITIATED'
          AND moved_at >= SYSTIMESTAMP - INTERVAL '24' HOUR
        """
    )
    return {row["sku_id"] for row in rows if row.get("sku_id")}


def _get_reordered_skus(db):
    return set(reordered_skus) | _recent_reordered_skus(db)


def _override_ordered_status(items, ordered_ids):
    updated_items = []
    for item in items:
        row = dict(item)
        if row.get("sku_id") in ordered_ids:
            row["status"] = "ordered"
            row["days_until_stockout"] = None
        updated_items.append(row)
    return updated_items


def _build_inventory_move_script(sku_id, from_slot, to_slot):
    return [
        """
        UPDATE inventory
        SET slot_id = {to_slot},
            placed_at = SYSTIMESTAMP
        WHERE sku_id = {sku_id}
          AND slot_id = {from_slot}
        """.format(
            to_slot=to_slot,
            sku_id=sku_id,
            from_slot=from_slot,
        ),
        """
        UPDATE slots
        SET is_occupied = CASE
            WHEN EXISTS (
                SELECT 1
                FROM inventory
                WHERE slot_id = {from_slot}
            ) THEN 1
            ELSE 0
        END
        WHERE slot_id = {from_slot}
        """.format(from_slot=from_slot),
        """
        UPDATE slots
        SET is_occupied = CASE
            WHEN EXISTS (
                SELECT 1
                FROM inventory
                WHERE slot_id = {to_slot}
            ) THEN 1
            ELSE 0
        END
        WHERE slot_id = {to_slot}
        """.format(to_slot=to_slot),
        "COMMIT",
    ]


def _sql_nullable_string(value):
    cleaned = (value or "").strip()
    if not cleaned:
        return "NULL"
    return sql_literal(cleaned)


def _sql_nullable_number(value):
    if value is None or value == "":
        return "NULL"
    return str(float(value))


def _sanitize_text(value):
    return (value or "").strip()


def _require_inventory_upload_support():
    schema_error = getattr(app.state, "inventory_upload_schema_error", None)
    if not schema_error:
        return
    raise HTTPException(
        status_code=500,
        detail="Inventory upload schema is unavailable: {0}".format(schema_error),
    )


def _get_forecast_engine():
    engine = getattr(app.state, "forecast_engine", None)
    if engine is not None:
        return engine

    try:
        ensure_forecast_history_support(app.state.db)
        engine = ForecastEngine(app.state.db)
        app.state.forecast_engine = engine
        app.state.forecast_schema_error = None
        return engine
    except Exception as exc:
        app.state.forecast_schema_error = str(exc)
        raise HTTPException(
            status_code=500,
            detail="Forecasting is unavailable: {0}".format(exc),
        )

def _require_forecast_support():
    _get_forecast_engine()
    return None


def _parse_forecast_horizon(request: Request):
    raw_horizon = request.query_params.get("horizon", "14")
    try:
        horizon = int(raw_horizon)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="horizon must be 7, 14, or 30")
    if horizon not in (7, 14, 30):
        raise HTTPException(status_code=400, detail="horizon must be 7, 14, or 30")
    return horizon


def _table_exists(db, table_name):
    row = db.fetch_one(
        """
        SELECT COUNT(*) AS table_count
        FROM user_tables
        WHERE table_name = {table_name}
        """.format(table_name=sql_literal(table_name.upper()))
    )
    return bool(int(row["table_count"] or 0))


def _ensure_inventory_upload_support(db):
    statements = []

    if not _table_exists(db, "SLOT_ASSIGNMENTS"):
        statements.append(
            """
            CREATE TABLE slot_assignments (
                assignment_id VARCHAR2(64) PRIMARY KEY,
                sku_id VARCHAR2(128) NOT NULL,
                slot_id VARCHAR2(128) NOT NULL,
                zone_id VARCHAR2(128),
                quantity NUMBER NOT NULL,
                unit_weight_kg NUMBER,
                supplier VARCHAR2(255),
                notes VARCHAR2(4000),
                assigned_at TIMESTAMP DEFAULT SYSTIMESTAMP NOT NULL
            )
            """
        )

    if not _table_exists(db, "MOVEMENT_LOG"):
        statements.append(
            """
            CREATE TABLE movement_log (
                movement_id VARCHAR2(64) PRIMARY KEY,
                sku_id VARCHAR2(128) NOT NULL,
                slot_id VARCHAR2(128) NOT NULL,
                zone_id VARCHAR2(128),
                quantity NUMBER NOT NULL,
                movement_type VARCHAR2(32) NOT NULL,
                status VARCHAR2(32) DEFAULT 'Assigned' NOT NULL,
                supplier VARCHAR2(255),
                notes VARCHAR2(4000),
                moved_at TIMESTAMP DEFAULT SYSTIMESTAMP NOT NULL
            )
            """
        )

    if statements:
        db.execute_script(statements)


def _zone_condition(zone_family):
    if zone_family == "fastpick":
        return (
            "UPPER(zone_name) LIKE '%FAST%' "
            "OR UPPER(zone_type) LIKE '%FAST%' "
            "OR UPPER(zone_type) LIKE '%PICK%'"
        )
    if zone_family == "dispatch":
        return (
            "UPPER(zone_name) LIKE '%DISPATCH%' "
            "OR UPPER(zone_type) LIKE '%DISPATCH%'"
        )
    return (
        "UPPER(zone_name) LIKE '%BULK%' "
        "OR UPPER(zone_type) LIKE '%BULK%' "
        "OR UPPER(zone_type) LIKE '%STORE%'"
    )


def _lookup_sku_details(db, sku_id):
    sku_literal = sql_literal(sku_id)
    product = db.fetch_one(
        """
        SELECT
            p.id,
            p.sku,
            p.name AS sku_name,
            p.weight_kg,
            c.name AS category
        FROM product p
        LEFT JOIN category c
            ON c.id = p.category_id
        WHERE p.sku = {sku_id}
        FETCH FIRST 1 ROW ONLY
        """.format(sku_id=sku_literal)
    )
    inventory_fallback = db.fetch_one(
        """
        SELECT
            MAX(sku_name) AS sku_name,
            MAX(category) AS category,
            MAX(weight_kg) AS weight_kg
        FROM inventory
        WHERE sku_id = {sku_id}
        """.format(sku_id=sku_literal)
    )
    pick_frequency_row = db.fetch_one(
        """
        SELECT COUNT(*) AS pick_frequency
        FROM pick_history
        WHERE sku_id = {sku_id}
          AND picked_at >= SYSTIMESTAMP - NUMTODSINTERVAL(30, 'DAY')
        """.format(sku_id=sku_literal)
    )

    sku_name = None
    category = None
    unit_weight = None
    exists = False

    if product is not None and product.get("sku"):
        exists = True
        sku_name = product.get("sku_name")
        category = product.get("category")
        unit_weight = product.get("weight_kg")

    if not sku_name and inventory_fallback is not None:
        sku_name = inventory_fallback.get("sku_name")
    if not category and inventory_fallback is not None:
        category = inventory_fallback.get("category")
    if unit_weight is None and inventory_fallback is not None:
        unit_weight = inventory_fallback.get("weight_kg")

    if inventory_fallback and inventory_fallback.get("sku_name"):
        exists = True

    return {
        "exists": exists,
        "sku_id": sku_id,
        "sku_name": sku_name,
        "category": category,
        "pick_frequency": int(pick_frequency_row.get("pick_frequency") or 0),
        "unit_weight": float(unit_weight) if unit_weight is not None else None,
    }


def _resolve_zone(db, zone_family):
    zone = db.fetch_one(
        """
        SELECT
            zone_id,
            zone_name,
            zone_type
        FROM warehouse_zones
        WHERE {condition}
        ORDER BY zone_id
        FETCH FIRST 1 ROW ONLY
        """.format(condition=_zone_condition(zone_family))
    )
    if zone is None:
        raise HTTPException(
            status_code=404,
            detail="No zone configured for {0}".format(zone_family),
        )
    return zone


def _dispatch_center(db):
    dispatch_zone = db.fetch_one(
        """
        SELECT
            ((x1 + x2) / 2) AS dispatch_x,
            ((y1 + y2) / 2) AS dispatch_y
        FROM warehouse_zones
        WHERE {condition}
        FETCH FIRST 1 ROW ONLY
        """.format(condition=_zone_condition("dispatch"))
    )
    if dispatch_zone is None:
        raise HTTPException(status_code=404, detail="Dispatch zone not found")
    return {
        "x": float(dispatch_zone.get("dispatch_x") or 0),
        "y": float(dispatch_zone.get("dispatch_y") or 0),
    }


def _slot_distance_expression(dispatch_center):
    return """
    ROUND(
        SQRT(
            POWER((NVL(s.x, 0) + (NVL(s.width, 0) / 2)) - {dispatch_x}, 2) +
            POWER((NVL(s.y, 0) + (NVL(s.height, 0) / 2)) - {dispatch_y}, 2)
        ),
        2
    )
    """.format(
        dispatch_x=dispatch_center["x"],
        dispatch_y=dispatch_center["y"],
    )


def _recommend_inbound_slot(db, sku_id, category, exclude_slots):
    sku_details = _lookup_sku_details(db, sku_id)
    pick_frequency = int(sku_details["pick_frequency"] or 0)
    zone_family = "fastpick" if pick_frequency > 15 else "bulk"
    target_zone = _resolve_zone(db, zone_family)
    dispatch_center = _dispatch_center(db)
    distance_sql = _slot_distance_expression(dispatch_center)

    clean_excludes = []
    for slot_id in exclude_slots or []:
        cleaned = _sanitize_text(slot_id)
        if cleaned and cleaned not in clean_excludes:
            clean_excludes.append(cleaned)

    exclude_clause = ""
    if clean_excludes:
        exclude_clause = "AND s.slot_id NOT IN ({0})".format(
            ", ".join(sql_literal(slot_id) for slot_id in clean_excludes)
        )

    slot = db.fetch_one(
        """
        SELECT
            s.slot_id,
            s.zone_id,
            s.aisle,
            s.bay,
            s."LEVEL" AS slot_level,
            z.zone_name,
            z.zone_type,
            {distance_sql} AS distance_to_dispatch
        FROM slots s
        JOIN warehouse_zones z
            ON z.zone_id = s.zone_id
        LEFT JOIN inventory inv
            ON inv.slot_id = s.slot_id
        WHERE NVL(s.is_occupied, 0) = 0
          AND inv.slot_id IS NULL
          AND s.zone_id = {zone_id}
          {exclude_clause}
        ORDER BY distance_to_dispatch ASC, s.aisle, s.bay, s."LEVEL", s.slot_id
        FETCH FIRST 1 ROW ONLY
        """.format(
            distance_sql=distance_sql,
            zone_id=sql_literal(target_zone["zone_id"]),
            exclude_clause=exclude_clause,
        )
    )
    if slot is None:
        raise HTTPException(
            status_code=404,
            detail="No available slot found in the target zone",
        )

    occupancy = db.fetch_one(
        """
        SELECT
            COUNT(*) AS total_slots,
            SUM(
                CASE
                    WHEN NVL(s.is_occupied, 0) = 1 OR inv.slot_id IS NOT NULL THEN 1
                    ELSE 0
                END
            ) AS occupied_slots
        FROM slots s
        LEFT JOIN (
            SELECT DISTINCT slot_id
            FROM inventory
        ) inv
            ON inv.slot_id = s.slot_id
        WHERE s.zone_id = {zone_id}
        """.format(zone_id=sql_literal(target_zone["zone_id"]))
    )
    avg_distance_row = db.fetch_one(
        """
        SELECT
            AVG({distance_sql}) AS avg_distance
        FROM slots s
        LEFT JOIN inventory inv
            ON inv.slot_id = s.slot_id
        WHERE NVL(s.is_occupied, 0) = 0
          AND inv.slot_id IS NULL
          AND s.zone_id = {zone_id}
        """.format(
            distance_sql=distance_sql,
            zone_id=sql_literal(target_zone["zone_id"]),
        )
    )

    total_slots = int(occupancy.get("total_slots") or 0)
    occupied_slots = int(occupancy.get("occupied_slots") or 0)
    occupancy_pct = round((occupied_slots / total_slots) * 100, 1) if total_slots else 0.0
    avg_distance = float(avg_distance_row.get("avg_distance") or slot["distance_to_dispatch"] or 0)
    distance_to_dispatch = float(slot.get("distance_to_dispatch") or 0)
    estimated_saving = max(0.0, avg_distance - distance_to_dispatch) * max(1, pick_frequency or 4)

    return {
        "slot_id": slot["slot_id"],
        "zone": slot["zone_name"],
        "zone_type": slot["zone_type"],
        "distance_to_dispatch": round(distance_to_dispatch, 2),
        "occupancy_pct": occupancy_pct,
        "estimated_saving": round(estimated_saving, 1),
        "pick_frequency": pick_frequency,
        "category": category or sku_details.get("category"),
    }


def _category_lookup(db, category_name):
    cleaned = _sanitize_text(category_name)
    if not cleaned:
        return None
    return db.fetch_one(
        """
        SELECT
            id,
            name
        FROM category
        WHERE UPPER(name) = UPPER({category_name})
        FETCH FIRST 1 ROW ONLY
        """.format(category_name=sql_literal(cleaned))
    )


@app.get("/", include_in_schema=False)
def get_map():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/floor")
def get_floor(request: Request):
    require_auth(request)

    def load_payload():
        db = get_db()
        zones = db.fetch_all(
            """
            SELECT
                zone_id,
                zone_name,
                zone_type,
                x1,
                y1,
                x2,
                y2,
                color_hex
            FROM warehouse_zones
            ORDER BY zone_id
            """
        )
        slots = db.fetch_all(
            """
            SELECT
                s.slot_id,
                s.zone_id,
                s.aisle,
                s.bay,
                s."LEVEL" AS slot_level,
                s.x,
                s.y,
                s.width,
                s.height,
                s.capacity_kg,
                s.is_occupied,
                inv.sku_id,
                inv.sku_name,
                inv.quantity,
                NVL(ph.pick_count, 0) AS pick_count,
                rec.to_slot AS recommendation_to_slot,
                rec.saving_m AS recommendation_saving_m,
                rec.ai_reason AS recommendation_reason,
                rec.status AS recommendation_status
            FROM slots s
            LEFT JOIN (
                SELECT
                    slot_id,
                    MAX(sku_id) AS sku_id,
                    MAX(sku_name) AS sku_name,
                    SUM(quantity) AS quantity
                FROM inventory
                GROUP BY slot_id
            ) inv
                ON inv.slot_id = s.slot_id
            LEFT JOIN (
                SELECT
                    slot_id,
                    COUNT(*) AS pick_count
                FROM pick_history
                GROUP BY slot_id
            ) ph
                ON ph.slot_id = s.slot_id
            LEFT JOIN (
                SELECT
                    sku_id,
                    from_slot,
                    to_slot,
                    saving_m,
                    ai_reason,
                    status
                FROM (
                    SELECT
                        sr.*,
                        ROW_NUMBER() OVER (
                            PARTITION BY sr.from_slot
                            ORDER BY sr.created_at DESC NULLS LAST, sr.rec_id DESC
                        ) AS row_num
                    FROM slotting_recommendations sr
                )
                WHERE row_num = 1
            ) rec
                ON rec.from_slot = s.slot_id
               AND (rec.sku_id = inv.sku_id OR inv.sku_id IS NULL)
            ORDER BY s.zone_id, s.aisle, s.bay, s."LEVEL", s.slot_id
            """
        )

        zone_index = {}
        for zone in zones:
            zone["slots"] = []
            zone_index[zone["zone_id"]] = zone

        for slot in slots:
            slot["level"] = slot.pop("slot_level", None)
            recommendation = None
            if slot.get("recommendation_to_slot"):
                recommendation = {
                    "to_slot": slot.pop("recommendation_to_slot"),
                    "saving_m": slot.pop("recommendation_saving_m"),
                    "reason": slot.pop("recommendation_reason"),
                    "status": slot.pop("recommendation_status"),
                }
            else:
                slot.pop("recommendation_to_slot", None)
                slot.pop("recommendation_saving_m", None)
                slot.pop("recommendation_reason", None)
                slot.pop("recommendation_status", None)
            slot["recommendation"] = recommendation
            zone = zone_index.get(slot["zone_id"])
            if zone is not None:
                zone["slots"].append(slot)

        return {"zones": zones}

    return _get_cached_payload("floor", load_payload)


@app.get("/api/inventory")
def get_inventory(request: Request):
    require_auth(request)
    db = get_db()
    items = db.fetch_all(
        """
        SELECT
            i.inv_id,
            i.sku_id,
            i.sku_name,
            i.slot_id,
            i.quantity,
            i.weight_kg,
            i.placed_at,
            i.category,
            s.zone_id,
            s.aisle,
            s.bay,
            s."LEVEL" AS slot_level,
            s.x,
            s.y
        FROM inventory i
        LEFT JOIN slots s
            ON s.slot_id = i.slot_id
        ORDER BY i.sku_id, i.slot_id
        """
    )
    for item in items:
        item["level"] = item.pop("slot_level", None)
    return {"items": items}


@app.get("/api/login-metrics")
def get_login_metrics():
    def load_payload():
        db = get_db()
        overview = db.fetch_one(
            """
            SELECT
                (SELECT COUNT(*) FROM slots) AS total_slots,
                (SELECT COUNT(*) FROM warehouse_zones) AS zones_online,
                (
                    SELECT NVL(SUM(saving_m), 0)
                    FROM slotting_recommendations
                    WHERE status = 'PENDING'
                ) AS queue_savings_m
            FROM dual
            """
        )
        fast_pick = db.fetch_one(
            """
            SELECT
                COUNT(DISTINCT s.slot_id) AS total_slots,
                COUNT(DISTINCT CASE
                    WHEN NVL(s.is_occupied, 0) = 1 OR inv.slot_id IS NOT NULL THEN s.slot_id
                    ELSE NULL
                END) AS occupied_slots
            FROM warehouse_zones z
            LEFT JOIN slots s
                ON s.zone_id = z.zone_id
            LEFT JOIN (
                SELECT DISTINCT slot_id
                FROM inventory
            ) inv
                ON inv.slot_id = s.slot_id
            WHERE {condition}
            """.format(condition=_zone_condition("fastpick"))
        )

        total_fast_pick_slots = int(fast_pick.get("total_slots") or 0)
        occupied_fast_pick_slots = int(fast_pick.get("occupied_slots") or 0)

        return {
            "total_slots": int(overview.get("total_slots") or 0),
            "zones_online": int(overview.get("zones_online") or 0),
            "queue_savings_m": round(float(overview.get("queue_savings_m") or 0), 1),
            "fast_pick_utilization_pct": round(
                (occupied_fast_pick_slots / total_fast_pick_slots) * 100, 1
            )
            if total_fast_pick_slots
            else 0.0,
        }

    return _get_cached_payload("login_metrics", load_payload)


@app.get("/api/analytics")
def get_warehouse_analytics(request: Request):
    require_auth(request)
    _require_inventory_upload_support()

    def load_payload():
        db = get_db()
        overview = db.fetch_one(
            """
            SELECT
                (SELECT COUNT(DISTINCT sku_id) FROM inventory) AS active_skus,
                (SELECT NVL(SUM(quantity), 0) FROM inventory) AS total_units,
                (
                    SELECT COUNT(DISTINCT s.slot_id)
                    FROM slots s
                    LEFT JOIN inventory inv
                        ON inv.slot_id = s.slot_id
                    WHERE NVL(s.is_occupied, 0) = 1 OR inv.slot_id IS NOT NULL
                ) AS occupied_slots,
                (SELECT COUNT(*) FROM slots) AS total_slots,
                (SELECT COUNT(*) FROM asset_positions) AS active_assets
            FROM dual
            """
        )
        pending_queue = db.fetch_one(
            """
            SELECT
                COUNT(*) AS pending_recommendations,
                NVL(SUM(saving_m), 0) AS queue_savings_m
            FROM slotting_recommendations
            WHERE status = 'PENDING'
            """
        )
        today_inbound = db.fetch_one(
            """
            SELECT
                NVL(SUM(quantity), 0) AS today_inbound_units,
                COUNT(*) AS inbound_events
            FROM movement_log
            WHERE movement_type = 'INBOUND'
              AND TRUNC(moved_at) = TRUNC(SYSTIMESTAMP)
            """
        )
        today_sales = db.fetch_one(
            """
            SELECT
                NVL(SUM(revenue), 0) AS today_revenue
            FROM daily_sales
            WHERE TRUNC(sale_date) = TRUNC(SYSDATE)
            """
        )

        total_slots = int(overview.get("total_slots") or 0)
        occupied_slots = int(overview.get("occupied_slots") or 0)
        summary = {
            "active_skus": int(overview.get("active_skus") or 0),
            "total_units": int(overview.get("total_units") or 0),
            "occupied_slots": occupied_slots,
            "empty_slots": max(0, total_slots - occupied_slots),
            "occupancy_rate": round((occupied_slots / total_slots) * 100, 1)
            if total_slots
            else 0.0,
            "active_assets": int(overview.get("active_assets") or 0),
            "pending_recommendations": int(
                pending_queue.get("pending_recommendations") or 0
            ),
            "queue_savings_m": round(float(pending_queue.get("queue_savings_m") or 0), 1),
            "today_inbound_units": int(today_inbound.get("today_inbound_units") or 0),
            "inbound_events": int(today_inbound.get("inbound_events") or 0),
            "today_revenue": round(float(today_sales.get("today_revenue") or 0), 2),
        }

        zone_utilization = db.fetch_all(
            """
            SELECT
                z.zone_id,
                z.zone_name,
                z.zone_type,
                COUNT(DISTINCT s.slot_id) AS total_slots,
                COUNT(DISTINCT CASE
                    WHEN NVL(s.is_occupied, 0) = 1 OR inv.slot_id IS NOT NULL THEN s.slot_id
                    ELSE NULL
                END) AS occupied_slots,
                COUNT(DISTINCT inv.sku_id) AS sku_count,
                NVL(SUM(NVL(ph.pick_count, 0)), 0) AS pick_count_30d
            FROM warehouse_zones z
            LEFT JOIN slots s
                ON s.zone_id = z.zone_id
            LEFT JOIN (
                SELECT
                    slot_id,
                    MAX(sku_id) AS sku_id
                FROM inventory
                GROUP BY slot_id
            ) inv
                ON inv.slot_id = s.slot_id
            LEFT JOIN (
                SELECT
                    slot_id,
                    COUNT(*) AS pick_count
                FROM pick_history
                WHERE picked_at >= SYSTIMESTAMP - NUMTODSINTERVAL(30, 'DAY')
                GROUP BY slot_id
            ) ph
                ON ph.slot_id = s.slot_id
            GROUP BY z.zone_id, z.zone_name, z.zone_type
            ORDER BY z.zone_id
            """
        )
        for zone in zone_utilization:
            zone_total = int(zone.get("total_slots") or 0)
            zone_occupied = int(zone.get("occupied_slots") or 0)
            zone["occupancy_pct"] = (
                round((zone_occupied / zone_total) * 100, 1) if zone_total else 0.0
            )

        top_skus = db.fetch_all(
            """
            SELECT
                ph.sku_id,
                NVL(MAX(inv.sku_name), NVL(MAX(p.name), ph.sku_id)) AS sku_name,
                COUNT(*) AS total_picks,
                NVL(MAX(inv.quantity_on_hand), 0) AS quantity_on_hand,
                MAX(inv.slot_id) AS current_slot,
                MAX(z.zone_name) AS zone_name
            FROM pick_history ph
            LEFT JOIN (
                SELECT
                    sku_id,
                    MAX(sku_name) AS sku_name,
                    SUM(quantity) AS quantity_on_hand,
                    MAX(slot_id) AS slot_id
                FROM inventory
                GROUP BY sku_id
            ) inv
                ON inv.sku_id = ph.sku_id
            LEFT JOIN slots s
                ON s.slot_id = inv.slot_id
            LEFT JOIN warehouse_zones z
                ON z.zone_id = s.zone_id
            LEFT JOIN product p
                ON p.sku = ph.sku_id
            WHERE ph.picked_at >= SYSTIMESTAMP - NUMTODSINTERVAL(30, 'DAY')
            GROUP BY ph.sku_id
            ORDER BY total_picks DESC, quantity_on_hand DESC, ph.sku_id
            FETCH FIRST 8 ROWS ONLY
            """
        )

        category_mix = db.fetch_all(
            """
            SELECT
                category,
                COUNT(DISTINCT sku_id) AS sku_count,
                NVL(SUM(quantity_on_hand), 0) AS quantity_on_hand,
                NVL(SUM(revenue_7d), 0) AS revenue_7d,
                NVL(SUM(picks_30d), 0) AS picks_30d
            FROM (
                SELECT
                    inv.sku_id,
                    NVL(inv.category, NVL(c.name, 'Uncategorized')) AS category,
                    inv.quantity_on_hand,
                    NVL(ds.revenue, 0) AS revenue_7d,
                    NVL(picks.pick_count, 0) AS picks_30d
                FROM (
                    SELECT
                        sku_id,
                        MAX(category) AS category,
                        SUM(quantity) AS quantity_on_hand
                    FROM inventory
                    GROUP BY sku_id
                ) inv
                LEFT JOIN product p
                    ON p.sku = inv.sku_id
                LEFT JOIN category c
                    ON c.id = p.category_id
                LEFT JOIN (
                    SELECT
                        prod.sku AS sku_id,
                        SUM(revenue) AS revenue
                    FROM daily_sales ds
                    JOIN product prod
                        ON prod.id = ds.product_id
                    WHERE ds.sale_date >= TRUNC(SYSDATE) - 6
                    GROUP BY prod.sku
                ) ds
                    ON ds.sku_id = inv.sku_id
                LEFT JOIN (
                    SELECT
                        sku_id,
                        COUNT(*) AS pick_count
                    FROM pick_history
                    WHERE picked_at >= SYSTIMESTAMP - NUMTODSINTERVAL(30, 'DAY')
                    GROUP BY sku_id
                ) picks
                    ON picks.sku_id = inv.sku_id
            )
            GROUP BY category
            ORDER BY revenue_7d DESC, picks_30d DESC, quantity_on_hand DESC
            FETCH FIRST 8 ROWS ONLY
            """
        )

        sales_trend = db.fetch_all(
            """
            SELECT
                TO_CHAR(sale_date, 'YYYY-MM-DD') AS sale_date,
                NVL(SUM(quantity_sold), 0) AS quantity_sold,
                NVL(SUM(revenue), 0) AS revenue
            FROM daily_sales
            WHERE sale_date >= TRUNC(SYSDATE) - 6
            GROUP BY TO_CHAR(sale_date, 'YYYY-MM-DD')
            ORDER BY sale_date
            """
        )

        asset_status = db.fetch_all(
            """
            SELECT
                NVL(status, 'UNKNOWN') AS status,
                COUNT(*) AS asset_count
            FROM asset_positions
            GROUP BY NVL(status, 'UNKNOWN')
            ORDER BY asset_count DESC, status
            """
        )

        recommendation_status = db.fetch_all(
            """
            SELECT
                NVL(status, 'UNKNOWN') AS status,
                COUNT(*) AS recommendation_count,
                NVL(SUM(saving_m), 0) AS total_saving_m
            FROM slotting_recommendations
            GROUP BY NVL(status, 'UNKNOWN')
            ORDER BY recommendation_count DESC, status
            """
        )

        inbound_activity = db.fetch_all(
            """
            SELECT
                TO_CHAR(moved_at, 'HH24') || ':00' AS hour_bucket,
                NVL(SUM(quantity), 0) AS inbound_units
            FROM movement_log
            WHERE movement_type = 'INBOUND'
              AND TRUNC(moved_at) = TRUNC(SYSTIMESTAMP)
            GROUP BY TO_CHAR(moved_at, 'HH24') || ':00'
            ORDER BY hour_bucket
            """
        )

        return {
            "summary": summary,
            "zone_utilization": zone_utilization,
            "top_skus": top_skus,
            "category_mix": category_mix,
            "sales_trend": sales_trend,
            "asset_status": asset_status,
            "recommendation_status": recommendation_status,
            "inbound_activity": inbound_activity,
        }

    return _get_cached_payload("analytics", load_payload)


@app.get("/api/skus/{sku_id}")
def get_sku_details(sku_id: str, request: Request):
    require_auth(request)
    _require_inventory_upload_support()

    normalized_sku = _sanitize_text(sku_id)
    if not normalized_sku:
        raise HTTPException(status_code=400, detail="sku_id is required")

    return _lookup_sku_details(get_db(), normalized_sku)


@app.post("/api/inventory/recommend")
def recommend_inventory_slot(payload: InventoryRecommendationRequest, request: Request):
    require_auth(request)
    _require_inventory_upload_support()

    sku_id = _sanitize_text(payload.sku_id)
    if not sku_id:
        raise HTTPException(status_code=400, detail="sku_id is required")
    if int(payload.quantity or 0) < 1:
        raise HTTPException(status_code=400, detail="quantity must be at least 1")

    return _recommend_inbound_slot(
        get_db(),
        sku_id,
        _sanitize_text(payload.category),
        payload.exclude_slots,
    )


@app.post("/api/inventory/assign")
def assign_inventory_slot(payload: InventoryAssignRequest, request: Request):
    require_auth(request)
    _require_inventory_upload_support()

    sku_id = _sanitize_text(payload.sku_id)
    slot_id = _sanitize_text(payload.slot_id)
    sku_name = _sanitize_text(payload.sku_name)
    category_name = _sanitize_text(payload.category)
    supplier = _sanitize_text(payload.supplier)
    notes = _sanitize_text(payload.notes)
    quantity = int(payload.quantity or 0)

    if not sku_id:
        raise HTTPException(status_code=400, detail="sku_id is required")
    if not slot_id:
        raise HTTPException(status_code=400, detail="slot_id is required")
    if quantity < 1:
        raise HTTPException(status_code=400, detail="quantity must be at least 1")

    db = get_db()
    sku_details = _lookup_sku_details(db, sku_id)
    resolved_category_name = category_name or sku_details.get("category") or ""
    slot = db.fetch_one(
        """
        SELECT
            s.slot_id,
            s.zone_id,
            z.zone_name,
            z.zone_type,
            NVL(s.is_occupied, 0) AS is_occupied
        FROM slots s
        JOIN warehouse_zones z
            ON z.zone_id = s.zone_id
        WHERE s.slot_id = {slot_id}
        FETCH FIRST 1 ROW ONLY
        """.format(slot_id=sql_literal(slot_id))
    )
    if slot is None:
        raise HTTPException(status_code=404, detail="Requested slot was not found")

    slot_conflict = db.fetch_one(
        """
        SELECT COUNT(*) AS row_count
        FROM inventory
        WHERE slot_id = {slot_id}
        """.format(slot_id=sql_literal(slot_id))
    )
    if int(slot.get("is_occupied") or 0) or int(slot_conflict.get("row_count") or 0):
        raise HTTPException(status_code=409, detail="Requested slot is already occupied")

    category_row = _category_lookup(db, resolved_category_name)
    category_id = category_row.get("id") if category_row else None
    category_insert = None
    if resolved_category_name and category_id is None:
        category_id = "CAT-" + secrets.token_hex(8).upper()
        category_insert = """
            INSERT INTO category (
                id,
                parent_id,
                name
            ) VALUES (
                {id},
                NULL,
                {name}
            )
        """.format(id=sql_literal(category_id), name=sql_literal(resolved_category_name))
        resolved_category_id = category_id

    resolved_sku_name = (
        sku_name
        or sku_details.get("sku_name")
        or sku_id
    )
    resolved_unit_weight = (
        payload.unit_weight
        if payload.unit_weight is not None
        else sku_details.get("unit_weight")
    )

    existing_inventory = db.fetch_one(
        """
        SELECT
            inv_id,
            quantity
        FROM inventory
        WHERE sku_id = {sku_id}
          AND slot_id = {slot_id}
        FETCH FIRST 1 ROW ONLY
        """.format(sku_id=sql_literal(sku_id), slot_id=sql_literal(slot_id))
    )

    statements = []
    if category_insert:
        statements.append(category_insert)

    statements.append(
        """
        UPDATE slots
        SET is_occupied = 1
        WHERE slot_id = {slot_id}
        """.format(slot_id=sql_literal(slot_id))
    )

    if existing_inventory is None:
        statements.append(
            """
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
                SYSTIMESTAMP,
                {category}
            )
            """.format(
                sku_id=sql_literal(sku_id),
                sku_name=sql_literal(resolved_sku_name),
                slot_id=sql_literal(slot_id),
                quantity=quantity,
                weight_kg=_sql_nullable_number(resolved_unit_weight),
                category=_sql_nullable_string(resolved_category_name),
            )
        )
    else:
        statements.append(
            """
            UPDATE inventory
            SET
                sku_name = {sku_name},
                quantity = {quantity},
                weight_kg = {weight_kg},
                placed_at = SYSTIMESTAMP,
                category = {category}
            WHERE inv_id = {inv_id}
            """.format(
                sku_name=sql_literal(resolved_sku_name),
                quantity=int(existing_inventory["quantity"] or 0) + quantity,
                weight_kg=_sql_nullable_number(resolved_unit_weight),
                category=_sql_nullable_string(resolved_category_name),
                inv_id=int(existing_inventory["inv_id"]),
            )
        )

    assignment_id = "ASN-" + secrets.token_hex(10).upper()
    movement_id = "MOV-" + secrets.token_hex(10).upper()
    statements.append(
        """
        INSERT INTO slot_assignments (
            assignment_id,
            sku_id,
            slot_id,
            zone_id,
            quantity,
            unit_weight_kg,
            supplier,
            notes,
            assigned_at
        ) VALUES (
            {assignment_id},
            {sku_id},
            {slot_id},
            {zone_id},
            {quantity},
            {weight_kg},
            {supplier},
            {notes},
            SYSTIMESTAMP
        )
        """.format(
            assignment_id=sql_literal(assignment_id),
            sku_id=sql_literal(sku_id),
            slot_id=sql_literal(slot_id),
            zone_id=sql_literal(slot["zone_id"]),
            quantity=quantity,
            weight_kg=_sql_nullable_number(resolved_unit_weight),
            supplier=_sql_nullable_string(supplier),
            notes=_sql_nullable_string(notes),
        )
    )
    statements.append(
        """
        INSERT INTO movement_log (
            movement_id,
            sku_id,
            slot_id,
            zone_id,
            quantity,
            movement_type,
            status,
            supplier,
            notes,
            moved_at
        ) VALUES (
            {movement_id},
            {sku_id},
            {slot_id},
            {zone_id},
            {quantity},
            'INBOUND',
            'Assigned',
            {supplier},
            {notes},
            SYSTIMESTAMP
        )
        """.format(
            movement_id=sql_literal(movement_id),
            sku_id=sql_literal(sku_id),
            slot_id=sql_literal(slot_id),
            zone_id=sql_literal(slot["zone_id"]),
            quantity=quantity,
            supplier=_sql_nullable_string(supplier),
            notes=_sql_nullable_string(notes),
        )
    )
    statements.append("COMMIT")

    try:
        db.execute_script(statements)
        _invalidate_cache("floor", "heatmap", "inbound_log")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    engine = getattr(app.state, "forecast_engine", None)
    if engine is not None:
        engine.clear_cache()

    timestamp_row = db.fetch_one("SELECT TO_CHAR(SYSTIMESTAMP, 'YYYY-MM-DD\"T\"HH24:MI:SS.FF3TZH:TZM') AS ts FROM dual")
    return {
        "success": True,
        "slot_id": slot_id,
        "sku_id": sku_id,
        "zone": slot["zone_name"],
        "timestamp": timestamp_row["ts"],
    }


@app.get("/api/inventory/today")
def get_today_inbound_log(request: Request):
    require_auth(request)
    _require_inventory_upload_support()

    def load_payload():
        rows = get_db().fetch_all(
            """
            SELECT
                ml.moved_at,
                ml.sku_id,
                NVL(inv.sku_name, NVL(p.name, ml.sku_id)) AS sku_name,
                ml.quantity,
                ml.slot_id AS assigned_slot,
                NVL(z.zone_name, ml.zone_id) AS zone,
                ml.status
            FROM movement_log ml
            LEFT JOIN inventory inv
                ON inv.sku_id = ml.sku_id
               AND inv.slot_id = ml.slot_id
            LEFT JOIN product p
                ON p.sku = ml.sku_id
            LEFT JOIN slots s
                ON s.slot_id = ml.slot_id
            LEFT JOIN warehouse_zones z
                ON z.zone_id = NVL(ml.zone_id, s.zone_id)
            WHERE ml.movement_type = 'INBOUND'
              AND TRUNC(ml.moved_at) = TRUNC(SYSTIMESTAMP)
            ORDER BY ml.moved_at DESC
            """
        )
        return {"items": rows}

    return _get_cached_payload("inbound_log", load_payload)


@app.get("/api/assets")
def get_assets(request: Request):
    require_auth(request)

    def load_payload():
        db = get_db()
        assets = db.fetch_all(
            """
            SELECT
                asset_id,
                asset_type,
                x,
                y,
                status,
                updated_at
            FROM asset_positions
            ORDER BY asset_id
            """
        )
        return {"assets": assets}

    return _get_cached_payload("assets", load_payload)


@app.get("/api/heatmap")
def get_heatmap(request: Request):
    require_auth(request)

    def load_payload():
        db = get_db()
        zones = db.fetch_all(
            """
            SELECT
                z.zone_id,
                z.zone_name,
                COUNT(s.slot_id) AS total_slots,
                SUM(
                    CASE
                        WHEN NVL(s.is_occupied, 0) = 1 OR inv.slot_id IS NOT NULL THEN 1
                        ELSE 0
                    END
                ) AS occupied_slots
            FROM warehouse_zones z
            LEFT JOIN slots s
                ON s.zone_id = z.zone_id
            LEFT JOIN (
                SELECT DISTINCT slot_id
                FROM inventory
            ) inv
                ON inv.slot_id = s.slot_id
            GROUP BY z.zone_id, z.zone_name
            ORDER BY z.zone_id
            """
        )

        overlays = []
        for zone in zones:
            total_slots = int(zone.get("total_slots") or 0)
            occupied_slots = int(zone.get("occupied_slots") or 0)
            density = 0.0
            if total_slots:
                density = float(occupied_slots) / float(total_slots)

            density_level = "low"
            if density >= 0.67:
                density_level = "high"
            elif density >= 0.34:
                density_level = "medium"

            overlays.append(
                {
                    "zone_id": zone["zone_id"],
                    "zone_name": zone["zone_name"],
                    "total_slots": total_slots,
                    "occupied_slots": occupied_slots,
                    "density": round(density, 4),
                    "density_level": density_level,
                }
            )

        return {"zones": overlays}

    return _get_cached_payload("heatmap", load_payload)


@app.get("/api/recommendations")
def get_recommendations(request: Request):
    require_auth(request)

    def load_payload():
        db = get_db()
        recommendations = db.fetch_all(
            """
            SELECT
                sr.rec_id,
                sr.sku_id,
                NVL(inv.sku_name, sr.sku_id) AS sku_name,
                sr.from_slot,
                sr.to_slot,
                sr.saving_m,
                sr.ai_reason,
                sr.status,
                sr.created_at
            FROM slotting_recommendations sr
            LEFT JOIN (
                SELECT
                    sku_id,
                    MAX(sku_name) AS sku_name
                FROM inventory
                GROUP BY sku_id
            ) inv
                ON inv.sku_id = sr.sku_id
            WHERE sr.status = 'PENDING'
            ORDER BY sr.saving_m DESC NULLS LAST, sr.created_at DESC NULLS LAST, sr.rec_id DESC
            """
        )

        total_meters_saved = 0.0
        for recommendation in recommendations:
            total_meters_saved += float(recommendation.get("saving_m") or 0)

        return {
            "recommendations": recommendations,
            "summary": {
                "total_meters_saved": round(total_meters_saved, 2),
                "count": len(recommendations),
            },
        }

    return _get_cached_payload("recommendations", load_payload)


@app.get("/api/forecast/summary")
def get_forecast_summary(request: Request):
    require_auth(request)
    horizon = _parse_forecast_horizon(request)
    db = get_db()
    data = _override_ordered_status(
        _get_forecast_engine().get_all_forecasts(horizon),
        _get_reordered_skus(db),
    )
    return {
        "items": data,
        "counts": {
            "stockout_risk": len(
                [item for item in data if item.get("status") == "stockout_risk"]
            ),
            "reorder_now": len(
                [item for item in data if item.get("status") == "reorder_now"]
            ),
            "healthy": len([item for item in data if item.get("status") == "healthy"]),
            "slow_moving": len(
                [item for item in data if item.get("status") == "slow_moving"]
            ),
        },
    }


@app.get("/api/forecast/sku/{sku_id}")
def get_forecast_for_sku(sku_id: str, request: Request):
    require_auth(request)
    horizon = _parse_forecast_horizon(request)
    normalized_sku = _sanitize_text(sku_id)
    if not normalized_sku:
        raise HTTPException(status_code=400, detail="sku_id is required")
    return _get_forecast_engine().forecast_sku(normalized_sku, horizon)


@app.get("/api/forecast/reorder-queue")
def get_forecast_reorder_queue(request: Request):
    require_auth(request)
    ordered_ids = _get_reordered_skus(get_db())
    data = _get_forecast_engine().get_all_forecasts(14)
    return [
        item
        for item in data
        if item.get("status") in ("stockout_risk", "reorder_now")
        and item.get("sku_id") not in ordered_ids
    ]


@app.post("/api/forecast/reorder/{sku_id}")
def create_reorder_signal(sku_id: str, request: Request):
    require_auth(request)
    engine = _get_forecast_engine()
    normalized_sku = _sanitize_text(sku_id)
    if not normalized_sku:
        raise HTTPException(status_code=400, detail="sku_id is required")

    get_db().execute_script(
        [
            """
            INSERT INTO movement_log (
                movement_id,
                sku_id,
                slot_id,
                zone_id,
                quantity,
                movement_type,
                status,
                moved_at
            )
            VALUES (
                {movement_id},
                {sku_id},
                'FORECAST',
                'FORECAST',
                0,
                'REORDER_INITIATED',
                'Pending',
                SYSTIMESTAMP
            )
            """.format(
                movement_id=sql_literal("REO-" + secrets.token_hex(10).upper()),
                sku_id=sql_literal(normalized_sku),
            ),
            "COMMIT",
        ]
    )
    reordered_skus.add(normalized_sku)
    engine.clear_cache()
    return {"success": True}


@app.post("/api/accept-recommendation")
def accept_recommendation(payload: AcceptRecommendationRequest, request: Request):
    require_auth(request)
    db = get_db()
    recommendation = db.fetch_one(
        """
        SELECT
            rec_id,
            sku_id,
            from_slot,
            to_slot,
            saving_m,
            status
        FROM slotting_recommendations
        WHERE rec_id = {rec_id}
        """.format(rec_id=int(payload.rec_id))
    )
    if recommendation is None:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    if recommendation.get("status") != "PENDING":
        raise HTTPException(status_code=409, detail="Recommendation is not pending")

    sku_id = sql_literal(recommendation["sku_id"])
    from_slot = sql_literal(recommendation["from_slot"])
    to_slot = sql_literal(recommendation["to_slot"])

    source_rows = db.fetch_all(
        """
        SELECT
            inv_id,
            sku_id,
            sku_name,
            slot_id,
            quantity
        FROM inventory
        WHERE sku_id = {sku_id}
          AND slot_id = {from_slot}
        ORDER BY inv_id
        """.format(sku_id=sku_id, from_slot=from_slot)
    )
    if not source_rows:
        raise HTTPException(
            status_code=404,
            detail="Source inventory for this recommendation was not found",
        )

    destination_slot = db.fetch_one(
        """
        SELECT slot_id
        FROM slots
        WHERE slot_id = {to_slot}
        """.format(to_slot=to_slot)
    )
    if destination_slot is None:
        raise HTTPException(status_code=404, detail="Recommended destination slot not found")

    destination_conflict = db.fetch_one(
        """
        SELECT COUNT(*) AS slot_count
        FROM inventory
        WHERE slot_id = {to_slot}
        """.format(to_slot=to_slot)
    )
    if int(destination_conflict["slot_count"] or 0):
        raise HTTPException(
            status_code=409,
            detail="Recommended destination slot is already occupied",
        )

    try:
        statements = _build_inventory_move_script(sku_id, from_slot, to_slot)
        statements.insert(
            -1,
            """
            UPDATE slotting_recommendations
            SET status = 'ACCEPTED'
            WHERE rec_id = {rec_id}
            """.format(rec_id=int(payload.rec_id)),
        )
        statements.insert(
            -1,
            """
            UPDATE slotting_recommendations
            SET status = 'SUPERSEDED'
            WHERE status = 'PENDING'
              AND rec_id <> {rec_id}
              AND (
                    sku_id = {sku_id}
                 OR from_slot IN ({from_slot}, {to_slot})
                 OR to_slot IN ({from_slot}, {to_slot})
              )
            """.format(
                rec_id=int(payload.rec_id),
                sku_id=sku_id,
                from_slot=from_slot,
                to_slot=to_slot,
            ),
        )
        db.execute_script(statements)
        _invalidate_cache("floor", "assets", "heatmap", "recommendations")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return {
        "message": "Recommendation accepted",
        "rec_id": int(payload.rec_id),
        "sku_id": recommendation["sku_id"],
        "from_slot": recommendation["from_slot"],
        "to_slot": recommendation["to_slot"],
        "saving_m": recommendation["saving_m"],
        "status": "ACCEPTED",
    }


@app.post("/api/move-inventory")
def move_inventory(payload: MoveInventoryRequest, request: Request):
    require_auth(request)
    if payload.from_slot == payload.to_slot:
        raise HTTPException(
            status_code=400,
            detail="from_slot and to_slot must be different values",
        )

    db = get_db()
    sku_id = sql_literal(payload.sku_id)
    from_slot = sql_literal(payload.from_slot)
    to_slot = sql_literal(payload.to_slot)

    try:
        source_rows = db.fetch_all(
            """
            SELECT
                inv_id,
                sku_id,
                sku_name,
                slot_id,
                quantity,
                weight_kg,
                placed_at,
                category
            FROM inventory
            WHERE sku_id = {sku_id}
              AND slot_id = {from_slot}
            ORDER BY inv_id
            """.format(sku_id=sku_id, from_slot=from_slot)
        )
        if not source_rows:
            raise HTTPException(
                status_code=404,
                detail="No inventory row found for the requested sku_id and from_slot",
            )

        destination_slot = db.fetch_one(
            """
            SELECT slot_id
            FROM slots
            WHERE slot_id = {to_slot}
            """.format(to_slot=to_slot)
        )
        if destination_slot is None:
            raise HTTPException(
                status_code=404,
                detail="Destination slot does not exist",
            )

        destination_conflict = db.fetch_one(
            """
            SELECT COUNT(*) AS slot_count
            FROM inventory
            WHERE slot_id = {to_slot}
            """.format(to_slot=to_slot)
        )
        if int(destination_conflict["slot_count"] or 0):
            raise HTTPException(
                status_code=409,
                detail="Destination slot is already occupied",
            )

        db.execute_script(_build_inventory_move_script(sku_id, from_slot, to_slot))
        _invalidate_cache("floor", "assets", "heatmap", "recommendations")
    except HTTPException:
        raise
    except Exception as exc:
        try:
            db.execute("ROLLBACK")
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(exc))

    updated_rows = db.fetch_all(
        """
        SELECT
            inv_id,
            sku_id,
            sku_name,
            slot_id,
            quantity,
            weight_kg,
            placed_at,
            category
        FROM inventory
        WHERE sku_id = {sku_id}
          AND slot_id = {slot_id}
        ORDER BY inv_id
        """.format(sku_id=sku_id, slot_id=to_slot)
    )

    return {
        "message": "Inventory updated",
        "sku_id": payload.sku_id,
        "from_slot": payload.from_slot,
        "to_slot": payload.to_slot,
        "rows_updated": len(updated_rows),
        "inventory": updated_rows,
    }


@app.get("/api/session")
def get_session(request: Request):
    session_id = request.session.get("session_id")
    active_sessions = getattr(app.state, "active_sessions", set())
    authenticated = bool(
        request.session.get("authenticated") and session_id in active_sessions
    )
    return {
        "authenticated": authenticated,
        "username": request.session.get("username") if authenticated else None,
    }


@app.post("/api/login")
def login(payload: LoginRequest, request: Request):
    username = (payload.username or "").strip()
    password = payload.password or ""
    if username != settings.app_username or password != settings.app_password:
        raise HTTPException(status_code=401, detail="Invalid username or password")

    session_id = secrets.token_urlsafe(24)
    request.session.clear()
    request.session.update(
        {
            "authenticated": True,
            "username": username,
            "session_id": session_id,
        }
    )
    app.state.active_sessions.add(session_id)
    return {"authenticated": True, "username": username}


@app.post("/api/logout")
def logout(request: Request):
    session_id = request.session.get("session_id")
    if session_id in app.state.active_sessions:
        app.state.active_sessions.remove(session_id)
    request.session.clear()
    return {"authenticated": False}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("warehouse_api.main:app", host="0.0.0.0", port=8000, reload=True)
