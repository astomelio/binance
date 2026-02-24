from __future__ import annotations

import glob
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List

import duckdb
import pandas as pd

from data_platform.config import DataPlatformConfig


def _iter_jsonl(path_pattern: str) -> Iterable[Dict]:
    for file in glob.glob(path_pattern, recursive=True):
        with open(file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    yield json.loads(line)


def _parse_iso_date(value: str) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _load_market_snapshot_raw(cfg: DataPlatformConfig) -> pd.DataFrame:
    rows: List[Dict] = []
    seen = set()
    patterns = [
        f"{cfg.lake_root}/bronze/binance_local_api/market_snapshot/**/part-*.jsonl",
        f"{cfg.lake_root}/bronze/binance_historical/market_snapshot/**/part-*.jsonl",
        f"{cfg.lake_root}/bronze/binance_vision/market_snapshot/**/part-*.jsonl",
    ]
    for pattern in patterns:
        for event in _iter_jsonl(pattern):
            symbol = str(event.get("symbol", "")).upper()
            key = (event.get("event_time"), symbol)
            if key in seen:
                continue
            seen.add(key)
            spot = event.get("spot_ticker", {}) or {}
            fut = event.get("futures_ticker", {}) or {}
            rows.append(
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
    return pd.DataFrame(rows)


def _load_derivatives_snapshot_raw(cfg: DataPlatformConfig) -> pd.DataFrame:
    rows: List[Dict] = []
    seen = set()
    patterns = [
        f"{cfg.lake_root}/bronze/binance_public/derivatives_snapshot/**/part-*.jsonl",
        f"{cfg.lake_root}/bronze/binance_historical/derivatives_snapshot/**/part-*.jsonl",
        f"{cfg.lake_root}/bronze/binance_vision/derivatives_snapshot/**/part-*.jsonl",
    ]
    for pattern in patterns:
        for event in _iter_jsonl(pattern):
            symbol = str(event.get("symbol", "")).upper()
            key = (event.get("event_time"), symbol)
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "event_time": event.get("event_time"),
                    "symbol": symbol,
                    "mark_price": float(event.get("mark_price", 0) or 0),
                    "index_price": float(event.get("index_price", 0) or 0),
                    "last_funding_rate": float(event.get("last_funding_rate", 0) or 0),
                    "open_interest": float(event.get("open_interest", 0) or 0),
                    "price_change_percent_24h": float(event.get("price_change_percent_24h", 0) or 0),
                    "quote_volume_24h": float(event.get("quote_volume_24h", 0) or 0),
                }
            )
    return pd.DataFrame(rows)


def _load_derivatives_flow_raw(cfg: DataPlatformConfig) -> pd.DataFrame:
    rows: List[Dict] = []
    seen = set()
    patterns = [
        f"{cfg.lake_root}/bronze/binance_public/derivatives_flow/**/part-*.jsonl",
        f"{cfg.lake_root}/bronze/binance_historical/derivatives_flow/**/part-*.jsonl",
        f"{cfg.lake_root}/bronze/binance_vision/derivatives_flow/**/part-*.jsonl",
    ]
    for pattern in patterns:
        for event in _iter_jsonl(pattern):
            symbol = str(event.get("symbol", "")).upper()
            key = (event.get("event_time"), symbol)
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "event_time": event.get("event_time"),
                    "symbol": symbol,
                    "long_short_account_ratio": float(event.get("long_short_account_ratio", 0) or 0),
                    "buy_sell_ratio": float(event.get("buy_sell_ratio", 0) or 0),
                    "buy_vol": float(event.get("buy_vol", 0) or 0),
                    "sell_vol": float(event.get("sell_vol", 0) or 0),
                }
            )
    return pd.DataFrame(rows)


def _load_cross_exchange_raw(cfg: DataPlatformConfig) -> pd.DataFrame:
    rows: List[Dict] = []
    seen = set()
    patterns = [
        f"{cfg.lake_root}/bronze/bybit_public/futures_snapshot/**/part-*.jsonl",
        f"{cfg.lake_root}/bronze/okx_public/futures_snapshot/**/part-*.jsonl",
        f"{cfg.lake_root}/bronze/bybit_historical/futures_snapshot/**/part-*.jsonl",
        f"{cfg.lake_root}/bronze/okx_historical/futures_snapshot/**/part-*.jsonl",
    ]
    for pattern in patterns:
        for event in _iter_jsonl(pattern):
            symbol = str(event.get("symbol", "")).upper()
            exchange = str(event.get("exchange", "")).lower()
            key = (event.get("event_time"), symbol, exchange)
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "event_time": event.get("event_time"),
                    "symbol": symbol,
                    "exchange": exchange,
                    "last_price": float(event.get("last_price", 0) or 0),
                    "bid_price": float(event.get("bid_price", 0) or 0),
                    "ask_price": float(event.get("ask_price", 0) or 0),
                    "quote_volume_24h": float(event.get("quote_volume_24h", 0) or 0),
                }
            )
    return pd.DataFrame(rows)


def _load_dex_raw(cfg: DataPlatformConfig) -> pd.DataFrame:
    rows: List[Dict] = []
    seen = set()
    patterns = [
        f"{cfg.lake_root}/bronze/dexscreener/dex_snapshot/**/part-*.jsonl",
        f"{cfg.lake_root}/bronze/dexscreener_historical/dex_snapshot/**/part-*.jsonl",
    ]
    for pattern in patterns:
        for event in _iter_jsonl(pattern):
            symbol = str(event.get("symbol", "")).upper()
            pair = str(event.get("pair_address", "")).lower()
            key = (event.get("event_time"), symbol, pair)
            if key in seen:
                continue
            seen.add(key)
            buys = float(event.get("txns_buys_24h", 0) or 0)
            sells = float(event.get("txns_sells_24h", 0) or 0)
            total = buys + sells
            rows.append(
                {
                    "event_time": event.get("event_time"),
                    "symbol": symbol,
                    "chain_id": str(event.get("chain_id", "")).lower(),
                    "pair_address": pair,
                    "dex_id": str(event.get("dex_id", "")).lower(),
                    "dex_price_usd": float(event.get("price_usd", 0) or 0),
                    "dex_liquidity_usd": float(event.get("liquidity_usd", 0) or 0),
                    "dex_volume_24h_usd": float(event.get("volume_24h_usd", 0) or 0),
                    "dex_txn_imbalance_24h": ((buys - sells) / total) if total > 0 else 0.0,
                }
            )
    return pd.DataFrame(rows)


def _load_global_market_raw(cfg: DataPlatformConfig) -> pd.DataFrame:
    rows: List[Dict] = []
    patterns = [
        f"{cfg.lake_root}/bronze/coingecko/global_market/**/part-*.jsonl",
        f"{cfg.lake_root}/bronze/coingecko_historical/global_market/**/part-*.jsonl",
    ]
    seen = set()
    for pattern in patterns:
        for event in _iter_jsonl(pattern):
            payload = event.get("payload", {}) or {}
            key = (event.get("event_time"),)
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "event_time": event.get("event_time"),
                    "btc_dominance": float(payload.get("market_cap_percentage", {}).get("btc", 0) or 0),
                    "total_market_cap_usd": float(payload.get("total_market_cap", {}).get("usd", 0) or 0),
                    "total_volume_usd": float(payload.get("total_volume", {}).get("usd", 0) or 0),
                }
            )
    return pd.DataFrame(rows)


def _load_fear_greed_raw(cfg: DataPlatformConfig) -> pd.DataFrame:
    rows: List[Dict] = []
    patterns = [
        f"{cfg.lake_root}/bronze/alternative_me/fear_greed_index/**/part-*.jsonl",
        f"{cfg.lake_root}/bronze/alternative_me_historical/fear_greed_index/**/part-*.jsonl",
    ]
    for pattern in patterns:
        for event in _iter_jsonl(pattern):
            rows.append(
                {
                    "event_time": event.get("event_time"),
                    "fear_greed_value": float(event.get("value", 0) or 0),
                    "fear_greed_classification": str(event.get("classification", "")),
                }
            )
    return pd.DataFrame(rows)


def _load_macro_rates_raw(cfg: DataPlatformConfig) -> pd.DataFrame:
    rows: List[Dict] = []
    seen: set = set()
    patterns = [
        f"{cfg.lake_root}/bronze/fred/macro_rates/**/part-*.jsonl",
        f"{cfg.lake_root}/bronze/fred_historical/macro_rates/**/part-*.jsonl",
    ]
    for pattern in patterns:
        for event in _iter_jsonl(pattern):
            et = event.get("event_time")
            if et in seen:
                continue
            fed_funds_rate = 0.0
            if "fed_funds_rate" in event:
                fed_funds_rate = float(event.get("fed_funds_rate", 0) or 0)
            else:
                payload = event.get("payload", {}) or {}
                observations = payload.get("observations", []) or []
                if observations:
                    try:
                        fed_funds_rate = float(observations[-1].get("value", 0) or 0)
                    except (ValueError, TypeError):
                        pass
            seen.add(et)
            rows.append({"event_time": et, "fed_funds_rate": fed_funds_rate})
    return pd.DataFrame(rows)


def _load_macro_assets_raw(cfg: DataPlatformConfig) -> pd.DataFrame:
    rows: List[Dict] = []
    seen: set = set()
    for event in _iter_jsonl(f"{cfg.lake_root}/bronze/fred_historical/macro_assets/**/part-*.jsonl"):
        et = event.get("event_time")
        if et in seen:
            continue
        seen.add(et)
        rows.append({
            "event_time": et,
            "sp500_close": float(event.get("sp500_close") or 0) if event.get("sp500_close") is not None else None,
            "oil_wti_usd": float(event.get("oil_wti_usd") or 0) if event.get("oil_wti_usd") is not None else None,
        })
    return pd.DataFrame(rows)


def _load_fed_calendar_raw(cfg: DataPlatformConfig) -> pd.DataFrame:
    rows: List[Dict] = []
    now = datetime.now(timezone.utc).date().isoformat()
    patterns = [
        f"{cfg.lake_root}/bronze/fed_calendar/decision_dates/**/part-*.jsonl",
        f"{cfg.lake_root}/bronze/fed_calendar_historical/decision_dates/**/part-*.jsonl",
    ]
    all_dates: List[str] = []
    for pattern in patterns:
        for event in _iter_jsonl(pattern):
            payload = event.get("payload", {}) or {}
            dates = payload.get("decision_dates_utc", []) or []
            if not dates and "decision_date" in event:
                dates = [event["decision_date"]]
            for d in dates:
                if d and d not in all_dates:
                    all_dates.append(d)
    all_dates = sorted(set(all_dates))
    next_date = ""
    for d in all_dates:
        if d >= now:
            next_date = d
            break
    # One row per FOMC date; br_macro_context joins - we need one row with next_fed for propagation
    if all_dates:
        rows.append({"event_time": now + "T12:00:00+00:00", "next_fed_decision_date": next_date})
    return pd.DataFrame(rows)


_EMPTY_TABLE_DDL: Dict[str, str] = {
    "market_snapshot_raw": "event_time VARCHAR, symbol VARCHAR, spot_last_price DOUBLE, spot_volume DOUBLE, futures_last_price DOUBLE, futures_volume DOUBLE, futures_quote_volume DOUBLE",
    "derivatives_snapshot_raw": "event_time VARCHAR, symbol VARCHAR, mark_price DOUBLE, index_price DOUBLE, last_funding_rate DOUBLE, open_interest DOUBLE, price_change_percent_24h DOUBLE, quote_volume_24h DOUBLE",
    "derivatives_flow_raw": "event_time VARCHAR, symbol VARCHAR, long_short_account_ratio DOUBLE, buy_sell_ratio DOUBLE, buy_vol DOUBLE, sell_vol DOUBLE",
    "cross_exchange_snapshot_raw": "event_time VARCHAR, symbol VARCHAR, exchange VARCHAR, last_price DOUBLE, bid_price DOUBLE, ask_price DOUBLE, quote_volume_24h DOUBLE",
    "dex_snapshot_raw": "event_time VARCHAR, symbol VARCHAR, chain_id VARCHAR, pair_address VARCHAR, dex_id VARCHAR, dex_price_usd DOUBLE, dex_liquidity_usd DOUBLE, dex_volume_24h_usd DOUBLE, dex_txn_imbalance_24h DOUBLE",
    "global_market_raw": "event_time VARCHAR, btc_dominance DOUBLE, total_market_cap_usd DOUBLE, total_volume_usd DOUBLE",
    "fear_greed_raw": "event_time VARCHAR, fear_greed_value DOUBLE, fear_greed_classification VARCHAR",
    "macro_rates_raw": "event_time VARCHAR, fed_funds_rate DOUBLE",
    "macro_assets_raw": "event_time VARCHAR, sp500_close DOUBLE, oil_wti_usd DOUBLE",
    "fed_calendar_raw": "event_time VARCHAR, next_fed_decision_date VARCHAR",
}


def _replace_table(
    con: duckdb.DuckDBPyConnection, schema: str, table_name: str, df: pd.DataFrame
) -> None:
    if df.empty:
        ddl = _EMPTY_TABLE_DDL.get(table_name, "event_time VARCHAR")
        con.execute(f"create schema if not exists {schema}")
        con.execute(f"create or replace table {schema}.{table_name} ({ddl})")
        return
    con.execute(f"create schema if not exists {schema}")
    view_name = f"tmp_{table_name}"
    con.register(view_name, df)
    con.execute(f"create or replace table {schema}.{table_name} as select * from {view_name}")
    con.unregister(view_name)


def load_bronze_to_duckdb(
    cfg: DataPlatformConfig,
    db_path: str,
    *,
    schema: str = "main",
    tables_only: List[str] | None = None,
) -> Dict[str, int]:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(db_path)
    # All tables in main schema (DuckDB default)

    all_datasets = {
        "market_snapshot_raw": _load_market_snapshot_raw(cfg),
        "derivatives_snapshot_raw": _load_derivatives_snapshot_raw(cfg),
        "derivatives_flow_raw": _load_derivatives_flow_raw(cfg),
        "cross_exchange_snapshot_raw": _load_cross_exchange_raw(cfg),
        "dex_snapshot_raw": _load_dex_raw(cfg),
        "global_market_raw": _load_global_market_raw(cfg),
        "fear_greed_raw": _load_fear_greed_raw(cfg),
        "macro_rates_raw": _load_macro_rates_raw(cfg),
        "macro_assets_raw": _load_macro_assets_raw(cfg),
        "fed_calendar_raw": _load_fed_calendar_raw(cfg),
    }
    datasets = (
        {k: v for k, v in all_datasets.items() if k in tables_only}
        if tables_only
        else all_datasets
    )
    counts: Dict[str, int] = {}
    for table_name, df in datasets.items():
        _replace_table(con, schema, table_name, df)
        counts[table_name] = int(df.shape[0])
    con.close()
    return counts

