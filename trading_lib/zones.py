from __future__ import annotations

import math
from typing import List

from .indicators import atr, rsi, sma, volume_ratio
from .models import Candle, FeatureSet, Regime


class ZoneClassifier:
    """Categoriza el mercado en regimenes y extrae features reutilizables."""

    def classify_regime(self, closes: List[float]) -> Regime:
        sma50 = sma(closes, 50)
        sma200 = sma(closes, 200)
        last = closes[-1]

        if math.isnan(sma200):
            return Regime.UNDEFINED
        if last < sma50 < sma200:
            return Regime.BEARISH
        if last > sma50 > sma200:
            return Regime.BULLISH
        return Regime.SIDEWAYS

    def build_features(self, candles: List[Candle]) -> FeatureSet:
        closes = [c.close for c in candles]
        highs = [c.high for c in candles]
        lows = [c.low for c in candles]
        volumes = [c.volume for c in candles]

        return FeatureSet(
            regime=self.classify_regime(closes),
            last_close=closes[-1],
            sma20=sma(closes, 20),
            sma50=sma(closes, 50),
            sma200=sma(closes, 200),
            rsi14=rsi(closes, 14),
            atr14=atr(highs, lows, closes, 14),
            volume_ratio20=volume_ratio(volumes, 20),
        )

