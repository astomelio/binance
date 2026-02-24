#!/usr/bin/env python3
"""Ejecuta una prueba concreta: mismo periodo, backtest con alpha rule-based (sin MLflow).
Si backtest y paper dan números del mismo orden, el motor del backtest es creíble."""
from __future__ import annotations

import json
import os
from pathlib import Path

def main() -> int:
    paper_path = Path("artifacts/quant_model/paper_scenarios.jsonl")
    if not paper_path.exists():
        print("FALTA: paper_scenarios.jsonl")
        return 1

    scenarios = [json.loads(l) for l in paper_path.read_text().strip().splitlines() if l.strip()]
    if not scenarios:
        print("paper_scenarios.jsonl vacío")
        return 1

    min_ts = min(s["entry_time"] for s in scenarios)
    max_ts = max(s["exit_time"] for s in scenarios)
    start_str = min_ts.replace("Z", "").replace("+00:00", "").strip()
    end_str = max_ts.replace("Z", "").replace("+00:00", "").strip()

    total_notional = sum(s["notional_usd"] for s in scenarios)
    paper_return = sum(s["pnl_pct"] * s["notional_usd"] for s in scenarios) / total_notional if total_notional else 0.0

    db_path = os.environ.get("DBT_DUCKDB_PATH", "artifacts/warehouse/crypto.duckdb")
    if not Path(db_path).exists():
        print("FALTA: DuckDB en", db_path)
        return 1

    from ai.data.loader import load_decision_features
    from ai.allocation.backtest import run_allocation_backtest
    from ai.allocation.strategies import compute_allocations

    rows = load_decision_features(horizon="1h", label_not_null=True, db_path=db_path, start=start_str, end=end_str)
    if not rows:
        print("No hay filas en decision_features para el periodo del paper.")
        return 1

    # Señal de prueba: alternar long/short; asegurar fed_window=NORMAL para que no se bloqueen trades
    by_ts: dict = {}
    for r in rows:
        r["fed_window"] = "NORMAL"
        by_ts.setdefault(r["event_time"], []).append(r)
    for ts, grp in sorted(by_ts.items()):
        for i, r in enumerate(grp):
            r["alpha_score"] = 0.35 if i % 2 == 0 else -0.35

    result = run_allocation_backtest(
        rows, horizon="1h", fee_percent=0.04, slippage_percent=0.02,
        compute_fn=lambda f, _: compute_allocations(f, prob_threshold=0.55, min_allocation=0.1, max_allocation=0.4, max_exposure=1.0),
    )

    print("--- RESULTADO (por qué puedes confiar) ---")
    print("Periodo:", min_ts, "->", max_ts)
    print("Paper  retorno realizado %:", f"{paper_return:+.3f}%", "| trades:", len(scenarios))
    print("Backtest retorno neto    %:", f"{result.net_return_percent:+.3f}%", "| trades:", result.trades_count)
    print("Diferencia (backtest - paper):", f"{result.net_return_percent - paper_return:+.3f}%")
    if result.trades_count > 0:
        print("-> El motor del backtest responde: con señales hay trades y retorno neto. Para confiar en tu estrategia real: usa el mismo modelo que el paper y compara con run_backtest_vs_paper.py --model-uri <tu_modelo>.")
    else:
        print("-> Backtest 0 trades (señales bloqueadas o sin modelo). Con modelo local: run_backtest_vs_paper.py --model-uri models:/quant_alpha_entry_lgbm@champion")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
