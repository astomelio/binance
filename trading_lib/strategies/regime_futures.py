from __future__ import annotations

from ..fees import FeeModel
from ..models import FeatureSet, Regime, SignalDecision, TradeSignal
from .base import Strategy


class RegimeFuturesStrategy(Strategy):
    """Estrategia reusable para futuros.

    Reglas:
    - Bajista: prioriza shorts en rebotes fallidos; longs solo en sobreventa extrema.
    - Lateral: buy dip / sell rally con umbrales de RSI.
    - Alcista: comprar pullbacks.
    - Siempre filtra por edge neto (movimiento esperado - fees round trip).
    """

    def __init__(self, min_net_edge_percent: float = 0.40) -> None:
        self.min_net_edge_percent = min_net_edge_percent

    def generate(self, features: FeatureSet, fee_model: FeeModel) -> SignalDecision:
        rsi = features.rsi14
        last = features.last_close
        atr = max(features.atr14, last * 0.005)
        break_even = fee_model.round_trip_fee_percent("futures", is_maker=True)

        signal = TradeSignal.HOLD
        position_side = None
        confidence = 0.0
        reason = "Sin setup claro"

        stop = None
        tp = None
        expected_move = 0.0

        if features.regime == Regime.BEARISH:
            # Short en rebote débil
            if rsi > 52 and last < features.sma50:
                signal = TradeSignal.SELL
                position_side = "SHORT"
                confidence = 0.73
                stop = last + (1.5 * atr)
                tp = last - (2.2 * atr)
                reason = "Bajista: rebote débil para short"
            # Long de rebote táctico, pequeño
            elif rsi < 24 and features.volume_ratio20 > 1.10:
                signal = TradeSignal.BUY
                position_side = "LONG"
                confidence = 0.62
                stop = last - (1.3 * atr)
                tp = last + (1.8 * atr)
                reason = "Bajista: sobreventa extrema para rebote táctico"

        elif features.regime == Regime.SIDEWAYS:
            if rsi < 35:
                signal = TradeSignal.BUY
                position_side = "LONG"
                confidence = 0.66
                stop = last - (1.2 * atr)
                tp = last + (1.8 * atr)
                reason = "Lateral: buy dip"
            elif rsi > 65:
                signal = TradeSignal.SELL
                position_side = "SHORT"
                confidence = 0.66
                stop = last + (1.2 * atr)
                tp = last - (1.8 * atr)
                reason = "Lateral: sell rally"

        elif features.regime == Regime.BULLISH:
            if rsi < 45 and last > features.sma50:
                signal = TradeSignal.BUY
                position_side = "LONG"
                confidence = 0.74
                stop = last - (1.4 * atr)
                tp = last + (2.3 * atr)
                reason = "Alcista: pullback sano"

        if signal != TradeSignal.HOLD and stop and tp:
            if signal == TradeSignal.BUY:
                expected_move = ((tp - last) / last) * 100
            else:
                expected_move = ((last - tp) / last) * 100

            net_edge = expected_move - break_even
            if net_edge < self.min_net_edge_percent:
                return SignalDecision(
                    signal=TradeSignal.HOLD,
                    position_side=None,
                    confidence=0.0,
                    reason=f"Edge insuficiente: {net_edge:.3f}% < {self.min_net_edge_percent:.3f}%",
                )

            return SignalDecision(
                signal=signal,
                position_side=position_side,
                confidence=confidence,
                reason=f"{reason} | edge={net_edge:.3f}% | be={break_even:.3f}%",
                stop_price=stop,
                take_profit_price=tp,
                expected_move_percent=expected_move,
            )

        return SignalDecision(
            signal=TradeSignal.HOLD,
            position_side=None,
            confidence=0.0,
            reason=reason,
        )

