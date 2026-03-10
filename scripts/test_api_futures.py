"""Prueba la API (Docker): health, ticker futures y respuesta de crear orden.
Uso: API_BASE_URL=http://localhost:8000 python scripts/test_api_futures.py
"""
import os
import sys
import json

try:
    import requests
except ImportError:
    print("pip install requests")
    sys.exit(1)

BASE = os.environ.get("API_BASE_URL", "http://localhost:8000").rstrip("/")
TIMEOUT = 30  # Binance client init + sync hora la primera vez puede tardar

def main():
    print(f"API_BASE_URL = {BASE}\n")

    # 1. Health
    print("1. GET /health")
    try:
        r = requests.get(f"{BASE}/health", timeout=TIMEOUT)
        print(f"   status={r.status_code} body={r.json()}")
    except Exception as e:
        print(f"   ERROR: {e}")
        return

    # 2. Futures ticker
    print("\n2. GET /futures/market/ticker/BTCUSDT")
    try:
        r = requests.get(f"{BASE}/futures/market/ticker/BTCUSDT", timeout=TIMEOUT)
        print(f"   status={r.status_code}")
        if r.status_code == 200:
            d = r.json()
            data = d.get("data", {})
            print(f"   last_price={data.get('last_price')} symbol={data.get('symbol')}")
        else:
            print(f"   body={r.text[:300]}")
    except Exception as e:
        print(f"   ERROR: {e}")
        return

    # 3. POST /futures/order/create (MARKET) - notional mínimo Futures Testnet = 100 USDT
    # Timeout 30s: primera vez hace sync hora Binance + llamada a API puede tardar
    print("\n3. POST /futures/order/create (MARKET BUY ~0.002 BTCUSDT, notional >= 100)")
    try:
        r = requests.post(
            f"{BASE}/futures/order/create",
            json={
                "symbol": "BTCUSDT",
                "side": "BUY",
                "order_type": "MARKET",
                "quantity": 0.002,
                "reduce_only": False,
            },
            timeout=30,
        )
        print(f"   status={r.status_code}")
        print(f"   body={json.dumps(r.json(), indent=2)[:800]}")
        if r.status_code == 200:
            data = (r.json() or {}).get("data") or r.json()
            oid = data.get("order_id") or data.get("orderId")
            print(f"   -> orderId en Binance Testnet: {oid}")
    except Exception as e:
        print(f"   ERROR: {e}")

    print("\nDone.")

if __name__ == "__main__":
    main()
