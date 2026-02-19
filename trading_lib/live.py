from __future__ import annotations

from dataclasses import asdict
from typing import Dict, Optional

from .api_client import BinanceConnectorClient
from .fees import FeeModel
from .models import TradeSignal
from .strategies.base import Strategy
from .trade_logger import TradingLogger
from .zones import ZoneClassifier


class FuturesLiveExecutor:
    """Ejecutor live para futuros usando la API local y estrategia reusable."""

    def __init__(
        self,
        client: BinanceConnectorClient,
        strategy: Strategy,
        fee_model: FeeModel,
        capital_usd: float = 500.0,
        risk_per_trade: float = 0.01,
        max_position_pct: float = 0.20,
        logger: TradingLogger | None = None,
    ) -> None:
        self.client = client
        self.strategy = strategy
        self.fee_model = fee_model
        self.classifier = ZoneClassifier()
        self.capital_usd = capital_usd
        self.risk_per_trade = risk_per_trade
        self.max_position_pct = max_position_pct
        self.logger = logger

    def _position_size_usd(self, entry: float, stop: float) -> float:
        max_risk_usd = self.capital_usd * self.risk_per_trade
        risk_per_unit = max(abs(entry - stop), entry * 0.005)
        units = max_risk_usd / risk_per_unit
        usd = units * entry
        return min(usd, self.capital_usd * self.max_position_pct)

    def evaluate(self, symbol: str, interval: str = "1h", limit: int = 300) -> Dict:
        candles = self.client.get_futures_klines(symbol, interval=interval, limit=limit)
        features = self.classifier.build_features(candles)
        decision = self.strategy.generate(features, self.fee_model)
        payload = {
            "symbol": symbol,
            "features": asdict(features),
            "decision": asdict(decision),
        }
        if self.logger:
            self.logger.event("LIVE_EVALUATE", payload)
        return payload

    def execute_if_actionable(self, symbol: str, interval: str = "1h", limit: int = 300) -> Dict:
        payload = self.evaluate(symbol, interval, limit)
        decision = payload["decision"]

        signal = decision["signal"]
        if signal == TradeSignal.HOLD.value:
            payload["executed"] = False
            payload["reason"] = "Sin señal operable."
            if self.logger:
                self.logger.event("LIVE_SKIP", payload)
            return payload

        side = "BUY" if signal == TradeSignal.BUY.value else "SELL"
        position_side = decision["position_side"] or ("LONG" if side == "BUY" else "SHORT")

        optimal_entry = self.client.get_optimal_futures_price(symbol, side=side, offset_percent=0.1)
        stop_price = decision["stop_price"] or (optimal_entry * (0.99 if side == "BUY" else 1.01))
        pos_usd = self._position_size_usd(optimal_entry, stop_price)
        quantity = pos_usd / optimal_entry if optimal_entry > 0 else 0.0

        if quantity <= 0:
            payload["executed"] = False
            payload["reason"] = "Cantidad calculada inválida."
            if self.logger:
                self.logger.event("LIVE_SKIP", payload)
            return payload

        order = self.client.create_smart_futures_order(
            symbol=symbol,
            side=side,
            quantity=quantity,
            position_side=position_side,
            offset_percent=0.1,
        )
        payload["executed"] = True
        payload["order"] = order
        payload["execution_plan"] = {
            "side": side,
            "position_side": position_side,
            "entry": optimal_entry,
            "stop": stop_price,
            "position_usd": pos_usd,
            "quantity": quantity,
        }
        if self.logger:
            self.logger.event("LIVE_EXECUTE", payload)
        return payload

