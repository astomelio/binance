from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple

import requests

from data_platform.config import DataPlatformConfig
from data_platform.storage.lake_writer import LakeWriter


SPOT_BASE = "https://api.binance.com"
FUTURES_BASE = "https://fapi.binance.com"
FUTURES_DATA_BASE = "https://fapi.binance.com"


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
    # Binance endpoint rejects very large ranges; query in rolling windows.
    max_window_ms = 20 * 24 * 60 * 60 * 1000  # 20 days
    while cursor < end_ms:
        window_end = min(end_ms, cursor + max_window_ms)
        resp = requests.get(
            f"{FUTURES_DATA_BASE}/futures/data/openInterestHist",
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
            # OI historical endpoint can be limited for older ranges by Binance.
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


def _latest_before(ts: int, series: List[Tuple[int, float]]) -> float:
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


def _micro_score(basis_bps: float, funding_rate_8h: float, price_change_24h: float) -> float:
    basis_component = max(min((-basis_bps) / 10.0, 1.0), -1.0)
    funding_component = max(min((-funding_rate_8h) / 0.0004, 1.0), -1.0)
    momentum_component = max(min((-price_change_24h) / 4.0, 1.0), -1.0)
    return round((0.45 * basis_component) + (0.35 * funding_component) + (0.20 * momentum_component), 4)


def _momentum_score(momentum_3: float, momentum_12: float) -> float:
    short_component = max(min(momentum_3 / 2.5, 1.0), -1.0)
    medium_component = max(min(momentum_12 / 5.0, 1.0), -1.0)
    return round((0.55 * short_component) + (0.45 * medium_component), 4)


def _session_band(close_ms: int) -> str:
    dt = datetime.fromtimestamp(close_ms / 1000, tz=timezone.utc)
    h = dt.hour
    if 0 <= h < 7:
        return "ASIA"
    if 7 <= h < 13:
        return "EUROPE"
    if 13 <= h < 21:
        return "US"
    return "OFF_HOURS"


def _session_overlap_score(session_band: str) -> float:
    if session_band == "US":
        return 1.0
    if session_band == "EUROPE":
        return 0.6
    if session_band == "ASIA":
        return 0.35
    return 0.15


def _clamp(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _liquidity_event_score(quote_volume_24h_proxy: float, open_interest: float, basis_bps: float) -> float:
    # Historical backfill does not include flow ratios; approximate pressure with OI + volume + basis.
    oi_component = _clamp(open_interest / 5_000_000.0)
    vol_component = _clamp(quote_volume_24h_proxy / 20_000_000_000.0)
    basis_component = _clamp(abs(basis_bps) / 15.0)
    return round((0.45 * oi_component) + (0.35 * vol_component) + (0.20 * basis_component), 4)


def build_historical_features(symbol: str, interval: str, days: int) -> List[Dict]:
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days)
    start_ms = _ms(start)
    end_ms = _ms(now)

    spot = _fetch_klines(SPOT_BASE, symbol, interval, start_ms, end_ms, market="spot")
    fut = _fetch_klines(FUTURES_BASE, symbol, interval, start_ms, end_ms, market="futures")
    funding = _fetch_funding_rates(symbol, start_ms, end_ms)
    oi = _fetch_open_interest_hist(symbol, "1h", start_ms, end_ms)

    if not spot or not fut:
        return []

    spot_by_open = {int(k[0]): k for k in spot}
    fut_by_open = {int(k[0]): k for k in fut}
    common_keys = sorted(set(spot_by_open.keys()) & set(fut_by_open.keys()))
    if not common_keys:
        return []

    funding_series = sorted((int(x["fundingTime"]), float(x["fundingRate"])) for x in funding)
    oi_series = sorted((int(x["timestamp"]), float(x.get("sumOpenInterest", 0) or 0)) for x in oi)

    fut_closes = [float(fut_by_open[k][4]) for k in common_keys]
    rows: List[Dict] = []
    for i, k in enumerate(common_keys):
        s = spot_by_open[k]
        f = fut_by_open[k]
        close_ms = int(f[6])
        spot_close = float(s[4])
        fut_close = float(f[4])
        basis_bps = ((fut_close - spot_close) / spot_close) * 10000 if spot_close else 0.0

        m3 = _pct_change(fut_closes, i, 3)
        m12 = _pct_change(fut_closes, i, 12)
        mom_score = _momentum_score(m3, m12)
        funding_rate = _latest_before(close_ms, funding_series)
        oi_val = _latest_before(close_ms, oi_series)
        # Approx proxy from futures return windows; can be replaced with exact rolling 24h return.
        p24 = _pct_change(fut_closes, i, 24)
        micro = _micro_score(basis_bps, funding_rate, p24)
        session_band = _session_band(close_ms)
        session_overlap_score = _session_overlap_score(session_band)
        # Use futures quote volume as practical 24h liquidity proxy in historical build.
        quote_volume_24h_proxy = float(f[7]) if len(f) > 7 else 0.0
        liquidity_event_score = _liquidity_event_score(quote_volume_24h_proxy, oi_val, basis_bps)
        alpha_score = round(
            (0.5 * micro) + (0.3 * mom_score) + (0.15 * session_overlap_score) + (0.05 * liquidity_event_score),
            4,
        )

        rows.append(
            {
                "event_time": _iso_from_ms(close_ms),
                "symbol": symbol,
                "spot_last_price": spot_close,
                "futures_last_price": fut_close,
                "basis_bps": basis_bps,
                "spot_volume": float(s[5]),
                "futures_volume": float(f[5]),
                "funding_rate_8h": funding_rate,
                "open_interest": oi_val,
                "quote_volume_24h": quote_volume_24h_proxy,
                "buy_sell_ratio": 1.0,
                "long_short_account_ratio": 1.0,
                "fear_greed_value": 0.0,
                "price_change_percent_24h": p24,
                "momentum_3": m3,
                "momentum_12": m12,
                "momentum_score": mom_score,
                "session_band": session_band,
                "session_overlap_score": session_overlap_score,
                "liquidity_event_score": liquidity_event_score,
                "liquidity_event_label": "UNKNOWN",
                "alpha_microstructure_score": micro,
                "alpha_score": alpha_score,
                "fed_window": "UNKNOWN",
                "alpha_signal": "LONG" if alpha_score >= 0.4 else ("SHORT" if alpha_score <= -0.4 else "NO_TRADE"),
            }
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill historical market features for model training")
    parser.add_argument("--days", type=int, default=30, help="Days to backfill (default: 30)")
    parser.add_argument("--interval", type=str, default="1h", help="Kline interval (default: 1h)")
    args = parser.parse_args()

    cfg = DataPlatformConfig()
    writer = LakeWriter(cfg.lake_root)

    total = 0
    for symbol in cfg.symbols:
        try:
            rows = build_historical_features(symbol=symbol, interval=args.interval, days=args.days)
            if not rows:
                print(f"[backfill][SKIP] {symbol}: no rows")
                continue
            dataset_name = f"decision_features_backfill_{args.interval}" if args.interval != "1h" else "decision_features_backfill"
            out = writer.write_events("gold", "signals", dataset_name, rows)
            total += len(rows)
            print(f"[backfill] {symbol}: {len(rows)} rows -> {out}")
        except Exception as exc:  # noqa: BLE001
            print(f"[backfill][WARN] {symbol}: {exc}")

    print(f"[backfill] done, total rows={total}, lake_root={cfg.lake_root}")


if __name__ == "__main__":
    main()

