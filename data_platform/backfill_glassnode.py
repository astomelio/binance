"""
Backfill Glassnode: métricas on-chain (BTC dominance, MVRV, SOPR, etc.).
Requiere GLASSNODE_API_KEY. La API es de pago; el plan más barato incluye métricas básicas (T1).

Métricas que suelen estar en tier gratuito/básico:
- market/btc_dominance
- market/mvrv
- market/marketcap_usd
- indicators/sopr (Spent Output Profit Ratio)

Uso:
    GLASSNODE_API_KEY=xxx python -m data_platform.backfill_glassnode
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import requests

from data_platform.config import DataPlatformConfig
from data_platform.storage.lake_writer import LakeWriter

BASE = "https://api.glassnode.com/v1/metrics"


def _fetch(
    api_key: str,
    path: str,
    asset: str = "BTC",
    since_ts: int | None = None,
    until_ts: int | None = None,
    interval: str = "24h",
) -> List[Dict[str, Any]]:
    url = f"{BASE}/{path}"
    params = {"a": asset, "api_key": api_key, "i": interval}
    if since_ts:
        params["s"] = since_ts
    if until_ts:
        params["u"] = until_ts
    try:
        r = requests.get(url, params=params, timeout=60)
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else []
    except Exception:
        return []


def backfill_glassnode(
    writer: LakeWriter,
    api_key: str,
    start_date: str = "2023-03-01",
    assets: List[str] | None = None,
) -> Dict[str, int]:
    """
    Descarga métricas de Glassnode y las escribe en bronze/glassnode/<metric>.
    Si api_key está vacía, no hace nada.
    """
    if not (api_key and api_key.strip()):
        print("[glassnode] GLASSNODE_API_KEY no configurada. Saltando.")
        return {}

    assets = assets or ["BTC", "ETH"]
    start = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    until = datetime.now(timezone.utc)
    since_ts = int(start.timestamp())
    until_ts = int(until.timestamp())

    # Métricas útiles (path, interval). Ver docs: https://docs.glassnode.com/basic-api/endpoints
    metrics = [
        ("market/btc_dominance", "24h"),
        ("market/mvrv", "24h"),
        ("market/marketcap_usd", "24h"),
        ("market/price_usd_close", "24h"),
        ("indicators/sopr", "24h"),
    ]

    results: Dict[str, int] = {}
    all_events: List[Dict[str, Any]] = []
    for path, interval in metrics:
        for asset in assets:
            rows = _fetch(api_key, path, asset=asset, since_ts=since_ts, until_ts=until_ts, interval=interval)
            if not rows:
                continue
            for point in rows:
                t = point.get("t")
                v = point.get("v")
                if t is None:
                    continue
                dt = datetime.fromtimestamp(t, tz=timezone.utc)
                all_events.append({
                    "event_time": dt.isoformat(),
                    "asset": asset,
                    "metric": path.replace("/", "_"),
                    "value": v if isinstance(v, (int, float)) else None,
                })
            time.sleep(0.3)

    if all_events:
        writer.write_events_by_event_time("bronze", "glassnode", "onchain_metrics", all_events)
        total = len(all_events)
        results["glassnode_onchain"] = total
        print(f"[glassnode] onchain_metrics: {total} registros")

    return results


def main():
    cfg = DataPlatformConfig()
    api_key = getattr(cfg, "glassnode_api_key", "") or ""
    writer = LakeWriter(cfg.lake_root)

    print("=" * 60)
    print("BACKFILL GLASSNODE")
    print(f"Lake root: {cfg.lake_root}")
    print("=" * 60)

    counts = backfill_glassnode(writer, api_key)
    print("\nResumen:", counts or "Sin API key o sin datos.")
    if counts:
        print("Siguiente: cargar bronze/glassnode/* a DuckDB (tabla glassnode_raw o similar).")


if __name__ == "__main__":
    main()
