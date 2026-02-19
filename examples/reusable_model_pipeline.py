#!/usr/bin/env python3
"""Ejemplo unificado: mismo modelo para backtest y live."""

from __future__ import annotations

import json

from trading_lib import BinanceConnectorClient, FeeModel
from trading_lib.backtest import Backtester
from trading_lib.live import FuturesLiveExecutor
from trading_lib.strategies import RegimeFuturesStrategy


def main() -> None:
    symbol = "BTCUSDT"
    client = BinanceConnectorClient("http://localhost:8000")
    fee_model = FeeModel()
    strategy = RegimeFuturesStrategy(min_net_edge_percent=0.40)

    # 1) Backtest con futures klines
    candles = client.get_futures_klines(symbol, interval="1h", limit=500)
    bt = Backtester(strategy, fee_model)
    result = bt.run(symbol, candles)
    print("=== BACKTEST ===")
    print(
        json.dumps(
            {
                "symbol": result.symbol,
                "trades": result.trades,
                "win_rate": round(result.win_rate, 2),
                "gross_return_percent": round(result.gross_return_percent, 2),
                "net_return_percent": round(result.net_return_percent, 2),
                "max_drawdown_percent": round(result.max_drawdown_percent, 2),
            },
            indent=2,
        )
    )

    # 2) Evaluación live (sin ejecutar orden)
    live = FuturesLiveExecutor(client, strategy, fee_model, capital_usd=500)
    preview = live.evaluate(symbol, interval="1h", limit=300)
    print("\n=== LIVE PREVIEW ===")
    print(json.dumps(preview["decision"], indent=2))

    # 3) Ejecutar en real (DESCOMENTAR solo cuando quieras operar)
    # execution = live.execute_if_actionable(symbol, interval="1h", limit=300)
    # print("\n=== LIVE EXECUTION ===")
    # print(json.dumps(execution, indent=2))


if __name__ == "__main__":
    main()

