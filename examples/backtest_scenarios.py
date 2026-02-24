#!/usr/bin/env python3
"""
Genera escenarios del backtest (por event_time y símbolo: asignación, fwd_return, retorno del periodo).
Salida: JSONL con event_time, symbol, allocation, fwd_return_4h, period_return_pct.
Así puedes comparar con los escenarios de paper (compare_backtest_vs_paper.py --scenarios --backtest-scenarios).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Genera backtest_scenarios.jsonl para comparar con paper")
    parser.add_argument(
        "--horizon",
        default="4h",
        choices=("1h", "4h", "24h"),
        help="Horizonte de retorno",
    )
    parser.add_argument(
        "--out",
        default="artifacts/quant_model/backtest_scenarios.jsonl",
        help="Archivo de salida JSONL",
    )
    parser.add_argument(
        "--db-path",
        default=None,
        help="Ruta a crypto.duckdb (por defecto DBT_DUCKDB_PATH o artifacts/warehouse/crypto.duckdb)",
    )
    args = parser.parse_args()

    import os
    db_path = args.db_path or os.environ.get("DBT_DUCKDB_PATH", "artifacts/warehouse/crypto.duckdb")
    if not Path(db_path).exists():
        print(f"No existe DuckDB: {db_path}")
        print("Ejecuta antes: make warehouse-load")
        return 1

    from ai.data.loader import load_decision_features
    from ai.allocation.backtest import run_allocation_backtest
    from ai.allocation.strategies import compute_allocations

    rows = load_decision_features(horizon=args.horizon, label_not_null=True, db_path=db_path)
    if not rows:
        print("No hay filas en decision_features. Ejecuta make warehouse-load y dbt.")
        return 1

    result = run_allocation_backtest(
        rows,
        horizon=args.horizon,
        fee_percent=0.04,
        compute_fn=lambda f, _: compute_allocations(f, prob_threshold=0.55, min_allocation=0.1, max_allocation=0.4, max_exposure=1.0),
    )

    label_col = {"1h": "fwd_return_1h", "4h": "fwd_return_4h", "24h": "fwd_return_24h"}[args.horizon]
    by_time: dict[str, dict[str, dict]] = {}
    for r in rows:
        ts = r.get("event_time", "")
        sym = r.get("symbol", "")
        if ts and sym:
            by_time.setdefault(ts, {})[sym] = r

    scenarios = []
    for ts, alloc in result.alloc_history:
        feats = by_time.get(ts, {})
        for sym, a in alloc.items():
            if abs(a) < 1e-9:
                continue
            r = feats.get(sym, {})
            fwd = r.get(label_col)
            if fwd is None:
                continue
            fwd_val = float(fwd)
            period_pct = a * (fwd_val / 100.0) * 100.0  # period return in %
            scenarios.append({
                "event_time": ts,
                "symbol": sym,
                "allocation": round(a, 6),
                "fwd_return_4h": round(fwd_val, 6),
                "period_return_pct": round(period_pct, 4),
            })

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for s in scenarios:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")

    print(f"Backtest net: {result.net_return_percent:+.3f}% | Trades: {result.trades_count}")
    print(f"Escenarios escritos: {out_path} ({len(scenarios)} periodos con asignación)")
    print("Comparar con: python examples/compare_backtest_vs_paper.py --scenarios --backtest-scenarios", out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
