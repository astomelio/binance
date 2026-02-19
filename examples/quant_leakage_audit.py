from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Sequence

from trading_lib.timeseries import load_jsonl_timeseries


def _pct_change(series: Sequence[float], idx: int, steps_back: int) -> float:
    if idx < steps_back:
        return 0.0
    prev = float(series[idx - steps_back])
    curr = float(series[idx])
    if prev == 0:
        return 0.0
    return ((curr - prev) / prev) * 100.0


def _mean_abs(values: List[float]) -> float:
    if not values:
        return 0.0
    return sum(abs(v) for v in values) / len(values)


def main() -> None:
    parser = argparse.ArgumentParser(description="Leakage audit for quant features")
    parser.add_argument("--dataset", default="/Users/joaquincano/data/binance_lake/gold/signals/decision_features_backfill")
    parser.add_argument("--print-json", action="store_true", help="Also print full JSON report to stdout")
    args = parser.parse_args()

    data_glob = args.dataset if "*" in args.dataset else f"{args.dataset}/**/part-*.jsonl"
    rows = load_jsonl_timeseries(data_glob, key_fields=("event_time", "symbol"))
    if not rows:
        raise ValueError(f"No rows found: {data_glob}")

    columns = sorted({k for r in rows for k in r.keys()})
    suspicious_prefixes = ("fwd_", "future_", "target", "label", "y_", "next_")
    suspicious_cols = [c for c in columns if c.lower().startswith(suspicious_prefixes) or c.lower() in {"label", "target"}]

    by_symbol: Dict[str, List[Dict]] = defaultdict(list)
    for r in rows:
        s = str(r.get("symbol", ""))
        if s:
            by_symbol[s].append(r)

    momentum3_err: List[float] = []
    momentum12_err: List[float] = []
    p24_err: List[float] = []
    checked_rows = 0

    for symbol, srows in by_symbol.items():
        srows.sort(key=lambda x: x["event_time"])
        closes = [float(r.get("futures_last_price", 0.0) or 0.0) for r in srows]
        for i, r in enumerate(srows):
            checked_rows += 1
            m3_recalc = _pct_change(closes, i, 3)
            m12_recalc = _pct_change(closes, i, 12)
            p24_recalc = _pct_change(closes, i, 24)
            momentum3_err.append(float(r.get("momentum_3", 0.0) or 0.0) - m3_recalc)
            momentum12_err.append(float(r.get("momentum_12", 0.0) or 0.0) - m12_recalc)
            # price_change_percent_24h can be externally sourced in live ETL, but on backfill it is recomputed.
            p24_err.append(float(r.get("price_change_percent_24h", 0.0) or 0.0) - p24_recalc)

    report = {
        "dataset": data_glob,
        "rows": len(rows),
        "symbols": sorted(list(by_symbol.keys())),
        "columns_count": len(columns),
        "suspicious_columns": suspicious_cols,
        "causality_checks": {
            "checked_rows": checked_rows,
            "momentum_3_mae": round(_mean_abs(momentum3_err), 10),
            "momentum_12_mae": round(_mean_abs(momentum12_err), 10),
            "price_change_24h_mae": round(_mean_abs(p24_err), 10),
            "notes": [
                "momentum_3 and momentum_12 are recomputed from historical closes up to t (no future).",
                "price_change_percent_24h is expected to match backfill recomputation; live ETL may differ due to source definition.",
            ],
        },
        "leakage_policy": {
            "forbidden_feature_prefixes": list(suspicious_prefixes),
            "policy_regime_inputs": ["momentum_12", "price_change_percent_24h", "momentum_3", "liquidity_event_score"],
        },
    }

    out = Path("artifacts/quant_model/leakage_audit_report.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("=== Leakage Audit ===")
    print(f"dataset: {data_glob}")
    print(f"rows: {report['rows']} | symbols: {', '.join(report['symbols'])}")
    print(f"suspicious_columns: {len(report['suspicious_columns'])} -> {report['suspicious_columns']}")
    c = report["causality_checks"]
    print(
        "causality_mae | "
        f"momentum_3={c['momentum_3_mae']} | "
        f"momentum_12={c['momentum_12_mae']} | "
        f"price_change_24h={c['price_change_24h_mae']}"
    )
    if args.print_json:
        print(json.dumps(report, indent=2))
    print(f"Saved leakage audit -> {out}")


if __name__ == "__main__":
    main()

