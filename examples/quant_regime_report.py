from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Tuple

from trading_lib.timeseries import load_jsonl_timeseries


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
    if m3_abs >= 1.5 or liq >= 0.5:
        return "HIGH_VOL"
    return "LOW_VOL"


def _compute_mdd(weighted_returns_pct: List[float]) -> float:
    if not weighted_returns_pct:
        return 0.0
    eq = 1.0
    peak = 1.0
    mdd = 0.0
    for r in weighted_returns_pct:
        eq *= 1 + (r / 100.0)
        if eq > peak:
            peak = eq
        dd = ((peak - eq) / peak) * 100.0
        if dd > mdd:
            mdd = dd
    return mdd


def _summarize(trades: List[Dict]) -> Dict:
    if not trades:
        return {
            "trades": 0,
            "win_rate_percent": 0.0,
            "net_return_percent": 0.0,
            "avg_trade_return_percent": 0.0,
            "mdd_percent": 0.0,
        }
    weighted = [float(t.get("weighted_net_pnl_percent", 0.0) or 0.0) for t in trades]
    wins = sum(1 for x in weighted if x > 0)
    return {
        "trades": len(trades),
        "win_rate_percent": round((wins / len(trades)) * 100.0, 2),
        "net_return_percent": round(sum(weighted), 5),
        "avg_trade_return_percent": round(sum(weighted) / len(weighted), 5),
        "mdd_percent": round(_compute_mdd(weighted), 5),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build regime-level OOS performance report")
    parser.add_argument(
        "--dataset",
        default="/Users/joaquincano/data/binance_lake/gold/signals/decision_features_backfill",
        help="Path to decision features directory or glob",
    )
    parser.add_argument("--oos-report", default="artifacts/quant_model/oos_report.json")
    parser.add_argument("--oos-days", type=int, default=14)
    args = parser.parse_args()

    data_glob = args.dataset if "*" in args.dataset else f"{args.dataset}/**/part-*.jsonl"
    rows = load_jsonl_timeseries(data_glob, key_fields=("event_time", "symbol"))
    if not rows:
        raise ValueError(f"No rows found for dataset: {data_glob}")

    max_ts = _parse_iso(rows[-1]["event_time"])
    cutoff = max_ts - timedelta(days=args.oos_days)
    oos_rows = [r for r in rows if _parse_iso(r["event_time"]) >= cutoff]
    row_idx = {(str(r.get("symbol", "")), str(r.get("event_time", ""))): r for r in oos_rows}

    report = json.loads(Path(args.oos_report).read_text(encoding="utf-8"))
    trades: List[Dict] = report.get("trades", [])

    by_regime: Dict[str, List[Dict]] = defaultdict(list)
    by_vol: Dict[str, List[Dict]] = defaultdict(list)
    by_combo: Dict[str, List[Dict]] = defaultdict(list)

    for t in trades:
        symbol = str(t.get("symbol", ""))
        entry_time = str(t.get("entry_time", ""))
        row = row_idx.get((symbol, entry_time))
        if not row:
            continue
        regime = _regime_label(row)
        vol = _vol_label(row)
        by_regime[regime].append(t)
        by_vol[vol].append(t)
        by_combo[f"{regime}__{vol}"].append(t)

    out = {
        "source_oos_report": args.oos_report,
        "dataset": data_glob,
        "oos_days": args.oos_days,
        "overall": _summarize(trades),
        "by_regime": {k: _summarize(v) for k, v in sorted(by_regime.items())},
        "by_volatility": {k: _summarize(v) for k, v in sorted(by_vol.items())},
        "by_regime_and_volatility": {k: _summarize(v) for k, v in sorted(by_combo.items())},
    }

    out_path = Path("artifacts/quant_model/oos_regime_report.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")

    print(json.dumps(out, indent=2))
    print(f"Saved regime report -> {out_path}")


if __name__ == "__main__":
    main()

