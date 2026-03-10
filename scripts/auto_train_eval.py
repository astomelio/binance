#!/usr/bin/env python3
"""
Motor de investigacion quant autonomo: benchmark walk-forward multi-modelo.
Versión Industrial: Prueba modelos ML con validación walk-forward real.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("DBT_DUCKDB_PATH", str(REPO_ROOT / "artifacts" / "warehouse" / "crypto.duckdb"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark walk-forward multi-modelo (Industrial)")
    parser.add_argument("--db", default=None, help="DuckDB path")
    parser.add_argument("--horizon", default="4h", choices=("1h", "4h", "24h"))
    parser.add_argument("--lookback-days", type=float, default=1000)
    parser.add_argument("--test-days", type=float, default=14)
    parser.add_argument("--train-days", type=float, default=180)
    parser.add_argument("--step-days", type=float, default=14)
    parser.add_argument("--register-name", default="quant_alpha_entry")
    parser.add_argument("--set-champion", action="store_true")
    parser.add_argument("--neutral", action="store_true", help="Use alpha-neutral (beta-adjusted) returns as target")
    parser.add_argument("--mlflow-uri", default=None)
    parser.add_argument("--out-report", default="artifacts/quant_model/auto_report.json")
    parser.add_argument("--embargo-hours", type=float, default=12)
    args = parser.parse_args()

    db_path = args.db or os.environ.get("DBT_DUCKDB_PATH", str(REPO_ROOT / "artifacts" / "warehouse" / "crypto.duckdb"))
    
    from ai.data.loader import load_decision_features
    from trading_lib.quant.labels import build_labeled_rows
    from trading_lib.quant.benchmark import benchmark_models_walk_forward

    target_col = f"fwd_return_{args.horizon}"
    if args.neutral:
        target_col = f"alpha_return_{args.horizon}_btc"
        print(f"NEUTRAL MODE: Target is {target_col}", file=sys.stderr)
    
    end_dt = datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(days=args.lookback_days)

    print(f"Loading decision_features ({args.lookback_days}d history, horizon={args.horizon})...", file=sys.stderr)
    rows = load_decision_features(
        horizon=args.horizon,
        label_not_null=True,
        db_path=db_path,
        start=start_dt.strftime("%Y-%m-%d"),
        end=end_dt.strftime("%Y-%m-%d"),
    )
    
    if not rows or len(rows) < 1000:
        print(f"Insufficient rows ({len(rows) if rows else 0}). Need >= 1000 for industry-standard research.", file=sys.stderr)
        return 1

    n_syms = len(set(r.get("symbol", "") for r in rows))
    print(f"Loaded {len(rows)} rows ({n_syms} symbols)", file=sys.stderr)

    print("Building labeled rows...", file=sys.stderr)
    labeled = build_labeled_rows(rows)
    # Filtrar outliers y ceros para mejorar la convergencia
    labeled = [r for r in labeled if getattr(r, target_col, None) is not None and abs(getattr(r, target_col)) > 1e-6]
    
    if len(labeled) < 500:
        print(f"Insufficient labeled rows after filtering ({len(labeled)}).", file=sys.stderr)
        return 1
    print(f"Labeled: {len(labeled)} rows", file=sys.stderr)

    # -- Walk-forward benchmark: 3 modelos x 4 feature sets x param grids x prob thresholds --
    print("\nRunning Intensive Walk-Forward Benchmark...", file=sys.stderr)
    print("Hypotheses: LightGBM, RandomForest, LogisticRegression x [core, plus_flow, full, cross_dex]", file=sys.stderr)
    
    results = benchmark_models_walk_forward(
        labeled,
        target_horizon=target_col,
        prob_threshold=0.55,
        prob_threshold_grid=[0.52, 0.55, 0.58, 0.62],
        fee_percent=0.04,
        train_days=args.train_days,
        test_days=args.test_days,
        step_days=args.step_days,
        embargo_hours=args.embargo_hours,
        max_drawdown_limit=0.15 # <--- Nuevo: Risk Engine MDD Limit en el backtest
    )

    if not results:
        print("Benchmark produced no results.", file=sys.stderr)
        return 1

    print(f"\n{'='*80}", file=sys.stderr)
    print(f"RESEARCH SUMMARY: {len(results)} configurations evaluated", file=sys.stderr)
    print(f"{'='*80}", file=sys.stderr)
    for i, r in enumerate(results[:10]):
        print(
            f"  #{i+1}: {r.model_name}/{r.feature_set_name} "
            f"| Fit={r.objective:.3f} | Net={r.mean_net_return_percent:.2f}% "
            f"| Win={r.mean_win_rate_percent:.1f}% | MDD={r.mean_mdd_percent:.1f}%",
            file=sys.stderr,
        )
    print(f"{'='*80}\n", file=sys.stderr)

    best = results[0]
    # Criterio Industrial: Sharpe ajustado (objective) > 0 Y Retorno neto positivo mediano
    is_profitable = best.objective > 0.05 and best.mean_net_return_percent > 0.5

    report = {
        "benchmark_results_count": len(results),
        "best_model": best.model_name,
        "best_feature_set": best.feature_set_name,
        "best_params": best.params,
        "best_objective": best.objective,
        "best_mean_net_return_percent": best.mean_net_return_percent,
        "best_mean_mdd_percent": best.mean_mdd_percent,
        "is_profitable": is_profitable,
        "registered": False,
        "champion": False,
    }

    if not is_profitable:
        print(f"WARNING: Best model fails profitability threshold (Fit={best.objective:.3f}).", file=sys.stderr)
        
        # Check if there is already a champion. If not, we MUST register one to avoid breaking the execution pipeline.
        try:
            import mlflow
            from mlflow import MlflowClient
            mlflow_uri = args.mlflow_uri or os.environ.get(
                "MLFLOW_TRACKING_URI",
                f"sqlite:///{REPO_ROOT / 'artifacts' / 'quant_model' / 'mlflow_v2.db'}",
            )
            mlflow.set_tracking_uri(mlflow_uri)
            client = MlflowClient()
            client.get_model_version_by_alias(args.register_name, "champion")
            has_champion = True
        except Exception:
            has_champion = False
            
        if has_champion:
            _write_report(report, args.out_report)
            return 0
        else:
            print("WARNING: Forcing registration because no champion exists. This is required for the pipeline to run.", file=sys.stderr)

    # -- Registro en MLflow --
    print(f"PROMOTING: {best.model_name}/{best.feature_set_name} with Fit={best.objective:.3f}", file=sys.stderr)
    report["registered"] = True

    try:
        import mlflow
        import mlflow.sklearn
        from mlflow import MlflowClient
        from trading_lib.quant.benchmark import _train_model, _build_samples
        import numpy as np
        import pandas as pd

        mlflow_uri = args.mlflow_uri or os.environ.get(
            "MLFLOW_TRACKING_URI",
            f"sqlite:///{REPO_ROOT / 'artifacts' / 'quant_model' / 'mlflow_v2.db'}",
        )
        mlflow.set_tracking_uri(mlflow_uri)
        mlflow.set_experiment("quant_research_engine")
        
        # Preparar datos finales para el modelo champion (usando todo el histórico)
        samples = _build_samples(labeled, target_col)
        from trading_lib.quant.benchmark import feature_sets as FEATURE_SETS
        feat_names = FEATURE_SETS.get(best.feature_set_name, FEATURE_SETS["core_micro"])
        
        X_full = pd.DataFrame([{f: float(r.get(f, 0.0) or 0.0) for f in feat_names} for r in samples], columns=feat_names)
        y_ret = np.array([float(r["y_return"]) for r in samples], dtype=float)
        y_cls = (y_ret > 0.0).astype(int)

        clean_params = {k: v for k, v in best.params.items() if k != "prob_threshold"}
        final_model = _train_model(best.model_name, clean_params)
        final_model.fit(X_full, y_cls)

        with mlflow.start_run(run_name=f"champion_{best.model_name}_{datetime.now(timezone.utc):%m%d_%H%M}"):
            mlflow.log_params({
                "model_type": best.model_name,
                "feature_set": best.feature_set_name,
                "horizon": args.horizon,
                "lookback": args.lookback_days,
                **{k: str(v) for k, v in best.params.items()},
            })
            mlflow.log_metrics({
                "objective": best.objective,
                "mean_net_return": best.mean_net_return_percent,
                "win_rate": best.mean_win_rate_percent,
                "max_drawdown": best.mean_mdd_percent,
                "n_samples": len(X_full),
            })
            mlflow.sklearn.log_model(final_model, "model")
            
            run_id = mlflow.active_run().info.run_id
            mv = mlflow.register_model(f"runs:/{run_id}/model", args.register_name)
            
            if args.set_champion:
                client = MlflowClient()
                client.set_registered_model_alias(args.register_name, "champion", mv.version)
                report["champion"] = True
                print(f"Set as CHAMPION v{mv.version}", file=sys.stderr)

    except Exception as e:
        print(f"MLflow error: {e}", file=sys.stderr)
        report["mlflow_error"] = str(e)

    _write_report(report, args.out_report)
    return 0


def _write_report(report: dict, out_path: str) -> None:
    p = REPO_ROOT / out_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
