"""
Registra posiciones abiertas actuales en Binance como operaciones ejecutadas en fct_order_history.
Útil cuando el short/long se abrió antes de tener el historial. Ejecutar una vez.

Uso: DBT_DUCKDB_PATH=... API_BASE_URL=... python scripts/backfill_order_history_from_positions.py
"""
import os
import sys
from pathlib import Path
from datetime import datetime, timezone

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import duckdb


def main():
    db_path = os.environ.get("DBT_DUCKDB_PATH", str(REPO_ROOT / "artifacts" / "warehouse" / "crypto.duckdb"))
    if not os.path.isabs(db_path):
        db_path = str(REPO_ROOT / db_path)

    api_url = os.environ.get("API_BASE_URL", "http://localhost:8000")
    try:
        from trading_lib.api_client import BinanceConnectorClient
        client = BinanceConnectorClient(base_url=api_url)
        positions = client.get_futures_positions()
    except Exception as e:
        print(f"No se pudo conectar a la API: {e}")
        return 1

    conn = duckdb.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS fct_order_history (
            event_time TIMESTAMP, symbol VARCHAR, signal_type VARCHAR,
            size_usd DOUBLE, confidence DOUBLE, risk_vol_multiplier DOUBLE, status VARCHAR, model_id VARCHAR
        )
    """)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    inserted = 0
    for p in positions:
        amt = float(p.get("positionAmt", p.get("position_amt", 0)) or 0)
        if amt == 0:
            continue
        symbol = p.get("symbol", "")
        entry = float(p.get("entryPrice", p.get("entry_price", 0)) or 0)
        size_usd = abs(amt) * entry if entry else 0
        ps = p.get("position_side", "")
        signal_type = "LONG" if amt > 0 else "SHORT" if ps in ("BOTH", "") else ps
        try:
            conn.execute("""
                INSERT INTO fct_order_history (event_time, symbol, signal_type, size_usd, confidence, risk_vol_multiplier, status, model_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, [now, symbol, signal_type, size_usd, 0.5, 1.0, "EXECUTED", "quant_alpha_entry_lgbm@champion"])
            inserted += 1
            print(f"  Registrado: {symbol} {signal_type} size_usd={size_usd:.2f}")
        except Exception as e:
            print(f"  Error insertando {symbol}: {e}")

    conn.close()
    print(f"\nBackfill: {inserted} posiciones registradas en fct_order_history")
    return 0


if __name__ == "__main__":
    sys.exit(main())
