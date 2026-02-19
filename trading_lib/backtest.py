from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from .fees import FeeModel
from .models import Candle, TradeSignal
from .strategies.base import Strategy
from .trade_logger import TradingLogger
from .zones import ZoneClassifier


@dataclass
class BacktestTrade:
    entry_price: float
    exit_price: float
    side: str
    pnl_percent: float
    net_pnl_percent: float


@dataclass
class BacktestResult:
    symbol: str
    trades: int
    win_rate: float
    gross_return_percent: float
    net_return_percent: float
    max_drawdown_percent: float
    trade_log: List[BacktestTrade]


class Backtester:
    """Backtester simple con una posicion a la vez y fees de round trip."""

    def __init__(self, strategy: Strategy, fee_model: FeeModel, logger: TradingLogger | None = None) -> None:
        self.strategy = strategy
        self.fee_model = fee_model
        self.classifier = ZoneClassifier()
        self.logger = logger

    def run(self, symbol: str, candles: List[Candle], warmup: int = 220) -> BacktestResult:
        if len(candles) <= warmup + 2:
            raise ValueError("No hay suficientes velas para backtest.")

        in_position = False
        side = ""
        entry_price = 0.0
        equity = 1.0
        peak = 1.0
        max_dd = 0.0
        logs: List[BacktestTrade] = []

        for i in range(warmup, len(candles)):
            window = candles[: i + 1]
            features = self.classifier.build_features(window)
            decision = self.strategy.generate(features, self.fee_model)
            current = candles[i].close

            if not in_position and decision.signal in (TradeSignal.BUY, TradeSignal.SELL):
                in_position = True
                side = "LONG" if decision.signal == TradeSignal.BUY else "SHORT"
                entry_price = current
                if self.logger:
                    self.logger.event(
                        "BACKTEST_ENTRY",
                        {
                            "symbol": symbol,
                            "index": i,
                            "side": side,
                            "entry_price": entry_price,
                            "decision_reason": decision.reason,
                            "confidence": decision.confidence,
                        },
                    )
                continue

            if in_position:
                should_exit = False
                if side == "LONG" and decision.signal == TradeSignal.SELL:
                    should_exit = True
                elif side == "SHORT" and decision.signal == TradeSignal.BUY:
                    should_exit = True

                if should_exit:
                    if side == "LONG":
                        gross = ((current - entry_price) / entry_price) * 100
                    else:
                        gross = ((entry_price - current) / entry_price) * 100

                    net = gross - self.fee_model.round_trip_fee_percent("futures", is_maker=True)
                    equity *= 1 + (net / 100.0)
                    peak = max(peak, equity)
                    dd = ((peak - equity) / peak) * 100
                    max_dd = max(max_dd, dd)

                    logs.append(
                        BacktestTrade(
                            entry_price=entry_price,
                            exit_price=current,
                            side=side,
                            pnl_percent=gross,
                            net_pnl_percent=net,
                        )
                    )
                    if self.logger:
                        self.logger.event(
                            "BACKTEST_EXIT",
                            {
                                "symbol": symbol,
                                "index": i,
                                "side": side,
                                "entry_price": entry_price,
                                "exit_price": current,
                                "gross_pnl_percent": gross,
                                "net_pnl_percent": net,
                                "drawdown_percent": dd,
                            },
                        )
                    in_position = False

        wins = len([t for t in logs if t.net_pnl_percent > 0])
        trades = len(logs)
        win_rate = (wins / trades) * 100 if trades else 0.0
        gross_return = sum(t.pnl_percent for t in logs)
        net_return = sum(t.net_pnl_percent for t in logs)

        result = BacktestResult(
            symbol=symbol,
            trades=trades,
            win_rate=win_rate,
            gross_return_percent=gross_return,
            net_return_percent=net_return,
            max_drawdown_percent=max_dd,
            trade_log=logs,
        )
        if self.logger:
            self.logger.event("BACKTEST_SUMMARY", {"symbol": symbol, "result": result})
        return result

