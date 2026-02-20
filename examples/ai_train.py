#!/usr/bin/env python3
"""Entrenar modelo: walk-forward + calibration. Lee de DuckDB."""
import argparse
from ai.training.pipeline import run_training


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--horizon", default="4h", choices=["1h", "4h", "24h"])
    p.add_argument("--train-days", type=int, default=90)
    p.add_argument("--test-days", type=int, default=14)
    p.add_argument("--step-days", type=int, default=14)
    p.add_argument("--embargo-hours", type=int, default=12)
    args = p.parse_args()

    r = run_training(
        horizon=args.horizon,
        train_days=args.train_days,
        test_days=args.test_days,
        step_days=args.step_days,
        embargo_hours=args.embargo_hours,
    )
    print(f"Run: {r.run_id}")
    print(f"Calibration: {r.calibration_path}")
    print(f"Threshold: {r.prob_threshold:.2f} | Sharpe-like: {r.sharpe_like:.4f} | Trades: {r.trades} | WinRate: {r.win_rate:.1f}%")


if __name__ == "__main__":
    main()
