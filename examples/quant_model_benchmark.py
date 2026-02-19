from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

import mlflow

from trading_lib import FeeModel
from trading_lib.quant import benchmark_models_walk_forward, build_labeled_rows
from trading_lib.timeseries import load_jsonl_timeseries


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark ML models (LGBM/RF/LogReg) with walk-forward validation")
    parser.add_argument(
        "--dataset",
        default="/Users/joaquincano/data/binance_lake/gold/signals/decision_features_backfill",
        help="Path to decision_features dataset directory or glob",
    )
    parser.add_argument("--horizon", default="fwd_return_4h", choices=["fwd_return_1h", "fwd_return_4h", "fwd_return_24h"])
    parser.add_argument("--prob-threshold", type=float, default=0.55, help="Entry probability threshold for long/short")
    parser.add_argument(
        "--prob-threshold-grid",
        default="0.55,0.6,0.65,0.7",
        help="Comma-separated thresholds to optimize per model, e.g. 0.55,0.6,0.65",
    )
    parser.add_argument("--train-days", type=int, default=60)
    parser.add_argument("--test-days", type=int, default=14)
    parser.add_argument("--step-days", type=int, default=14)
    parser.add_argument("--embargo-hours", type=int, default=12)
    parser.add_argument("--mlflow-uri", default="sqlite:///artifacts/quant_model/mlflow.db")
    parser.add_argument("--mlflow-experiment", default="quant-benchmark")
    args = parser.parse_args()

    data_glob = args.dataset if "*" in args.dataset else f"{args.dataset}/**/part-*.jsonl"
    # Load multi-timeframe
    from pathlib import Path
    base_path = Path(args.dataset).parent if Path(args.dataset).is_file() else Path(args.dataset)
    
    rows_1h = load_jsonl_timeseries(data_glob, key_fields=("event_time", "symbol"))
    
    path_4h = str(base_path).replace("decision_features_backfill", "decision_features_backfill_4h")
    path_1d = str(base_path).replace("decision_features_backfill", "decision_features_backfill_1d")
    
    rows_4h = None
    if Path(path_4h).exists():
        try:
            rows_4h = load_jsonl_timeseries(f"{path_4h}/**/part-*.jsonl", key_fields=("event_time", "symbol"))
        except:
            pass
    
    rows_1d = None
    if Path(path_1d).exists():
        try:
            rows_1d = load_jsonl_timeseries(f"{path_1d}/**/part-*.jsonl", key_fields=("event_time", "symbol"))
        except:
            pass
    
    labeled = build_labeled_rows(rows_1h, rows_4h=rows_4h, rows_1d=rows_1d)
    fee_model = FeeModel()
    fee_percent = fee_model.round_trip_fee_percent("futures", is_maker=True)
    prob_grid = [float(x.strip()) for x in str(args.prob_threshold_grid).split(",") if x.strip()]

    results = benchmark_models_walk_forward(
        labeled_rows=labeled,
        target_horizon=args.horizon,
        prob_threshold=args.prob_threshold,
        prob_threshold_grid=prob_grid,
        fee_percent=fee_percent,
        train_days=args.train_days,
        test_days=args.test_days,
        step_days=args.step_days,
        embargo_hours=args.embargo_hours,
    )
    if not results:
        raise ValueError("No benchmark results produced. Check dataset size/splits.")

    top = results[:8]
    print("=== Model Benchmark Leaderboard ===")
    for i, r in enumerate(top, start=1):
        print(
            f"[{i}] {r.model_name}/{r.feature_set_name} "
            f"| obj={r.objective:.4f} | net={r.mean_net_return_percent:.4f}% "
            f"| mdd={r.mean_mdd_percent:.4f}% | win={r.mean_win_rate_percent:.2f}% "
            f"| trades={r.mean_trades:.2f}"
        )
        print(f"    params={r.params}")

    report = {
        "config": {
            "dataset": data_glob,
            "horizon": args.horizon,
            "prob_threshold": args.prob_threshold,
            "prob_threshold_grid": prob_grid,
            "fee_percent": fee_percent,
            "train_days": args.train_days,
            "test_days": args.test_days,
            "step_days": args.step_days,
            "embargo_hours": args.embargo_hours,
        },
        "leaderboard": [asdict(r) for r in results],
        "best": asdict(results[0]),
        "leakage_guards": {
            "split_policy": "walk-forward by time",
            "policy": "train on fold train window only, evaluate on next fold test window",
            "embargo_hours": args.embargo_hours,
            "forbidden_features": ["fwd_return_*", "label", "target", "future_*"],
        },
    }
    out = Path("artifacts/quant_model/model_benchmark_report.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")

    mlflow.set_tracking_uri(args.mlflow_uri)
    mlflow.set_experiment(args.mlflow_experiment)
    with mlflow.start_run(run_name="model_benchmark_best"):
        mlflow.log_params(
            {
                "dataset": data_glob,
                "horizon": args.horizon,
                "train_days": args.train_days,
                "test_days": args.test_days,
                "step_days": args.step_days,
                "embargo_hours": args.embargo_hours,
                "prob_threshold_grid": ",".join(str(x) for x in prob_grid),
            }
        )
        best = results[0]
        mlflow.log_param("best_model_name", best.model_name)
        mlflow.log_param("best_feature_set", best.feature_set_name)
        for k, v in best.params.items():
            mlflow.log_param(f"best__{k}", v)
        mlflow.log_metric("best__objective", float(best.objective))
        mlflow.log_metric("best__mean_net_return_percent", float(best.mean_net_return_percent))
        mlflow.log_metric("best__mean_mdd_percent", float(best.mean_mdd_percent))
        mlflow.log_metric("best__mean_win_rate_percent", float(best.mean_win_rate_percent))
        mlflow.log_metric("best__mean_trades", float(best.mean_trades))
        mlflow.log_dict(report, "model_benchmark_report.json")
    print(f"Saved benchmark report -> {out}")


if __name__ == "__main__":
    main()

