from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List

import mlflow
import numpy as np
import pandas as pd

from trading_lib import FeeModel, StrategySpec, compute_model_allocations, load_jsonl_timeseries
from trading_lib.planner.engine import _run_rows


def _parse_iso(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _normalize_fed_window(rows: List[Dict], allow_unknown_as_normal: bool) -> List[Dict]:
    if not allow_unknown_as_normal:
        return rows
    out: List[Dict] = []
    for row in rows:
        r = dict(row)
        if r.get("fed_window") in {"", None, "UNKNOWN"}:
            r["fed_window"] = "NORMAL"
        out.append(r)
    return out


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


def _apply_regime_policy(rows: List[Dict], blocked_combos: List[str]) -> List[Dict]:
    blocked_set = {x.strip().upper() for x in blocked_combos if x.strip()}
    if not blocked_set:
        return rows
    out: List[Dict] = []
    for row in rows:
        r = dict(row)
        combo = f"{_regime_label(r)}__{_vol_label(r)}"
        if combo.upper() in blocked_set:
            r["alpha_score"] = 0.0
        out.append(r)
    return out


def _build_orders(rows: List[Dict], spec: StrategySpec) -> List[Dict]:
    rows_by_time: Dict[str, List[Dict]] = {}
    for row in rows:
        ts = row.get("event_time", "")
        if ts:
            rows_by_time.setdefault(ts, []).append(row)

    prev_alloc: Dict[str, float] = {}
    prev_side: Dict[str, str] = {}
    orders: List[Dict] = []

    for ts in sorted(rows_by_time.keys()):
        snapshot = rows_by_time[ts]
        row_by_symbol = {r.get("symbol"): r for r in snapshot if r.get("symbol")}
        target = compute_model_allocations(
            snapshot_rows=snapshot,
            spec=spec,
            max_gross_exposure_pct=spec.max_gross_exposure_pct,
            max_symbol_pct=spec.max_symbol_pct,
        )
        target_alloc = {a.symbol: a.allocation_pct for a in target}
        target_side = {a.symbol: a.side for a in target}

        symbols = sorted(set(prev_alloc.keys()) | set(target_alloc.keys()))
        for symbol in symbols:
            old_alloc = prev_alloc.get(symbol, 0.0)
            new_alloc = target_alloc.get(symbol, 0.0)
            old_side = prev_side.get(symbol, "")
            new_side = target_side.get(symbol, "")
            if abs(new_alloc - old_alloc) < 1e-9 and new_side == old_side:
                continue
            action = "REBALANCE"
            if old_alloc == 0 and new_alloc > 0:
                action = "OPEN"
            elif old_alloc > 0 and new_alloc == 0:
                action = "CLOSE"
            elif old_alloc > 0 and new_alloc > 0 and old_side != new_side:
                action = "FLIP"
            row = row_by_symbol.get(symbol, {})
            orders.append(
                {
                    "event_time": ts,
                    "symbol": symbol,
                    "action": action,
                    "side": new_side or old_side,
                    "from_allocation_pct": round(old_alloc, 6),
                    "to_allocation_pct": round(new_alloc, 6),
                    "price": float(row.get("futures_last_price", 0.0) or 0.0),
                    "model_score": round(float(row.get("model_score", 0.0) or 0.0), 6),
                    "entry_probability": round(float(row.get("entry_probability", 0.5) or 0.5), 6),
                }
            )
        prev_alloc = target_alloc
        prev_side = target_side

    return orders


def main() -> None:
    parser = argparse.ArgumentParser(description="Run OOS using MLflow registered champion model")
    parser.add_argument("--dataset", default="/Users/joaquincano/data/binance_lake/gold/signals/decision_features_backfill")
    parser.add_argument("--model-uri", default="models:/quant_alpha_entry_lgbm@champion")
    parser.add_argument("--mlflow-uri", default="sqlite:///artifacts/quant_model/mlflow.db")
    parser.add_argument("--oos-days", type=int, default=14)
    parser.add_argument("--prob-threshold", type=float, default=0.7, help="Long/short activation threshold on p(up).")
    parser.add_argument("--score-threshold", type=float, default=0.25, help="Threshold over transformed score in [-1,1].")
    parser.add_argument("--allow-unknown-fed-window", action="store_true")
    parser.add_argument("--block-regime-combos", default="NEUTRAL__HIGH_VOL")
    parser.add_argument("--max-gross-exposure-pct", type=float, default=1.0)
    parser.add_argument("--max-symbol-pct", type=float, default=0.4)
    args = parser.parse_args()

    data_glob = args.dataset if "*" in args.dataset else f"{args.dataset}/**/part-*.jsonl"
    rows = load_jsonl_timeseries(data_glob, key_fields=("event_time", "symbol"))
    if not rows:
        raise ValueError(f"No rows found for dataset: {data_glob}")

    feature_names = [
        "alpha_microstructure_score",
        "momentum_score",
        "basis_bps",
        "funding_rate_8h",
        "long_short_account_ratio",
        "buy_sell_ratio",
        "fear_greed_value",
        "btc_dominance",
        "fed_funds_rate",
        "session_overlap_score",
        "liquidity_event_score",
    ]

    mlflow.set_tracking_uri(args.mlflow_uri)
    model = mlflow.lightgbm.load_model(args.model_uri)

    X = pd.DataFrame([{k: float(r.get(k, 0.0) or 0.0) for k in feature_names} for r in rows], columns=feature_names)
    p_up = model.predict_proba(X)[:, 1]
    # map to [-1,1] for compatibility with current allocation engine.
    score = (2.0 * p_up) - 1.0

    enriched: List[Dict] = []
    for i, row in enumerate(rows):
        r = dict(row)
        r["entry_probability"] = float(p_up[i])
        s = float(score[i])
        # Convert probability gating into score gating.
        if p_up[i] >= args.prob_threshold:
            r["alpha_score"] = s
        elif p_up[i] <= (1.0 - args.prob_threshold):
            r["alpha_score"] = s
        else:
            r["alpha_score"] = 0.0
        r["model_score"] = s
        enriched.append(r)

    enriched = _normalize_fed_window(enriched, allow_unknown_as_normal=args.allow_unknown_fed_window)
    blocked = [x for x in str(args.block_regime_combos).split(",") if x.strip()]
    enriched = _apply_regime_policy(enriched, blocked)

    max_ts = _parse_iso(enriched[-1]["event_time"])
    cutoff = max_ts - timedelta(days=args.oos_days)
    oos_rows = [r for r in enriched if _parse_iso(r["event_time"]) >= cutoff]
    if not oos_rows:
        raise ValueError("No OOS rows found")

    spec = StrategySpec(
        name="mlflow_champion_oos",
        long_score_threshold=float(args.score_threshold),
        short_score_threshold=-float(args.score_threshold),
        allow_trading_in_event_window=False,
        min_open_interest=0.0,
        min_quote_volume_24h=0.0,
        max_gross_exposure_pct=float(args.max_gross_exposure_pct),
        max_symbol_pct=float(args.max_symbol_pct),
    )

    fee_model = FeeModel()
    result, trades = _run_rows(oos_rows, spec, fee_model)
    orders = _build_orders(oos_rows, spec)

    out_dir = Path("artifacts/quant_model")
    out_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "model_uri": args.model_uri,
        "dataset": data_glob,
        "oos_days": args.oos_days,
        "prob_threshold": args.prob_threshold,
        "score_threshold": args.score_threshold,
        "blocked_regime_combos": blocked,
        "metrics": asdict(result),
        "orders_count": len(orders),
        "trades": [asdict(t) for t in trades],
    }
    report_path = out_dir / "oos_report_champion.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    orders_path = out_dir / "oos_orders_champion.jsonl"
    with orders_path.open("w", encoding="utf-8") as f:
        for o in orders:
            f.write(json.dumps(o) + "\n")

    print(
        f"Champion OOS | rows={len(oos_rows)} | trades={result.trades} | "
        f"net={result.net_return_percent:.4f}% | win={result.win_rate:.2f}% | "
        f"mdd={result.max_drawdown_percent:.4f}% | orders={len(orders)}"
    )
    print(f"Report: {report_path}")
    print(f"Orders: {orders_path}")


if __name__ == "__main__":
    main()

