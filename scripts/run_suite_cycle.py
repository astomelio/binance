#!/usr/bin/env python3
"""
Motor de investigacion quant: OptimizerTuningAgent + run_research_loop.
Escala la investigación automáticamente hasta encontrar estrategias rentables.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("DBT_DUCKDB_PATH", str(REPO_ROOT / "artifacts" / "warehouse" / "crypto.duckdb"))


def _scale_exploration(suite, state, report, research_state):
    """Callback para escalar la búsqueda cuando no hay mejoras."""
    rnd = research_state.exploration_round + 1
    # Escalamiento agresivo: más trials y más combinaciones por estrategia
    new_max_trials = min(800 + rnd * 800, 4000)
    new_max_combos = min(150 + rnd * 150, 800)
    
    print(f"\n[RESEARCH SCALE] Ciclos sin mejora: {research_state.cycles_without_improvement}", file=sys.stderr)
    print(f"[RESEARCH SCALE] Iniciando Ronda {rnd}: trials={new_max_trials}, combos/strat={new_max_combos}\n", file=sys.stderr)
    
    from ai.suite import OptimizerTuningAgent
    suite.tuning_agent = OptimizerTuningAgent(
        horizons=["1h", "4h"],
        symbol_sets=["top20", "top50", "all"],
        max_total_trials=new_max_trials,
        max_combos_per_strategy=new_max_combos,
        max_candidates=30,
        fee_percent=0.04,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Quant Research Engine: Optimizer + Research Loop")
    parser.add_argument("--horizon", default="4h", choices=("1h", "4h", "24h"))
    parser.add_argument("--lookback-days", type=int, default=90) # Reducido de 1000 para mayor relevancia reciente
    parser.add_argument("--max-cycles", type=int, default=10)
    parser.add_argument("--max-trials", type=int, default=800) # Subido de 400
    parser.add_argument("--cycles-before-explore", type=int, default=3)
    parser.add_argument("--use-champion", action="store_true", default=True) # Usar champion por defecto
    parser.add_argument("--model-uri", default="models:/quant_alpha_entry@champion")
    parser.add_argument("--db", default=None)
    parser.add_argument("--out-report", default="artifacts/quant_model/suite_report.json")
    args = parser.parse_args()

    db_path = args.db or os.environ.get("DBT_DUCKDB_PATH", str(REPO_ROOT / "artifacts" / "warehouse" / "crypto.duckdb"))
    
    from ai.data.loader import load_decision_features
    from ai.suite import (
        QuantAgentSuite,
        OptimizerTuningAgent,
        BacktestDecisionAgent,
        DefaultReportAgent,
        DefaultEvolutionAgent,
        run_research_loop,
    )

    end_dt = datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(days=args.lookback_days)

    print(f"Loading data for research ({args.lookback_days}d history, horizon={args.horizon})...", file=sys.stderr)
    try:
        rows = load_decision_features(
            db_path=db_path,
            horizon=args.horizon,
            label_not_null=True,
            start=start_dt.strftime("%Y-%m-%d"),
            end=end_dt.strftime("%Y-%m-%d"),
        )
    except Exception as e:
        err = str(e).lower()
        if "does not exist" in err or "catalog" in err:
            print(
                "decision_features no existe. Ejecuta 04_pipeline_datos_completo primero.",
                file=sys.stderr,
            )
        else:
            print(f"Error cargando decision_features: {e}", file=sys.stderr)
        return 1

    if not rows or len(rows) < 500:
        print(f"Insufficient data: {len(rows) if rows else 0} rows found. Need >= 500.", file=sys.stderr)
        return 1

    # Enriquecer con el mejor modelo ML (Champion) para tener alpha_score real
    if args.use_champion:
        try:
            from ai.inference.champion_loader import enrich_rows_with_champion
            mlflow_uri = os.environ.get("MLFLOW_TRACKING_URI", f"sqlite:///{REPO_ROOT}/artifacts/quant_model/mlflow_v2.db")
            rows = enrich_rows_with_champion(rows, model_uri=args.model_uri, mlflow_tracking_uri=mlflow_uri)
            print("Alpha score enriched with ML champion.", file=sys.stderr)
        except Exception as e:
            print(f"Warning: Could not load champion ({e}). Using existing alpha_score.", file=sys.stderr)

    # Configuración del motor de búsqueda
    tuning_agent = OptimizerTuningAgent(
        horizons=["1h", "4h"],
        symbol_sets=["top20", "top50", "all"],
        max_total_trials=args.max_trials,
        max_combos_per_strategy=args.max_trials // 4, # Aumentado para explorar más pesos
        max_candidates=20,
        fee_percent=0.04,
    )

    state_path = str(REPO_ROOT / "artifacts" / "quant_model" / "suite_state.json")
    research_state_path = str(REPO_ROOT / "artifacts" / "quant_model" / "research_state.json")
    
    suite = QuantAgentSuite(
        tuning_agent=tuning_agent,
        decision_agent=BacktestDecisionAgent(horizon=args.horizon, fee_percent=0.04, db_path=db_path),
        report_agent=DefaultReportAgent(
            promote_min_net_return=0.5,
            promote_min_trades=10,
            report_dir=str(REPO_ROOT / "artifacts" / "quant_model"),
        ),
        evolution_agent=DefaultEvolutionAgent(),
        state_path=state_path,
        report_dir=str(REPO_ROOT / "artifacts" / "quant_model"),
    )

    print(f"\nIniciando Ciclo de Investigación: max_cycles={args.max_cycles}, trials/ciclo={args.max_trials}", file=sys.stderr)

    state, report, research_state, cycles_run = run_research_loop(
        suite,
        rows,
        max_cycles=args.max_cycles,
        cycles_before_explore=args.cycles_before_explore,
        stop_on_promote=False,
        on_explore=_scale_exploration,
        state_path=state_path,
        research_state_path=research_state_path,
    )

    print(f"\n{'='*80}", file=sys.stderr)
    print(f"RESEARCH LOOP FINALIZADO: {cycles_run} ciclos completados", file=sys.stderr)
    print(f"Champion Actual: {state.champion_id} (v{state.version})", file=sys.stderr)
    print(f"Métricas Champion: Net={state.champion_metrics.get('net_return_percent', 0):.2f}%, Sharpe={state.champion_metrics.get('sharpe', 0):.2f}", file=sys.stderr)
    print(f"Estado de Investigación: {research_state.mode} (Round {research_state.exploration_round})", file=sys.stderr)
    print(f"{'='*80}\n", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
