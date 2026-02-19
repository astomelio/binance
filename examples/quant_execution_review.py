from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Tuple


def _read_jsonl(path: Path) -> List[Dict]:
    if not path.exists():
        return []
    rows: List[Dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def _pct(n: float, d: float) -> float:
    return (n / d * 100.0) if d else 0.0


def _build_tuning_hints(skip_reasons: Counter, total_skips: int) -> List[str]:
    hints: List[str] = []
    if total_skips <= 0:
        return ["No skip pressure detected; keep controls and validate longer horizon."]

    daily_limit_pct = _pct(skip_reasons.get("daily_notional_limit", 0), total_skips)
    small_change_pct = _pct(skip_reasons.get("small_allocation_change", 0), total_skips)
    price_diff_pct = _pct(skip_reasons.get("price_diff_guard", 0), total_skips)

    if daily_limit_pct >= 35:
        hints.append(
            "High skip by daily notional limit: increase --max-daily-notional-usd (e.g. 300->450) or reduce signal frequency."
        )
    if small_change_pct >= 20:
        hints.append(
            "High skip by small allocation change: decrease --min-allocation-change-pct (e.g. 0.02->0.01) for finer rebalances."
        )
    if price_diff_pct >= 20:
        hints.append(
            "High skip by price_diff_guard: in replay use --paper-fill-source file; in live tune --max-price-diff-bps cautiously."
        )
    if not hints:
        hints.append("Skips are balanced across controls; keep limits and gather more history before tuning.")
    return hints


def _bucket_abs_score(score: float) -> str:
    x = abs(score)
    if x < 0.15:
        return "<0.15"
    if x < 0.25:
        return "0.15-0.25"
    if x < 0.40:
        return "0.25-0.40"
    return ">=0.40"


def _build_modelability_dataset(orders: List[Dict], trades: List[Dict]) -> Tuple[List[Dict], Dict]:
    # Key by model entry identity.
    trade_by_key: Dict[Tuple[str, str, str], Dict] = {}
    for t in trades:
        key = (str(t.get("symbol", "")), str(t.get("entry_time", "")), str(t.get("side", "")))
        trade_by_key[key] = t

    rows: List[Dict] = []
    for o in orders:
        action = str(o.get("action", "")).upper()
        if action not in {"OPEN", "FLIP"}:
            continue
        symbol = str(o.get("symbol", ""))
        entry_time = str(o.get("event_time", ""))
        side = str(o.get("side", ""))
        key = (symbol, entry_time, side)
        trade = trade_by_key.get(key)
        if not trade:
            continue

        net = float(trade.get("net_pnl_percent", 0.0) or 0.0)
        weighted = float(trade.get("weighted_net_pnl_percent", 0.0) or 0.0)
        score = float(o.get("model_score", 0.0) or 0.0)

        rows.append(
            {
                "event_time": entry_time,
                "symbol": symbol,
                "side": side,
                "action": action,
                "model_score": score,
                "score_abs": abs(score),
                "from_allocation_pct": float(o.get("from_allocation_pct", 0.0) or 0.0),
                "to_allocation_pct": float(o.get("to_allocation_pct", 0.0) or 0.0),
                "net_pnl_percent": net,
                "weighted_net_pnl_percent": weighted,
                "entry_label": 1 if net > 0 else 0,
            }
        )

    by_bucket: Dict[str, List[Dict]] = defaultdict(list)
    for row in rows:
        by_bucket[_bucket_abs_score(row["model_score"])].append(row)

    bucket_metrics = {}
    for bucket, bucket_rows in by_bucket.items():
        wins = sum(r["entry_label"] for r in bucket_rows)
        bucket_metrics[bucket] = {
            "samples": len(bucket_rows),
            "hit_rate_percent": round(_pct(wins, len(bucket_rows)), 2),
            "avg_net_pnl_percent": round(sum(r["net_pnl_percent"] for r in bucket_rows) / len(bucket_rows), 5),
        }

    # Threshold sweep for a modelable "entry gate".
    thresholds = [0.15, 0.20, 0.25, 0.30, 0.35, 0.40]
    threshold_eval = []
    for th in thresholds:
        selected = [r for r in rows if abs(r["model_score"]) >= th]
        if not selected:
            continue
        wins = sum(r["entry_label"] for r in selected)
        threshold_eval.append(
            {
                "score_abs_threshold": th,
                "samples": len(selected),
                "hit_rate_percent": round(_pct(wins, len(selected)), 2),
                "avg_net_pnl_percent": round(sum(r["net_pnl_percent"] for r in selected) / len(selected), 5),
                "avg_weighted_net_pnl_percent": round(
                    sum(r["weighted_net_pnl_percent"] for r in selected) / len(selected), 5
                ),
            }
        )

    best_threshold = None
    if threshold_eval:
        best_threshold = max(threshold_eval, key=lambda x: (x["avg_weighted_net_pnl_percent"], x["hit_rate_percent"]))

    summary = {
        "samples": len(rows),
        "hit_rate_percent": round(_pct(sum(r["entry_label"] for r in rows), len(rows)), 2) if rows else 0.0,
        "avg_net_pnl_percent": round(sum(r["net_pnl_percent"] for r in rows) / len(rows), 5) if rows else 0.0,
        "bucket_metrics": bucket_metrics,
        "threshold_evaluation": threshold_eval,
        "recommended_score_abs_threshold": best_threshold,
    }
    return rows, summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Review execution quality and create modelability dataset")
    parser.add_argument("--orders-file", default="artifacts/quant_model/oos_orders.jsonl")
    parser.add_argument("--execution-log", default="artifacts/quant_model/execution_log.jsonl")
    parser.add_argument("--execution-report", default="artifacts/quant_model/execution_report.json")
    parser.add_argument("--oos-report", default="artifacts/quant_model/oos_report.json")
    args = parser.parse_args()

    orders_path = Path(args.orders_file)
    exec_log_path = Path(args.execution_log)
    exec_report_path = Path(args.execution_report)
    oos_report_path = Path(args.oos_report)

    orders = _read_jsonl(orders_path)
    exec_rows = _read_jsonl(exec_log_path)
    exec_report = json.loads(exec_report_path.read_text(encoding="utf-8")) if exec_report_path.exists() else {}
    oos_report = json.loads(oos_report_path.read_text(encoding="utf-8")) if oos_report_path.exists() else {}
    trades = oos_report.get("trades", [])

    status = Counter(str(r.get("status", "")) for r in exec_rows)
    skip_reasons = Counter(str(r.get("reason", "")) for r in exec_rows if str(r.get("status")) != "EXECUTED")
    symbol_exec_count = Counter(str(r.get("symbol", "")) for r in exec_rows if str(r.get("status")) == "EXECUTED")
    symbol_notional = defaultdict(float)
    for r in exec_rows:
        if str(r.get("status")) == "EXECUTED":
            symbol_notional[str(r.get("symbol", ""))] += float(r.get("notional_usd", 0) or 0)

    total = sum(status.values())
    fill_rate = _pct(status.get("EXECUTED", 0), total)

    model_rows, model_summary = _build_modelability_dataset(orders, trades)

    out_dir = Path("artifacts/quant_model")
    out_dir.mkdir(parents=True, exist_ok=True)
    dataset_path = out_dir / "entry_model_dataset.jsonl"
    with dataset_path.open("w", encoding="utf-8") as f:
        for row in model_rows:
            f.write(json.dumps(row) + "\n")

    review = {
        "execution": {
            "total_events": total,
            "status_counts": dict(status),
            "fill_rate_percent": round(fill_rate, 2),
            "skip_reasons": dict(skip_reasons),
            "skip_reason_percent": {
                k: round(_pct(v, max(1, status.get("SKIP", 0))), 2) for k, v in skip_reasons.items()
            },
            "executed_by_symbol": dict(symbol_exec_count),
            "executed_notional_by_symbol_usd": {k: round(v, 2) for k, v in symbol_notional.items()},
            "risk_controls": exec_report.get("risk_controls", {}),
            "tuning_hints": _build_tuning_hints(skip_reasons, status.get("SKIP", 0)),
        },
        "modelability": model_summary,
        "artifacts": {
            "entry_model_dataset": str(dataset_path),
            "source_orders": str(orders_path),
            "source_execution_log": str(exec_log_path),
            "source_oos_report": str(oos_report_path),
        },
    }

    out_path = out_dir / "execution_review.json"
    out_path.write_text(json.dumps(review, indent=2), encoding="utf-8")
    print(json.dumps(review, indent=2))
    print(f"Review report -> {out_path}")


if __name__ == "__main__":
    main()

