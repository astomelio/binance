#!/usr/bin/env python3
"""
Pipeline 100% automatizado: sacar modelo + probarlo.
- Carga datos de DuckDB (decision_features).
- Entrena un LightGBM (parámetros fijos o pocos trials Optuna).
- Registra en MLflow y opcionalmente marca champion.
- Ejecuta backtest en los últimos N días y escribe reporte.
Todo local = 0€ en APIs. Programable con Task Scheduler / cron para que corra solo.
Uso: python scripts/auto_train_eval.py [--trials 0 para solo 1 modelo fijo]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

# Añadir raíz del repo
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("DBT_DUCKDB_PATH", str(REPO_ROOT / "artifacts" / "warehouse" / "crypto.duckdb"))

FEATURE_NAMES = [
    "alpha_microstructure_score", "momentum_score", "basis_bps", "funding_rate_8h",
    "long_short_account_ratio", "buy_sell_ratio", "fear_greed_value", "btc_dominance",
    "fed_funds_rate", "session_overlap_score", "liquidity_event_score",
    "cross_exchange_spread_bps", "cross_exchange_mean_diff_bps", "cross_exchange_bid_ask_bps_mean",
    "bybit_okx_delta_bps", "cross_exchange_score", "dex_cex_basis_bps", "dex_liquidity_usd",
    "dex_volume_24h_usd", "dex_txn_imbalance_24h", "dex_alpha_score",
]


def _parse_iso(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _build_samples_from_rows(rows: list[dict], horizon: str = "1h") -> list[dict]:
    """Construye muestras etiquetadas: y_cls = 1 si fwd_return > 0 else 0."""
    label_col = f"fwd_return_{horizon.replace('h', 'h')}" if "h" in horizon else "fwd_return_4h"
    if label_col not in (rows[0] or {}):
        label_col = "fwd_return_1h"
    out = []
    for r in rows:
        fwd = r.get(label_col)
        if fwd is None:
            continue
        try:
            fwd = float(fwd)
        except (TypeError, ValueError):
            continue
        item = dict(r)
        item["y_return"] = fwd
        item["y_cls"] = 1 if fwd > 0 else 0
        out.append(item)
    return sorted(out, key=lambda x: (x.get("event_time") or "", x.get("symbol") or ""))


def main() -> int:
    parser = argparse.ArgumentParser(description="Entrenar modelo + evaluar (100% local)")
    parser.add_argument("--db", default=None, help="DuckDB path")
    parser.add_argument("--horizon", default="1h", choices=("1h", "4h", "24h"))
    parser.add_argument("--lookback-days", type=int, default=90, help="Días de datos para entrenar")
    parser.add_argument("--test-days", type=int, default=14, help="Días para backtest final")
    parser.add_argument("--trials", type=int, default=0, help="0 = un solo modelo fijo; 5–20 = Optuna rápido")
    parser.add_argument("--register-name", default="quant_alpha_entry_lgbm")
    parser.add_argument("--set-champion", action="store_true", help="Marcar como champion en MLflow")
    parser.add_argument("--mlflow-uri", default=None, help="Default: sqlite:///REPO/artifacts/quant_model/mlflow.db")
    parser.add_argument("--out-report", default="artifacts/quant_model/auto_report.json")
    args = parser.parse_args()

    db_path = args.db or os.environ.get("DBT_DUCKDB_PATH", str(REPO_ROOT / "artifacts" / "warehouse" / "crypto.duckdb"))
    if not Path(db_path).exists():
        print(f"DuckDB no encontrado: {db_path}", file=sys.stderr)
        return 1

    from ai.data.loader import load_decision_features
    from ai.allocation.backtest import run_allocation_backtest
    from ai.allocation.strategies import compute_allocations
    from ai.inference.model_scorer import enrich_rows_with_model

    # 1) Cargar datos (últimos lookback_days)
    end_dt = datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(days=args.lookback_days)
    start_str = start_dt.strftime("%Y-%m-%d")
    end_str = end_dt.strftime("%Y-%m-%d")

    rows = load_decision_features(
        horizon=args.horizon,
        label_not_null=True,
        db_path=db_path,
        start=start_str,
        end=end_str,
    )
    if not rows or len(rows) < 500:
        print(f"Pocas filas ({len(rows)}). Necesitas más datos en DuckDB.", file=sys.stderr)
        return 1

    samples = _build_samples_from_rows(rows, args.horizon)
    if len(samples) < 300:
        print(f"Pocas muestras ({len(samples)}).", file=sys.stderr)
        return 1

    # 2) Entrenar
    X = pd.DataFrame([{f: float(r.get(f, 0) or 0) for f in FEATURE_NAMES} for r in samples], columns=FEATURE_NAMES)
    y = np.array([r["y_cls"] for r in samples], dtype=int)
    ts_all = np.array([_parse_iso(r["event_time"]) for r in samples], dtype=object)
    max_ts = max(ts_all)
    # Train = todo menos últimos test_days
    cutoff = max_ts - timedelta(days=args.test_days)
    train_mask = np.array([t < cutoff for t in ts_all], dtype=bool)
    if train_mask.sum() < 200 or (len(np.unique(y[train_mask])) < 2):
        print("Datos insuficientes o una sola clase en train.", file=sys.stderr)
        return 1

    X_train, y_train = X.loc[train_mask], y[train_mask]
    from lightgbm import LGBMClassifier

    model = LGBMClassifier(
        n_estimators=200,
        learning_rate=0.05,
        num_leaves=31,
        min_child_samples=30,
        subsample=0.8,
        colsample_bytree=0.8,
        reg_lambda=0.1,
        random_state=42,
        verbose=-1,
    )
    model.fit(X_train, y_train)

    # 3) Registrar en MLflow
    import mlflow
    import mlflow.lightgbm
    from mlflow.models import infer_signature
    from mlflow import MlflowClient

    mlflow_uri = args.mlflow_uri or f"sqlite:///{REPO_ROOT / 'artifacts' / 'quant_model' / 'mlflow.db'}"
    mlflow.set_tracking_uri(mlflow_uri)
    mlflow.set_experiment("auto_train_eval")
    Path(REPO_ROOT / "artifacts" / "quant_model").mkdir(parents=True, exist_ok=True)

    model_uri_saved = None
    mv = None
    with mlflow.start_run(run_name="auto_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")):
        mlflow.log_params({"horizon": args.horizon, "lookback_days": args.lookback_days, "test_days": args.test_days})
        sig = infer_signature(X_train.head(50), model.predict_proba(X_train.head(50)))
        model_info = mlflow.lightgbm.log_model(
            lgb_model=model,
            artifact_path="model",
            signature=sig,
            input_example=X_train.head(5),
        )
        mlflow.log_dict({"feature_names": FEATURE_NAMES}, "model_context.json")
        mv = mlflow.register_model(model_info.model_uri, args.register_name)
        if args.set_champion:
            client = MlflowClient()
            client.set_registered_model_alias(args.register_name, "champion", mv.version)
        model_uri_saved = model_info.model_uri

    # 4) Backtest en últimos test_days
    test_start = (max_ts - timedelta(days=args.test_days)).strftime("%Y-%m-%d")
    test_end = max_ts.strftime("%Y-%m-%d")
    rows_test = load_decision_features(
        horizon=args.horizon,
        label_not_null=True,
        db_path=db_path,
        start=test_start,
        end=test_end,
    )
    if not rows_test:
        report = {"model_uri": model_uri_saved, "registered_version": mv.version if mv else None, "backtest": "no_data"}
    else:
        rows_test = enrich_rows_with_model(rows_test, model, feature_names=FEATURE_NAMES, prob_threshold=0.55)
        for r in rows_test:
            r["fed_window"] = r.get("fed_window") or "NORMAL"
        res = run_allocation_backtest(
            rows_test,
            horizon=args.horizon,
            fee_percent=0.04,
            slippage_percent=0.02,
            compute_fn=lambda f, _: compute_allocations(f, prob_threshold=0.55, min_allocation=0.1, max_allocation=0.4, max_exposure=1.0),
        )
        report = {
            "model_uri": model_uri_saved,
            "registered_version": mv.version if mv else None,
            "champion": args.set_champion,
            "backtest": {
                "net_return_percent": res.net_return_percent,
                "trades_count": res.trades_count,
                "total_fees_percent": res.total_fees_percent,
                "period": [test_start, test_end],
            },
        }

    out_path = REPO_ROOT / args.out_report
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("Reporte:", out_path)
    print("Backtest net %:", report.get("backtest", {}).get("net_return_percent"))
    print("Trades:", report.get("backtest", {}).get("trades_count"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
