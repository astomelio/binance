#!/usr/bin/env python3
import duckdb
import os
import pandas as pd
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = os.environ.get("DBT_DUCKDB_PATH", str(REPO_ROOT / "artifacts" / "warehouse" / "crypto.duckdb"))

def get_performance_window(conn, start_dt, label):
    query = """
        SELECT 
            COUNT(*) as trades,
            COALESCE(SUM(realized_pnl), 0) as pnl,
            SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END) as wins
        FROM fct_order_history
        WHERE event_time >= ? AND realized_pnl IS NOT NULL
    """
    res = conn.execute(query, [start_dt]).fetchone()
    trades = res[0]
    pnl = float(res[1])
    win_rate = (res[2] / trades * 100) if trades > 0 else 0.0
    return {
        "Periodo": label,
        "Operaciones": trades,
        "PnL Realizado (USDT)": round(pnl, 4),
        "Win Rate %": round(win_rate, 1)
    }

def main():
    print("=== ANÁLISIS DE RENDIMIENTO REAL POR PERIODOS ===")
    
    if not Path(DB_PATH).exists():
        print(f"Error: No se encontró DuckDB en {DB_PATH}")
        return

    conn = duckdb.connect(DB_PATH, read_only=True)
    now = datetime.now(timezone.utc)
    
    windows = [
        (now - timedelta(days=1), "Últimas 24h"),
        (now - timedelta(days=7), "Últimos 7 días"),
        (now - timedelta(days=30), "Últimos 30 días"),
        (datetime(2020, 1, 1, tzinfo=timezone.utc), "Todo el histórico"),
    ]
    
    stats = []
    for dt, label in windows:
        stats.append(get_performance_window(conn, dt, label))
    
    df = pd.DataFrame(stats)
    print("\n" + df.to_string(index=False))
    
    # Detalle por modelo
    print("\n=== RENDIMIENTO POR MODELO (HISTÓRICO) ===")
    query_models = """
        SELECT 
            model_id,
            COUNT(*) as trades,
            SUM(realized_pnl) as pnl,
            AVG(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END) * 100 as win_rate
        FROM fct_order_history
        WHERE realized_pnl IS NOT NULL
        GROUP BY 1
        ORDER BY pnl DESC
    """
    try:
        models_df = conn.execute(query_models).fetchdf()
        if not models_df.empty:
            print(models_df.to_string(index=False))
        else:
            print("No hay datos de modelos todavía.")
    except Exception:
        print("Error al consultar rendimiento por modelo.")
        
    conn.close()

if __name__ == "__main__":
    main()
