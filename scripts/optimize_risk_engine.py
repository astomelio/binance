#!/usr/bin/env python3
"""
Optimiza RiskEngine: max_open_trades, max_position_size_pct, etc.
Ejecuta backtests con distintas combinaciones y guarda los mejores params en auto_report.json.
Uso: python scripts/optimize_risk_engine.py [--db PATH] [--out-report PATH]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Grid de params a explorar
RISK_PARAM_GRID = {
    "max_open_trades": [4, 5, 6, 7, 8],
    "max_position_size_pct": [0.10, 0.15, 0.20, 0.25],
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Optimiza RiskEngine params vía backtest")
    parser.add_argument("--db", default=None, help="DuckDB path")
    parser.add_argument("--out-report", default="artifacts/quant_model/auto_report.json")
    parser.add_argument("--horizon", default="4h", choices=("1h", "4h", "24h"))
    parser.add_argument("--max-trials", type=int, default=20, help="Máx combinaciones a probar")
    args = parser.parse_args()

    db_path = args.db or os.environ.get("DBT_DUCKDB_PATH", str(REPO_ROOT / "artifacts" / "warehouse" / "crypto.duckdb"))

    from ai.data.loader import load_decision_features
    from ai.backtest.runner import run_backtest
    import itertools
    import random

    rows = load_decision_features(
        horizon=args.horizon,
        label_not_null=True,
        db_path=db_path,
    )
    if not rows or len(rows) < 500:
        print(f"Insufficient data: {len(rows) if rows else 0} rows", file=sys.stderr)
        return 1

    keys = list(RISK_PARAM_GRID.keys())
    values = [RISK_PARAM_GRID[k] for k in keys]
    combos = [dict(zip(keys, c)) for c in itertools.product(*values)]
    if len(combos) > args.max_trials:
        combos = random.sample(combos, args.max_trials)

    best = None
    best_fitness = -1e9
    results = []

    for i, rp in enumerate(combos):
        try:
            res = run_backtest(
                horizon=args.horizon,
                fee_percent=0.04,
                slippage_percent=0.0,
                prob_threshold=0.55,
                use_risk_engine=True,
                risk_engine_params=rp,
            )
            fitness = res.net_return_percent - 0.3 * res.max_drawdown_percent
            results.append({
                "params": rp,
                "net_return_percent": res.net_return_percent,
                "max_drawdown_percent": res.max_drawdown_percent,
                "trades_count": res.trades_count,
                "sharpe_ratio": res.sharpe_ratio,
                "fitness": fitness,
            })
            if fitness > best_fitness:
                best_fitness = fitness
                best = rp
                print(f"  [{i+1}/{len(combos)}] {rp} -> net={res.net_return_percent:.2f}% MDD={res.max_drawdown_percent:.1f}% fit={fitness:.2f} *", file=sys.stderr)
            else:
                print(f"  [{i+1}/{len(combos)}] {rp} -> net={res.net_return_percent:.2f}% MDD={res.max_drawdown_percent:.1f}% fit={fitness:.2f}", file=sys.stderr)
        except Exception as e:
            print(f"  [{i+1}/{len(combos)}] {rp} -> ERROR: {e}", file=sys.stderr)

    if not best:
        print("No valid results.", file=sys.stderr)
        return 1

    out_path = REPO_ROOT / args.out_report
    out_path.parent.mkdir(parents=True, exist_ok=True)
    report = {}
    if out_path.exists():
        try:
            report = json.loads(out_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    report["risk_engine"] = {
        "max_open_trades": best["max_open_trades"],
        "max_position_size_pct": best["max_position_size_pct"],
        "max_drawdown_limit": 0.15,
        "volatility_target": 0.20,
        "optimization_trials": len(combos),
        "best_fitness": best_fitness,
    }
    out_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"\nBest risk_engine params: {best}", file=sys.stderr)
    print(f"Saved to {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
