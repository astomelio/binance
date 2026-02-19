from __future__ import annotations

import argparse
from pathlib import Path

from trading_lib import load_jsonl_timeseries
from trading_lib.quant import build_labeled_rows
from trading_lib.quant.train import optimize_quant_model


def main() -> None:
    parser = argparse.ArgumentParser(description="Train model with multi-timeframe features")
    parser.add_argument("--data-1h", required=True, help="Path to 1h decision_features")
    parser.add_argument("--data-4h", help="Path to 4h decision_features (optional)")
    parser.add_argument("--data-1d", help="Path to 1d decision_features (optional)")
    parser.add_argument("--horizon", default="fwd_return_4h", help="Target horizon")
    args = parser.parse_args()
    
    print("Loading 1h data...")
    rows_1h = load_jsonl_timeseries(
        args.data_1h if Path(args.data_1h).is_dir() else f"{args.data_1h}/**/*.jsonl",
        key_fields=("event_time", "symbol"),
    )
    print(f"Loaded {len(rows_1h)} 1h rows")
    
    rows_4h = None
    if args.data_4h:
        print("Loading 4h data...")
        rows_4h = load_jsonl_timeseries(
            args.data_4h if Path(args.data_4h).is_dir() else f"{args.data_4h}/**/*.jsonl",
            key_fields=("event_time", "symbol"),
        )
        print(f"Loaded {len(rows_4h)} 4h rows")
    
    rows_1d = None
    if args.data_1d:
        print("Loading 1d data...")
        rows_1d = load_jsonl_timeseries(
            args.data_1d if Path(args.data_1d).is_dir() else f"{args.data_1d}/**/*.jsonl",
            key_fields=("event_time", "symbol"),
        )
        print(f"Loaded {len(rows_1d)} 1d rows")
    
    print("Building labeled rows with multi-timeframe features...")
    labeled_rows = build_labeled_rows(rows_1h, rows_4h=rows_4h, rows_1d=rows_1d)
    print(f"Built {len(labeled_rows)} labeled rows")
    
    print("Training model...")
    result = optimize_quant_model(
        labeled_rows,
        target_horizon=args.horizon,
        train_days=60,
        test_days=14,
        step_days=14,
    )
    
    print(f"\nBest model:")
    print(f"  Net return: {result.mean_net_return_percent:.4f}%")
    print(f"  Win rate: {result.mean_win_rate:.2f}%")
    print(f"  Sharpe-like: {result.mean_sharpe_like:.4f}")


if __name__ == "__main__":
    main()
