#!/usr/bin/env python3
"""
CLI para el agente de exploración.
Uso programático: from ai.explorer import ExplorationAgent; agent.run_quick()
"""
from __future__ import annotations

import argparse
import os

from ai.explorer import ExplorationAgent


def main():
    p = argparse.ArgumentParser(description="Explorador de estrategias (agente)")
    p.add_argument("mode", choices=["quick", "grid", "full"], help="quick=defaults, grid=una estrategia, full=exploración completa")
    p.add_argument("--strategy", default="mean_reversion", help="Para grid: strategy_id")
    p.add_argument("--horizon", default="4h", choices=["1h", "4h", "24h"])
    p.add_argument("--fee-percent", type=float, default=0.04)
    p.add_argument("--max-combos", type=int, default=30, help="Grid: max combinaciones")
    p.add_argument("--symbols", nargs="*", help="Filtrar símbolos")
    args = p.parse_args()

    db_path = os.environ.get("DBT_DUCKDB_PATH") or "artifacts/warehouse/crypto.duckdb"
    agent = ExplorationAgent(
        horizon=args.horizon,
        fee_percent=args.fee_percent,
        symbols=args.symbols or None,
        db_path=db_path,
    )

    if args.mode == "quick":
        report = agent.run_quick()
    elif args.mode == "grid":
        report = agent.run_grid(args.strategy, max_combos=args.max_combos)
    else:
        report = agent.run_full(max_experiments_per_strategy=args.max_combos)

    if not report.results:
        print("❌ Sin resultados. ¿make warehouse-load?")
        return 1

    print(f"📊 Datos: {report.data_summary.get('rows', 0)} filas | {report.data_summary.get('symbols', 0)} símbolos")
    print()
    print("Resultados (ordenados por net return):")
    for r in sorted(report.results, key=lambda x: -x.net_return_percent)[:15]:
        print(f"  {r.strategy_id:15} | {str(r.params)[:50]:50} | net={r.net_return_percent:+.2f}% trades={r.trades_count}")
    if report.best_overall:
        print()
        print(f"✅ Mejor: {report.best_overall.strategy_id} {report.best_overall.params} -> net={report.best_overall.net_return_percent:+.2f}%")
    return 0


if __name__ == "__main__":
    exit(main())
