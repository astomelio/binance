#!/usr/bin/env python3
"""
Bucle de investigación: corre ciclos de la suite hasta encontrar algo bueno
o detectar estancamiento; entonces amplía la búsqueda (más trials, otras estrategias, sesiones, etc.).

Uso:
  python scripts/run_suite_research.py
  python scripts/run_suite_research.py --max-cycles 20 --cycles-before-explore 3
  python scripts/run_suite_research.py --stop-on-promote   # para al primer promote
  python scripts/run_suite_research.py --optimize --use-champion
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


def _make_exploration_tuning_agent(round_index: int, base_trials: int, session_hours=None):
    """Crea un OptimizerTuningAgent más agresivo según la ronda de exploración."""
    from ai.suite.agents import OptimizerTuningAgent

    # Cada ronda amplía: más trials, más horizontes, o sesión distinta
    if round_index == 0:
        return OptimizerTuningAgent(
            horizons=["1h", "4h"],
            symbol_sets=["top20", "top50", "all"],
            session_hours=session_hours,
            max_combos_per_strategy=60,
            max_total_trials=min(base_trials * 2, 800),
            max_candidates=20,
            fee_percent=0.04,
        )
    if round_index == 1:
        return OptimizerTuningAgent(
            horizons=["1h", "4h", "24h"],
            symbol_sets=["top20", "top50", "all"],
            session_hours=session_hours or (8, 16),
            max_combos_per_strategy=80,
            max_total_trials=min(base_trials * 2, 900),
            max_candidates=20,
            fee_percent=0.04,
        )
    # Rondas siguientes: aún más trials y más estrategias
    return OptimizerTuningAgent(
        horizons=["1h", "4h", "24h"],
        symbol_sets=["top20", "top50", "all"],
        session_hours=session_hours,
        max_combos_per_strategy=100,
        max_total_trials=min(base_trials * 3, 1200),
        max_candidates=25,
        fee_percent=0.04,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run research loop: cycles until good result or no progress, then explore"
    )
    parser.add_argument("--horizon", default="4h", choices=("1h", "4h", "24h"))
    parser.add_argument("--lookback-days", type=int, default=90, help="Días de datos (0 = todo el dataset)")
    parser.add_argument("--max-cycles", type=int, default=30, help="Máximo de ciclos antes de parar")
    parser.add_argument("--cycles-before-explore", type=int, default=3, help="Ciclos sin mejora para activar exploración")
    parser.add_argument("--stop-on-promote", action="store_true", help="Parar al primer promote (si no, sigue buscando)")
    parser.add_argument("--optimize", action="store_true", help="Usar OptimizerTuningAgent (estrategias × params × activos)")
    parser.add_argument("--max-trials", type=int, default=400, help="Trials por ciclo en modo optimize")
    parser.add_argument("--session", type=int, nargs=2, metavar=("START_H", "END_H"), default=None)
    parser.add_argument("--use-champion", action="store_true", help="Rellenar alpha_score con champion MLflow")
    parser.add_argument("--mlflow-uri", default=None)
    parser.add_argument("--model-uri", default="models:/quant_alpha_entry_lgbm@champion")
    parser.add_argument("--db", default=None)
    parser.add_argument("--state", default=None)
    parser.add_argument("--research-state", default=None, help="Path research_state.json")
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
        run_research_loop,
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

    if args.use_champion:
        try:
            mlflow_uri = args.mlflow_uri or f"sqlite:///{REPO_ROOT / 'artifacts' / 'quant_model' / 'mlflow.db'}"
            from ai.inference.champion_loader import enrich_rows_with_champion
            rows = enrich_rows_with_champion(rows, model_uri=args.model_uri, mlflow_tracking_uri=mlflow_uri)
            print("alpha_score rellenado con champion.", file=sys.stderr)
        except Exception as e:
            print(f"No se pudo cargar champion: {e}", file=sys.stderr)
            return 1
    else:
        from ai.allocation.checks import warn_alpha_score_if_low
        warn_alpha_score_if_low(rows, min_fraction_non_zero=0.02)

    session_hours = tuple(args.session) if args.session else None
    if args.optimize:
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

    def on_explore(suite_ref, state, report, research_state):
        if not args.optimize:
            return
        r = research_state.exploration_round
        new_agent = _make_exploration_tuning_agent(r, args.max_trials, session_hours)
        suite_ref.tuning_agent = new_agent
        print(f"[explore] Ronda {r}: ampliando búsqueda (trials ~{new_agent.max_total_trials})", file=sys.stderr)

    state, report, research_state, cycles = run_research_loop(
        suite,
        rows,
        max_cycles=args.max_cycles,
        cycles_before_explore=args.cycles_before_explore,
        stop_on_promote=args.stop_on_promote,
        on_explore=on_explore if args.optimize else None,
        state_path=args.state or str(REPO_ROOT / "artifacts" / "quant_model" / "suite_state.json"),
        research_state_path=args.research_state or str(REPO_ROOT / "artifacts" / "quant_model" / "research_state.json"),
    )

    print("--- Resultado del bucle ---")
    print("Ciclos ejecutados:", cycles)
    print("Recommendation:", report.recommendation)
    print("Reason:", report.recommendation_reason)
    print("Champion:", state.champion_id, "version", state.version)
    print("Research: mode=%s, cycles_without_improvement=%s, exploration_round=%s" % (
        research_state.mode, research_state.cycles_without_improvement, research_state.exploration_round,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
