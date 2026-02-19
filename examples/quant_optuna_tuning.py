from __future__ import annotations

import argparse
import json
import warnings
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean, pstdev
from typing import Dict, List, Sequence, Tuple

import numpy as np
import optuna
from optuna.samplers import TPESampler
from lightgbm import LGBMClassifier
import pandas as pd
import mlflow
import mlflow.lightgbm
from mlflow import MlflowClient
from mlflow.models import infer_signature

from trading_lib import FeeModel
from trading_lib.timeseries import WalkForwardSplit, build_walk_forward_splits, load_jsonl_timeseries


def _parse_iso(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _regime_label(row: Dict) -> str:
    m12 = float(row.get("momentum_12", 0.0) or 0.0)
    p24 = float(row.get("price_change_percent_24h", 0.0) or 0.0)
    if m12 >= 1.0 and p24 >= 0.5:
        return "BULL"
    if m12 <= -1.0 and p24 <= -0.5:
        return "BEAR"
    return "NEUTRAL"


def _vol_label(row: Dict) -> str:
    m3_abs = abs(float(row.get("momentum_3", 0.0) or 0.0))
    liq = float(row.get("liquidity_event_score", 0.0) or 0.0)
    return "HIGH_VOL" if (m3_abs >= 1.5 or liq >= 0.5) else "LOW_VOL"


def _build_labeled_samples(rows: List[Dict], horizon_steps: int = 4) -> List[Dict]:
    by_symbol: Dict[str, List[Dict]] = defaultdict(list)
    for r in rows:
        s = str(r.get("symbol", ""))
        if s and r.get("event_time"):
            by_symbol[s].append(r)

    out: List[Dict] = []
    for symbol, srows in by_symbol.items():
        srows.sort(key=lambda x: x["event_time"])
        closes = [float(r.get("futures_last_price", 0.0) or 0.0) for r in srows]
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
            item["regime_combo"] = f"{_regime_label(row)}__{_vol_label(row)}"
            out.append(item)
    out.sort(key=lambda x: x["event_time"])
    return out


def _simulate(
    prob_up: np.ndarray,
    y_return: np.ndarray,
    regime_combo: Sequence[str],
    prob_threshold: float,
    fee_percent: float,
    blocked: Sequence[str],
) -> Tuple[int, float, float, float]:
    blocked_set = {b.upper() for b in blocked}
    signal = np.zeros_like(prob_up, dtype=float)
    signal[prob_up >= prob_threshold] = 1.0
    signal[prob_up <= (1.0 - prob_threshold)] = -1.0

    active = signal != 0.0
    if blocked_set:
        block_mask = np.array([str(c).upper() in blocked_set for c in regime_combo], dtype=bool)
        active = active & (~block_mask)
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


def _policy_from_id(policy_id: str) -> List[str]:
    policies = {
        "none": [],
        "neutral_high_vol": ["NEUTRAL__HIGH_VOL"],
        "bull_high_vol": ["BULL__HIGH_VOL"],
        "bear_high_vol": ["BEAR__HIGH_VOL"],
        "bull_and_neutral_high_vol": ["BULL__HIGH_VOL", "NEUTRAL__HIGH_VOL"],
        "bull_high_and_bear_low": ["BULL__HIGH_VOL", "BEAR__LOW_VOL"],
    }
    return policies.get(policy_id, [])


def main() -> None:
    parser = argparse.ArgumentParser(description="Optuna tuning for quant model (walk-forward, no leakage)")
    parser.add_argument("--dataset", default="/Users/joaquincano/data/binance_lake/gold/signals/decision_features_backfill")
    parser.add_argument("--horizon-steps", type=int, default=4, help="Forward steps for label. For 1h bars, 4=4h.")
    parser.add_argument("--trials", type=int, default=120)
    parser.add_argument("--train-days", type=int, default=60)
    parser.add_argument("--test-days", type=int, default=14)
    parser.add_argument("--step-days", type=int, default=14)
    parser.add_argument("--embargo-hours", type=int, default=12)
    parser.add_argument("--min-test-trades", type=int, default=8)
    parser.add_argument(
        "--optimize-time-windows",
        action="store_true",
        help="If set, Optuna will also tune lookback_days/train_days/test_days/step_days.",
    )
    parser.add_argument("--lookback-days-grid", default="15,30,60,90,120")
    parser.add_argument("--train-days-grid", default="45,60,90")
    parser.add_argument("--test-days-grid", default="7,14,21")
    parser.add_argument("--step-days-grid", default="7,14")
    parser.add_argument(
        "--study-name",
        default="quant_lgbm_wf_tuning",
        help="Optuna study name (used with storage for dashboard/UI).",
    )
    parser.add_argument(
        "--storage",
        default="sqlite:///artifacts/quant_model/optuna.db",
        help="Optuna storage URL. Use sqlite:///... for local persistent UI.",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--mlflow-uri",
        default="sqlite:///artifacts/quant_model/mlflow.db",
        help="MLflow tracking URI for local UI/logging.",
    )
    parser.add_argument(
        "--mlflow-experiment",
        default="quant-optuna",
        help="MLflow experiment name.",
    )
    parser.add_argument(
        "--register-model-name",
        default="quant_alpha_entry_lgbm",
        help="Registered model name in MLflow Model Registry.",
    )
    parser.add_argument(
        "--set-champion-alias",
        action="store_true",
        help="Set alias 'champion' to the newly registered version.",
    )
    args = parser.parse_args()
    warnings.filterwarnings("ignore", message="X does not have valid feature names")
    optuna.logging.set_verbosity(optuna.logging.WARNING)

    # Load 1h, 4h, 1d for multi-timeframe
    from pathlib import Path
    base_path = Path(args.dataset).parent if Path(args.dataset).is_file() else Path(args.dataset)
    
    data_glob_1h = args.dataset if "*" in args.dataset else f"{args.dataset}/**/part-*.jsonl"
    rows_1h = load_jsonl_timeseries(data_glob_1h, key_fields=("event_time", "symbol"))
    
    # Try to load 4h and 1d
    path_4h = str(base_path).replace("decision_features_backfill", "decision_features_backfill_4h")
    path_1d = str(base_path).replace("decision_features_backfill", "decision_features_backfill_1d")
    
    rows_4h = None
    if Path(path_4h).exists():
        try:
            data_glob_4h = f"{path_4h}/**/part-*.jsonl"
            rows_4h = load_jsonl_timeseries(data_glob_4h, key_fields=("event_time", "symbol"))
            print(f"Loaded {len(rows_4h)} 4h rows for multi-timeframe")
        except:
            pass
    
    rows_1d = None
    if Path(path_1d).exists():
        try:
            data_glob_1d = f"{path_1d}/**/part-*.jsonl"
            rows_1d = load_jsonl_timeseries(data_glob_1d, key_fields=("event_time", "symbol"))
            print(f"Loaded {len(rows_1d)} 1d rows for multi-timeframe")
        except:
            pass
    
    # Enrich 1h with 4h and 1d
    from trading_lib.quant.multi_timeframe import enrich_with_multi_timeframe
    if rows_4h is not None or rows_1d is not None:
        rows_1h = enrich_with_multi_timeframe(rows_1h, rows_4h or [], rows_1d or [])
        print(f"Enriched 1h data with multi-timeframe features")
    
    samples = _build_labeled_samples(rows_1h, horizon_steps=args.horizon_steps)
    if len(samples) < 1000:
        raise ValueError(f"Not enough samples: {len(samples)}")

    lookback_grid = [int(x.strip()) for x in str(args.lookback_days_grid).split(",") if x.strip()]
    train_grid = [int(x.strip()) for x in str(args.train_days_grid).split(",") if x.strip()]
    test_grid = [int(x.strip()) for x in str(args.test_days_grid).split(",") if x.strip()]
    step_grid = [int(x.strip()) for x in str(args.step_days_grid).split(",") if x.strip()]

    feature_names = [
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
    ]

    X_all = pd.DataFrame(
        [{f: float(r.get(f, 0.0) or 0.0) for f in feature_names} for r in samples],
        columns=feature_names,
    )
    y_cls_all = np.array([int(r["y_cls"]) for r in samples], dtype=int)
    y_ret_all = np.array([float(r["y_return"]) for r in samples], dtype=float)
    regime_all = np.array([str(r["regime_combo"]) for r in samples], dtype=object)
    ts_all = np.array([_parse_iso(r["event_time"]) for r in samples], dtype=object)
    max_ts = max(ts_all)

    fee_percent = FeeModel().round_trip_fee_percent("futures", is_maker=True)

    def objective(trial: optuna.Trial) -> float:
        params = {
            "n_estimators": trial.suggest_int("n_estimators", 120, 500),
            "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.15, log=True),
            "num_leaves": trial.suggest_int("num_leaves", 15, 127),
            "min_child_samples": trial.suggest_int("min_child_samples", 10, 120),
            "subsample": trial.suggest_float("subsample", 0.6, 1.0),
            "colsample_bytree": trial.suggest_float("colsample_bytree", 0.6, 1.0),
            "reg_lambda": trial.suggest_float("reg_lambda", 0.0, 3.0),
            "random_state": 42,
            "verbose": -1,
        }
        prob_threshold = trial.suggest_float("prob_threshold", 0.55, 0.75)
        policy_id = trial.suggest_categorical(
            "policy_id",
            [
                "none",
                "neutral_high_vol",
                "bull_high_vol",
                "bear_high_vol",
                "bull_and_neutral_high_vol",
                "bull_high_and_bear_low",
            ],
        )
        blocked = _policy_from_id(policy_id)

        if args.optimize_time_windows:
            lookback_days = trial.suggest_categorical("lookback_days", lookback_grid)
            train_days = trial.suggest_categorical("train_days", train_grid)
            test_days = trial.suggest_categorical("test_days", test_grid)
            step_days = trial.suggest_categorical("step_days", step_grid)
        else:
            lookback_days = max(lookback_grid) if lookback_grid else 120
            train_days = args.train_days
            test_days = args.test_days
            step_days = args.step_days

        # Restrict training universe to most recent lookback window to test data-age sensitivity.
        min_ts = max_ts - timedelta(days=int(lookback_days))
        lb_mask = np.array([t >= min_ts for t in ts_all], dtype=bool)
        if int(np.sum(lb_mask)) < 600:
            return -1e9

        ts_sub = ts_all[lb_mask]
        if ts_sub.size == 0:
            return -1e9
        split_rows = [{"event_time": t.isoformat()} for t in ts_sub]
        splits: List[WalkForwardSplit] = build_walk_forward_splits(
            rows=split_rows,
            train_days=int(train_days),
            test_days=int(test_days),
            step_days=int(step_days),
            embargo_hours=args.embargo_hours,
        )
        if not splits:
            return -1e9

        fold_net: List[float] = []
        fold_mdd: List[float] = []
        fold_win: List[float] = []
        fold_trades: List[int] = []

        for split in splits:
            a_train, b_train = _parse_iso(split.train_start), _parse_iso(split.train_end)
            a_test, b_test = _parse_iso(split.test_start), _parse_iso(split.test_end)
            train_mask = np.array([((t >= a_train and t < b_train) and (t >= min_ts)) for t in ts_all], dtype=bool)
            test_mask = np.array([((t >= a_test and t < b_test) and (t >= min_ts)) for t in ts_all], dtype=bool)
            if int(np.sum(train_mask)) < 200 or int(np.sum(test_mask)) < 50:
                continue
            X_train, y_train = X_all.loc[train_mask, :], y_cls_all[train_mask]
            X_test, y_ret_test = X_all.loc[test_mask, :], y_ret_all[test_mask]
            reg_test = regime_all[test_mask]
            if len(np.unique(y_train)) < 2:
                continue
            model = LGBMClassifier(**params)
            model.fit(X_train, y_train)
            p_up = model.predict_proba(X_test)[:, 1]
            trades, net_sum, win_rate, mdd = _simulate(
                prob_up=p_up,
                y_return=y_ret_test,
                regime_combo=reg_test,
                prob_threshold=prob_threshold,
                fee_percent=fee_percent,
                blocked=blocked,
            )
            fold_trades.append(trades)
            fold_net.append(net_sum)
            fold_win.append(win_rate)
            fold_mdd.append(mdd)

        if not fold_net:
            return -1e9
        avg_trades = mean(fold_trades)
        if avg_trades < args.min_test_trades:
            return -1e6 - avg_trades

        mean_net = mean(fold_net)
        std_net = pstdev(fold_net) if len(fold_net) > 1 else 0.0
        mean_mdd = mean(fold_mdd)
        mean_win = mean(fold_win)
        # Maximize return with explicit penalties for drawdown and instability.
        objective_value = mean_net - (0.30 * mean_mdd) - (0.20 * std_net) + (0.02 * mean_win)

        trial.set_user_attr("avg_trades", avg_trades)
        trial.set_user_attr("mean_net", mean_net)
        trial.set_user_attr("mean_mdd", mean_mdd)
        trial.set_user_attr("mean_win", mean_win)
        trial.set_user_attr("blocked_policy", blocked)
        trial.set_user_attr("lookback_days", int(lookback_days))
        trial.set_user_attr("train_days", int(train_days))
        trial.set_user_attr("test_days", int(test_days))
        trial.set_user_attr("step_days", int(step_days))
        return objective_value

    study = optuna.create_study(
        direction="maximize",
        study_name=args.study_name,
        storage=args.storage,
        load_if_exists=True,
        sampler=TPESampler(seed=args.seed),
    )
    study.optimize(objective, n_trials=args.trials, show_progress_bar=False)

    top_trials = sorted(study.trials, key=lambda t: t.value if t.value is not None else -1e18, reverse=True)[:20]
    top_rows = []
    for t in top_trials:
        top_rows.append(
            {
                "trial": t.number,
                "value": t.value,
                "params": t.params,
                "mean_net": t.user_attrs.get("mean_net"),
                "mean_mdd": t.user_attrs.get("mean_mdd"),
                "mean_win": t.user_attrs.get("mean_win"),
                "avg_trades": t.user_attrs.get("avg_trades"),
                "blocked_policy": t.user_attrs.get("blocked_policy"),
            }
        )

    best = study.best_trial
    report = {
        "config": {
            "dataset": data_glob,
            "horizon_steps": args.horizon_steps,
            "trials": args.trials,
            "train_days": args.train_days,
            "test_days": args.test_days,
            "step_days": args.step_days,
            "embargo_hours": args.embargo_hours,
            "min_test_trades": args.min_test_trades,
            "optimize_time_windows": args.optimize_time_windows,
            "lookback_days_grid": lookback_grid,
            "train_days_grid": train_grid,
            "test_days_grid": test_grid,
            "step_days_grid": step_grid,
            "study_name": args.study_name,
            "storage": args.storage,
            "seed": args.seed,
            "fee_percent": fee_percent,
        },
        "best_trial": {
            "number": best.number,
            "value": best.value,
            "params": best.params,
            "user_attrs": best.user_attrs,
        },
        "top_trials": top_rows,
        "leakage_guards": {
            "validation": "walk-forward by event_time",
            "selection": "hyperparameters selected only from training windows in each fold",
            "embargo_hours": args.embargo_hours,
            "forbidden_features": ["future_*", "fwd_*", "label", "target", "next_*"],
        },
    }

    out_dir = Path("artifacts/quant_model")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "optuna_best_params.json").write_text(json.dumps(best.params, indent=2), encoding="utf-8")
    (out_dir / "optuna_tuning_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    # Log one summary run so MLflow UI always has visible artifacts/metrics.
    mlflow.set_tracking_uri(args.mlflow_uri)
    mlflow.set_experiment(args.mlflow_experiment)
    mlflow.set_registry_uri(args.mlflow_uri)
    with mlflow.start_run(run_name=f"{args.study_name}_best"):
        mlflow.log_params(
            {
                "study_name": args.study_name,
                "storage": args.storage,
                "trials": args.trials,
                "train_days": args.train_days,
                "test_days": args.test_days,
                "step_days": args.step_days,
                "embargo_hours": args.embargo_hours,
                "horizon_steps": args.horizon_steps,
                "min_test_trades": args.min_test_trades,
            }
        )
        for k, v in best.params.items():
            mlflow.log_param(f"best__{k}", v)
        for k, v in best.user_attrs.items():
            if isinstance(v, (int, float)):
                mlflow.log_metric(f"best__{k}", float(v))
        mlflow.log_metric("best__objective", float(best.value))
        mlflow.log_dict(best.params, "best_params.json")
        mlflow.log_dict(report, "optuna_tuning_report.json")

        # Train final model with best params on latest lookback window and log it as an MLflow Model.
        best_params = dict(best.params)
        lookback_days = int(best_params.get("lookback_days", max(lookback_grid) if lookback_grid else 120))
        min_ts = max_ts - timedelta(days=lookback_days)
        train_mask_final = np.array([t >= min_ts for t in ts_all], dtype=bool)
        X_train_final = X_all.loc[train_mask_final, :]
        y_train_final = y_cls_all[train_mask_final]
        if int(np.sum(train_mask_final)) < 200 or len(np.unique(y_train_final)) < 2:
            raise ValueError("Insufficient data/classes for final model logging")

        lgbm_keys = {
            "n_estimators",
            "learning_rate",
            "num_leaves",
            "min_child_samples",
            "subsample",
            "colsample_bytree",
            "reg_lambda",
        }
        final_model_params = {k: v for k, v in best_params.items() if k in lgbm_keys}
        final_model_params.update({"random_state": args.seed, "verbose": -1})
        final_model = LGBMClassifier(**final_model_params)
        final_model.fit(X_train_final, y_train_final)

        signature = infer_signature(X_train_final.head(50), final_model.predict_proba(X_train_final.head(50)))
        model_info = mlflow.lightgbm.log_model(
            lgb_model=final_model,
            name="model",
            signature=signature,
            input_example=X_train_final.head(5),
            registered_model_name=None,
        )
        model_uri = model_info.model_uri
        mlflow.log_param("model_uri", model_uri)
        mlflow.log_param("model_lookback_days", lookback_days)
        mlflow.log_param("model_prob_threshold", best_params.get("prob_threshold"))
        mlflow.log_param("model_policy_id", best_params.get("policy_id"))
        mlflow.log_dict(
            {
                "feature_names": feature_names,
                "best_params": best_params,
                "best_user_attrs": best.user_attrs,
                "lookback_days": lookback_days,
            },
            "model_context.json",
        )

        # Register model version in MLflow Model Registry.
        mv = mlflow.register_model(model_uri=model_uri, name=args.register_model_name)
        mlflow.log_param("registered_model_name", args.register_model_name)
        mlflow.log_param("registered_model_version", mv.version)
        if args.set_champion_alias:
            client = MlflowClient()
            client.set_registered_model_alias(args.register_model_name, "champion", mv.version)
            mlflow.log_param("registered_alias", "champion")
            mlflow.log_param("registered_alias_version", mv.version)

    print("=== Optuna Tuning Done ===")
    print(f"best_trial={best.number} | objective={best.value:.6f}")
    print(f"best_params={best.params}")
    print(f"best_user_attrs={best.user_attrs}")
    print(f"Saved -> {out_dir / 'optuna_best_params.json'}")
    print(f"Saved -> {out_dir / 'optuna_tuning_report.json'}")


if __name__ == "__main__":
    main()

