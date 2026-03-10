#!/usr/bin/env python3
"""
Backfill de métricas del monitor: realized_pnl y fct_risk_cycle_stats.
- Añade columna realized_pnl a fct_order_history si no existe.
- Obtiene income history de Binance (REALIZED_PNL) y actualiza órdenes EXIT ejecutadas.
- Crea fct_risk_cycle_stats si no existe (run_risk_engine la poblará en próximos ciclos).
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv
load_dotenv(REPO_ROOT / ".env")

import duckdb


def _ensure_realized_pnl_column(conn: duckdb.DuckDBPyConnection) -> None:
    """Añade realized_pnl a fct_order_history si no existe."""
    try:
        conn.execute("ALTER TABLE fct_order_history ADD COLUMN realized_pnl DOUBLE")
    except Exception:
        pass  # ya existe


def _backfill_from_binance_income(conn: duckdb.DuckDBPyConnection) -> int:
    """Obtiene REALIZED_PNL de Binance y actualiza fct_order_history. Devuelve filas actualizadas."""
    try:
        from binance.client import Client
        api_key = os.getenv("BINANCE_API_KEY")
        secret = os.getenv("BINANCE_SECRET_KEY")
        testnet = os.getenv("BINANCE_TESTNET", "false").lower() == "true"
        if not api_key or not secret:
            print("BINANCE_API_KEY/SECRET no configurados. Saltando backfill desde Binance.")
            return 0

        client = Client(api_key, secret, testnet=testnet)
        # Últimos 30 días de income REALIZED_PNL (Binance retiene ~3 meses)
        end_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        start_ms = int((datetime.now(timezone.utc) - timedelta(days=30)).timestamp() * 1000)

        incomes = []
        while True:
            batch = client.futures_income_history(
                incomeType="REALIZED_PNL",
                startTime=start_ms,
                endTime=end_ms,
                limit=1000,
            )
            if not batch:
                break
            incomes.extend(batch)
            if len(batch) < 1000:
                break
            start_ms = int(batch[-1]["time"]) + 1

        if not incomes:
            print("  Binance income: 0 registros REALIZED_PNL en últimos 7 días")
            return 0

        # EXIT orders sin realized_pnl
        exit_rows = conn.execute("""
            SELECT event_time, symbol FROM fct_order_history
            WHERE status = 'EXECUTED' AND signal_type IN ('EXIT_LONG', 'EXIT_SHORT')
            AND (realized_pnl IS NULL OR realized_pnl = 0)
        """).fetchall()
        if not exit_rows:
            print("  No hay EXIT ejecutados sin realized_pnl. Nada que actualizar.")
            return 0

        print(f"  Binance income: {len(incomes)} registros | EXIT pendientes: {len(exit_rows)}")
        updated = 0
        for inc in incomes:
            sym = inc.get("symbol", "")
            amt = float(inc.get("income", 0) or 0)
            ts_ms = int(inc.get("time", 0))
            if not sym or ts_ms == 0:
                continue
            # Buscar EXIT ejecutado en ventana ±60 min (Binance puede registrar con delay)
            ts_lo = datetime.fromtimestamp((ts_ms - 3600000) / 1000, tz=timezone.utc).replace(tzinfo=None)
            ts_hi = datetime.fromtimestamp((ts_ms + 3600000) / 1000, tz=timezone.utc).replace(tzinfo=None)
            try:
                rows = conn.execute("""
                    SELECT event_time FROM fct_order_history
                    WHERE symbol = ? AND status = 'EXECUTED'
                    AND signal_type IN ('EXIT_LONG', 'EXIT_SHORT')
                    AND event_time >= ? AND event_time <= ?
                    AND (realized_pnl IS NULL OR realized_pnl = 0)
                """, [sym, ts_lo, ts_hi]).fetchall()
                for (et,) in rows:
                    conn.execute(
                        "UPDATE fct_order_history SET realized_pnl = ? WHERE symbol = ? AND event_time = ?",
                        [amt, sym, et],
                    )
                    updated += 1
                    break  # un match por income
            except Exception:
                pass
        return updated
    except ImportError:
        print("binance no instalado. pip install python-binance")
        return 0
    except Exception as e:
        print(f"Error backfill Binance income: {e}")
        return 0


def _ensure_risk_stats_table(conn: duckdb.DuckDBPyConnection) -> None:
    """Crea fct_risk_cycle_stats si no existe."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS fct_risk_cycle_stats (
            event_time TIMESTAMP, raw_count INTEGER, approved_count INTEGER, rejected_count INTEGER
        )
    """)


def main() -> int:
    db_path = os.environ.get("DBT_DUCKDB_PATH", str(REPO_ROOT / "artifacts" / "warehouse" / "crypto.duckdb"))
    if not os.path.exists(db_path):
        print(f"DuckDB no encontrado: {db_path}")
        return 1

    conn = duckdb.connect(db_path)
    tables = [t[0] for t in conn.execute("SHOW TABLES").fetchall()]

    if "fct_order_history" in tables:
        _ensure_realized_pnl_column(conn)
        updated = _backfill_from_binance_income(conn)
        print(f"Backfill realized_pnl: {updated} filas actualizadas desde Binance")
    else:
        print("fct_order_history no existe. Nada que backfill.")

    _ensure_risk_stats_table(conn)
    print("fct_risk_cycle_stats creada/verificada. run_risk_engine la poblará en próximos ciclos.")

    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
