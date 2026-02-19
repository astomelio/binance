from __future__ import annotations

from statistics import mean
from typing import List


def sma(values: List[float], period: int) -> float:
    if len(values) < period or period <= 0:
        return float("nan")
    return mean(values[-period:])


def rsi(values: List[float], period: int = 14) -> float:
    if len(values) < period + 1:
        return 50.0

    gains = []
    losses = []
    for i in range(-period, 0):
        diff = values[i] - values[i - 1]
        gains.append(max(diff, 0.0))
        losses.append(abs(min(diff, 0.0)))

    avg_gain = mean(gains)
    avg_loss = mean(losses)
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        return 0.0

    trs = []
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)
    return mean(trs[-period:])


def volume_ratio(volumes: List[float], lookback: int = 20) -> float:
    if len(volumes) < lookback or lookback <= 0:
        return 1.0
    baseline = mean(volumes[-lookback:])
    if baseline == 0:
        return 1.0
    return volumes[-1] / baseline

