from __future__ import annotations

from typing import Dict, List, Optional

import requests

from .models import Candle


class BinanceConnectorClient:
    """HTTP client for the local FastAPI Binance connector."""

    def __init__(self, base_url: str = "http://localhost:8000") -> None:
        self.base_url = base_url.rstrip("/")

    def _request(self, method: str, path: str, params: Optional[Dict] = None, body: Optional[Dict] = None) -> Dict:
        url = f"{self.base_url}{path}"
        resp = requests.request(method, url, params=params, json=body, timeout=25)
        try:
            resp.raise_for_status()
        except requests.exceptions.HTTPError as e:
            import logging
            logging.getLogger(__name__).error(f"API Error: {method} {path} -> {resp.text}")
            raise
        return resp.json()

    def get_spot_klines(self, symbol: str, interval: str = "1h", limit: int = 300) -> List[Candle]:
        payload = self._request("GET", f"/market/klines/{symbol}", params={"interval": interval, "limit": limit})
        if payload.get("status") != "success":
            raise ValueError(f"Invalid response: {payload}")
        out = []
        for row in payload["data"]:
            out.append(
                Candle(
                    open_time=int(row["open_time"]),
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row["volume"]),
                )
            )
        return out

    def get_futures_klines(self, symbol: str, interval: str = "1h", limit: int = 300) -> List[Candle]:
        payload = self._request(
            "GET",
            f"/futures/market/klines/{symbol}",
            params={"interval": interval, "limit": limit},
        )
        if payload.get("status") != "success":
            raise ValueError(f"Invalid response: {payload}")
        out = []
        for row in payload["data"]:
            out.append(
                Candle(
                    open_time=int(row["open_time"]),
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row["volume"]),
                )
            )
        return out

    def get_optimal_futures_price(self, symbol: str, side: str, offset_percent: float = 0.1) -> float:
        payload = self._request(
            "GET",
            f"/futures/order/optimal-price/{symbol}",
            params={"side": side, "price_offset_percent": offset_percent},
        )
        if payload.get("status") != "success":
            raise ValueError(f"Invalid response: {payload}")
        return float(payload["data"]["suggested_limit_price"])

    def create_smart_futures_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        position_side: str,
        offset_percent: float = 0.1,
    ) -> Dict:
        payload = self._request(
            "POST",
            "/futures/order/smart-limit",
            body={
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "position_side": position_side,
                "price_offset_percent": offset_percent,
            },
        )
        return payload

    def get_futures_account_balance(self) -> Dict:
        payload = self._request("GET", "/futures/account/balance")
        if payload.get("status") != "success":
            raise ValueError(f"Invalid response: {payload}")
        return payload["data"]

    def get_futures_positions(self) -> List[Dict]:
        payload = self._request("GET", "/futures/positions")
        if payload.get("status") != "success":
            raise ValueError(f"Invalid response: {payload}")
        return payload["data"]

    def get_futures_ticker_price(self, symbol: str) -> float:
        payload = self._request("GET", f"/futures/market/ticker/{symbol}")
        if payload.get("status") != "success":
            raise ValueError(f"Invalid response: {payload}")
        return float(payload["data"]["last_price"])

    def get_futures_order_book(self, symbol: str, limit: int = 5) -> Dict:
        """Get order book for limit order pricing (maker fees)."""
        payload = self._request("GET", f"/futures/market/orderbook/{symbol}", params={"limit": limit})
        if payload.get("status") != "success":
            raise ValueError(f"Invalid response: {payload}")
        return payload["data"]

    def get_futures_exchange_info(self) -> Dict:
        payload = self._request("GET", "/futures/exchange-info")
        if payload.get("status") != "success":
            raise ValueError(f"Invalid response: {payload}")
        return payload["data"]

    def create_futures_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str = "MARKET",
        position_side: str | None = None,
        reduce_only: bool = False,
        price: float | None = None,
        time_in_force: str | None = None,
        stop_price: float | None = None,
    ) -> Dict:
        body: Dict = {
            "symbol": symbol,
            "side": side,
            "order_type": order_type,
            "quantity": quantity,
            "reduce_only": reduce_only,
        }
        if position_side:
            body["position_side"] = position_side
        if price is not None:
            body["price"] = price
        if time_in_force:
            body["time_in_force"] = time_in_force
        if stop_price is not None:
            body["stop_price"] = stop_price
        return self._request("POST", "/futures/order/create", body=body)

