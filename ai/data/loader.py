"""Load decision_features from DuckDB. Single source of truth for ML."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import duckdb

from ai.config import get_warehouse_path

if TYPE_CHECKING:
    from duckdb import DuckDBPyConnection


def get_connection(db_path: str | None = None) -> DuckDBPyConnection:
    import time
    path = db_path or get_warehouse_path()
    for attempt in range(12):
        try:
            return duckdb.connect(path, read_only=True)
        except Exception as e:
            if "Could not set lock on file" in str(e):
                time.sleep(5)
            else:
                raise
    raise RuntimeError("Failed to acquire DuckDB lock for reading after 1 minute.")


def load_decision_features(
    conn: DuckDBPyConnection | None = None,
    db_path: str | None = None,
    horizon: str = "4h",
    symbols: list[str] | None = None,
    start: datetime | str | None = None,
    end: datetime | str | None = None,
    label_not_null: bool = False,
) -> list[dict]:
    """
    Load decision_features from DuckDB.
    Returns list of dicts sorted by event_time.
    """
    label_col = {"1h": "fwd_return_1h", "4h": "fwd_return_4h", "24h": "fwd_return_24h"}.get(
        horizon, "fwd_return_4h"
    )
    own_conn = False
    if conn is None:
        conn = get_connection(db_path)
        own_conn = True

    try:
        q = "SELECT * FROM main.decision_features"
        conditions = []
        params: list = []
        if label_not_null:
            conditions.append(f"{label_col} IS NOT NULL")
        if symbols:
            placeholders = ", ".join(f"'{s}'" for s in symbols)
            conditions.append(f"symbol IN ({placeholders})")
        if start is not None:
            params.append(start.isoformat() if isinstance(start, datetime) else start)
            conditions.append(f"cast(event_time as timestamp) >= ${len(params)}")
        if end is not None:
            params.append(end.isoformat() if isinstance(end, datetime) else end)
            conditions.append(f"cast(event_time as timestamp) <= ${len(params)}")

        if conditions:
            q += " WHERE " + " AND ".join(conditions)
        q += " ORDER BY event_time, symbol"

        rows = conn.execute(q, params).fetchall() if params else conn.execute(q).fetchall()
        cols = [d[0] for d in conn.execute("DESCRIBE main.decision_features").fetchall()]
        out = [dict(zip(cols, r)) for r in rows]
        for row in out:
            if "cross_exchange_spread_bps" not in row and "cross_exchange_bid_ask_bps_mean" in row:
                row["cross_exchange_spread_bps"] = row.get("cross_exchange_bid_ask_bps_mean") or 0
        return out
    finally:
        if own_conn:
            conn.close()
