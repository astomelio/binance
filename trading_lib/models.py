from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Regime(str, Enum):
    BEARISH = "BEARISH"
    SIDEWAYS = "SIDEWAYS"
    BULLISH = "BULLISH"
    UNDEFINED = "UNDEFINED"


class TradeSignal(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass
class Candle:
    open_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class FeatureSet:
    regime: Regime
    last_close: float
    sma20: float
    sma50: float
    sma200: float
    rsi14: float
    atr14: float
    volume_ratio20: float


@dataclass
class SignalDecision:
    signal: TradeSignal
    position_side: Optional[str]
    confidence: float
    reason: str
    stop_price: Optional[float] = None
    take_profit_price: Optional[float] = None
    expected_move_percent: float = 0.0

