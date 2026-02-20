"""Training pipeline: load from DuckDB, walk-forward, calibration, save."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from trading_lib import build_labeled_rows, build_walk_forward_splits
from trading_lib.quant import LabeledRow
from trading_lib.quant.benchmark import benchmark_models_walk_forward
from trading_lib.quant.calibration import (
    CalibratedModel,
    load_calibration,
    predict_calibrated_probability,
    save_calibration,
    train_calibration,
)
from trading_lib.quant.proper_calibration import calibrate_per_split
from trading_lib.quant.real_model_wrapper import RealModelWrapper

from ai.config import get_calibration_dir, get_warehouse_path
from ai.data.loader import load_decision_features
from ai.registry import log_run

import numpy as np


@dataclass
class TrainingResult:
    run_id: str
    calibration_path: str
    prob_threshold: float
    sharpe_like: float
    trades: int
    win_rate: float


def _parse_iso(value: str):
    from datetime import datetime, timezone
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _build_labels_for_calibration(
    labeled_rows: list[LabeledRow],
    horizon: str,
    fee_percent: float = 0.04,
) -> tuple[list[float], list[int]]:
    from trading_lib.quant.improved_labels import build_improved_labels
    scores = [
        sum(float(v) for v in row.features.values()) / len(row.features) if row.features else 0.0
        for row in labeled_rows
    ]
    _, labels, _ = build_improved_labels(labeled_rows, horizon, fee_percent)
    return scores, labels


def _simulate_with_calibration(
    labeled_rows: list[LabeledRow],
    calibration_model: CalibratedModel | None,
    prob_threshold: float,
    horizon: str,
    fee_percent: float = 0.04,
) -> dict:
    trades = 0
    wins = 0
    returns: list[float] = []
    for row in labeled_rows:
        score = sum(float(v) for v in row.features.values()) / len(row.features) if row.features else 0.0
        if calibration_model:
            prob = predict_calibrated_probability(score, calibration_model)
        else:
            prob = 1.0 / (1.0 + np.exp(-score))
        if prob < prob_threshold:
            continue
        side = 1.0 if score >= 0 else -1.0
        fwd_return = getattr(row, horizon)
        net_return = (side * fwd_return) - fee_percent
        trades += 1
        returns.append(net_return)
        if net_return > 0:
            wins += 1
    if not returns:
        return {"trades": 0, "win_rate": 0.0, "net_return": 0.0, "sharpe_like": 0.0}
    avg = np.mean(returns)
    std = np.std(returns) if len(returns) > 1 else 0.0
    sharpe = (avg / std) if std > 0 else 0.0
    return {
        "trades": trades,
        "win_rate": (wins / trades * 100.0) if trades > 0 else 0.0,
        "net_return": sum(returns),
        "sharpe_like": sharpe,
    }


def run_training(
    horizon: str = "4h",
    train_days: int = 90,
    test_days: int = 14,
    step_days: int = 14,
    embargo_hours: int = 12,
    symbols: list[str] | None = None,
    fee_percent: float = 0.04,
) -> TrainingResult:
    """
    Load from DuckDB, walk-forward train, calibrate, save.
    Returns TrainingResult with paths and metrics.
    """
    label_col = {"1h": "fwd_return_1h", "4h": "fwd_return_4h", "24h": "fwd_return_24h"}.get(
        horizon, "fwd_return_4h"
    )
    rows_1h = load_decision_features(
        horizon=horizon,
        symbols=symbols,
        label_not_null=True,
    )
    if not rows_1h:
        raise ValueError("No decision_features in DuckDB. Run warehouse-load first.")

    labeled_rows = build_labeled_rows(rows_1h)
    rows_for_splits = [{"event_time": r.event_time, "symbol": r.symbol} for r in labeled_rows]
    splits = build_walk_forward_splits(
        rows_for_splits,
        train_days=train_days,
        test_days=test_days,
        step_days=step_days,
        embargo_hours=embargo_hours,
    )

    calib_dir = get_calibration_dir()
    Path(calib_dir).mkdir(parents=True, exist_ok=True)
    calib_path = f"{calib_dir}/champion_{horizon}_calibration.json"

    if not splits:
        split_idx = int(len(labeled_rows) * 0.8)
        train_rows = labeled_rows[:split_idx]
        test_rows = labeled_rows[split_idx:]
        scores, labels = _build_labels_for_calibration(train_rows, label_col, fee_percent)
        if len(scores) < 10:
            raise ValueError(f"Insufficient data for calibration ({len(scores)} samples)")
        calibration = train_calibration(scores, labels, feature_name="champion_score")
        best_threshold = 0.55
        best_metric = 0.0
        for th in [0.45, 0.50, 0.55, 0.60]:
            sim = _simulate_with_calibration(test_rows, calibration, th, label_col, fee_percent)
            if sim["sharpe_like"] > best_metric:
                best_metric = sim["sharpe_like"]
                best_threshold = th
        save_calibration(calibration, calib_path)
        run_id = log_run(
            run_type="train",
            config={"horizon": horizon, "train_days": train_days, "test_days": test_days},
            metrics={"sharpe_like": best_metric, "net_return": sim["net_return"], "trades": sim["trades"], "win_rate": sim["win_rate"]},
            artifacts={"calibration_path": calib_path},
            data_rows=rows_1h,
        )
        return TrainingResult(
            run_id=run_id,
            calibration_path=calib_path,
            prob_threshold=best_threshold,
            sharpe_like=best_metric,
            trades=sim["trades"],
            win_rate=sim["win_rate"],
        )

    results = benchmark_models_walk_forward(
        labeled_rows,
        target_horizon=label_col,
        train_days=train_days,
        test_days=test_days,
        step_days=step_days,
        embargo_hours=embargo_hours,
    )
    champion = max(results, key=lambda r: r.objective)
    last_split = splits[-1]
    train_rows = [
        r for r in labeled_rows
        if _parse_iso(last_split.train_start) <= _parse_iso(r.event_time) < _parse_iso(last_split.train_end)
    ]
    split_idx = int(len(train_rows) * 0.8)
    calib_train = train_rows[:split_idx]
    calib_val = train_rows[split_idx:]
    model_type = getattr(champion, "model_name", "lgbm")
    model, best_threshold, val_metrics = calibrate_per_split(
        calib_train,
        calib_val,
        model_type=model_type,
        target_horizon=label_col,
    )
    test_rows = [
        r for r in labeled_rows
        if _parse_iso(last_split.test_start) <= _parse_iso(r.event_time) < _parse_iso(last_split.test_end)
    ]
    test_probs = model.predict_proba(test_rows)[:, 1]
    test_returns = np.array([getattr(r, label_col) for r in test_rows])
    test_net = test_returns - fee_percent
    signals = np.zeros_like(test_probs)
    signals[test_probs >= best_threshold] = 1.0
    signals[test_probs <= (1.0 - best_threshold)] = -1.0
    active = signals != 0.0
    if np.any(active):
        net = signals[active] * test_net[active]
        avg_return = np.mean(net)
        std_return = np.std(net) if len(net) > 1 else 0.01
        periods_per_year = 8760.0
        best_metric = (avg_return * np.sqrt(periods_per_year)) / (std_return * np.sqrt(periods_per_year)) if std_return > 0 else 0.0
        trades = len(net)
        win_rate = float(np.sum(net > 0) / len(net) * 100) if len(net) > 0 else 0.0
    else:
        best_metric = 0.0
        trades = 0
        win_rate = 0.0

    calibration = train_calibration(
        [sum(float(v) for v in r.features.values()) / len(r.features) if r.features else 0.0 for r in calib_train],
        [1 if getattr(r, label_col) > fee_percent else 0 for r in calib_train],
        feature_name="champion_score",
    )
    save_calibration(calibration, calib_path)
    run_id = log_run(
        run_type="train",
        config={"horizon": horizon, "train_days": train_days, "test_days": test_days, "step_days": step_days},
        metrics={"sharpe_like": best_metric, "trades": trades, "win_rate": win_rate},
        artifacts={"calibration_path": calib_path},
        data_rows=rows_1h,
    )
    return TrainingResult(
        run_id=run_id,
        calibration_path=calib_path,
        prob_threshold=best_threshold,
        sharpe_like=best_metric,
        trades=trades,
        win_rate=win_rate,
    )
