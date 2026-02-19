"""
Backfill historical data into bronze layer in format compatible with warehouse_raw_load.

Writes to bronze/binance_historical/{market_snapshot,derivatives_snapshot,derivatives_flow}
so that warehouse_raw_load + dbt can populate DuckDB tables with years of data.

Usage:
    python -m data_platform.backfill_bronze_historical --days 1095 --interval 1h
    make warehouse-backfill
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from typing import Dict, List

import requests

from data_platform.config import DataPlatformConfig
from data_platform.storage.lake_writer import LakeWriter

SPOT_BASE = "https://api.binance.com"
FUTURES_BASE = "https://fapi.binance.com"


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _iso_from_ms(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


def _fetch_klines(
    base_url: str,
    symbol: str,
    interval: str,
    start_ms: int,
    end_ms: int,
    market: str,
) -> List[List]:
    out: List[List] = []
    cursor = start_ms
    while cursor < end_ms:
        endpoint = f"{base_url}/api/v3/klines" if market == "spot" else f"{base_url}/fapi/v1/klines"
        resp = requests.get(
            endpoint,
            params={
                "symbol": symbol,
                "interval": interval,
                "startTime": cursor,
                "endTime": end_ms,
                "limit": 1000,
            },
            timeout=30,
        )
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        out.extend(batch)
        last_open = int(batch[-1][0])
        if last_open <= cursor:
            break
        cursor = last_open + 1
    return out


def _fetch_funding_rates(symbol: str, start_ms: int, end_ms: int) -> List[Dict]:
    out: List[Dict] = []
    cursor = start_ms
    while cursor < end_ms:
        resp = requests.get(
            f"{FUTURES_BASE}/fapi/v1/fundingRate",
            params={
                "symbol": symbol,
                "startTime": cursor,
                "endTime": end_ms,
                "limit": 1000,
            },
            timeout=30,
        )
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        out.extend(batch)
        last = int(batch[-1]["fundingTime"])
        if last <= cursor:
            break
        cursor = last + 1
    return out


def _fetch_open_interest_hist(symbol: str, period: str, start_ms: int, end_ms: int) -> List[Dict]:
    out: List[Dict] = []
    cursor = start_ms
    max_window_ms = 20 * 24 * 60 * 60 * 1000
    while cursor < end_ms:
        window_end = min(end_ms, cursor + max_window_ms)
        resp = requests.get(
            f"{FUTURES_BASE}/futures/data/openInterestHist",
            params={
                "symbol": symbol,
                "period": period,
                "startTime": cursor,
                "endTime": window_end,
                "limit": 500,
            },
            timeout=30,
        )
        if resp.status_code >= 400:
            return out
        batch = resp.json()
        if not batch:
            cursor = window_end + 1
            continue
        out.extend(batch)
        last = int(batch[-1]["timestamp"])
        if last <= cursor:
            cursor = window_end + 1
            continue
        cursor = last + 1
    return out


def _latest_before(ts: int, series: List[tuple[int, float]]) -> float:
    value = 0.0
    for t, v in series:
        if t <= ts:
            value = v
        else:
            break
    return value


def _pct_change(series: List[float], idx: int, steps_back: int) -> float:
    if idx < steps_back:
        return 0.0
    prev = series[idx - steps_back]
    curr = series[idx]
    if prev == 0:
        return 0.0
    return ((curr - prev) / prev) * 100.0


def build_bronze_events(
    symbol: str, interval: str, days: int
) -> tuple[List[Dict], List[Dict], List[Dict]]:
    """Build bronze-compatible events for market_snapshot, derivatives_snapshot, derivatives_flow."""
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days)
    start_ms = _ms(start)
    end_ms = _ms(now)

    spot = _fetch_klines(SPOT_BASE, symbol, interval, start_ms, end_ms, market="spot")
    fut = _fetch_klines(FUTURES_BASE, symbol, interval, start_ms, end_ms, market="futures")
    funding = _fetch_funding_rates(symbol, start_ms, end_ms)
    oi = _fetch_open_interest_hist(symbol, "1h", start_ms, end_ms)

    if not spot or not fut:
        return [], [], []

    spot_by_open = {int(k[0]): k for k in spot}
    fut_by_open = {int(k[0]): k for k in fut}
    common_keys = sorted(set(spot_by_open.keys()) & set(fut_by_open.keys()))
    if not common_keys:
        return [], [], []

    funding_series = sorted((int(x["fundingTime"]), float(x["fundingRate"])) for x in funding)
    oi_series = sorted((int(x["timestamp"]), float(x.get("sumOpenInterest", 0) or 0)) for x in oi)
    fut_closes = [float(fut_by_open[k][4]) for k in common_keys]

    market_events: List[Dict] = []
    deriv_events: List[Dict] = []
    flow_events: List[Dict] = []

    for i, k in enumerate(common_keys):
        s = spot_by_open[k]
        f = fut_by_open[k]
        close_ms = int(f[6])
        event_time = _iso_from_ms(close_ms)

        spot_close = float(s[4])
        fut_close = float(f[4])
        spot_vol = float(s[5])
        fut_vol = float(f[5])
        quote_vol = float(f[7]) if len(f) > 7 else 0.0
        funding_rate = _latest_before(close_ms, funding_series)
        oi_val = _latest_before(close_ms, oi_series)
        p24 = _pct_change(fut_closes, i, 24)

        # Format expected by _load_market_snapshot_raw (from binance_local_api structure)
        market_events.append({
            "event_time": event_time,
            "symbol": symbol.upper(),
            "spot_ticker": {"last_price": spot_close, "volume": spot_vol},
            "futures_ticker": {
                "last_price": fut_close,
                "volume": fut_vol,
                "quote_volume": quote_vol,
            },
        })

        # Format expected by _load_derivatives_snapshot_raw
        deriv_events.append({
            "event_time": event_time,
            "symbol": symbol.upper(),
            "mark_price": fut_close,
            "index_price": fut_close,
            "last_funding_rate": funding_rate,
            "open_interest": oi_val,
            "price_change_percent_24h": p24,
            "quote_volume_24h": quote_vol,
        })

        # Format expected by _load_derivatives_flow_raw (historical: no real ratio, use 1.0)
        flow_events.append({
            "event_time": event_time,
            "symbol": symbol.upper(),
            "long_short_account_ratio": 1.0,
            "buy_sell_ratio": 1.0,
            "buy_vol": 0.0,
            "sell_vol": 0.0,
        })

    return market_events, deriv_events, flow_events


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill historical data into bronze for DuckDB/dbt warehouse"
    )
    parser.add_argument(
        "--days",
        type=int,
        default=1095,
        help="Days to backfill (default: 1095 = ~3 years)",
    )
    parser.add_argument(
        "--interval",
        type=str,
        default="1h",
        help="Kline interval (default: 1h)",
    )
    args = parser.parse_args()

    cfg = DataPlatformConfig()
    writer = LakeWriter(cfg.lake_root)

    total_market = 0
    total_deriv = 0
    total_flow = 0

    for symbol in cfg.symbols:
        try:
            market_ev, deriv_ev, flow_ev = build_bronze_events(
                symbol=symbol, interval=args.interval, days=args.days
            )
            if not market_ev:
                print(f"[backfill_bronze][SKIP] {symbol}: no data")
                continue

            paths_m = writer.write_events_by_event_time(
                "bronze", "binance_historical", "market_snapshot", market_ev
            )
            paths_d = writer.write_events_by_event_time(
                "bronze", "binance_historical", "derivatives_snapshot", deriv_ev
            )
            paths_f = writer.write_events_by_event_time(
                "bronze", "binance_historical", "derivatives_flow", flow_ev
            )

            total_market += len(market_ev)
            total_deriv += len(deriv_ev)
            total_flow += len(flow_ev)
            print(
                f"[backfill_bronze] {symbol}: market={len(market_ev)}, "
                f"derivatives={len(deriv_ev)}, flow={len(flow_ev)}"
            )
        except Exception as exc:
            print(f"[backfill_bronze][WARN] {symbol}: {exc}")

    print(
        f"[backfill_bronze] done. market_snapshot={total_market}, "
        f"derivatives_snapshot={total_deriv}, derivatives_flow={total_flow}"
    )
    print(f"[backfill_bronze] lake_root={cfg.lake_root}")
    print("[backfill_bronze] Next: make warehouse-load dbt-run  (or run Dagster warehouse_raw_load)")


if __name__ == "__main__":
    main()
