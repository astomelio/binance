#!/usr/bin/env python3
"""
Motor de alertas para mercado bajista/mixto usando la API local.

Objetivo:
- Detectar zonas de compra en caidas con reglas claras.
- Evitar entradas que no superen fees + margen objetivo.
- Emitir alertas accionables con entrada, stop y take profit sugeridos.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from statistics import mean
from typing import Dict, List, Optional, Tuple

import requests

from apps.automation.fee_calculator import FeeCalculator


@dataclass
class AlertSignal:
    symbol: str
    regime: str
    signal: str
    confidence: float
    entry_price: float
    stop_price: float
    take_profit_price: float
    expected_move_percent: float
    break_even_percent: float
    net_edge_percent: float
    reason: str
    timestamp: str


class MarketAlertEngine:
    """Motor de alertas con logica de tendencia + validacion de fees."""

    def __init__(self, api_url: str = "http://localhost:8000", capital_usd: float = 500.0) -> None:
        self.api_url = api_url.rstrip("/")
        self.capital_usd = capital_usd
        self.fee_calc = FeeCalculator(self.api_url)

    # ---------------------------
    # API helpers
    # ---------------------------
    def _get_json(self, endpoint: str, params: Optional[Dict] = None) -> Dict:
        resp = requests.get(f"{self.api_url}{endpoint}", params=params, timeout=20)
        resp.raise_for_status()
        return resp.json()

    def get_klines(self, symbol: str, interval: str = "1h", limit: int = 300) -> List[Dict]:
        data = self._get_json(f"/market/klines/{symbol}", {"interval": interval, "limit": limit})
        if data.get("status") != "success":
            raise ValueError(f"Error en klines para {symbol}: {data}")
        return data["data"]

    def get_optimal_entry(self, symbol: str, side: str = "BUY") -> float:
        data = self._get_json(
            f"/order/optimal-price/{symbol}",
            {"side": side, "price_offset_percent": 0.1},
        )
        if data.get("status") != "success":
            raise ValueError(f"Error en optimal-price para {symbol}: {data}")
        return float(data["data"]["suggested_limit_price"])

    # ---------------------------
    # Indicadores
    # ---------------------------
    @staticmethod
    def _sma(values: List[float], period: int) -> float:
        if len(values) < period:
            return float("nan")
        return mean(values[-period:])

    @staticmethod
    def _rsi(values: List[float], period: int = 14) -> float:
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

    @staticmethod
    def _atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
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

    # ---------------------------
    # Logica de mercado
    # ---------------------------
    def classify_regime(self, closes: List[float]) -> str:
        sma50 = self._sma(closes, 50)
        sma200 = self._sma(closes, 200)
        last = closes[-1]

        if math.isnan(sma200):
            return "UNDEFINED"
        if last < sma50 < sma200:
            return "BEARISH"
        if last > sma50 > sma200:
            return "BULLISH"
        return "SIDEWAYS"

    def build_signal(self, symbol: str, interval: str = "1h") -> Optional[AlertSignal]:
        klines = self.get_klines(symbol, interval=interval, limit=300)
        closes = [float(k["close"]) for k in klines]
        highs = [float(k["high"]) for k in klines]
        lows = [float(k["low"]) for k in klines]
        volumes = [float(k["volume"]) for k in klines]

        last = closes[-1]
        rsi = self._rsi(closes, 14)
        sma20 = self._sma(closes, 20)
        sma50 = self._sma(closes, 50)
        sma200 = self._sma(closes, 200)
        atr = self._atr(highs, lows, closes, 14)
        vol_ratio = volumes[-1] / max(mean(volumes[-20:]), 1e-9)

        regime = self.classify_regime(closes)
        entry = self.get_optimal_entry(symbol, "BUY")

        # Riesgo: stop 1.8 ATR por debajo, TP 2.8 ATR por encima (RR > 1.5)
        stop = max(entry - (1.8 * atr), entry * 0.94)
        take_profit = entry + (2.8 * atr)

        expected_move_pct = ((take_profit - entry) / entry) * 100
        break_even_pct = self.fee_calc.calculate_round_trip_fees(100.0, True, "spot")["break_even_percent"]
        net_edge_pct = expected_move_pct - break_even_pct

        confidence = 0.0
        reason = []
        signal_type = "NO_TRADE"

        # 1) Mercado bajista: comprar solo sobreventa extrema + recuperacion de momentum
        if regime == "BEARISH":
            if rsi < 30 and last < sma20 and vol_ratio > 1.15:
                confidence = 0.70
                signal_type = "ACCUMULATE_STEP"
                reason.append("Regimen bajista con sobreventa (RSI<30) y volumen creciente")
            elif rsi < 25:
                confidence = 0.62
                signal_type = "ACCUMULATE_SMALL"
                reason.append("Sobreventa profunda en bajista (RSI<25), entrada parcial")

        # 2) Lateral: buy dip cerca de soporte dinámico
        elif regime == "SIDEWAYS":
            if rsi < 38 and last < sma20:
                confidence = 0.66
                signal_type = "BUY_DIP"
                reason.append("Rango lateral con retroceso hacia zona de valor")

        # 3) Alcista: pullback controlado
        elif regime == "BULLISH":
            if rsi < 45 and last > sma50:
                confidence = 0.72
                signal_type = "TREND_PULLBACK_BUY"
                reason.append("Tendencia alcista con pullback saludable")

        # filtro de edge real (fees incluidas)
        if signal_type != "NO_TRADE":
            if net_edge_pct < 0.50:
                return None
            if sma200 and not math.isnan(sma200):
                reason.append(f"Precio={last:.2f}, RSI={rsi:.1f}, net_edge={net_edge_pct:.2f}%")
            return AlertSignal(
                symbol=symbol,
                regime=regime,
                signal=signal_type,
                confidence=round(confidence, 2),
                entry_price=round(entry, 6),
                stop_price=round(stop, 6),
                take_profit_price=round(take_profit, 6),
                expected_move_percent=round(expected_move_pct, 3),
                break_even_percent=round(break_even_pct, 3),
                net_edge_percent=round(net_edge_pct, 3),
                reason=" | ".join(reason),
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
        return None

    # ---------------------------
    # Alerting / execution
    # ---------------------------
    def suggest_position_size_usd(self, signal: AlertSignal, risk_per_trade: float = 0.01) -> float:
        """
        Tamaño por riesgo:
        - capital * risk_per_trade = riesgo $ máximo
        - riesgo por unidad = entry-stop
        """
        max_risk_usd = self.capital_usd * risk_per_trade
        risk_per_unit = max(signal.entry_price - signal.stop_price, signal.entry_price * 0.01)
        units = max_risk_usd / risk_per_unit
        position_usd = units * signal.entry_price
        # limite: max 20% del capital en una sola entrada
        return min(position_usd, self.capital_usd * 0.20)

    def send_webhook(self, signal: AlertSignal, webhook_url: str) -> None:
        payload = {"text": json.dumps(asdict(signal), ensure_ascii=False)}
        requests.post(webhook_url, json=payload, timeout=10)

    def scan(self, symbols: List[str], interval: str = "1h") -> List[AlertSignal]:
        alerts: List[AlertSignal] = []
        for symbol in symbols:
            try:
                signal = self.build_signal(symbol, interval=interval)
                if signal:
                    alerts.append(signal)
            except Exception as exc:  # noqa: BLE001
                print(f"[WARN] {symbol}: {exc}")
        return alerts


def main() -> None:
    """
    Ejemplo:
    python market_alert_engine.py --once
    """
    import argparse

    parser = argparse.ArgumentParser(description="Motor de alertas cuantitativo")
    parser.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT", "BNBUSDT"])
    parser.add_argument("--interval", default="1h")
    parser.add_argument("--capital", type=float, default=500.0)
    parser.add_argument("--loop-seconds", type=int, default=900, help="15m por defecto")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--webhook-url", default="")
    args = parser.parse_args()

    engine = MarketAlertEngine(capital_usd=args.capital)

    def run_once() -> None:
        alerts = engine.scan(args.symbols, interval=args.interval)
        if not alerts:
            print(f"[{datetime.now().isoformat()}] Sin alertas accionables.")
            return

        print(f"[{datetime.now().isoformat()}] Alertas detectadas: {len(alerts)}")
        for a in alerts:
            pos_usd = engine.suggest_position_size_usd(a, risk_per_trade=0.01)
            out = asdict(a)
            out["suggested_position_usd"] = round(pos_usd, 2)
            print(json.dumps(out, ensure_ascii=False, indent=2))
            if args.webhook_url:
                try:
                    engine.send_webhook(a, args.webhook_url)
                except Exception as exc:  # noqa: BLE001
                    print(f"[WARN] webhook fallo: {exc}")

    if args.once:
        run_once()
        return

    while True:
        run_once()
        time.sleep(max(args.loop_seconds, 30))


if __name__ == "__main__":
    main()

