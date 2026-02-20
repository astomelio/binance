"""
Backfill histórico desde data.binance.vision (descargas directas, sin API).
Klines + funding rate en paralelo; open interest vía API (vision no lo ofrece).

Tiempos OI (36 meses, ~0.2s/request): 3 símbolos ~30s | 20 (top) ~3-4 min | 500 (all) ~90 min.

Usage:
    python -m data_platform.backfill_from_vision --interval 1h --months 36
    DP_SYMBOLS=top python -m data_platform.backfill_from_vision --interval 1h --months 36
    make warehouse-backfill-vision   # 1h para principales
"""
from __future__ import annotations

import argparse
import csv
import io
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple

import requests

from data_platform.config import DataPlatformConfig
from data_platform.storage.lake_writer import LakeWriter
from data_platform.symbols import resolve_symbols

BASE = "https://data.binance.vision/data"
FUTURES_API = "https://fapi.binance.com"


def _iso_from_ms(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


def _download_zip(url: str) -> bytes | None:
    try:
        r = requests.get(url, timeout=90)
        if r.status_code == 200:
            return r.content
    except Exception:
        pass
    return None


def _parse_klines_csv(content: bytes, symbol: str) -> List[Dict]:
    """Parse CSV from Binance klines zip. Cols: open_time, open, high, low, close, volume, close_time, quote_vol, ..."""
    rows = []
    with zipfile.ZipFile(io.BytesIO(content), "r") as z:
        for name in z.namelist():
            if not name.endswith(".csv"):
                continue
            with z.open(name) as f:
                for r in csv.reader(io.TextIOWrapper(f)):
                    if len(r) < 7:
                        continue
                    try:
                        open_ms = int(r[0])
                        close_ms = int(r[6]) if len(r) > 6 else open_ms
                        close = float(r[4])
                        volume = float(r[5])
                        quote_vol = float(r[7]) if len(r) > 7 else 0
                        rows.append({
                            "event_time": _iso_from_ms(close_ms),
                            "symbol": symbol,
                            "close": close,
                            "volume": volume,
                            "quote_volume": quote_vol,
                        })
                    except (ValueError, IndexError):
                        continue
    return rows


def _month_range(months: int) -> List[str]:
    now = datetime.now(timezone.utc)
    return [(now - timedelta(days=30 * i)).strftime("%Y-%m") for i in range(months, 0, -1)]


def _url(market: str, symbol: str, interval: str, month: str) -> str:
    if market == "futures":
        return f"{BASE}/futures/um/monthly/klines/{symbol}/{interval}/{symbol}-{interval}-{month}.zip"
    return f"{BASE}/spot/monthly/klines/{symbol}/{interval}/{symbol}-{interval}-{month}.zip"


def _url_funding_rate(symbol: str, month: str) -> str:
    return f"{BASE}/futures/um/monthly/fundingRate/{symbol}/{symbol}-fundingRate-{month}.zip"


def _parse_funding_rate_csv(content: bytes, symbol: str) -> List[Tuple[int, float]]:
    """Parse funding rate CSV. Returns sorted [(calc_time_ms, last_funding_rate), ...]"""
    out: List[Tuple[int, float]] = []
    with zipfile.ZipFile(io.BytesIO(content), "r") as z:
        for name in z.namelist():
            if not name.endswith(".csv"):
                continue
            with z.open(name) as f:
                reader = csv.reader(io.TextIOWrapper(f))
                next(reader, None)  # skip header: calc_time,funding_interval_hours,last_funding_rate
                for r in reader:
                    if len(r) < 3:
                        continue
                    try:
                        calc_ms = int(r[0])
                        rate = float(r[2])
                        out.append((calc_ms, rate))
                    except (ValueError, IndexError):
                        continue
    return sorted(out)


def _latest_before(ts_ms: int, series: List[Tuple[int, float]]) -> float:
    value = 0.0
    for t, v in series:
        if t <= ts_ms:
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


def _fetch_open_interest_hist(
    symbol: str, period: str, start_ms: int, end_ms: int, delay_sec: float = 0.2
) -> List[Tuple[int, float]]:
    """Fetch OI via API. Returns sorted [(timestamp_ms, sumOpenInterest), ...]"""
    out: List[Tuple[int, float]] = []
    cursor = start_ms
    max_window_ms = 20 * 24 * 60 * 60 * 1000
    while cursor < end_ms:
        window_end = min(end_ms, cursor + max_window_ms)
        try:
            resp = requests.get(
                f"{FUTURES_API}/futures/data/openInterestHist",
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
                break
            batch = resp.json()
            if not batch:
                cursor = window_end + 1
                time.sleep(delay_sec)
                continue
            for x in batch:
                ts = int(x.get("timestamp", 0))
                oi = float(x.get("sumOpenInterest", 0) or 0)
                out.append((ts, oi))
            last = int(batch[-1]["timestamp"])
            if last <= cursor:
                cursor = window_end + 1
            else:
                cursor = last + 1
        except Exception:
            break
        time.sleep(delay_sec)
    return sorted(out)


def run_backfill(
    symbols: List[str],
    interval: str = "1h",
    months: int = 36,
    lake_root: str = "data_lake",
    workers: int = 12,
    fetch_open_interest: bool = True,
) -> Dict[str, int]:
    writer = LakeWriter(lake_root)
    month_list = _month_range(months)

    tasks: List[Tuple[str, str, str]] = []
    for symbol in symbols:
        for month in month_list:
            tasks.append(("futures", symbol, month))
            tasks.append(("spot", symbol, month))

    # (symbol, event_time) -> {spot: {...}, futures: {...}, close_ms: int}
    merged: Dict[Tuple[str, str], Dict] = {}
    # symbol -> sorted [(ts_ms, rate)]
    funding_by_symbol: Dict[str, List[Tuple[int, float]]] = {s: [] for s in symbols}

    def fetch_and_parse(args):
        market, symbol, month = args
        url = _url(market, symbol, interval, month)
        content = _download_zip(url)
        if not content:
            return None
        return (market, symbol, _parse_klines_csv(content, symbol))

    done = 0
    failed = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(fetch_and_parse, t): t for t in tasks}
        for fut in as_completed(futures):
            done += 1
            if done % 50 == 0:
                print(f"  [klines {done}/{len(tasks)}] ...")
            try:
                r = fut.result()
                if not r:
                    failed += 1
                    continue
                market, symbol, rows = r
                for row in rows:
                    key = (symbol, row["event_time"])
                    if key not in merged:
                        merged[key] = {"event_time": row["event_time"], "symbol": symbol, "spot": {}, "futures": {}}
                    if market == "spot":
                        merged[key]["spot"] = {"last_price": row["close"], "volume": row["volume"]}
                    else:
                        merged[key]["futures"] = {
                            "last_price": row["close"],
                            "volume": row["volume"],
                            "quote_volume": row["quote_volume"],
                        }
            except Exception:
                failed += 1

    # Funding rate from data.binance.vision
    def fetch_funding(symbol: str, month: str):
        content = _download_zip(_url_funding_rate(symbol, month))
        if not content:
            return (symbol, [])
        return (symbol, _parse_funding_rate_csv(content, symbol))

    fr_tasks = [(s, m) for s in symbols for m in month_list]
    with ThreadPoolExecutor(max_workers=workers) as ex:
        fr_futures = {ex.submit(fetch_funding, s, m): (s, m) for s, m in fr_tasks}
    for fut in as_completed(fr_futures):
        try:
            symbol, series = fut.result()
            if series:
                funding_by_symbol[symbol].extend(series)
        except Exception:
            pass
    for s in symbols:
        funding_by_symbol[s] = sorted(funding_by_symbol[s])

    # Open interest via API (data.binance.vision no tiene OI)
    oi_by_symbol: Dict[str, List[Tuple[int, float]]] = {}
    if fetch_open_interest:
        now = datetime.now(timezone.utc)
        start = now - timedelta(days=months * 30)
        start_ms = int(start.timestamp() * 1000)
        end_ms = int(now.timestamp() * 1000)
        for i, symbol in enumerate(symbols):
            if (i + 1) % 5 == 0:
                print(f"  [OI {i + 1}/{len(symbols)}] {symbol}...")
            oi_by_symbol[symbol] = _fetch_open_interest_hist(symbol, "1h", start_ms, end_ms)

    # Build events for loader format (need both spot and futures)
    market_events = []
    deriv_events = []
    flow_events = []
    # Per-symbol sorted (event_time, close) for p24
    fut_closes_by_symbol: Dict[str, List[Tuple[str, float]]] = {}
    for (symbol, _), data in sorted(merged.items(), key=lambda x: (x[0][0], x[0][1])):
        spot = data.get("spot") or {}
        fut = data.get("futures") or {}
        if not fut:
            continue
        ts = data["event_time"]
        close_ms = int(datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp() * 1000)
        if symbol not in fut_closes_by_symbol:
            fut_closes_by_symbol[symbol] = []
        fut_closes_by_symbol[symbol].append((ts, float(fut.get("last_price", 0))))

    for (symbol, _), data in merged.items():
        spot = data.get("spot") or {}
        fut = data.get("futures") or {}
        if not fut:
            continue
        ts = data["event_time"]
        close_ms = int(datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp() * 1000)
        funding_rate = _latest_before(close_ms, funding_by_symbol.get(symbol, []))
        oi_val = _latest_before(close_ms, oi_by_symbol.get(symbol, []))
        closes = fut_closes_by_symbol.get(symbol, [])
        idx = next((i for i, (et, _) in enumerate(closes) if et == ts), -1)
        p24 = _pct_change([c for _, c in closes], idx, 24) if idx >= 0 else 0.0

        market_events.append({
            "event_time": ts,
            "symbol": symbol,
            "spot_ticker": spot or {"last_price": fut.get("last_price", 0), "volume": 0},
            "futures_ticker": fut,
        })
        deriv_events.append({
            "event_time": ts,
            "symbol": symbol,
            "mark_price": fut.get("last_price", 0),
            "index_price": fut.get("last_price", 0),
            "last_funding_rate": funding_rate,
            "open_interest": oi_val,
            "price_change_percent_24h": p24,
            "quote_volume_24h": fut.get("quote_volume", 0),
        })
        flow_events.append({
            "event_time": ts,
            "symbol": symbol,
            "long_short_account_ratio": 1.0,
            "buy_sell_ratio": 1.0,
            "buy_vol": 0.0,
            "sell_vol": 0.0,
        })

    if market_events:
        writer.write_events_by_event_time("bronze", "binance_vision", "market_snapshot", market_events)
    if deriv_events:
        writer.write_events_by_event_time("bronze", "binance_vision", "derivatives_snapshot", deriv_events)
    if flow_events:
        writer.write_events_by_event_time("bronze", "binance_vision", "derivatives_flow", flow_events)

    return {
        "market": len(market_events),
        "derivatives": len(deriv_events),
        "flow": len(flow_events),
        "failed_downloads": failed,
    }


def main():
    parser = argparse.ArgumentParser(description="Backfill from data.binance.vision (funding+OI)")
    parser.add_argument("--interval", default="1h", help="1m, 3m, 5m, 15m, 30m, 1h, 2h, 4h, 1d")
    parser.add_argument("--months", type=int, default=36, help="Months of history")
    parser.add_argument("--workers", type=int, default=12, help="Parallel downloads")
    parser.add_argument("--lake-root", default="data_lake")
    parser.add_argument("--no-open-interest", action="store_true", help="Skip OI (faster, uses API)")
    args = parser.parse_args()

    cfg = DataPlatformConfig()
    symbols = cfg.symbols
    print(f"Symbols: {len(symbols)} | Interval: {args.interval} | Months: {args.months}")
    print("Downloading from data.binance.vision (klines + funding rate)...")
    result = run_backfill(
        symbols=symbols,
        interval=args.interval,
        months=args.months,
        lake_root=args.lake_root,
        workers=args.workers,
        fetch_open_interest=not args.no_open_interest,
    )
    print(f"Done: market={result['market']}, deriv={result['derivatives']}, flow={result['flow']}, failed={result['failed_downloads']}")
    print("Next: make warehouse-load")


if __name__ == "__main__":
    main()
