#!/usr/bin/env python3
"""Predicción para símbolo. Lee de DuckDB."""
import argparse
from ai.inference.predictor import predict


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--symbol", default="BTCUSDT")
    p.add_argument("--horizon", default="4h")
    args = p.parse_args()

    out = predict(symbol=args.symbol, horizon=args.horizon)
    print(out)


if __name__ == "__main__":
    main()
