"""
Backfill histórico de fuentes externas: Fear & Greed, FRED, CoinGecko.
Obtiene datos desde 2023-03-01 para alinear con Binance Vision.

Usage:
    python -m data_platform.backfill_external_sources
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List

import requests

from data_platform.config import DataPlatformConfig
from data_platform.storage.lake_writer import LakeWriter


def backfill_fear_greed(writer: LakeWriter, start_date: str = "2023-03-01") -> int:
    """
    Fear & Greed Index desde Alternative.me.
    API permite hasta 3 años de datos con ?limit=N
    """
    print("[fear_greed] Descargando histórico...")
    
    start = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    days = (now - start).days + 1
    
    url = f"https://api.alternative.me/fng/?limit={days}&format=json"
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    data = resp.json().get("data", [])
    
    events = []
    for item in data:
        ts = int(item.get("timestamp", 0))
        if ts == 0:
            continue
        base_dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        # Una fila por hora para alinear con el warehouse
        for hour in range(24):
            dt = base_dt.replace(hour=hour, minute=0, second=0, microsecond=0)
            events.append({
                "event_time": dt.isoformat(),
                "value": float(item.get("value", 0) or 0),
                "classification": item.get("value_classification", ""),
                "timestamp": str(ts),
            })
    
    if events:
        writer.write_events_by_event_time("bronze", "alternative_me_historical", "fear_greed_index", events)
    
    print(f"[fear_greed] {len(events)} registros guardados")
    return len(events)


def _fetch_fred_series(
    api_key: str,
    series_id: str,
    start_date: str,
) -> List[Dict]:
    """Fetch FRED series observations. Returns list of {date, value, series_id}."""
    url = "https://api.stlouisfed.org/fred/series/observations"
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "observation_start": start_date,
        "sort_order": "asc",
    }
    resp = requests.get(url, params=params, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    observations = data.get("observations", [])
    out = []
    for obs in observations:
        date_str = obs.get("date", "")
        value = obs.get("value", ".")
        if value == "." or not date_str:
            continue
        try:
            v = float(value)
        except (ValueError, TypeError):
            continue
        out.append({"date": date_str, "value": v, "series_id": series_id})
    return out


def backfill_fred_macro(writer: LakeWriter, api_key: str, start_date: str = "2023-03-01") -> int:
    """
    FRED Federal Funds Rate histórico.
    """
    if not api_key:
        print("[fred] FRED_API_KEY no configurada, saltando...")
        return 0

    print("[fred] Descargando FEDFUNDS histórico...")
    events = []
    for row in _fetch_fred_series(api_key, "FEDFUNDS", start_date):
        dt = datetime.strptime(row["date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        events.append({
            "event_time": dt.isoformat(),
            "fed_funds_rate": row["value"],
            "series_id": "FEDFUNDS",
        })

    if events:
        writer.write_events_by_event_time("bronze", "fred_historical", "macro_rates", events)

    print(f"[fred] FEDFUNDS: {len(events)} registros guardados")
    return len(events)


def backfill_fred_macro_assets(
    writer: LakeWriter, api_key: str, start_date: str = "2023-03-01"
) -> int:
    """
    FRED macro assets: SP500, DCOILWTICO (WTI oil).
    Gold (GOLDPMGBD228NLBM) fue removido de FRED en 2022; usar otra fuente si se necesita.
    """
    if not api_key:
        print("[fred_assets] FRED_API_KEY no configurada, saltando...")
        return 0

    # SP500, DCOILWTICO (WTI crude oil price)
    series_map = {
        "SP500": "sp500_close",
        "DCOILWTICO": "oil_wti_usd",
    }
    all_events: Dict[str, Dict] = {}  # date -> {sp500, oil_wti}

    for series_id, key in series_map.items():
        print(f"[fred_assets] Descargando {series_id}...")
        try:
            rows = _fetch_fred_series(api_key, series_id, start_date)
            for row in rows:
                d = all_events.setdefault(row["date"], {})
                d[key] = row["value"]
            print(f"[fred_assets] {series_id}: {len(rows)} observaciones")
        except Exception as e:
            print(f"[fred_assets] {series_id} error: {e}")

    events = []
    for date_str, vals in sorted(all_events.items()):
        dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        events.append({
            "event_time": dt.isoformat(),
            "sp500_close": vals.get("sp500_close"),
            "oil_wti_usd": vals.get("oil_wti_usd"),
        })

    if events:
        writer.write_events_by_event_time("bronze", "fred_historical", "macro_assets", events)

    print(f"[fred_assets] {len(events)} registros guardados")
    return len(events)


def backfill_coingecko_global(writer: LakeWriter, api_key: str = "") -> int:
    """
    CoinGecko global market data SIN API KEY (API pública).
    Usa solo el endpoint /global que devuelve:
    - btc_dominance (market_cap_percentage.btc)
    - total_market_cap_usd
    - total_volume_usd
    No requiere registro ni key. Histórico no está disponible en plan free.
    """
    url = "https://api.coingecko.com/api/v3/global"
    headers = {}
    if api_key and api_key.strip():
        headers["x-cg-demo-api-key"] = api_key.strip()

    print("[coingecko] Obteniendo snapshot global (/global, sin key necesaria)...")
    try:
        resp = requests.get(url, headers=headers or None, timeout=30)
        resp.raise_for_status()
        payload = resp.json().get("data", {})
    except requests.exceptions.HTTPError as e:
        print(f"[coingecko] Error HTTP {e.response.status_code}: {e}")
        return 0
    except Exception as e:
        print(f"[coingecko] Error: {e}")
        return 0

    now = datetime.now(timezone.utc)
    event = {
        "event_time": now.isoformat(),
        "payload": {
            "market_cap_percentage": payload.get("market_cap_percentage", {}),
            "total_market_cap": payload.get("total_market_cap", {}),
            "total_volume": payload.get("total_volume", {}),
        },
    }
    writer.write_events_by_event_time("bronze", "coingecko", "global_market", [event])
    btc_pct = payload.get("market_cap_percentage", {}).get("btc", 0)
    mcap = payload.get("total_market_cap", {}).get("usd", 0)
    vol = payload.get("total_volume", {}).get("usd", 0)
    print(f"[coingecko] OK: BTC dominance={btc_pct:.1f}%, market_cap=${mcap/1e12:.2f}T, volume_24h=${vol/1e9:.1f}B")
    return 1


def backfill_fed_calendar(writer: LakeWriter) -> int:
    """
    FED Calendar - usa seed file + fechas conocidas.
    """
    print("[fed_calendar] Generando calendario histórico...")
    
    # Fechas FOMC conocidas 2023-2026
    fomc_dates = [
        # 2023
        "2023-02-01", "2023-03-22", "2023-05-03", "2023-06-14",
        "2023-07-26", "2023-09-20", "2023-11-01", "2023-12-13",
        # 2024
        "2024-01-31", "2024-03-20", "2024-05-01", "2024-06-12",
        "2024-07-31", "2024-09-18", "2024-11-07", "2024-12-18",
        # 2025
        "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18",
        "2025-07-30", "2025-09-17", "2025-11-05", "2025-12-17",
        # 2026
        "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
        "2026-07-29", "2026-09-16", "2026-11-04", "2026-12-16",
    ]
    
    events = []
    now = datetime.now(timezone.utc)
    
    for date_str in fomc_dates:
        dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        events.append({
            "event_time": dt.isoformat(),
            "decision_date": date_str,
            "source": "fomc_calendar_seed",
        })
    
    if events:
        writer.write_events_by_event_time("bronze", "fed_calendar_historical", "decision_dates", events)
    
    print(f"[fed_calendar] {len(events)} fechas guardadas")
    return len(events)


def main():
    cfg = DataPlatformConfig()
    writer = LakeWriter(cfg.lake_root)
    
    print("=" * 60)
    print("BACKFILL FUENTES EXTERNAS")
    print(f"Desde: 2023-03-01")
    print(f"Lake root: {cfg.lake_root}")
    print("=" * 60)
    
    results = {}
    
    # Fear & Greed
    results["fear_greed"] = backfill_fear_greed(writer)
    time.sleep(1)
    
    # FRED
    results["fred"] = backfill_fred_macro(writer, cfg.fred_api_key)
    time.sleep(1)

    # FRED macro assets (SP500, oil WTI)
    results["fred_assets"] = backfill_fred_macro_assets(writer, cfg.fred_api_key)
    time.sleep(1)
    
    # CoinGecko: /global funciona sin key (snapshot actual)
    results["coingecko"] = backfill_coingecko_global(writer, api_key=cfg.coingecko_api_key)
    time.sleep(1)
    
    # FED Calendar
    results["fed_calendar"] = backfill_fed_calendar(writer)
    time.sleep(1)

    # Glassnode (on-chain; requiere GLASSNODE_API_KEY)
    try:
        from data_platform.backfill_glassnode import backfill_glassnode
        glassnode_counts = backfill_glassnode(writer, cfg.glassnode_api_key)
        results["glassnode"] = sum(glassnode_counts.values()) if glassnode_counts else 0
    except Exception as e:
        print(f"[glassnode] Skip: {e}")
        results["glassnode"] = 0

    print("\n" + "=" * 60)
    print("RESUMEN:")
    for source, count in results.items():
        print(f"  {source}: {count} registros")
    print("=" * 60)
    print("\nSiguiente: Cargar a DuckDB y correr dbt")


if __name__ == "__main__":
    main()
