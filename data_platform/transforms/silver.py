from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List


def _iter_jsonl(files: Iterable[Path]) -> Iterable[Dict]:
    for file in files:
        with file.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    yield json.loads(line)


def normalize_market_snapshot(events: List[Dict]) -> List[Dict]:
    out: List[Dict] = []
    seen = set()
    for event in events:
        symbol = event.get("symbol", "")
        key = (event.get("event_time"), symbol)
        if key in seen:
            continue
        seen.add(key)
        spot = event.get("spot_ticker", {})
        fut = event.get("futures_ticker", {})
        out.append(
            {
                "event_time": event.get("event_time"),
                "symbol": symbol,
                "spot_last_price": float(spot.get("last_price", 0) or 0),
                "spot_volume": float(spot.get("volume", 0) or 0),
                "futures_last_price": float(fut.get("last_price", 0) or 0),
                "futures_volume": float(fut.get("volume", 0) or 0),
                "futures_quote_volume": float(fut.get("quote_volume", 0) or 0),
            }
        )
    return out


def normalize_derivatives_snapshot(events: List[Dict]) -> List[Dict]:
    out: List[Dict] = []
    seen = set()
    for event in events:
        symbol = event.get("symbol", "")
        key = (event.get("event_time"), symbol)
        if key in seen:
            continue
        seen.add(key)

        out.append(
            {
                "event_time": event.get("event_time"),
                "symbol": symbol,
                "mark_price": float(event.get("mark_price", 0) or 0),
                "index_price": float(event.get("index_price", 0) or 0),
                "last_funding_rate": float(event.get("last_funding_rate", 0) or 0),
                "open_interest": float(event.get("open_interest", 0) or 0),
                "price_change_percent_24h": float(event.get("price_change_percent_24h", 0) or 0),
                "quote_volume_24h": float(event.get("quote_volume_24h", 0) or 0),
                "next_funding_time": event.get("next_funding_time"),
            }
        )
    return out


def normalize_global_market(events: List[Dict]) -> List[Dict]:
    out: List[Dict] = []
    for event in events:
        payload = event.get("payload", {})
        out.append(
            {
                "event_time": event.get("event_time"),
                "btc_dominance": float(payload.get("market_cap_percentage", {}).get("btc", 0) or 0),
                "total_market_cap_usd": float(payload.get("total_market_cap", {}).get("usd", 0) or 0),
                "total_volume_usd": float(payload.get("total_volume", {}).get("usd", 0) or 0),
            }
        )
    return out


def normalize_fear_greed(events: List[Dict]) -> List[Dict]:
    out: List[Dict] = []
    for event in events:
        out.append(
            {
                "event_time": event.get("event_time"),
                "fear_greed_value": float(event.get("value", 0) or 0),
                "fear_greed_classification": event.get("classification", ""),
            }
        )
    return out


def normalize_derivatives_flow(events: List[Dict]) -> List[Dict]:
    out: List[Dict] = []
    seen = set()
    for event in events:
        symbol = event.get("symbol", "")
        key = (event.get("event_time"), symbol)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "event_time": event.get("event_time"),
                "symbol": symbol,
                "long_short_account_ratio": float(event.get("long_short_account_ratio", 0) or 0),
                "buy_sell_ratio": float(event.get("buy_sell_ratio", 0) or 0),
                "buy_vol": float(event.get("buy_vol", 0) or 0),
                "sell_vol": float(event.get("sell_vol", 0) or 0),
            }
        )
    return out


def normalize_cross_exchange_snapshot(events: List[Dict]) -> List[Dict]:
    out: List[Dict] = []
    seen = set()
    for event in events:
        symbol = str(event.get("symbol", "")).upper()
        exchange = str(event.get("exchange", "")).lower()
        key = (event.get("event_time"), symbol, exchange)
        if key in seen:
            continue
        seen.add(key)

        bid = float(event.get("bid_price", 0) or 0)
        ask = float(event.get("ask_price", 0) or 0)
        mid = (bid + ask) / 2.0 if bid > 0 and ask > 0 else 0.0
        spread_bps = ((ask - bid) / mid) * 10000.0 if mid > 0 else 0.0
        out.append(
            {
                "event_time": event.get("event_time"),
                "symbol": symbol,
                "exchange": exchange,
                "last_price": float(event.get("last_price", 0) or 0),
                "bid_price": bid,
                "ask_price": ask,
                "spread_bps": spread_bps,
                "quote_volume_24h": float(event.get("quote_volume_24h", 0) or 0),
            }
        )
    return out


def normalize_dex_snapshot(events: List[Dict]) -> List[Dict]:
    out: List[Dict] = []
    seen = set()
    for event in events:
        symbol = str(event.get("symbol", "")).upper()
        pair_address = str(event.get("pair_address", "")).lower()
        key = (event.get("event_time"), symbol, pair_address)
        if key in seen:
            continue
        seen.add(key)
        buys = float(event.get("txns_buys_24h", 0) or 0)
        sells = float(event.get("txns_sells_24h", 0) or 0)
        total = buys + sells
        imbalance = ((buys - sells) / total) if total > 0 else 0.0
        out.append(
            {
                "event_time": event.get("event_time"),
                "symbol": symbol,
                "chain_id": str(event.get("chain_id", "")).lower(),
                "pair_address": pair_address,
                "dex_id": str(event.get("dex_id", "")).lower(),
                "dex_price_usd": float(event.get("price_usd", 0) or 0),
                "dex_liquidity_usd": float(event.get("liquidity_usd", 0) or 0),
                "dex_volume_24h_usd": float(event.get("volume_24h_usd", 0) or 0),
                "dex_txn_imbalance_24h": imbalance,
            }
        )
    return out


def normalize_macro_rates(events: List[Dict]) -> List[Dict]:
    out: List[Dict] = []
    for event in events:
        payload = event.get("payload", {})
        observations = payload.get("observations", [])
        if observations:
            latest = observations[-1]
            try:
                fed_funds = float(latest.get("value"))
            except (TypeError, ValueError):
                fed_funds = 0.0
        else:
            fed_funds = 0.0
        out.append(
            {
                "event_time": event.get("event_time"),
                "fed_funds_rate": fed_funds,
            }
        )
    return out


def normalize_fed_calendar(events: List[Dict]) -> List[Dict]:
    out: List[Dict] = []
    now = datetime.now(timezone.utc).date().isoformat()
    for event in events:
        payload = event.get("payload", {})
        dates = payload.get("decision_dates_utc", [])
        next_date = ""
        for d in dates:
            if d >= now:
                next_date = d
                break
        out.append({"event_time": event.get("event_time"), "next_fed_decision_date": next_date})
    return out

