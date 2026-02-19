from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import product
from statistics import mean, pstdev
import numpy as np
from typing import Dict, List, Sequence, Tuple

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from ..timeseries import build_walk_forward_splits
from .labels import LabeledRow

try:
    from lightgbm import LGBMClassifier

    _HAS_LGBM = True
except Exception:  # noqa: BLE001
    LGBMClassifier = None
    _HAS_LGBM = False


@dataclass
class BenchmarkFoldMetric:
    split_index: int
    trades: int
    net_return_percent: float
    win_rate_percent: float
    mdd_percent: float


@dataclass
class BenchmarkResult:
    model_name: str
    feature_set_name: str
    params: Dict
    folds: List[BenchmarkFoldMetric]
    mean_trades: float
    mean_net_return_percent: float
    std_net_return_percent: float
    mean_win_rate_percent: float
    mean_mdd_percent: float
    objective: float


def _parse_iso(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _build_samples(labeled_rows: List[LabeledRow], target_horizon: str) -> List[Dict]:
    rows: List[Dict] = []
    for r in labeled_rows:
        y_return = float(getattr(r, target_horizon))
        row = {
            "event_time": r.event_time,
            "symbol": r.symbol,
            "y_return": y_return,
        }
        row.update({k: float(v) for k, v in r.features.items()})
        rows.append(row)
    rows.sort(key=lambda x: x["event_time"])
    return rows


def _train_model(model_name: str, params: Dict):
    if model_name == "logreg":
        c = float(params.get("C", 1.0))
        class_weight = params.get("class_weight")
        return Pipeline(
            [
                ("scaler", StandardScaler()),
                (
                    "model",
                    LogisticRegression(
                        C=c,
                        class_weight=class_weight,
                        max_iter=2000,
                        random_state=42,
                    ),
                ),
            ]
        )
    if model_name == "rf":
        return RandomForestClassifier(
            n_estimators=int(params.get("n_estimators", 250)),
            max_depth=params.get("max_depth"),
            min_samples_leaf=int(params.get("min_samples_leaf", 1)),
            random_state=42,
            n_jobs=-1,
        )
    if model_name == "lgbm":
        if not _HAS_LGBM:
            raise RuntimeError("LightGBM unavailable (missing native dependency)")
        return LGBMClassifier(
            n_estimators=int(params.get("n_estimators", 250)),
            learning_rate=float(params.get("learning_rate", 0.05)),
            num_leaves=int(params.get("num_leaves", 31)),
            subsample=float(params.get("subsample", 0.9)),
            colsample_bytree=float(params.get("colsample_bytree", 0.9)),
            reg_lambda=float(params.get("reg_lambda", 0.2)),
            random_state=42,
            verbose=-1,
        )
    raise ValueError(f"Unknown model: {model_name}")


def _simulate_from_prob(prob_up: np.ndarray, y_return: np.ndarray, prob_threshold: float, fee_percent: float) -> Tuple[int, float, float, float]:
    # Long when p_up is strong, short when p_down is strong.
    longs = prob_up >= prob_threshold
    shorts = prob_up <= (1.0 - prob_threshold)
    active = longs | shorts
    if not np.any(active):
        return 0, 0.0, 0.0, 0.0

    signal = np.zeros_like(prob_up, dtype=float)
    signal[longs] = 1.0
    signal[shorts] = -1.0
    gross = signal[active] * y_return[active]
    net = gross - fee_percent

    wins = float(np.sum(net > 0))
    trades = int(net.shape[0])
    win_rate = (wins / trades) * 100.0 if trades else 0.0
    net_sum = float(np.sum(net))

    eq = 1.0
    peak = 1.0
    mdd = 0.0
    for r in net:
        eq *= 1.0 + (float(r) / 100.0)
        if eq > peak:
            peak = eq
        dd = ((peak - eq) / peak) * 100.0
        mdd = max(mdd, dd)
    return trades, net_sum, win_rate, mdd


def _param_grid(model_name: str) -> List[Dict]:
    if model_name == "logreg":
        return [{"C": c, "class_weight": cw} for c, cw in product([0.5, 1.0, 2.0], [None, "balanced"])]
    if model_name == "rf":
        return [
            {"n_estimators": 250, "max_depth": d, "min_samples_leaf": leaf}
            for d, leaf in product([4, 8, None], [1, 3])
        ]
    if model_name == "lgbm":
        return [
            {
                "n_estimators": 280,
                "learning_rate": lr,
                "num_leaves": nl,
                "subsample": 0.9,
                "colsample_bytree": 0.9,
                "reg_lambda": reg,
            }
            for lr, nl, reg in product([0.03, 0.06], [31, 63], [0.0, 0.2])
        ]
    raise ValueError(f"Unknown model: {model_name}")


def benchmark_models_walk_forward(
    labeled_rows: List[LabeledRow],
    target_horizon: str = "fwd_return_4h",
    prob_threshold: float = 0.55,
    prob_threshold_grid: Sequence[float] | None = None,
    fee_percent: float = 0.04,
    train_days: int = 60,
    test_days: int = 14,
    step_days: int = 14,
    embargo_hours: int = 12,
) -> List[BenchmarkResult]:
    if not labeled_rows:
        raise ValueError("No labeled rows for benchmark")

    samples = _build_samples(labeled_rows, target_horizon=target_horizon)
    split_rows = [{"event_time": r["event_time"]} for r in samples]
    splits = build_walk_forward_splits(
        rows=split_rows,
        train_days=train_days,
        test_days=test_days,
        step_days=step_days,
        embargo_hours=embargo_hours,
    )
    if not splits:
        raise ValueError("No walk-forward splits generated")

    feature_sets = {
        "core_micro": ["alpha_microstructure_score", "basis_bps", "funding_rate_8h"],
        "core_plus_flow": [
            "alpha_microstructure_score",
            "basis_bps",
            "funding_rate_8h",
            "long_short_account_ratio",
            "buy_sell_ratio",
        ],
        "full_quant": [
            "alpha_microstructure_score",
            "momentum_score",
            "basis_bps",
            "funding_rate_8h",
            "long_short_account_ratio",
            "buy_sell_ratio",
            "fear_greed_value",
            "session_overlap_score",
            "liquidity_event_score",
        ],
        "cross_dex_quant": [
            "alpha_microstructure_score",
            "momentum_score",
            "basis_bps",
            "funding_rate_8h",
            "long_short_account_ratio",
            "buy_sell_ratio",
            "fear_greed_value",
            "session_overlap_score",
            "liquidity_event_score",
            "cross_exchange_spread_bps",
            "cross_exchange_mean_diff_bps",
            "cross_exchange_bid_ask_bps_mean",
            "bybit_okx_delta_bps",
            "cross_exchange_score",
            "dex_cex_basis_bps",
            "dex_liquidity_usd",
            "dex_volume_24h_usd",
            "dex_txn_imbalance_24h",
            "dex_alpha_score",
        ],
    }

    results: List[BenchmarkResult] = []
    model_names = ["logreg", "rf", "lgbm"]
    if not _HAS_LGBM:
        model_names = ["logreg", "rf"]

    # Pre-compute datetimes once for speed.
    ts = np.array([_parse_iso(r["event_time"]) for r in samples], dtype=object)

    for feature_set_name, feature_names in feature_sets.items():
        X_all = pd.DataFrame(
            [{f: float(r.get(f, 0.0) or 0.0) for f in feature_names} for r in samples],
            columns=feature_names,
        )
        y_ret_all = np.array([float(r["y_return"]) for r in samples], dtype=float)
        # Class label is direction (up/down); trading edge is evaluated later with fees.
        y_cls_all = (y_ret_all > 0.0).astype(int)

        for model_name in model_names:
            best_res: BenchmarkResult | None = None
            for params in _param_grid(model_name):
                thresholds = list(prob_threshold_grid) if prob_threshold_grid else [prob_threshold]
                for prob_th in thresholds:
                    fold_metrics: List[BenchmarkFoldMetric] = []
                    for idx, split in enumerate(splits, start=1):
                        a_train, b_train = _parse_iso(split.train_start), _parse_iso(split.train_end)
                        a_test, b_test = _parse_iso(split.test_start), _parse_iso(split.test_end)

                        train_mask = np.array([(t >= a_train and t < b_train) for t in ts], dtype=bool)
                        test_mask = np.array([(t >= a_test and t < b_test) for t in ts], dtype=bool)

                        if int(np.sum(train_mask)) < 100 or int(np.sum(test_mask)) < 30:
                            continue

                        X_train = X_all.loc[train_mask, :]
                        y_train = y_cls_all[train_mask]
                        X_test = X_all.loc[test_mask, :]
                        y_ret_test = y_ret_all[test_mask]

                        # Need both classes to train classifiers.
                        if len(np.unique(y_train)) < 2:
                            continue

                        model = _train_model(model_name, params)
                        model.fit(X_train, y_train)
                        p_up = model.predict_proba(X_test)[:, 1]
                        trades, net_sum, win_rate, mdd = _simulate_from_prob(
                            prob_up=p_up,
                            y_return=y_ret_test,
                            prob_threshold=float(prob_th),
                            fee_percent=fee_percent,
                        )
                        fold_metrics.append(
                            BenchmarkFoldMetric(
                                split_index=idx,
                                trades=trades,
                                net_return_percent=net_sum,
                                win_rate_percent=win_rate,
                                mdd_percent=mdd,
                            )
                        )

                    if not fold_metrics:
                        continue

                    net_list = [f.net_return_percent for f in fold_metrics]
                    win_list = [f.win_rate_percent for f in fold_metrics]
                    mdd_list = [f.mdd_percent for f in fold_metrics]
                    trd_list = [f.trades for f in fold_metrics]

                    mean_net = mean(net_list)
                    std_net = pstdev(net_list) if len(net_list) > 1 else 0.0
                    mean_win = mean(win_list)
                    mean_mdd = mean(mdd_list)
                    mean_trades = mean(trd_list)
                    # Real risk-adjusted objective: Sharpe-like (annualized)
                    # Annualize returns and volatility (assuming hourly data)
                    periods_per_year = 8760.0
                    annualized_return = mean_net * (periods_per_year / (test_days * 24))
                    annualized_vol = std_net * np.sqrt(periods_per_year / (test_days * 24)) if std_net > 0 else 0.01
                    sharpe_annualized = (annualized_return / annualized_vol) if annualized_vol > 0 else 0.0
                    
                    # Objective: Sharpe - penalty for drawdown and instability
                    objective = sharpe_annualized - (0.20 * mean_mdd) - (0.10 * std_net / mean_net if mean_net > 0 else 0)

                    params_with_threshold = dict(params)
                    params_with_threshold["prob_threshold"] = float(prob_th)
                    cand = BenchmarkResult(
                        model_name=model_name,
                        feature_set_name=feature_set_name,
                        params=params_with_threshold,
                        folds=fold_metrics,
                        mean_trades=mean_trades,
                        mean_net_return_percent=mean_net,
                        std_net_return_percent=std_net,
                        mean_win_rate_percent=mean_win,
                        mean_mdd_percent=mean_mdd,
                        objective=objective,
                    )

                    if best_res is None or cand.objective > best_res.objective:
                        best_res = cand

            if best_res is not None:
                results.append(best_res)

    results.sort(key=lambda x: x.objective, reverse=True)
    return results

