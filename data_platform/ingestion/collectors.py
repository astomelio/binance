from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

import requests

from data_platform.ingestion.base import Collector


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class BinanceLocalCollector(Collector):
    source = "binance_local_api"
    dataset = "market_snapshot"

    def __init__(self, base_url: str, symbols: List[str]) -> None:
        self.base_url = base_url.rstrip("/")
        self.symbols = symbols

    def _get(self, path: str, params: Dict | None = None) -> Dict:
        resp = requests.get(f"{self.base_url}{path}", params=params, timeout=20)
        resp.raise_for_status()
        return resp.json()

    def collect(self) -> List[Dict]:
        rows: List[Dict] = []
        ts = utc_now_iso()
        for symbol in self.symbols:
            spot_ticker = self._get(f"/market/ticker/{symbol}")
            futures_ticker = self._get(f"/futures/market/ticker/{symbol}")
            spot_klines = self._get(f"/market/klines/{symbol}", {"interval": "1m", "limit": 120})
            futures_klines = self._get(f"/futures/market/klines/{symbol}", {"interval": "1m", "limit": 120})

            rows.append(
                {
                    "event_time": ts,
                    "symbol": symbol,
                    "spot_ticker": spot_ticker.get("data", {}),
                    "futures_ticker": futures_ticker.get("data", {}),
                    "spot_klines_1m": spot_klines.get("data", []),
                    "futures_klines_1m": futures_klines.get("data", []),
                }
            )
        return rows


class CoinGeckoGlobalCollector(Collector):
    source = "coingecko"
    dataset = "global_market"

    def collect(self) -> List[Dict]:
        resp = requests.get("https://api.coingecko.com/api/v3/global", timeout=20)
        resp.raise_for_status()
        payload = resp.json()
        return [{"event_time": utc_now_iso(), "payload": payload.get("data", {})}]


class FearGreedCollector(Collector):
    source = "alternative_me"
    dataset = "fear_greed_index"

    def collect(self) -> List[Dict]:
        resp = requests.get("https://api.alternative.me/fng/?limit=1&format=json", timeout=20)
        resp.raise_for_status()
        payload = resp.json()
        data = payload.get("data", [{}])[0] if payload.get("data") else {}
        return [
            {
                "event_time": utc_now_iso(),
                "value": float(data.get("value", 0) or 0),
                "classification": data.get("value_classification", ""),
                "timestamp": data.get("timestamp", ""),
            }
        ]


class BinanceDerivativesPublicCollector(Collector):
    source = "binance_public"
    dataset = "derivatives_snapshot"

    def __init__(self, symbols: List[str]) -> None:
        self.symbols = symbols

    def collect(self) -> List[Dict]:
        rows: List[Dict] = []
        ts = utc_now_iso()
        base = "https://fapi.binance.com"

        for symbol in self.symbols:
            premium = requests.get(
                f"{base}/fapi/v1/premiumIndex",
                params={"symbol": symbol.upper()},
                timeout=20,
            )
            premium.raise_for_status()
            premium_payload = premium.json()

            open_interest = requests.get(
                f"{base}/fapi/v1/openInterest",
                params={"symbol": symbol.upper()},
                timeout=20,
            )
            open_interest.raise_for_status()
            oi_payload = open_interest.json()

            ticker_24h = requests.get(
                f"{base}/fapi/v1/ticker/24hr",
                params={"symbol": symbol.upper()},
                timeout=20,
            )
            ticker_24h.raise_for_status()
            ticker_payload = ticker_24h.json()

            rows.append(
                {
                    "event_time": ts,
                    "symbol": symbol.upper(),
                    "mark_price": premium_payload.get("markPrice"),
                    "index_price": premium_payload.get("indexPrice"),
                    "last_funding_rate": premium_payload.get("lastFundingRate"),
                    "next_funding_time": premium_payload.get("nextFundingTime"),
                    "open_interest": oi_payload.get("openInterest"),
                    "open_interest_symbol": oi_payload.get("symbol"),
                    "price_change_percent_24h": ticker_payload.get("priceChangePercent"),
                    "quote_volume_24h": ticker_payload.get("quoteVolume"),
                }
            )

        return rows


class BinanceDerivativesFlowCollector(Collector):
    source = "binance_public"
    dataset = "derivatives_flow"

    def __init__(self, symbols: List[str]) -> None:
        self.symbols = symbols

    def collect(self) -> List[Dict]:
        rows: List[Dict] = []
        ts = utc_now_iso()
        for symbol in self.symbols:
            s = symbol.upper()
            # Global long/short account ratio
            gls = requests.get(
                "https://fapi.binance.com/futures/data/globalLongShortAccountRatio",
                params={"symbol": s, "period": "1h", "limit": 1},
                timeout=20,
            )
            gls.raise_for_status()
            gls_data = gls.json()
            gls_latest = gls_data[-1] if gls_data else {}

            # Taker buy/sell volume ratio
            taker = requests.get(
                "https://fapi.binance.com/futures/data/takerlongshortRatio",
                params={"symbol": s, "period": "1h", "limit": 1},
                timeout=20,
            )
            taker.raise_for_status()
            taker_data = taker.json()
            taker_latest = taker_data[-1] if taker_data else {}

            rows.append(
                {
                    "event_time": ts,
                    "symbol": s,
                    "long_short_account_ratio": float(gls_latest.get("longShortRatio", 0) or 0),
                    "long_account": float(gls_latest.get("longAccount", 0) or 0),
                    "short_account": float(gls_latest.get("shortAccount", 0) or 0),
                    "buy_sell_ratio": float(taker_latest.get("buySellRatio", 0) or 0),
                    "buy_vol": float(taker_latest.get("buyVol", 0) or 0),
                    "sell_vol": float(taker_latest.get("sellVol", 0) or 0),
                }
            )

        return rows


class BybitFuturesCollector(Collector):
    source = "bybit_public"
    dataset = "futures_snapshot"

    def __init__(self, symbols: List[str]) -> None:
        self.symbols = symbols

    def collect(self) -> List[Dict]:
        rows: List[Dict] = []
        ts = utc_now_iso()
        base = "https://api.bybit.com/v5/market/tickers"
        for symbol in self.symbols:
            s = symbol.upper()
            resp = requests.get(base, params={"category": "linear", "symbol": s}, timeout=20)
            resp.raise_for_status()
            payload = resp.json()
            tickers = payload.get("result", {}).get("list", [])
            ticker = tickers[0] if tickers else {}
            rows.append(
                {
                    "event_time": ts,
                    "exchange": "bybit",
                    "symbol": s,
                    "last_price": float(ticker.get("lastPrice", 0) or 0),
                    "bid_price": float(ticker.get("bid1Price", 0) or 0),
                    "ask_price": float(ticker.get("ask1Price", 0) or 0),
                    "quote_volume_24h": float(ticker.get("turnover24h", 0) or 0),
                }
            )
        return rows


class OKXFuturesCollector(Collector):
    source = "okx_public"
    dataset = "futures_snapshot"

    def __init__(self, symbols: List[str]) -> None:
        self.symbols = symbols

    @staticmethod
    def _to_okx_inst_id(symbol: str) -> str:
        base = symbol.replace("USDT", "")
        return f"{base}-USDT-SWAP"

    def collect(self) -> List[Dict]:
        rows: List[Dict] = []
        ts = utc_now_iso()
        base = "https://www.okx.com/api/v5/market/ticker"
        for symbol in self.symbols:
            s = symbol.upper()
            inst_id = self._to_okx_inst_id(s)
            resp = requests.get(base, params={"instId": inst_id}, timeout=20)
            resp.raise_for_status()
            payload = resp.json()
            data = payload.get("data", [])
            ticker = data[0] if data else {}
            rows.append(
                {
                    "event_time": ts,
                    "exchange": "okx",
                    "symbol": s,
                    "last_price": float(ticker.get("last", 0) or 0),
                    "bid_price": float(ticker.get("bidPx", 0) or 0),
                    "ask_price": float(ticker.get("askPx", 0) or 0),
                    "quote_volume_24h": float(ticker.get("volCcy24h", 0) or 0),
                }
            )
        return rows


class DexScreenerCollector(Collector):
    source = "dexscreener"
    dataset = "dex_snapshot"

    def __init__(self, pairs: List[Dict]) -> None:
        self.pairs = pairs

    def collect(self) -> List[Dict]:
        if not self.pairs:
            return []
        rows: List[Dict] = []
        ts = utc_now_iso()
        for pair in self.pairs:
            chain_id = str(pair.get("chain_id", "")).strip().lower()
            pair_address = str(pair.get("pair_address", "")).strip()
            symbol = str(pair.get("symbol", "")).strip().upper()
            if not chain_id or not pair_address or not symbol:
                continue
            url = f"https://api.dexscreener.com/latest/dex/pairs/{chain_id}/{pair_address}"
            resp = requests.get(url, timeout=20)
            resp.raise_for_status()
            payload = resp.json()
            pair_data = payload.get("pair", {}) or {}
            txns_24h = pair_data.get("txns", {}).get("h24", {})
            buys = float(txns_24h.get("buys", 0) or 0)
            sells = float(txns_24h.get("sells", 0) or 0)
            rows.append(
                {
                    "event_time": ts,
                    "symbol": symbol,
                    "chain_id": chain_id,
                    "pair_address": pair_address,
                    "dex_id": pair_data.get("dexId", ""),
                    "price_usd": float(pair_data.get("priceUsd", 0) or 0),
                    "liquidity_usd": float(pair_data.get("liquidity", {}).get("usd", 0) or 0),
                    "volume_24h_usd": float(pair_data.get("volume", {}).get("h24", 0) or 0),
                    "txns_buys_24h": buys,
                    "txns_sells_24h": sells,
                }
            )
        return rows


class FREDMacroCollector(Collector):
    source = "fred"
    dataset = "macro_rates"

    def __init__(self, fred_api_key: str) -> None:
        self.fred_api_key = fred_api_key

    def collect(self) -> List[Dict]:
        if not self.fred_api_key:
            return []

        # FEDFUNDS is a practical baseline for rate regime.
        url = "https://api.stlouisfed.org/fred/series/observations"
        params = {
            "series_id": "FEDFUNDS",
            "api_key": self.fred_api_key,
            "file_type": "json",
            "sort_order": "desc",
            "limit": 5,
        }
        resp = requests.get(url, params=params, timeout=20)
        resp.raise_for_status()
        payload = resp.json()
        return [{"event_time": utc_now_iso(), "payload": payload}]


class FedCalendarCollector(Collector):
    source = "fed_calendar"
    dataset = "decision_dates"

    FED_CALENDAR_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
    _MONTH_MAP = {
        "january": 1,
        "february": 2,
        "march": 3,
        "april": 4,
        "may": 5,
        "june": 6,
        "july": 7,
        "august": 8,
        "september": 9,
        "october": 10,
        "november": 11,
        "december": 12,
    }

    def __init__(self, file_path: str = "data_platform/config/fed_decision_dates.json", live_url: str | None = None) -> None:
        self.file_path = Path(file_path)
        self.live_url = live_url or self.FED_CALENDAR_URL

    def _parse_fomc_dates_from_html(self, html: str) -> List[str]:
        dates: List[str] = []
        now = datetime.now(timezone.utc)
        min_dt = now.replace(year=now.year - 1)
        max_dt = now.replace(year=now.year + 2)

        section_re = re.compile(
            r'<a id="(?P<id>\d+)">(?P<year>\d{4}) FOMC Meetings</a></h4></div>(?P<body>.*?)(?:</div>\s*</div>\s*<div class="panel panel-default"|<div class=\'lastUpdate\')',
            re.IGNORECASE | re.DOTALL,
        )
        row_re = re.compile(
            r'fomc-meeting__month[^>]*><strong>(?P<month>[^<]+)</strong>.*?fomc-meeting__date[^>]*>(?P<date>[^<]+)</div>',
            re.IGNORECASE | re.DOTALL,
        )

        for section in section_re.finditer(html):
            year = int(section.group("year"))
            body = section.group("body")
            for row in row_re.finditer(body):
                month_text = row.group("month").strip()
                date_text = row.group("date").strip()

                # Keep only main meeting ranges like "27-28", "30-1", excluding "22 (notation vote)".
                cleaned_date = re.sub(r"\*|\(.*?\)", "", date_text).strip()
                if "-" not in cleaned_date:
                    continue
                parts = cleaned_date.split("-")
                if len(parts) != 2:
                    continue

                try:
                    start_day = int(parts[0].strip())
                    end_day = int(parts[1].strip())
                except ValueError:
                    continue

                month_parts = [m.strip().lower() for m in month_text.split("/") if m.strip()]
                if not month_parts:
                    continue

                # If the range crosses month (e.g., "Apr/May 30-1"), decision day is in second month.
                if len(month_parts) > 1 and end_day < start_day:
                    decision_month_name = month_parts[-1]
                else:
                    decision_month_name = month_parts[0]

                if decision_month_name not in self._MONTH_MAP:
                    continue

                decision_month = self._MONTH_MAP[decision_month_name]
                try:
                    dt = datetime(year, decision_month, end_day, tzinfo=timezone.utc)
                except ValueError:
                    continue
                if dt < min_dt or dt > max_dt:
                    continue
                dates.append(dt.strftime("%Y-%m-%d"))

        return sorted(set(dates))

    def collect(self) -> List[Dict]:
        # 1) Try official live source
        try:
            resp = requests.get(self.live_url, timeout=20)
            resp.raise_for_status()
            dates = self._parse_fomc_dates_from_html(resp.text)
            # Quality gate: a valid FOMC calendar should include multiple future dates.
            if len(dates) >= 4:
                return [
                    {
                        "event_time": utc_now_iso(),
                        "payload": {
                            "source": "federalreserve_live",
                            "source_url": self.live_url,
                            "decision_dates_utc": dates,
                        },
                    }
                ]
        except Exception:
            pass

        # 2) Fallback local backup seed
        if not self.file_path.exists():
            return []
        payload = json.loads(self.file_path.read_text(encoding="utf-8"))
        payload["source"] = payload.get("source", "fallback_seed")
        payload["source_url"] = str(self.file_path)
        return [{"event_time": utc_now_iso(), "payload": payload}]


class OnChainCollector(Collector):
    source = "onchain_provider"
    dataset = "onchain_snapshot"

    def __init__(self, provider_url: str) -> None:
        self.provider_url = provider_url

    def collect(self) -> List[Dict]:
        if not self.provider_url:
            return [{"event_time": utc_now_iso(), "warning": "ONCHAIN_PROVIDER_URL not set"}]
        resp = requests.get(self.provider_url, timeout=20)
        resp.raise_for_status()
        payload = resp.json()
        return [{"event_time": utc_now_iso(), "payload": payload}]

