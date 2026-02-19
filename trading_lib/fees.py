from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class FeeModel:
    """Fee model reusable in backtest and live.

    Defaults are Binance-like for non-VIP spot.
    """

    spot_maker: float = 0.001
    spot_taker: float = 0.001
    futures_maker: float = 0.0002
    futures_taker: float = 0.0004

    def rate(self, market_type: str, is_maker: bool) -> float:
        if market_type == "futures":
            return self.futures_maker if is_maker else self.futures_taker
        return self.spot_maker if is_maker else self.spot_taker

    def round_trip_fee_percent(self, market_type: str = "spot", is_maker: bool = True) -> float:
        # Approximation: open + close
        rate = self.rate(market_type, is_maker)
        return (2 * rate) * 100

    def round_trip_fee_amount(
        self,
        notional_usd: float,
        market_type: str = "spot",
        is_maker: bool = True,
    ) -> float:
        return notional_usd * (self.round_trip_fee_percent(market_type, is_maker) / 100.0)

    def net_edge_percent(
        self,
        expected_move_percent: float,
        market_type: str = "spot",
        is_maker: bool = True,
    ) -> float:
        return expected_move_percent - self.round_trip_fee_percent(market_type, is_maker)

