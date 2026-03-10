#!/usr/bin/env python3
"""Listar símbolos: los configurados o todos los USDT perpetual de Binance."""
import argparse
from data_platform.symbols import fetch_usdt_perpetual_symbols, resolve_symbols


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--all", action="store_true", help="Fetch todos los USDT perpetual de Binance")
    p.add_argument("--env", action="store_true", help="Usar DP_SYMBOLS del env (default)")
    args = p.parse_args()

    if args.all:
        symbols = fetch_usdt_perpetual_symbols()
        print(f"Binance USDT perpetual: {len(symbols)} símbolos")
    else:
        import os
        raw = os.getenv("DP_SYMBOLS", "all")
        symbols = resolve_symbols(raw)
        print(f"DP_SYMBOLS={raw} -> {len(symbols)} símbolos")
    for s in symbols:
        print(s)


if __name__ == "__main__":
    main()
