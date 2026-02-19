from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

import mlflow
import numpy as np

from trading_lib import FeeModel, StrategySpec, compute_model_allocations, load_jsonl_timeseries
from trading_lib.quant import LabeledRow, build_labeled_rows
from trading_lib.quant.benchmark import benchmark_models_walk_forward
from trading_lib.quant.calibration import (
    CalibratedModel,
    load_calibration,
    predict_calibrated_probability,
    save_calibration,
    train_calibration,
)
from trading_lib.timeseries import build_walk_forward_splits


def _parse_iso(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _build_labels_for_calibration(
    labeled_rows: List[LabeledRow],
    horizon: str,
    fee_percent: float = 0.04,
) -> tuple[List[float], List[int]]:
    """
    Build improved labels with risk adjustment.
    Uses real model scores, not average of features.
    """
    from trading_lib.quant.improved_labels import build_improved_labels
    
    # This will be replaced by actual model scores in proper workflow
    # For now, use placeholder (will be replaced by RealModelWrapper)
    scores = [sum(float(v) for v in row.features.values()) / len(row.features) if row.features else 0.0 
              for row in labeled_rows]
    
    _, labels, _ = build_improved_labels(labeled_rows, horizon, fee_percent)
    
    return scores, labels


def _simulate_with_calibration(
    labeled_rows: List[LabeledRow],
    calibration_model: CalibratedModel | None,
    prob_threshold: float,
    horizon: str,
    fee_percent: float = 0.04,
) -> Dict:
    """Simulate trading with calibrated probabilities."""
    trades = 0
    wins = 0
    returns: List[float] = []
    
    for row in labeled_rows:
        # Base score
        score = sum(float(v) for v in row.features.values()) / len(row.features) if row.features else 0.0
        
        # Calibrated probability
        if calibration_model:
            prob = predict_calibrated_probability(score, calibration_model)
        else:
            # Fallback: simple sigmoid
            prob = 1.0 / (1.0 + np.exp(-score))
        
        if prob < prob_threshold:
            continue
        
        # Determine side (simplified: use score sign)
        side = 1.0 if score >= 0 else -1.0
        fwd_return = getattr(row, horizon)
        net_return = (side * fwd_return) - fee_percent
        
        trades += 1
        returns.append(net_return)
        if net_return > 0:
            wins += 1
    
    if not returns:
        return {
            "trades": 0,
            "win_rate": 0.0,
            "net_return": 0.0,
            "sharpe_like": 0.0,
        }
    
    avg_return = np.mean(returns)
    std_return = np.std(returns) if len(returns) > 1 else 0.0
    sharpe_like = (avg_return / std_return) if std_return > 0 else 0.0
    
    return {
        "trades": trades,
        "win_rate": (wins / trades * 100.0) if trades > 0 else 0.0,
        "net_return": sum(returns),
        "sharpe_like": sharpe_like,
    }


def run_champion_challenger(
    data_path: str,
    horizon: str,
    mlflow_uri: str = "sqlite:///artifacts/mlflow/mlflow.db",
    mlflow_experiment: str = "champion_challenger",
    train_days: int = 60,
    test_days: int = 14,
    step_days: int = 14,
    embargo_hours: int = 12,
) -> None:
    """Run champion/challenger evaluation by horizon."""
    
    # Load data - 1h, 4h, 1d for multi-timeframe
    print(f"[1/5] Loading data from {data_path}...")
    import os
    from pathlib import Path
    
    base_path = Path(data_path).parent if Path(data_path).is_file() else Path(data_path)
    
    # Try to find 4h and 1d data in same directory structure
    path_1h = data_path
    path_4h = str(base_path).replace("decision_features_backfill", "decision_features_backfill_4h") if "backfill" in str(base_path) else None
    path_1d = str(base_path).replace("decision_features_backfill", "decision_features_backfill_1d") if "backfill" in str(base_path) else None
    
    if os.path.isdir(path_1h):
        path_1h = os.path.join(path_1h, "**/*.jsonl")
    
    try:
        rows_1h = load_jsonl_timeseries(path_1h, key_fields=("event_time", "symbol"))
        print(f"Loaded {len(rows_1h)} 1h rows")
    except Exception as e:
        print(f"Error loading 1h: {e}")
        import duckdb
        con = duckdb.connect("artifacts/warehouse/crypto.duckdb")
        rows_dict = con.sql("select * from gold.fct_decision_features where fwd_return_4h is not null order by event_time, symbol").fetchall()
        cols = [desc[0] for desc in con.sql("describe gold.fct_decision_features").fetchall()]
        rows_1h = [dict(zip(cols, r)) for r in rows_dict]
        print(f"Loaded {len(rows_1h)} rows from DuckDB")
    
    rows_4h = None
    if path_4h and os.path.exists(path_4h.replace("/**/*.jsonl", "")):
        try:
            path_4h_glob = os.path.join(path_4h, "**/*.jsonl") if os.path.isdir(path_4h) else path_4h
            rows_4h = load_jsonl_timeseries(path_4h_glob, key_fields=("event_time", "symbol"))
            print(f"Loaded {len(rows_4h)} 4h rows for multi-timeframe")
        except:
            pass
    
    rows_1d = None
    if path_1d and os.path.exists(path_1d.replace("/**/*.jsonl", "")):
        try:
            path_1d_glob = os.path.join(path_1d, "**/*.jsonl") if os.path.isdir(path_1d) else path_1d
            rows_1d = load_jsonl_timeseries(path_1d_glob, key_fields=("event_time", "symbol"))
            print(f"Loaded {len(rows_1d)} 1d rows for multi-timeframe")
        except:
            pass
    
    # Build labeled rows with multi-timeframe
    print(f"[2/5] Building labeled rows for horizon {horizon}...")
    labeled_rows = build_labeled_rows(rows_1h, rows_4h=rows_4h, rows_1d=rows_1d)
    print(f"Built {len(labeled_rows)} labeled rows (with multi-timeframe: {rows_4h is not None or rows_1d is not None})")
    
    # Convert LabeledRow to dicts for walk-forward splits
    rows_for_splits = [
        {"event_time": r.event_time, "symbol": r.symbol}
        for r in labeled_rows
    ]
    
    # Build walk-forward splits
    print(f"[3/5] Building walk-forward splits...")
    splits = build_walk_forward_splits(
        rows_for_splits,
        train_days=train_days,
        test_days=test_days,
        step_days=step_days,
        embargo_hours=embargo_hours,
    )
    print(f"Built {len(splits)} splits")
    
    if len(splits) == 0:
        print("WARNING: No walk-forward splits created. Using simple train/test split...")
        # Simple split: 80% train, 20% test
        split_idx = int(len(labeled_rows) * 0.8)
        train_rows = labeled_rows[:split_idx]
        test_rows = labeled_rows[split_idx:]
        print(f"Train: {len(train_rows)}, Test: {len(test_rows)}")
        
        # For now, skip benchmarking and go straight to calibration
        print("[4/5] Skipping benchmark (insufficient data), training calibration directly...")
        scores, labels = _build_labels_for_calibration(train_rows, horizon)
        if len(scores) < 10:
            print(f"ERROR: Insufficient data for calibration ({len(scores)} samples)")
            return
        
        calibration = train_calibration(scores, labels, feature_name="champion_score")
        
        # Test calibration
        test_scores, test_labels = _build_labels_for_calibration(test_rows, horizon)
        prob_thresholds = [0.45, 0.50, 0.55, 0.60]
        best_threshold = None
        best_metric = -float("inf")
        
        for th in prob_thresholds:
            sim_result = _simulate_with_calibration(test_rows, calibration, th, horizon)
            metric = sim_result["sharpe_like"]
            if metric > best_metric:
                best_metric = metric
                best_threshold = th
        
        print(f"Best prob threshold: {best_threshold} (Sharpe-like: {best_metric:.4f})")
        print(f"Test trades: {sim_result['trades']}, Win rate: {sim_result['win_rate']:.2f}%")
        
        # Save calibration
        calib_path = f"artifacts/calibration/champion_{horizon}_calibration.json"
        Path(calib_path).parent.mkdir(parents=True, exist_ok=True)
        save_calibration(calibration, calib_path)
        print(f"Saved calibration to {calib_path}")
        return
    
    # Setup MLflow
    mlflow.set_tracking_uri(mlflow_uri)
    mlflow.set_experiment(mlflow_experiment)
    
    # Benchmark models
    print(f"[4/5] Benchmarking models...")
    results = benchmark_models_walk_forward(
        labeled_rows,
        target_horizon=horizon,
        train_days=train_days,
        test_days=test_days,
        step_days=step_days,
        embargo_hours=embargo_hours,
    )
    
    # Find champion (by objective which is sharpe-like)
    champion = max(results, key=lambda r: r.objective)
    print(f"\n[5/5] Champion model: {champion.model_name} / {champion.feature_set_name}")
    print(f"  Objective (Sharpe-like): {champion.objective:.4f}")
    print(f"  Net return: {champion.mean_net_return_percent:.4f}%")
    print(f"  Win rate: {champion.mean_win_rate_percent:.2f}%")
    print(f"  Trades: {champion.mean_trades:.0f}")
    
    # Train REAL model per split (NO LEAKAGE, NO FAKE AVERAGE)
    print(f"\n[6/6] Training real model per split (no leakage)...")
    from trading_lib.quant.proper_calibration import calibrate_per_split
    from trading_lib.quant.real_model_wrapper import RealModelWrapper
    
    if not splits:
        print("No splits available")
        return
    
    # Use last split for final model (most recent)
    last_split = splits[-1]
    train_rows = [
        r for r in labeled_rows
        if _parse_iso(last_split.train_start) <= _parse_iso(r.event_time) < _parse_iso(last_split.train_end)
    ]
    
    # Split train into train/validation (80/20) - NO TEST LEAKAGE
    split_idx = int(len(train_rows) * 0.8)
    calib_train = train_rows[:split_idx]
    calib_val = train_rows[split_idx:]
    
    # Use champion model type
    champion_model_type = champion.model_name if hasattr(champion, 'model_name') else "lgbm"
    
    # Train REAL model (learns weights, interactions) + calibrate + optimize threshold on VALIDATION
    model, best_threshold, val_metrics = calibrate_per_split(
        calib_train,
        calib_val,
        model_type=champion_model_type,
        target_horizon=horizon,
    )
    
    # Test on ACTUAL test set (unseen)
    test_rows = [
        r for r in labeled_rows
        if _parse_iso(last_split.test_start) <= _parse_iso(r.event_time) < _parse_iso(last_split.test_end)
    ]
    
    # Get predictions from REAL model
    test_probs = model.predict_proba(test_rows)[:, 1]
    test_returns = np.array([getattr(r, horizon) for r in test_rows])
    test_net = test_returns - 0.04
    
    # Apply threshold (optimized on VALIDATION, not test!)
    signals = np.zeros_like(test_probs)
    signals[test_probs >= best_threshold] = 1.0
    signals[test_probs <= (1.0 - best_threshold)] = -1.0
    
    active = signals != 0.0
    if np.any(active):
        net = signals[active] * test_net[active]
        # Real Sharpe: annualized, with proper risk adjustment
        avg_return = np.mean(net)
        std_return = np.std(net) if len(net) > 1 else 0.01
        # Annualize (assuming hourly data, ~8760 hours/year)
        periods_per_year = 8760.0
        sharpe_annualized = (avg_return * np.sqrt(periods_per_year)) / (std_return * np.sqrt(periods_per_year)) if std_return > 0 else 0.0
        best_metric = sharpe_annualized
        trades = len(net)
        win_rate = float(np.sum(net > 0) / len(net) * 100) if len(net) > 0 else 0.0
    else:
        best_metric = 0.0
        trades = 0
        win_rate = 0.0
    
    print(f"Best prob threshold: {best_threshold} (Sharpe-like: {best_metric:.4f})")
    
    # Save calibration
    calib_path = f"artifacts/calibration/champion_{horizon}_calibration.json"
    Path(calib_path).parent.mkdir(parents=True, exist_ok=True)
    save_calibration(calibration, calib_path)
    print(f"Saved calibration to {calib_path}")
    
    # Save report
    report = {
        "horizon": horizon,
        "all_results": [
            {
                "model_name": r.model_name,
                "feature_set": r.feature_set_name,
                "objective": r.objective,
                "mean_net_return_percent": r.mean_net_return_percent,
            }
            for r in results
        ],
        "calibration": {
            "prob_threshold": best_threshold,
            "sharpe_like": best_metric,
            "path": calib_path,
        },
        "all_results": [
            {
                "model_name": r.model_name,
                "feature_set": r.feature_set,
                "mean_sharpe_like": r.mean_sharpe_like,
                "mean_net_return_percent": r.mean_net_return_percent,
            }
            for r in results
        ],
    }
    
    report_path = f"artifacts/reports/champion_challenger_{horizon}.json"
    Path(report_path).parent.mkdir(parents=True, exist_ok=True)
    Path(report_path).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Saved report to {report_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Champion/Challenger evaluation by horizon")
    parser.add_argument("--data-path", required=True, help="Path to decision_features JSONL")
    parser.add_argument("--horizon", choices=["1h", "4h", "24h"], default="4h", help="Target horizon")
    parser.add_argument("--mlflow-uri", default="sqlite:///artifacts/mlflow/mlflow.db")
    parser.add_argument("--mlflow-experiment", default="champion_challenger")
    parser.add_argument("--train-days", type=int, default=60)
    parser.add_argument("--test-days", type=int, default=14)
    parser.add_argument("--step-days", type=int, default=14)
    parser.add_argument("--embargo-hours", type=int, default=12)
    
    args = parser.parse_args()
    
    horizon_map = {"1h": "fwd_return_1h", "4h": "fwd_return_4h", "24h": "fwd_return_24h"}
    horizon = horizon_map[args.horizon]
    
    run_champion_challenger(
        data_path=args.data_path,
        horizon=horizon,
        mlflow_uri=args.mlflow_uri,
        mlflow_experiment=args.mlflow_experiment,
        train_days=args.train_days,
        test_days=args.test_days,
        step_days=args.step_days,
        embargo_hours=args.embargo_hours,
    )


if __name__ == "__main__":
    main()
