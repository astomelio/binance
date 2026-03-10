"""
Comprueba: (1) órdenes PENDING en fct_approved_orders y (2) órdenes recientes en Binance Futures Testnet.
Uso: DBT_DUCKDB_PATH=... API_BASE_URL=http://localhost:8000 python scripts/check_orders_binance.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

def main():
    db_path = os.environ.get("DBT_DUCKDB_PATH", "artifacts/warehouse/crypto.duckdb")
    api_url = os.environ.get("API_BASE_URL", "http://localhost:8000").rstrip("/")

    print("=== 1. Órdenes en la DB (fct_approved_orders) ===")
    try:
        import duckdb
        conn = duckdb.connect(db_path)
        try:
            pending = conn.execute("""
                SELECT event_time, symbol, signal_type, size_usd, status
                FROM fct_approved_orders WHERE status = 'PENDING'
            """).fetchdf()
            print(f"PENDING: {len(pending)}")
            if not pending.empty:
                print(pending.to_string())
            else:
                print("  (ninguna; el risk engine no ha generado órdenes o ya se ejecutaron)")

            recent = conn.execute("""
                SELECT event_time, symbol, signal_type, status
                FROM fct_approved_orders ORDER BY event_time DESC LIMIT 10
            """).fetchdf()
            print("\nÚltimas 10 (cualquier status):")
            print(recent.to_string() if not recent.empty else "  (tabla vacía)")
        finally:
            conn.close()
    except Exception as e:
        print(f"  Error: {e}")

    print("\n=== 2. Órdenes recientes en Binance Futures Testnet (API) ===")
    try:
        import requests
        r = requests.get(f"{api_url}/futures/order/BTCUSDT", params={"limit": 10}, timeout=10)
        if r.status_code != 200:
            print(f"  API error {r.status_code}: {r.text[:200]}")
        else:
            data = r.json()
            orders = data.get("data", [])
            print(f"  Últimas {len(orders)} órdenes BTCUSDT en Testnet:")
            for o in orders[:5]:
                print(f"    orderId={o.get('order_id')} symbol={o.get('symbol')} side={o.get('side')} status={o.get('status')}")
            if not orders:
                print("  (ninguna orden; asegúrate de usar Binance Futures TESTNET y que la API tenga las keys correctas)")
    except Exception as e:
        print(f"  Error: {e}")

    print("\nVer Futures Testnet en el navegador: https://testnet.binancefuture.com")

if __name__ == "__main__":
    main()
