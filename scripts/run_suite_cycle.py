#!/usr/bin/env python3
"""
Ejecuta un ciclo de la suite de agentes quant: tuning → decisión → informe → evolución.
Carga datos de DuckDB, corre la suite y persiste estado e informe.

Modos:
- Sin --optimize: explora estrategias con params por defecto (rápido).
- Con --optimize: optimiza sobre estrategias × params × horizontes × activos (top20/top50/all)
  y opcionalmente sesión (horas UTC). Usa todo el dataset si --lookback-days 0.

Uso:
  python scripts/run_suite_cycle.py
  python scripts/run_suite_cycle.py --use-champion   # rellena alpha_score con MLflow champion antes de evaluar
  python scripts/run_suite_cycle.py --optimize --use-champion --strict-alpha
  python scripts/run_suite_cycle.py --optimize --session 8 16
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("DBT_DUCKDB_PATH", str(REPO_ROOT / "artifacts" / "warehouse" / "crypto.duckdb"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one cycle of the quant agent suite")
    parser.add_argument("--horizon", default="4h", choices=("1h", "4h", "24h"))
    parser.add_argument("--lookback-days", type=int, default=90, help="Días de datos (0 = todo el dataset)")
    parser.add_argument("--optimize", action="store_true", help="Optimizar: estrategias × params × horizontes × activos × sesión")
    parser.add_argument("--session", type=int, nargs=2, metavar=("START_H", "END_H"), default=None, help="Solo barras en [START_H, END_H] UTC (ej. 8 16)")
    parser.add_argument("--max-trials", type=int, default=400, help="Máx backtests en modo optimize (default 400)")
    parser.add_argument("--use-champion", action="store_true", help="Cargar champion de MLflow y rellenar alpha_score antes de evaluar (evita optimizar columna vacía)")
    parser.add_argument("--mlflow-uri", default=None, help="MLflow tracking URI (default: sqlite en artifacts/quant_model/mlflow.db)")
    parser.add_argument("--model-uri", default="models:/quant_alpha_entry_lgbm@champion", help="Model URI para --use-champion")
    parser.add_argument("--strict-alpha", action="store_true", help="Fallar si alpha_score está vacío en demasiadas filas (cuando se usa estrategia alpha)")
    parser.add_argument("--db", default=None, help="DuckDB path")
    parser.add_argument("--state", default=None, help="suite_state.json path")
    parser.add_argument("--no-persist", action="store_true", help="Do not save state")
    parser.add_argument("--no-report", action="store_true", help="Do not write report file")
    args = parser.parse_args()

    db_path = args.db or os.environ.get("DBT_DUCKDB_PATH", str(REPO_ROOT / "artifacts" / "warehouse" / "crypto.duckdb"))
    if not Path(db_path).exists():
        print(f"DuckDB no encontrado: {db_path}", file=sys.stderr)
        return 1

    from datetime import datetime, timedelta, timezone
    from ai.data.loader import load_decision_features
    from ai.suite import (
        QuantAgentSuite,
        ExplorationTuningAgent,
        OptimizerTuningAgent,
        BacktestDecisionAgent,
        DefaultReportAgent,
        DefaultEvolutionAgent,
    )

    end_dt = datetime.now(timezone.utc)
    if args.lookback_days <= 0:
        start_str = end_str = None
    else:
        start_dt = end_dt - timedelta(days=args.lookback_days)
        start_str = start_dt.strftime("%Y-%m-%d")
        end_str = end_dt.strftime("%Y-%m-%d")
    rows = load_decision_features(
        db_path=db_path,
        horizon=args.horizon,
        label_not_null=True,
        start=start_str,
        end=end_str,
    )
    if not rows or len(rows) < 200:
        print(f"Datos insuficientes: {len(rows)} filas.", file=sys.stderr)
        return 1

    # Conectar modelo ML con suite: rellenar alpha_score con el champion antes de evaluar
    if args.use_champion:
        try:
            mlflow_uri = args.mlflow_uri or f"sqlite:///{REPO_ROOT / 'artifacts' / 'quant_model' / 'mlflow.db'}"
            from ai.inference.champion_loader import enrich_rows_with_champion
            rows = enrich_rows_with_champion(
                rows,
                model_uri=args.model_uri,
                mlflow_tracking_uri=mlflow_uri,
            )
            print("alpha_score rellenado con champion de MLflow.", file=sys.stderr)
        except Exception as e:
            print(f"No se pudo cargar champion: {e}. Usa --use-champion solo si tienes modelo registrado.", file=sys.stderr)
            return 1
    else:
        from ai.allocation.checks import warn_alpha_score_if_low, check_alpha_score_coverage
        warn_alpha_score_if_low(rows, min_fraction_non_zero=0.02)
        if args.strict_alpha:
            check_alpha_score_coverage(rows, raise_on_fail=True)

    if args.optimize:
        session_hours = tuple(args.session) if args.session else None
        tuning_agent = OptimizerTuningAgent(
            horizons=["1h", "4h"],
            symbol_sets=["top20", "top50", "all"],
            session_hours=session_hours,
            max_total_trials=args.max_trials,
            max_candidates=15,
            fee_percent=0.04,
        )
    else:
        tuning_agent = ExplorationTuningAgent(
            horizon=args.horizon,
            fee_percent=0.04,
            max_candidates=10,
        )

    suite = QuantAgentSuite(
        tuning_agent=tuning_agent,
        decision_agent=BacktestDecisionAgent(horizon=args.horizon, fee_percent=0.04, db_path=db_path),
        report_agent=DefaultReportAgent(promote_min_net_return=0.0, promote_min_trades=1),
        evolution_agent=DefaultEvolutionAgent(),
        state_path=args.state or str(REPO_ROOT / "artifacts" / "quant_model" / "suite_state.json"),
        report_dir=str(REPO_ROOT / "artifacts" / "quant_model"),
    )

    state, report, decision = suite.run_cycle(
        rows,
        persist_state=not args.no_persist,
        save_report=not args.no_report,
    )

    print("Recommendation:", report.recommendation)
    print("Reason:", report.recommendation_reason)
    print("Champion:", state.champion_id, "version", state.version)
    print("Champion backtest:", decision.champion_backtest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
