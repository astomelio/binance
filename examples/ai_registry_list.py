#!/usr/bin/env python3
"""Listar corridas del registry: train y backtest con métricas."""
import argparse
from ai.registry import list_runs


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--type", choices=["train", "backtest"], help="Filtrar por tipo")
    args = p.parse_args()

    runs = list_runs(limit=args.limit, run_type=args.type)
    for r in runs:
        m = r.metrics
        sharpe = m.get("sharpe_like", m.get("objective", "-"))
        ret = m.get("net_return_percent", m.get("total_return_percent", m.get("net_return", "-")))
        trades = m.get("trades", m.get("trades_count", "-"))
        wr = m.get("win_rate", "-")
        print(f"{r.run_id} | {r.created_at[:19]} | {r.run_type} | algo={r.algo_version} data={r.data_version}")
        print(f"  Sharpe: {sharpe} | Ret: {ret} | Trades: {trades} | WinRate: {wr}")


if __name__ == "__main__":
    main()
