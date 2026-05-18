import math
import random
import time
from datetime import date, datetime, timedelta

import numpy as np
from sklearn.linear_model import LinearRegression

from warehouse_api.database import sql_literal


def _to_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value), "%Y-%m-%d").date()


def _sql_date(value):
    return "TO_DATE({0}, 'YYYY-MM-DD')".format(sql_literal(value.strftime("%Y-%m-%d")))

def _history_days(days):
    return max(1, int(days or 1))


def _has_forecast_history_index(db):
    rows = db.fetch_all(
        """
        SELECT
            index_name,
            LISTAGG(column_name, ',') WITHIN GROUP (ORDER BY column_position) AS columns_list
        FROM user_ind_columns
        WHERE table_name = 'FORECAST_HISTORY'
        GROUP BY index_name
        """
    )
    for row in rows:
        if row.get("columns_list") == "SKU_ID,PICK_DATE":
            return True
    return False


def seed_forecast_history(db):
    today = datetime.utcnow().date()
    start_date = today - timedelta(days=89)

    sku_rows = db.fetch_all(
        """
        SELECT
            sku AS sku_id
        FROM product
        WHERE sku IS NOT NULL
        ORDER BY sku
        """
    )
    if not sku_rows:
        return 0

    sales_rows = db.fetch_all(
        """
        SELECT
            p.sku AS sku_id,
            TRUNC(ds.sale_date) AS pick_date,
            NVL(SUM(ds.quantity_sold), 0) AS sales_qty,
            COUNT(*) AS pick_count
        FROM daily_sales ds
        JOIN product p
            ON ds.product_id = p.id
        WHERE ds.sale_date >= TRUNC(SYSTIMESTAMP) - 90
        GROUP BY p.sku, TRUNC(ds.sale_date)
        """
    )
    pick_rows = db.fetch_all(
        """
        SELECT
            sku_id,
            TRUNC(picked_at) AS pick_date,
            COUNT(*) AS pick_count
        FROM pick_history
        WHERE picked_at >= TRUNC(SYSTIMESTAMP) - 90
        GROUP BY sku_id, TRUNC(picked_at)
        """
    )
    frequency_rows = db.fetch_all(
        """
        SELECT
            sku_id,
            COUNT(*) AS pick_frequency
        FROM pick_history
        WHERE picked_at >= SYSTIMESTAMP - NUMTODSINTERVAL(30, 'DAY')
        GROUP BY sku_id
        """
    )

    sales_map = {}
    for row in sales_rows:
        key = (row["sku_id"], _to_date(row["pick_date"]))
        sales_map[key] = {
            "pick_count": int(row.get("pick_count") or 0),
            "sales_qty": int(row.get("sales_qty") or 0),
            "source": "actual",
        }

    pick_map = {}
    for row in pick_rows:
        key = (row["sku_id"], _to_date(row["pick_date"]))
        pick_map[key] = int(row.get("pick_count") or 0)

    frequency_map = {
        row["sku_id"]: int(row.get("pick_frequency") or 0)
        for row in frequency_rows
        if row.get("sku_id")
    }

    statements = []
    inserted = 0

    for sku_row in sku_rows:
        sku_id = sku_row.get("sku_id")
        if not sku_id:
            continue

        pick_frequency = frequency_map.get(sku_id, 1)
        avg_daily = float(pick_frequency) / 30.0
        if avg_daily > 0.5:
            tier = "hot"
        elif avg_daily > 0.15:
            tier = "medium"
        else:
            tier = "slow"

        for offset in range(90):
            current_date = start_date + timedelta(days=offset)
            key = (sku_id, current_date)

            if key in sales_map:
                record = sales_map[key]
            elif key in pick_map:
                record = {
                    "pick_count": pick_map[key],
                    "sales_qty": 0,
                    "source": "actual",
                }
            else:
                generator = random.Random("{0}:{1}".format(sku_id, current_date.isoformat()))
                weekday = current_date.weekday()
                if tier == "hot":
                    base = avg_daily
                    trend = 0.015 * offset
                    weekend_factor = 0.65 if weekday in (5, 6) else 1.0
                    noise = generator.gauss(0, max(base * 0.25, 0.05))
                    pick_count = max(0, round((base + trend + noise) * weekend_factor))
                    sales_qty = max(0, round(pick_count * generator.uniform(0.8, 1.2)))
                elif tier == "medium":
                    deviation = max(avg_daily * 0.4, 0.1)
                    pick_count = max(0, round(generator.gauss(avg_daily, deviation)))
                    sales_qty = pick_count
                else:
                    pick_count = 1 if generator.random() < avg_daily else 0
                    sales_qty = pick_count

                record = {
                    "pick_count": int(pick_count),
                    "sales_qty": int(sales_qty),
                    "source": "synthetic",
                }

            statements.append(
                """
                MERGE INTO forecast_history fh
                USING DUAL
                    ON (
                        fh.sku_id = {sku_id}
                        AND fh.pick_date = {_sql_date}
                    )
                WHEN NOT MATCHED THEN
                    INSERT (
                        sku_id,
                        pick_date,
                        pick_count,
                        sales_qty,
                        source
                    )
                    VALUES (
                        {sku_id},
                        {_sql_date},
                        {pick_count},
                        {sales_qty},
                        {source}
                    )
                """.format(
                    sku_id=sql_literal(sku_id),
                    _sql_date=_sql_date(current_date),
                    pick_count=int(record["pick_count"]),
                    sales_qty=int(record["sales_qty"]),
                    source=sql_literal(record["source"]),
                )
            )
            inserted += 1

            if len(statements) >= 250:
                statements.append("COMMIT")
                db.execute_script(statements)
                statements = []

    if statements:
        statements.append("COMMIT")
        db.execute_script(statements)

    return inserted


def ensure_forecast_history_support(db):
    table_row = db.fetch_one(
        """
        SELECT COUNT(*) AS table_count
        FROM user_tables
        WHERE table_name = 'FORECAST_HISTORY'
        """
    )
    if int(table_row.get("table_count") or 0) == 0:
        db.execute_script(
            [
                """
                CREATE TABLE forecast_history (
                    id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                    sku_id VARCHAR2(20) NOT NULL,
                    pick_date DATE NOT NULL,
                    pick_count NUMBER DEFAULT 0,
                    sales_qty NUMBER DEFAULT 0,
                    source VARCHAR2(20) DEFAULT 'synthetic',
                    created_at TIMESTAMP DEFAULT SYSTIMESTAMP,
                    CONSTRAINT uq_fh_sku_date UNIQUE (sku_id, pick_date)
                )
                """,
                "COMMIT",
            ]
        )

    if not _has_forecast_history_index(db):
        db.execute_script(
            [
                """
                CREATE INDEX idx_fh_sku_date
                ON forecast_history(sku_id, pick_date)
                """,
                "COMMIT",
            ]
        )

    count_row = db.fetch_one(
        """
        SELECT COUNT(*) AS row_count
        FROM forecast_history
        """
    )
    if int(count_row.get("row_count") or 0) == 0:
        seed_forecast_history(db)


def upsert_forecast_actual(db, sku_id, quantity, pick_date=None):
    normalized_date = pick_date or datetime.utcnow().date()
    amount = max(0, int(quantity or 0))
    db.execute_script(
        [
            """
            MERGE INTO forecast_history fh
            USING DUAL
                ON (
                    fh.sku_id = {sku_id}
                    AND fh.pick_date = {pick_date}
                )
            WHEN MATCHED THEN
                UPDATE SET
                    fh.pick_count = NVL(fh.pick_count, 0) + {amount},
                    fh.sales_qty = NVL(fh.sales_qty, 0) + {amount},
                    fh.source = 'actual',
                    fh.created_at = SYSTIMESTAMP
            WHEN NOT MATCHED THEN
                INSERT (
                    sku_id,
                    pick_date,
                    pick_count,
                    sales_qty,
                    source
                )
                VALUES (
                    {sku_id},
                    {pick_date},
                    {amount},
                    {amount},
                    'actual'
                )
            """.format(
                sku_id=sql_literal(sku_id),
                pick_date=_sql_date(normalized_date),
                amount=amount,
            ),
            "COMMIT",
        ]
    )


class ForecastEngine:
    CACHE_TTL = 300

    def __init__(self, db):
        self.db = db
        self._cache = {}

    def clear_cache(self):
        self._cache = {}

    def get_inventory_upload_skus(self):
        rows = self.db.fetch_all(
            """
            SELECT DISTINCT sku_id
            FROM movement_log
            WHERE movement_type = 'INBOUND'
              AND status = 'Assigned'
              AND sku_id IS NOT NULL
            """
        )
        return {row["sku_id"] for row in rows if row.get("sku_id")}

    def get_history(self, sku_id, days=90):
        rows = self.db.fetch_all(
            """
            SELECT
                pick_date,
                pick_count,
                sales_qty,
                source
            FROM forecast_history
            WHERE sku_id = {sku_id}
              AND pick_date >= TRUNC(SYSTIMESTAMP) - {days}
            ORDER BY pick_date ASC
            """.format(
                sku_id=sql_literal(sku_id),
                days=_history_days(days),
            )
        )
        if not rows:
            return []

        normalized = []
        for row in rows:
            normalized.append(
                {
                    "date": _to_date(row["pick_date"]),
                    "pick_count": int(row.get("pick_count") or 0),
                    "sales_qty": int(row.get("sales_qty") or 0),
                    "source": row.get("source") or "synthetic",
                }
            )

        by_date = {row["date"]: row for row in normalized}
        filled = []
        cursor = normalized[0]["date"]
        end_date = normalized[-1]["date"]
        while cursor <= end_date:
            row = by_date.get(cursor)
            if row is None:
                filled.append(
                    {
                        "date": cursor,
                        "pick_count": 0,
                        "sales_qty": 0,
                        "source": "synthetic",
                    }
                )
            else:
                filled.append(row)
            cursor += timedelta(days=1)
        return filled

    def forecast_sku(self, sku_id, horizon_days=14):
        horizon_days = _history_days(horizon_days)
        history = self.get_history(sku_id, 90)
        if not history:
            today = datetime.utcnow().date()
            forecast = []
            for index in range(horizon_days):
                forecast.append(
                    {
                        "date": (today + timedelta(days=index + 1)).isoformat(),
                        "predicted": 0.0,
                        "lower": 0.0,
                        "upper": 0.0,
                    }
                )
            return {
                "sku_id": sku_id,
                "historical": [],
                "forecast": forecast,
                "avg_daily_demand": 0.0,
                "forecast_total": 0.0,
                "slope": 0.0,
                "trend": "stable",
                "model": "linear_regression",
            }

        y = np.array(
            [
                row["sales_qty"] if int(row["sales_qty"] or 0) > 0 else int(row["pick_count"] or 0)
                for row in history
            ],
            dtype=float,
        )
        y_smooth = np.array(
            [
                float(np.mean(y[max(0, index - 6) : index + 1]))
                for index in range(len(y))
            ],
            dtype=float,
        )
        x = np.array(range(len(y)), dtype=float).reshape(-1, 1)

        if len(history) < 7:
            mean_value = float(np.mean(y)) if len(y) else 0.0
            y_pred = np.array([mean_value for _ in range(horizon_days)], dtype=float)
            model_fit = y_smooth
            slope = 0.0
        else:
            model = LinearRegression()
            model.fit(x, y_smooth)
            x_future = np.array(range(len(y), len(y) + horizon_days), dtype=float).reshape(-1, 1)
            y_pred = model.predict(x_future).flatten()
            model_fit = model.predict(x).flatten()
            slope = float(model.coef_[0])

        y_pred = np.array([max(0.0, float(value)) for value in y_pred], dtype=float)
        residuals = y_smooth - model_fit
        std = float(np.std(residuals)) if len(residuals) else 0.0
        lower = [max(0.0, float(value) - std) for value in y_pred]
        upper = [float(value) + std for value in y_pred]

        if slope > 0.05:
            trend = "rising"
        elif slope < -0.05:
            trend = "falling"
        else:
            trend = "stable"

        last_history_date = history[-1]["date"]
        historical = []
        for index, row in enumerate(history):
            historical.append(
                {
                    "date": row["date"].isoformat(),
                    "actual": int(y[index]),
                    "smoothed": round(float(y_smooth[index]), 3),
                    "source": row["source"],
                }
            )

        forecast = []
        for index in range(horizon_days):
            future_date = last_history_date + timedelta(days=index + 1)
            forecast.append(
                {
                    "date": future_date.isoformat(),
                    "predicted": round(float(y_pred[index]), 3),
                    "lower": round(float(lower[index]), 3),
                    "upper": round(float(upper[index]), 3),
                }
            )

        avg_window = y[-30:] if len(y) >= 30 else y
        avg_daily = float(np.mean(avg_window)) if len(avg_window) else 0.0
        forecast_total = float(np.sum(y_pred)) if len(y_pred) else 0.0

        return {
            "sku_id": sku_id,
            "historical": historical,
            "forecast": forecast,
            "avg_daily_demand": round(avg_daily, 3),
            "forecast_total": round(forecast_total, 3),
            "slope": round(slope, 6),
            "trend": trend,
            "model": "linear_regression",
        }

    def get_current_stock(self, sku_id):
        row = self.db.fetch_one(
            """
            SELECT COUNT(*) AS stock
            FROM inventory i
            JOIN slots s
                ON i.slot_id = s.slot_id
            WHERE i.sku_id = {sku_id}
              AND s.is_occupied = 1
            """.format(sku_id=sql_literal(sku_id))
        )
        return int(row.get("stock") or 0) if row else 0

    def compute_risk(self, sku_id, sku_name, horizon_days=14):
        fc = self.forecast_sku(sku_id, horizon_days)
        stock = self.get_current_stock(sku_id)
        avg = float(fc["avg_daily_demand"] or 0.0)

        days_until_stockout = (float(stock) / avg) if avg > 0.1 else 999.0
        reorder_qty = int(math.ceil(avg * int(horizon_days) * 1.25)) if avg > 0 else 0
        covers_days = (float(reorder_qty) / avg) if avg > 0.1 else 999.0

        if avg < 0.2:
            status = "slow_moving"
        elif days_until_stockout < 7:
            status = "stockout_risk"
        elif days_until_stockout < 14:
            status = "reorder_now"
        else:
            status = "healthy"

        return {
            "sku_id": sku_id,
            "sku_name": sku_name or sku_id,
            "current_stock": stock,
            "avg_daily_demand": round(avg, 2),
            "forecast_total": round(float(fc["forecast_total"] or 0.0), 1),
            "days_until_stockout": round(days_until_stockout, 1),
            "reorder_qty": reorder_qty,
            "covers_days": round(covers_days, 1),
            "slope": float(fc["slope"] or 0.0),
            "trend": fc["trend"],
            "status": status,
        }

    def get_all_forecasts(self, horizon_days=14):
        horizon_days = _history_days(horizon_days)
        cache_key = "horizon_{0}".format(horizon_days)
        cached = self._cache.get(cache_key)
        now = time.time()
        if cached is not None and (now - cached["ts"]) < self.CACHE_TTL:
            return cached["data"]

        inventory_upload_skus = self.get_inventory_upload_skus()
        sku_rows = self.db.fetch_all(
            """
            SELECT
                p.sku AS sku_id,
                p.name AS sku_name,
                TO_CHAR(ml.latest_inbound_at, 'YYYY-MM-DD"T"HH24:MI:SS') AS latest_inbound_at
            FROM product p
            LEFT JOIN (
                SELECT
                    sku_id,
                    MAX(moved_at) AS latest_inbound_at
                FROM movement_log
                WHERE movement_type = 'INBOUND'
                  AND status = 'Assigned'
                GROUP BY sku_id
            ) ml
                ON ml.sku_id = p.sku
            WHERE p.sku IS NOT NULL
            ORDER BY p.sku
            """
        )
        results = [
            {
                **self.compute_risk(row["sku_id"], row.get("sku_name"), horizon_days),
                "latest_inbound_at": row.get("latest_inbound_at"),
            }
            for row in sku_rows
            if row.get("sku_id") and row["sku_id"] not in inventory_upload_skus
        ]

        status_order = {
            "stockout_risk": 0,
            "reorder_now": 1,
            "healthy": 2,
            "slow_moving": 3,
        }
        results.sort(
            key=lambda item: (
                status_order.get(item["status"], 99),
                float(item.get("days_until_stockout") or 999),
                item["sku_id"],
            )
        )
        self._cache[cache_key] = {"ts": now, "data": results}
        return results
