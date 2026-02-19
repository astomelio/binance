from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List

import mlflow

from trading_lib import FeeModel, StrategySpec, compute_model_allocations, load_jsonl_timeseries
from trading_lib.quant import EntryMetaModel, predict_entry_probability
from trading_lib.planner.engine import _run_rows


def _parse_iso(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _score_row(row: Dict, weights: Dict[str, float]) -> float:
    score = 0.0
    for key, weight in weights.items():
        score += float(weight) * float(row.get(key, 0.0) or 0.0)
    return score


def _enrich_with_model_scores(rows: List[Dict], weights: Dict[str, float]) -> List[Dict]:
    out: List[Dict] = []
    for row in rows:
        r = dict(row)
        score = _score_row(r, weights)
        # Reuse planner allocation engine via alpha_score field.
        r["model_score"] = score
        r["alpha_score"] = score
        out.append(r)
    return out


def _load_entry_meta_model(path: str) -> EntryMetaModel:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return EntryMetaModel(
        feature_names=list(payload.get("feature_names", [])),
        means={k: float(v) for k, v in payload.get("means", {}).items()},
        stds={k: float(v) for k, v in payload.get("stds", {}).items()},
        weights={k: float(v) for k, v in payload.get("weights", {}).items()},
        bias=float(payload.get("bias", 0.0)),
        prob_threshold=float(payload.get("prob_threshold", 0.55)),
    )


def _apply_entry_meta_gate(
    rows: List[Dict],
    meta_model: EntryMetaModel | None,
    prob_threshold: float | None,
    weighting_mode: str,
    min_weight: float,
) -> tuple[List[Dict], Dict]:
    if meta_model is None:
        return rows, {}
    th = prob_threshold if prob_threshold is not None else meta_model.prob_threshold
    out: List[Dict] = []
    probs: List[float] = []
    gated = 0
    for row in rows:
        r = dict(row)
        prob = predict_entry_probability(r, meta_model)
        probs.append(prob)
        r["entry_probability"] = prob
        if prob < th:
            r["alpha_score"] = 0.0
            gated += 1
            r["entry_weight"] = 0.0
        else:
            # confidence factor in [0,1] beyond threshold
            denom = max(1e-9, 1.0 - th)
            conf = max(0.0, min(1.0, (prob - th) / denom))
            if weighting_mode == "off":
                base = 1.0
            elif weighting_mode == "squared":
                base = conf * conf
            else:
                base = conf
            w = min_weight + ((1.0 - min_weight) * base)
            r["entry_weight"] = w
            r["alpha_score"] = float(r.get("alpha_score", 0.0) or 0.0) * w
        out.append(r)
    stats = {
        "threshold": th,
        "rows": len(rows),
        "gated_rows": gated,
        "gated_rate_percent": (gated / len(rows) * 100.0) if rows else 0.0,
        "prob_min": min(probs) if probs else 0.0,
        "prob_max": max(probs) if probs else 0.0,
        "prob_mean": (sum(probs) / len(probs)) if probs else 0.0,
    }
    return out, stats


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
    if m3_abs >= 1.5 or liq >= 0.5:
        return "HIGH_VOL"
    return "LOW_VOL"


def _apply_regime_policy(rows: List[Dict], blocked_combos: List[str]) -> tuple[List[Dict], Dict]:
    blocked_set = {x.strip().upper() for x in blocked_combos if x.strip()}
    if not blocked_set:
        return rows, {}
    out: List[Dict] = []
    blocked_rows = 0
    combo_counts: Dict[str, int] = {}
    for row in rows:
        r = dict(row)
        regime = _regime_label(r)
        vol = _vol_label(r)
        combo = f"{regime}__{vol}"
        r["regime_label"] = regime
        r["volatility_label"] = vol
        r["regime_combo"] = combo
        if combo.upper() in blocked_set:
            r["alpha_score"] = 0.0
            blocked_rows += 1
            combo_counts[combo] = combo_counts.get(combo, 0) + 1
        out.append(r)
    stats = {
        "blocked_combos": sorted(list(blocked_set)),
        "blocked_rows": blocked_rows,
        "blocked_rate_percent": (blocked_rows / len(rows) * 100.0) if rows else 0.0,
        "blocked_combo_counts": combo_counts,
    }
    return out, stats


def _build_rebalance_orders(rows: List[Dict], spec: StrategySpec) -> List[Dict]:
    rows_by_time: Dict[str, List[Dict]] = {}
    for row in rows:
        ts = row.get("event_time", "")
        if not ts:
            continue
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
                }
            )

        prev_alloc = target_alloc
        prev_side = target_side

    return orders


def main() -> None:
    parser = argparse.ArgumentParser(description="Run OOS inference and backtest using trained quant model artifact")
    parser.add_argument(
        "--dataset",
        default="/Users/joaquincano/data/binance_lake/gold/signals/decision_features_backfill",
        help="Path to decision features directory or glob",
    )
    parser.add_argument(
        "--model-artifact",
        default="artifacts/quant_model/latest_walkforward_model.json",
        help="Path to quant model artifact JSON",
    )
    parser.add_argument("--oos-days", type=int, default=14, help="Out-of-sample holdout length in days")
    parser.add_argument(
        "--score-threshold",
        type=float,
        default=None,
        help="Optional override for absolute model score threshold used to open long/short.",
    )
    parser.add_argument("--min-open-interest", type=float, default=0.0)
    parser.add_argument("--min-quote-volume-24h", type=float, default=0.0)
    parser.add_argument("--max-gross-exposure-pct", type=float, default=1.0)
    parser.add_argument("--max-symbol-pct", type=float, default=0.4)
    parser.add_argument(
        "--entry-meta-model",
        default="",
        help="Optional path to entry meta-model artifact. If provided, rows are gated by P(win).",
    )
    parser.add_argument(
        "--entry-prob-threshold",
        type=float,
        default=None,
        help="Optional override probability threshold for entry gate.",
    )
    parser.add_argument(
        "--entry-weighting",
        choices=["off", "linear", "squared"],
        default="linear",
        help="How to scale alpha_score above entry probability threshold.",
    )
    parser.add_argument(
        "--entry-min-weight",
        type=float,
        default=0.4,
        help="Minimum alpha weight when entry meta gate is active (0..1).",
    )
    parser.add_argument(
        "--block-regime-combos",
        default="NEUTRAL__HIGH_VOL",
        help="Comma separated regime combos to hard-block (set alpha_score=0), e.g. NEUTRAL__HIGH_VOL",
    )
    parser.add_argument(
        "--allow-unknown-fed-window",
        action="store_true",
        help="Treat UNKNOWN fed_window as NORMAL to avoid blocking trades on missing macro labels.",
    )
    parser.add_argument(
        "--allow-trading-in-event-window",
        action="store_true",
        help="If set, do not block PRE_EVENT/POST_EVENT windows during allocation.",
    )
    parser.add_argument("--mlflow-uri", default="sqlite:///artifacts/quant_model/mlflow.db")
    parser.add_argument("--mlflow-experiment", default="quant-oos")
    args = parser.parse_args()

    data_glob = args.dataset if "*" in args.dataset else f"{args.dataset}/**/part-*.jsonl"
    rows = load_jsonl_timeseries(data_glob, key_fields=("event_time", "symbol"))
    if not rows:
        raise ValueError(f"No rows found for dataset: {data_glob}")

    artifact = json.loads(Path(args.model_artifact).read_text(encoding="utf-8"))
    weights = artifact.get("weights", {})
    threshold = float(artifact.get("threshold", 0.4))
    if args.score_threshold is not None:
        threshold = float(args.score_threshold)
    if not weights:
        raise ValueError(f"Model artifact has no weights: {args.model_artifact}")

    model_rows = _enrich_with_model_scores(rows, weights)
    meta_model = _load_entry_meta_model(args.entry_meta_model) if args.entry_meta_model else None
    model_rows, entry_meta_stats = _apply_entry_meta_gate(
        model_rows,
        meta_model,
        args.entry_prob_threshold,
        args.entry_weighting,
        max(0.0, min(1.0, args.entry_min_weight)),
    )
    model_rows = _normalize_fed_window(model_rows, allow_unknown_as_normal=args.allow_unknown_fed_window)
    blocked_combos = [x for x in str(args.block_regime_combos).split(",") if x.strip()]
    model_rows, regime_policy_stats = _apply_regime_policy(model_rows, blocked_combos)

    max_ts = _parse_iso(model_rows[-1]["event_time"])
    cutoff = max_ts - timedelta(days=args.oos_days)
    oos_rows = [r for r in model_rows if _parse_iso(r["event_time"]) >= cutoff]
    if not oos_rows:
        raise ValueError("No rows selected for OOS. Reduce --oos-days or add more data.")

    spec = StrategySpec(
        name="quant_artifact_oos",
        long_score_threshold=threshold,
        short_score_threshold=-threshold,
        min_open_interest=args.min_open_interest,
        min_quote_volume_24h=args.min_quote_volume_24h,
        allow_trading_in_event_window=args.allow_trading_in_event_window,
        max_gross_exposure_pct=args.max_gross_exposure_pct,
        max_symbol_pct=args.max_symbol_pct,
    )

    fee_model = FeeModel()
    result, trades = _run_rows(oos_rows, spec, fee_model)
    orders = _build_rebalance_orders(oos_rows, spec)

    out_dir = Path("artifacts/quant_model")
    out_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "model_artifact": args.model_artifact,
        "dataset": data_glob,
        "oos_days": args.oos_days,
        "oos_rows": len(oos_rows),
        "threshold": threshold,
        "entry_meta_model": args.entry_meta_model or None,
        "entry_prob_threshold": (
            args.entry_prob_threshold if args.entry_prob_threshold is not None else (meta_model.prob_threshold if meta_model else None)
        ),
        "entry_weighting": args.entry_weighting,
        "entry_min_weight": args.entry_min_weight,
        "entry_meta_stats": entry_meta_stats,
        "regime_policy_stats": regime_policy_stats,
        "weights": weights,
        "metrics": asdict(result),
        "trades": [asdict(t) for t in trades],
        "orders_count": len(orders),
        "orders_file": str(out_dir / "oos_orders.jsonl"),
    }
    report_path = out_dir / "oos_report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    orders_path = out_dir / "oos_orders.jsonl"
    with orders_path.open("w", encoding="utf-8") as f:
        for order in orders:
            f.write(json.dumps(order) + "\n")

    mlflow.set_tracking_uri(args.mlflow_uri)
    mlflow.set_experiment(args.mlflow_experiment)
    with mlflow.start_run(run_name="quant_oos_run"):
        mlflow.log_params(
            {
                "dataset": data_glob,
                "model_artifact": args.model_artifact,
                "oos_days": args.oos_days,
                "score_threshold": threshold,
                "entry_meta_model": args.entry_meta_model or "none",
                "entry_prob_threshold": report.get("entry_prob_threshold"),
                "entry_weighting": args.entry_weighting,
                "entry_min_weight": args.entry_min_weight,
                "block_regime_combos": args.block_regime_combos,
                "allow_unknown_fed_window": args.allow_unknown_fed_window,
            }
        )
        metrics = report["metrics"]
        mlflow.log_metric("oos_trades", float(metrics.get("trades", 0)))
        mlflow.log_metric("oos_net_return_percent", float(metrics.get("net_return_percent", 0.0)))
        mlflow.log_metric("oos_win_rate_percent", float(metrics.get("win_rate", 0.0)))
        mlflow.log_metric("oos_mdd_percent", float(metrics.get("max_drawdown_percent", 0.0)))
        mlflow.log_metric("oos_turnover_percent", float(metrics.get("turnover_percent", 0.0)))
        mlflow.log_metric("orders_count", float(report.get("orders_count", 0)))
        mlflow.log_dict(report, "oos_report.json")

    print(
        f"OOS done | rows={len(oos_rows)} | trades={result.trades} | "
        f"net={result.net_return_percent:.4f}% | win={result.win_rate:.2f}% | "
        f"mdd={result.max_drawdown_percent:.4f}% | orders={len(orders)}"
    )
    print(f"Report: {report_path}")
    print(f"Orders: {orders_path}")


if __name__ == "__main__":
    main()

