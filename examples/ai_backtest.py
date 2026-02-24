#!/usr/bin/env python3
"""
Backtest con vectores de asignación. Lee de DuckDB.
allocation[symbol] = 0 (nada), 0.2 (20% long), -0.2 (20% short).
Operaciones solo en cada event_time. Ver docs/AI_BACKTEST_PARAMS.md
"""
import argparse
from ai.backtest.runner import run_backtest


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--horizon", default="4h")
    p.add_argument("--symbols", nargs="*", help="Filtrar símbolos (default: todos)")
    p.add_argument("--prob-threshold", type=float, default=0.55, help="Umbral para LONG/SHORT")
    p.add_argument("--fee-percent", type=float, default=0.04)
    p.add_argument("--slippage-percent", type=float, default=0.0, help="Slippage por cambio de posición, ej. 0.02 = 0.02%%")
    p.add_argument("--min-quote-volume-24h", type=float, default=None, help="Excluir símbolos con volumen 24h (USD) menor, ej. 1e6 = 1M USD")
    args = p.parse_args()

    result = run_backtest(
        horizon=args.horizon,
        symbols=args.symbols or None,
        fee_percent=args.fee_percent,
        slippage_percent=args.slippage_percent,
        min_quote_volume_24h=args.min_quote_volume_24h,
        prob_threshold=args.prob_threshold,
    )
    print(f"Trades: {result.trades_count}")
    print(f"Return: {result.total_return_percent:.3f}% | Net: {result.net_return_percent:.3f}% | Fees: {result.total_fees_percent:.3f}% | Slippage: {result.total_slippage_percent:.3f}%")
    print(f"By symbol: {result.by_symbol}")


if __name__ == "__main__":
    main()
