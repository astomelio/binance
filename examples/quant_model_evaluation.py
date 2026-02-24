"""
Evaluación comparativa de modelos: LightGBM, XGBoost, mean reversion.
Prueba diferentes configuraciones: 1 vs N monedas, distintos feature sets.
Identifica mean reversion y sensibilidad a horarios (US/China).

Usage:
    python examples/quant_model_evaluation.py --dataset data_lake/gold/signals/decision_features_backfill
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

from trading_lib import FeeModel
from trading_lib.timeseries import build_walk_forward_splits, load_jsonl_timeseries


def _parse_iso(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _build_samples(
    rows: List[Dict],
    horizon_steps: int = 4,
    symbols_filter: List[str] | None = None,
) -> List[Dict]:
    """Build labeled samples, optionally filtering by symbol."""
    if symbols_filter:
        rows = [r for r in rows if str(r.get("symbol", "")).upper() in {s.upper() for s in symbols_filter}]
    by_symbol: Dict[str, List[Dict]] = defaultdict(list)
    for r in rows:
        s = str(r.get("symbol", ""))
        if s and r.get("event_time"):
            by_symbol[s].append(r)

    out: List[Dict] = []
    for symbol, srows in by_symbol.items():
        srows.sort(key=lambda x: x["event_time"])
        closes = [float(r.get("futures_last_price", 0) or 0) for r in srows]
        for i, row in enumerate(srows):
            px = closes[i]
            if px <= 0:
                continue
            j = i + horizon_steps
            if j >= len(closes):
                continue
            nxt = closes[j]
            if nxt <= 0:
                continue
            y_return = ((nxt - px) / px) * 100.0
            item = dict(row)
            item["y_return"] = y_return
            item["y_cls"] = 1 if y_return > 0 else 0
            out.append(item)
    out.sort(key=lambda x: x["event_time"])
    return out


def _simulate(
    signal: np.ndarray,
    y_return: np.ndarray,
    fee_percent: float,
) -> Tuple[int, float, float, float]:
    """signal: -1, 0, 1. Returns trades, net_sum, win_rate, mdd."""
    active = signal != 0.0
    if not np.any(active):
        return 0, 0.0, 0.0, 0.0
    net = (signal[active] * y_return[active]) - fee_percent
    trades = int(net.shape[0])
    wins = float(np.sum(net > 0))
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
        if dd > mdd:
            mdd = dd
    return trades, net_sum, win_rate, mdd


# Feature sets for ablation
FEATURE_SETS = {
    "full": [
        "alpha_microstructure_score", "momentum_score", "basis_bps", "funding_rate_8h",
        "long_short_account_ratio", "buy_sell_ratio", "fear_greed_value", "btc_dominance",
        "fed_funds_rate", "session_overlap_score", "liquidity_event_score",
        "cross_exchange_spread_bps", "cross_exchange_mean_diff_bps", "cross_exchange_bid_ask_bps_mean",
        "bybit_okx_delta_bps", "cross_exchange_score", "dex_cex_basis_bps", "dex_liquidity_usd",
        "dex_volume_24h_usd", "dex_txn_imbalance_24h", "dex_alpha_score",
        "spread_bps", "depth_imbalance_score", "microprice", "depth_slope_proxy",
        "order_flow_imbalance", "spread_momentum_bps",
        "sp500_close", "oil_wti_usd", "session_us_open", "session_china_open",
        "earnings_window", "price_zscore_24h", "price_deviation_pct_24h",
    ],
    "mean_reversion": ["price_zscore_24h", "price_deviation_pct_24h", "momentum_score", "basis_bps"],
    "macro_only": ["fear_greed_value", "btc_dominance", "fed_funds_rate", "sp500_close", "oil_wti_usd"],
    "session_only": ["session_overlap_score", "session_us_open", "session_china_open", "earnings_window"],
    "microstructure": [
        "alpha_microstructure_score", "basis_bps", "funding_rate_8h", "spread_bps",
        "depth_imbalance_score", "order_flow_imbalance", "cross_exchange_score", "dex_alpha_score",
    ],
}


def run_mean_reversion_strategy(
    samples: List[Dict],
    feature_names: List[str],
    z_threshold: float = 2.0,
) -> np.ndarray:
    """Mean reversion: short when z-score > threshold, long when z-score < -threshold."""
    X = np.array([[float(r.get(f, 0) or 0) for f in feature_names] for r in samples])
    z_idx = feature_names.index("price_zscore_24h") if "price_zscore_24h" in feature_names else -1
    if z_idx < 0:
        return np.zeros(len(samples))

    z = X[:, z_idx]
    signal = np.zeros(len(samples))
    signal[z > z_threshold] = -1.0
    signal[z < -z_threshold] = 1.0
    return signal


def run_ml_model(
    model_type: str,
    X_train: pd.DataFrame,
    y_train: np.ndarray,
    X_test: pd.DataFrame,
) -> np.ndarray:
    """Train and predict with LightGBM or XGBoost. use_gpu: LightGBM device='gpu', XGBoost device='cuda'."""
    import os
    use_gpu = os.environ.get("USE_GPU", "").strip().lower() in ("1", "true", "yes")
    if model_type == "lightgbm":
        from lightgbm import LGBMClassifier
        kwargs = dict(n_estimators=150, learning_rate=0.05, num_leaves=31, random_state=42, verbose=-1)
        if use_gpu:
            kwargs["device"] = "gpu"
        clf = LGBMClassifier(**kwargs)
    elif model_type == "xgboost":
        try:
            from xgboost import XGBClassifier
            kwargs = dict(n_estimators=150, learning_rate=0.05, max_depth=6, random_state=42, verbosity=0)
            if use_gpu:
                kwargs["tree_method"] = "hist"
                kwargs["device"] = "cuda"
            clf = XGBClassifier(**kwargs)
        except ImportError:
            from lightgbm import LGBMClassifier
            kwargs = dict(n_estimators=150, learning_rate=0.05, num_leaves=31, random_state=42, verbose=-1)
            if use_gpu:
                kwargs["device"] = "gpu"
            clf = LGBMClassifier(**kwargs)
    else:
        raise ValueError(f"Unknown model: {model_type}")

    clf.fit(X_train, y_train)
    prob_up = clf.predict_proba(X_test)[:, 1]
    return prob_up


def evaluate(
    samples: List[Dict],
    feature_set_name: str,
    model_type: str,
    train_days: int,
    test_days: int,
    step_days: int,
    fee_percent: float,
    prob_threshold: float = 0.55,
) -> Dict:
    """Run walk-forward evaluation."""
    feature_names = FEATURE_SETS.get(feature_set_name, FEATURE_SETS["full"])
    sample_keys = set()
    for s in samples[:500]:
        sample_keys.update(k for k, v in s.items() if v is not None and v != "")
    feature_names = [f for f in feature_names if f in sample_keys]
    if not feature_names:
        feature_names = [f for f in FEATURE_SETS["full"] if f in sample_keys]
    if not feature_names:
        feature_names = ["momentum_score", "basis_bps", "fear_greed_value"]

    X_all = pd.DataFrame(
        [{f: float(r.get(f, 0) or 0) for f in feature_names} for r in samples],
        columns=feature_names,
    )
    y_cls = np.array([int(r["y_cls"]) for r in samples])
    y_ret = np.array([float(r["y_return"]) for r in samples])
    ts_all = np.array([_parse_iso(r["event_time"]) for r in samples])
    max_ts = max(ts_all)

    split_rows = [{"event_time": t.isoformat()} for t in ts_all]
    splits = build_walk_forward_splits(
        rows=split_rows,
        train_days=train_days,
        test_days=test_days,
        step_days=step_days,
        embargo_hours=12,
    )

    fold_results = []
    for split in splits:
        a_train, b_train = _parse_iso(split.train_start), _parse_iso(split.train_end)
        a_test, b_test = _parse_iso(split.test_start), _parse_iso(split.test_end)
        train_mask = np.array([(t >= a_train and t < b_train) for t in ts_all])
        test_mask = np.array([(t >= a_test and t < b_test) for t in ts_all])
        if train_mask.sum() < 200 or test_mask.sum() < 50:
            continue

        X_train = X_all.loc[train_mask, feature_names].fillna(0)
        y_train = y_cls[train_mask]
        X_test = X_all.loc[test_mask, feature_names].fillna(0)
        y_ret_test = y_ret[test_mask]

        if model_type == "mean_reversion":
            test_samples = [s for s, m in zip(samples, test_mask) if m]
            signal = run_mean_reversion_strategy(test_samples, feature_names)
        else:
            prob_up = run_ml_model(model_type, X_train, y_train, X_test)
            signal = np.zeros(len(prob_up))
            signal[prob_up >= prob_threshold] = 1.0
            signal[prob_up <= (1.0 - prob_threshold)] = -1.0

        trades, net_sum, win_rate, mdd = _simulate(signal, y_ret_test, fee_percent)
        fold_results.append({"trades": trades, "net_sum": net_sum, "win_rate": win_rate, "mdd": mdd})

    if not fold_results:
        return {"trades": 0, "net_sum": 0.0, "win_rate": 0.0, "mdd": 0.0, "folds": 0}

    return {
        "trades": int(np.mean([f["trades"] for f in fold_results])),
        "net_sum": float(np.mean([f["net_sum"] for f in fold_results])),
        "win_rate": float(np.mean([f["win_rate"] for f in fold_results])),
        "mdd": float(np.mean([f["mdd"] for f in fold_results])),
        "folds": len(fold_results),
    }


def main():
    parser = argparse.ArgumentParser(description="Evaluate model types and configurations")
    parser.add_argument("--dataset", default="data_lake/gold/signals/decision_features_backfill")
    parser.add_argument("--symbols", default="", help="Comma-separated symbols for 1-N test, empty=all")
    parser.add_argument("--train-days", type=int, default=60)
    parser.add_argument("--test-days", type=int, default=14)
    parser.add_argument("--step-days", type=int, default=14)
    parser.add_argument("--output", default="artifacts/quant_model/evaluation_report.json")
    args = parser.parse_args()

    data_glob = args.dataset if "*" in args.dataset else f"{args.dataset}/**/part-*.jsonl"
    rows = load_jsonl_timeseries(data_glob, key_fields=("event_time", "symbol"))
    if len(rows) < 1000:
        raise ValueError(f"Not enough rows: {len(rows)}")

    symbols_filter = [s.strip() for s in args.symbols.split(",") if s.strip()] if args.symbols else None
    samples_all = _build_samples(rows, horizon_steps=4, symbols_filter=None)
    first_symbol = next((str(r.get("symbol", "")).upper() for r in rows if r.get("symbol")), "BTCUSDT")
    samples_1coin = _build_samples(rows, horizon_steps=4, symbols_filter=[first_symbol])
    if symbols_filter:
        samples_1coin = _build_samples(rows, horizon_steps=4, symbols_filter=symbols_filter)

    fee_percent = FeeModel().round_trip_fee_percent("futures", is_maker=True)

    results = []
    configs = [
        ("full", "lightgbm", "all_coins"),
        ("full", "xgboost", "all_coins"),
        ("mean_reversion", "mean_reversion", "all_coins"),
        ("macro_only", "lightgbm", "all_coins"),
        ("session_only", "lightgbm", "all_coins"),
        ("microstructure", "lightgbm", "all_coins"),
        ("full", "lightgbm", "1_coin"),
        ("mean_reversion", "mean_reversion", "1_coin"),
    ]

    samples_by_config = {"all_coins": samples_all, "1_coin": samples_1coin}
    for feature_set, model_type, coin_config in configs:
        samples = samples_by_config.get(coin_config, samples_all)
        if len(samples) < 200:
            continue
        try:
            r = evaluate(
                samples,
                feature_set_name=feature_set,
                model_type=model_type,
                train_days=args.train_days,
                test_days=args.test_days,
                step_days=args.step_days,
                fee_percent=fee_percent,
            )
            results.append({
                "feature_set": feature_set,
                "model_type": model_type,
                "coin_config": coin_config,
                **r,
            })
            print(f"{feature_set} | {model_type} | {coin_config}: net={r['net_sum']:.2f} win={r['win_rate']:.1f}% mdd={r['mdd']:.1f}% folds={r['folds']}")
        except Exception as e:
            print(f"{feature_set} | {model_type} | {coin_config}: ERROR {e}")

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "config": {"dataset": data_glob, "train_days": args.train_days, "test_days": args.test_days},
        "results": results,
    }
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nReport saved -> {out_path}")


if __name__ == "__main__":
    main()
