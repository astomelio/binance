from __future__ import annotations

import argparse
import json
from pathlib import Path

from trading_lib.quant import build_labeled_rows, optimize_quant_model
from trading_lib.timeseries import load_jsonl_timeseries


def main() -> None:
    parser = argparse.ArgumentParser(description="Train quant baseline with walk-forward validation")
    parser.add_argument(
        "--dataset",
        default="/Users/joaquincano/data/binance_lake/gold/signals/decision_features_backfill",
        help="Path to decision features dataset directory",
    )
    parser.add_argument("--horizon", default="fwd_return_4h", choices=["fwd_return_1h", "fwd_return_4h", "fwd_return_24h"])
    parser.add_argument("--trials", type=int, default=120)
    args = parser.parse_args()

    data_glob = args.dataset
    if "*" not in data_glob:
        data_glob = f"{args.dataset}/**/part-*.jsonl"
    # Load multi-timeframe
    from pathlib import Path
    base_path = Path(args.dataset).parent if Path(args.dataset).is_file() else Path(args.dataset)
    
    rows_1h = load_jsonl_timeseries(data_glob, key_fields=("event_time", "symbol"))
    
    path_4h = str(base_path).replace("decision_features_backfill", "decision_features_backfill_4h")
    path_1d = str(base_path).replace("decision_features_backfill", "decision_features_backfill_1d")
    
    rows_4h = None
    if Path(path_4h).exists():
        try:
            rows_4h = load_jsonl_timeseries(f"{path_4h}/**/part-*.jsonl", key_fields=("event_time", "symbol"))
        except:
            pass
    
    rows_1d = None
    if Path(path_1d).exists():
        try:
            rows_1d = load_jsonl_timeseries(f"{path_1d}/**/part-*.jsonl", key_fields=("event_time", "symbol"))
        except:
            pass
    
    labeled = build_labeled_rows(rows_1h, rows_4h=rows_4h, rows_1d=rows_1d)
    result = optimize_quant_model(labeled_rows=labeled, target_horizon=args.horizon, random_trials=args.trials)

    printable = {
        "horizon": args.horizon,
        "rows": len(labeled),
        "mean_net_return_percent": round(result.mean_net_return_percent, 4),
        "std_net_return_percent": round(result.std_net_return_percent, 4),
        "mean_win_rate": round(result.mean_win_rate, 2),
        "mean_sharpe_like": round(result.mean_sharpe_like, 4),
        "mean_trades": round(result.mean_trades, 2),
        "threshold": round(result.config.threshold, 4),
        "weights": {k: round(v, 4) for k, v in result.config.weights.items()},
        "folds": [
            {
                "split_index": f.split_index,
                "net_return_percent": round(f.net_return_percent, 4),
                "win_rate": round(f.win_rate, 2),
                "trades": f.trades,
                "sharpe_like": round(f.sharpe_like, 4),
            }
            for f in result.folds
        ],
    }
    print(json.dumps(printable, indent=2))

    out_path = Path("artifacts/quant_model/latest_walkforward_model.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(printable, indent=2), encoding="utf-8")
    print(f"\nSaved model artifact -> {out_path}")


if __name__ == "__main__":
    main()

